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
    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=text,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        print(f"[LOG-SEND-FAILED] video.py _log: {e!r}")


def _join_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 Main Channel", url=JOIN_CHANNEL_LINK),
            InlineKeyboardButton("💎 VIP Channel", url=VIP_CHANNEL_LINK),
        ],
        [InlineKeyboardButton("▶️ Next Video", callback_data="next_video")],
    ])


def _group_prompt_buttons(bot_username: str):
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


async def deliver_video(client, user_id: int, chat_id: int, reply_to=None):
    is_admin = (user_id in ADMIN_IDS)

    # Join check
    if not is_admin and VIP_CHANNEL_ID:
        is_member = True
        try:
            member = await client.get_chat_member(VIP_CHANNEL_ID, user_id)
            if member.status in [enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT]:
                is_member = False
        except UserNotParticipant:
            is_member = False
        except Exception:
            is_member = True

        if not is_member:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join Channel", url=VIP_CHANNEL_LINK)],
                [InlineKeyboardButton("✅ I have Joined", callback_data="next_video")]
            ])
            await client.send_message(
                chat_id=chat_id,
                text="❌ <b>You haven't joined our channel yet!</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=keyboard
            )
            return False, "not_joined"

    # User record
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

    # Window reset
    current_window = get_current_window_start()
    user_window = user.get("video_window_start")
    video_count = user.get("video_count", 0)

    if user_window != current_window:
        video_count = 0
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"video_count": 0, "video_window_start": current_window}},
        )

    # Daily limit
    if not is_admin and video_count >= VIDEO_DAILY_LIMIT:
        await client.send_message(
            chat_id=chat_id,
            text="⛔ Daily limit reached.",
            parse_mode=enums.ParseMode.HTML,
        )
        return False, "limit"

    # Unseen video
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
        await client.send_message(
            chat_id=chat_id,
            text="🎬 No new videos available.",
            parse_mode=enums.ParseMode.HTML,
        )
        return False, "no_pool"

    video_doc = pool[0]
    file_id   = video_doc.get("file_id")
    file_type = video_doc.get("file_type", "video")

    caption = ""  # ← CAPTION REMOVED

    sent = None

    # Try sending video
    if file_type == "video":
        try:
            sent = await client.send_video(
                chat_id=chat_id,
                video=file_id,
                caption="",  # ← CAPTION REMOVED
                has_spoiler=True,
                supports_streaming=True,
                duration=video_doc.get("duration", 0),
                width=video_doc.get("width", 0),
                height=video_doc.get("height", 0),
                reply_markup=_join_buttons(),
            )
        except Exception:
            pass

    # Fallback
    if sent is None:
        try:
            sent = await client.send_video(
                chat_id=chat_id,
                video=file_id,
                caption="",  # ← CAPTION REMOVED
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
                    caption="",  # ← CAPTION REMOVED
                    reply_markup=_join_buttons(),
                )
            except Exception as e:
                await client.send_message(
                    chat_id=chat_id,
                    text=f"❌ Failed to send video.\n<code>{e}</code>",
                    parse_mode=enums.ParseMode.HTML,
                )
                return False, str(e)

    if sent:
        asyncio.create_task(_delete_after(client, chat_id, sent.id, delay=86400))

    # Save history
    await user_video_history.insert_one({
        "user_id": user_id,
        "video_id": video_doc["_id"],
        "sent_at": datetime.now(timezone.utc),
    })

    # Increase count
    if not is_admin:
        await users.update_one(
            {"user_id": user_id},
            {"$inc": {"video_count": 1}},
        )

    return True, None


