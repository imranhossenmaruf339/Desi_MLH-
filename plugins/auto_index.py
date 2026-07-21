"""
Auto-index plugin: automatically saves any video posted in VIDEO_CHANNEL_ID to the database.
Admins no longer need to manually forward videos — just post to the channel and the bot saves them.
"""

import asyncio
from datetime import datetime, timezone

from pyrogram import Client, filters, enums

from config import VIDEO_CHANNEL_ID, LOG_GROUP_ID, ADMIN_IDS
from database import videos

# Track recently processed media_group_ids to avoid saving album duplicates
_seen_media_groups: set[str] = set()


@Client.on_message(
    filters.chat(VIDEO_CHANNEL_ID) & (filters.video | filters.document)
    if VIDEO_CHANNEL_ID else filters.chat([])
)
async def auto_index_channel_video(client, message):
    """Save any video posted in VIDEO_CHANNEL_ID to the database automatically."""

    # Deduplicate album items — only save one item per media group
    if message.media_group_id:
        if message.media_group_id in _seen_media_groups:
            return
        _seen_media_groups.add(message.media_group_id)
        # Clean up old entries to avoid memory leak
        if len(_seen_media_groups) > 500:
            _seen_media_groups.clear()

    file_id = None
    file_type = "video"
    duration = width = height = 0
    if message.video:
        v = message.video
        file_id = v.file_id
        duration = v.duration or 0
        width = v.width or 0
        height = v.height or 0

    elif (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("video/")
    ):
        # Convert document to proper video so it gets a spoiler-capable file_id
        try:
            tmp = await client.send_video(
                chat_id=LOG_GROUP_ID,
                video=message.document.file_id,
                caption="",
            )
            file_id = tmp.video.file_id
            duration = tmp.video.duration or 0
            width = tmp.video.width or 0
            height = tmp.video.height or 0
            await tmp.delete()
        except Exception:
            file_id = message.document.file_id
            file_type = "document"
    else:
        return

    # Avoid duplicates
    existing = await videos.find_one({"file_id": file_id})
    if existing:
        return

    await videos.insert_one({
        "file_id": file_id,
        "file_type": file_type,
        "duration": duration,
        "width": width,
        "height": height,
        "added_at": datetime.now(timezone.utc),
        "source": "auto_index",
    })

    total = await videos.count_documents({})

    if LOG_GROUP_ID:
        try:
            spoiler_note = "✅ Spoiler-capable" if file_type == "video" else "⚠️ Document"
            await client.send_message(
                chat_id=LOG_GROUP_ID,
                text=(
                    "🔄 <b>Auto-Index: নতুন ভিডিও সংরক্ষিত</b>\n\n"
                    f"📦 মোট ভিডিও: <b>{total}</b>\n"
                    f"🎭 Type: {spoiler_note}"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            print(f"[LOG-SEND-FAILED] auto_index.py: {e!r}")
