from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


def now_seoul_naive() -> datetime:
    """Return Korea Standard Time for legacy naive DATETIME columns."""
    return datetime.now(SEOUL_TIMEZONE).replace(tzinfo=None)


def epoch_to_seoul_naive(value: float | int) -> datetime:
    return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(SEOUL_TIMEZONE).replace(tzinfo=None)


def seoul_naive_to_epoch(value: datetime) -> float:
    if value.tzinfo is not None:
        return value.timestamp()
    return value.replace(tzinfo=SEOUL_TIMEZONE).timestamp()


def format_seoul_datetime(value: datetime | None) -> str:
    if value is None:
        value = now_seoul_naive()
    if value.tzinfo is not None:
        value = value.astimezone(SEOUL_TIMEZONE).replace(tzinfo=None)
    return f"{value.strftime('%Y-%m-%d %H:%M:%S')} KST"
