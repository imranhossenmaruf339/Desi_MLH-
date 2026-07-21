import asyncio
from datetime import datetime

from pyrogram import Client, filters, enums

from config import LOG_GROUP_ID, REQUIRED_GROUP_LINK
from database import users
from helpers import get_current_window_start, schedule_delete, is_rate_limited
from plugins.video import deliver_video


def _make_welcome_keyboard(bot_username: str):
    from urllib.parse import quote
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    bot_url = f"https://t.me/{bot_username}"
    share_text = quote(f"Watch exclusive videos! Try @{bot_username}", safe="")
    share_url = f"https://t.me/share/url?url={quote(bot_url, safe='')}&text={share_text}"

    rows = [
        [InlineKeyboardButton(
            "➕ Add Me To a Group",
            url=f"https://t.me/{bot_username}?startgroup=true",
        )],
    ]

    if REQUIRED_GROUP_LINK:
        rows.append([InlineKeyboardButton("👥 আমাদের Group-এ Join করুন", url=REQUIRED_GROUP_LINK)])

    rows.append([
        InlineKeyboardButton("📊 My Status", callback_data="my_status"),
        InlineKeyboardButton("📢 Share Bot", url=share_url),
    ])

    return InlineKeyboardMarkup(rows)


WELCOME_TEXT = """━━━━━━━━━━━━━━━━━━━
✨🎬  <b>WELCOME</b> 🎬✨
━━━━━━━━━━━━━━━━━━━
👑 স্বাগতম <b>{name}</b> ! 👑
আমাদের Video Community-তে আপনাকে স্বাগত জানাই 🎥

🔥 ভিডিও দেখতে ব্যবহার করুন:
👉 /video
━━━━━━━━━━━━━━━━━━━
📜 নিয়মাবলী
━━━━━━━━━━━━━━━━━━━
✅ সবার সাথে সম্মানজনক আচরণ করুন
✅ Spam করবেন না
✅ অবৈধ কন্টেন্ট শেয়ার করবেন না
✅ Admin-এর নির্দেশ মেনে চলুন
⚠️ নিয়ম ভাঙলে = তাৎক্ষণিক Remove
━━━━━━━━━━━━━━━━━━━"""


@Client.on_message(filters.command("start") & (filters.private | filters.group))
async def start(client, message):
    if not message.from_user:
        return

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
        await users.update_one(
            {"user_id": user_id},
            {"$set": {
                "username": user.username,
                "first_name": user.first_name or "",
            }},
        )
        status_label = "🔁 Returning user"

    # Deep-link: /start video
    args = message.text.split(None, 1)
    deep_link = args[1].strip() if len(args) > 1 else ""

    if deep_link == "video" and not in_group:
        from config import ADMIN_IDS
        if user_id not in ADMIN_IDS:
            wait = is_rate_limited(user_id, cooldown=3.0)
            if wait > 0:
                await message.reply_text(
                    f"⏳ একটু ধীরে! <b>{wait:.1f} seconds</b> পরে আবার চেষ্টা করুন।",
                    parse_mode=enums.ParseMode.HTML,
                )
                return

        try:
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=(
                    f"👤 <b>User Started Bot</b>\n\n"
                    f"📛 Name: {user.first_name or ''} {user.last_name or ''}\n"
                    f"🔖 Username: {username}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"📌 Status: {status_label} (via group button)"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            print(f"[LOG-SEND-FAILED] start.py deep-link notice: {e!r}")
        await deliver_video(client, user_id, message.chat.id)
        return

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
    except Exception as e:
        print(f"[LOG-SEND-FAILED] start.py start notice: {e!r}")

    import bot_info
    name = user.first_name or user.username or "Friend"
    keyboard = _make_welcome_keyboard(bot_info.BOT_USERNAME) if bot_info.BOT_USERNAME else None

    sent = await message.reply_text(
        WELCOME_TEXT.format(name=name),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=keyboard,
    )

    if in_group and sent:
        asyncio.create_task(schedule_delete(client, message.chat.id, sent.id, 30))
