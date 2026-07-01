from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN

app = Client(
    "UnityBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

@app.on_message()
async def hello(client, message):
    if message.text == "/start":
        await message.reply_text("✅ Bot is running successfully!")

print("Bot Started...")
app.run()