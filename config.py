import os
import sys
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")

# Multiple Admins support
_admin_ids_raw = os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(i.strip()) for i in _admin_ids_raw.split(",") if i.strip().isdigit()]
OWNER_ID = ADMIN_IDS[0] if ADMIN_IDS else 0

MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGO_URL")

VIDEO_CHANNEL_ID = int(os.getenv("VIDEO_CHANNEL_ID", "-1002623940581"))
LOG_GROUP_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

JOIN_CHANNEL_LINK = os.getenv("VIP_CHANNEL1_LINK", "https://t.me/+YTZcUp9h0qYwNjc1")

# Fix: .env-এ VIP_CHANNEL_LINK নামে সেট করুন (আগে VIP_CHANNEL2_LINK ছিল — ভুল নাম)
VIP_CHANNEL_LINK = os.getenv("VIP_CHANNEL_LINK", "https://t.me/+ob96Z-mZmjBjNGQ1")

# VIP_CHANNEL_ID is needed for membership check
_vip_raw = os.getenv("VIP_CHANNEL_ID", "")
try:
    VIP_CHANNEL_ID = int(_vip_raw) if _vip_raw else None
except (ValueError, TypeError):
    VIP_CHANNEL_ID = None

JOIN_CHANNEL_2_LINK     = os.getenv("JOIN_CHANNEL_2_LINK", "https://t.me/the_couple_vibe")
JOIN_CHANNEL_2_USERNAME = os.getenv("JOIN_CHANNEL_2_USERNAME", "the_couple_vibe")
VIDEO_DAILY_LIMIT = int(os.getenv("VIDEO_DAILY_LIMIT", "10"))
GROUP_VIDEO_LIMIT = int(os.getenv("GROUP_VIDEO_LIMIT", "5"))   # গ্রুপে প্রতি ইউজার প্রতি 12 ঘন্টায় সর্বোচ্চ ভিডিও
SUPPORT_GROUP_ID  = int(os.getenv("SUPPORT_GROUP_ID", "-1003876863435"))  # সাপোর্ট ইনবক্স গ্রুপ

# ── Required variable validation ─────────────────────────────────────────────
_missing = []
if not BOT_TOKEN:
    _missing.append("BOT_TOKEN")
if not API_HASH or API_ID == 0:
    _missing.append("API_ID / API_HASH")
if not MONGO_URI:
    _missing.append("MONGO_URI")
if not ADMIN_IDS:
    _missing.append("ADMIN_ID")

if _missing:
    print(f"[ERROR] এই environment variable(s) সেট করা নেই: {', '.join(_missing)}")
    print("[ERROR] .env ফাইল বা deployment platform-এ variable গুলো সেট করুন।")
    sys.exit(1)
