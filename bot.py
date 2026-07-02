from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN
from database import ensure_indexes

app = Client(
    "UnityBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)


async def main():
    await ensure_indexes()
    await app.start()
    print("Bot Started...")
    await idle()
    await app.stop()


app.run(main())
