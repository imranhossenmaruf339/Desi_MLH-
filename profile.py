from pyrogram import Client, filters
from database import users

@Client.on_message(filters.command("profile"))
async def profile(client, message):
    user = await users.find_one({"user_id": message.from_user.id})

    if not user:
        return await message.reply("User not found.")

    await message.reply_text(
        f"👤 Profile\n\n"
        f"ID: {user['user_id']}\n"
        f"Points: {user.get('points', 0)}\n"
        f"Referrals: {user.get('referrals', 0)}"
    )
