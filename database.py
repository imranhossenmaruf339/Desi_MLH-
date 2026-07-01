import motor.motor_asyncio
from config import MONGO_URI

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client["UnityBot"]

users = db.users
referrals = db.referrals
daily = db.daily
videos = db.videos
premium = db.premium
logs = db.logs
