from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")
UTC_TIMEZONE = timezone.utc


def utc_now() -> datetime:
    """Return an aware UTC timestamp for cross-system event comparison."""
    return datetime.now(UTC_TIMEZONE)


def now_seoul_naive() -> datetime:
    """Return Korea Standard Time for legacy naive DATETIME columns."""
    return datetime.now(SEOUL_TIMEZONE).replace(tzinfo=None)


def epoch_to_seoul_naive(value: float | int) -> datetime:
    return datetime.fromtimestamp(float(value), tz=UTC_TIMEZONE).astimezone(SEOUL_TIMEZONE).replace(tzinfo=None)


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


def parse_timestamp(value: Any, *, naive_timezone: timezone | ZoneInfo = UTC_TIMEZONE) -> datetime | None:
    """Parse an external timestamp without discarding its timezone information.

    RunPod's worker logs are supplied in KST. API responses that omit an
    offset are therefore passed with ``naive_timezone=SEOUL_TIMEZONE``. An
    explicit ``Z`` or ``+09:00`` always wins over that fallback.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC_TIMEZONE)
    else:
        text = str(value).strip()
        if not text:
            return None
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            else:
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=naive_timezone)
    return parsed


def timestamp_pair(
    value: Any,
    *,
    naive_timezone: timezone | ZoneInfo = UTC_TIMEZONE,
    source_timezone: str | None = None,
    source: str = "application",
) -> dict[str, str | None]:
    """Return explicit UTC and KST representations for an event timestamp."""
    parsed = parse_timestamp(value, naive_timezone=naive_timezone)
    if parsed is None:
        return {
            "utc": None,
            "kst": None,
            "sourceTimezone": source_timezone or _timezone_name(naive_timezone),
            "source": source,
        }
    utc_value = parsed.astimezone(UTC_TIMEZONE)
    kst_value = parsed.astimezone(SEOUL_TIMEZONE)
    return {
        "utc": utc_value.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kst": kst_value.strftime("%Y-%m-%d %H:%M:%S KST"),
        "sourceTimezone": source_timezone or _timezone_name(parsed.tzinfo),
        "source": source,
    }


def timestamp_fields(
    field_name: str,
    value: Any,
    *,
    naive_timezone: timezone | ZoneInfo = UTC_TIMEZONE,
    source_timezone: str | None = None,
    source: str = "application",
) -> dict[str, str | None]:
    """Create the API-compatible legacy value plus explicit UTC/KST fields."""
    pair = timestamp_pair(
        value,
        naive_timezone=naive_timezone,
        source_timezone=source_timezone,
        source=source,
    )
    return {
        field_name: pair["kst"],
        f"{field_name}Utc": pair["utc"],
        f"{field_name}Kst": pair["kst"],
        f"{field_name}SourceTimezone": pair["sourceTimezone"],
        f"{field_name}Source": pair["source"],
    }


def _timezone_name(value: timezone | ZoneInfo | None) -> str:
    if value is None:
        return "UTC"
    if value == UTC_TIMEZONE:
        return "UTC"
    return str(getattr(value, "key", None) or value.tzname(None) or "UTC")
