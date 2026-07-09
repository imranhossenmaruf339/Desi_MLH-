import os
from dotenv import load_dotenv

load_dotenv()

# ─── সরাসরি আপনার তথ্যগুলো নিচে বসান ──────────────────────────────────────────
# মনে রাখবেন: রিপোজিটরি অবশ্যই PRIVATE করে রাখবেন।

BOT_TOKEN = os.getenv("BOT_TOKEN", "এখানে_বটের_টোকেন_বসান")
API_ID = int(os.getenv("API_ID", "0"))  # এখানে API ID বসান (যেমন: 123456)
API_HASH = os.getenv("API_HASH", "এখানে_API_HASH_বসান")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # এখানে আপনার আইডি বসান
MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGO_URL") or "এখানে_MONGO_URI_বসান"

VIDEO_CHANNEL_ID = int(os.getenv("VIDEO_CHANNEL_ID", "-1002623940581")) # ভিডিও চ্যানেল আইডি
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID", "0")) # লগ গ্রুপ আইডি (এখানে বসান)

# ─── অন্যান্য কনফিগারেশন ──────────────────────────────────────────────────────

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
