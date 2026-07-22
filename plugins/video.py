import asyncio
import random
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters, enums
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import REQUIRED_GROUP_ID, REQUIRED_GROUP_LINK, VIDEO_DAILY_LIMIT, GROUP_VIDEO_LIMIT, ADMIN_IDS, LOG_GROUP_ID
from database import users, videos, user_video_history, groups, group_video_stats, banned_users, custom_access
from helpers import get_current_window_start, schedule_delete, is_rate_limited


async def _log(client, text: str):
    if not LOG_GROUP_ID:
        return
    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID, text=text, parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        print(f"[LOG-SEND-FAILED] video.py (chat_id={LOG_GROUP_ID}): {e!r}")


def _join_buttons():
    buttons = []
    if REQUIRED_GROUP_LINK:
        buttons.append([InlineKeyboardButton("🔴 আমাদের Group-এ Join করুন", url=REQUIRED_GROUP_LINK)])
    buttons.append([InlineKeyboardButton("🔴 Next Video", callback_data="next_video")])
    return InlineKeyboardMarkup(buttons)


def _group_prompt_buttons(bot_username: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Watch Video", url=f"https://t.me/{bot_username}?start=video")],
    ])


async def _delete_after(client, chat_id: int, message_id: int, delay: int = 1800):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


async def _is_banned(user_id: int) -> bool:
    return await banned_users.find_one({"user_id": user_id}) is not None


async def _get_effective_limit(user_id: int) -> int:
    """Return video limit for user. -1 = unlimited."""
    doc = await custom_access.find_one({"user_id": user_id})
    if doc:
        return doc.get("limit", VIDEO_DAILY_LIMIT)
    return VIDEO_DAILY_LIMIT


async def _check_group_membership(client, user_id: int) -> bool:
    if not REQUIRED_GROUP_ID:
        return True
    try:
        member = await client.get_chat_member(REQUIRED_GROUP_ID, user_id)
        if member.status in [enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT]:
            return False
        return True
    except UserNotParticipant:
        return False
    except Exception:
        return True


