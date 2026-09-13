from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from backend.app.core.config import Settings
from backend.app.core.timezone_utils import UTC_TIMEZONE, parse_timestamp, timestamp_fields, utc_now


RUNPOD_HTTP_USER_AGENT = "dobedub-studio/1.0"
ACTIVE_STATES = {"RUNNING", "STARTING", "PENDING", "CREATED", "RESTARTING"}
_START_RECHECK_DELAY_SECONDS = 3
_STOP_POLL_INTERVAL_SECONDS = 3
_NO_CAPACITY_MARKERS = ("no instances", "not enough", "not available", "no longer available")
_ERROR_DETAIL_LIMIT = 200

# Patched in tests so staged retries do not sleep for real.
_sleep = time.sleep


class SandboxPodApiError(RuntimeError):
    """A RunPod REST call failed. ``status`` is None for connection failures."""

    def __init__(self, status: int | None, detail: str) -> None:
        self.status = status
        self.detail = detail or ""
        if status is None:
            super().__init__(f"Sandbox Pod API 연결 실패: {detail}")
        else:
            super().__init__(f"Sandbox Pod API HTTP {status}: {detail}")


class SandboxPodUnavailable(RuntimeError):
    """Every start/switch/create stage failed. Carries the attempt log for the API and UI."""

    def __init__(self, message: str, attempts: list[dict], *, retry_after_seconds: int = 300) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.retry_after_seconds = retry_after_seconds


class SandboxPodConflict(RuntimeError):
    """The single-running-Pod invariant is violated or a switch could not complete."""

    def __init__(self, message: str, attempts: list[dict], *, running_pod_ids: list[str]) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.running_pod_ids = running_pod_ids


@dataclass(frozen=True)
class SandboxPodPrefs:
    """Operator preferences stored in ``sandbox_pod_settings`` (spec §5.1)."""

    selected_pod_id: str | None = None
    auto_switch_on_start_failure: bool = True
    pod_priority: tuple[str, ...] = ()
    # After a successful create, terminate stopped Pods with the same GPU so the
    # volume keeps at most one Pod per GPU type (host-pinned stopped Pods can
    # never be resumed when their host is busy, so replacing is the recovery).
    replace_same_gpu_pods: bool = True
    payload: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sandbox_pod_is_configured(settings: Settings) -> bool:
    selector = (
        settings.sandbox_pod_network_volume_id.strip()
        or settings.sandbox_pod_template_id.strip()
        or settings.sandbox_pod_name.strip()
        or settings.sandbox_pod_id.strip()
    )
    return bool(selector and settings.sandbox_pod_api_key.strip())


def sandbox_pod_status(
    settings: Settings,
    db=None,
    *,
    prefs: SandboxPodPrefs | None = None,
    include_live: bool = True,
) -> dict:
    """Full status. ``include_live=False`` skips the 8188 probe and v2 runtime metrics
    (2단계 로딩의 1단계): ``runtimeStatus``는 desiredStatus, ``systemStatus.mode``는
    ``"pending"``으로 채워지고 화면이 ``sandbox_pod_live``로 나중에 덮어쓴다."""
    if not sandbox_pod_is_configured(settings):
        return {
            "configured": False,
            "message": "RUNPOD_SANDBOX_NETWORK_VOLUME_ID 및 RUNPOD_SANDBOX_POD_API_KEY가 설정되지 않았습니다.",
            "httpServices": [],
            "pods": [],
            "selectedPodId": None,
            "activePodId": None,
            "conflict": False,
            "conflictPodIds": [],
            "attempts": [],
        }
    prefs = prefs or _load_prefs(db)
    pods = _resolve_pods(settings)
    return _build_status(settings, pods, prefs, attempts=[], include_live=include_live)


def sandbox_pod_live(settings: Settings, db=None, *, prefs: SandboxPodPrefs | None = None) -> dict:
    """2단계 로딩의 2단계: 표시 파드의 8188 준비 상태·v2 runtime 지표와 RUNNING 파드별
    runtimeStatus만 반환한다. 목록·설정은 ``sandbox_pod_status(include_live=False)``가 담당."""
    if not sandbox_pod_is_configured(settings):
        return {"configured": False, "podId": None, "runtimeStatus": None, "systemStatus": None, "pods": []}
    prefs = prefs or _load_prefs(db)
    pods = _resolve_pods(settings)
    display = _display_pod(pods, prefs.selected_pod_id)
    live = _collect_live_info(settings, pods, display)
    pod_statuses = [
        {"podId": str(pod.get("id") or ""), "runtimeStatus": live["runtime_status"].get(str(pod.get("id") or ""), _status_of(pod) or "UNKNOWN")}
        for pod in pods
    ]
    if display is None:
        return {
            "configured": True,
            "podId": None,
            "runtimeStatus": "NONE",
            "systemStatus": {"available": False, "mode": "configuration", "gpus": []},
            "message": None,
            "pods": pod_statuses,
            **timestamp_fields("checkedAt", utc_now(), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="ecs-application"),
        }
    pod_id = str(display.get("id") or settings.sandbox_pod_id).strip()
    services = _http_services(pod_id, display.get("ports") or [], jupyter_auth_required=_jupyter_auth_required(display))
    status = str(display.get("desiredStatus") or display.get("status") or "UNKNOWN").upper()
    runtime_status = live["runtime_status"].get(pod_id, status)
    return {
        "configured": True,
        "podId": pod_id,
        "desiredStatus": status,
        "runtimeStatus": runtime_status,
        "systemStatus": live["system_status"],
        "message": _readiness_message(services, status, runtime_status),
        "pods": pod_statuses,
        **timestamp_fields("checkedAt", utc_now(), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="ecs-application"),
    }