@Client.on_message(filters.command("video") & (filters.private | filters.group))
async def video_cmd(client, message):
    if not message.from_user:
        await message.reply_text("❌ Cannot identify user.")
        return

    user_id = message.from_user.id
    in_group = message.chat.type != enums.ChatType.PRIVATE

    if not in_group and user_id not in ADMIN_IDS:
        wait = is_rate_limited(user_id, cooldown=3.0)
        if wait > 0:
            await message.reply_text(
                f"⏳ Try again in <b>{wait:.1f} seconds</b>.",
                parse_mode=enums.ParseMode.HTML,
            )
            return

    if in_group:
        await groups.update_one(
            {"group_id": message.chat.id},
            {"$set": {"group_id": message.chat.id, "title": message.chat.title or ""}},
            upsert=True,
        )

    if in_group:
        import bot_info
        bot_username = bot_info.BOT_USERNAME or "this_bot"
        group_id     = message.chat.id
        current_win  = get_current_window_start()

        stat = await group_video_stats.find_one({
            "user_id": user_id, "group_id": group_id, "window_start": current_win,
        })
        count_in_group = stat["count"] if stat else 0

        if count_in_group >= GROUP_VIDEO_LIMIT:
            sent = await message.reply_text(
                "🎬 Group limit reached.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🤖 Watch more",
                        url=f"https://t.me/{bot_username}?start=video",
                    )
                ]]),
            )
            asyncio.create_task(schedule_delete(client, group_id, sent.id, 60))
            asyncio.create_task(schedule_delete(client, group_id, message.id, 5))
            return

        # Unseen video
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
                "😔 No new videos.",
                parse_mode=enums.ParseMode.HTML,
            )
            asyncio.create_task(schedule_delete(client, group_id, sent.id, 30))
            asyncio.create_task(schedule_delete(client, group_id, message.id, 5))
            return

        video_doc = pool[0]
        file_id   = video_doc.get("file_id")
        file_type = video_doc.get("file_type", "video")

        vid_caption = ""  # ← CAPTION REMOVED

        grp_buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔥 Main Channel", url=JOIN_CHANNEL_LINK),
                InlineKeyboardButton("💎 VIP Channel", url=VIP_CHANNEL_LINK),
            ],
            [InlineKeyboardButton(
                "🤖 Watch more",
                url=f"https://t.me/{bot_username}?start=video",
            )],
        ])

        sent = None
        if file_type == "video":
            try:
                sent = await client.send_video(
                    chat_id=group_id, video=file_id, caption="",
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
                    chat_id=group_id, video=file_id, caption="",
                    supports_streaming=True,
                    duration=video_doc.get("duration", 0),
                    width=video_doc.get("width", 0), height=video_doc.get("height", 0),
                    parse_mode=enums.ParseMode.HTML, reply_markup=grp_buttons,
                )
            except Exception:
                try:
                    sent = await client.send_document(
                        chat_id=group_id, document=file_id,
                        caption="", parse_mode=enums.ParseMode.HTML,
                        reply_markup=grp_buttons,
                    )
                except Exception:
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
            asyncio.create_task(_delete_after(client, group_id, sent.id, delay=43200))

        asyncio.create_task(schedule_delete(client, group_id, message.id, 5))

        await group_video_stats.update_one(
            {"user_id": user_id, "group_id": group_id, "window_start": current_win},
            {"$inc": {"count": 1}},
            upsert=True,
        )

        await user_video_history.insert_one({
            "user_id": user_id,
            "video_id": video_doc["_id"],
            "sent_at": datetime.now(timezone.utc),
        })

        return

    await deliver_video(client, user_id, message.chat.id, reply_to=message)


@Client.on_callback_query(filters.regex(r"^next_video$"))
async def next_video_callback(client, callback_query):
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id

    if callback_query.message.chat.type != enums.ChatType.PRIVATE:
        await callback_query.answer(
            "Videos are only sent in private chat.",
            show_alert=True,
        )
        return

    if user_id not in ADMIN_IDS:
        wait = is_rate_limited(user_id, cooldown=3.0)
        if wait > 0:
            await callback_query.answer(
                f"⏳ Try again in {wait:.1f} seconds.",
                show_alert=True,
            )
            return

    await callback_query.answer("⏳ Sending...")
    await deliver_video(client, user_id, chat_id)
