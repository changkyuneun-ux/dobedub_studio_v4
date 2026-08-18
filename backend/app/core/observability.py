from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Request, Response

from backend.app.core.config import get_settings


OBSERVABILITY_LOGGER = logging.getLogger("dobedub.observability")
if not OBSERVABILITY_LOGGER.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    OBSERVABILITY_LOGGER.addHandler(_handler)
OBSERVABILITY_LOGGER.setLevel(logging.INFO)
OBSERVABILITY_LOGGER.propagate = False

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_TIMING_ORDER = ("auth", "db", "file_stat", "render", "app")


def operation_for_path(path: str) -> str | None:
    if path in {"/api/assets", "/api/v1/assets"}:
        return "asset_list"
    if path.startswith("/api/files/") or path.startswith("/api/v1/files/"):
        return "asset_file"
    if path == "/manual":
        return "manual_html"
    if path.startswith("/docs/manual-assets/"):
        return "manual_asset"
    return None


def ensure_request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", "")
    if existing:
        return str(existing)

    requested = request.headers.get("x-request-id", "").strip()
    request_id = requested if _REQUEST_ID_PATTERN.fullmatch(requested) else uuid.uuid4().hex
    request.state.request_id = request_id
    return request_id


def _timings(request: Request) -> dict[str, float]:
    current = getattr(request.state, "observation_timings", None)
    if current is None:
        current = {}
        request.state.observation_timings = current
    return current


def add_timing(request: Request, name: str, duration_ms: float) -> None:
    timings = _timings(request)
    timings[name] = timings.get(name, 0.0) + max(0.0, duration_ms)


@contextmanager
def request_timing(request: Request, name: str) -> Iterator[None]:
    started_at = time.perf_counter()
    try:
        yield
    finally:
        add_timing(request, name, (time.perf_counter() - started_at) * 1000)


def server_timing_value(timings: dict[str, float]) -> str:
    parts = [f"{name};dur={timings[name]:.1f}" for name in _TIMING_ORDER if name in timings]
    return ", ".join(parts)


def observe_response(request: Request, response: Response | None, total_ms: float, *, status_code: int | None = None) -> None:
    operation = operation_for_path(request.url.path)
    settings = get_settings()
    if not operation or not settings.observability_enabled:
        return

    status = status_code or (response.status_code if response is not None else 500)
    timings = dict(_timings(request))
    timings["app"] = max(0.0, total_ms)
    request_id = ensure_request_id(request)
    if response is not None:
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = server_timing_value(timings)

    range_request = operation == "asset_file" and bool(request.headers.get("range"))
    payload = _request_emf_payload(
        environment=settings.observability_environment,
        operation=operation,
        request_id=request_id,
        status_code=status,
        timings=timings,
        slow_request_ms=settings.observability_slow_request_ms,
        range_request=range_request,
    )
    OBSERVABILITY_LOGGER.info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def observe_asset_stream(request: Request, *, duration_ms: float, bytes_sent: int, status_code: int) -> None:
    settings = get_settings()
    if not settings.observability_enabled:
        return
    payload = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "DOBEDUB/Studio",
                    "Dimensions": [["Environment", "Operation", "StatusFamily"]],
                    "Metrics": [
                        {"Name": "AssetStreamReadMs", "Unit": "Milliseconds"},
                        {"Name": "AssetStreamBytes", "Unit": "Bytes"},
                        {"Name": "AssetStreamCount", "Unit": "Count"},
                    ],
                }
            ],
        },
        "event": "asset_stream",
        "environment": settings.observability_environment,
        "operation": "asset_file",
        "status": status_code,
        "statusFamily": f"{status_code // 100}xx",
        "requestId": ensure_request_id(request),
        "durationMs": round(max(0.0, duration_ms), 3),
        "bytesSent": max(0, bytes_sent),
        "Environment": settings.observability_environment,
        "Operation": "asset_file",
        "StatusFamily": f"{status_code // 100}xx",
        "AssetStreamReadMs": round(max(0.0, duration_ms), 3),
        "AssetStreamBytes": max(0, bytes_sent),
        "AssetStreamCount": 1,
    }
    OBSERVABILITY_LOGGER.info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def _request_emf_payload(
    *,
    environment: str,
    operation: str,
    request_id: str,
    status_code: int,
    timings: dict[str, float],
    slow_request_ms: int,
    range_request: bool,
) -> dict[str, Any]:
    total_ms = round(max(0.0, timings.get("app", 0.0)), 3)
    status_family = f"{status_code // 100}xx"
    return {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "DOBEDUB/Studio",
                    "Dimensions": [["Environment", "Operation", "StatusFamily"]],
                    "Metrics": [
                        {"Name": "ApiLatencyMs", "Unit": "Milliseconds"},
                        {"Name": "ApiRequestCount", "Unit": "Count"},
                        {"Name": "ApiErrorCount", "Unit": "Count"},
                        {"Name": "AssetRangeRequestCount", "Unit": "Count"},
                    ],
                }
            ],
        },
        "event": "request_timing",
        "environment": environment,
        "operation": operation,
        "status": status_code,
        "statusFamily": status_family,
        "requestId": request_id,
        "totalMs": total_ms,
        "authMs": round(timings.get("auth", 0.0), 3),
        "dbMs": round(timings.get("db", 0.0), 3),
        "fileStatMs": round(timings.get("file_stat", 0.0), 3),
        "renderMs": round(timings.get("render", 0.0), 3),
        "rangeRequest": range_request,
        "slowRequest": total_ms >= slow_request_ms,
        "Environment": environment,
        "Operation": operation,
        "StatusFamily": status_family,
        "ApiLatencyMs": total_ms,
        "ApiRequestCount": 1,
        "ApiErrorCount": 1 if status_code >= 400 else 0,
        "AssetRangeRequestCount": 1 if range_request else 0,
    }
