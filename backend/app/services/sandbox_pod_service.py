from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from backend.app.core.config import Settings
from backend.app.core.timezone_utils import UTC_TIMEZONE, parse_timestamp, timestamp_fields, utc_now


def sandbox_pod_is_configured(settings: Settings) -> bool:
    selector = (
        settings.sandbox_pod_network_volume_id.strip()
        or settings.sandbox_pod_template_id.strip()
        or settings.sandbox_pod_name.strip()
        or settings.sandbox_pod_id.strip()
    )
    return bool(selector and settings.sandbox_pod_api_key.strip())


def sandbox_pod_status(settings: Settings) -> dict:
    if not sandbox_pod_is_configured(settings):
        return {
            "configured": False,
            "message": "RUNPOD_SANDBOX_POD_ID 및 RUNPOD_SANDBOX_POD_API_KEY가 설정되지 않았습니다.",
            "httpServices": [],
        }
    pod, resolved_by = _resolve_pod(settings)
    return _present_pod(settings, pod, resolved_by)


def start_sandbox_pod(settings: Settings) -> dict:
    _require_configuration(settings)
    pod, resolved_by = _resolve_pod(settings)
    if str(pod.get("desiredStatus") or "").upper() in {"EXITED", "TERMINATED"}:
        return _deploy_sandbox_pod(settings)
    response = _request(settings, "POST", f"/pods/{pod['id']}/start")
    status = _present_pod(settings, _hydrate_pod(settings, response or pod, strict=False), resolved_by)
    status["message"] = "Sandbox Pod 시작을 요청했습니다. RUNNING 상태와 HTTP 서비스 준비 여부를 새로고침으로 확인하세요."
    return status


def stop_sandbox_pod(settings: Settings) -> dict:
    _require_configuration(settings)
    pod, resolved_by = _resolve_pod(settings)
    response = _request(settings, "POST", f"/pods/{pod['id']}/stop")
    status = _present_pod(settings, _hydrate_pod(settings, response or pod, strict=False), resolved_by)
    status["message"] = "Sandbox Pod 중지를 요청했습니다."
    return status


def _require_configuration(settings: Settings) -> None:
    if not sandbox_pod_is_configured(settings):
        raise ValueError("RUNPOD_SANDBOX_NETWORK_VOLUME_ID(권장) 또는 다른 Sandbox Pod selector와 RUNPOD_SANDBOX_POD_API_KEY가 필요합니다.")


def _deploy_sandbox_pod(settings: Settings) -> dict:
    template_id = settings.sandbox_pod_template_id.strip()
    network_volume_id = settings.sandbox_pod_network_volume_id.strip()
    gpu_type_id = settings.sandbox_pod_gpu_type_id.strip()
    if not (template_id and network_volume_id and gpu_type_id):
        raise ValueError(
            "새 Sandbox Pod 생성에는 RUNPOD_SANDBOX_TEMPLATE_ID, "
            "RUNPOD_SANDBOX_NETWORK_VOLUME_ID, RUNPOD_SANDBOX_GPU_TYPE_ID가 필요합니다."
        )

    response = _request(
        settings,
        "POST",
        "/pods",
        {
            "name": settings.sandbox_pod_deploy_name.strip() or "dobedub_comfyUI_Sandbox",
            "templateId": template_id,
            "networkVolumeId": network_volume_id,
            "gpuTypeIds": [gpu_type_id],
            "gpuCount": settings.sandbox_pod_gpu_count,
        },
    )
    status = _present_pod(settings, response, "template+network-volume+gpu")
    status["message"] = "새 Sandbox Pod 생성을 요청했습니다. GPU 할당과 HTTP 서비스 준비까지 잠시 기다린 뒤 Refresh Status를 누르세요."
    return status


