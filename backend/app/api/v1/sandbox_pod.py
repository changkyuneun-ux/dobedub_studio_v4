from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.security import CurrentUser, require_permission
from backend.app.db.session import get_db
from backend.app.services.audit_log_service import record_audit_log
from backend.app.services.sandbox_pod_service import (
    SandboxPodConflict,
    SandboxPodUnavailable,
    sandbox_pod_live,
    sandbox_pod_status,
    start_sandbox_pod,
    stop_sandbox_pod,
    terminate_sandbox_pod,
)
from backend.app.services.sandbox_pod_settings_service import (
    sandbox_pod_settings_payload,
    select_sandbox_pod,
    update_sandbox_pod_settings,
)


router = APIRouter(prefix="/admin/sandbox-pod", tags=["admin"])
LOGGER = logging.getLogger("dobedub.sandbox_pod")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _pod_id_from(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("podId")
    return str(value).strip() or None if value is not None else None


def _last_pod_id(attempts: list[dict]) -> str:
    for attempt in reversed(attempts):
        if attempt.get("podId"):
            return str(attempt["podId"])
    return ""


@router.get("")
def get_sandbox_pod(
    live: bool = Query(default=True, description="false면 8188 프로브·runtime 지표를 생략(2단계 로딩 1단계)"),
    _: CurrentUser = Depends(require_permission("sandbox:read")),
    db: Session = Depends(get_db),
):
    try:
        return sandbox_pod_status(get_settings(), db, include_live=live)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface the cause to the admin UI instead of a bare 500
        LOGGER.exception("sandbox_pod.status failed")
        raise HTTPException(status_code=500, detail=f"Sandbox Pod 상태 처리 오류: {type(exc).__name__}: {exc}") from exc


@router.get("/live")
def get_sandbox_pod_live(
    _: CurrentUser = Depends(require_permission("sandbox:read")),
    db: Session = Depends(get_db),
):
    """2단계 로딩 2단계: 표시 파드의 준비 상태(8188)·runtime 지표와 파드별 runtimeStatus."""
    try:
        return sandbox_pod_live(get_settings(), db)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("sandbox_pod.live failed")
        raise HTTPException(status_code=500, detail=f"Sandbox Pod LIVE 지표 처리 오류: {type(exc).__name__}: {exc}") from exc


@router.post("/select")
def select_pod(
    request: Request,
    payload: dict = Body(default=None),
    current_user: CurrentUser = Depends(require_permission("sandbox:control")),
    db: Session = Depends(get_db),
):
    pod_id = _pod_id_from(payload)
    if not pod_id:
        raise HTTPException(status_code=400, detail="podId가 필요합니다.")
    before = sandbox_pod_settings_payload(db)
    after = select_sandbox_pod(db, pod_id=pod_id, updated_by=current_user.id)
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="sandbox_pod.select",
        target_type="sandbox_pod",
        target_id=pod_id,
        before={"selectedPodId": before.get("selectedPodId")},
        after={"selectedPodId": after.get("selectedPodId")},
        ip=_client_ip(request),
    )
    try:
        return sandbox_pod_status(get_settings(), db)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/start")
def start_pod(
    request: Request,
    payload: dict = Body(default=None),
    current_user: CurrentUser = Depends(require_permission("sandbox:control")),
    db: Session = Depends(get_db),
):
    pod_id = _pod_id_from(payload)
    try:
        result = start_sandbox_pod(get_settings(), db, pod_id, actor_id=current_user.id)
    except ValueError as exc:
        # Configuration / permission errors (RunPod 400·401·403·422) stop the
        # staged start immediately; still leave an audit trail with attempts.
        _record_start_failed(db, request, current_user, getattr(exc, "attempts", []), str(exc), status=400)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SandboxPodConflict as exc:
        _record_start_failed(db, request, current_user, exc.attempts, str(exc), status=409)
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "attempts": exc.attempts, "runningPodIds": exc.running_pod_ids},
        ) from exc
    except SandboxPodUnavailable as exc:
        _record_start_failed(db, request, current_user, exc.attempts, str(exc), status=503)
        raise HTTPException(
            status_code=503,
            detail={"message": str(exc), "attempts": exc.attempts, "retryAfterSeconds": exc.retry_after_seconds},
        ) from exc
    except RuntimeError as exc:
        _record_start_failed(db, request, current_user, [], str(exc), status=502)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="sandbox_pod.start",
        target_type="sandbox_pod",
        target_id=str(result.get("activePodId") or result.get("podId") or ""),
        before=None,
        after={
            "desiredStatus": result.get("desiredStatus"),
            "runtimeStatus": result.get("runtimeStatus"),
            "requestedPodId": pod_id,
            "activePodId": result.get("activePodId"),
            "activePodName": result.get("activePodName"),
            "gpuTypeId": result.get("gpuTypeId"),
            "gpuTier": result.get("gpuTier"),
            "switched": result.get("switched"),
            "createdBy": result.get("createdBy"),
            "attempts": result.get("attempts", []),
        },
        ip=_client_ip(request),
    )
    return result


