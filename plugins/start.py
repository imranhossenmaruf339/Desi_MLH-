from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import OWNER_ID
from database import users
from helpers import get_current_window_start


@Client.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    user = message.from_user
    username = f"@{user.username}" if user.username else "N/A"

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
        })
        status_label = "🆕 New user"
    else:
        status_label = "🔁 Returning user"

    # Notify the admin every time someone starts the bot
    try:
        await client.send_message(
            chat_id=OWNER_ID,
            text=(
                f"👤 <b>User Started Bot</b>\n\n"
                f"📛 Name: {user.first_name or ''} {user.last_name or ''}\n"
                f"🔖 Username: {username}\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📌 Status: {status_label}"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply_text(
        "👋 <b>Welcome to UnityBot!</b>\n\n"
        "Use /help to see available commands.",
        parse_mode=enums.ParseMode.HTML,
    )
