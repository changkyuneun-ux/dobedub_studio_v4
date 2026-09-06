from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, has_permission, require_permission
from backend.app.db.session import get_db
from backend.app.services import batch_job_service, batch_zip_service

router = APIRouter(prefix="/batch-jobs", tags=["batch-jobs"])


def _require_batch_access(current_user: CurrentUser) -> None:
    if not has_permission(current_user.permissions, "jobs:run"):
        raise HTTPException(status_code=403, detail="배치 작업은 prompts:build와 jobs:run 권한이 모두 필요합니다.")


def _scope(current_user: CurrentUser) -> str | None:
    return None if has_permission(current_user.permissions, "jobs:manage") else current_user.id


@router.post("")
def create_batch_job(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    try:
        return batch_job_service.create_batch_job(db, payload, created_by=current_user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/active")
def active_batch_jobs(
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    return batch_job_service.list_active_batch_jobs(db, created_by=_scope(current_user))


@router.get("")
def batch_job_history(
    page: int = 1,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    workerId: str | None = None,
    status: str | None = None,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    return batch_job_service.list_batch_jobs(
        db,
        created_by=_scope(current_user),
        page=page,
        date_from=dateFrom,
        date_to=dateTo,
        worker_id=workerId,
        status=status,
    )


@router.get("/{batch_job_id}/download")
def download_batch_zip(
    batch_job_id: str,
    taskIds: list[str] | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    try:
        batch = batch_job_service.batch_job_payload(db, batch_job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scoped_user = _scope(current_user)
    if scoped_user and batch["createdBy"] != scoped_user:
        raise HTTPException(status_code=403, detail="다른 작업자의 배치는 내려받을 수 없습니다.")
    try:
        chunks, skipped = batch_zip_service.stream_batch_zip(batch_job_id, task_ids=taskIds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    batch_job_service.mark_batch_downloaded(db, batch_job_id)
    return StreamingResponse(
        chunks,
        media_type="application/zip",
        headers={
            **batch_zip_service.ZIP_RESPONSE_HEADERS,
            "Content-Disposition": f'attachment; filename="{batch_job_id}.zip"',
            "X-Batch-Zip-Skipped": str(skipped),
        },
    )
