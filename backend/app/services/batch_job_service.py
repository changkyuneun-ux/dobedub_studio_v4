"""Folder-scoped batch orchestration over the existing prompt and RunPod pipelines.

A batch job owns nothing that the existing pipelines already own. It records the
user's folder-level intent, links the prompt and RunPod batches it spawned, and
keeps denormalized counters so the dashboards never join across three tables.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import SEOUL_TIMEZONE, UTC_TIMEZONE, utc_now
from backend.app.db.models import (
    BATCH_JOB_COMPLETE,
    BATCH_JOB_INCOMPLETE,
    BatchJob,
    ImagePromptDraft,
    PromptGenerationBatch,
    User,
    WorkflowTask,
)
from backend.app.db.session import SessionLocal
from backend.app.services import prompt_batch_service, workflow_service

ALLOWED_FRAMES: frozenset[int] = frozenset({49, 81, 161})
DEFAULT_FRAMES = 81
DEFAULT_FPS = 16
PROMOTION_LIMIT_PER_CYCLE = 20
STALE_PROMOTION_CLAIM_SECONDS = 300
PAGE_SIZE = 10
TERMINAL_DRAFT_STATES = frozenset({"READY", "FAILED", "MANUAL_REQUIRED"})
FAILED_DRAFT_STATES = frozenset({"FAILED", "MANUAL_REQUIRED"})
TERMINAL_TASK_STATES = frozenset({"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"})
SUCCESS_TASK_STATES = frozenset({"COMPLETED", "SUCCESS"})

# Last promotion error per batch job, for operator diagnosis. Deliberately
# in-memory: it is a transient monitor detail, not batch state.
_PROMOTION_FAILURES: dict[str, str] = {}


def resolve_duration_seconds(workflow_id: str, requested_frames: int) -> int:
    """Seconds of video for a frame count, using the workflow's own output fps.

    Falls back to DEFAULT_FPS when the workflow schema cannot be loaded or
    exposes no output_fps configControl (true for every workflow today).
    A missing/unreadable schema must never block batch creation.
    """
    fps = DEFAULT_FPS
    try:
        schema = workflow_service.get_workflow_schema(workflow_id)
    except Exception:
        schema = None
    if schema:
        for segment in schema.get("segments") or []:
            for control in segment.get("configControls") or []:
                if str(control.get("key")) == "output_fps":
                    candidate = control.get("default")
                    if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) and candidate > 0:
                        fps = int(candidate)
                    break
    return max(1, round(requested_frames / fps))


def _validated_frames(value: Any) -> int:
    try:
        frames = int(value)
    except (TypeError, ValueError):
        frames = DEFAULT_FRAMES
    if frames not in ALLOWED_FRAMES:
        allowed = ", ".join(str(item) for item in sorted(ALLOWED_FRAMES))
        raise ValueError(f"영상 길이(Length)는 {allowed} 중 하나여야 합니다.")
    return frames


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC_TIMEZONE)
    return value.astimezone(UTC_TIMEZONE)


def _worker_batch_token(db: Session, created_by: str) -> str:
    user = db.get(User, created_by) if created_by else None
    raw = str(user.name if user and user.name else created_by or "unknown").strip()
    compact = "_".join(raw.split())
    return compact or "unknown"


def _next_batch_job_id(db: Session, *, created_by: str, created_at: datetime) -> str:
    created_at_utc = _aware_utc(created_at)
    created_at_kst = created_at_utc.astimezone(SEOUL_TIMEZONE)
    date_token = created_at_kst.strftime("%y%m%d")
    day_start_kst = created_at_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_kst = day_start_kst + timedelta(days=1)
    day_start_utc = day_start_kst.astimezone(UTC_TIMEZONE).replace(tzinfo=None)
    day_end_utc = day_end_kst.astimezone(UTC_TIMEZONE).replace(tzinfo=None)
    existing_count = int(db.scalar(
        select(func.count())
        .select_from(BatchJob)
        .where(
            BatchJob.created_by == created_by,
            BatchJob.created_at >= day_start_utc,
            BatchJob.created_at < day_end_utc,
        )
    ) or 0)
    sequence = existing_count + 1
    suffix = f"_{date_token}_{sequence}"
    worker_token = _worker_batch_token(db, created_by)
    max_worker_length = max(1, 64 - len(suffix))
    return f"{worker_token[:max_worker_length]}{suffix}"


def create_batch_job(db: Session, payload: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    """Create the batch job and its prompt generation batch in one transaction."""
    workflow_id = str(payload.get("workflowId") or "").strip()
    if not workflow_id:
        raise ValueError("워크플로우를 먼저 선택하세요.")
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValueError("배치로 처리할 이미지를 하나 이상 선택하세요.")
    requested_frames = _validated_frames(payload.get("requestedFrames", DEFAULT_FRAMES))

    created_at = _aware_utc(utc_now()).replace(tzinfo=None)
    batch = BatchJob(
        id=_next_batch_job_id(db, created_by=created_by, created_at=created_at),
        workflow_id=workflow_id,
        status=BATCH_JOB_INCOMPLETE,
        source_dir_name=str(payload.get("sourceDirName") or "").strip()[:512] or None,
        requested_frames=requested_frames,
        duration_seconds=resolve_duration_seconds(workflow_id, requested_frames),
        total_images=len(items),
        prompt_waiting_count=len(items),
        created_by=created_by,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(batch)
    db.flush()

    _link_prompt_batch(
        db,
        workflow_id=workflow_id,
        items=items,
        requested_frames=requested_frames,
        created_by=created_by,
        batch_job_id=batch.id,
    )
    db.commit()
    return batch_job_payload(db, batch.id)


def _link_prompt_batch(
    db: Session,
    *,
    workflow_id: str,
    items: list[dict[str, Any]],
    requested_frames: int,
    created_by: str,
    batch_job_id: str,
) -> dict[str, Any]:
    """Create linked prompt rows while create_batch_job owns the transaction."""
    return prompt_batch_service.create_prompt_generation_batch(
        db,
        {
            "workflowId": workflow_id,
            "items": [
                {"assetId": str(item.get("assetId") or "").strip(), "slotIndex": index, "requestedFrames": requested_frames}
                for index, item in enumerate(items, start=1)
            ],
        },
        created_by=created_by,
        commit=False,
        batch_job_id=batch_job_id,
    )


def batch_job_payload(db: Session, batch_job_id: str) -> dict[str, Any]:
    batch = db.get(BatchJob, batch_job_id)
    if batch is None:
        raise ValueError("배치 작업을 찾을 수 없습니다.")
    return _batch_payload(db, batch)


def _batch_payload(db: Session, batch: BatchJob) -> dict[str, Any]:
    return {
        "id": batch.id,
        "workflowId": batch.workflow_id,
        "status": batch.status,
        "sourceDirName": batch.source_dir_name,
        "requestedFrames": batch.requested_frames,
        "durationSeconds": batch.duration_seconds,
        "totalImages": batch.total_images,
        "promptCompletedCount": batch.prompt_completed_count,
        "promptFailedCount": batch.prompt_failed_count,
        "videoRequestedCount": batch.video_requested_count,
        "videoCompletedCount": batch.video_completed_count,
        "videoFailedCount": batch.video_failed_count,
        "promptWaiting": batch.prompt_waiting_count,
        "promptGenerating": batch.prompt_generating_count,
        "runpodPendingSubmit": batch.runpod_pending_submit_count,
        "runpodQueued": batch.runpod_queued_count,
        "runpodInProgress": batch.runpod_in_progress_count,
        "failedCount": batch.prompt_failed_count + batch.video_failed_count,
        "lastDownloadedAt": batch.last_downloaded_at.isoformat() if batch.last_downloaded_at else None,
        "createdBy": batch.created_by,
        "createdByName": _user_name(db, batch.created_by),
        "createdAt": batch.created_at.isoformat() if batch.created_at else None,
        "updatedAt": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _user_name(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user.name if user else None


def promote_ready_batch_drafts() -> dict[str, Any]:
    """Turn newly-READY batch prompts into direct durable RunPod tasks.

    Folder-based batch work is intentionally tracked only in Task History. It
    must not create RunPod request-management batches or request items.
    """
    # Imported here: studio_api_service imports this module's siblings, and a
    # module-level import would create a cycle at application start.
    from backend.app.services import studio_api_service

    db = SessionLocal()
    try:
        claimed, claim_stamps = claim_batch_drafts_for_promotion(db, limit=PROMOTION_LIMIT_PER_CYCLE)
    finally:
        db.close()

    by_batch: dict[tuple[str, str], list[str]] = {}
    for batch_id, owner_id, draft_id in claimed:
        by_batch.setdefault((batch_id, owner_id), []).append(draft_id)

    promoted_batches: list[str] = []
    promoted = 0
    for (batch_id, owner_id), draft_ids in by_batch.items():
        recheck_db = SessionLocal()
        try:
            owned_ids = still_owns_claim(
                recheck_db,
                {draft_id: claim_stamps[draft_id] for draft_id in draft_ids if draft_id in claim_stamps},
            )
        finally:
            recheck_db.close()
        if not owned_ids:
            continue
        failed_claims: dict[str, datetime] = {}
        promoted_count = 0
        try:
            worker_user = _submitter_user(owner_id)
            for draft_id in owned_ids:
                try:
                    job_payload = studio_api_service.job_payload_from_prompt_draft(draft_id, user=worker_user)
                    job_payload["batchJobId"] = batch_id
                    studio_api_service.create_job(job_payload, user=worker_user)
                    promoted_count += 1
                except Exception as exc:  # noqa: BLE001 - keep later drafts retryable
                    _PROMOTION_FAILURES[batch_id] = str(exc)
                    if draft_id in claim_stamps:
                        failed_claims[draft_id] = claim_stamps[draft_id]
        except Exception as exc:  # noqa: BLE001 - one bad batch must not stop the rest
            _PROMOTION_FAILURES[batch_id] = str(exc)
            failed_claims = {draft_id: claim_stamps[draft_id] for draft_id in owned_ids if draft_id in claim_stamps}
        if failed_claims:
            release_db = SessionLocal()
            try:
                release_promotion_claim(release_db, failed_claims)
            finally:
                release_db.close()
        if promoted_count == 0:
            continue
        if not failed_claims:
            _PROMOTION_FAILURES.pop(batch_id, None)
        promoted += promoted_count
        promoted_batches.append(batch_id)

    return {"promoted": promoted, "batches": promoted_batches}


def _unpromoted_ready_drafts(limit: int, cutoff: datetime):
    already_promoted = (
        select(WorkflowTask.id)
        .where(
            WorkflowTask.prompt_draft_id == ImagePromptDraft.id,
            WorkflowTask.batch_job_id == ImagePromptDraft.batch_job_id,
            WorkflowTask.deleted_at.is_(None),
        )
        .exists()
    )
    return (
        select(ImagePromptDraft.id, ImagePromptDraft.batch_job_id, BatchJob.created_by)
        .join(BatchJob, BatchJob.id == ImagePromptDraft.batch_job_id)
        .where(
            BatchJob.status == BATCH_JOB_INCOMPLETE,
            ImagePromptDraft.status == "READY",
            or_(ImagePromptDraft.promotion_claimed_at.is_(None), ImagePromptDraft.promotion_claimed_at <= cutoff),
            ~already_promoted,
        )
        .order_by(ImagePromptDraft.created_at.asc(), ImagePromptDraft.id.asc())
        .limit(limit)
    )


def claim_batch_drafts_for_promotion(
    db: Session, *, limit: int
) -> tuple[list[tuple[str, str, str]], dict[str, datetime]]:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=STALE_PROMOTION_CLAIM_SECONDS)
    candidates = db.execute(_unpromoted_ready_drafts(limit, cutoff)).all()
    claimed: list[tuple[str, str, str]] = []
    for draft_id, batch_id, owner_id in candidates:
        if not owner_id:
            continue
        result = db.execute(
            ImagePromptDraft.__table__.update()
            .where(
                ImagePromptDraft.id == draft_id,
                or_(ImagePromptDraft.promotion_claimed_at.is_(None), ImagePromptDraft.promotion_claimed_at <= cutoff),
            )
            .values(promotion_claimed_at=now)
        )
        if result.rowcount:
            claimed.append((str(batch_id), str(owner_id), str(draft_id)))
    db.commit()
    claimed_ids = [draft_id for _batch, _owner, draft_id in claimed]
    if not claimed_ids:
        return claimed, {}
    stamps = {
        str(draft_id): claimed_at
        for draft_id, claimed_at in db.execute(
            select(ImagePromptDraft.id, ImagePromptDraft.promotion_claimed_at).where(ImagePromptDraft.id.in_(claimed_ids))
        ).all()
        if claimed_at is not None
    }
    return claimed, stamps


def still_owns_claim(db: Session, claims: dict[str, datetime]) -> list[str]:
    if not claims:
        return []
    owned: list[str] = []
    for draft_id, claimed_at in claims.items():
        row = db.scalar(
            select(ImagePromptDraft.id).where(
                ImagePromptDraft.id == draft_id,
                ImagePromptDraft.promotion_claimed_at == claimed_at,
            )
        )
        if row is not None:
            owned.append(str(row))
    return owned


def release_promotion_claim(db: Session, claims: dict[str, datetime]) -> None:
    if not claims:
        return
    for draft_id, claimed_at in claims.items():
        db.execute(
            ImagePromptDraft.__table__.update()
            .where(ImagePromptDraft.id == draft_id, ImagePromptDraft.promotion_claimed_at == claimed_at)
            .values(promotion_claimed_at=None)
        )
    db.commit()


def refresh_batch_job_counters() -> dict[str, Any]:
    db = SessionLocal()
    refreshed = 0
    completed = 0
    try:
        for batch in db.scalars(select(BatchJob).where(BatchJob.status == BATCH_JOB_INCOMPLETE)).all():
            counts = _counts_for(db, batch.id)
            batch.prompt_completed_count = counts["promptReady"]
            batch.prompt_failed_count = counts["promptFailed"]
            batch.video_requested_count = counts["videoRequested"]
            batch.video_completed_count = counts["videoCompleted"]
            batch.video_failed_count = counts["videoFailed"]
            batch.prompt_waiting_count = counts["promptWaiting"]
            batch.prompt_generating_count = counts["promptGenerating"]
            batch.runpod_pending_submit_count = counts["videoPendingSubmit"]
            batch.runpod_queued_count = counts["videoQueued"]
            batch.runpod_in_progress_count = counts["videoInProgress"]
            if _batch_is_settled(db, batch):
                batch.status = BATCH_JOB_COMPLETE
                completed += 1
            refreshed += 1
        db.commit()
    finally:
        db.close()
    return {"refreshed": refreshed, "completed": completed}


def _counts_for(db: Session, batch_job_id: str) -> dict[str, int]:
    draft_rows = db.execute(
        select(ImagePromptDraft.status, func.count())
        .where(ImagePromptDraft.batch_job_id == batch_job_id)
        .group_by(ImagePromptDraft.status)
    ).all()
    task_rows = db.execute(
        select(WorkflowTask.status, func.count())
        .where(WorkflowTask.batch_job_id == batch_job_id, WorkflowTask.deleted_at.is_(None))
        .group_by(WorkflowTask.status)
    ).all()
    drafts = {str(status or "").upper(): int(total or 0) for status, total in draft_rows}
    tasks = {str(status or "").upper(): int(total or 0) for status, total in task_rows}
    video_failed = sum(tasks.get(state, 0) for state in TERMINAL_TASK_STATES - SUCCESS_TASK_STATES)
    return {
        "promptWaiting": drafts.get("PENDING", 0),
        "promptGenerating": drafts.get("GENERATING", 0),
        "promptReady": drafts.get("READY", 0),
        "promptFailed": sum(drafts.get(state, 0) for state in FAILED_DRAFT_STATES),
        "promptTerminal": sum(drafts.get(state, 0) for state in TERMINAL_DRAFT_STATES),
        "videoRequested": sum(tasks.values()),
        "videoPendingSubmit": tasks.get("PENDING_SUBMIT", 0) + tasks.get("DISPATCHING", 0),
        "videoQueued": tasks.get("QUEUED", 0) + tasks.get("IN_QUEUE", 0),
        "videoInProgress": tasks.get("IN_PROGRESS", 0) + tasks.get("RUNNING", 0),
        "videoCompleted": sum(tasks.get(state, 0) for state in SUCCESS_TASK_STATES),
        "videoFailed": video_failed,
    }


def _batch_is_settled(db: Session, batch: BatchJob) -> bool:
    pending_drafts = db.scalar(
        select(func.count())
        .select_from(ImagePromptDraft)
        .where(ImagePromptDraft.batch_job_id == batch.id, ImagePromptDraft.status.not_in(TERMINAL_DRAFT_STATES))
    ) or 0
    if pending_drafts:
        return False
    unpromoted_ready_drafts = db.scalar(
        select(func.count())
        .select_from(ImagePromptDraft)
        .where(
            ImagePromptDraft.batch_job_id == batch.id,
            ImagePromptDraft.status == "READY",
            ~select(WorkflowTask.id)
            .where(
                WorkflowTask.prompt_draft_id == ImagePromptDraft.id,
                WorkflowTask.batch_job_id == ImagePromptDraft.batch_job_id,
                WorkflowTask.deleted_at.is_(None),
            )
            .exists(),
        )
    ) or 0
    if unpromoted_ready_drafts:
        return False
    pending_tasks = db.scalar(
        select(func.count())
        .select_from(WorkflowTask)
        .where(
            WorkflowTask.batch_job_id == batch.id,
            WorkflowTask.deleted_at.is_(None),
            WorkflowTask.status.not_in(TERMINAL_TASK_STATES),
        )
    ) or 0
    return int(pending_tasks) == 0


def list_active_batch_jobs(db: Session, *, created_by: str | None) -> dict[str, Any]:
    query = select(BatchJob).where(BatchJob.status == BATCH_JOB_INCOMPLETE)
    if created_by:
        query = query.where(BatchJob.created_by == created_by)
    batches = db.scalars(query.order_by(BatchJob.created_at.desc(), BatchJob.id.desc())).all()
    return {"items": [_batch_payload(db, batch) for batch in batches]}


def list_batch_jobs(
    db: Session,
    *,
    created_by: str | None,
    page: int = 1,
    date_from: str | None = None,
    date_to: str | None = None,
    worker_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    query = select(BatchJob)
    if created_by:
        query = query.where(BatchJob.created_by == created_by)
    elif worker_id:
        query = query.where(BatchJob.created_by == worker_id)
    if status:
        query = query.where(BatchJob.status == str(status).upper())
    parsed_from = _parse_date(date_from)
    if parsed_from:
        query = query.where(BatchJob.created_at >= parsed_from)
    parsed_to = _parse_date(date_to, end_of_day=True)
    if parsed_to:
        query = query.where(BatchJob.created_at <= parsed_to)

    safe_page = max(1, int(page or 1))
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(
        query.order_by(BatchJob.created_at.desc(), BatchJob.id.desc())
        .offset((safe_page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    worker_rows = db.execute(
        select(BatchJob.created_by, User.name)
        .join(User, User.id == BatchJob.created_by, isouter=True)
        .where(BatchJob.created_by.is_not(None))
        .group_by(BatchJob.created_by, User.name)
    ).all()
    return {
        "items": [_batch_payload(db, row) for row in rows],
        "page": safe_page,
        "pageSize": PAGE_SIZE,
        "total": total,
        "workers": [{"workerId": str(worker_id), "workerName": str(name or worker_id)} for worker_id, name in worker_rows],
    }


def mark_batch_downloaded(db: Session, batch_job_id: str) -> None:
    batch = db.get(BatchJob, batch_job_id)
    if batch is None:
        return
    batch.last_downloaded_at = datetime.utcnow()
    db.commit()


def _parse_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if end_of_day and len(text) <= 10:
        return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    if len(text) <= 10:
        return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    return parsed


def _submitter_user(owner_id: str) -> dict[str, Any]:
    """The batch job's owner is also the submitter of its promoted requests.

    The real row is used so created tasks carry the owner's own name and
    permissions exactly as an interactive submission by that user would.
    """
    db = SessionLocal()
    try:
        user = db.get(User, owner_id)
        if user is None or not user.is_active:
            raise ValueError("선택한 작업자를 찾을 수 없거나 비활성 상태입니다.")
        return {
            "id": user.id,
            "name": user.name,
            "role": user.role,
            "permissions": user.permissions_json or [],
        }
    finally:
        db.close()


__all__ = [
    "ALLOWED_FRAMES",
    "DEFAULT_FRAMES",
    "BATCH_JOB_INCOMPLETE",
    "BATCH_JOB_COMPLETE",
    "resolve_duration_seconds",
    "create_batch_job",
    "batch_job_payload",
    "claim_batch_drafts_for_promotion",
    "still_owns_claim",
    "release_promotion_claim",
    "promote_ready_batch_drafts",
    "refresh_batch_job_counters",
    "list_active_batch_jobs",
    "list_batch_jobs",
    "mark_batch_downloaded",
]
