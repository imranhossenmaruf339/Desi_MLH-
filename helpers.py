from datetime import datetime, timedelta

def now():
    return datetime.utcnow()

def is_24h_passed(last_time):
    if not last_time:
        return True
    return now() - last_time >= timedelta(hours=24)
