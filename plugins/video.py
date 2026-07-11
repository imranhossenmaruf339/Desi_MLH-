import asyncio
import random
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters, enums
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import JOIN_CHANNEL_LINK, VIP_CHANNEL_LINK, VIDEO_DAILY_LIMIT, GROUP_VIDEO_LIMIT, ADMIN_IDS, LOG_GROUP_ID, VIP_CHANNEL_ID
from database import users, videos, user_video_history, groups, group_video_stats
from helpers import get_current_window_start, schedule_delete, is_rate_limited


async def _log(client, text: str):
    """Send a log message to the monitor group — never raises, but prints the
    failure to stdout so a misconfigured LOG_CHANNEL_ID is visible in the
    deployment logs instead of failing completely silently."""
    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=text,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        print(f"[LOG-SEND-FAILED] video.py _log: {e!r}")


# ─── Shared button builders ───────────────────────────────────────────────────

def _join_buttons():
    """Attractive buttons — always shown under every video."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 Main Channel", url=JOIN_CHANNEL_LINK),
            InlineKeyboardButton("💎 VIP Channel", url=VIP_CHANNEL_LINK),
        ],
        [InlineKeyboardButton("▶️ Next Video", callback_data="next_video")],
    ])


def _group_prompt_buttons(bot_username: str):
    """Button shown in groups — deep-links user to bot PM to get video."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎬 Watch Video",
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
    # Fix: only catch UserNotParticipant — catching any Exception would wrongly
    # block a user just because of a network error.
    if not is_admin and VIP_CHANNEL_ID:
        is_member = True  # default: give the benefit of the doubt
        try:
            member = await client.get_chat_member(VIP_CHANNEL_ID, user_id)
            if member.status in [enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT]:
                is_member = False
        except UserNotParticipant:
            is_member = False
        except Exception:
            # API/network error — don't block the user
            is_member = True

        if not is_member:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join Channel", url=VIP_CHANNEL_LINK)],
                [InlineKeyboardButton("✅ I have Joined", callback_data="next_video")]
            ])
            await client.send_message(
                chat_id=chat_id,
                text=(
                    "❌ <b>You haven't joined our channel yet!</b>\n\n"
                    "You must join our channel to get videos. "
                    "Tap the button below to join, then try again."
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

    # ── Daily limit check (admin always bypasses) ───────────────────────────
    if not is_admin and video_count >= VIDEO_DAILY_LIMIT:
        name    = user.get("first_name") or "Unknown"
        uname   = f"@{user['username']}" if user.get("username") else "no username"
        now_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")

        await _log(
            client,
            f"🚫 <b>Limit Reached!</b>\n\n"
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

    # ── Pick unseen video (Fix: uses MongoDB aggregation instead of loading all videos into RAM) ──
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = await user_video_history.find(
        {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}},
        {"video_id": 1},
    ).to_list(length=None)
    seen_ids = [h["video_id"] for h in recent]

    # Use MongoDB $sample to fetch one random unseen video directly
    pipeline = [
        {"$match": {"_id": {"$nin": seen_ids}}},
        {"$sample": {"size": 1}},
    ]
    pool = await videos.aggregate(pipeline).to_list(length=1)

    if not pool:
        # Check whether there are any videos in the DB at all
        total_vids = await videos.count_documents({})
        if total_vids > 0:
            # Videos exist, but the user has already seen all of them
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
            # No videos in the DB at all
            await client.send_message(
                chat_id=chat_id,
                text="❌ <b>No videos available yet.</b>\n\nPlease check back later!",
                parse_mode=enums.ParseMode.HTML,
            )
            return False, "empty"

    video_doc = pool[0]
    file_id   = video_doc.get("file_id")
    file_type = video_doc.get("file_type", "video")

    # ── Remaining count hint (not shown to admin) ───────────────────────────
    remaining = (VIDEO_DAILY_LIMIT - video_count - 1) if not is_admin else None
    remaining_text = (
        f"\n\n📹 <i>You have <b>{remaining}</b> more videos left in this window.</i>"
        if remaining is not None and remaining >= 0
        else ""
    )

    caption = (video_doc.get("caption", "") or "") + remaining_text

    # ── Send video ───────────────────────────────────────────────────────────
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
            pass  # spoiler not supported — will retry below

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

    # ── Auto-delete after 24 hours (PM) ──────────────────────────────────────
    if sent:
        asyncio.create_task(_delete_after(client, chat_id, sent.id, delay=86400))

    # ── Fix: atomic counter increment to avoid a race condition ─────────────
    # Before: read → compute → write (two concurrent requests could read the
    # same count). Now: MongoDB increments it atomically with $inc.
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
    total_in_library = await videos.count_documents({})

    if is_admin:
        count_line = "📊 Count: <b>Admin (no limit)</b>"
    else:
        remaining = max(0, VIDEO_DAILY_LIMIT - new_count)
        count_line = f"📊 Count: <b>{new_count}/{VIDEO_DAILY_LIMIT}</b> (remaining: {remaining})"

    await _log(
        client,
        f"🎬 <b>Video Sent (PM)</b>\n\n"
        f"👤 Name: <b>{name}</b>\n"
        f"🔖 Username: {uname}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"{count_line}\n"
        f"🎞 Total ever watched: <b>{total_watched}</b>\n"
        f"📦 Total in library: <b>{total_in_library}</b>\n"
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

    # ── Rate limit: 1 command every 3 seconds in PM ─────────────────────────
    if not in_group and user_id not in ADMIN_IDS:
        wait = is_rate_limited(user_id, cooldown=3.0)
        if wait > 0:
            await message.reply_text(
                f"⏳ Slow down! Try again in <b>{wait:.1f} seconds</b>.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

    # ── Auto-register group ───────────────────────────────────────────────────
    if in_group:
        await groups.update_one(
            {"group_id": message.chat.id},
            {"$set": {"group_id": message.chat.id, "title": message.chat.title or ""}},
            upsert=True,
        )

    # ── Send video directly in the group (up to GROUP_VIDEO_LIMIT total) ────
    if in_group:
        import bot_info
        bot_username = bot_info.BOT_USERNAME or "this_bot"
        group_id     = message.chat.id
        current_win  = get_current_window_start()

        # How many videos this user has watched in this group during this window
        stat = await group_video_stats.find_one({
            "user_id": user_id, "group_id": group_id, "window_start": current_win,
        })
        count_in_group = stat["count"] if stat else 0

        if count_in_group >= GROUP_VIDEO_LIMIT:
            # Limit reached — direct user to the bot's PM
            sent = await message.reply_text(
                f"🎬 <b>You've watched {GROUP_VIDEO_LIMIT} videos in this group!</b>\n\n"
                "Come to the bot directly to watch more 👇\n"
                "<i>(The group limit resets after 12 hours.)</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🤖 Watch more in the bot",
                        url=f"https://t.me/{bot_username}?start=video",
                    )
                ]]),
            )
            asyncio.create_task(schedule_delete(client, group_id, sent.id, 60))
            asyncio.create_task(schedule_delete(client, group_id, message.id, 5))
            return

        # Pick an unseen video
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
                "😔 <b>No new videos right now.</b>\n\nNew videos are coming soon! 🔔",
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
            f"\n\n🎬 <i>You have <b>{remaining}</b> more videos left in this group.</i>"
            if remaining > 0
            else "\n\n🎬 <i>Group limit reached. Come to the bot to watch more!</i>"
        )

        grp_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔥 Main Channel", url=JOIN_CHANNEL_LINK),
                InlineKeyboardButton("💎 VIP Channel", url=VIP_CHANNEL_LINK),
            ],
            [InlineKeyboardButton(
                "🤖 Watch more in the bot",
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
                    # Last resort: retry without the caption at all, so a bad
                    # caption (e.g. raw HTML characters) can never silently
                    # swallow the whole delivery.
                    try:
                        sent = await client.send_video(
                            chat_id=group_id, video=file_id,
                            supports_streaming=True,
                            duration=video_doc.get("duration", 0),
                            width=video_doc.get("width", 0), height=video_doc.get("height", 0),
                            reply_markup=grp_buttons,
                        )
                    except Exception:
                        pass

        if sent:
            # Delete the video after 12 hours
            asyncio.create_task(_delete_after(client, group_id, sent.id, delay=43200))

        # Delete the user's /video command message
        asyncio.create_task(schedule_delete(client, group_id, message.id, 5))

        # Increment the group video count (atomic)
        await group_video_stats.update_one(
            {"user_id": user_id, "group_id": group_id, "window_start": current_win},
            {"$inc": {"count": 1}},
            upsert=True,
        )
        # Save to history
        await user_video_history.insert_one({
            "user_id": user_id,
            "video_id": video_doc["_id"],
            "sent_at": datetime.now(timezone.utc),
        })

        # Fix: group deliveries were never logged to the monitor group at all —
        # now logged the same way PM deliveries are, including the DB total.
        name  = message.from_user.first_name or "Unknown"
        uname = f"@{message.from_user.username}" if message.from_user.username else "no username"
        total_in_library = await videos.count_documents({})
        await _log(
            client,
            f"🎬 <b>Video Sent (Group)</b>\n\n"
            f"👤 Name: <b>{name}</b>\n"
            f"🔖 Username: {uname}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"🏘 Group: <b>{message.chat.title or group_id}</b>\n"
            f"📊 Count in group: <b>{count_in_group + 1}/{GROUP_VIDEO_LIMIT}</b>\n"
            f"📦 Total in library: <b>{total_in_library}</b>\n"
            f"🕐 Time: {datetime.now(timezone.utc).strftime('%d %b %Y, %I:%M %p UTC')}",
        )
        return

    # ── Private chat: deliver directly ───────────────────────────────────────
    await deliver_video(client, user_id, message.chat.id, reply_to=message)


# ─── "Next video" inline button callback ─────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^next_video$") & filters.private)
async def next_video_callback(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id

    # Safety: only deliver in private chats
    if callback_query.message.chat.type != enums.ChatType.PRIVATE:
        await callback_query.answer(
            "Videos are only sent in private chat. Please tap the link below.",
            show_alert=True,
        )
        return

    # ── Rate limit (to prevent button spam) ──────────────────────────────────
    if user_id not in ADMIN_IDS:
        wait = is_rate_limited(user_id, cooldown=3.0)
        if wait > 0:
            await callback_query.answer(
                f"⏳ Slow down! Try again in {wait:.1f} seconds.",
                show_alert=True,
            )
            return

    await callback_query.answer("⏳ Sending...")
    success, reason = await deliver_video(client, user_id, chat_id)
    if not success and reason not in ("limit", "no_pool", "empty", "not_joined"):
        await callback_query.answer("❌ Something went wrong. Please try again.", show_alert=True)
