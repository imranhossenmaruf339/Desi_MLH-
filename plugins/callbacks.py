from datetime import datetime

from pyrogram import Client, filters, enums
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import OWNER_ID, JOIN_CHANNEL_LINK, JOIN_CHANNEL_2_USERNAME, LOG_GROUP_ID
from database import users, video_requests, user_video_history
from helpers import get_current_window_start


# ─── Auto-verify: bot checks channel 1 membership ────────────────────────────

@Client.on_callback_query(filters.regex(r"^auto_confirm:(\d+)$"))
async def auto_confirm(client, callback_query):
    requester_id = callback_query.from_user.id
    target_id = int(callback_query.matches[0].group(1))

    if requester_id != target_id:
        await callback_query.answer("❌ This button is not for you.", show_alert=True)
        return

    # Check membership in channel 1 (JOIN_CHANNEL_2_USERNAME = the_couple_vibe)
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

    # Reset the 12-hour video limit
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


# ─── Manual verify: user requests admin approval ──────────────────────────────

@Client.on_callback_query(filters.regex(r"^confirm_join:(\d+)$"))
async def confirm_join(client, callback_query):
    requester_id = callback_query.from_user.id
    target_id = int(callback_query.matches[0].group(1))

    if requester_id != target_id:
        await callback_query.answer("❌ This button is not for you.", show_alert=True)
        return

    existing = await video_requests.find_one({"user_id": requester_id, "status": "pending"})
    if existing:
        await callback_query.answer(
            "⏳ Your request is already pending admin review. Please wait.",
            show_alert=True,
        )
        return

    await video_requests.insert_one({
        "user_id": requester_id,
        "username": callback_query.from_user.username or "N/A",
        "first_name": callback_query.from_user.first_name or "",
        "status": "pending",
        "requested_at": datetime.utcnow(),
    })

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve:{requester_id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"admin_decline:{requester_id}"),
        ]
    ])

    username_display = (
        f"@{callback_query.from_user.username}"
        if callback_query.from_user.username
        else "N/A"
    )

    # Send to monitor group, not bot inbox
    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=(
                "📋 <b>Join Verification Request</b>\n\n"
                f"👤 Name: {callback_query.from_user.first_name}\n"
                f"🆔 Username: {username_display}\n"
                f"🔢 User ID: <code>{requester_id}</code>\n\n"
                "Claims to have joined <b>Channel 2</b>.\n"
                f"🔗 {JOIN_CHANNEL_LINK}"
            ),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        pass

    await callback_query.answer("✅ Request sent! Please wait for admin approval.", show_alert=True)
    try:
        await callback_query.message.edit_text(
            "⏳ <b>Request submitted!</b>\n\n"
            "Your join confirmation has been sent to the admin.\n"
            "You'll receive a message here once it's reviewed.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass


# ─── Admin: approve ───────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^admin_approve:(\d+)$"))
async def admin_approve(client, callback_query):
    if callback_query.from_user.id != OWNER_ID:
        await callback_query.answer("❌ Unauthorized.", show_alert=True)
        return

    user_id = int(callback_query.matches[0].group(1))

    current_window = get_current_window_start()
    await users.update_one(
        {"user_id": user_id},
        {"$set": {"video_count": 0, "video_window_start": current_window}},
        upsert=True,
    )
    await video_requests.update_one(
        {"user_id": user_id, "status": "pending"},
        {"$set": {"status": "approved", "reviewed_at": datetime.utcnow()}},
    )

    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                "✅ <b>Approved!</b>\n\n"
                "Your video limit has been reset. Use /video to continue. Enjoy! 🎬"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    original_text = callback_query.message.text or ""
    try:
        await callback_query.message.edit_text(
            original_text + "\n\n✅ <b>Approved</b> by admin.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass
    await callback_query.answer("✅ User approved and notified.")


# ─── Admin: decline ───────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^admin_decline:(\d+)$"))
async def admin_decline(client, callback_query):
    if callback_query.from_user.id != OWNER_ID:
        await callback_query.answer("❌ Unauthorized.", show_alert=True)
        return

    user_id = int(callback_query.matches[0].group(1))

    await video_requests.update_one(
        {"user_id": user_id, "status": "pending"},
        {"$set": {"status": "declined", "reviewed_at": datetime.utcnow()}},
    )

    try:
        await client.send_message(
            chat_id=user_id,
            text=(
                "❌ <b>Request Declined</b>\n\n"
                "It looks like you haven't joined the channel yet.\n"
                "Please join first, then use /video and confirm again.\n\n"
                f"🔗 {JOIN_CHANNEL_LINK}"
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

    # Total videos watched (all time, from history collection)
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
