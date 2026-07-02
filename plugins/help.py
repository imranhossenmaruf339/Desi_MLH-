from pyrogram import Client, filters

@Client.on_message(filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(
        "📌 <b>Commands:</b>\n\n"
        "/start — Start the bot\n"
        "/help — Show this menu\n"
        "/profile — Your profile & stats\n"
        "/video — Get a random video 🎬\n\n"
        "🕐 Video limit: <b>10 per 12 hours</b> (resets at 12 AM & 12 PM UTC)",
        parse_mode="html",
    )