def start_sandbox_pod(
    settings: Settings,
    db=None,
    pod_id: str | None = None,
    *,
    actor_id: str | None = None,
    prefs: SandboxPodPrefs | None = None,
) -> dict:
    """Start the selected Pod, enforcing the single-running-Pod invariant (spec §5.3).

    Stages: ⓪ stop other running Pods and wait → ① start target → ② start
    another stopped Pod (auto switch) → ③/④ create with primary then fallback
    GPUs. Every stage is appended to ``attempts``.
    """
    _require_configuration(settings)
    prefs = prefs or _load_prefs(db)
    attempts: list[dict] = []
    pods = _resolve_pods(settings)

    conflict_ids = _conflict_pod_ids(pods)
    if conflict_ids:
        _log_event(settings, "conflict", pod_id=",".join(conflict_ids), gpu_type_id=None)
        conflict_names = ", ".join(_pod_display(pod) for pod in pods if str(pod.get("id")) in conflict_ids)
        raise SandboxPodConflict(
            f"실행 중인 Sandbox Pod가 {len(conflict_ids)}개입니다 ({conflict_names}). "
            "볼륨 손상 위험이 있어 Start를 거부했습니다. 하나만 남기고 정지한 뒤 다시 시도하세요.",
            attempts,
            running_pod_ids=conflict_ids,
        )

    target = _pick_target(pods, pod_id, prefs.selected_pod_id)
    if pod_id and target is None:
        raise ValueError(f"Pod '{pod_id}'를 Sandbox 볼륨에 연결된 파드 목록에서 찾을 수 없습니다. Refresh Status 후 다시 선택하세요.")

    switched = False
    created_by: str | None = None
    if target is not None:
        target_status = _status_of(target)
        if target_status in ACTIVE_STATES:
            # Idempotent: the selected Pod is already up. Re-issue start so a
            # STARTING Pod is nudged, then present the current state.
            response = _request(settings, "POST", f"/pods/{target['id']}/start")
            refreshed = _hydrate_pod(settings, response or target, strict=False)
            pods = _replace_pod(pods, refreshed)
            _persist_selection(db, target["id"], actor_id)
            status = _build_status(settings, pods, _with_selected(prefs, target["id"]), attempts=attempts)
            status["message"] = "Sandbox Pod 시작을 요청했습니다. RUNNING 상태와 HTTP 서비스 준비 여부를 새로고침으로 확인하세요."
            return status

        _switch_off_others(settings, pods, target["id"], attempts)

        started = _attempt_start(settings, target, attempts, stage="start")
        if started is not None:
            _persist_selection(db, target["id"], actor_id)
            pods = _replace_pod(pods, started)
            status = _build_status(settings, pods, _with_selected(prefs, target["id"]), attempts=attempts)
            status["message"] = (
                f"정지된 {_pod_display(started)} 파드를 다시 시작했습니다. "
                "HTTP 서비스 준비 여부를 새로고침으로 확인하세요."
            )
            return status

        if prefs.auto_switch_on_start_failure:
            for candidate in _switch_candidates(pods, prefs.pod_priority, exclude_id=target["id"]):
                started = _attempt_start(settings, candidate, attempts, stage="switch")
                if started is None:
                    continue
                switched = True
                _log_event(settings, "switch", pod_id=candidate["id"], gpu_type_id=_gpu_type_name(candidate))
                _persist_selection(db, candidate["id"], actor_id)
                pods = _replace_pod(pods, started)
                status = _build_status(
                    settings, pods, _with_selected(prefs, candidate["id"]), attempts=attempts, switched=True
                )
                status["message"] = (
                    f"선택한 {_pod_display(target)} 파드는 재고 부족으로 기동하지 못해 "
                    f"{_pod_display(candidate)} 파드를 대신 시작했습니다."
                )
                return status
    else:
        # No target: nothing on the volume yet or every Pod is gone. Still make
        # sure nothing else is running before creating a new one.
        _switch_off_others(settings, pods, None, attempts)

    created, gpu = _attempt_create(settings, attempts)
    created_by = "auto-fallback"
    pod_for_status = _hydrate_pod(settings, created, strict=False)
    _persist_selection(db, str(pod_for_status.get("id") or ""), actor_id)
    pods = [pod for pod in pods if pod.get("id") != pod_for_status.get("id")] + [pod_for_status]
    if prefs.replace_same_gpu_pods:
        pods = _terminate_replaced_pods(settings, pods, keep_pod_id=str(pod_for_status.get("id") or ""), gpu=gpu, attempts=attempts)
    status = _build_status(
        settings,
        pods,
        _with_selected(prefs, str(pod_for_status.get("id") or "")),
        attempts=attempts,
        switched=switched,
        created_by=created_by,
        resolved_by=f"create:{gpu}",
    )
    status["message"] = _create_message(settings, gpu, attempts, target)
    return status


def stop_sandbox_pod(
    settings: Settings,
    db=None,
    pod_id: str | None = None,
    *,
    actor_id: str | None = None,
    prefs: SandboxPodPrefs | None = None,
) -> dict:
    _require_configuration(settings)
    prefs = prefs or _load_prefs(db)
    pods = _resolve_pods(settings)
    target = None
    if pod_id:
        target = next((pod for pod in pods if str(pod.get("id")) == pod_id), None)
        if target is None:
            raise ValueError(f"Pod '{pod_id}'는 Sandbox 볼륨에 연결된 파드 목록에 없습니다.")
    else:
        active = [pod for pod in pods if _status_of(pod) in ACTIVE_STATES]
        if len(active) == 1:
            target = active[0]
        elif len(active) > 1:
            raise ValueError("실행 중인 Sandbox Pod가 2개 이상입니다. 정지할 Pod ID를 지정하세요.")
        else:
            raise ValueError("실행 중인 Sandbox Pod가 없습니다.")
    response = _request(settings, "POST", f"/pods/{target['id']}/stop")
    refreshed = _hydrate_pod(settings, response or target, strict=False)
    pods = _replace_pod(pods, refreshed)
    attempts = [{"stage": "stop", "podId": str(target["id"]), "podName": target.get("name") or None, "ok": True, "at": _now_iso()}]
    status = _build_status(settings, pods, prefs, attempts=attempts)
    status["stoppedPodId"] = str(target["id"])
    status["message"] = f"{_pod_display(target)} 파드 중지를 요청했습니다."
    return status