def _resolve_pod(settings: Settings) -> tuple[dict, str]:
    """Resolve the current physical Pod without trusting its migration-sensitive ID or name."""
    volume_id = settings.sandbox_pod_network_volume_id.strip()
    template_id = settings.sandbox_pod_template_id.strip()
    pod_name_prefix = settings.sandbox_pod_name.strip()
    if not (volume_id or template_id or pod_name_prefix):
        pod = _request(settings, "GET", f"/pods/{settings.sandbox_pod_id.strip()}")
        return pod, "pod-id"

    response = _request(settings, "GET", "/pods?includeNetworkVolume=true")
    pods = response if isinstance(response, list) else response.get("items") or response.get("pods") or []
    matches = list(pods)
    if volume_id:
        matches = [pod for pod in matches if _network_volume_id(pod) == volume_id]
    if template_id:
        matches = [pod for pod in matches if str(pod.get("templateId") or "") == template_id]
    if not (volume_id or template_id) and pod_name_prefix:
        normalized_prefix = pod_name_prefix.lower()
        matches = [
            pod for pod in matches
            if str(pod.get("name") or "").lower().startswith(normalized_prefix)
        ]
    if not matches:
        selectors = []
        if volume_id:
            selectors.append(f"network volume '{volume_id}'")
        if template_id:
            selectors.append(f"template '{template_id}'")
        if pod_name_prefix and not selectors:
            selectors.append(f"name prefix '{pod_name_prefix}'")
        raise ValueError(f"Sandbox Pod selector ({', '.join(selectors)})에 일치하는 Pod를 찾지 못했습니다.")

    non_terminated = [pod for pod in matches if str(pod.get("desiredStatus") or "").upper() != "TERMINATED"]
    candidates = non_terminated or matches

    # Pod migration leaves earlier EXITED Pods attached to the same Network
    # Volume and template. Prefer the single active Pod; when every matching
    # Pod is stopped, choose the most recently started one for a start request.
    active_states = {"RUNNING", "STARTING", "PENDING", "CREATED", "RESTARTING"}
    active_candidates = [
        pod for pod in candidates
        if str(pod.get("desiredStatus") or "").upper() in active_states
    ]
    if len(active_candidates) == 1:
        candidates = active_candidates
    elif not active_candidates and candidates:
        candidates = [_most_recent_pod(candidates)]

    if len(candidates) != 1:
        ids = ", ".join(str(pod.get("id") or "-") for pod in candidates)
        raise ValueError(
            f"Sandbox Pod selector에 일치하는 Pod가 {len(candidates)}개입니다 ({ids}). "
            "전용 RUNPOD_SANDBOX_NETWORK_VOLUME_ID를 지정하거나 Template ID를 함께 설정하세요."
        )
    resolved_by = "+".join(part for part, value in (
        ("network-volume", volume_id),
        ("template-id", template_id),
        ("pod-name-prefix", pod_name_prefix if not (volume_id or template_id) else ""),
    ) if value)
    # The list response is sufficient to select the migration-safe Pod, but it
    # does not consistently include lifecycle fields such as lastStartedAt.
    # Always hydrate the chosen Pod from its detail endpoint before presenting
    # its operational status.
    return _hydrate_pod(settings, candidates[0]), resolved_by


def _hydrate_pod(settings: Settings, pod: dict, *, strict: bool = True) -> dict:
    pod_id = str(pod.get("id") or "").strip()
    if not pod_id:
        return pod
    try:
        detail = _request(settings, "GET", f"/pods/{pod_id}")
    except RuntimeError:
        if strict:
            raise
        return pod
    if not isinstance(detail, dict):
        return pod
    # Keep list-only values when a detail response omits an optional field.
    return {**pod, **{key: value for key, value in detail.items() if value is not None}}


def _most_recent_pod(pods: list[dict]) -> dict:
    return max(
        pods,
        key=lambda pod: str(
            pod.get("lastStartedAt")
            or pod.get("createdAt")
            or pod.get("lastStatusChange")
            or ""
        ),
    )


def _network_volume_id(pod: dict) -> str:
    value = pod.get("networkVolume")
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(pod.get("networkVolumeId") or "")


def _request(settings: Settings, method: str, path: str, body: dict | None = None) -> dict:
    url = f"{settings.sandbox_pod_rest_url.rstrip('/')}{path}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.sandbox_pod_api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.sandbox_pod_timeout) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Sandbox Pod API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Sandbox Pod API 연결 실패: {exc.reason}") from exc


