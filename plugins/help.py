from pyrogram import Client, filters, enums


@Client.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(
        "📌 <b>Commands:</b>\n\n"
        "/start — Start the bot\n"
        "/help — Show this menu\n"
        "/profile — Your profile & stats\n"
        "/video — Get a random video 🎬\n\n"
        "🕐 Video limit: <b>10 per 12 hours</b>\n"
        "Resets at 12:00 AM &amp; 12:00 PM UTC daily.",
        parse_mode=enums.ParseMode.HTML,
    )