async def deliver_video(client, user_id: int, chat_id: int, reply_to=None):
    is_admin = (user_id in ADMIN_IDS)

    # ── Ban check ─────────────────────────────────────────────────────────────
    if not is_admin and await _is_banned(user_id):
        await client.send_message(
            chat_id=chat_id,
            text="🚫 <b>আপনাকে ban করা হয়েছে।</b> Admin-এর সাথে যোগাযোগ করুন।",
            parse_mode=enums.ParseMode.HTML,
        )
        return False, "banned"

    # ── Join check ────────────────────────────────────────────────────────────
    if not is_admin and REQUIRED_GROUP_ID:
        if not await _check_group_membership(client, user_id):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔴 Group-এ Join করুন", url=REQUIRED_GROUP_LINK or "https://t.me")],
                [InlineKeyboardButton("🔴 Join করেছি — Check করুন", callback_data="check_join")],
            ])
            await client.send_message(
                chat_id=chat_id,
                text=(
                    "❌ <b>প্রথমে আমাদের Group-এ Join করুন!</b>\n\n"
                    "Group-এ Join Request পাঠান এবং Admin Approve করলে\n"
                    "নিচের বাটনে ক্লিক করুন।"
                ),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=keyboard,
            )
            return False, "not_joined"

    # ── User record ───────────────────────────────────────────────────────────
    user = await users.find_one({"user_id": user_id})
    if not user:
        window = get_current_window_start()
        await users.insert_one({
            "user_id": user_id, "username": None, "first_name": "",
            "points": 0, "referrals": 0, "video_count": 0,
            "video_window_start": window, "joined_at": datetime.now(timezone.utc),
        })
        user = await users.find_one({"user_id": user_id})

    # ── Window reset ──────────────────────────────────────────────────────────
    current_window = get_current_window_start()
    user_window    = user.get("video_window_start")
    video_count    = user.get("video_count", 0)

    if user_window != current_window:
        video_count = 0
        await users.update_one(
            {"user_id": user_id},
            {"$set": {"video_count": 0, "video_window_start": current_window}},
        )

    # ── Limit check (respects custom access) ─────────────────────────────────
    effective_limit = await _get_effective_limit(user_id)
    if not is_admin and effective_limit != -1 and video_count >= effective_limit:
        limit_label = str(effective_limit)
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"⛔ <b>আপনার ১২ ঘণ্টার limit শেষ!</b>\n\n"
                f"প্রতি ১২ ঘণ্টায় {limit_label}টি ভিডিও দেখা যাবে।\n"
                "পরের window-এ আবার চেষ্টা করুন।"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
        return False, "limit"

    # ── Pick unseen video ─────────────────────────────────────────────────────
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent = await user_video_history.find(
        {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}}, {"video_id": 1},
    ).to_list(length=None)
    seen_ids = [h["video_id"] for h in recent]

    pool = await videos.aggregate([
        {"$match": {"_id": {"$nin": seen_ids}}},
        {"$sample": {"size": 1}},
    ]).to_list(length=1)

    if not pool:
        await client.send_message(
            chat_id=chat_id,
            text="🎬 এই মুহূর্তে কোনো নতুন ভিডিও নেই। পরে আবার চেষ্টা করুন।",
            parse_mode=enums.ParseMode.HTML,
        )
        return False, "no_pool"

    video_doc = pool[0]
    file_id   = video_doc.get("file_id")
    file_type = video_doc.get("file_type", "video")
    sent      = None

    # ── Send video ────────────────────────────────────────────────────────────
    for spoiler in (True, False):
        if file_type == "video" and sent is None:
            try:
                sent = await client.send_video(
                    chat_id=chat_id, video=file_id, caption="",
                    has_spoiler=spoiler, supports_streaming=True,
                    duration=video_doc.get("duration", 0),
                    width=video_doc.get("width", 0),
                    height=video_doc.get("height", 0),
                    reply_markup=_join_buttons(),
                )
            except Exception:
                pass

    if sent is None:
        try:
            sent = await client.send_document(
                chat_id=chat_id, document=file_id, caption="",
                reply_markup=_join_buttons(),
            )
        except Exception as e:
            await client.send_message(
                chat_id=chat_id,
                text=f"❌ ভিডিও পাঠানো সম্ভব হয়নি।\n<code>{e}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return False, str(e)

    if sent:
        asyncio.create_task(_delete_after(client, chat_id, sent.id, delay=86400))

    # ── Record history & increment count ──────────────────────────────────────
    await user_video_history.insert_one({
        "user_id":  user_id,
        "video_id": video_doc["_id"],
        "sent_at":  datetime.now(timezone.utc),
    })
    if not is_admin:
        await users.update_one({"user_id": user_id}, {"$inc": {"video_count": 1}})

    return True, None


# ─── /video command ───────────────────────────────────────────────────────────

@Client.on_message(filters.command("video") & (filters.private | filters.group))
async def video_cmd(client, message):
    if not message.from_user:
        await message.reply_text("❌ Cannot identify user.")
        return

    user_id  = message.from_user.id
    in_group = message.chat.type != enums.ChatType.PRIVATE

    if not in_group and user_id not in ADMIN_IDS:
        wait = is_rate_limited(user_id, cooldown=3.0)
        if wait > 0:
            await message.reply_text(
                f"⏳ একটু অপেক্ষা করুন — <b>{wait:.1f}s</b>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

    if in_group:
        import bot_info
        bot_username = bot_info.BOT_USERNAME
        group_id     = message.chat.id

        await groups.update_one(
            {"group_id": group_id},
            {"$set": {"group_id": group_id, "title": message.chat.title}},
            upsert=True,
        )

        # Group video limit
        current_win = get_current_window_start()
        grp_stat    = await group_video_stats.find_one(
            {"user_id": user_id, "group_id": group_id, "window_start": current_win}
        )
        grp_count = grp_stat.get("count", 0) if grp_stat else 0

        if user_id not in ADMIN_IDS and grp_count >= GROUP_VIDEO_LIMIT:
            btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("🤖 Private-এ দেখুন", url=f"https://t.me/{bot_username}?start=video"),
            ]])
            sent = await message.reply_text(
                f"⛔ Group-এ ১২ ঘণ্টায় সর্বোচ্চ {GROUP_VIDEO_LIMIT}টি।\nPrivate-এ আরো দেখুন 👇",
                reply_markup=btn,
            )
            asyncio.create_task(schedule_delete(client, group_id, sent.id, 30))
            asyncio.create_task(schedule_delete(client, group_id, message.id, 5))
            return

        grp_buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Join করুন", url=REQUIRED_GROUP_LINK or "https://t.me")],
            [InlineKeyboardButton("🔴 আরো দেখুন", url=f"https://t.me/{bot_username}?start=video")],
        ])

        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent = await user_video_history.find(
            {"user_id": user_id, "sent_at": {"$gte": seven_days_ago}}, {"video_id": 1},
        ).to_list(length=None)
        seen_ids = [h["video_id"] for h in recent]

        pool = await videos.aggregate([
            {"$match": {"_id": {"$nin": seen_ids}}},
            {"$sample": {"size": 1}},
        ]).to_list(length=1)

        if not pool:
            await message.reply_text("🎬 এই মুহূর্তে কোনো নতুন ভিডিও নেই।")
            return

        video_doc = pool[0]
        file_id   = video_doc.get("file_id")
        file_type = video_doc.get("file_type", "video")
        sent      = None

        for spoiler in (True, False):
            if file_type == "video" and sent is None:
                try:
                    sent = await client.send_video(
                        chat_id=group_id, video=file_id, caption="",
                        has_spoiler=spoiler, supports_streaming=True,
                        duration=video_doc.get("duration", 0),
                        width=video_doc.get("width", 0), height=video_doc.get("height", 0),
                        reply_markup=grp_buttons,
                    )
                except Exception:
                    pass

        if sent is None:
            try:
                sent = await client.send_document(
                    chat_id=group_id, document=file_id, caption="",
                    reply_markup=grp_buttons,
                )
            except Exception:
                pass

        if sent:
            asyncio.create_task(_delete_after(client, group_id, sent.id, delay=43200))
        asyncio.create_task(schedule_delete(client, group_id, message.id, 5))

        if pool:
            await user_video_history.insert_one({
                "user_id":  user_id,
                "video_id": pool[0]["_id"],
                "sent_at":  datetime.now(timezone.utc),
            })
        await group_video_stats.update_one(
            {"user_id": user_id, "group_id": group_id, "window_start": current_win},
            {"$inc": {"count": 1}}, upsert=True,
        )
        return

    # ── Private chat ─────────────────────────────────────────────────────────
    await deliver_video(client, user_id, message.chat.id)


# ─── Callbacks ────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^next_video$"))
async def next_video_callback(client, callback_query):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    await deliver_video(client, user_id, callback_query.message.chat.id)


@Client.on_callback_query(filters.regex(r"^check_join$"))
async def check_join_callback(client, callback_query):
    user_id    = callback_query.from_user.id
    is_member  = await _check_group_membership(client, user_id)
    if is_member:
        await callback_query.answer("✅ Verified! ভিডিও আসছে…", show_alert=False)
        await deliver_video(client, user_id, callback_query.message.chat.id)
    else:
        await callback_query.answer(
            "❌ এখনো Join করেননি। Group-এ Join করুন তারপর আবার চেষ্টা করুন।",
            show_alert=True,
        )
