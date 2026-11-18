"""Shared local clock for cinema schedules stored as Visakhapatnam wall time."""
from datetime import datetime, timedelta, timezone

CINEMA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name='Asia/Kolkata')


def cinema_now():
    """Return the current cinema-local wall time as a naive datetime."""
    return datetime.now(CINEMA_TIMEZONE).replace(tzinfo=None)