def _graphql_request(settings: Settings, query: str, variables: dict[str, str]) -> dict:
    """Query RunPod's Pod runtime fields without exposing the API key to clients."""
    api_key = settings.sandbox_pod_graphql_api_key.strip() or settings.sandbox_pod_api_key
    query_string = urllib.parse.urlencode({"api_key": api_key})
    url = f"{settings.sandbox_pod_graphql_url.rstrip('/')}?{query_string}"
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.sandbox_pod_timeout) as response:
            payload = response.read().decode("utf-8")
            parsed = json.loads(payload) if payload.strip() else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Sandbox Pod runtime API HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Sandbox Pod runtime API 연결 실패: {exc.reason}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Sandbox Pod runtime API 응답 형식이 올바르지 않습니다.")
    errors = parsed.get("errors")
    if errors:
        raise RuntimeError("Sandbox Pod runtime API가 상태 정보를 반환하지 않았습니다.")
    data = parsed.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Sandbox Pod runtime API 응답 데이터가 없습니다.")
    return data


def _present_pod(settings: Settings, pod: dict, resolved_by: str) -> dict:
    pod_id = str(pod.get("id") or settings.sandbox_pod_id).strip()
    services = _http_services(pod_id, pod.get("ports") or [])
    status = str(pod.get("desiredStatus") or pod.get("status") or "UNKNOWN").upper()
    runtime_status = _runtime_status(settings, pod_id, status, services)
    system_status = _runtime_metrics(settings, pod_id, pod)
    if not any(service["internalPort"] == 8188 for service in services):
        message = "ComfyUI HTTP 8188 포트가 노출되지 않았습니다. RunPod Pod 설정을 확인하세요."
    elif runtime_status == "READY":
        message = "Sandbox Pod와 ComfyUI HTTP 8188 서비스가 준비되었습니다."
    elif status == "RUNNING":
        message = "Sandbox Pod는 실행 중이며 ComfyUI HTTP 8188 서비스 준비를 확인 중입니다. 잠시 후 Refresh Status를 누르세요."
    else:
        message = "Sandbox Pod 상태를 조회했습니다."
    lifecycle_event = str(pod.get("lastStatusChange") or "").strip() or None
    lifecycle_event_at = _lifecycle_event_timestamp(lifecycle_event)
    return {
        "configured": True,
        "podId": pod_id,
        "podName": pod.get("name") or None,
        "resolvedBy": resolved_by,
        "desiredStatus": status,
        "runtimeStatus": runtime_status,
        # RunPod's Pod API documents lastStartedAt as UTC. Explicit offsets in
        # the source still take precedence in timestamp_fields.
        **timestamp_fields(
            "lastStartedAt",
            pod.get("lastStartedAt"),
            naive_timezone=UTC_TIMEZONE,
            source_timezone="UTC",
            source="runpod-sandbox",
        ),
        **timestamp_fields(
            "lastStatusChange",
            lifecycle_event_at,
            naive_timezone=UTC_TIMEZONE,
            source_timezone="UTC",
            source="runpod-sandbox-lifecycle-event",
        ),
        "lastLifecycleEvent": lifecycle_event,
        **timestamp_fields(
            "checkedAt",
            utc_now(),
            naive_timezone=UTC_TIMEZONE,
            source_timezone="UTC",
            source="ecs-application",
        ),
        "locked": bool(pod.get("locked")),
        "httpServices": services,
        "systemStatus": system_status,
        "message": message,
    }


def _http_services(pod_id: str, ports: list[object]) -> list[dict]:
    service_labels = {8188: "ComfyUI", 8080: "FileBrowser", 8888: "JupyterLab"}
    services: list[dict] = []
    for item in ports:
        try:
            raw_port, protocol = str(item).split("/", 1)
            port = int(raw_port)
        except (TypeError, ValueError):
            continue
        if protocol.lower() != "http" or port not in service_labels:
            continue
        services.append({
            "internalPort": port,
            "url": f"https://{pod_id}-{port}.proxy.runpod.net",
            "label": service_labels[port],
        })
    # The readiness source is presented first; the other links are supplementary
    # access points and do not participate in the READY decision.
    display_order = {8188: 0, 8080: 1, 8888: 2}
    return sorted(services, key=lambda service: display_order[service["internalPort"]])


