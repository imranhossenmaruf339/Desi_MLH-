import bot_info
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, VIP_CHANNEL_LINK
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

    # Resolve private VIP channel ID so membership checks work
    try:
        vip_chat = await app.get_chat(VIP_CHANNEL_LINK)
        bot_info.VIP_CHANNEL_ID = vip_chat.id
        print(f"VIP channel resolved: {bot_info.VIP_CHANNEL_ID}")
    except Exception as e:
        print(f"Warning: Could not resolve VIP channel ID: {e}")

    print("Bot Started...")
    await idle()
    await app.stop()


app.run(main())