def _record_start_failed(db: Session, request: Request, current_user: CurrentUser, attempts: list[dict], error: str, *, status: int) -> None:
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="sandbox_pod.start_failed",
        target_type="sandbox_pod",
        target_id=_last_pod_id(attempts),
        before=None,
        after={"attempts": attempts, "error": error, "status": status},
        ip=_client_ip(request),
    )


@router.post("/stop")
def stop_pod(
    request: Request,
    payload: dict = Body(default=None),
    current_user: CurrentUser = Depends(require_permission("sandbox:control")),
    db: Session = Depends(get_db),
):
    pod_id = _pod_id_from(payload)
    try:
        result = stop_sandbox_pod(get_settings(), db, pod_id, actor_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="sandbox_pod.stop",
        target_type="sandbox_pod",
        target_id=str(result.get("stoppedPodId") or result.get("podId") or ""),
        before=None,
        after={
            "desiredStatus": result.get("desiredStatus"),
            "runtimeStatus": result.get("runtimeStatus"),
            "stoppedPodId": result.get("stoppedPodId"),
            "stoppedPodName": next((a.get("podName") for a in result.get("attempts", []) if a.get("stage") == "stop"), None),
        },
        ip=_client_ip(request),
    )
    return result


@router.post("/terminate")
def terminate_pod(
    request: Request,
    payload: dict = Body(default=None),
    current_user: CurrentUser = Depends(require_permission("sandbox:control")),
    db: Session = Depends(get_db),
):
    pod_id = _pod_id_from(payload)
    if not pod_id:
        raise HTTPException(status_code=400, detail="podId가 필요합니다.")
    try:
        result = terminate_sandbox_pod(get_settings(), db, pod_id, actor_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="sandbox_pod.terminate",
        target_type="sandbox_pod",
        target_id=pod_id,
        before={"podName": result.get("terminatedPodName")},
        after={"attempts": result.get("attempts", []), "selectedPodId": result.get("selectedPodId")},
        ip=_client_ip(request),
    )
    return result


@router.put("/settings")
def update_settings(
    request: Request,
    payload: dict = Body(default=None),
    current_user: CurrentUser = Depends(require_permission("sandbox:control")),
    db: Session = Depends(get_db),
):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="설정 본문이 필요합니다.")
    before = sandbox_pod_settings_payload(db)
    try:
        after = update_sandbox_pod_settings(
            db,
            auto_switch_on_start_failure=payload.get("autoSwitchOnStartFailure", before["autoSwitchOnStartFailure"]),
            pod_priority=payload.get("podPriority", before["podPriority"]),
            replace_same_gpu_pods=payload.get("replaceSameGpuPods", before.get("replaceSameGpuPods", True)),
            updated_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="sandbox_pod.settings_update",
        target_type="sandbox_pod_settings",
        target_id="1",
        before={"autoSwitchOnStartFailure": before["autoSwitchOnStartFailure"], "podPriority": before["podPriority"], "replaceSameGpuPods": before.get("replaceSameGpuPods")},
        after={"autoSwitchOnStartFailure": after["autoSwitchOnStartFailure"], "podPriority": after["podPriority"], "replaceSameGpuPods": after.get("replaceSameGpuPods")},
        ip=_client_ip(request),
    )
    return after
