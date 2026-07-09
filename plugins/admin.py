import asyncio
from datetime import datetime, timezone

from pyrogram import Client, filters, enums

from config import ADMIN_IDS, VIDEO_CHANNEL_ID, LOG_GROUP_ID, VIDEO_DAILY_LIMIT, OWNER_ID
from database import users, videos, groups
from helpers import get_current_window_start


# ─── Admin sends/forwards any video to the bot PM → auto-save ────────────────

@Client.on_message(
    filters.private
    & filters.user(ADMIN_IDS)
    & (filters.video | filters.document)
)
async def admin_save_video(client, message):
    """
    Admin sends or forwards ANY video to the bot in PM → stored by file_id.
    Document-type videos are re-sent as proper video to obtain a spoiler-capable file_id.
    Save confirmation is sent to the monitor group only.
    """
    file_id = None
    file_type = "video"
    duration = width = height = 0
    caption = message.caption or ""

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
        "caption": caption,
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
                "🎬 <b>New Video Added</b>\n\n"
                f"📦 Total videos in DB: <b>{total}</b>\n"
                f"🎭 Type: {spoiler_note}\n"
                f"📝 Caption: {caption or '—'}"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text("✅ Saved.", parse_mode=enums.ParseMode.HTML)


async def _notify_users_videos_available(client):
    """Notify all users that the video library is now available.
    Fix: rate limiting রোধ করতে প্রতি মেসেজের পর পর্যাপ্ত বিরতি রাখা হয়েছে।
    Telegram প্রতি সেকেন্ডে সর্বোচ্চ ~30 মেসেজ পাঠাতে দেয়।
    """
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
            # Fix: 0.05 → 0.1 সেকেন্ড বিরতি (Telegram rate limit সহ্য করতে)
            await asyncio.sleep(0.1)
        except Exception:
            pass


# ─── Auto-capture videos posted directly to the channel ──────────────────────

@Client.on_message(filters.chat(VIDEO_CHANNEL_ID))
async def auto_index_new_video(client, message):
    """Save file_id when a video is posted to the channel."""
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

    await videos.insert_one({
        "file_id": file_id,
        "file_type": file_type,
        "caption": message.caption or "",
        "duration": duration,
        "width": width,
        "height": height,
        "added_at": datetime.now(timezone.utc),
    })


# ─── /fixvideos — re-process document-type videos for spoiler support ────────

