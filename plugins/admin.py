import asyncio
from datetime import datetime

from pyrogram import Client, filters, enums

from config import OWNER_ID, VIDEO_CHANNEL_ID
from database import users, videos


# ─── Admin sends/forwards any video to the bot PM → auto-save ────────────────

@Client.on_message(
    filters.private
    & filters.user(OWNER_ID)
    & (filters.video | filters.document)
)
async def admin_save_video(client, message):
    """
    Admin sends or forwards ANY video to the bot in PM → stored by file_id.
    Works with direct uploads and channel forwards.
    Use /delvideo <id> to remove. Use /stats to see totals.
    """
    file_id = None
    file_type = "video"
    duration = width = height = 0

    if message.video:
        v = message.video
        file_id = v.file_id
        file_type = "video"
        duration = v.duration or 0
        width = v.width or 0
        height = v.height or 0
    elif (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video/")
    ):
        file_id = message.document.file_id
        file_type = "document"
    else:
        # Not a usable video — ignore silently
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

    total = await videos.count_documents({})
    await message.reply_text(
        f"✅ <b>Video saved!</b>\n"
        f"📦 Total videos in DB: <b>{total}</b>\n\n"
        f"<i>Users can now receive this video via /video.</i>",
        parse_mode=enums.ParseMode.HTML,
    )


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
        index = int(message.command[1]) - 1  # 1-based for the user
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

    success = 0
    failed = 0

    for user_doc in all_users:
        uid = user_doc["user_id"]
        try:
            await client.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.id,
            )
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        "✅ <b>Broadcast complete!</b>\n\n"
        f"✅ Delivered: <b>{success}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n"
        f"👥 Total: <b>{total}</b>",
        parse_mode=enums.ParseMode.HTML,
    )
