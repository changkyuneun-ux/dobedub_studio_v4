from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, has_permission, require_permission
from backend.app.db.models import BatchJob
from backend.app.db.session import get_db
from backend.app.services import batch_job_service, batch_zip_import_service, batch_zip_service

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


@router.post("/zip")
async def create_batch_job_from_zip(
    workflowId: str = Form(...),
    requestedFrames: int = Form(batch_job_service.DEFAULT_FRAMES),
    resolutionTier: str = Form("sd"),
    negativePrompt: str = Form(""),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    try:
        # Reject duplicate IDs before extracting the ZIP or registering assets.
        batch_id = batch_job_service.zip_batch_job_id(
            db,
            created_by=current_user.id,
            zip_file_name=file.filename or "upload.zip",
        )
        batch_job_service.ensure_batch_job_id_available(db, batch_id)
        imported = batch_zip_import_service.import_zip_bytes(
            await file.read(),
            zip_file_name=file.filename or "upload.zip",
            batch_job_id=batch_id,
            created_by=current_user.id,
        )
        return batch_job_service.create_batch_job(
            db,
            {
                "workflowId": workflowId,
                "requestedFrames": requestedFrames,
                "resolutionTier": resolutionTier,
                "negativePrompt": negativePrompt,
                "sourceDirName": imported.source_dir_name,
                "sourceZipFileName": imported.source_zip_file_name,
                "items": imported.items,
            },
            created_by=current_user.id,
        )
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


@router.get("/search")
def batch_job_candidates(
    query: str = Query(""),
    limit: int = Query(10),
    current_user: CurrentUser = Depends(require_permission("history:read")),
    db: Session = Depends(get_db),
):
    return batch_job_service.list_batch_job_candidates(
        db,
        created_by=_scope(current_user),
        query=query,
        limit=limit,
    )


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


@router.get("/{batch_job_id}")
def batch_job_detail(
    batch_job_id: str,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    batch_row = db.get(BatchJob, batch_job_id)
    if batch_row is None:
        raise HTTPException(status_code=404, detail="배치 작업을 찾을 수 없습니다.")
    scoped_user = _scope(current_user)
    if scoped_user and batch_row.created_by != scoped_user:
        raise HTTPException(status_code=403, detail="다른 작업자의 배치는 조회할 수 없습니다.")
    try:
        detail = batch_job_service.batch_job_detail(db, batch_job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return detail


@router.post("/{batch_job_id}/retry-failed")
def retry_failed_batch_items(
    batch_job_id: str,
    payload: dict | None = None,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
    db: Session = Depends(get_db),
):
    try:
        return batch_job_service.retry_failed_batch_items(
            db,
            batch_job_id,
            actor_id=current_user.id,
            can_manage=has_permission(current_user.permissions, "jobs:manage"),
            stage=str((payload or {}).get("stage") or "all"),
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{batch_job_id}/items/retry")
def retry_selected_batch_items(
    batch_job_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
    db: Session = Depends(get_db),
):
    try:
        return batch_job_service.retry_failed_batch_items(
            db,
            batch_job_id,
            actor_id=current_user.id,
            can_manage=has_permission(current_user.permissions, "jobs:manage"),
            stage=str(payload.get("stage") or "all"),
            draft_ids=[str(item) for item in payload.get("draftIds") or []],
            task_ids=[str(item) for item in payload.get("taskIds") or []],
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    batch_row = db.get(BatchJob, batch_job_id)
    if batch_row is None:
        raise HTTPException(status_code=404, detail="배치 작업을 찾을 수 없습니다.")
    return StreamingResponse(
        chunks,
        media_type="application/zip",
        headers={
            **batch_zip_service.ZIP_RESPONSE_HEADERS,
            "Content-Disposition": batch_zip_service.content_disposition_for_batch_zip(batch_row),
            "X-Batch-Zip-Skipped": str(skipped),
        },
    )
