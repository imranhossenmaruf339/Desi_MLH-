from pyrogram import Client, filters, enums
from config import VIDEO_DAILY_LIMIT


@Client.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(
        "📌 <b>Commands:</b>\n\n"
        "/start — Start the bot\n"
        "/help — Show this menu\n"
        "/profile — Your profile & stats\n"
        "/video — Get a random video 🎬\n\n"
        f"🕐 Video limit: <b>{VIDEO_DAILY_LIMIT} per 12 hours</b>\n"
        "Resets at 12:00 AM & 12:00 PM UTC daily.",
        parse_mode=enums.ParseMode.HTML,
    )
