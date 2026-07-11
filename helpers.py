import asyncio
import time
from datetime import datetime, timedelta, timezone


def now():
    # Fix: datetime.utcnow() is deprecated on Python 3.12 — use timezone-aware instead
    return datetime.now(timezone.utc)


def utcnow():
    """Current UTC time, timezone-aware."""
    return datetime.now(timezone.utc)


def is_24h_passed(last_time):
    if not last_time:
        return True
    return now() - last_time >= timedelta(hours=24)


def get_current_window_start():
    """Return the start of the current 12-hour window (midnight or noon UTC).
    Limits reset at 00:00 UTC and 12:00 UTC every day.
    """
    n = datetime.now(timezone.utc)
    if n.hour < 12:
        return n.replace(hour=0, minute=0, second=0, microsecond=0)
    return n.replace(hour=12, minute=0, second=0, microsecond=0)


async def schedule_delete(client, chat_id: int, message_id: int, delay: int = 30):
    """Delete a message after `delay` seconds (default 30s). Silently ignores errors."""
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


# ─── Rate Limiter (per user) ─────────────────────────────────────────────────
# In-memory dict: user_id -> last command timestamp
_rate_limit_map: dict[int, float] = {}

def is_rate_limited(user_id: int, cooldown: float = 3.0) -> float:
    """
    Check whether a user is currently rate limited.
    Returns 0.0 if allowed, or the remaining wait time (seconds) if blocked.
    """
    now_ts = time.monotonic()
    last = _rate_limit_map.get(user_id, 0.0)
    remaining = cooldown - (now_ts - last)
    if remaining > 0:
        return remaining  # still need to wait
    _rate_limit_map[user_id] = now_ts
    return 0.0


async def get_caption_with_media_group_fallback(client, message) -> str:
    """
    Return the caption for a message, falling back to the caption of the other
    items in the same media group (album) if this particular message has none.

    Telegram albums only attach the caption to ONE message in the group — if the
    handler happens to process a different item first, message.caption is empty
    even though the album clearly "has" a caption. Without this fallback, videos
    auto-saved from albums silently lose their caption.
    """
    if message.caption:
        return message.caption

    if not message.media_group_id:
        return ""

    try:
        group_messages = await client.get_media_group(message.chat.id, message.id)
        for gm in group_messages:
            if gm.caption:
                return gm.caption
    except Exception:
        pass

    return ""
