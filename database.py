import sys
import motor.motor_asyncio
from config import MONGO_URI

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
banned_users = db.banned_users               # users banned by admin


async def ensure_indexes():
    """Create indexes required for correct and efficient operation."""
    # Fast lookup of recent history per user (used on every /video call)
    await user_video_history.create_index(
        [("user_id", 1), ("sent_at", -1)],
        name="user_history_lookup",
    )
    # Compound index to quickly check if a specific video was sent to a user
    await user_video_history.create_index(
        [("user_id", 1), ("video_id", 1)],
        name="user_video_pair",
    )
    # Fast lookup of banned users
    await banned_users.create_index(
        [("user_id", 1)],
        name="banned_user_lookup",
        unique=True,
    )
    # Group video stats lookup
    await group_video_stats.create_index(
        [("user_id", 1), ("group_id", 1), ("window_start", 1)],
        name="group_video_stats_lookup",
    )
