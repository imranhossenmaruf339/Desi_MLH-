from datetime import datetime, timezone

from pyrogram import Client, filters, enums
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS, JOIN_CHANNEL_LINK, VIP_CHANNEL_LINK, VIDEO_DAILY_LIMIT, JOIN_CHANNEL_2_USERNAME, LOG_GROUP_ID
from database import users, video_requests, user_video_history
from helpers import get_current_window_start


# ─── Auto-verify: legacy handler (the_couple_vibe channel) ───────────────────

@Client.on_callback_query(filters.regex(r"^auto_confirm:(\d+)$"))
async def auto_confirm(client, callback_query):
    requester_id = callback_query.from_user.id
    target_id = int(callback_query.matches[0].group(1))

    if requester_id != target_id:
        await callback_query.answer("❌ This button is not for you.", show_alert=True)
        return

    is_member = False
    try:
        member = await client.get_chat_member(JOIN_CHANNEL_2_USERNAME, requester_id)
        is_member = member.status not in [
            enums.ChatMemberStatus.BANNED,
            enums.ChatMemberStatus.LEFT,
        ]
    except UserNotParticipant:
        is_member = False
    except Exception:
        is_member = False

    if not is_member:
        await callback_query.answer(
            "❌ You haven't joined the channel yet! Please join first, then try again.",
            show_alert=True,
        )
        return

    current_window = get_current_window_start()
    await users.update_one(
        {"user_id": requester_id},
        {"$set": {"video_count": 0, "video_window_start": current_window}},
        upsert=True,
    )

    await callback_query.answer("✅ Verified! Your video limit has been reset.", show_alert=True)
    try:
        await callback_query.message.edit_text(
            "✅ <b>Verified!</b>\n\n"
            "Your video limit has been reset. Use /video to continue. Enjoy! 🎬",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass


# ─── Confirmed button: check VIP channel → send request to monitor group ─────

@Client.on_callback_query(filters.regex(r"^confirm_join:(\d+)$"))
async def confirm_join(client, callback_query):
    requester_id = callback_query.from_user.id
    target_id = int(callback_query.matches[0].group(1))

    if requester_id != target_id:
        await callback_query.answer("❌ This button is not for you.", show_alert=True)
        return

    # ── Check VIP channel membership (only when channel ID is configured) ────
    import bot_info
    vip_id = bot_info.VIP_CHANNEL_ID

    if vip_id:
        try:
            member = await client.get_chat_member(vip_id, requester_id)
            is_member = member.status not in [
                enums.ChatMemberStatus.BANNED,
                enums.ChatMemberStatus.LEFT,
            ]
            if not is_member:
                await callback_query.answer(
                    "❌ You haven't joined the VIP Channel yet!\n"
                    "Please join first, then tap Confirmed again.",
                    show_alert=True,
                )
                return
        except UserNotParticipant:
            await callback_query.answer(
                "❌ You haven't joined the VIP Channel yet!\n"
                "Please join first, then tap Confirmed again.",
                show_alert=True,
            )
            return
        except Exception:
            pass  # verify করা গেলো না — admin-কে পাঠাই

    # ── Guard: pending request less than 24 h old ─────────────────────────────
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    existing = await video_requests.find_one({
        "user_id": requester_id,
        "status": "pending",
        "requested_at": {"$gte": cutoff},
    })
    if existing:
        await callback_query.answer(
            "⏳ Your request is already pending admin review. Please wait.",
            show_alert=True,
        )
        return

    # Clear any old/stale pending entries before inserting a fresh one
    await video_requests.delete_many({
        "user_id": requester_id,
        "status": "pending",
        "requested_at": {"$lt": cutoff},
    })

    await video_requests.insert_one({
        "user_id": requester_id,
        "username": callback_query.from_user.username or "N/A",
        "first_name": callback_query.from_user.first_name or "",
        "status": "pending",
        "requested_at": datetime.now(timezone.utc),
    })

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve (+15 videos)", callback_data=f"admin_approve:{requester_id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"admin_decline:{requester_id}"),
        ]
    ])

    username_display = (
        f"@{callback_query.from_user.username}"
        if callback_query.from_user.username
        else "N/A"
    )

    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=(
                "📋 <b>VIP Channel Verification Request</b>\n\n"
                f"👤 Name: {callback_query.from_user.first_name}\n"
                f"🔖 Username: {username_display}\n"
                f"🔢 User ID: <code>{requester_id}</code>\n\n"
                "✅ Claims to have joined <b>VIP Channel</b>.\n"
                f"🔗 {VIP_CHANNEL_LINK}\n\n"
                "Approve to grant <b>+15 extra videos</b>."
            ),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception as e:
        # Roll back the pending insert so user can try again
        await video_requests.delete_one({"user_id": requester_id, "status": "pending"})
        await callback_query.answer(
            f"❌ Could not reach monitor group. Please try again later.\nError: {e}",
            show_alert=True,
        )
        return

    await callback_query.answer("✅ Request sent! Please wait for admin approval.", show_alert=True)
    try:
        await callback_query.message.edit_text(
            "⏳ <b>Request submitted!</b>\n\n"
            "Your VIP channel join has been sent to the admin.\n"
            "You'll receive a message once it's reviewed. 🔔",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass


# ─── Admin: approve → grant +15 videos ───────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^admin_approve:(\d+)$"))
async def admin_approve(client, callback_query):
    if callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("❌ Unauthorized.", show_alert=True)
        return

    user_id = int(callback_query.matches[0].group(1))

    # Fix: video_count নেগেটিভ হওয়া রোধ করতে max(0, ...) ব্যবহার
    # +15 bonus দিতে current count থেকে 15 কমাও (0-এর নিচে যাবে না)
    user = await users.find_one({"user_id": user_id})
    old_count = user.get("video_count", 0) if user else 0
    new_count = max(0, old_count - 15)   # 0-এর নিচে নামবে না

    current_window = get_current_window_start()
    await users.update_one(
        {"user_id": user_id},
        {
            "$set": {"video_count": new_count, "video_window_start": current_window},
            "$setOnInsert": {
                "points": 0, "referrals": 0,
                "joined_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )
    await video_requests.update_one(
        {"user_id": user_id, "status": "pending"},
        {"$set": {"status": "approved", "reviewed_at": datetime.now(timezone.utc)}},
    )

    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                "✅ <b>Approved!</b>\n\n"
                "You've been granted <b>+15 extra videos</b>! 🎬\n"
                "Use /video to continue watching. Enjoy! 🔥"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    original_text = callback_query.message.text or ""
    try:
        await callback_query.message.edit_text(
            original_text + "\n\n✅ <b>Approved</b> — +15 videos granted.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass
    await callback_query.answer("✅ User approved — +15 videos granted.")


# ─── Admin: decline ───────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^admin_decline:(\d+)$"))
async def admin_decline(client, callback_query):
    if callback_query.from_user.id not in ADMIN_IDS:
        await callback_query.answer("❌ Unauthorized.", show_alert=True)
        return

    user_id = int(callback_query.matches[0].group(1))

    await video_requests.update_one(
        {"user_id": user_id, "status": "pending"},
        {"$set": {"status": "declined", "reviewed_at": datetime.now(timezone.utc)}},
    )

    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>Request Declined</b>\n\n"
                "It seems you haven't joined the VIP Channel yet.\n"
                "Please join first, then use /video and tap <b>Confirmed</b> again.\n\n"
                f"🔗 {VIP_CHANNEL_LINK}"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    original_text = callback_query.message.text or ""
    try:
        await callback_query.message.edit_text(
            original_text + "\n\n❌ <b>Declined</b> by admin.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass
    await callback_query.answer("❌ User declined and notified.")


# ─── My Status ────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^my_status$"))
async def my_status(client, callback_query):
    user_id = callback_query.from_user.id
    user = await users.find_one({"user_id": user_id})

    if not user:
        await callback_query.answer("No profile found. Send /start first.", show_alert=True)
        return

    total_watched = await user_video_history.count_documents({"user_id": user_id})

    joined_at = user.get("joined_at")
    joined_str = joined_at.strftime("%d %b %Y") if joined_at else "N/A"

    name = user.get("first_name") or callback_query.from_user.first_name or "N/A"
    username = f"@{user.get('username')}" if user.get("username") else "N/A"

    await callback_query.answer()
    await callback_query.message.reply_text(
        "📊 <b>My Status</b>\n\n"
        f"👤 Name: <b>{name}</b>\n"
        f"🔖 Username: {username}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📅 Joined: <b>{joined_str}</b>\n"
        f"🎬 Total Videos Watched: <b>{total_watched}</b>",
        parse_mode=enums.ParseMode.HTML,
    )