def terminate_sandbox_pod(
    settings: Settings,
    db=None,
    pod_id: str | None = None,
    *,
    actor_id: str | None = None,
    prefs: SandboxPodPrefs | None = None,
) -> dict:
    """Delete a stopped Pod from the volume (manual clean-up). Running Pods are refused."""
    _require_configuration(settings)
    prefs = prefs or _load_prefs(db)
    pods = _resolve_pods(settings)
    if not pod_id:
        raise ValueError("삭제할 Pod ID를 지정하세요.")
    target = next((pod for pod in pods if str(pod.get("id")) == pod_id), None)
    if target is None:
        raise ValueError(f"Pod '{pod_id}'를 Sandbox 볼륨에 연결된 파드 목록에서 찾을 수 없습니다.")
    if _status_of(target) in ACTIVE_STATES:
        raise ValueError(f"{_pod_display(target)} 파드는 실행 중이라 삭제할 수 없습니다. 먼저 정지하세요.")
    attempts: list[dict] = []
    if not _terminate_pod(settings, target, attempts):
        raise SandboxPodApiError(None, attempts[-1].get("error") or "terminate failed")
    pods = [pod for pod in pods if str(pod.get("id")) != pod_id]
    next_prefs = prefs
    if prefs.selected_pod_id == pod_id:
        replacement = _most_recent_pod(pods) if pods else None
        next_prefs = _with_selected(prefs, str(replacement.get("id")) if replacement else None)
        _persist_selection(db, next_prefs.selected_pod_id, actor_id, allow_none=True)
    status = _build_status(settings, pods, next_prefs, attempts=attempts)
    status["terminatedPodId"] = pod_id
    status["terminatedPodName"] = target.get("name") or None
    status["message"] = f"{_pod_display(target)} 파드를 삭제했습니다. /workspace 볼륨의 데이터는 유지됩니다."
    return status


def _terminate_pod(settings: Settings, pod: dict, attempts: list[dict]) -> bool:
    pod_id = str(pod.get("id") or "")
    entry = {"stage": "terminate", "podId": pod_id, "podName": pod.get("name") or None, "gpuTypeId": _gpu_type_name(pod), "at": _now_iso()}
    try:
        _request(settings, "DELETE", f"/pods/{pod_id}")
    except RuntimeError as exc:
        attempts.append({**entry, "ok": False, "error": _short_error(exc)})
        _log_attempt(settings, attempts[-1])
        return False
    attempts.append({**entry, "ok": True})
    _log_attempt(settings, attempts[-1])
    _log_event(settings, "terminate", pod_id=pod_id, gpu_type_id=_gpu_type_name(pod))
    return True


def _terminate_replaced_pods(settings: Settings, pods: list[dict], *, keep_pod_id: str, gpu: str, attempts: list[dict]) -> list[dict]:
    """Policy A (2026-09-12): after create, delete stopped Pods with the same GPU type.

    Only EXITED Pods of exactly the created GPU are removed; running Pods and
    other GPU types are never touched. A failed delete is recorded and skipped.
    """
    remaining: list[dict] = []
    for pod in pods:
        same_gpu = _gpu_type_name(pod) == gpu
        if str(pod.get("id")) == keep_pod_id or not same_gpu or _status_of(pod) != "EXITED":
            remaining.append(pod)
            continue
        if not _terminate_pod(settings, pod, attempts):
            remaining.append(pod)
    return remaining


def _require_configuration(settings: Settings) -> None:
    if not sandbox_pod_is_configured(settings):
        raise ValueError("RUNPOD_SANDBOX_NETWORK_VOLUME_ID(권장) 또는 다른 Sandbox Pod selector와 RUNPOD_SANDBOX_POD_API_KEY가 필요합니다.")


# ---------------------------------------------------------------------------
# Preferences (DB-backed, optional so the service stays testable without a DB)
# ---------------------------------------------------------------------------


def _load_prefs(db) -> SandboxPodPrefs:
    if db is None:
        return SandboxPodPrefs()
    from backend.app.services.sandbox_pod_settings_service import sandbox_pod_settings_payload

    payload = sandbox_pod_settings_payload(db)
    return SandboxPodPrefs(
        selected_pod_id=payload.get("selectedPodId") or None,
        auto_switch_on_start_failure=bool(payload.get("autoSwitchOnStartFailure", True)),
        pod_priority=tuple(payload.get("podPriority") or ()),
        replace_same_gpu_pods=bool(payload.get("replaceSameGpuPods", True)),
        payload=payload,
    )


def _with_selected(prefs: SandboxPodPrefs, pod_id: str | None) -> SandboxPodPrefs:
    payload = {**prefs.payload, "selectedPodId": pod_id}
    return SandboxPodPrefs(
        selected_pod_id=pod_id,
        auto_switch_on_start_failure=prefs.auto_switch_on_start_failure,
        pod_priority=prefs.pod_priority,
        replace_same_gpu_pods=prefs.replace_same_gpu_pods,
        payload=payload,
    )


def _persist_selection(db, pod_id: str | None, actor_id: str | None, *, allow_none: bool = False) -> None:
    if db is None or (not pod_id and not allow_none):
        return
    from backend.app.services.sandbox_pod_settings_service import select_sandbox_pod

    try:
        select_sandbox_pod(db, pod_id=pod_id, updated_by=actor_id)
    except Exception:  # noqa: BLE001 - persisting the selection must never block Pod control
        db.rollback()


# ---------------------------------------------------------------------------
# Pod list resolution (volume = identity; template = creation spec only)
# ---------------------------------------------------------------------------


def _resolve_pods(settings: Settings) -> list[dict]:
    """Return every non-terminated Pod attached to the Sandbox Network Volume.

    Without a volume selector the legacy single-Pod resolution is used so
    template / name / ID based deployments keep working.
    """
    volume_id = settings.sandbox_pod_network_volume_id.strip()
    if not volume_id:
        pod, _ = _resolve_pod(settings)
        return [pod]
    response = _request(settings, "GET", "/pods?includeNetworkVolume=true")
    items = response if isinstance(response, list) else response.get("items") or response.get("pods") or []
    matches = [
        pod for pod in items
        if isinstance(pod, dict)
        and _network_volume_id(pod) == volume_id
        and _status_of(pod) != "TERMINATED"
    ]
    if not matches:
        return []
    # 2026-09-13 성능: 파드별 상세 조회를 병렬로, 목록 응답에 필요한 필드가 이미
    # 있으면 생략한다(직렬 N회 → 최대 1회 지연).
    with ThreadPoolExecutor(max_workers=min(8, len(matches))) as pool:
        return list(pool.map(lambda pod: _hydrate_pod_if_needed(settings, pod), matches))


_HYDRATE_REQUIRED_KEYS = ("ports", "memoryInGb", "costPerHr")


def _hydrate_pod_if_needed(settings: Settings, pod: dict) -> dict:
    ports = pod.get("ports")
    complete = (
        isinstance(ports, list) and bool(ports)
        and all(pod.get(key) is not None for key in _HYDRATE_REQUIRED_KEYS)
        and bool(_gpu_type_name(pod))
    )
    if complete:
        return pod
    return _hydrate_pod(settings, pod, strict=False)


