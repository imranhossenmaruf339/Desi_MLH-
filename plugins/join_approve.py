"""
Auto-approve join requests for the required group.
When a user sends a join request to REQUIRED_GROUP_ID, the bot
automatically approves it so they can start receiving videos.
"""

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import REQUIRED_GROUP_ID, REQUIRED_GROUP_LINK, LOG_GROUP_ID, ADMIN_IDS
from database import users
from helpers import get_current_window_start
from datetime import datetime, timezone


@Client.on_chat_join_request(
    filters.chat(REQUIRED_GROUP_ID) if REQUIRED_GROUP_ID else filters.chat([])
)
async def auto_approve_join_request(client, join_request):
    """Auto-approve every join request to the required group."""
    user = join_request.from_user
    user_id = user.id

    try:
        await join_request.approve()
    except Exception as e:
        print(f"[JOIN-APPROVE-FAILED] Could not approve {user_id}: {e!r}")
        return

    # Make sure the user exists in the DB
    existing = await users.find_one({"user_id": user_id})
    if not existing:
        window = get_current_window_start()
        await users.insert_one({
            "user_id": user_id,
            "username": user.username,
            "first_name": user.first_name or "",
            "points": 0,
            "referrals": 0,
            "video_count": 0,
            "video_window_start": window,
            "joined_at": datetime.now(timezone.utc),
        })

    # Welcome message to the user in PM
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 Get Video", callback_data="next_video")],
        ])
        await client.send_message(
            chat_id=user_id,
            text=(
                "✅ <b>আপনার Join Request Approve হয়েছে!</b>\n\n"
                "🎉 এখন আপনি ভিডিও দেখতে পারবেন।\n"
                "👇 নিচের বাটনে ক্লিক করুন অথবা /video লিখুন।"
            ),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        pass  # user may not have started the bot yet — that's fine

    # Log to monitor group
    if LOG_GROUP_ID:
        try:
            username = f"@{user.username}" if user.username else "N/A"
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=(
                    "✅ <b>Join Request Approved</b>\n\n"
                    f"👤 Name: {user.first_name or ''} {user.last_name or ''}\n"
                    f"🔖 Username: {username}\n"
                    f"🆔 ID: <code>{user_id}</code>"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            print(f"[LOG-SEND-FAILED] join_approve.py: {e!r}")
