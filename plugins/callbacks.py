"""
Callback query handlers (non-video related).
Old VIP/channel verification logic removed — replaced by group-based force-join in video.py.
"""

from datetime import datetime, timezone, timedelta

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS, LOG_GROUP_ID, SUPPORT_GROUP_ID
from database import users, support_msgs
from helpers import get_current_window_start


# ─── my_status callback (from start keyboard) ────────────────────────────────

@Client.on_callback_query(filters.regex(r"^my_status$"))
async def my_status_callback(client, callback_query):
    user_id = callback_query.from_user.id

    user = await users.find_one({"user_id": user_id})
    if not user:
        await callback_query.answer("Profile পাওয়া যায়নি।", show_alert=True)
        return

    from config import VIDEO_DAILY_LIMIT
    current_window = get_current_window_start()
    user_window = user.get("video_window_start")
    video_count = user.get("video_count", 0) if user_window == current_window else 0
    remaining = max(0, VIDEO_DAILY_LIMIT - video_count)

    await callback_query.answer(
        f"🎬 এই window-এ দেখেছেন: {video_count}/{VIDEO_DAILY_LIMIT}\n"
        f"✅ আরো পাবেন: {remaining}টি",
        show_alert=True,
    )


# ─── Support: user sends message to bot PM → forwarded to support group ───────

@Client.on_message(
    filters.private
    & ~filters.command(["start", "help", "video", "profile", "ban", "unban", "banlist",
                        "stats", "broadcast", "notifyusers", "addvideo", "delvideo", "cmdlist"])
    & ~filters.user(ADMIN_IDS)
    & (filters.text | filters.photo | filters.document | filters.audio | filters.voice | filters.sticker)
)
async def user_to_support(client, message):
    """Forward any plain user message to the support group."""
    if not SUPPORT_GROUP_ID:
        return

    user = message.from_user
    if not user:
        return

    name = user.first_name or user.username or "Unknown"
    username = f"@{user.username}" if user.username else "N/A"

    # Send header
    try:
        header = await client.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=(
                f"📩 <b>Support Message</b>\n\n"
                f"👤 Name: {name}\n"
                f"🔖 Username: {username}\n"
                f"🆔 ID: <code>{user.id}</code>"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        return

    # Forward the actual message
    try:
        forwarded = await message.forward(chat_id=SUPPORT_GROUP_ID)
        fwd_id = forwarded.id
    except Exception:
        fwd_id = None

    # Store mapping so admin replies go back to the user
    await support_msgs.insert_one({
        "user_id": user.id,
        "user_name": name,
        "username": user.username,
        "header_msg_id": header.id,
        "forwarded_msg_id": fwd_id,
        "sent_at": datetime.now(timezone.utc),
    })

    try:
        await message.reply_text(
            "✅ <b>আপনার message admin-এর কাছে পাঠানো হয়েছে।</b>\n\n"
            "একটু অপেক্ষা করুন, শীঘ্রই reply পাবেন 🙏",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


# ─── Support Group Reply → User ───────────────────────────────────────────────

_support_filter = (
    (filters.chat(SUPPORT_GROUP_ID) if SUPPORT_GROUP_ID else filters.chat([]))
    & filters.reply
    & filters.user(ADMIN_IDS)
    & ~filters.command(["broadcast", "stats", "addvideo", "delvideo", "notifyusers",
                        "cmdlist", "ban", "unban", "banlist"])
)

@Client.on_message(_support_filter)
async def support_reply_to_user(client, message):
    """Send the admin's reply back to the user."""
    reply_to = message.reply_to_message
    if not reply_to:
        return

    doc = await support_msgs.find_one({"forwarded_msg_id": reply_to.id})
    if not doc:
        doc = await support_msgs.find_one({"header_msg_id": reply_to.id})
    if not doc:
        return

    user_id = doc["user_id"]
    user_name = doc.get("user_name", "the user")

    try:
        await message.copy(chat_id=user_id)
        await message.reply_text(
            f"✅ <b>{user_name}</b>-কে পাঠানো হয়েছে।",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(
            f"❌ পাঠানো সম্ভব হয়নি!\n<code>{e}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
