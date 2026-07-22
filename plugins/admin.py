import asyncio
from datetime import datetime, timezone

from pyrogram import Client, filters, enums

from config import (
    ADMIN_IDS, VIDEO_CHANNEL_ID, LOG_GROUP_ID,
    CONTROL_GROUP_ID, VIDEO_DAILY_LIMIT, GROUP_VIDEO_LIMIT, OWNER_ID,
)
from database import users, videos, groups, banned_users, custom_access
from helpers import get_current_window_start


def _log_error(context: str, exc: Exception):
    print(f"[LOG-SEND-FAILED] {context}: {exc!r}")


# Allow admin commands from PM *or* control group
def _admin_filter():
    base = filters.user(ADMIN_IDS)
    if CONTROL_GROUP_ID:
        return base & (filters.private | filters.chat(CONTROL_GROUP_ID))
    return base & filters.private


_af = _admin_filter()


# ─── Admin sends/forwards video to bot PM → manual save ──────────────────────

@Client.on_message(filters.private & filters.user(ADMIN_IDS) & (filters.video | filters.document))
async def admin_save_video(client, message):
    file_id = None
    file_type = "video"
    duration = width = height = 0

    if message.video:
        v = message.video
        file_id  = v.file_id
        duration = v.duration or 0
        width    = v.width or 0
        height   = v.height or 0
    elif (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video/")
    ):
        try:
            tmp = await client.send_video(
                chat_id=LOG_GROUP_ID, video=message.document.file_id, caption="",
            )
            file_id  = tmp.video.file_id
            duration = tmp.video.duration or 0
            width    = tmp.video.width or 0
            height   = tmp.video.height or 0
            await tmp.delete()
        except Exception:
            file_id   = message.document.file_id
            file_type = "document"
    else:
        return

    count_before = await videos.count_documents({})
    await videos.insert_one({
        "file_id":   file_id,
        "file_type": file_type,
        "duration":  duration,
        "width":     width,
        "height":    height,
        "added_at":  datetime.now(timezone.utc),
    })
    total = await videos.count_documents({})

    if count_before == 0 and total > 0:
        asyncio.create_task(_notify_users_videos_available(client))

    tag = "✅ Spoiler-capable" if file_type == "video" else "⚠️ Document"
    if LOG_GROUP_ID:
        try:
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=f"🎬 <b>New Video (Manual)</b>\n\n📦 Total: <b>{total}</b>\n🎭 {tag}",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            _log_error("admin_save_video", e)

    await message.reply_text(
        f"✅ Saved. Library: <b>{total}</b> videos", parse_mode=enums.ParseMode.HTML,
    )


async def _notify_users_videos_available(client):
    all_users = await users.find({}, {"user_id": 1}).to_list(length=None)
    for u in all_users:
        try:
            await client.send_message(
                chat_id=u["user_id"],
                text="🎬 <b>নতুন ভিডিও এসেছে!</b>\n\n/video দিয়ে এখনই দেখুন 🔥",
                parse_mode=enums.ParseMode.HTML,
            )
            await asyncio.sleep(0.1)
        except Exception:
            pass


