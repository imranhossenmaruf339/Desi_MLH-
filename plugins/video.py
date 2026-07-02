import asyncio
import random
from datetime import datetime, timedelta

from pyrogram import Client, filters, enums
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import JOIN_CHANNEL_LINK, JOIN_CHANNEL_2_LINK, JOIN_CHANNEL_2_USERNAME, VIDEO_DAILY_LIMIT
from database import users, videos, user_video_history
from helpers import get_current_window_start


# Two JOIN buttons shown under every video
JOIN_BUTTONS = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("JOIN", url=JOIN_CHANNEL_LINK),
        InlineKeyboardButton("JOIN", url=JOIN_CHANNEL_2_LINK),
    ]
])


async def _delete_after(client, chat_id: int, message_id: int, delay: int = 1800):
    """Delete a message after `delay` seconds (default 30 minutes)."""
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


async def check_second_channel(client, user_id: int) -> bool:
    """Returns True if the user is a member of the required channel."""
    try:
        member = await client.get_chat_member(JOIN_CHANNEL_2_USERNAME, user_id)
        return member.status not in [
            enums.ChatMemberStatus.BANNED,
            enums.ChatMemberStatus.LEFT,
        ]
    except UserNotParticipant:
        return False
    except Exception:
        return False


# Works in private chats AND in any group where the bot is a member
@Client.on_message(filters.command("video") & (filters.private | filters.group))
async def video_cmd(client, message):
    # Anonymous group admins have no from_user
    if not message.from_user:
        await message.reply_text("❌ Cannot identify user. Please disable anonymous mode.")
        return

    user_id = message.from_user.id

    # ── Ensure user record exists ─────────────────────────────────────────────
    user = await users.find_one({"user_id": user_id})
    if not user:
        window = get_current_window_start()
        await users.insert_one({
            "user_id": user_id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name or "",
            "points": 0,
            "referrals": 0,
            "video_count": 0,
            "video_window_start": window,
        })
        user = await users.find_one({"user_id": user_id})

    # ── Channel membership check ──────────────────────────────────────────────
    if not await check_second_channel(client, user_id):
        await message.reply_text(
            "⚠️ <b>You must join our channel to use this feature!</b>\n\n"
            "👇 Tap <b>JOIN</b> below, join the channel, then send /video again.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=JOIN_BUTTONS,
        )
        return

    # ── 12-hour window check / reset ──────────────────────────────────────────
    current_window = get_current_window_start()
    user_window = user.get("video_window_start")
    video_count = user.get("video_count", 0)

    if user_window != current_window:
        video_count = 0
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"video_count": 0, "video_window_start": current_window}},
        )

    # ── Daily limit reached ───────────────────────────────────────────────────
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
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    # ── Pick a video not seen by this user in the last 7 days ────────────────
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent = await user_video_history.find(
        {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}},
        {"video_id": 1},
    ).to_list(length=None)
    seen_ids = {h["video_id"] for h in recent}

    all_vids = await videos.find().to_list(length=500)
    pool = [v for v in all_vids if v["_id"] not in seen_ids]

    # If everything has been seen recently, fall back to the full pool
    if not pool:
        pool = all_vids

    if not pool:
        await message.reply_text(
            "❌ <b>No videos available yet.</b>\n\nPlease check back later!",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    video_doc = random.choice(pool)
    file_id = video_doc.get("file_id")

    # ── Send the video with spoiler ───────────────────────────────────────────
    # Always try send_video first so has_spoiler=True is applied.
    # Documents cannot carry a spoiler; if the file_id only works as a document,
    # we fall back to send_document (no spoiler — Telegram limitation).
    sent = None
    try:
        sent = await client.send_video(
            chat_id=message.chat.id,
            video=file_id,
            caption=video_doc.get("caption", ""),
            has_spoiler=True,
            duration=video_doc.get("duration", 0),
            width=video_doc.get("width", 0),
            height=video_doc.get("height", 0),
            reply_markup=JOIN_BUTTONS,
        )
    except Exception:
        # file_id is a non-streamable document — send without spoiler
        try:
            sent = await client.send_document(
                chat_id=message.chat.id,
                document=file_id,
                caption=video_doc.get("caption", ""),
                reply_markup=JOIN_BUTTONS,
            )
        except Exception as e:
            await message.reply_text(
                f"❌ Failed to send video. Please try again.\n<code>{e}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

    # ── Schedule auto-delete after 30 minutes ────────────────────────────────
    if sent:
        asyncio.create_task(_delete_after(client, message.chat.id, sent.id, delay=1800))

    # ── Record history + increment counter ───────────────────────────────────
    await user_video_history.insert_one({
        "user_id": user_id,
        "video_id": video_doc["_id"],
        "sent_at": datetime.utcnow(),
    })
    await users.update_one(
        {"user_id": user_id},
        {"$set": {"video_count": video_count + 1}},
    )
