import asyncio
from datetime import datetime

from pyrogram import Client, filters, enums

from config import LOG_GROUP_ID
from database import users
from helpers import get_current_window_start, schedule_delete


def _make_welcome_keyboard(bot_username: str):
    from urllib.parse import quote
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    bot_url = f"https://t.me/{bot_username}"
    share_text = quote(f"Watch exclusive videos! Try @{bot_username}", safe="")
    share_url = f"https://t.me/share/url?url={quote(bot_url, safe='')}&text={share_text}"

    return InlineKeyboardMarkup([
        # Row 1 — add bot to a group
        [InlineKeyboardButton(
            "➕ Add Me To a Group",
            url=f"https://t.me/{bot_username}?startgroup=true",
        )],
        # Row 2 — VIP channel + buy premium
        [
            InlineKeyboardButton("💎 VIP Channel", url="https://t.me/+YcRBja2GjY4xMmRl"),
            InlineKeyboardButton("💳 Buy Premium", url="https://t.me/GhostinWhispers1"),
        ],
        # Row 3 — my status + share bot
        [
            InlineKeyboardButton("📊 My Status", callback_data="my_status"),
            InlineKeyboardButton("📢 Share Bot", url=share_url),
        ],
    ])


WELCOME_TEXT = """━━━━━━━━━━━━━━━━━━━
✨🎬  𝗪𝗘𝗟𝗖𝗢𝗠𝗘 🎬✨
━━━━━━━━━━━━━━━━━━━
👑 Welcome <b>{name}</b> ! 👑
You are now a member of our Video Community 🎥

🔥 To watch videos use:
👉 /video
━━━━━━━━━━━━━━━━━━━
📜 RULES
━━━━━━━━━━━━━━━━━━━
✅ Be respectful
✅ No spam
✅ No illegal content
✅ Follow admin rules
⚠️ Rule violation = Instant remove
━━━━━━━━━━━━━━━━━━━"""


# /start in private chat OR in a group
@Client.on_message(filters.command("start") & (filters.private | filters.group))
async def start(client, message):
    if not message.from_user:
        return   # anonymous admin in group — ignore

    user_id = message.from_user.id
    user = message.from_user
    username = f"@{user.username}" if user.username else "N/A"
    in_group = message.chat.type != enums.ChatType.PRIVATE

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
            "joined_at": datetime.utcnow(),
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

    import bot_info
    name = user.first_name or user.username or "Friend"
    keyboard = _make_welcome_keyboard(bot_info.BOT_USERNAME) if bot_info.BOT_USERNAME else None

    sent = await message.reply_text(
        WELCOME_TEXT.format(name=name),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=keyboard,
    )

    # Auto-delete /start reply in groups after 30 seconds
    if in_group and sent:
        asyncio.create_task(schedule_delete(client, message.chat.id, sent.id, 30))
