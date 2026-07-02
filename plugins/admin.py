import asyncio
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import OWNER_ID, VIDEO_CHANNEL_ID
from database import users, videos
from plugins.video import index_channel_videos


# ─── Auto-capture new videos posted to the channel ───────────────────────────

@Client.on_message(filters.chat(VIDEO_CHANNEL_ID))
async def auto_index_new_video(client, message):
    """Automatically add newly posted channel videos to the DB."""
    is_video = message.video
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


# ─── /index — manually trigger a full channel scan ───────────────────────────

@Client.on_message(filters.command("index") & filters.user(OWNER_ID))
async def index_cmd(client, message):
    status = await message.reply("🔄 Scanning channel for videos…")
    try:
        scanned, added = await index_channel_videos(client)
        total_in_db = await videos.count_documents({})
        await status.edit_text(
            "✅ <b>Indexing complete!</b>\n\n"
            f"📨 Messages scanned: <b>{scanned}</b>\n"
            f"🎬 New videos added: <b>{added}</b>\n"
            f"📦 Total videos in DB: <b>{total_in_db}</b>",
            parse_mode="html",
        )
    except RuntimeError as e:
        await status.edit_text(
            f"❌ <b>Indexing failed:</b>\n<code>{e}</code>",
            parse_mode="html",
        )


# ─── /stats — quick overview ──────────────────────────────────────────────────

@Client.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def stats_cmd(client, message):
    total_users = await users.count_documents({})
    total_videos = await videos.count_documents({})
    await message.reply_text(
        "📊 <b>Bot Stats</b>\n\n"
        f"👥 Total users: <b>{total_users}</b>\n"
        f"🎬 Videos in DB: <b>{total_videos}</b>",
        parse_mode="html",
    )


# ─── /broadcast — send a message to every user ───────────────────────────────

@Client.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_cmd(client, message):
    if not message.reply_to_message:
        await message.reply_text(
            "❌ <b>Usage:</b> Reply to a message with /broadcast to send it to all users.",
            parse_mode="html",
        )
        return

    all_users = await users.find({}, {"user_id": 1}).to_list(length=None)
    total = len(all_users)

    if total == 0:
        await message.reply_text("No users in the database yet.")
        return

    status_msg = await message.reply_text(f"📡 Broadcasting to <b>{total}</b> users…", parse_mode="html")

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
        # Respect Telegram rate limits (~20 msg/s max for bots)
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        "✅ <b>Broadcast complete!</b>\n\n"
        f"✅ Delivered: <b>{success}</b>\n"
        f"❌ Failed (blocked/deleted): <b>{failed}</b>\n"
        f"👥 Total: <b>{total}</b>",
        parse_mode="html",
    )