def _runtime_metrics(settings: Settings, pod_id: str, pod: dict) -> dict:
    """Return best-effort runtime metrics. A metrics outage must not block Pod control."""
    storage = {
        "containerDiskInGb": _number_or_none(pod.get("containerDiskInGb")),
        "volumeInGb": _number_or_none(pod.get("volumeInGb")),
        "networkVolumeId": _network_volume_id(pod) or None,
    }
    fallback = {
        "gpuCount": _number_or_none(pod.get("gpuCount")),
        "gpuType": _gpu_type_name(pod),
        "memoryInGb": _number_or_none(pod.get("memoryInGb")),
    }
    query = """
        query SandboxPodRuntime($podId: String!) {
          pod(input: { podId: $podId }) {
            runtime {
              uptimeInSeconds
              container { cpuPercent memoryPercent }
              gpus { id gpuUtilPercent memoryUtilPercent }
            }
          }
        }
    """
    try:
        response = _graphql_request(settings, query, {"podId": pod_id})
        pod_data = response.get("pod") if isinstance(response, dict) else None
        runtime = pod_data.get("runtime") if isinstance(pod_data, dict) else None
        if not isinstance(runtime, dict):
            raise RuntimeError("Sandbox Pod runtime 정보가 아직 준비되지 않았습니다.")
        container = runtime.get("container") if isinstance(runtime.get("container"), dict) else {}
        gpus = runtime.get("gpus") if isinstance(runtime.get("gpus"), list) else []
        return {
            "available": True,
            "mode": "live",
            "uptimeSeconds": _number_or_none(runtime.get("uptimeInSeconds")),
            "cpuPercent": _number_or_none(container.get("cpuPercent")),
            "memoryPercent": _number_or_none(container.get("memoryPercent")),
            "gpus": [
                {
                    "id": str(gpu.get("id") or f"GPU {index + 1}"),
                    "gpuUtilPercent": _number_or_none(gpu.get("gpuUtilPercent")),
                    "memoryUtilPercent": _number_or_none(gpu.get("memoryUtilPercent")),
                }
                for index, gpu in enumerate(gpus)
                if isinstance(gpu, dict)
            ],
            **fallback,
            "storage": storage,
        }
    except RuntimeError as exc:
        return {
            "available": False,
            "mode": "configuration",
            "gpus": [],
            **fallback,
            "storage": storage,
            "message": _runtime_metric_fallback_message(exc),
        }


def _number_or_none(value: object) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _gpu_type_name(pod: dict) -> str | None:
    values = pod.get("gpuTypeIds") or pod.get("gpuTypes") or []
    if isinstance(values, list) and values:
        return ", ".join(str(value) for value in values if value)
    value = pod.get("gpuTypeId")
    return str(value) if value else None


def _runtime_metric_fallback_message(error: RuntimeError) -> str:
    message = str(error)
    if "HTTP 403" in message:
        return "실시간 CPU·메모리·GPU 사용률은 GraphQL 조회 권한이 있는 RunPod API 키가 필요합니다. 현재 Pod 구성 및 저장소 정보만 표시합니다."
    return "실시간 런타임 상태를 불러오지 못했습니다. 현재 Pod 구성 및 저장소 정보만 표시합니다."


def _lifecycle_event_timestamp(value: str | None) -> datetime | None:
    """Extract a timestamp from RunPod's descriptive lifecycle event safely.

    `lastStatusChange` is not a guaranteed timestamp field. Current RunPod
    responses use strings such as ``Rented by User: Fri Aug 07 2026 07:51:24
    GMT+0000 (...)``. We only normalize the date when it can be parsed; the
    original event text remains available to the UI either way.
    """
    if not value:
        return None
    parsed = parse_timestamp(value, naive_timezone=UTC_TIMEZONE)
    if parsed is not None:
        return parsed
    matched = re.search(
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+GMT[+-]\d{4}",
        value,
    )
    if not matched:
        return None
    try:
        return datetime.strptime(matched.group(0), "%a %b %d %Y %H:%M:%S GMT%z")
    except ValueError:
        return None


def _runtime_status(settings: Settings, pod_id: str, desired_status: str, services: list[dict]) -> str:
    if desired_status != "RUNNING":
        return desired_status
    service = next((item for item in services if item["internalPort"] == 8188), None)
    if service is None:
        return "INITIALIZING"
    service_url = service["url"]
    request = urllib.request.Request(service_url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=min(settings.sandbox_pod_timeout, 5)) as response:
            return "READY" if 200 <= response.status < 500 else "INITIALIZING"
    except urllib.error.HTTPError as exc:
        return "READY" if 200 <= exc.code < 500 else "INITIALIZING"
    except (urllib.error.URLError, TimeoutError):
        return "INITIALIZING"
