from datetime import datetime, timedelta, timezone

from config import TZ


def today_et(now=None):
    """toLocaleDateString('en-CA', {timeZone: 'America/New_York'}): a 19:00 run is already tomorrow in UTC once DST ends."""
    return (now or datetime.now(timezone.utc)).astimezone(TZ).strftime("%Y-%m-%d")


def days_ago_et(n):
    return today_et(datetime.now(timezone.utc) - timedelta(days=n))


def et_stamp(now=None):
    """toLocaleString('sv-SE', {timeZone: 'America/New_York'}): '2026-10-22 17:30:00'."""
    return (now or datetime.now(timezone.utc)).astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")


def iso_ms(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None
