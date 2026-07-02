from datetime import datetime

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import OWNER_ID, JOIN_CHANNEL_LINK
from database import users, video_requests
from helpers import get_current_window_start


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
    await client.send_message(
        chat_id=OWNER_ID,
        text=(
            "📋 <b>Join Verification Request</b>\n\n"
            f"👤 Name: {callback_query.from_user.first_name}\n"
            f"🆔 Username: {username_display}\n"
            f"🔢 User ID: <code>{requester_id}</code>\n\n"
            f"Claims to have joined the partner channel.\n"
            f"🔗 Channel: {JOIN_CHANNEL_LINK}"
        ),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=keyboard,
    )

    await callback_query.answer("✅ Request sent to admin! Please wait.", show_alert=True)
    await callback_query.message.edit_text(
        "⏳ <b>Request submitted!</b>\n\n"
        "Your join confirmation has been sent to the admin.\n"
        "You'll receive a message here once it's reviewed.",
        parse_mode=enums.ParseMode.HTML,
    )


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
    await callback_query.message.edit_text(
        original_text + "\n\n✅ <b>Approved</b> by admin.",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=None,
    )
    await callback_query.answer("✅ User approved and notified.")


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
                "It looks like you haven't joined the partner channel yet.\n"
                "Please join first, then use /video and confirm again.\n\n"
                f"🔗 {JOIN_CHANNEL_LINK}"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    original_text = callback_query.message.text or ""
    await callback_query.message.edit_text(
        original_text + "\n\n❌ <b>Declined</b> by admin.",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=None,
    )
    await callback_query.answer("❌ User declined and notified.")
