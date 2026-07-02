from pyrogram import Client, filters
from database import users

@Client.on_message(filters.command("start"))
async def start(client, message):
    user_id = message.from_user.id

    user = await users.find_one({"user_id": user_id})

    if not user:
        await users.insert_one({
            "user_id": user_id,
            "username": message.from_user.username,
            "points": 0,
            "referrals": 0
        })

    await message.reply_text(
        "👋 Welcome to UnityBot!\n\n"
        "Use /help to see commands."
    )
