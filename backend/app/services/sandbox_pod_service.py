from __future__ import annotations

import json
import urllib.error
import urllib.request

from backend.app.core.config import Settings
from backend.app.core.timezone_utils import SEOUL_TIMEZONE, timestamp_fields


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
    status = _present_pod(settings, response or pod, resolved_by)
    status["message"] = "Sandbox Pod 시작을 요청했습니다. RUNNING 상태와 HTTP 서비스 준비 여부를 새로고침으로 확인하세요."
    return status


def stop_sandbox_pod(settings: Settings) -> dict:
    _require_configuration(settings)
    pod, resolved_by = _resolve_pod(settings)
    response = _request(settings, "POST", f"/pods/{pod['id']}/stop")
    status = _present_pod(settings, response or pod, resolved_by)
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
    return candidates[0], resolved_by


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


def _present_pod(settings: Settings, pod: dict, resolved_by: str) -> dict:
    pod_id = str(pod.get("id") or settings.sandbox_pod_id).strip()
    services = []
    for item in pod.get("ports") or []:
        try:
            raw_port, protocol = str(item).split("/", 1)
            port = int(raw_port)
        except (TypeError, ValueError):
            continue
        if protocol.lower() != "http" or port != 8188:
            continue
        services.append({
            "internalPort": port,
            "url": f"https://{pod_id}-{port}.proxy.runpod.net",
            "label": f"HTTP {port}",
        })
    status = str(pod.get("desiredStatus") or pod.get("status") or "UNKNOWN").upper()
    runtime_status = _runtime_status(settings, pod_id, status, services)
    if not services:
        message = "ComfyUI HTTP 8188 포트가 노출되지 않았습니다. RunPod Pod 설정을 확인하세요."
    elif runtime_status == "READY":
        message = "Sandbox Pod와 ComfyUI HTTP 8188 서비스가 준비되었습니다."
    elif status == "RUNNING":
        message = "Sandbox Pod는 실행 중이며 ComfyUI HTTP 8188 서비스 준비를 확인 중입니다. 잠시 후 Refresh Status를 누르세요."
    else:
        message = "Sandbox Pod 상태를 조회했습니다."
    return {
        "configured": True,
        "podId": pod_id,
        "podName": pod.get("name") or None,
        "resolvedBy": resolved_by,
        "desiredStatus": status,
        "runtimeStatus": runtime_status,
        # RunPod Pod lifecycle timestamps are provided in KST by the configured
        # sandbox environment. Preserve their raw source timezone while also
        # returning a UTC equivalent for operations and audit comparison.
        **timestamp_fields(
            "lastStartedAt",
            pod.get("lastStartedAt"),
            naive_timezone=SEOUL_TIMEZONE,
            source_timezone="Asia/Seoul",
            source="runpod-sandbox",
        ),
        **timestamp_fields(
            "lastStatusChange",
            pod.get("lastStatusChange"),
            naive_timezone=SEOUL_TIMEZONE,
            source_timezone="Asia/Seoul",
            source="runpod-sandbox",
        ),
        "locked": bool(pod.get("locked")),
        "httpServices": services,
        "message": message,
    }


def _runtime_status(settings: Settings, pod_id: str, desired_status: str, services: list[dict]) -> str:
    if desired_status != "RUNNING":
        return desired_status
    if not services:
        return "INITIALIZING"
    service_url = services[0]["url"]
    request = urllib.request.Request(service_url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=min(settings.sandbox_pod_timeout, 5)) as response:
            return "READY" if 200 <= response.status < 500 else "INITIALIZING"
    except urllib.error.HTTPError as exc:
        return "READY" if 200 <= exc.code < 500 else "INITIALIZING"
    except (urllib.error.URLError, TimeoutError):
        return "INITIALIZING"
