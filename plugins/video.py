import asyncio
import random
from datetime import datetime, timedelta

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import JOIN_CHANNEL_LINK, VIP_CHANNEL_LINK, VIDEO_DAILY_LIMIT, OWNER_ID, LOG_GROUP_ID
from database import users, videos, user_video_history, groups
from helpers import get_current_window_start, schedule_delete


async def _log(client, text: str):
    """Send a log message to the monitor group — never raises."""
    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=text,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


# ─── Shared button builders ───────────────────────────────────────────────────

def _join_buttons():
    """Two channel join buttons shown under every video."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("JOIN", url=JOIN_CHANNEL_LINK),
            InlineKeyboardButton("JOIN", url=VIP_CHANNEL_LINK),
        ],
        [InlineKeyboardButton("🎬 আরেকটি ভিডিও পান", callback_data="next_video")],
    ])


def _group_prompt_buttons(bot_username: str):
    """Button shown in groups — deep-links user to bot PM to get video."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎬 ভিডিও দেখুন",
            url=f"https://t.me/{bot_username}?start=video",
        )],
    ])


async def _delete_after(client, chat_id: int, message_id: int, delay: int = 1800):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


# ─── Core video-delivery logic (called from PM handler AND /start deeplink) ──

async def deliver_video(client, user_id: int, chat_id: int, reply_to=None):
    """
    Fetch an unseen video for user_id and send it to chat_id.
    Returns (success: bool, error_msg: str | None).
    Skips the daily limit entirely for OWNER_ID.
    """
    is_admin = (user_id == OWNER_ID)

    # ── Ensure user record ───────────────────────────────────────────────────
    user = await users.find_one({"user_id": user_id})
    if not user:
        window = get_current_window_start()
        await users.insert_one({
            "user_id": user_id,
            "username": None,
            "first_name": "",
            "points": 0,
            "referrals": 0,
            "video_count": 0,
            "video_window_start": window,
            "joined_at": datetime.utcnow(),
        })
        user = await users.find_one({"user_id": user_id})

    # ── 12-hour window reset ─────────────────────────────────────────────────
    current_window = get_current_window_start()
    user_window = user.get("video_window_start")
    video_count = user.get("video_count", 0)

    if user_window != current_window:
        video_count = 0
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"video_count": 0, "video_window_start": current_window}},
        )

    # ── Daily limit (admin always bypasses) ──────────────────────────────────
    if not is_admin and video_count >= VIDEO_DAILY_LIMIT:
        name      = user.get("first_name") or "Unknown"
        uname     = f"@{user['username']}" if user.get("username") else "no username"
        now_str   = datetime.utcnow().strftime("%d %b %Y, %I:%M %p UTC")

        # Notify monitor group that this user just hit their limit
        await _log(
            client,
            f"🚫 <b>লিমিট শেষ হয়েছে!</b>\n\n"
            f"👤 Name: <b>{name}</b>\n"
            f"🔖 Username: {uname}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📊 Used: <b>{video_count}/{VIDEO_DAILY_LIMIT}</b> videos\n"
            f"🕐 Time: {now_str}",
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📢 Channel 1", url=JOIN_CHANNEL_LINK),
                InlineKeyboardButton("💎 VIP Channel", url=VIP_CHANNEL_LINK),
            ],
            [InlineKeyboardButton("✅ Confirmed — Unlock +15 Videos", callback_data=f"confirm_join:{user_id}")],
        ])
        await client.send_message(
            chat_id=chat_id,
            text=(
                "🔥 <b>Daily Limit Reached!</b>\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
                "⏰ Come back after <b>12:00</b> for a free reset.\n\n"
                "💡 <b>Want more right now?</b>\n"
                "Join our channels and unlock <b>+15 bonus videos</b> instantly!\n\n"
                "🎬 <i>Our VIP Channel drops exclusive, never-seen content daily — "
                "hot videos, behind-the-scenes, and members-only drops you won't find anywhere else.</i>\n\n"
                "👇 <b>Join both channels below, then tap Confirmed:</b>"
            ),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
        return False, "limit"

    # ── Pick unseen video ────────────────────────────────────────────────────
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent = await user_video_history.find(
        {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}},
        {"video_id": 1},
    ).to_list(length=None)
    seen_ids = {h["video_id"] for h in recent}

    all_vids = await videos.find().to_list(length=None)
    pool = [v for v in all_vids if v["_id"] not in seen_ids]

    if not pool and all_vids:
        await client.send_message(
            chat_id=chat_id,
            text=(
                "🎬 <b>You've watched all available videos!</b>\n\n"
                "New videos will be added soon. You'll be notified when they arrive! 🔔\n\n"
                "Come back in a few days — watched videos also refresh after <b>7 days</b>."
            ),
            parse_mode=enums.ParseMode.HTML,
        )
        return False, "no_pool"

    if not pool:
        await client.send_message(
            chat_id=chat_id,
            text="❌ <b>No videos available yet.</b>\n\nPlease check back later!",
            parse_mode=enums.ParseMode.HTML,
        )
        return False, "empty"

    video_doc = random.choice(pool)
    file_id = video_doc.get("file_id")
    file_type = video_doc.get("file_type", "video")

    # ── Remaining count hint (not shown to admin — they have no limit) ───────
    remaining = (VIDEO_DAILY_LIMIT - video_count - 1) if not is_admin else None
    remaining_text = (
        f"\n\n📹 <i>আপনার কাছে এই উইন্ডোতে আরও <b>{remaining}</b>টি ভিডিও বাকি আছে।</i>"
        if remaining is not None and remaining >= 0
        else ""
    )

    caption = (video_doc.get("caption", "") or "") + remaining_text

    # ── Send video ───────────────────────────────────────────────────────────
    sent = None
    spoiler_err = None

    if file_type == "video":
        try:
            sent = await client.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=caption,
                has_spoiler=True,
                supports_streaming=True,
                duration=video_doc.get("duration", 0),
                width=video_doc.get("width", 0),
                height=video_doc.get("height", 0),
                reply_markup=_join_buttons(),
            )
        except Exception as e:
            spoiler_err = str(e)

    if sent is None:
        try:
            sent = await client.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=caption,
                supports_streaming=True,
                duration=video_doc.get("duration", 0),
                width=video_doc.get("width", 0),
                height=video_doc.get("height", 0),
                reply_markup=_join_buttons(),
            )
        except Exception:
            try:
                sent = await client.send_document(
                    chat_id=chat_id,
                    document=file_id,
                    caption=caption,
                    reply_markup=_join_buttons(),
                )
            except Exception as e:
                await client.send_message(
                    chat_id=chat_id,
                    text=f"❌ Failed to send video. Please try again.\n<code>{e}</code>",
                    parse_mode=enums.ParseMode.HTML,
                )
                return False, str(e)

    # ── Auto-delete after 30 minutes ─────────────────────────────────────────
    if sent:
        asyncio.create_task(_delete_after(client, chat_id, sent.id, delay=1800))

    # ── Record history + increment counter (admin counter also tracked) ───────
    await user_video_history.insert_one({
        "user_id": user_id,
        "video_id": video_doc["_id"],
        "sent_at": datetime.utcnow(),
    })
    new_count = video_count + 1
    if not is_admin:
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"video_count": new_count}},
        )

    # ── Log to monitor group ──────────────────────────────────────────────────
    name    = user.get("first_name") or "Unknown"
    uname   = f"@{user['username']}" if user.get("username") else "no username"
    now_str = datetime.utcnow().strftime("%d %b %Y, %I:%M %p UTC")
    total_watched = await user_video_history.count_documents({"user_id": user_id})

    if is_admin:
        count_line = "📊 Count: <b>Admin (no limit)</b>"
    else:
        remaining = max(0, VIDEO_DAILY_LIMIT - new_count)
        count_line = f"📊 Count: <b>{new_count}/{VIDEO_DAILY_LIMIT}</b> (remaining: {remaining})"

    await _log(
        client,
        f"🎬 <b>ভিডিও পাঠানো হয়েছে</b>\n\n"
        f"👤 Name: <b>{name}</b>\n"
        f"🔖 Username: {uname}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"{count_line}\n"
        f"🎞 Total ever watched: <b>{total_watched}</b>\n"
        f"🕐 Time: {now_str}",
    )

    return True, None


