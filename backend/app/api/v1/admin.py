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
    archive_admin_workflow,
    deactivate_admin_user,
    list_admin_users,
    list_admin_workflows,
    list_workflow_revisions,
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
from backend.app.services.grok_instruction_service import (
    copy_instruction_documents,
    delete_instruction_document,
    import_markdown_document,
    list_instruction_documents,
    list_instruction_source_workflows,
    save_instruction_document,
)
router = APIRouter(prefix="/admin", tags=["admin"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/grok-instructions")
def grok_instructions(workflowId: str, _: CurrentUser = Depends(require_permission("prompt-catalog:read"))):
    try:
        return list_instruction_documents(workflowId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Grok instruction load failed: {exc}") from exc


@router.get("/grok-instructions/sources")
def grok_instruction_sources(_: CurrentUser = Depends(require_permission("prompt-catalog:read"))):
    try:
        return {"workflowIds": list_instruction_source_workflows()}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Grok instruction source load failed: {exc}") from exc


@router.post("/grok-instructions")
def create_grok_instruction(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        result = save_instruction_document(payload, document_id=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit_log(db, actor_id=current_user.id, action="grok_instruction.create", target_type="grok_instruction", target_id=str((result.get("item") or {}).get("id") or ""), after=result.get("item"), ip=_client_ip(request))
    return result


@router.put("/grok-instructions/{document_id}")
def update_grok_instruction(document_id: str, payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    workflow_id = str(payload.get("workflowId") or "").strip()
    try:
        existing = next((item for item in list_instruction_documents(workflow_id)["items"] if item["id"] == document_id), None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    before = existing
    try:
        result = save_instruction_document(payload, document_id=document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit_log(db, actor_id=current_user.id, action="grok_instruction.update", target_type="grok_instruction", target_id=document_id, before=before, after=result.get("item"), ip=_client_ip(request))
    return result


@router.delete("/grok-instructions/{document_id}")
def delete_grok_instruction(document_id: str, workflowId: str, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        existing = next((item for item in list_instruction_documents(workflowId)["items"] if item["id"] == document_id), None)
        result = delete_instruction_document(workflowId, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit_log(db, actor_id=current_user.id, action="grok_instruction.delete", target_type="grok_instruction", target_id=document_id, before=existing, ip=_client_ip(request))
    return result


@router.post("/grok-instructions/import-markdown")
def import_grok_instruction_markdown(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        result = import_markdown_document(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Markdown import failed: {exc}") from exc
    item = result.get("item") or {}
    record_audit_log(db, actor_id=current_user.id, action="grok_instruction.import_markdown", target_type="grok_instruction", target_id=str(item.get("id") or ""), after=item, ip=_client_ip(request))
    return result


@router.post("/grok-instructions/copy")
def copy_grok_instruction_documents(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        result = copy_instruction_documents(
            str(payload.get("sourceWorkflowId") or ""),
            str(payload.get("targetWorkflowId") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit_log(db, actor_id=current_user.id, action="grok_instruction.copy", target_type="grok_instruction_set", target_id=str(payload.get("targetWorkflowId") or ""), after=result.get("instructionSet"), ip=_client_ip(request))
    return result


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
def workflows(_: CurrentUser = Depends(require_permission("workflows:read")), db: Session = Depends(get_db)):
    try:
        return list_admin_workflows(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows")
def register_workflow(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("workflows:write")),
    db: Session = Depends(get_db),
):
    try:
        return register_admin_workflow(db, payload, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/activate")
def activate_workflow(
    workflow_id: str,
    revisionId: int | None = None,
    current_user: CurrentUser = Depends(require_permission("workflows:activate")),
    db: Session = Depends(get_db),
):
    try:
        return set_admin_workflow_active(db, workflow_id, True, current_user.id, revisionId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/deactivate")
def deactivate_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(require_permission("workflows:activate")),
    db: Session = Depends(get_db),
):
    try:
        return set_admin_workflow_active(db, workflow_id, False, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/revisions")
def workflow_revisions(
    workflow_id: str,
    _: CurrentUser = Depends(require_permission("workflows:read")),
    db: Session = Depends(get_db),
):
    try:
        return list_workflow_revisions(db, workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/archive")
def archive_workflow(
    workflow_id: str,
    current_user: CurrentUser = Depends(require_permission("workflows:write")),
    db: Session = Depends(get_db),
):
    try:
        return archive_admin_workflow(db, workflow_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
