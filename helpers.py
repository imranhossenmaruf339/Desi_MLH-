import asyncio
from datetime import datetime, timedelta, timezone


def now():
    # Fix: datetime.utcnow() Python 3.12-এ deprecated — timezone-aware ব্যবহার করুন
    return datetime.now(timezone.utc)


def utcnow():
    """UTC সময় timezone-aware ফরম্যাটে।"""
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
    """Delete a message after `delay` seconds (default 30 s). Silently ignores errors."""
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass
