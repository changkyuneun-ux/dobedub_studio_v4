from __future__ import annotations

import json
import urllib.error
import urllib.request


TERMINAL_RUNPOD_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


def idle_worker_capacity(health: dict) -> dict:
    """Normalize the small set of worker-capacity shapes returned by /health.

    Unknown capacity intentionally does not permit dispatch. That keeps Studio
    from building a second opaque provider queue when RunPod cannot confirm an
    idle Serverless worker.
    """
    workers = health.get("workers") if isinstance(health, dict) else None
    if not isinstance(workers, dict):
        return {"known": False, "idle": 0, "source": "workers unavailable"}

    for key in ("idle", "available", "ready"):
        value = workers.get(key)
        try:
            return {"known": True, "idle": max(0, int(value)), "source": f"workers.{key}"}
        except (TypeError, ValueError):
            continue
    return {"known": False, "idle": 0, "source": "idle worker count unavailable"}


def is_real_secret(value: str, placeholder: str) -> bool:
    return bool(value and value.strip() and value.strip() != placeholder)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}...{value[-4:]}"


def runpod_is_configured(api_key: str, endpoint_id: str) -> bool:
    return (
        is_real_secret(api_key, "your_runpod_api_key")
        and is_real_secret(endpoint_id, "your_runpod_endpoint_id")
    )


def runpod_headers(api_key: str, endpoint_id: str) -> dict[str, str]:
    if not runpod_is_configured(api_key, endpoint_id):
        raise ValueError("RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID are required for RunPod submission")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def runpod_request(method: str, path: str, *, api_key: str, endpoint_id: str, base_url: str, timeout: int, payload=None):
    url = f"{base_url.rstrip('/')}/{endpoint_id}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=runpod_headers(api_key, endpoint_id))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"RunPod HTTP {exc.code}: {detail}") from exc


def connection_status(*, api_key: str, endpoint_id: str, base_url: str, timeout: int) -> dict:
    if not runpod_is_configured(api_key, endpoint_id):
        return {
            "ok": False,
            "message": "RUNPOD_API_KEY / RUNPOD_ENDPOINT_ID is not configured.",
        }
    health = runpod_request("GET", "/health", api_key=api_key, endpoint_id=endpoint_id, base_url=base_url, timeout=timeout)
    return {
        "ok": True,
        "endpointId": mask_secret(endpoint_id),
        "baseUrl": base_url,
        "workers": health.get("workers") or {},
        "jobs": health.get("jobs") or {},
        "message": "RunPod endpoint health check succeeded.",
    }
