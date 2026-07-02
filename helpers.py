from datetime import datetime, timedelta

def now():
    return datetime.utcnow()

def is_24h_passed(last_time):
    if not last_time:
        return True
    return now() - last_time >= timedelta(hours=24)

def get_current_window_start():
    """Return the start of the current 12-hour window (midnight or noon UTC).
    Limits reset at 00:00 UTC and 12:00 UTC every day.
    """
    n = datetime.utcnow()
    if n.hour < 12:
        return n.replace(hour=0, minute=0, second=0, microsecond=0)
    return n.replace(hour=12, minute=0, second=0, microsecond=0)