def _status_of(pod: dict) -> str:
    return str(pod.get("desiredStatus") or pod.get("status") or "").upper()


def _conflict_pod_ids(pods: list[dict]) -> list[str]:
    running = [str(pod.get("id")) for pod in pods if _status_of(pod) in ACTIVE_STATES]
    return running if len(running) >= 2 else []


def _active_pod(pods: list[dict]) -> dict | None:
    active = [pod for pod in pods if _status_of(pod) in ACTIVE_STATES]
    return active[0] if len(active) == 1 else None


def _pick_target(pods: list[dict], pod_id: str | None, selected_pod_id: str | None) -> dict | None:
    if pod_id:
        return next((pod for pod in pods if str(pod.get("id")) == pod_id), None)
    if selected_pod_id:
        match = next((pod for pod in pods if str(pod.get("id")) == selected_pod_id), None)
        if match is not None:
            return match
    active = _active_pod(pods)
    if active is not None:
        return active
    return _most_recent_pod(pods) if pods else None


def _display_pod(pods: list[dict], selected_pod_id: str | None) -> dict | None:
    """Pod whose fields fill the legacy single-Pod response: active → selected → most recent."""
    active = _active_pod(pods)
    if active is not None:
        return active
    if selected_pod_id:
        match = next((pod for pod in pods if str(pod.get("id")) == selected_pod_id), None)
        if match is not None:
            return match
    return _most_recent_pod(pods) if pods else None


def _replace_pod(pods: list[dict], updated: dict) -> list[dict]:
    updated_id = str(updated.get("id") or "")
    if not updated_id:
        return pods
    return [updated if str(pod.get("id")) == updated_id else pod for pod in pods]


def _switch_candidates(pods: list[dict], priority: tuple[str, ...], *, exclude_id: str) -> list[dict]:
    stopped = [pod for pod in pods if str(pod.get("id")) != exclude_id and _status_of(pod) == "EXITED"]
    if priority:
        order = {pod_id: index for index, pod_id in enumerate(priority)}
        return sorted(stopped, key=lambda pod: (order.get(str(pod.get("id")), len(order)), _price_of(pod) or 1e9))
    return sorted(stopped, key=lambda pod: _price_of(pod) if _price_of(pod) is not None else 1e9)


def _price_of(pod: dict) -> float | None:
    value = _number_or_none(pod.get("costPerHr"))
    return float(value) if value is not None else None


# ---------------------------------------------------------------------------
# Staged start: stop others → start → switch → create
# ---------------------------------------------------------------------------


def _switch_off_others(settings: Settings, pods: list[dict], target_id: str | None, attempts: list[dict]) -> None:
    others = [pod for pod in pods if str(pod.get("id")) != target_id and _status_of(pod) in ACTIVE_STATES]
    for pod in others:
        pod_id = str(pod["id"])
        entry = {"stage": "stop", "podId": pod_id, "podName": pod.get("name") or None, "at": _now_iso()}
        try:
            _request(settings, "POST", f"/pods/{pod_id}/stop")
        except RuntimeError as exc:
            attempts.append({**entry, "ok": False, "error": _short_error(exc)})
            _log_attempt(settings, attempts[-1])
            raise SandboxPodConflict(
                f"실행 중인 Pod {pod_id} 정지 요청이 실패했습니다: {_short_error(exc)}",
                attempts,
                running_pod_ids=[pod_id],
            ) from exc
        if not _wait_until_exited(settings, pod_id):
            attempts.append({**entry, "ok": False, "error": f"stop accepted but pod not EXITED within {settings.sandbox_pod_stop_wait_seconds}s"})
            _log_attempt(settings, attempts[-1])
            raise SandboxPodConflict(
                f"이전 파드 {pod_id} 정지 대기 중입니다 ({settings.sandbox_pod_stop_wait_seconds}초 초과). "
                "잠시 후 Refresh Status로 EXITED를 확인한 뒤 다시 시도하세요.",
                attempts,
                running_pod_ids=[pod_id],
            )
        attempts.append({**entry, "ok": True})
        _log_attempt(settings, attempts[-1])
        pod["desiredStatus"] = "EXITED"


def _wait_until_exited(settings: Settings, pod_id: str) -> bool:
    deadline = settings.sandbox_pod_stop_wait_seconds
    waited = 0
    while True:
        try:
            detail = _request(settings, "GET", f"/pods/{pod_id}")
        except RuntimeError:
            detail = {}
        if isinstance(detail, dict) and _status_of(detail) not in ACTIVE_STATES and detail:
            return True
        if waited >= deadline:
            return False
        _sleep(_STOP_POLL_INTERVAL_SECONDS)
        waited += _STOP_POLL_INTERVAL_SECONDS


def _attempt_start(settings: Settings, pod: dict, attempts: list[dict], *, stage: str) -> dict | None:
    """POST /pods/{id}/start with retries. Returns the refreshed Pod on success, else None."""
    pod_id = str(pod["id"])
    gpu = _gpu_type_name(pod)
    for _ in range(settings.sandbox_pod_start_retry_count + 1):
        entry = {"stage": stage, "podId": pod_id, "podName": pod.get("name") or None, "gpuTypeId": gpu, "at": _now_iso()}
        try:
            _request(settings, "POST", f"/pods/{pod_id}/start")
        except RuntimeError as exc:
            kind = _classify_error(exc)
            attempts.append({**entry, "ok": False, "error": _short_error(exc)})
            _log_attempt(settings, attempts[-1])
            if kind == "config":
                error = ValueError(f"Sandbox Pod 시작 설정/권한 오류 ({pod_id}): {_short_error(exc)}")
                error.attempts = list(attempts)  # type: ignore[attr-defined]
                raise error from exc
            continue
        _sleep(_START_RECHECK_DELAY_SECONDS)
        refreshed = _hydrate_pod(settings, pod, strict=False)
        if _status_of(refreshed) == "EXITED" and not refreshed.get("runtime"):
            attempts.append({**entry, "ok": False, "error": "start accepted but pod stayed EXITED (no GPU assigned)"})
            _log_attempt(settings, attempts[-1])
            continue
        attempts.append({**entry, "ok": True})
        _log_attempt(settings, attempts[-1])
        return refreshed
    return None


