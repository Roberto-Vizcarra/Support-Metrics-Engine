"""Period helpers — ISO weeks, calendar months, rolling windows."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_week_window(today: date | None = None) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (current_week_start, now, last_week_start, last_week_end_exclusive).

    Current week: Monday 00:00 UTC of `today`'s week → now.
    Last week: Monday 00:00 UTC of previous week → following Monday 00:00 UTC.
    """
    today = today or now_utc().date()
    weekday = today.weekday()  # Monday=0
    cur_start = datetime.combine(today - timedelta(days=weekday), datetime.min.time(), tzinfo=timezone.utc)
    last_start = cur_start - timedelta(days=7)
    last_end = cur_start
    return cur_start, now_utc(), last_start, last_end


def rolling_days(days: int, anchor: datetime | None = None) -> tuple[datetime, datetime]:
    end = anchor or now_utc()
    start = end - timedelta(days=days)
    return start, end


def last_n_calendar_months(n: int, anchor: date | None = None) -> tuple[datetime, datetime]:
    """Returns (start_of_(anchor month - (n-1)), exclusive end = start of next month after anchor)."""
    anchor = anchor or now_utc().date()
    year, month = anchor.year, anchor.month
    # subtract n-1 months
    months_back = n - 1
    sy, sm = year, month - months_back
    while sm <= 0:
        sm += 12
        sy -= 1
    start = datetime(sy, sm, 1, tzinfo=timezone.utc)
    # end = first day of month after anchor
    ey, em = year, month + 1
    if em > 12:
        em = 1
        ey += 1
    end = datetime(ey, em, 1, tzinfo=timezone.utc)
    return start, end


def parse_ymd(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
