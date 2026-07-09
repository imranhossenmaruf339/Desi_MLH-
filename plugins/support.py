"""
Support Inbox Plugin
════════════════════
• User PM-এ কোনো সাধারণ মেসেজ (কমান্ড ছাড়া) পাঠালে → সাপোর্ট গ্রুপে ফরওয়ার্ড হয়।
• এডমিন সাপোর্ট গ্রুপে reply করলে → বট সেই reply ইউজারের কাছে পাঠায়।
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
    """ইউজারের মেসেজ সাপোর্ট গ্রুপে ফরওয়ার্ড করো।"""
    if not message.from_user:
        return

    user = message.from_user
    name = user.first_name or "Unknown"
    username = f"@{user.username}" if user.username else "নেই"

    # ── সাপোর্ট গ্রুপে হেডার মেসেজ পাঠাও ──────────────────────────────────
    try:
        header = await client.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=(
                "📩 <b>নতুন সাপোর্ট মেসেজ</b>\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                f"👤 নাম: <b>{name}</b>\n"
                f"🔖 Username: {username}\n"
                f"🆔 ID: <code>{user.id}</code>\n\n"
                "💬 নিচের মেসেজে <b>Reply</b> করলে ইউজারের কাছে পৌঁছাবে।"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        return

    # ── আসল মেসেজটি ফরওয়ার্ড করো ──────────────────────────────────────────
    try:
        forwarded = await message.copy(chat_id=SUPPORT_GROUP_ID)
    except Exception:
        try:
            forwarded = await message.forward(SUPPORT_GROUP_ID)
        except Exception:
            return

    # ── ম্যাপিং সেভ করো: forwarded_msg_id → user_id ─────────────────────────
    await support_msgs.insert_one({
        "forwarded_msg_id": forwarded.id,
        "header_msg_id": header.id,
        "user_id": user.id,
        "user_name": name,
        "username": user.username,
    })

    # ── ইউজারকে কনফার্মেশন দাও ──────────────────────────────────────────────
    try:
        await message.reply_text(
            "✅ <b>আপনার মেসেজ এডমিনের কাছে পাঠানো হয়েছে!</b>\n\n"
            "শীঘ্রই রিপ্লাই পাবেন। একটু অপেক্ষা করুন 🙏",
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
    """এডমিনের reply ইউজারের কাছে পাঠাও।"""
    reply_to = message.reply_to_message
    if not reply_to:
        return

    # ── forwarded_msg_id বা header_msg_id দিয়ে user_id খোঁজো ───────────────
    doc = await support_msgs.find_one({"forwarded_msg_id": reply_to.id})
    if not doc:
        doc = await support_msgs.find_one({"header_msg_id": reply_to.id})
    if not doc:
        return  # এটা কোনো সাপোর্ট মেসেজ নয়

    user_id = doc["user_id"]
    user_name = doc.get("user_name", "ইউজার")

    try:
        await message.copy(chat_id=user_id)
        await message.reply_text(
            f"✅ <b>{user_name}</b>-এর কাছে পাঠানো হয়েছে।",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(
            f"❌ পাঠানো যায়নি!\n<code>{e}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
