import sys
import motor.motor_asyncio
from config import MONGO_URI

# The bot won't start without MONGO_URI — already checked in config.py,
# but double-check here too for safety.
if not MONGO_URI:
    print("[ERROR] MONGO_URI is not set. Shutting down.")
    sys.exit(1)

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client["UnityBot"]

users = db.users
referrals = db.referrals
daily = db.daily
videos = db.videos
premium = db.premium
logs = db.logs
video_requests = db.video_requests
user_video_history = db.user_video_history   # tracks which videos each user has seen (7-day cooldown)
groups = db.groups                           # groups the bot has been added to
support_msgs = db.support_msgs               # user_id <-> support group message mapping
group_video_stats = db.group_video_stats     # per-user group video count per 12h window


async def ensure_indexes():
    """Create indexes required for correct and efficient operation."""
    # Fast lookup of recent history per user (used on every /video call)
    await user_video_history.create_index(
        [("user_id", 1), ("sent_at", -1)],
        name="user_history_lookup",
    )
    # Compound index to quickly check if a specific video was sent to a user
    await user_video_history.create_index(
        [("user_id", 1), ("video_id", 1), ("sent_at", -1)],
        name="user_video_sent",
    )
    # TTL index: automatically expire history documents after 7 days
    await user_video_history.create_index(
        [("sent_at", 1)],
        expireAfterSeconds=7 * 24 * 3600,
        name="history_ttl",
    )
    # Users lookup by user_id
    await users.create_index([("user_id", 1)], unique=True, name="users_uid")
    # Duplicate video check — fast lookup by file_unique_id
    await videos.create_index(
        [("file_unique_id", 1)],
        sparse=True,
        name="videos_unique_id",
    )