def _attempt_create(settings: Settings, attempts: list[dict]) -> tuple[dict, str]:
    template_id = settings.sandbox_pod_template_id.strip()
    network_volume_id = settings.sandbox_pod_network_volume_id.strip()
    if not (template_id and network_volume_id and settings.sandbox_pod_gpu_type_id.strip()):
        raise ValueError(
            "새 Sandbox Pod 생성에는 RUNPOD_SANDBOX_TEMPLATE_ID, "
            "RUNPOD_SANDBOX_NETWORK_VOLUME_ID, RUNPOD_SANDBOX_GPU_TYPE_ID가 필요합니다."
        )
    catalog = _fetch_gpu_catalog(settings)
    vram_by_gpu = {gpu_id: item["memoryInGb"] for gpu_id, item in (catalog or {}).items() if item.get("memoryInGb") is not None}
    name_prefix = settings.sandbox_pod_deploy_name.strip() or "dobedub_comfyUI_Sandbox"
    candidates = _gpu_candidates(settings, vram_by_gpu if catalog else None)
    tried: list[str] = []
    for gpu, skip_reason in candidates:
        entry = {"stage": "create", "gpuTypeId": gpu, "at": _now_iso()}
        if skip_reason:
            attempts.append({**entry, "ok": False, "skipped": skip_reason})
            _log_attempt(settings, attempts[-1])
            continue
        if tried and settings.sandbox_pod_create_attempt_delay_seconds > 0:
            _sleep(settings.sandbox_pod_create_attempt_delay_seconds)
        tried.append(gpu)
        try:
            response = _request(
                settings,
                "POST",
                "/pods",
                {
                    "name": _pod_name_for_gpu(name_prefix, gpu, catalog),
                    "templateId": template_id,
                    "networkVolumeId": network_volume_id,
                    "gpuTypeIds": [gpu],
                    "gpuCount": settings.sandbox_pod_gpu_count,
                    # REST v1 PodCreateInput rejects unknown keys (HTTP 400 "Extra
                    # input keys"). startJupyter/startSsh are GraphQL-only fields; Jupyter
                    # and SSH exposure come from the template's ports/env.
                },
            )
        except RuntimeError as exc:
            kind = _classify_error(exc)
            attempts.append({**entry, "ok": False, "error": _short_error(exc)})
            _log_attempt(settings, attempts[-1])
            if kind == "config":
                error = ValueError(f"Sandbox Pod 생성 설정/권한 오류 ({gpu}): {_short_error(exc)}")
                error.attempts = list(attempts)  # type: ignore[attr-defined]
                raise error from exc
            continue
        if not isinstance(response, dict):
            response = {}
        attempts.append({**entry, "ok": True, "podId": str(response.get("id") or "")})
        _log_attempt(settings, attempts[-1])
        if gpu != settings.sandbox_pod_gpu_type_id.strip():
            _log_event(settings, "fallback", pod_id=str(response.get("id") or ""), gpu_type_id=gpu)
        return response, gpu
    raise SandboxPodUnavailable(_unavailable_message(tried), attempts)


def _create_message(settings: Settings, gpu: str, attempts: list[dict], target: dict | None) -> str:
    primary = settings.sandbox_pod_gpu_type_id.strip()
    if gpu == primary and target is None:
        return "새 Sandbox Pod 생성을 요청했습니다. GPU 할당과 HTTP 서비스 준비까지 잠시 기다린 뒤 Refresh Status를 누르세요."
    if gpu == primary:
        return (
            f"정지된 파드를 다시 시작하지 못해 {_gpu_label(gpu)}로 새 Sandbox Pod를 생성했습니다. "
            "HTTP 서비스 준비까지 잠시 기다린 뒤 Refresh Status를 누르세요."
        )
    return (
        f"1순위 GPU({_gpu_label(primary)}) 재고가 없어 {_gpu_label(gpu)}로 새 Sandbox Pod를 생성했습니다. "
        "HTTP 서비스 준비까지 잠시 기다린 뒤 Refresh Status를 누르세요."
    )


def _unavailable_message(tried: list[str]) -> str:
    labels = "·".join(_gpu_label(gpu) for gpu in tried) or "지정된 GPU"
    return f"EU-RO-1에 기동 가능한 파드·GPU가 없습니다. ({labels} 모두 재고 없음)"


# ---------------------------------------------------------------------------
# Error classification / GPU candidate selection (pure helpers)
# ---------------------------------------------------------------------------


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, SandboxPodApiError):
        if exc.status is None:
            return "transient"
        if exc.status == 404:
            return "not_found"
        if exc.status in {400, 401, 403, 422}:
            return "config"
        body = exc.detail.lower()
        if any(marker in body for marker in _NO_CAPACITY_MARKERS) or exc.status in {500, 503}:
            return "no_capacity"
        return "unknown"
    if "연결 실패" in str(exc):
        return "transient"
    return "unknown"


def _gpu_candidates(settings: Settings, vram_by_gpu: dict[str, float] | None) -> list[tuple[str, str | None]]:
    primary = settings.sandbox_pod_gpu_type_id.strip()
    ordered: list[str] = []
    for gpu in [primary, *settings.sandbox_pod_gpu_fallback_type_ids]:
        gpu = gpu.strip()
        if gpu and gpu not in ordered:
            ordered.append(gpu)
    result: list[tuple[str, str | None]] = []
    for gpu in ordered:
        reason = None
        if (
            gpu != primary
            and vram_by_gpu is not None
            and gpu in vram_by_gpu
            and float(vram_by_gpu[gpu]) < settings.sandbox_pod_min_vram_gb
        ):
            reason = "vram"
        result.append((gpu, reason))
    return result


_CATALOG_TTL_SECONDS = 600
_catalog_cache: dict[str, object] = {"at": 0.0, "value": None}


