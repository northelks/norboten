"""The internal calendar: which days the office is open. (Added 2026-09 for the digest.)"""

OPEN_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


def is_open(day_name):
    """True when the office is open on that weekday."""
    return day_name in OPEN_DAYS
