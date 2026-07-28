from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def now_in(zone: ZoneInfo) -> datetime:
    return datetime.now(zone)


def iso_now(zone: ZoneInfo) -> str:
    return now_in(zone).isoformat(timespec="seconds")


def parse_datetime(value: str | None, zone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        parsed_date = datetime.strptime(cleaned, "%Y-%m-%d").date()
        return datetime.combine(parsed_date, time.min, tzinfo=zone)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def parse_day(value: str | None, zone: ZoneInfo) -> str:
    parsed = parse_datetime(value, zone) if value else now_in(zone)
    if parsed is None:
        parsed = now_in(zone)
    return parsed.date().isoformat()


def event_status(start_at: str | None, end_at: str | None, zone: ZoneInfo, at: datetime | None = None) -> str:
    current = at or now_in(zone)
    start = parse_datetime(start_at, zone)
    end = parse_datetime(end_at, zone)
    if not start and not end:
        return "unknown"
    if start and current < start:
        return "upcoming"
    if end and current > end:
        return "past"
    return "active"


def end_after_days(start_at: str, days: int, zone: ZoneInfo) -> str:
    start = parse_datetime(start_at, zone) or now_in(zone)
    return (start + timedelta(days=days)).isoformat(timespec="seconds")


def today_payload(zone: ZoneInfo) -> dict[str, str]:
    current = now_in(zone)
    return {
        "now": current.isoformat(timespec="seconds"),
        "time": current.strftime("%H:%M:%S"),
        "day": current.strftime("%d"),
        "month": current.strftime("%m"),
        "year": current.strftime("%Y"),
        "date": current.date().isoformat(),
        "weekday": current.strftime("%A"),
        "timezone": str(zone.key),
        "date_text": current.strftime("%d.%m.%Y"),
        "human": current.strftime("%H:%M:%S %d.%m.%Y"),
    }
