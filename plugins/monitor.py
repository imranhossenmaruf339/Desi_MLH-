"""
Monitor plugin: forwards comments made on VIDEO_CHANNEL_ID posts to LOG_GROUP_ID.

Setup:
  1. Link a Discussion Group to your VIDEO_CHANNEL_ID in Telegram channel settings.
  2. Set DISCUSSION_GROUP_ID to that group's numeric ID in your .env / Railway.
  3. Add the bot to that discussion group.

When any user comments (replies to a channel post), the bot forwards the
comment info to LOG_GROUP_ID so admins can see it.
"""

from pyrogram import Client, filters, enums

from config import DISCUSSION_GROUP_ID, LOG_GROUP_ID, VIDEO_CHANNEL_ID


def _build_filter():
    if not DISCUSSION_GROUP_ID:
        return filters.chat([])
    # Only capture messages that are replies to a channel post (i.e. comments)
    return filters.chat(DISCUSSION_GROUP_ID) & filters.reply


@Client.on_message(_build_filter())
async def forward_comment_to_monitor(client, message):
    """Forward every comment on a channel post to the monitor group."""
    if not LOG_GROUP_ID:
        return

    # Only care about comments on the linked channel's posts
    reply_to = message.reply_to_message
    if not reply_to:
        return

    # reply_to_message in a discussion group linked to a channel will have
    # forward_from_chat == the channel
    if VIDEO_CHANNEL_ID and reply_to.forward_from_chat:
        if reply_to.forward_from_chat.id != VIDEO_CHANNEL_ID:
            return  # comment is on some other post — ignore

    user = message.from_user
    if not user:
        return  # anonymous / channel message

    name     = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
    username = f"@{user.username}" if user.username else "N/A"

    # Build preview of what they said
    content = ""
    if message.text:
        content = message.text[:200]
    elif message.caption:
        content = message.caption[:200]
    elif message.sticker:
        content = f"[Sticker: {message.sticker.emoji or ''}]"
    elif message.video:
        content = "[Video]"
    elif message.photo:
        content = "[Photo]"
    elif message.voice:
        content = "[Voice]"
    elif message.document:
        content = "[File]"
    else:
        content = "[Media]"

    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=(
                "💬 <b>নতুন Comment</b>\n\n"
                f"👤 Name: {name}\n"
                f"🔖 Username: {username}\n"
                f"🆔 ID: <code>{user.id}</code>\n\n"
                f"📝 Comment:\n{content}"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        print(f"[MONITOR] Failed to forward comment to LOG_GROUP_ID: {e!r}")
