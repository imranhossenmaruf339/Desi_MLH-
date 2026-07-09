import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGO_URL")

_video_channel_raw = os.getenv("VIDEO_CHANNEL_ID", "-1002623940581")
try:
    VIDEO_CHANNEL_ID = int(_video_channel_raw)
except (ValueError, TypeError):
    VIDEO_CHANNEL_ID = -1002623940581

JOIN_CHANNEL_LINK = os.getenv("JOIN_CHANNEL_LINK", "https://t.me/+YTZcUp9h0qYwNjc1")
VIP_CHANNEL_LINK  = os.getenv("VIP_CHANNEL_LINK", "https://t.me/+QuC95d9R5zI2MTM9")

_vip_raw = os.getenv("VIP_CHANNEL_ID", "")
try:
    VIP_CHANNEL_ID = int(_vip_raw) if _vip_raw else None
except (ValueError, TypeError):
    VIP_CHANNEL_ID = None

JOIN_CHANNEL_2_LINK     = os.getenv("JOIN_CHANNEL_2_LINK", "https://t.me/the_couple_vibe")
JOIN_CHANNEL_2_USERNAME = os.getenv("JOIN_CHANNEL_2_USERNAME", "the_couple_vibe")
VIDEO_DAILY_LIMIT = int(os.getenv("VIDEO_DAILY_LIMIT", "10"))

_log_group_raw = os.getenv("LOG_GROUP_ID")
LOG_GROUP_ID = int(_log_group_raw) if _log_group_raw else OWNER_ID
