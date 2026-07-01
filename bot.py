from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN

app = Client(
    "UnityBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Import handler modules so their decorators register on the Client
import start
import help
import profile

print("Bot Started...")
app.run()