# ─── /video command handler ───────────────────────────────────────────────────

@Client.on_message(filters.command("video") & (filters.private | filters.group))
async def video_cmd(client, message):
    if not message.from_user:
        await message.reply_text("❌ Cannot identify user. Please disable anonymous mode.")
        return

    user_id = message.from_user.id
    in_group = message.chat.type != enums.ChatType.PRIVATE

    # ── Auto-register group ───────────────────────────────────────────────────
    if in_group:
        await groups.update_one(
            {"group_id": message.chat.id},
            {"$set": {"group_id": message.chat.id, "title": message.chat.title or ""}},
            upsert=True,
        )

    # ── In a group: never send video directly — show Bangla prompt + button ──
    if in_group:
        import bot_info
        bot_username = bot_info.BOT_USERNAME or "this_bot"

        sent = await message.reply_text(
            "🎬 <b>ভিডিও দেখতে নিচের বাটনে ক্লিক করুন</b>\n\n"
            "বাটনে ক্লিক করলে বট আপনাকে সরাসরি প্রাইভেট মেসেজে ভিডিও পাঠাবে। 🔒",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_group_prompt_buttons(bot_username),
        )
        # Auto-delete group prompt after 60 seconds
        asyncio.create_task(schedule_delete(client, message.chat.id, sent.id, 60))
        # Also delete the user's /video command message
        asyncio.create_task(schedule_delete(client, message.chat.id, message.id, 5))
        return

    # ── Private chat: deliver directly ───────────────────────────────────────
    await deliver_video(client, user_id, message.chat.id, reply_to=message)


# ─── "🎬 আরেকটি ভিডিও পান" inline button callback ───────────────────────────

@Client.on_callback_query(filters.regex(r"^next_video$") & filters.private)
async def next_video_callback(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id

    # Safety: only deliver in private chats — group button should never appear, but guard anyway
    if callback_query.message.chat.type != enums.ChatType.PRIVATE:
        import bot_info
        bot_username = bot_info.BOT_USERNAME or "this_bot"
        await callback_query.answer(
            "ভিডিও শুধু প্রাইভেট চ্যাটে পাঠানো হয়। নিচের লিঙ্কে ক্লিক করুন।",
            show_alert=True,
        )
        return

    await callback_query.answer("⏳ পাঠাচ্ছি...")
    success, reason = await deliver_video(client, user_id, chat_id)
    if not success and reason not in ("limit", "no_pool", "empty"):
        await callback_query.answer("❌ কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।", show_alert=True)