def _fetch_gpu_catalog(settings: Settings) -> dict[str, dict] | None:
    """Best-effort GPU catalog → {gpuTypeId: {memoryInGb, securePrice, displayName}}.

    REST v1 has no catalog endpoint, so this reads REST v2 ``GET /catalog/gpus``
    (same host and API key as the v1 Pod control calls). Cached for a few
    minutes; ``None`` when unavailable — callers then skip VRAM filtering and
    fall back to local labels.
    """
    now = time.monotonic()
    cached = _catalog_cache.get("value")
    if cached is not None and now - float(_catalog_cache.get("at") or 0.0) < _CATALOG_TTL_SECONDS:
        return cached  # type: ignore[return-value]
    try:
        response = _request(settings, "GET", "/catalog/gpus", base_url=settings.sandbox_pod_rest_v2_url)
    except Exception:  # noqa: BLE001 - the catalog is optional; never break status/start on it
        return None
    items = response.get("gpus") if isinstance(response, dict) else response
    if not isinstance(items, list):
        return None
    catalog: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        gpu_id = str(item.get("id") or "").strip()
        if not gpu_id:
            continue
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        catalog[gpu_id] = {
            "memoryInGb": _number_or_none(item.get("memory")),
            "securePrice": _number_or_none(price.get("secure")),
            "displayName": str(item.get("name") or "").strip() or None,
        }
    if catalog:
        _catalog_cache["at"] = now
        _catalog_cache["value"] = catalog
    return catalog or None


_GPU_LABEL_RULES = (
    ("NVIDIA GeForce ", ""),
    ("NVIDIA ", ""),
    (" Blackwell Workstation Edition", " WK"),
    (" Blackwell Server Edition", " Server"),
    (" Blackwell", ""),
)


def _pod_display(pod: dict | None) -> str:
    """Human-readable Pod reference: RunPod name first, ID as a suffix (spec §2.1 name rule)."""
    if not pod:
        return "Sandbox Pod"
    pod_id = str(pod.get("id") or pod.get("podId") or "").strip()
    name = str(pod.get("name") or pod.get("podName") or "").strip()
    if name and pod_id:
        return f"{name} ({pod_id})"
    return name or pod_id or "Sandbox Pod"


def _pod_name_for_gpu(prefix: str, gpu_type_id: str, catalog: dict[str, dict] | None) -> str:
    """`<RUNPOD_SANDBOX_DEPLOY_NAME>_<GPU displayName>` — the operator naming rule (spec §2.1).

    The RunPod catalog displayName is preferred; without a catalog the local
    short label (same convention: "RTX 5090", "RTX PRO 6000 WK") is used.
    """
    display = None
    if catalog and gpu_type_id in catalog:
        display = catalog[gpu_type_id].get("displayName")
    return f"{prefix}_{display or _gpu_label(gpu_type_id)}"


def _gpu_label(gpu_type_id: str | None) -> str:
    label = str(gpu_type_id or "").strip()
    if not label:
        return "GPU"
    for old, new in _GPU_LABEL_RULES:
        label = label.replace(old, new)
    return label


def _short_error(exc: Exception) -> str:
    if isinstance(exc, SandboxPodApiError):
        detail = exc.detail.strip()
        try:
            parsed = json.loads(detail) if detail else {}
            if isinstance(parsed, dict) and parsed.get("error"):
                detail = str(parsed["error"])
        except ValueError:
            pass
        prefix = f"HTTP {exc.status}: " if exc.status is not None else "연결 실패: "
        return (prefix + detail)[:_ERROR_DETAIL_LIMIT]
    return str(exc)[:_ERROR_DETAIL_LIMIT]


def _now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Observability hooks (never block Pod control)
# ---------------------------------------------------------------------------


def _log_attempt(settings: Settings, entry: dict) -> None:
    try:
        from backend.app.core import observability

        observability.observe_sandbox_pod_attempt(
            stage=str(entry.get("stage") or ""),
            pod_id=entry.get("podId"),
            gpu_type_id=entry.get("gpuTypeId"),
            ok=bool(entry.get("ok")),
            error=entry.get("error"),
            skipped=entry.get("skipped"),
        )
    except Exception:  # noqa: BLE001
        return


def _log_event(settings: Settings, kind: str, *, pod_id: str | None, gpu_type_id: str | None) -> None:
    try:
        from backend.app.core import observability

        observability.observe_sandbox_pod_event(kind=kind, pod_id=pod_id, gpu_type_id=gpu_type_id)
    except Exception:  # noqa: BLE001
        return


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------


def _build_status(
    settings: Settings,
    pods: list[dict],
    prefs: SandboxPodPrefs,
    *,
    attempts: list[dict],
    switched: bool = False,
    created_by: str | None = None,
    resolved_by: str | None = None,
    include_live: bool = True,
) -> dict:
    conflict_ids = _conflict_pod_ids(pods)
    active = _active_pod(pods)
    display = _display_pod(pods, prefs.selected_pod_id)
    volume_id = settings.sandbox_pod_network_volume_id.strip()
    default_resolved_by = "network-volume" if volume_id else "legacy-selector"
    # 2026-09-13 성능: 카탈로그·RUNNING 파드의 8188 프로브·표시 파드의 v2 runtime 지표를
    # 한 번에 병렬 조회하고, 아래 _present_pod/_pod_summary에는 결과를 전달해
    # 같은 파드에 프로브가 두 번 나가지 않게 한다.
    live = _collect_live_info(settings, pods, display, include_live=include_live)
    catalog = live["catalog"]
    if display is not None:
        status = _present_pod(
            settings,
            display,
            resolved_by or default_resolved_by,
            runtime_status=live["runtime_status"].get(str(display.get("id") or "")),
            system_status=live["system_status"],
        )
    else:
        status = {
            "configured": True,
            "podId": None,
            "podName": None,
            "resolvedBy": resolved_by or default_resolved_by,
            "desiredStatus": "NONE",
            "runtimeStatus": "NONE",
            "httpServices": [],
            "systemStatus": {"available": False, "mode": "configuration", "gpus": []},
            "message": "Sandbox 볼륨에 연결된 Pod가 없습니다. Start를 누르면 새 Pod를 생성합니다.",
            **timestamp_fields("checkedAt", utc_now(), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="ecs-application"),
        }
    selected_missing = bool(prefs.selected_pod_id) and not any(str(pod.get("id")) == prefs.selected_pod_id for pod in pods)
    status.update(
        {
            "pods": [_pod_summary(settings, pod, catalog, runtime_status=live["runtime_status"].get(str(pod.get("id") or ""))) for pod in pods],
            "selectedPodId": prefs.selected_pod_id,
            "selectedPodMissing": selected_missing,
            "activePodId": str(active.get("id")) if active is not None else None,
            "activePodName": (active.get("name") or None) if active is not None else None,
            "conflict": bool(conflict_ids),
            "conflictPodIds": conflict_ids,
            "settings": {
                "selectedPodId": prefs.selected_pod_id,
                "autoSwitchOnStartFailure": prefs.auto_switch_on_start_failure,
                "podPriority": list(prefs.pod_priority),
                "replaceSameGpuPods": prefs.replace_same_gpu_pods,
            },
            "attempts": attempts,
            "switched": switched,
            "createdBy": created_by,
        }
    )
    if conflict_ids:
        status["message"] = (
            f"실행 중인 Sandbox Pod가 {len(conflict_ids)}개입니다. 볼륨 손상 위험이 있으니 하나만 남기고 정지하세요."
        )
    elif selected_missing:
        status["message"] = (
            f"선택했던 파드 {prefs.selected_pod_id}를 볼륨에서 찾을 수 없습니다(migration으로 ID가 바뀌었을 수 있음). "
            "목록에서 같은 이름의 파드를 다시 선택하세요."
        )
    return status