# ─── /ban ─────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("ban") & _af)
async def ban_user(client, message):
    target_id = None
    reason = "No reason provided"

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        args = message.text.split(None, 1)
        if len(args) > 1:
            reason = args[1].strip()
    else:
        parts = message.text.split(None, 2)
        if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
            await message.reply_text(
                "❌ Usage: /ban &lt;user_id&gt; [reason]\nOr reply to a message.",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        target_id = int(parts[1])
        if len(parts) > 2:
            reason = parts[2].strip()

    if target_id in ADMIN_IDS:
        await message.reply_text("⚠️ Admin-কে ban করা যাবে না।")
        return

    existing = await banned_users.find_one({"user_id": target_id})
    if existing:
        await message.reply_text(f"⚠️ User <code>{target_id}</code> আগেই banned।", parse_mode=enums.ParseMode.HTML)
        return

    await banned_users.insert_one({
        "user_id":   target_id,
        "reason":    reason,
        "banned_by": message.from_user.id,
        "banned_at": datetime.now(timezone.utc),
    })

    try:
        await client.send_message(
            chat_id=target_id,
            text=f"🚫 <b>আপনাকে ban করা হয়েছে।</b>\n\n📝 কারণ: {reason}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(
        f"✅ <code>{target_id}</code> ban হয়েছে।\n📝 {reason}",
        parse_mode=enums.ParseMode.HTML,
    )
    if LOG_GROUP_ID:
        try:
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=(
                    f"🚫 <b>User Banned</b>\n🆔 <code>{target_id}</code>\n"
                    f"👮 By: <code>{message.from_user.id}</code>\n📝 {reason}"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            _log_error("ban_user log", e)


# ─── /unban ───────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("unban") & _af)
async def unban_user(client, message):
    target_id = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip().lstrip("-").isdigit():
            await message.reply_text(
                "❌ Usage: /unban &lt;user_id&gt;", parse_mode=enums.ParseMode.HTML,
            )
            return
        target_id = int(parts[1])

    result = await banned_users.delete_one({"user_id": target_id})
    if result.deleted_count == 0:
        await message.reply_text(f"⚠️ <code>{target_id}</code> banned নেই।", parse_mode=enums.ParseMode.HTML)
        return

    try:
        await client.send_message(
            chat_id=target_id,
            text="✅ <b>আপনার ban তুলে নেওয়া হয়েছে।</b>\nএখন /video দিয়ে দেখুন। 🎬",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(
        f"✅ <code>{target_id}</code> unban হয়েছে।", parse_mode=enums.ParseMode.HTML,
    )
    if LOG_GROUP_ID:
        try:
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=f"✅ <b>User Unbanned</b>\n🆔 <code>{target_id}</code>\n👮 By: <code>{message.from_user.id}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            _log_error("unban_user log", e)


# ─── /banlist ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("banlist") & _af)
async def banlist(client, message):
    banned = await banned_users.find({}).to_list(length=None)
    if not banned:
        await message.reply_text("✅ কোনো banned user নেই।")
        return
    lines = []
    for i, doc in enumerate(banned, 1):
        uid      = doc.get("user_id")
        reason   = doc.get("reason", "—")
        date_str = doc.get("banned_at", "").strftime("%d %b %Y") if doc.get("banned_at") else "?"
        lines.append(f"{i}. <code>{uid}</code> — {reason} ({date_str})")
    await message.reply_text(
        f"🚫 <b>Banned Users ({len(banned)})</b>\n━━━━━━━━━━━\n" + "\n".join(lines),
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /giveaccess — custom video limit or unlimited ───────────────────────────

@Client.on_message(filters.command("giveaccess") & _af)
async def give_access(client, message):
    """
    /giveaccess <user_id> unlimited   — unlimited videos
    /giveaccess <user_id> 25          — 25 videos per 12-hour window
    /giveaccess <user_id> 0           — remove special access (back to default)
    """
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        await message.reply_text(
            "❌ <b>Usage:</b>\n"
            "/giveaccess &lt;user_id&gt; unlimited\n"
            "/giveaccess &lt;user_id&gt; 25\n"
            "/giveaccess &lt;user_id&gt; 0  ← remove access",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    raw_id, raw_limit = parts[1].strip(), parts[2].strip().lower()
    if not raw_id.lstrip("-").isdigit():
        await message.reply_text("❌ Invalid user ID.", parse_mode=enums.ParseMode.HTML)
        return

    target_id = int(raw_id)

    if raw_limit in ("unlimited", "ul", "∞"):
        limit_val = -1   # -1 means unlimited
        label     = "Unlimited ∞"
    elif raw_limit.isdigit():
        limit_val = int(raw_limit)
        label     = str(limit_val)
    else:
        await message.reply_text("❌ Limit must be a number or 'unlimited'.")
        return

    if limit_val == 0:
        await custom_access.delete_one({"user_id": target_id})
        await message.reply_text(
            f"✅ <code>{target_id}</code>-এর special access সরানো হয়েছে।\n"
            f"Default limit ({VIDEO_DAILY_LIMIT}) প্রযোজ্য হবে।",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    await custom_access.update_one(
        {"user_id": target_id},
        {"$set": {
            "user_id":    target_id,
            "limit":      limit_val,
            "given_by":   message.from_user.id,
            "given_at":   datetime.now(timezone.utc),
        }},
        upsert=True,
    )

    await message.reply_text(
        f"✅ <code>{target_id}</code>-কে <b>{label}</b> access দেওয়া হয়েছে।",
        parse_mode=enums.ParseMode.HTML,
    )

    # Notify the user
    try:
        msg = (
            "🎉 <b>আপনাকে Unlimited access দেওয়া হয়েছে!</b>\n\nযত খুশি ভিডিও দেখুন 🎬"
            if limit_val == -1
            else f"🎉 <b>আপনার video limit বাড়ানো হয়েছে!</b>\n\nএখন প্রতি ১২ ঘণ্টায় <b>{label}</b>টি ভিডিও দেখতে পারবেন। 🎬"
        )
        await client.send_message(chat_id=target_id, text=msg, parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass


# ─── /accesslist — list users with custom access ─────────────────────────────

@Client.on_message(filters.command("accesslist") & _af)
async def access_list(client, message):
    docs = await custom_access.find({}).to_list(length=None)
    if not docs:
        await message.reply_text("ℹ️ কোনো custom access দেওয়া নেই।")
        return
    lines = []
    for i, doc in enumerate(docs, 1):
        uid   = doc.get("user_id")
        lim   = doc.get("limit", 0)
        label = "∞ Unlimited" if lim == -1 else str(lim)
        dt    = doc.get("given_at")
        date  = dt.strftime("%d %b %Y") if dt else "?"
        lines.append(f"{i}. <code>{uid}</code> — {label} ({date})")
    await message.reply_text(
        f"🔑 <b>Custom Access List ({len(docs)})</b>\n━━━━━━━━━━━\n" + "\n".join(lines),
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /addvideo — add by replying ──────────────────────────────────────────────

@Client.on_message(filters.command("addvideo") & _af)
async def addvideo(client, message):
    if not message.reply_to_message:
        await message.reply_text("❌ একটি ভিডিওতে reply করে /addvideo লিখুন।")
        return

    reply     = message.reply_to_message
    file_id   = None
    file_type = "video"
    duration  = width = height = 0

    if reply.video:
        v        = reply.video
        file_id  = v.file_id
        duration = v.duration or 0
        width    = v.width or 0
        height   = v.height or 0
    elif reply.document and reply.document.mime_type and reply.document.mime_type.startswith("video/"):
        try:
            tmp      = await client.send_video(chat_id=LOG_GROUP_ID, video=reply.document.file_id, caption="")
            file_id  = tmp.video.file_id
            duration = tmp.video.duration or 0
            width    = tmp.video.width or 0
            height   = tmp.video.height or 0
            await tmp.delete()
        except Exception:
            file_id   = reply.document.file_id
            file_type = "document"
    else:
        await message.reply_text("❌ Reply করা message-এ কোনো ভিডিও নেই।")
        return

    if await videos.find_one({"file_id": file_id}):
        await message.reply_text("⚠️ এই ভিডিও আগেই database-এ আছে।")
        return

    await videos.insert_one({
        "file_id":   file_id,
        "file_type": file_type,
        "duration":  duration,
        "width":     width,
        "height":    height,
        "added_at":  datetime.now(timezone.utc),
    })
    total = await videos.count_documents({})
    await message.reply_text(
        f"✅ Video saved! Library: <b>{total}</b>", parse_mode=enums.ParseMode.HTML,
    )


# ─── /delvideo — delete N random videos ──────────────────────────────────────

@Client.on_message(filters.command("delvideo") & _af)
async def delvideo(client, message):
    parts = message.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply_text("❌ Usage: /delvideo &lt;number&gt;", parse_mode=enums.ParseMode.HTML)
        return
    n     = int(parts[1])
    total = await videos.count_documents({})
    if n > total:
        await message.reply_text(f"⚠️ Database-এ মাত্র {total}টি ভিডিও আছে।")
        return
    docs    = await videos.aggregate([{"$sample": {"size": n}}]).to_list(length=n)
    ids     = [d["_id"] for d in docs]
    result  = await videos.delete_many({"_id": {"$in": ids}})
    new_tot = await videos.count_documents({})
    await message.reply_text(
        f"🗑 <b>{result.deleted_count}</b>টি ভিডিও মুছে ফেলা হয়েছে।\n📦 বাকি: <b>{new_tot}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /stats ───────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("stats") & _af)
async def stats(client, message):
    total_users  = await users.count_documents({})
    total_videos = await videos.count_documents({})
    total_groups = await groups.count_documents({})
    total_banned = await banned_users.count_documents({})
    total_access = await custom_access.count_documents({})

    # New users today (UTC)
    from datetime import timedelta
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    new_today   = await users.count_documents({"joined_at": {"$gte": today_start}})

    # Videos watched today (from user_video_history)
    from database import user_video_history
    watched_today = await user_video_history.count_documents({"sent_at": {"$gte": today_start}})

    now = datetime.now(timezone.utc)
    await message.reply_text(
        "📊 <b>Bot Statistics</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users:     <b>{total_users}</b>\n"
        f"🆕 New Today:       <b>{new_today}</b>\n"
        f"🎬 Total Videos:    <b>{total_videos}</b>\n"
        f"▶️ Watched Today:   <b>{watched_today}</b>\n"
        f"🏘 Total Groups:    <b>{total_groups}</b>\n"
        f"🚫 Banned:          <b>{total_banned}</b>\n"
        f"🔑 Custom Access:   <b>{total_access}</b>\n\n"
        f"🕐 {now.strftime('%d %b %Y, %I:%M %p')} UTC",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /notifyusers ─────────────────────────────────────────────────────────────

@Client.on_message(filters.command("notifyusers") & _af)
async def notifyusers(client, message):
    all_users = await users.find({}, {"user_id": 1}).to_list(length=None)
    if not all_users:
        await message.reply_text("No users yet.")
        return
    status_msg = await message.reply_text(f"📡 Notifying {len(all_users)} users…")
    success = failed = 0
    for u in all_users:
        try:
            await client.send_message(
                chat_id=u["user_id"],
                text="🎬 <b>নতুন ভিডিও যোগ হয়েছে!</b>\n\n/video দিয়ে এখনই দেখুন 🔥",
                parse_mode=enums.ParseMode.HTML,
            )
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"✅ Done! ✅ {success}  ❌ {failed}")


# ─── /broadcast ───────────────────────────────────────────────────────────────
# Usage:
#   /broadcast         → everyone (users + groups)
#   /broadcast users   → only private users
#   /broadcast groups  → only groups

@Client.on_message(filters.command("broadcast") & _af)
async def broadcast_cmd(client, message):
    if not message.reply_to_message:
        await message.reply_text(
            "❌ <b>Usage:</b> কোনো message-এ reply করে লিখুন:\n\n"
            "/broadcast          — সবাইকে (users + groups)\n"
            "/broadcast users    — শুধু users\n"
            "/broadcast groups   — শুধু groups",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    args   = message.text.split(None, 1)
    target = args[1].strip().lower() if len(args) > 1 else "all"

    send_users  = target in ("all", "users")
    send_groups = target in ("all", "groups")

    all_users       = await users.find({}, {"user_id": 1}).to_list(length=None) if send_users else []
    all_group_docs  = await groups.find({}, {"group_id": 1}).to_list(length=None) if send_groups else []

    label = {"all": "Everyone", "users": "Users only", "groups": "Groups only"}.get(target, "Everyone")
    status_msg = await message.reply_text(
        f"📡 <b>Broadcasting…</b>\n"
        f"🎯 Target: <b>{label}</b>\n"
        f"👥 Users: {len(all_users)}  🏘 Groups: {len(all_group_docs)}",
        parse_mode=enums.ParseMode.HTML,
    )

    u_ok = u_fail = g_ok = g_fail = 0

    for ud in all_users:
        try:
            await client.copy_message(
                chat_id=ud["user_id"],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.id,
            )
            u_ok += 1
        except Exception:
            u_fail += 1
        await asyncio.sleep(0.05)

    for gd in all_group_docs:
        try:
            await client.copy_message(
                chat_id=gd["group_id"],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.id,
            )
            g_ok += 1
        except Exception:
            g_fail += 1
        await asyncio.sleep(0.05)

    result_text = (
        "✅ <b>Broadcast complete!</b>\n\n"
        f"🎯 Target: <b>{label}</b>\n"
    )
    if send_users:
        result_text += f"👥 Users   — ✅ {u_ok}  ❌ {u_fail}\n"
    if send_groups:
        result_text += f"🏘 Groups  — ✅ {g_ok}  ❌ {g_fail}\n"

    await status_msg.edit_text(result_text, parse_mode=enums.ParseMode.HTML)

    # Also notify control group if broadcast was not sent from there
    if CONTROL_GROUP_ID and message.chat.id != CONTROL_GROUP_ID:
        try:
            await client.send_message(
                chat_id=CONTROL_GROUP_ID,
                text=result_text,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass


# ─── /cmdlist ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("cmdlist") & _af)
async def cmdlist(client, message):
    await message.reply_text(
        "📋 <b>All Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 <b>User:</b>\n"
        "/start — Bot শুরু\n"
        "/help — Help\n"
        "/video — ভিডিও পান 🎬\n"
        "/profile — প্রোফাইল\n\n"
        "🔑 <b>Admin:</b>\n"
        "/stats — Statistics\n"
        "/broadcast [users|groups] — Message পাঠান\n"
        "/notifyusers — Video notification\n"
        "/addvideo — ভিডিও যোগ (reply করে)\n"
        "/delvideo &lt;n&gt; — ভিডিও মুছুন\n"
        "/ban &lt;id&gt; [reason] — Ban\n"
        "/unban &lt;id&gt; — Unban\n"
        "/banlist — Ban তালিকা\n"
        "/giveaccess &lt;id&gt; &lt;n|unlimited&gt; — Custom limit\n"
        "/accesslist — Custom access তালিকা\n"
        "/cmdlist — এই তালিকা\n\n"
        f"🎬 PM limit: <b>{VIDEO_DAILY_LIMIT}</b>/12h  "
        f"🏘 Group limit: <b>{GROUP_VIDEO_LIMIT}</b>/12h",
        parse_mode=enums.ParseMode.HTML,
    )
