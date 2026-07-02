import asyncio
from datetime import datetime

from pyrogram import Client, filters, enums

from config import OWNER_ID, VIDEO_CHANNEL_ID, LOG_GROUP_ID
from database import users, videos, groups


# ─── Admin sends/forwards any video to the bot PM → auto-save ────────────────

@Client.on_message(
    filters.private
    & filters.user(OWNER_ID)
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
        # Re-send as video to get a spoiler-capable file_id; use monitor group as temp destination
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
            # Fallback: store as document (no spoiler support)
            file_id = message.document.file_id
            file_type = "document"
    else:
        return

    # Check if DB was empty before this insert
    count_before = await videos.count_documents({})

    await videos.insert_one({
        "file_id": file_id,
        "file_type": file_type,
        "caption": caption,
        "duration": duration,
        "width": width,
        "height": height,
        "added_at": datetime.utcnow(),
    })

    total = await videos.count_documents({})

    # If DB was empty, notify all users that videos are now available
    if count_before == 0 and total > 0:
        asyncio.create_task(_notify_users_videos_available(client))

    # ── Confirmation goes to monitor group only ───────────────────────────────
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

    # Brief acknowledgement in admin's PM so they know it was received
    await message.reply_text("✅ Saved.", parse_mode=enums.ParseMode.HTML)


async def _notify_users_videos_available(client):
    """Notify all users that the video library is now available."""
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
            await asyncio.sleep(0.05)
        except Exception:
            pass


# ─── Auto-capture videos posted directly to the channel ──────────────────────

@Client.on_message(filters.chat(VIDEO_CHANNEL_ID))
async def auto_index_new_video(client, message):
    """Save file_id when a video is posted to the channel.
    Document-type videos are converted to proper video type for spoiler support.
    """
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
        # Re-send to monitor group as video to get a spoiler-capable file_id
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
            # Fallback: store as document (no spoiler support)
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
        "added_at": datetime.utcnow(),
    })


# ─── /fixvideos — re-process document-type videos for spoiler support ────────

@Client.on_message(filters.command("fixvideos") & filters.user(OWNER_ID))
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
        f"{'All videos now support spoiler! 🎉' if failed == 0 else 'Some videos could not be converted — they may stay without spoiler.'}",
        parse_mode=enums.ParseMode.HTML,
    )


# ─── /delvideo <index> — remove a video by its position number ───────────────

@Client.on_message(filters.command("delvideo") & filters.user(OWNER_ID))
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

    all_vids = await videos.find({}, {"_id": 1}).to_list(length=None)
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


# ─── /stats ───────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("stats") & filters.user(OWNER_ID))
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

@Client.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
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

    # ── Send to all individual users (copy — no "Forwarded from" header) ─────
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
        await asyncio.sleep(0.05)

    # ── Send to all groups ────────────────────────────────────────────────────
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
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        "✅ <b>Broadcast complete!</b>\n\n"
        f"👥 Users — ✅ {success}  ❌ {failed}\n"
        f"🏘 Groups — ✅ {g_success}  ❌ {g_failed}",
        parse_mode=enums.ParseMode.HTML,
    )
