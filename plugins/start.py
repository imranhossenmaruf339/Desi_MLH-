from pyrogram import Client, filters, enums

from config import LOG_GROUP_ID
from database import users
from helpers import get_current_window_start
from plugins.welcome import WELCOME_TEXT


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

    # Notify the log group every time someone starts the bot
    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
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

    # Send welcome message using the shared template
    name = user.first_name or user.username or "Friend"
    await message.reply_text(
        WELCOME_TEXT.format(name=name),
        parse_mode=enums.ParseMode.HTML,
    )
