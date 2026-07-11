import asyncio
from datetime import datetime, timezone

from pyrogram import Client, filters, enums, ContinuePropagation

from config import ADMIN_IDS, VIDEO_CHANNEL_ID, LOG_GROUP_ID, VIDEO_DAILY_LIMIT, GROUP_VIDEO_LIMIT, OWNER_ID
from database import users, videos, groups
from helpers import get_current_window_start, get_caption_with_media_group_fallback


def _log_error(context: str, exc: Exception):
    """Print monitor-group send failures to stdout so they show up in deployment
    logs instead of failing completely silently — this is the main way to
    diagnose a misconfigured LOG_CHANNEL_ID."""
    print(f"[LOG-SEND-FAILED] {context}: {exc!r}")


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
    caption = await get_caption_with_media_group_fallback(client, message)

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
    except Exception as e:
        _log_error("admin_save_video new-video notice", e)

    await message.reply_text(
        f"✅ Saved. Total videos in library: <b>{total}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


async def _notify_users_videos_available(client):
    """Notify all users that the video library is now available.
    Rate limiting: a short delay is kept between messages since Telegram
    allows at most ~30 messages/second.
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
            await asyncio.sleep(0.1)
        except Exception:
            pass


# ─── Auto-save videos shared in ANY group/channel ─────────────────────────────
# Conditions: (1) not already in DB, (2) longer than 3 minutes (any length if
# it comes from VIDEO_CHANNEL_ID, the main source channel)

@Client.on_message(
    (filters.group | filters.channel)
    & (filters.video | filters.document)
)
async def auto_index_new_video(client, message):
    """Save any video shared in a group/channel into the DB.

    Important: this handler only matches video/document messages.
    Text/command messages never reach here — so /video, /stats, and all
    other commands correctly reach their own handlers.
    """
    from config import SUPPORT_GROUP_ID

    # Don't save videos posted in the LOG group or support group —
    # use ContinuePropagation so the next matching handler still runs.
    if message.chat.id in (LOG_GROUP_ID, SUPPORT_GROUP_ID):
        raise ContinuePropagation()

    file_id        = None
    file_unique_id = None
    file_type      = "video"
    duration = width = height = 0
    is_video_channel = (message.chat.id == VIDEO_CHANNEL_ID)

    if message.video:
        v              = message.video
        file_id        = v.file_id
        file_unique_id = v.file_unique_id
        duration       = v.duration or 0
        width          = v.width or 0
        height         = v.height or 0

    elif (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video/")
    ):
        file_unique_id = message.document.file_unique_id
        try:
            tmp = await client.send_video(
                chat_id=LOG_GROUP_ID,
                video=message.document.file_id,
                caption="",
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
        raise ContinuePropagation()

    # Only accept videos longer than 3 minutes, unless it's the main source channel
    if not is_video_channel and duration < 180:
        return

    # Skip duplicates already in DB (matched by file_unique_id)
    if file_unique_id:
        existing = await videos.find_one({"file_unique_id": file_unique_id})
        if existing:
            return

    # Fix: fetch caption with media-group (album) fallback — Telegram only
    # attaches the caption to ONE message of an album, so a video posted as
    # part of a multi-video album could otherwise be saved with no caption.
    caption_text = await get_caption_with_media_group_fallback(client, message)

    await videos.insert_one({
        "file_id":        file_id,
        "file_unique_id": file_unique_id,
        "file_type":      file_type,
        "caption":        caption_text,
        "duration":       duration,
        "width":          width,
        "height":         height,
        "source_chat":    message.chat.id,
        "added_at":       datetime.now(timezone.utc),
    })

    # Always notify the monitor group, including for the main source channel —
    # previously this was skipped for the main channel, which is why "new video
    # saved" notifications appeared to be missing.
    try:
        mins = duration // 60
        secs = duration % 60
        source_label = "Main source channel" if is_video_channel else (message.chat.title or str(message.chat.id))
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=(
                "🎬 <b>New Video Auto-Saved</b>\n\n"
                f"📌 Source: <b>{source_label}</b>\n"
                f"⏱ Duration: <b>{mins}:{secs:02d}</b>\n"
                f"📝 Caption: {caption_text or '—'}\n"
                f"📦 Total videos in DB: <b>{await videos.count_documents({})}</b>"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        _log_error("auto_index_new_video notice", e)


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

    # Sort by added_at so the index always stays consistent
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
    except Exception as e:
        _log_error("addlimit_cmd notice", e)

    try:
        await client.send_message(
            chat_id=target_id,
            text=(
                f"🎁 <b>Your limit has been increased!</b>\n\n"
                f"The admin has given you <b>{amount} more</b> videos! 🎬\n"
                f"You now have <b>{remaining_after}</b> videos remaining.\n\n"
                f"Enjoy! /video"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(confirmation, parse_mode=enums.ParseMode.HTML)


# ─── /stats · /dashboard — detailed statistics ────────────────────────────────

@Client.on_message(filters.command(["stats", "dashboard"]) & filters.user(ADMIN_IDS))
async def stats_cmd(client, message):
    from datetime import timedelta
    from database import user_video_history, group_video_stats, support_msgs

    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    last_12h = now - timedelta(hours=12)

    # Fetch all stats together
    total_users    = await users.count_documents({})
    active_24h     = await users.count_documents({"joined_at": {"$gte": last_24h}})
    new_today      = await users.count_documents({"joined_at": {"$gte": last_24h}})

    total_videos   = await videos.count_documents({})
    sent_24h       = await user_video_history.count_documents({"sent_at": {"$gte": last_24h}})
    sent_12h       = await user_video_history.count_documents({"sent_at": {"$gte": last_12h}})

    total_groups   = await groups.count_documents({})
    total_support  = await support_msgs.count_documents({})
    pending_sup    = await support_msgs.count_documents({"replied": {"$ne": True}})

    # Most-active user by videos watched
    top_cursor = user_video_history.aggregate([
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
        {"$sort":  {"count": -1}},
        {"$limit": 1},
    ])
    top_list = await top_cursor.to_list(length=1)
    if top_list:
        top_uid   = top_list[0]["_id"]
        top_count = top_list[0]["count"]
        top_user  = await users.find_one({"user_id": top_uid})
        top_name  = (top_user or {}).get("first_name") or f"ID:{top_uid}"
    else:
        top_name, top_count = "—", 0

    await message.reply_text(
        "📊 <b>Admin Dashboard</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "👥 <b>Users:</b>\n"
        f"  • Total: <b>{total_users:,}</b>\n"
        f"  • New today: <b>{new_today:,}</b>\n\n"
        "🎬 <b>Videos:</b>\n"
        f"  • Total in DB: <b>{total_videos:,}</b>\n"
        f"  • Sent in last 12h: <b>{sent_12h:,}</b>\n"
        f"  • Sent in last 24h: <b>{sent_24h:,}</b>\n\n"
        "🏘 <b>Groups:</b>\n"
        f"  • Total: <b>{total_groups:,}</b>\n\n"
        "📩 <b>Support Inbox:</b>\n"
        f"  • Total messages: <b>{total_support:,}</b>\n"
        f"  • Pending: <b>{pending_sup:,}</b>\n\n"
        "🏆 <b>Most videos watched:</b>\n"
        f"  • {top_name} — <b>{top_count:,}</b>\n\n"
        f"🕐 Updated: {now.strftime('%d %b %Y, %I:%M %p')} UTC",
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
    """Admin: show list of all commands."""
    await message.reply_text(
        "📋 <b>All Commands</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "👤 <b>User Commands:</b>\n"
        "/start — Start the bot\n"
        "/help — Show help\n"
        "/video — Get a random video 🎬\n"
        "/profile — View your profile\n\n"
        "🔑 <b>Admin Commands:</b>\n"
        "/stats — View all statistics\n"
        "/broadcast — Message everyone (as a reply)\n"
        "/notifyusers — Send video notification\n"
        "/addvideo — Add a video (as a reply)\n"
        "/delvideo <number> — Remove a specific video\n"
        "/cmdlist — Show this command list\n\n"
        "⚙️ <b>Settings:</b>\n"
        f"🎬 PM video limit: <b>{VIDEO_DAILY_LIMIT}</b> per 12h\n"
        f"🏘 Group video limit: <b>{GROUP_VIDEO_LIMIT}</b> per 12h\n\n"
        "📩 <b>Support Inbox:</b>\n"
        "When a user sends a plain message to the bot, it lands here.\n"
        "Reply to it and it goes straight back to the user. ✅",
        parse_mode=enums.ParseMode.HTML,
    )
