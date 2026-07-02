import random
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import OWNER_ID, VIDEO_CHANNEL_ID, JOIN_CHANNEL_LINK, VIDEO_DAILY_LIMIT
from database import users, videos
from helpers import get_current_window_start


def _is_video_message(msg):
    """Return True for proper video messages OR documents with a video mime type."""
    if msg.video:
        return True
    if msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        return True
    return False


async def index_channel_videos(client: Client):
    """Scan the video channel, cache all video message IDs in MongoDB.
    Returns (scanned, newly_added) counts.
    """
    scanned = 0
    added = 0
    try:
        async for msg in client.get_chat_history(VIDEO_CHANNEL_ID):
            scanned += 1
            if _is_video_message(msg):
                exists = await videos.find_one({"msg_id": msg.id})
                if not exists:
                    await videos.insert_one({
                        "msg_id": msg.id,
                        "channel_id": VIDEO_CHANNEL_ID,
                        "is_document": bool(msg.document),
                        "indexed_at": datetime.utcnow(),
                    })
                    added += 1
    except Exception as e:
        raise RuntimeError(f"Channel scan failed: {e}") from e
    return scanned, added


@Client.on_message(filters.command("video") & filters.private)
async def video_cmd(client, message):
    user_id = message.from_user.id

    # Ensure user record exists
    user = await users.find_one({"user_id": user_id})
    if not user:
        window = get_current_window_start()
        await users.insert_one({
            "user_id": user_id,
            "username": message.from_user.username,
            "points": 0,
            "referrals": 0,
            "video_count": 0,
            "video_window_start": window,
        })
        user = await users.find_one({"user_id": user_id})

    # Check / reset 12-hour window
    current_window = get_current_window_start()
    user_window = user.get("video_window_start")
    video_count = user.get("video_count", 0)

    if user_window != current_window:
        video_count = 0
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"video_count": 0, "video_window_start": current_window}},
        )

    # Limit reached → show join prompt
    if video_count >= VIDEO_DAILY_LIMIT:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=JOIN_CHANNEL_LINK)],
            [InlineKeyboardButton("✅ I've Joined — Confirm", callback_data=f"confirm_join:{user_id}")],
        ])
        await message.reply_text(
            "⚠️ <b>Daily limit reached!</b>\n\n"
            f"You've used all <b>{VIDEO_DAILY_LIMIT} videos</b> for this period.\n\n"
            "👉 Join our partner channel to get more access, "
            "then tap <b>I've Joined — Confirm</b>.\n\n"
            "🕐 Limits reset at <b>12:00 AM</b> and <b>12:00 PM</b> (UTC) daily.",
            parse_mode="html",
            reply_markup=keyboard,
        )
        return

    # Fetch video list; auto-index once if DB is empty
    video_list = await videos.find().to_list(length=500)
    if not video_list:
        status_msg = await message.reply_text("⏳ Indexing videos, please wait…")
        try:
            scanned, added = await index_channel_videos(client)
        except RuntimeError as e:
            await status_msg.edit_text(f"❌ Could not index channel: <code>{e}</code>", parse_mode="html")
            return
        video_list = await videos.find().to_list(length=500)
        await status_msg.delete()
        if not video_list:
            await message.reply_text(
                f"❌ No videos found in the channel.\n"
                f"<i>(Scanned {scanned} messages)</i>\n\n"
                "Ask the admin to post videos in the channel first.",
                parse_mode="html",
            )
            return

    # Pick a random video and send with spoiler
    video_doc = random.choice(video_list)
    try:
        channel_msg = await client.get_messages(VIDEO_CHANNEL_ID, video_doc["msg_id"])

        # Detect media object (video or document-video)
        media = None
        send_as_doc = False
        if channel_msg and channel_msg.video:
            media = channel_msg.video
        elif channel_msg and channel_msg.document and \
                channel_msg.document.mime_type and \
                channel_msg.document.mime_type.startswith("video/"):
            media = channel_msg.document
            send_as_doc = True

        if not media:
            await videos.delete_one({"msg_id": video_doc["msg_id"]})
            await message.reply_text("⚠️ That video is no longer available. Please use /video again.")
            return

        if send_as_doc:
            # Send document-videos as regular video using file_id
            await client.send_document(
                chat_id=message.chat.id,
                document=media.file_id,
                caption=channel_msg.caption or "",
            )
        else:
            await client.send_video(
                chat_id=message.chat.id,
                video=media.file_id,
                caption=channel_msg.caption or "",
                has_spoiler=True,
                duration=media.duration,
                width=media.width,
                height=media.height,
            )

        new_count = video_count + 1
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"video_count": new_count}},
        )

        remaining = VIDEO_DAILY_LIMIT - new_count
        period_text = (
            "🕛 Resets at 12:00 PM UTC"
            if datetime.utcnow().hour < 12
            else "🕛 Resets at 12:00 AM UTC"
        )
        await message.reply_text(
            f"🎬 Enjoy!\n"
            f"📊 <b>{remaining}</b> video(s) remaining this period.\n"
            f"{period_text}",
            parse_mode="html",
        )

    except Exception as e:
        await message.reply_text(
            f"❌ Failed to send video. Please try again.\n<code>{e}</code>",
            parse_mode="html",
        )
