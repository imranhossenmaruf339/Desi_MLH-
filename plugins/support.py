"""
Support Inbox Plugin
════════════════════
• When a user sends a plain message in PM (not a command) → it's forwarded to the support group.
• When an admin replies to it in the support group → the bot sends that reply back to the user.
"""

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS, SUPPORT_GROUP_ID
from database import support_msgs


# ─── User → Support Group ─────────────────────────────────────────────────────

@Client.on_message(
    filters.private
    & ~filters.user(ADMIN_IDS)
    & ~filters.command(["start", "help", "video", "profile"])
)
async def user_to_support(client, message):
    """Forward the user's message to the support group."""
    if not message.from_user:
        return

    user = message.from_user
    name = user.first_name or "Unknown"
    username = f"@{user.username}" if user.username else "none"

    # ── Send a header message to the support group ───────────────────────
    try:
        header = await client.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=(
                "📩 <b>New Support Message</b>\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                f"👤 Name: <b>{name}</b>\n"
                f"🔖 Username: {username}\n"
                f"🆔 ID: <code>{user.id}</code>\n\n"
                "💬 <b>Reply</b> to the message below to reach the user."
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        return

    # ── Forward the actual message ────────────────────────────────────────
    try:
        forwarded = await message.copy(chat_id=SUPPORT_GROUP_ID)
    except Exception:
        try:
            forwarded = await message.forward(SUPPORT_GROUP_ID)
        except Exception:
            return

    # ── Save the mapping: forwarded_msg_id → user_id ───────────────────────
    await support_msgs.insert_one({
        "forwarded_msg_id": forwarded.id,
        "header_msg_id": header.id,
        "user_id": user.id,
        "user_name": name,
        "username": user.username,
    })

    # ── Confirm to the user ─────────────────────────────────────────────────
    try:
        await message.reply_text(
            "✅ <b>Your message has been sent to the admin!</b>\n\n"
            "You'll get a reply soon. Please wait a moment 🙏",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


# ─── Support Group Reply → User ───────────────────────────────────────────────

@Client.on_message(
    filters.chat(SUPPORT_GROUP_ID)
    & filters.reply
    & filters.user(ADMIN_IDS)
    & ~filters.command(["broadcast", "stats", "addvideo", "delvideo", "notifyusers", "cmdlist"])
)
async def support_reply_to_user(client, message):
    """Send the admin's reply back to the user."""
    reply_to = message.reply_to_message
    if not reply_to:
        return

    # ── Find the user_id via forwarded_msg_id or header_msg_id ────────────
    doc = await support_msgs.find_one({"forwarded_msg_id": reply_to.id})
    if not doc:
        doc = await support_msgs.find_one({"header_msg_id": reply_to.id})
    if not doc:
        return  # not a support message

    user_id = doc["user_id"]
    user_name = doc.get("user_name", "the user")

    try:
        await message.copy(chat_id=user_id)
        await message.reply_text(
            f"✅ Sent to <b>{user_name}</b>.",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(
            f"❌ Could not send!\n<code>{e}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
