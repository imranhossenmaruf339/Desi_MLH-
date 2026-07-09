import asyncio
import random
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters, enums
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import JOIN_CHANNEL_LINK, VIP_CHANNEL_LINK, VIDEO_DAILY_LIMIT, GROUP_VIDEO_LIMIT, ADMIN_IDS, LOG_GROUP_ID, VIP_CHANNEL_ID
from database import users, videos, user_video_history, groups, group_video_stats
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
    """আকর্ষণীয় বাটন — প্রতিটি ভিডিওর নিচে সবসময় দেখাবে।"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 মেইন চ্যানেল", url=JOIN_CHANNEL_LINK),
            InlineKeyboardButton("💎 VIP চ্যানেল", url=VIP_CHANNEL_LINK),
        ],
        [InlineKeyboardButton("▶️ পরবর্তী ভিডিও দেখুন", callback_data="next_video")],
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
    Skips the daily limit entirely for ADMIN_IDS.
    """
    is_admin = (user_id in ADMIN_IDS)

    # ── Mandatory Join Check ──────────────────────────────────────────────────
    # Fix: শুধু UserNotParticipant ধরুন — অন্য Exception ধরলে নেটওয়ার্ক এরর হলেও
    # ইউজার ভুলভাবে ব্লক হয়ে যায়
    if not is_admin and VIP_CHANNEL_ID:
        is_member = True  # default: সন্দেহের সুবিধা দাও
        try:
            member = await client.get_chat_member(VIP_CHANNEL_ID, user_id)
            if member.status in [enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT]:
                is_member = False
        except UserNotParticipant:
            is_member = False
        except Exception:
            # API error বা network error — block করবো না
            is_member = True

        if not is_member:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join Channel", url=VIP_CHANNEL_LINK)],
                [InlineKeyboardButton("✅ I have Joined", callback_data="next_video")]
            ])
            await client.send_message(
                chat_id=chat_id,
                text=(
                    "❌ <b>আপনি আমাদের চ্যানেলে জয়েন করেননি!</b>\n\n"
                    "ভিডিও পেতে হলে আপনাকে অবশ্যই আমাদের চ্যানেলে জয়েন থাকতে হবে। "
                    "নিচের বাটনে ক্লিক করে জয়েন করুন এবং তারপর আবার চেষ্টা করুন।"
                ),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=keyboard
            )
            return False, "not_joined"

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
            "joined_at": datetime.now(timezone.utc),
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

    # ── Daily limit check (admin সবসময় bypass করে) ──────────────────────────
    if not is_admin and video_count >= VIDEO_DAILY_LIMIT:
        name    = user.get("first_name") or "Unknown"
        uname   = f"@{user['username']}" if user.get("username") else "no username"
        now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")

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

    # ── Pick unseen video (Fix: সব ভিডিও RAM-এ না এনে MongoDB aggregation ব্যবহার) ──
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = await user_video_history.find(
        {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}},
        {"video_id": 1},
    ).to_list(length=None)
    seen_ids = [h["video_id"] for h in recent]

    # MongoDB $sample দিয়ে সরাসরি একটি random unseen ভিডিও আনো
    pipeline = [
        {"$match": {"_id": {"$nin": seen_ids}}},
        {"$sample": {"size": 1}},
    ]
    pool = await videos.aggregate(pipeline).to_list(length=1)

    if not pool:
        # দেখো ডাটাবেজে কোনো ভিডিও আছে কিনা
        total_vids = await videos.count_documents({})
        if total_vids > 0:
            # ভিডিও আছে কিন্তু ইউজার সব দেখে ফেলেছে
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
        else:
            # ডাটাবেজে কোনো ভিডিও নেই
            await client.send_message(
                chat_id=chat_id,
                text="❌ <b>No videos available yet.</b>\n\nPlease check back later!",
                parse_mode=enums.ParseMode.HTML,
            )
            return False, "empty"

    video_doc = pool[0]
    file_id   = video_doc.get("file_id")
    file_type = video_doc.get("file_type", "video")

    # ── Remaining count hint (admin-কে দেখানো হয় না) ────────────────────────
    remaining = (VIDEO_DAILY_LIMIT - video_count - 1) if not is_admin else None
    remaining_text = (
        f"\n\n📹 <i>আপনার কাছে এই উইন্ডোতে আরও <b>{remaining}</b>টি ভিডিও বাকি আছে।</i>"
        if remaining is not None and remaining >= 0
        else ""
    )

    caption = (video_doc.get("caption", "") or "") + remaining_text

    # ── Send video ───────────────────────────────────────────────────────────
    # Fix: spoiler_err ভেরিয়েবল সরানো হয়েছে — আগে সেট হতো কিন্তু কোথাও ব্যবহার হতো না
    sent = None

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
        except Exception:
            pass  # spoiler support নেই হলে নিচে আবার চেষ্টা হবে

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

    # ── Fix: Atomic counter increment — race condition রোধ করতে $inc ব্যবহার ──
    # আগে: read → compute → write (দুটো request একসাথে এলে একই count পড়তো)
    # এখন: MongoDB-তে atomically increment হয়
    await user_video_history.insert_one({
        "user_id": user_id,
        "video_id": video_doc["_id"],
        "sent_at": datetime.now(timezone.utc),
    })

    if not is_admin:
        await users.update_one(
            {"user_id": user_id},
            {"$inc": {"video_count": 1}},
        )
        new_count = video_count + 1
    else:
        new_count = video_count + 1

    # ── Log to monitor group ──────────────────────────────────────────────────
    name    = user.get("first_name") or "Unknown"
    uname   = f"@{user['username']}" if user.get("username") else "no username"
    now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")
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

    # ── গ্রুপে সরাসরি ভিডিও পাঠাও (সর্বোচ্চ GROUP_VIDEO_LIMIT টি) ────────────
    if in_group:
        import bot_info
        bot_username = bot_info.BOT_USERNAME or "this_bot"
        group_id     = message.chat.id
        current_win  = get_current_window_start()

        # এই window-এ এই ইউজার এই গ্রুপে কতটি ভিডিও দেখেছে
        stat = await group_video_stats.find_one({
            "user_id": user_id, "group_id": group_id, "window_start": current_win,
        })
        count_in_group = stat["count"] if stat else 0

        if count_in_group >= GROUP_VIDEO_LIMIT:
            # লিমিট শেষ — বটে আসতে বলো
            sent = await message.reply_text(
                f"🎬 <b>গ্রুপে {GROUP_VIDEO_LIMIT}টি ভিডিও দেখা হয়ে গেছে!</b>\n\n"
                "আরও ভিডিও দেখতে সরাসরি বটে আসুন 👇\n"
                "<i>(১২ ঘন্টা পর গ্রুপের লিমিট রিসেট হবে)</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🤖 বটে এসে আরো ভিডিও দেখুন",
                        url=f"https://t.me/{bot_username}?start=video",
                    )
                ]]),
            )
            asyncio.create_task(schedule_delete(client, group_id, sent.id, 60))
            asyncio.create_task(schedule_delete(client, group_id, message.id, 5))
            return

        # অপ্রদর্শিত ভিডিও বেছে নাও
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent = await user_video_history.find(
            {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}},
            {"video_id": 1},
        ).to_list(length=None)
        seen_ids = [h["video_id"] for h in recent]
        pool = await videos.aggregate([
            {"$match": {"_id": {"$nin": seen_ids}}},
            {"$sample": {"size": 1}},
        ]).to_list(length=1)

        if not pool:
            sent = await message.reply_text(
                "😔 <b>এই মুহূর্তে কোনো নতুন ভিডিও নেই।</b>\n\nশীঘ্রই নতুন ভিডিও আসবে! 🔔",
                parse_mode=enums.ParseMode.HTML,
            )
            asyncio.create_task(schedule_delete(client, group_id, sent.id, 30))
            asyncio.create_task(schedule_delete(client, group_id, message.id, 5))
            return

        video_doc = pool[0]
        file_id   = video_doc.get("file_id")
        file_type = video_doc.get("file_type", "video")
        remaining = GROUP_VIDEO_LIMIT - count_in_group - 1

        vid_caption = (video_doc.get("caption") or "")
        vid_caption += (
            f"\n\n🎬 <i>গ্রুপে আর <b>{remaining}</b>টি ভিডিও বাকি।</i>"
            if remaining > 0
            else "\n\n🎬 <i>গ্রুপের লিমিট শেষ। বটে এসে আরো দেখুন!</i>"
        )

        grp_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔥 মেইন চ্যানেল", url=JOIN_CHANNEL_LINK),
                InlineKeyboardButton("💎 VIP চ্যানেল", url=VIP_CHANNEL_LINK),
            ],
            [InlineKeyboardButton(
                "🤖 বটে এসে আরো ভিডিও দেখুন",
                url=f"https://t.me/{bot_username}?start=video",
            )],
        ])

        sent = None
        if file_type == "video":
            try:
                sent = await client.send_video(
                    chat_id=group_id, video=file_id, caption=vid_caption,
                    has_spoiler=True, supports_streaming=True,
                    duration=video_doc.get("duration", 0),
                    width=video_doc.get("width", 0), height=video_doc.get("height", 0),
                    parse_mode=enums.ParseMode.HTML, reply_markup=grp_buttons,
                )
            except Exception:
                pass
        if sent is None:
            try:
                sent = await client.send_video(
                    chat_id=group_id, video=file_id, caption=vid_caption,
                    supports_streaming=True,
                    duration=video_doc.get("duration", 0),
                    width=video_doc.get("width", 0), height=video_doc.get("height", 0),
                    parse_mode=enums.ParseMode.HTML, reply_markup=grp_buttons,
                )
            except Exception:
                try:
                    sent = await client.send_document(
                        chat_id=group_id, document=file_id,
                        caption=vid_caption, parse_mode=enums.ParseMode.HTML,
                        reply_markup=grp_buttons,
                    )
                except Exception:
                    pass

        if sent:
            # ১২ ঘন্টা পর ভিডিও মুছে ফেলো
            asyncio.create_task(_delete_after(client, group_id, sent.id, delay=43200))

        # ইউজারের /video কমান্ড মেসেজ মুছো
        asyncio.create_task(schedule_delete(client, group_id, message.id, 5))

        # গ্রুপ ভিডিও কাউন্ট বাড়াও (atomic)
        await group_video_stats.update_one(
            {"user_id": user_id, "group_id": group_id, "window_start": current_win},
            {"$inc": {"count": 1}},
            upsert=True,
        )
        # ইতিহাসে সেভ করো
        await user_video_history.insert_one({
            "user_id": user_id,
            "video_id": video_doc["_id"],
            "sent_at": datetime.now(timezone.utc),
        })
        return

    # ── Private chat: deliver directly ───────────────────────────────────────
    await deliver_video(client, user_id, message.chat.id, reply_to=message)


# ─── "🎬 আরেকটি ভিডিও পান" inline button callback ───────────────────────────

@Client.on_callback_query(filters.regex(r"^next_video$") & filters.private)
async def next_video_callback(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id

    # Safety: only deliver in private chats
    if callback_query.message.chat.type != enums.ChatType.PRIVATE:
        await callback_query.answer(
            "ভিডিও শুধু প্রাইভেট চ্যাটে পাঠানো হয়। নিচের লিঙ্কে ক্লিক করুন।",
            show_alert=True,
        )
        return

    await callback_query.answer("⏳ পাঠাচ্ছি...")
    success, reason = await deliver_video(client, user_id, chat_id)
    if not success and reason not in ("limit", "no_pool", "empty", "not_joined"):
        await callback_query.answer("❌ কিছু একটা সমস্যা হয়েছে। আবার চেষ্টা করুন।", show_alert=True)
