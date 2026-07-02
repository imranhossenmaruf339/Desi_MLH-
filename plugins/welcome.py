from pyrogram import Client, filters, enums

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


@Client.on_message(filters.new_chat_members & filters.group)
async def welcome_new_member(client, message):
    """Send welcome message when a user joins any group where the bot is a member."""
    me = await client.get_me()

    for member in message.new_chat_members:
        # Don't welcome the bot itself
        if member.id == me.id:
            continue
        # Don't welcome other bots
        if member.is_bot:
            continue

        name = member.first_name or member.username or "Friend"
        await message.reply_text(
            WELCOME_TEXT.format(name=name),
            parse_mode=enums.ParseMode.HTML,
        )
