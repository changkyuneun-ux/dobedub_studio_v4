from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, normalize_role, require_permission
from backend.app.db.models import Role, User
from backend.app.db.session import get_db
from backend.app.services.admin_service import (
    admin_user_payload,
    deactivate_admin_user,
    list_admin_users,
    list_admin_workflows,
    list_permission_governance,
    register_admin_workflow,
    reset_admin_user_password,
    set_admin_workflow_active,
    upsert_admin_user,
)
from backend.app.services.audit_log_service import list_audit_logs, record_audit_log
from backend.app.services.permission_service import update_role_permission_codes
from backend.app.services.task_policy_service import (
    task_execution_policy_payload,
    update_task_execution_policy,
)
router = APIRouter(prefix="/admin", tags=["admin"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/users")
def users(_: CurrentUser = Depends(require_permission("users:read")), db: Session = Depends(get_db)):
    try:
        return list_admin_users(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"User list failed: {exc}") from exc


@router.get("/permissions")
def permissions(_: CurrentUser = Depends(require_permission("roles:read")), db: Session = Depends(get_db)):
    try:
        return list_permission_governance(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Permission governance load failed: {exc}") from exc


@router.get("/task-execution-policy")
def task_execution_policy(
    _: CurrentUser = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    try:
        return task_execution_policy_payload(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Task execution policy load failed: {exc}") from exc


@router.put("/task-execution-policy")
def update_task_policy(
    payload: dict,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("roles:write")),
    db: Session = Depends(get_db),
):
    before = task_execution_policy_payload(db)
    try:
        result = update_task_execution_policy(
            db,
            max_active_tasks_per_user=payload.get("maxActiveTasksPerUser"),
            max_active_tasks_total=payload.get("maxActiveTasksTotal"),
            updated_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Task execution policy save failed: {exc}") from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="task.execution_policy.update",
        target_type="task_execution_policy",
        target_id="1",
        before=before,
        after=result,
        ip=_client_ip(request),
    )
    return result


@router.put("/roles/{role_code}/permissions")
def update_role_permissions(
    role_code: str,
    payload: dict,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("roles:write")),
    db: Session = Depends(get_db),
):
    requested_codes = payload.get("permissionCodes") or payload.get("permissions") or []
    role = db.scalar(select(Role).where(Role.code == normalize_role(role_code)))
    before_codes = sorted({link.permission.code for link in role.permissions}) if role else []
    try:
        result = update_role_permission_codes(db, role_code, requested_codes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Role permission save failed: {exc}") from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="role.permissions.update",
        target_type="role",
        target_id=role_code,
        before={"permissionCodes": before_codes},
        after={"permissionCodes": sorted(set(requested_codes))},
        ip=_client_ip(request),
    )
    return result


@router.post("/users")
def create_user(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    try:
        result = upsert_admin_user(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"User save failed: {exc}") from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="user.create",
        target_type="user",
        target_id=str((result.get("user") or {}).get("id") or payload.get("id") or ""),
        before=None,
        after=result.get("user"),
        ip=_client_ip(request),
    )
    return result


@router.put("/users/{user_id}")
def update_user(user_id: str, payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    existing = db.get(User, user_id)
    before = admin_user_payload(db, existing) if existing else None
    try:
        result = upsert_admin_user(db, payload, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"User save failed: {exc}") from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="user.update",
        target_type="user",
        target_id=user_id,
        before=before,
        after=result.get("user"),
        ip=_client_ip(request),
    )
    return result


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: str, request: Request, current_user: CurrentUser = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    existing = db.get(User, user_id)
    before = {"isActive": bool(existing.is_active)} if existing else None
    try:
        result = deactivate_admin_user(db, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"User deactivate failed: {exc}") from exc
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="user.deactivate",
        target_type="user",
        target_id=user_id,
        before=before,
        after={"isActive": False},
        ip=_client_ip(request),
    )
    return result


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    try:
        result = reset_admin_user_password(db, user_id, str(payload.get("password") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Password reset failed: {exc}") from exc
    # 비밀번호 값 자체는 before/after 어디에도 기록하지 않는다 - "재설정됨" 표시만 남긴다.
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="user.password_reset",
        target_type="user",
        target_id=user_id,
        before=None,
        after={"passwordReset": True},
        ip=_client_ip(request),
    )
    return result


@router.get("/audit-logs")
def audit_logs(
    page: int = 1,
    pageSize: int = 20,
    action: str | None = None,
    targetType: str | None = None,
    targetId: str | None = None,
    actorId: str | None = None,
    _: CurrentUser = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    try:
        return list_audit_logs(
            db,
            page,
            pageSize,
            action=action,
            target_type=targetType,
            target_id=targetId,
            actor_id=actorId,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Audit log query failed: {exc}") from exc


@router.get("/workflows")
def workflows(_: CurrentUser = Depends(require_permission("workflows:read"))):
    try:
        return list_admin_workflows()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows")
def register_workflow(payload: dict, _: CurrentUser = Depends(require_permission("workflows:write"))):
    try:
        return register_admin_workflow(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/activate")
def activate_workflow(workflow_id: str, _: CurrentUser = Depends(require_permission("workflows:activate"))):
    try:
        return set_admin_workflow_active(workflow_id, True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/deactivate")
def deactivate_workflow(workflow_id: str, _: CurrentUser = Depends(require_permission("workflows:activate"))):
    try:
        return set_admin_workflow_active(workflow_id, False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
