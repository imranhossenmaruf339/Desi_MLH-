import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGO_URL")

VIDEO_CHANNEL_ID = -1002623940581
JOIN_CHANNEL_LINK = "https://t.me/+YTZcUp9h0qYwNjc1"       # button 1 URL
JOIN_CHANNEL_2_LINK = "https://t.me/the_couple_vibe"        # button 2 URL (membership enforced)
JOIN_CHANNEL_2_USERNAME = "the_couple_vibe"                 # username used for get_chat_member check
VIDEO_DAILY_LIMIT = 10

# Group where user-start / user-blocked notifications are sent.
# Set LOG_GROUP_ID env var to your group's chat ID (negative number for supergroups).
# Falls back to the owner's DM if not configured.
_log_group_raw = os.getenv("LOG_GROUP_ID")
LOG_GROUP_ID = int(_log_group_raw) if _log_group_raw else OWNER_ID
