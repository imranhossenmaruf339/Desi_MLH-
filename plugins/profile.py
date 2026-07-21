"""
Improved /profile command — shows user stats, watch history, and rank.
"""

from datetime import datetime, timezone
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import users, user_video_history, videos


async def _get_rank(user_id: int) -> tuple[int, int]:
    """Return (rank, total_users) based on total videos watched (all-time)."""
    history_counts = await user_video_history.aggregate([
        {"$group": {"_id": "$user_id", "total": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]).to_list(length=None)

    total_users = len(history_counts)
    rank = next(
        (i + 1 for i, h in enumerate(history_counts) if h["_id"] == user_id),
        total_users,
    )
    return rank, total_users


@Client.on_message(filters.command("profile") & (filters.private | filters.group))
async def profile(client, message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    user = await users.find_one({"user_id": user_id})
    if not user:
        await message.reply_text(
            "⚠️ আপনার প্রোফাইল পাওয়া যায়নি। /start দিয়ে শুরু করুন।"
        )
        return

    # Rank
    rank, total_users = await _get_rank(user_id)

    # Total watched (all-time)
    total_watched = await user_video_history.count_documents({"user_id": user_id})

    # Current 12h window count
    from helpers import get_current_window_start
    from config import VIDEO_DAILY_LIMIT
    current_window = get_current_window_start()
    user_window = user.get("video_window_start")
    window_count = user.get("video_count", 0) if user_window == current_window else 0

    # Last 5 watched videos (history)
    recent_history = await user_video_history.find(
        {"user_id": user_id},
        {"video_id": 1, "sent_at": 1},
    ).sort("sent_at", -1).limit(5).to_list(length=5)

    history_lines = ""
    for i, h in enumerate(recent_history, 1):
        sent_at = h.get("sent_at")
        if sent_at:
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            date_str = sent_at.strftime("%d %b %Y, %I:%M %p")
        else:
            date_str = "Unknown"
        history_lines += f"  {i}. 🎬 {date_str}\n"

    if not history_lines:
        history_lines = "  এখনো কোনো ভিডিও দেখেননি।\n"

    # Rank emoji
    if rank == 1:
        rank_emoji = "🥇"
    elif rank == 2:
        rank_emoji = "🥈"
    elif rank == 3:
        rank_emoji = "🥉"
    elif rank <= 10:
        rank_emoji = "⭐"
    else:
        rank_emoji = "👤"

    # Joined date
    joined_at = user.get("joined_at")
    if joined_at:
        if hasattr(joined_at, "tzinfo") and joined_at.tzinfo is None:
            joined_at = joined_at.replace(tzinfo=timezone.utc)
        joined_str = joined_at.strftime("%d %b %Y")
    else:
        joined_str = "Unknown"

    name = user.get("first_name") or "User"
    username = f"@{user.get('username')}" if user.get("username") else "N/A"

    text = (
        "━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>প্রোফাইল — {name}</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🔖 Username: {username}\n"
        f"📅 যোগদান: {joined_str}\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>পরিসংখ্যান</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"{rank_emoji} Rank: <b>#{rank}</b> / {total_users} জন\n"
        f"🎬 মোট ভিডিও দেখেছেন: <b>{total_watched}</b>\n"
        f"⏱ এই Window-এ: <b>{window_count}</b> / {VIDEO_DAILY_LIMIT}\n"
        f"💎 Points: <b>{user.get('points', 0)}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📜 <b>সাম্প্রতিক ইতিহাস</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"{history_lines}"
        "━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 ভিডিও দেখুন", callback_data="next_video")],
    ])

    await message.reply_text(
        text,
        parse_mode=enums.ParseMode.HTML,
        reply_markup=keyboard,
    )
