from __future__ import annotations

import json
import urllib.error
import urllib.parse
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


# --- 서버리스 빌링(계정 단위, 엔드포인트 실행과는 별개 호스트) ------------------
# 2026-09-15: 대시보드 "컷 길이별 비용" 카드(5초컷/10초컷 배분)의 원천 데이터.
# 주의: 잡 제출/상태 조회(runpod_request 위)는 RUNPOD_BASE_URL(api.runpod.ai/v2,
# 엔드포인트별 실행 API)을 쓰지만, 빌링은 계정 단위 REST v2 API로 완전히 다른
# 호스트(api.runpod.io — .ai가 아니라 .io)에 있다. 두 호스트를 혼동하면 404/HTML
# 응답이 온다(과거 Sandbox Pod REST v2 host 버그와 같은 함정 - workflow_visibility류
# 문제와 무관, RunPod 자체 API 설계).
BILLING_BASE_URL = "https://api.runpod.io/v2"


def fetch_serverless_billing_daily(
    *, api_key: str, serverless_id: str, start_time: str, end_time: str, timeout: int = 20
) -> dict[str, dict]:
    """RunPod 서버리스 일별 청구 내역을 UTC 날짜 문자열(YYYY-MM-DD) 키로 반환한다.

    ``start_time``/``end_time``은 RFC3339 문자열(예: "2026-09-10T00:00:00Z")이어야 한다.
    비용이 0인 날짜는 RunPod 응답에서 그 레코드 자체가 빠지므로(레코드가 없다고
    0비용을 의미하는 게 아니라 "그 버킷은 청구가 없어 생략됨"), 호출자가 없는
    날짜를 0으로 채워야 한다. ``api_key``/``serverless_id``가 비어 있으면 빈
    dict를 반환한다(설정 미완료를 예외로 취급하지 않음 - 대시보드는 그 구간을
    그냥 "표시 안 함" 처리한다).
    """
    if not is_real_secret(api_key, "your_runpod_api_key") or not serverless_id:
        return {}
    query = urllib.parse.urlencode({
        "serverlessId": serverless_id,
        "bucketSize": "day",
        "startTime": start_time,
        "endTime": end_time,
    })
    url = f"{BILLING_BASE_URL}/billing/serverless?{query}"
    request = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"RunPod billing HTTP {exc.code}: {detail}") from exc

    by_day: dict[str, dict] = {}
    for record in payload.get("records") or []:
        day = str(record.get("startTime") or "")[:10]
        if not day:
            continue
        by_day[day] = {
            "totalAmount": float(record.get("totalAmount") or 0.0),
            "gpuAmount": float(record.get("gpuAmount") or 0.0),
            "cpuAmount": float(record.get("cpuAmount") or 0.0),
            "diskAmount": float(record.get("diskAmount") or 0.0),
            "feeAmount": float(record.get("feeAmount") or 0.0),
        }
    return by_day