_PENDING_SYSTEM_STATUS = {"available": False, "mode": "pending", "gpus": [], "message": "RunPod 런타임 지표를 조회 중입니다."}


def _collect_live_info(settings: Settings, pods: list[dict], display: dict | None, *, include_live: bool = True) -> dict:
    """Fetch catalog, per-RUNNING-pod 8188 probe and the display Pod's v2 runtime metrics concurrently.

    With ``include_live=False`` only the (cached) catalog is fetched; runtime status
    falls back to the desired status and system status is marked ``pending``."""
    result: dict = {"catalog": None, "runtime_status": {}, "system_status": None}
    if not pods:
        return result
    if not include_live:
        result["catalog"] = _fetch_gpu_catalog(settings)
        result["runtime_status"] = {str(pod.get("id") or ""): (_status_of(pod) or "UNKNOWN") for pod in pods}
        result["system_status"] = dict(_PENDING_SYSTEM_STATUS) if display is not None else None
        return result
    tasks: dict[str, object] = {"catalog": lambda: _fetch_gpu_catalog(settings)}
    for pod in pods:
        pod_id = str(pod.get("id") or "").strip()
        if _status_of(pod) == "RUNNING" and pod_id:
            services = _http_services(pod_id, pod.get("ports") or [], jupyter_auth_required=_jupyter_auth_required(pod))
            tasks[f"probe:{pod_id}"] = (lambda pid=pod_id, svc=services: _runtime_status(settings, pid, "RUNNING", svc))
    if display is not None:
        display_id = str(display.get("id") or settings.sandbox_pod_id).strip()
        tasks["metrics"] = lambda: _runtime_metrics(settings, display_id, display)
    with ThreadPoolExecutor(max_workers=min(8, len(tasks))) as pool:
        futures = {name: pool.submit(fn) for name, fn in tasks.items()}
        for name, future in futures.items():
            value = future.result()
            if name == "catalog":
                result["catalog"] = value
            elif name == "metrics":
                result["system_status"] = value
            else:
                result["runtime_status"][name.split(":", 1)[1]] = value
    return result


def _pod_summary(
    settings: Settings,
    pod: dict,
    catalog: dict[str, dict] | None,
    *,
    runtime_status: str | None = None,
) -> dict:
    pod_id = str(pod.get("id") or "").strip()
    status = _status_of(pod) or "UNKNOWN"
    services = _http_services(pod_id, pod.get("ports") or [], jupyter_auth_required=_jupyter_auth_required(pod))
    gpu = _gpu_type_name(pod)
    vram = None
    if catalog and gpu and gpu in catalog:
        vram = catalog[gpu].get("memoryInGb")
    if vram is None:
        vram = _number_or_none(pod.get("gpuMemoryInGb"))
    if runtime_status is None:
        runtime_status = _runtime_status(settings, pod_id, status, services) if status == "RUNNING" else status
    return {
        "podId": pod_id,
        "name": pod.get("name") or None,
        "gpuTypeId": gpu,
        "gpuLabel": _gpu_display_name(pod) or _gpu_label(gpu),
        "gpuTier": _gpu_tier(settings, gpu),
        "vramGb": vram,
        "ramGb": _number_or_none(pod.get("memoryInGb")),
        "pricePerHr": _price_of(pod),
        "desiredStatus": status,
        "runtimeStatus": runtime_status,
        **timestamp_fields(
            "lastStartedAt",
            pod.get("lastStartedAt"),
            naive_timezone=UTC_TIMEZONE,
            source_timezone="UTC",
            source="runpod-sandbox",
        ),
        "httpServices": services,
    }


def _gpu_tier(settings: Settings, gpu: str | None) -> str:
    if not gpu:
        return "unknown"
    return "primary" if gpu == settings.sandbox_pod_gpu_type_id.strip() else "fallback"


def _jupyter_auth_required(pod: dict) -> bool:
    env = pod.get("env")
    if isinstance(env, dict):
        return "JUPYTER_PASSWORD" in env
    if isinstance(env, list):
        for item in env:
            if isinstance(item, dict) and str(item.get("key") or item.get("name") or "") == "JUPYTER_PASSWORD":
                return True
    return False


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
    if template_id and not volume_id:
        # The template ID is a *creation* spec, not an identity: Pods created
        # through the console, REST v2, or Pod migration may carry no
        # templateId at all. When a Network Volume selector is configured it
        # is the sole identity filter; the template is only used to build the
        # replacement Pod in _deploy_sandbox_pod.
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
        ("template-id", template_id if not volume_id else ""),
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


def _request(settings: Settings, method: str, path: str, body: dict | None = None, *, base_url: str | None = None) -> dict:
    url = f"{(base_url or settings.sandbox_pod_rest_url).rstrip('/')}{path}"
    api_key = settings.sandbox_pod_api_key.strip()
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": RUNPOD_HTTP_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.sandbox_pod_timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SandboxPodApiError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise SandboxPodApiError(None, str(exc.reason)) from exc
    except (TimeoutError, OSError) as exc:
        raise SandboxPodApiError(None, str(exc)) from exc
    if not payload.strip():
        return {}
    try:
        return json.loads(payload)
    except ValueError as exc:
        raise SandboxPodApiError(None, f"non-JSON response from {url}: {payload[:120]!r}") from exc