@Client.on_message(filters.command("fixvideos") & filters.user(ADMIN_IDS))
async def fix_videos_cmd(client, message):
    """Re-send every document-type video through send_video to get a spoiler-capable file_id."""
    doc_vids = await videos.find({"file_type": "document"}).to_list(length=None)
    total = len(doc_vids)

    if total == 0:
        await message.reply_text(
            "✅ All videos already have spoiler-capable file IDs. Nothing to fix.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    status = await message.reply_text(
        f"🔄 Re-processing <b>{total}</b> document-type video(s)…\n"
        "This may take a moment.",
        parse_mode=enums.ParseMode.HTML,
    )

    fixed = failed = 0
    for vid in doc_vids:
        try:
            tmp = await client.send_video(
                chat_id=LOG_GROUP_ID,
                video=vid["file_id"],
                caption="",
            )
            new_file_id = tmp.video.file_id
            duration = tmp.video.duration or 0
            width = tmp.video.width or 0
            height = tmp.video.height or 0
            await tmp.delete()

            await videos.update_one(
                {"_id": vid["_id"]},
                {"$set": {
                    "file_id": new_file_id,
                    "file_type": "video",
                    "duration": duration,
                    "width": width,
                    "height": height,
                }},
            )
            fixed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)

    await status.edit_text(
        f"✅ <b>Fix complete!</b>\n\n"
        f"🎭 Converted: <b>{fixed}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n\n"
        f"{'All videos now support spoiler! 🎉' if failed == 0 else 'Some videos could not be converted.'}",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /users — list all registered users ──────────────────────────────────────

@Client.on_message(filters.command("users") & (filters.user(ADMIN_IDS) | filters.chat(LOG_GROUP_ID)))
async def users_cmd(client, message):
    all_users = await users.find({}, {"user_id": 1, "username": 1, "first_name": 1}).to_list(length=None)
    if not all_users:
        await message.reply_text("No users registered yet.", parse_mode=enums.ParseMode.HTML)
        return

    lines = [f"👥 <b>All Users ({len(all_users)})</b>\n"]
    for u in all_users:
        name = u.get("first_name") or "—"
        uname = f"@{u['username']}" if u.get("username") else "no username"
        uid = u["user_id"]
        lines.append(f"• {name} | {uname} | <code>{uid}</code>")

    chunk_size = 50
    for i in range(0, len(lines), chunk_size):
        chunk = lines[i:i + chunk_size] if i > 0 else lines[:chunk_size]
        await message.reply_text("\n".join(chunk), parse_mode=enums.ParseMode.HTML)


# ─── /groups — list all groups the bot is in ─────────────────────────────────

@Client.on_message(filters.command("groups") & (filters.user(ADMIN_IDS) | filters.chat(LOG_GROUP_ID)))
async def groups_cmd(client, message):
    all_groups = await groups.find({}, {"group_id": 1, "title": 1}).to_list(length=None)
    if not all_groups:
        await message.reply_text(
            "No groups in database yet.\n"
            "Use /updategroup inside any group to register it.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    lines = [f"🏘 <b>Groups ({len(all_groups)})</b>\n"]
    for g in all_groups:
        title = g.get("title") or "Unknown"
        gid = g["group_id"]
        lines.append(f"• {title} | <code>{gid}</code>")

    await message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)


# ─── /updategroup — register current group (or group by ID) in DB ─────────────

@Client.on_message(filters.command("updategroup") & filters.user(ADMIN_IDS))
async def updategroup_cmd(client, message):
    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        gid = message.chat.id
        title = message.chat.title or "Unknown"
        await groups.update_one(
            {"group_id": gid},
            {"$set": {"group_id": gid, "title": title, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        await message.reply_text(
            f"✅ Group registered!\n"
            f"📌 <b>{title}</b>\n"
            f"🆔 <code>{gid}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if len(message.command) >= 2:
        try:
            gid = int(message.command[1])
        except ValueError:
            await message.reply_text(
                "❌ Usage: send <code>/updategroup</code> <b>inside the group</b>, "
                "or <code>/updategroup -100XXXXXXXXX</code> here.",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        try:
            chat = await client.get_chat(gid)
            title = chat.title or "Unknown"
        except Exception:
            title = f"Group {gid}"
        await groups.update_one(
            {"group_id": gid},
            {"$set": {"group_id": gid, "title": title, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        await message.reply_text(
            f"✅ Group registered!\n"
            f"📌 <b>{title}</b>\n"
            f"🆔 <code>{gid}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    await message.reply_text(
        "ℹ️ <b>How to use /updategroup:</b>\n\n"
        "1️⃣ Send <code>/updategroup</code> <b>inside the group</b> to register it.\n"
        "2️⃣ Or use <code>/updategroup -100XXXXXXXXX</code> here with the group ID.",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /delvideo <index> — remove a video by its position number ───────────────

@Client.on_message(filters.command("delvideo") & filters.user(ADMIN_IDS))
async def del_video_cmd(client, message):
    if len(message.command) < 2:
        await message.reply_text(
            "❌ Usage: <code>/delvideo &lt;number&gt;</code>\n"
            "Use /stats to see video count.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    try:
        index = int(message.command[1]) - 1
    except ValueError:
        await message.reply_text("❌ Invalid number.", parse_mode=enums.ParseMode.HTML)
        return

    # Fix: sort by added_at নিশ্চিত করে ইনডেক্স সবসময় একই থাকে
    all_vids = await videos.find({}, {"_id": 1}).sort("added_at", 1).to_list(length=None)
    if index < 0 or index >= len(all_vids):
        await message.reply_text(
            f"⚠️ No video at position {index + 1}. Total: {len(all_vids)}",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    target_id = all_vids[index]["_id"]
    await videos.delete_one({"_id": target_id})
    total = await videos.count_documents({})
    await message.reply_text(
        f"🗑 Video #{index + 1} removed.\n"
        f"📦 Videos remaining: <b>{total}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /addlimit <user_id> <amount> — give a user extra videos ─────────────────

@Client.on_message(filters.command("addlimit") & filters.user(ADMIN_IDS))
async def addlimit_cmd(client, message):
    if len(message.command) < 3:
        await message.reply_text(
            "❌ <b>Usage:</b> <code>/addlimit &lt;user_id&gt; &lt;amount&gt;</code>\n\n"
            "<b>Example:</b> <code>/addlimit 123456789 5</code>  →  gives user 5 more videos",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    try:
        target_id = int(message.command[1])
        amount    = int(message.command[2])
        if amount <= 0 or target_id <= 0:
            raise ValueError
    except ValueError:
        await message.reply_text(
            "❌ Both <code>user_id</code> and <code>amount</code> must be positive integers.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    user = await users.find_one({"user_id": target_id})
    if not user:
        await message.reply_text(
            f"❌ No user found with ID <code>{target_id}</code>.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    old_count = user.get("video_count", 0)
    new_count = max(0, old_count - amount)
    await users.update_one(
        {"user_id": target_id},
        {"$set": {"video_count": new_count, "video_window_start": get_current_window_start()}},
    )

    remaining_before = max(0, VIDEO_DAILY_LIMIT - old_count)
    remaining_after  = max(0, VIDEO_DAILY_LIMIT - new_count)
    name  = user.get("first_name") or "Unknown"
    uname = f"@{user['username']}" if user.get("username") else "no username"

    confirmation = (
        f"✅ <b>Limit Added</b>\n\n"
        f"👤 {name} | {uname} | <code>{target_id}</code>\n"
        f"➕ Added: <b>+{amount}</b> videos\n"
        f"📊 Before: {remaining_before} remaining → After: <b>{remaining_after} remaining</b>\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%d %b %Y, %I:%M %p UTC')}"
    )

    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=f"🔓 <b>Admin Added Limit</b>\n\n{confirmation}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    try:
        await client.send_message(
            chat_id=target_id,
            text=(
                f"🎁 <b>আপনার লিমিট বাড়ানো হয়েছে!</b>\n\n"
                f"অ্যাডমিন আপনাকে আরও <b>{amount}টি</b> ভিডিও দিয়েছেন। 🎬\n"
                f"এখন আপনার কাছে আরও <b>{remaining_after}টি</b> ভিডিও বাকি আছে।\n\n"
                f"উপভোগ করুন! /video"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(confirmation, parse_mode=enums.ParseMode.HTML)


# ─── /stats ───────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats_cmd(client, message):
    total_users = await users.count_documents({})
    total_videos = await videos.count_documents({})
    await message.reply_text(
        "📊 <b>Bot Stats</b>\n\n"
        f"👥 Total users: <b>{total_users}</b>\n"
        f"🎬 Videos in DB: <b>{total_videos}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /broadcast ───────────────────────────────────────────────────────────────

@Client.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast_cmd(client, message):
    if not message.reply_to_message:
        await message.reply_text(
            "❌ <b>Usage:</b> Reply to any message with /broadcast.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    all_users = await users.find({}, {"user_id": 1}).to_list(length=None)
    total = len(all_users)

    if total == 0:
        await message.reply_text("No users in the database yet.")
        return

    status_msg = await message.reply_text(
        f"📡 Broadcasting to <b>{total}</b> users…",
        parse_mode=enums.ParseMode.HTML,
    )

    all_group_docs = await groups.find({}, {"group_id": 1}).to_list(length=None)
    total_groups = len(all_group_docs)

    await status_msg.edit_text(
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
        # Fix: 0.05 → 0.1 সেকেন্ড বিরতি (Telegram rate limit সহ্য করতে)
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
