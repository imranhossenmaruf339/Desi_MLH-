import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGO_URL")

VIDEO_CHANNEL_ID = -1002623940581
JOIN_CHANNEL_LINK = "https://t.me/+YTZcUp9h0qYwNjc1"
VIDEO_DAILY_LIMIT = 10