def _readiness_message(services: list[dict], status: str, runtime_status: str) -> str:
    if not any(service["internalPort"] == 8188 for service in services):
        return "ComfyUI HTTP 8188 포트가 노출되지 않았습니다. RunPod Pod 설정을 확인하세요."
    if runtime_status == "READY":
        return "Sandbox Pod와 ComfyUI HTTP 8188 서비스가 준비되었습니다."
    if status == "RUNNING":
        return "Sandbox Pod는 실행 중이며 ComfyUI HTTP 8188 서비스 준비를 확인 중입니다. 잠시 후 Refresh Status를 누르세요."
    return "Sandbox Pod 상태를 조회했습니다."


def _present_pod(
    settings: Settings,
    pod: dict,
    resolved_by: str,
    *,
    runtime_status: str | None = None,
    system_status: dict | None = None,
) -> dict:
    pod_id = str(pod.get("id") or settings.sandbox_pod_id).strip()
    services = _http_services(pod_id, pod.get("ports") or [], jupyter_auth_required=_jupyter_auth_required(pod))
    status = str(pod.get("desiredStatus") or pod.get("status") or "UNKNOWN").upper()
    if runtime_status is None:
        runtime_status = _runtime_status(settings, pod_id, status, services)
    if system_status is None:
        system_status = _runtime_metrics(settings, pod_id, pod)
    message = _readiness_message(services, status, runtime_status)
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
        "gpuTypeId": _gpu_type_name(pod),
        "gpuTier": _gpu_tier(settings, _gpu_type_name(pod)),
        "message": message,
    }


def _http_services(pod_id: str, ports: list[object], *, jupyter_auth_required: bool = False) -> list[dict]:
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
        entry = {
            "internalPort": port,
            "url": f"https://{pod_id}-{port}.proxy.runpod.net",
            "label": service_labels[port],
        }
        if port == 8888 and jupyter_auth_required:
            entry["authRequired"] = True
        services.append(entry)
    # The readiness source is presented first; the other links are supplementary
    # access points and do not participate in the READY decision.
    display_order = {8188: 0, 8080: 1, 8888: 2}
    return sorted(services, key=lambda service: display_order[service["internalPort"]])


def _runtime_metrics(settings: Settings, pod_id: str, pod: dict) -> dict:
    """Return best-effort runtime metrics. A metrics outage must not block Pod control.

    Live utilization is not part of the REST v1 Pod object; it is read from
    REST v2 ``GET /pods/{id}`` (``runtime.uptime``, ``runtime.cpu.util``,
    ``runtime.memory.util``, ``runtime.gpus[].util/memoryUtil``), which is
    served by the same host and accepts the same API key.
    """
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
    try:
        response = _request(settings, "GET", f"/pods/{pod_id}", base_url=settings.sandbox_pod_rest_v2_url)
        runtime = response.get("runtime") if isinstance(response, dict) else None
        if not isinstance(runtime, dict):
            raise RuntimeError("Sandbox Pod runtime 정보가 아직 준비되지 않았습니다.")
        cpu = runtime.get("cpu") if isinstance(runtime.get("cpu"), dict) else {}
        memory = runtime.get("memory") if isinstance(runtime.get("memory"), dict) else {}
        gpus = runtime.get("gpus") if isinstance(runtime.get("gpus"), list) else []
        return {
            "available": True,
            "mode": "live",
            "uptimeSeconds": _number_or_none(runtime.get("uptime")),
            "cpuPercent": _number_or_none(cpu.get("util")),
            "memoryPercent": _number_or_none(memory.get("util")),
            "gpus": [
                {
                    "id": str(gpu.get("id") or f"GPU {index + 1}"),
                    "gpuUtilPercent": _number_or_none(gpu.get("util")),
                    "memoryUtilPercent": _number_or_none(gpu.get("memoryUtil")),
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
    """GPU type id from any RunPod Pod shape.

    REST v1 detail: ``gpu.id`` / ``machine.gpuTypeId`` / ``machine.gpuType.id``;
    create responses and older payloads: ``gpuTypeIds`` / ``gpuTypeId``.
    """
    values = pod.get("gpuTypeIds") or pod.get("gpuTypes") or []
    if isinstance(values, list) and values:
        return ", ".join(str(value) for value in values if value)
    value = pod.get("gpuTypeId")
    if value:
        return str(value)
    gpu = pod.get("gpu")
    if isinstance(gpu, dict) and gpu.get("id"):
        return str(gpu["id"])
    machine = pod.get("machine")
    if isinstance(machine, dict):
        if machine.get("gpuTypeId"):
            return str(machine["gpuTypeId"])
        gpu_type = machine.get("gpuType")
        if isinstance(gpu_type, dict) and gpu_type.get("id"):
            return str(gpu_type["id"])
    return None


def _gpu_display_name(pod: dict) -> str | None:
    """RunPod's short GPU display name (``gpu.displayName``), when the Pod payload carries it."""
    for holder in (pod.get("gpu"), (pod.get("machine") or {}).get("gpuType") if isinstance(pod.get("machine"), dict) else None):
        if isinstance(holder, dict) and holder.get("displayName"):
            return str(holder["displayName"]).strip()
    return None


def _runtime_metric_fallback_message(error: RuntimeError) -> str:
    message = str(error)
    if "HTTP 403" in message:
        return "실시간 CPU·메모리·GPU 사용률(REST v2 /pods/{id}) 조회 권한이 없는 API 키입니다. 현재 Pod 구성 및 저장소 정보만 표시합니다."
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


_PROBE_TIMEOUT_SECONDS = 2


def _runtime_status(settings: Settings, pod_id: str, desired_status: str, services: list[dict]) -> str:
    if desired_status != "RUNNING":
        return desired_status
    service = next((item for item in services if item["internalPort"] == 8188), None)
    if service is None:
        return "INITIALIZING"
    service_url = service["url"]
    request = urllib.request.Request(service_url, method="GET")
    try:
        # 2026-09-13: 초기화 중인 파드는 어차피 INITIALIZING이므로 프로브 대기 상한 5→2초
        with urllib.request.urlopen(request, timeout=min(settings.sandbox_pod_timeout, _PROBE_TIMEOUT_SECONDS)) as response:
            return "READY" if 200 <= response.status < 500 else "INITIALIZING"
    except urllib.error.HTTPError as exc:
        return "READY" if 200 <= exc.code < 500 else "INITIALIZING"
    except (urllib.error.URLError, TimeoutError):
        return "INITIALIZING"
