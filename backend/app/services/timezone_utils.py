"""US Eastern timezone helpers ensuring consistent EST/EDT timestamps across API and UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    _ZONEINFO_EASTERN: tzinfo | None = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    _ZONEINFO_EASTERN = None

_EST_TZ = timezone(timedelta(hours=-5), name="EST")
_EDT_TZ = timezone(timedelta(hours=-4), name="EDT")


def _nth_sunday_day(year: int, month: int, nth: int) -> int:
    first_day = datetime(year, month, 1)
    days_until_sunday = (6 - first_day.weekday()) % 7
    return 1 + days_until_sunday + (nth - 1) * 7


def _is_us_eastern_dst(utc_dt: datetime) -> bool:
    """Determine if a UTC datetime falls in US Eastern Daylight Time (2nd Sun Mar -> 1st Sun Nov)."""
    naive_utc = utc_dt.astimezone(timezone.utc).replace(tzinfo=None)
    year = naive_utc.year
    # 02:00 EST = 07:00 UTC on 2nd Sunday of March; 02:00 EDT = 06:00 UTC on 1st Sunday of November.
    dst_start_utc = datetime(year, 3, _nth_sunday_day(year, 3, 2), 7, 0)
    dst_end_utc = datetime(year, 11, _nth_sunday_day(year, 11, 1), 6, 0)
    return dst_start_utc <= naive_utc < dst_end_utc


def now_eastern() -> datetime:
    """Return current timezone-aware US Eastern datetime (EST/EDT)."""
    return to_eastern(datetime.now(timezone.utc)) or datetime.now(timezone.utc)


def to_eastern(dt: datetime | None) -> datetime | None:
    """Convert a naive (UTC-stored in SQLite) or aware datetime into US Eastern Time."""
    if dt is None:
        return None
    aware_utc = (
        dt.astimezone(timezone.utc)
        if dt.tzinfo is not None
        else dt.replace(tzinfo=timezone.utc)
    )
    if _ZONEINFO_EASTERN is not None:
        return aware_utc.astimezone(_ZONEINFO_EASTERN)
    target_tz = _EDT_TZ if _is_us_eastern_dst(aware_utc) else _EST_TZ
    return aware_utc.astimezone(target_tz)


def eastern_today_str() -> str:
    """Return YYYY-MM-DD in US Eastern time."""
    return now_eastern().strftime("%Y-%m-%d")
