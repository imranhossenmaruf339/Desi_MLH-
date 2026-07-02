import asyncio
import random
from datetime import datetime, timedelta

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import JOIN_CHANNEL_LINK, VIP_CHANNEL_LINK, VIDEO_DAILY_LIMIT
from database import users, videos, user_video_history
from helpers import get_current_window_start, schedule_delete


# Two JOIN buttons shown under every video (always visible)
def _join_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("JOIN", url=JOIN_CHANNEL_LINK),
            InlineKeyboardButton("JOIN", url=VIP_CHANNEL_LINK),
        ]
    ])


async def _delete_after(client, chat_id: int, message_id: int, delay: int = 1800):
    """Delete a message after `delay` seconds (default 30 minutes)."""
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


# Works in private chats AND in any group where the bot is a member
@Client.on_message(filters.command("video") & (filters.private | filters.group))
async def video_cmd(client, message):
    # Anonymous group admins have no from_user
    if not message.from_user:
        await message.reply_text("❌ Cannot identify user. Please disable anonymous mode.")
        return

    user_id = message.from_user.id
    in_group = message.chat.type != enums.ChatType.PRIVATE

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
            "joined_at": datetime.utcnow(),
        })
        user = await users.find_one({"user_id": user_id})

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

    # ── Daily limit reached → show 2-channel unlock options ──────────────────
    if video_count >= VIDEO_DAILY_LIMIT:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel 1", url=JOIN_CHANNEL_LINK)],
            [InlineKeyboardButton("💎 Join VIP Channel", url=VIP_CHANNEL_LINK)],
            [InlineKeyboardButton("✅ Confirmed", callback_data=f"confirm_join:{user_id}")],
        ])
        sent = await message.reply_text(
            "⚠️ <b>You Have Reached your Limit!</b>\n\n"
            "Come Again After <b>12:00</b> 🕛\n\n"
            "Or join our channels and get <b>+15 extra videos</b>:\n\n"
            "1️⃣ Join <b>Channel 1</b>\n"
            "2️⃣ Join <b>VIP Channel</b>\n\n"
            "After joining, tap <b>✅ Confirmed</b> — admin will verify and unlock your videos.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
        # Delete limit message in groups after 90 s (user needs time to tap buttons)
        if in_group and sent:
            asyncio.create_task(schedule_delete(client, message.chat.id, sent.id, 90))
        return

    # ── Pick a video not seen by this user in the last 7 days ────────────────
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent = await user_video_history.find(
        {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}},
        {"video_id": 1},
    ).to_list(length=None)
    seen_ids = {h["video_id"] for h in recent}

    all_vids = await videos.find().to_list(length=None)
    pool = [v for v in all_vids if v["_id"] not in seen_ids]

    # All videos watched — notify user, do NOT fall back to re-sending seen ones
    if not pool and all_vids:
        sent = await message.reply_text(
            "🎬 <b>You've watched all available videos!</b>\n\n"
            "New videos will be added soon. You'll be notified when they arrive! 🔔\n\n"
            "Come back in a few days — watched videos also refresh after <b>7 days</b>.",
            parse_mode=enums.ParseMode.HTML,
        )
        if in_group and sent:
            asyncio.create_task(schedule_delete(client, message.chat.id, sent.id, 30))
        return

    if not pool:
        sent = await message.reply_text(
            "❌ <b>No videos available yet.</b>\n\nPlease check back later!",
            parse_mode=enums.ParseMode.HTML,
        )
        if in_group and sent:
            asyncio.create_task(schedule_delete(client, message.chat.id, sent.id, 30))
        return

    video_doc = random.choice(pool)
    file_id = video_doc.get("file_id")

    # ── Send the video with spoiler ───────────────────────────────────────────
    # Always try send_video first → has_spoiler works only for video type.
    # If the stored file_id is document-only, fall back to send_document (no spoiler).
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
            reply_markup=_join_buttons(),
        )
    except Exception:
        try:
            sent = await client.send_document(
                chat_id=message.chat.id,
                document=file_id,
                caption=video_doc.get("caption", ""),
                reply_markup=_join_buttons(),
            )
        except Exception as e:
            err = await message.reply_text(
                f"❌ Failed to send video. Please try again.\n<code>{e}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            if in_group and err:
                asyncio.create_task(schedule_delete(client, message.chat.id, err.id, 30))
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

    # Check if this was the last unseen video — notify user
    remaining_pool = [v for v in all_vids if v["_id"] not in seen_ids and v["_id"] != video_doc["_id"]]
    if not remaining_pool:
        try:
            note = await message.reply_text(
                "🎬 <b>That was your last unseen video!</b>\n\n"
                "You've now watched everything available. "
                "New videos will be added soon — you'll get a notification! 🔔\n\n"
                "Watched videos also refresh after <b>7 days</b>.",
                parse_mode=enums.ParseMode.HTML,
            )
            if in_group and note:
                asyncio.create_task(schedule_delete(client, message.chat.id, note.id, 30))
        except Exception:
            pass
