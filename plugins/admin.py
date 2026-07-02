import asyncio
from datetime import datetime

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import OWNER_ID, VIDEO_CHANNEL_ID
from database import users, videos


# ─── Auto-capture new videos posted to the channel ───────────────────────────

@Client.on_message(filters.chat(VIDEO_CHANNEL_ID))
async def auto_index_new_video(client, message):
    """Automatically save video message IDs when new posts arrive in the channel."""
    is_video = bool(message.video)
    is_doc_video = (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video/")
    )
    if not (is_video or is_doc_video):
        return

    await videos.update_one(
        {"msg_id": message.id},
        {
            "$setOnInsert": {
                "msg_id": message.id,
                "channel_id": VIDEO_CHANNEL_ID,
                "is_document": bool(message.document),
                "indexed_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


# ─── Auto-detect when admin forwards a channel video to the bot ──────────────

@Client.on_message(
    filters.private
    & filters.user(OWNER_ID)
    & (filters.video | filters.document)
)
async def admin_forwarded_video(client, message):
    """If admin forwards a video from the video channel, auto-add it to DB."""
    fwd_chat = getattr(message, "forward_from_chat", None)
    if not fwd_chat or fwd_chat.id != VIDEO_CHANNEL_ID:
        return

    msg_id = message.forward_from_message_id
    if not msg_id:
        return

    result = await videos.update_one(
        {"msg_id": msg_id},
        {
            "$setOnInsert": {
                "msg_id": msg_id,
                "channel_id": VIDEO_CHANNEL_ID,
                "is_document": bool(message.document),
                "indexed_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )

    if result.upserted_id:
        total = await videos.count_documents({})
        await message.reply_text(
            f"✅ <b>Video added!</b>\n"
            f"📦 Total videos in DB: <b>{total}</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await message.reply_text("ℹ️ This video is already in the database.")


# ─── /addvideo — add a video by its channel message ID ───────────────────────

@Client.on_message(filters.command("addvideo") & filters.user(OWNER_ID))
async def add_video_cmd(client, message):
    """
    Usage:
      • /addvideo <msg_id>       — add by channel message ID
      • Reply to a forwarded channel video with /addvideo
    """
    msg_id = None

    # Case 1: reply to a forwarded message from the channel
    if message.reply_to_message:
        replied = message.reply_to_message
        fwd_chat = getattr(replied, "forward_from_chat", None)
        if fwd_chat and fwd_chat.id == VIDEO_CHANNEL_ID:
            msg_id = replied.forward_from_message_id

    # Case 2: explicit message ID argument
    if msg_id is None and len(message.command) > 1:
        try:
            msg_id = int(message.command[1])
        except ValueError:
            await message.reply_text(
                "❌ <b>Invalid ID.</b> Usage: <code>/addvideo 12345</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

    if msg_id is None:
        await message.reply_text(
            "❌ <b>Usage:</b>\n"
            "• <code>/addvideo &lt;msg_id&gt;</code> — add a video by its channel message ID\n"
            "• Forward a video from the channel here and reply with <code>/addvideo</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    # Verify the message exists and has a video
    try:
        ch_msg = await client.get_messages(VIDEO_CHANNEL_ID, msg_id)
    except Exception as e:
        await message.reply_text(
            f"❌ Could not fetch message <code>{msg_id}</code> from the channel.\n"
            f"<code>{e}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    is_video = bool(ch_msg and ch_msg.video)
    is_doc_video = (
        ch_msg
        and ch_msg.document
        and ch_msg.document.mime_type
        and ch_msg.document.mime_type.startswith("video/")
    )
    if not (is_video or is_doc_video):
        await message.reply_text(
            f"⚠️ Message <code>{msg_id}</code> is not a video.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    result = await videos.update_one(
        {"msg_id": msg_id},
        {
            "$setOnInsert": {
                "msg_id": msg_id,
                "channel_id": VIDEO_CHANNEL_ID,
                "is_document": bool(ch_msg.document),
                "indexed_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )

    total = await videos.count_documents({})
    if result.upserted_id:
        await message.reply_text(
            f"✅ <b>Video {msg_id} added!</b>\n"
            f"📦 Total videos in DB: <b>{total}</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"ℹ️ Video <code>{msg_id}</code> is already in the database.\n"
            f"📦 Total videos in DB: <b>{total}</b>",
            parse_mode=enums.ParseMode.HTML,
        )


# ─── /delvideo — remove a video from DB ──────────────────────────────────────

@Client.on_message(filters.command("delvideo") & filters.user(OWNER_ID))
async def del_video_cmd(client, message):
    if len(message.command) < 2:
        await message.reply_text(
            "❌ Usage: <code>/delvideo &lt;msg_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    try:
        msg_id = int(message.command[1])
    except ValueError:
        await message.reply_text("❌ Invalid ID.", parse_mode=enums.ParseMode.HTML)
        return

    result = await videos.delete_one({"msg_id": msg_id})
    total = await videos.count_documents({})
    if result.deleted_count:
        await message.reply_text(
            f"🗑 Video <code>{msg_id}</code> removed.\n"
            f"📦 Videos remaining: <b>{total}</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"⚠️ Video <code>{msg_id}</code> not found in DB.",
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
            "❌ <b>Usage:</b> Reply to any message with /broadcast to send it to all users.",
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
        f"❌ Failed (blocked/deleted): <b>{failed}</b>\n"
        f"👥 Total: <b>{total}</b>",
        parse_mode=enums.ParseMode.HTML,
    )
