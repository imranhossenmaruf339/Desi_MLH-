import bot_info
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, VIP_CHANNEL_ID
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
    me = await app.get_me()
    bot_info.BOT_USERNAME = me.username or ""
    bot_info.BOT_ID = me.id
    bot_info.VIP_CHANNEL_ID = VIP_CHANNEL_ID
    if VIP_CHANNEL_ID:
        print(f"VIP channel ID loaded: {VIP_CHANNEL_ID}")
    else:
        print("Warning: VIP_CHANNEL_ID not set — channel membership checks will be skipped.")
    print("Bot Started...")
    await idle()
    await app.stop()


app.run(main())
