import asyncio
from datetime import datetime, timezone

from pyrogram import Client, filters, enums

from config import ADMIN_IDS, VIDEO_CHANNEL_ID, LOG_GROUP_ID, VIDEO_DAILY_LIMIT, GROUP_VIDEO_LIMIT, OWNER_ID
from database import users, videos, groups, banned_users
from helpers import get_current_window_start


def _log_error(context: str, exc: Exception):
    print(f"[LOG-SEND-FAILED] {context}: {exc!r}")


# ─── Admin sends/forwards any video to the bot PM → manual save ──────────────

@Client.on_message(
    filters.private
    & filters.user(ADMIN_IDS)
    & (filters.video | filters.document)
)
async def admin_save_video(client, message):
    """Admin sends/forwards any video to the bot PM → stored by file_id."""
    file_id = None
    file_type = "video"
    duration = width = height = 0
    if message.video:
        v = message.video
        file_id = v.file_id
        duration = v.duration or 0
        width = v.width or 0
        height = v.height or 0

    elif (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video/")
    ):
        try:
            tmp = await client.send_video(
                chat_id=LOG_GROUP_ID,
                video=message.document.file_id,
                caption="",
            )
            file_id = tmp.video.file_id
            duration = tmp.video.duration or 0
            width = tmp.video.width or 0
            height = tmp.video.height or 0
            await tmp.delete()
        except Exception:
            file_id = message.document.file_id
            file_type = "document"
    else:
        return

    count_before = await videos.count_documents({})

    await videos.insert_one({
        "file_id": file_id,
        "file_type": file_type,
        "duration": duration,
        "width": width,
        "height": height,
        "added_at": datetime.now(timezone.utc),
    })

    total = await videos.count_documents({})

    if count_before == 0 and total > 0:
        asyncio.create_task(_notify_users_videos_available(client))

    spoiler_note = "✅ Spoiler-capable" if file_type == "video" else "⚠️ Document (no spoiler)"
    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=(
                "🎬 <b>New Video Added (Manual)</b>\n\n"
                f"📦 Total videos in DB: <b>{total}</b>\n"
                f"🎭 Type: {spoiler_note}"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        _log_error("admin_save_video new-video notice", e)

    await message.reply_text(
        f"✅ Saved. Total videos in library: <b>{total}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


async def _notify_users_videos_available(client):
    all_users = await users.find({}, {"user_id": 1}).to_list(length=None)
    for u in all_users:
        try:
            await client.send_message(
                chat_id=u["user_id"],
                text=(
                    "🎬 <b>Videos are now available!</b>\n\n"
                    "The video library just got stocked. Use /video to watch! 🔥"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
            await asyncio.sleep(0.1)
        except Exception:
            pass


# ─── /ban — ban a user ────────────────────────────────────────────────────────

@Client.on_message(filters.command("ban") & filters.user(ADMIN_IDS))
async def ban_user(client, message):
    """
    Ban a user from using the bot.
    Usage: /ban <user_id> [reason]
    Or reply to a user's message with /ban [reason]
    """
    target_id = None
    reason = "No reason provided"

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        args = message.text.split(None, 1)
        if len(args) > 1:
            reason = args[1].strip()
    else:
        args = message.text.split(None, 2)
        if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
            await message.reply_text(
                "❌ <b>Usage:</b>\n"
                "/ban &lt;user_id&gt; [reason]\n"
                "or reply to a message with /ban [reason]",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        target_id = int(args[1])
        reason = args[2].strip() if len(args) > 2 else "No reason provided"

    if target_id in ADMIN_IDS:
        await message.reply_text("❌ Admin-কে ban করা যাবে না।")
        return

    existing = await banned_users.find_one({"user_id": target_id})
    if existing:
        await message.reply_text(f"⚠️ User <code>{target_id}</code> ইতিমধ্যে ban করা আছে।", parse_mode=enums.ParseMode.HTML)
        return

    await banned_users.insert_one({
        "user_id": target_id,
        "reason": reason,
        "banned_by": message.from_user.id,
        "banned_at": datetime.now(timezone.utc),
    })

    # Try to notify the banned user
    try:
        await client.send_message(
            chat_id=target_id,
            text=(
                "🚫 <b>আপনাকে ban করা হয়েছে।</b>\n\n"
                f"📝 কারণ: {reason}\n\n"
                "আপনি আর ভিডিও পাবেন না।"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(
        f"✅ User <code>{target_id}</code> ban করা হয়েছে।\n"
        f"📝 কারণ: {reason}",
        parse_mode=enums.ParseMode.HTML,
    )

    if LOG_GROUP_ID:
        try:
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=(
                    "🚫 <b>User Banned</b>\n\n"
                    f"🆔 User ID: <code>{target_id}</code>\n"
                    f"👮 Banned by: <code>{message.from_user.id}</code>\n"
                    f"📝 Reason: {reason}"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            _log_error("ban_user log", e)


# ─── /unban — unban a user ────────────────────────────────────────────────────

@Client.on_message(filters.command("unban") & filters.user(ADMIN_IDS))
async def unban_user(client, message):
    """
    Unban a previously banned user.
    Usage: /unban <user_id>
    Or reply to a message with /unban
    """
    target_id = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split(None, 1)
        if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
            await message.reply_text(
                "❌ <b>Usage:</b> /unban &lt;user_id&gt;\n"
                "or reply to a message with /unban",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        target_id = int(args[1])

    result = await banned_users.delete_one({"user_id": target_id})

    if result.deleted_count == 0:
        await message.reply_text(f"⚠️ User <code>{target_id}</code> ban তালিকায় নেই।", parse_mode=enums.ParseMode.HTML)
        return

    # Notify the user
    try:
        await client.send_message(
            chat_id=target_id,
            text=(
                "✅ <b>আপনার ban তুলে নেওয়া হয়েছে।</b>\n\n"
                "এখন আবার /video দিয়ে ভিডিও দেখতে পারবেন। 🎬"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(
        f"✅ User <code>{target_id}</code> এর ban তুলে নেওয়া হয়েছে।",
        parse_mode=enums.ParseMode.HTML,
    )

    if LOG_GROUP_ID:
        try:
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=(
                    "✅ <b>User Unbanned</b>\n\n"
                    f"🆔 User ID: <code>{target_id}</code>\n"
                    f"👮 Unbanned by: <code>{message.from_user.id}</code>"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            _log_error("unban_user log", e)


# ─── /banlist — show all banned users ────────────────────────────────────────

@Client.on_message(filters.command("banlist") & filters.user(ADMIN_IDS))
async def banlist(client, message):
    """Show all currently banned users."""
    banned = await banned_users.find({}).to_list(length=None)

    if not banned:
        await message.reply_text("✅ এখন কোনো banned user নেই।")
        return

    lines = []
    for i, doc in enumerate(banned, 1):
        uid = doc.get("user_id")
        reason = doc.get("reason", "—")
        banned_at = doc.get("banned_at")
        date_str = banned_at.strftime("%d %b %Y") if banned_at else "?"
        lines.append(f"{i}. <code>{uid}</code> — {reason} ({date_str})")

    text = (
        f"🚫 <b>Banned Users ({len(banned)} জন)</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(lines)
    )
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)


# ─── /addvideo — add a video by replying ─────────────────────────────────────

@Client.on_message(filters.command("addvideo") & filters.user(ADMIN_IDS))
async def addvideo(client, message):
    if not message.reply_to_message:
        await message.reply_text("❌ একটি ভিডিওতে reply করে /addvideo লিখুন।")
        return

    reply = message.reply_to_message
    file_id = None
    file_type = "video"
    duration = width = height = 0
    if reply.video:
        v = reply.video
        file_id = v.file_id
        duration = v.duration or 0
        width = v.width or 0
        height = v.height or 0
    elif reply.document and reply.document.mime_type and reply.document.mime_type.startswith("video/"):
        try:
            tmp = await client.send_video(chat_id=LOG_GROUP_ID, video=reply.document.file_id, caption="")
            file_id = tmp.video.file_id
            duration = tmp.video.duration or 0
            width = tmp.video.width or 0
            height = tmp.video.height or 0
            await tmp.delete()
        except Exception:
            file_id = reply.document.file_id
            file_type = "document"
    else:
        await message.reply_text("❌ Reply করা message-এ কোনো ভিডিও নেই।")
        return

    existing = await videos.find_one({"file_id": file_id})
    if existing:
        await message.reply_text("⚠️ এই ভিডিও আগেই database-এ আছে।")
        return

    await videos.insert_one({
        "file_id": file_id,
        "file_type": file_type,
        "duration": duration,
        "width": width,
        "height": height,
        "added_at": datetime.now(timezone.utc),
    })

    total = await videos.count_documents({})
    await message.reply_text(
        f"✅ ভিডিও যোগ করা হয়েছে। মোট: <b>{total}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /delvideo — delete a video by index ─────────────────────────────────────

@Client.on_message(filters.command("delvideo") & filters.user(ADMIN_IDS))
async def delvideo(client, message):
    args = message.text.split(None, 1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.reply_text("❌ Usage: /delvideo &lt;number&gt;", parse_mode=enums.ParseMode.HTML)
        return

    index = int(args[1]) - 1
    all_videos = await videos.find({}).skip(index).limit(1).to_list(length=1)
    if not all_videos:
        await message.reply_text("❌ ওই নম্বরের ভিডিও পাওয়া যায়নি।")
        return

    await videos.delete_one({"_id": all_videos[0]["_id"]})
    total = await videos.count_documents({})
    await message.reply_text(
        f"✅ ভিডিও #{int(args[1])} মুছে ফেলা হয়েছে। মোট অবশিষ্ট: <b>{total}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /stats — bot statistics ──────────────────────────────────────────────────

@Client.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(client, message):
    total_users = await users.count_documents({})
    total_videos = await videos.count_documents({})
    total_groups = await groups.count_documents({})
    total_banned = await banned_users.count_documents({})

    now = datetime.now(timezone.utc)
    await message.reply_text(
        "📊 <b>Bot Statistics</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users: <b>{total_users}</b>\n"
        f"🎬 Total Videos: <b>{total_videos}</b>\n"
        f"🏘 Total Groups: <b>{total_groups}</b>\n"
        f"🚫 Banned Users: <b>{total_banned}</b>\n\n"
        f"🕐 Updated: {now.strftime('%d %b %Y, %I:%M %p')} UTC",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /notifyusers — notify all users ─────────────────────────────────────────

@Client.on_message(filters.command("notifyusers") & filters.user(ADMIN_IDS))
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
                text=(
                    "🎬 <b>নতুন ভিডিও যোগ হয়েছে!</b>\n\n"
                    "/video দিয়ে এখনই দেখুন 🔥"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ Done! ✅ {success}  ❌ {failed}",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /broadcast ───────────────────────────────────────────────────────────────

@Client.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast_cmd(client, message):
    if not message.reply_to_message:
        await message.reply_text(
            "❌ <b>Usage:</b> যেকোনো message-এ reply করে /broadcast লিখুন।",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    all_users = await users.find({}, {"user_id": 1}).to_list(length=None)
    all_group_docs = await groups.find({}, {"group_id": 1}).to_list(length=None)
    total = len(all_users)
    total_groups = len(all_group_docs)

    status_msg = await message.reply_text(
        f"📡 Broadcasting to <b>{total}</b> users and <b>{total_groups}</b> groups…",
        parse_mode=enums.ParseMode.HTML,
    )

    success = failed = 0
    for user_doc in all_users:
        try:
            await client.copy_message(
                chat_id=user_doc["user_id"],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.id,
            )
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.1)

    g_success = g_failed = 0
    for group_doc in all_group_docs:
        try:
            await client.copy_message(
                chat_id=group_doc["group_id"],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.id,
            )
            g_success += 1
        except Exception:
            g_failed += 1
        await asyncio.sleep(0.1)

    await status_msg.edit_text(
        "✅ <b>Broadcast complete!</b>\n\n"
        f"👥 Users — ✅ {success}  ❌ {failed}\n"
        f"🏘 Groups — ✅ {g_success}  ❌ {g_failed}",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /cmdlist — list of all commands ─────────────────────────────────────────

@Client.on_message(filters.command("cmdlist") & filters.user(ADMIN_IDS))
async def cmdlist(client, message):
    await message.reply_text(
        "📋 <b>All Commands</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "👤 <b>User Commands:</b>\n"
        "/start — Bot শুরু করুন\n"
        "/help — সাহায্য দেখুন\n"
        "/video — র‍্যান্ডম ভিডিও পান 🎬\n"
        "/profile — আপনার প্রোফাইল দেখুন\n\n"
        "🔑 <b>Admin Commands:</b>\n"
        "/stats — Bot-এর পরিসংখ্যান\n"
        "/broadcast — সবাইকে message পাঠান (reply করে)\n"
        "/notifyusers — ভিডিও নোটিফিকেশন পাঠান\n"
        "/addvideo — ভিডিও যোগ করুন (reply করে)\n"
        "/delvideo &lt;number&gt; — ভিডিও মুছুন\n"
        "/ban &lt;user_id&gt; [reason] — User ban করুন\n"
        "/unban &lt;user_id&gt; — User unban করুন\n"
        "/banlist — Banned user তালিকা\n"
        "/cmdlist — এই তালিকা\n\n"
        "⚙️ <b>Settings:</b>\n"
        f"🎬 PM video limit: <b>{VIDEO_DAILY_LIMIT}</b> per 12h\n"
        f"🏘 Group video limit: <b>{GROUP_VIDEO_LIMIT}</b> per 12h\n\n"
        "🔄 <b>Auto-Index:</b>\n"
        "Channel-এ video post করলে bot স্বয়ংক্রিয় save করবে।\n\n"
        "📩 <b>Support Inbox:</b>\n"
        "User message দিলে এখানে আসে। Reply করলে user পাবে। ✅",
        parse_mode=enums.ParseMode.HTML,
    )
