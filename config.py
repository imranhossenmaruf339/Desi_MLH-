import os
import sys
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH")

# Multiple Admins support
_admin_ids_raw = os.getenv("ADMIN_ID", "")
ADMIN_IDS = [int(i.strip()) for i in _admin_ids_raw.split(",") if i.strip().isdigit()]
OWNER_ID  = ADMIN_IDS[0] if ADMIN_IDS else 0

MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGO_URL")

VIDEO_CHANNEL_ID    = int(os.getenv("VIDEO_CHANNEL_ID", "0"))
LOG_GROUP_ID        = int(os.getenv("LOG_CHANNEL_ID", "0"))       # monitor group
CONTROL_GROUP_ID    = int(os.getenv("CONTROL_GROUP_ID", "0"))     # admin control panel group
DISCUSSION_GROUP_ID = int(os.getenv("DISCUSSION_GROUP_ID", "0"))  # linked comments group of VIDEO_CHANNEL_ID

# ── Required Group (Force Join) ───────────────────────────────────────────────
_required_group_raw = os.getenv("REQUIRED_GROUP_ID", "")
try:
    REQUIRED_GROUP_ID = int(_required_group_raw) if _required_group_raw else None
except (ValueError, TypeError):
    REQUIRED_GROUP_ID = None

REQUIRED_GROUP_LINK = os.getenv("REQUIRED_GROUP_LINK", "")

SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))

VIDEO_DAILY_LIMIT = int(os.getenv("VIDEO_DAILY_LIMIT", "10"))
GROUP_VIDEO_LIMIT = int(os.getenv("GROUP_VIDEO_LIMIT", "5"))

# ── Required variable validation ─────────────────────────────────────────────
_missing = []
if not BOT_TOKEN:         _missing.append("BOT_TOKEN")
if not API_HASH or API_ID == 0: _missing.append("API_ID / API_HASH")
if not MONGO_URI:         _missing.append("MONGO_URI")
if not ADMIN_IDS:         _missing.append("ADMIN_ID")

if _missing:
    print(f"[ERROR] Missing required environment variable(s): {', '.join(_missing)}")
    sys.exit(1)

if not REQUIRED_GROUP_ID:
    print("[WARNING] REQUIRED_GROUP_ID not set — force-join disabled.")
if LOG_GROUP_ID == 0:
    print("[WARNING] LOG_CHANNEL_ID not set — monitor group disabled.")
if CONTROL_GROUP_ID == 0:
    print("[WARNING] CONTROL_GROUP_ID not set — control group disabled.")
if DISCUSSION_GROUP_ID == 0:
    print("[WARNING] DISCUSSION_GROUP_ID not set — comment monitoring disabled.")
