"""Folder-scoped batch orchestration over the existing prompt and RunPod pipelines.

A batch job owns nothing that the existing pipelines already own. It records the
user's folder-level intent, links the prompt and RunPod batches it spawned, and
keeps denormalized counters so the dashboards never join across three tables.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import unicodedata

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import SEOUL_TIMEZONE, UTC_TIMEZONE, now_seoul_naive, utc_now
from backend.app.db.models import (
    Asset,
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
from backend.app.services.zip_encoding_service import normalize_zip_path

ALLOWED_FRAMES: frozenset[int] = frozenset({49, 81, 161})
DEFAULT_FRAMES = 81
DEFAULT_FPS = 16
PROMOTION_LIMIT_PER_CYCLE = 20
STALE_PROMOTION_CLAIM_SECONDS = 300
PAGE_SIZE = 5
TERMINAL_DRAFT_STATES = frozenset({"READY", "FAILED", "MANUAL_REQUIRED"})
FAILED_DRAFT_STATES = frozenset({"FAILED", "MANUAL_REQUIRED"})
TERMINAL_TASK_STATES = frozenset({"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"})
SUCCESS_TASK_STATES = frozenset({"COMPLETED", "SUCCESS"})
REWORKABLE_TASK_STATES = TERMINAL_TASK_STATES - SUCCESS_TASK_STATES
ACTIVE_TASK_STATES = frozenset({"PENDING_SUBMIT", "DISPATCHING", "QUEUED", "IN_QUEUE", "IN_PROGRESS", "RUNNING"})

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
    compact = "_".join(unicodedata.normalize("NFC", raw).split())
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


def _safe_batch_token(value: str, *, fallback: str = "unknown") -> str:
    compact = "_".join(unicodedata.normalize("NFC", str(value or "").strip()).split())
    compact = compact.replace("/", "_").replace("\\", "_").replace(":", "_")
    cleaned = "".join(ch for ch in compact if ch.isprintable()).strip("._")
    return cleaned or fallback


def _fit_zip_batch_job_id(
    worker_token: str,
    zip_token: str,
    date_suffix: str,
    collision_suffix: str,
    *,
    max_length: int = 64,
) -> str:
    fixed_length = len(worker_token) + 1 + len(date_suffix) + len(collision_suffix)
    max_zip_length = max(1, max_length - fixed_length)
    return f"{worker_token}_{zip_token[:max_zip_length]}{date_suffix}{collision_suffix}"


def _next_zip_batch_job_id(db: Session, *, created_by: str, created_at: datetime, zip_file_name: str) -> str:
    created_at_utc = _aware_utc(created_at)
    date_suffix = f"_{created_at_utc.astimezone(SEOUL_TIMEZONE).strftime('%y%m%d')}"
    worker_token = _safe_batch_token(_worker_batch_token(db, created_by))
    zip_token = _safe_batch_token(Path(Path(zip_file_name).name).stem, fallback="upload")
    candidate = _fit_zip_batch_job_id(worker_token, zip_token, date_suffix, "")
    sequence = 2
    while db.get(BatchJob, candidate) is not None:
        collision_suffix = f"_{sequence}"
        candidate = _fit_zip_batch_job_id(worker_token, zip_token, date_suffix, collision_suffix)
        sequence += 1
    return candidate


def create_batch_job(db: Session, payload: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    """Create the batch job and its prompt generation batch in one transaction."""
    workflow_id = str(payload.get("workflowId") or "").strip()
    if not workflow_id:
        raise ValueError("워크플로우를 먼저 선택하세요.")
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValueError("배치로 처리할 이미지를 하나 이상 선택하세요.")
    requested_frames = _validated_frames(payload.get("requestedFrames", DEFAULT_FRAMES))
    negative_prompt = str(payload.get("negativePrompt") or "").strip()

    created_at = _aware_utc(utc_now()).replace(tzinfo=None)
    source_dir_name = unicodedata.normalize("NFC", str(payload.get("sourceDirName") or "").strip())
    source_zip_file_name = unicodedata.normalize("NFC", str(payload.get("sourceZipFileName") or "").strip())
    batch = BatchJob(
        id=(
            _next_zip_batch_job_id(db, created_by=created_by, created_at=created_at, zip_file_name=source_zip_file_name)
            if source_zip_file_name
            else _next_batch_job_id(db, created_by=created_by, created_at=created_at)
        ),
        workflow_id=workflow_id,
        status=BATCH_JOB_INCOMPLETE,
        source_dir_name=source_dir_name[:512] or None,
        source_zip_file_name=source_zip_file_name[:512] or None,
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
        source_zip_file_name=source_zip_file_name,
        negative_prompt=negative_prompt,
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
    source_zip_file_name: str = "",
    negative_prompt: str = "",
) -> dict[str, Any]:
    """Create linked prompt rows while create_batch_job owns the transaction."""
    return prompt_batch_service.create_prompt_generation_batch(
        db,
        {
            "workflowId": workflow_id,
            "items": [
                {
                    "assetId": str(item.get("assetId") or "").strip(),
                    "slotIndex": index,
                    "requestedFrames": requested_frames,
                    "negativePrompt": negative_prompt,
                }
                | {
                    key: value
                    for key, value in {
                        "sourceRelativePath": str(item.get("relativePath") or "").strip(),
                        "sourceZipFileName": source_zip_file_name,
                    }.items()
                    if value
                }
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


def batch_job_detail(db: Session, batch_job_id: str) -> dict[str, Any]:
    batch = db.get(BatchJob, batch_job_id)
    if batch is None:
        raise ValueError("배치 작업을 찾을 수 없습니다.")
    batch.status = BATCH_JOB_COMPLETE if _refresh_batch_row(db, batch) else BATCH_JOB_INCOMPLETE
    drafts = db.scalars(
        select(ImagePromptDraft)
        .where(ImagePromptDraft.batch_job_id == batch.id)
        .order_by(ImagePromptDraft.slot_index.asc(), ImagePromptDraft.created_at.asc(), ImagePromptDraft.id.asc())
    ).all()
    draft_ids = [draft.id for draft in drafts]
    task_filter = WorkflowTask.batch_job_id == batch.id
    if draft_ids:
        task_filter = or_(task_filter, WorkflowTask.prompt_draft_id.in_(draft_ids))
    tasks = db.scalars(
        select(WorkflowTask)
        .where(task_filter, WorkflowTask.deleted_at.is_(None))
        .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
    ).all()
    tasks_by_draft: dict[str, list[WorkflowTask]] = {}
    orphan_tasks: list[WorkflowTask] = []
    warnings: list[dict[str, Any]] = []
    for task in tasks:
        key = str(task.prompt_draft_id or "").strip()
        if key:
            if key in draft_ids and not task.batch_job_id:
                payload = dict(task.payload_json or {})
                payload["batchJobId"] = batch.id
                task.payload_json = payload
                task.batch_job_id = batch.id
                task.updated_at = now_seoul_naive()
                warnings.append({
                    "type": "repaired_missing_batch_link",
                    "promptDraftId": key,
                    "taskId": task.id,
                    "batchJobId": batch.id,
                })
            elif key in draft_ids and task.batch_job_id != batch.id:
                warnings.append({
                    "type": "conflicting_batch_link",
                    "promptDraftId": key,
                    "taskId": task.id,
                    "batchJobId": task.batch_job_id,
                    "expectedBatchJobId": batch.id,
                })
            tasks_by_draft.setdefault(key, []).append(task)
        else:
            orphan_tasks.append(task)

    duplicate_draft_ids = {
        draft_id
        for draft_id, linked_tasks in tasks_by_draft.items()
        if len(linked_tasks) > 1
    }
    for draft_id in sorted(duplicate_draft_ids):
        warnings.append({
            "type": "duplicate_runpod_task",
            "promptDraftId": draft_id,
            "taskIds": [task.id for task in tasks_by_draft[draft_id]],
        })
    for task in orphan_tasks:
        warnings.append({
            "type": "missing_prompt_draft_link",
            "taskId": task.id,
            "batchJobId": batch.id,
        })

    asset_ids = {draft.asset_id for draft in drafts if draft.asset_id}
    assets = {
        asset.id: asset
        for asset in db.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
    } if asset_ids else {}

    items = [
        _batch_detail_item(draft, tasks_by_draft.get(draft.id, []), assets.get(draft.asset_id), duplicate=draft.id in duplicate_draft_ids)
        for draft in drafts
    ]
    items.extend(_orphan_task_detail_item(task) for task in orphan_tasks)
    batch.status = BATCH_JOB_COMPLETE if _refresh_batch_row(db, batch) else BATCH_JOB_INCOMPLETE
    return {"batch": _batch_payload(db, batch), "items": items, "warnings": warnings}


def _batch_payload(db: Session, batch: BatchJob) -> dict[str, Any]:
    return {
        "id": batch.id,
        "workflowId": batch.workflow_id,
        "status": batch.status,
        "sourceDirName": batch.source_dir_name,
        "sourceZipFileName": batch.source_zip_file_name,
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


def _source_metadata(draft: ImagePromptDraft) -> dict[str, str]:
    raw = draft.raw_json if isinstance(draft.raw_json, dict) else {}
    return {
        "sourceRelativePath": normalize_zip_path(str(raw.get("sourceRelativePath") or "").strip()),
        "sourceZipFileName": normalize_zip_path(str(raw.get("sourceZipFileName") or "").strip()),
    }


def _source_file_name(draft: ImagePromptDraft, asset: Asset | None) -> str:
    metadata = _source_metadata(draft)
    source_path = metadata["sourceRelativePath"]
    if source_path:
        return Path(source_path).name
    return asset.file_name if asset and asset.file_name else draft.asset_id


def _task_error(task: WorkflowTask | None) -> str:
    if task is None:
        return ""
    status_json = task.runpod_status_json if isinstance(task.runpod_status_json, dict) else {}
    submit_json = task.runpod_submit_json if isinstance(task.runpod_submit_json, dict) else {}
    candidates = (
        task.last_dispatch_error,
        status_json.get("error"),
        status_json.get("message"),
        submit_json.get("error"),
        submit_json.get("message"),
    )
    return next((str(value) for value in candidates if value), "")


def _batch_detail_item(
    draft: ImagePromptDraft,
    linked_tasks: list[WorkflowTask],
    asset: Asset | None,
    *,
    duplicate: bool,
) -> dict[str, Any]:
    latest_task = linked_tasks[-1] if linked_tasks else None
    prompt_status = str(draft.status or "").upper()
    runpod_status = str(latest_task.status or "").upper() if latest_task else "미요청"
    prompt_failed = prompt_status in FAILED_DRAFT_STATES
    runpod_failed = latest_task is not None and runpod_status in REWORKABLE_TASK_STATES
    runpod_active = latest_task is not None and runpod_status in ACTIVE_TASK_STATES
    retry_kind = "none"
    retryable = False
    action_label = "제외"
    error = ""
    if duplicate:
        error = "동일 프롬프트에 연결된 RunPod 작업이 2개 이상입니다."
    elif prompt_failed and latest_task is None:
        retry_kind = "prompt"
        retryable = True
        action_label = "재처리"
        error = str(draft.failure_message or "")
    elif runpod_failed:
        retry_kind = "runpod"
        retryable = True
        action_label = "재작업"
        error = _task_error(latest_task)
    elif runpod_active:
        action_label = "잠김"
        error = _task_error(latest_task)
    metadata = _source_metadata(draft)
    return {
        "id": f"{draft.id}:{latest_task.id if latest_task else ''}",
        "assetId": draft.asset_id,
        "sourceFileName": _source_file_name(draft, asset),
        "sourceRelativePath": metadata["sourceRelativePath"],
        "sourceZipFileName": metadata["sourceZipFileName"],
        "promptDraftId": draft.id,
        "taskId": latest_task.id if latest_task else None,
        "promptStatus": prompt_status,
        "runpodStatus": runpod_status,
        "error": error,
        "retryKind": retry_kind,
        "retryable": retryable,
        "selectable": retryable,
        "actionLabel": action_label,
        "retryCount": int((latest_task.dispatch_attempts if latest_task else 0) or 0),
        "nextRetryAt": latest_task.next_dispatch_at.isoformat() if latest_task and latest_task.next_dispatch_at else None,
    }


def _orphan_task_detail_item(task: WorkflowTask) -> dict[str, Any]:
    return {
        "id": f":{task.id}",
        "assetId": None,
        "sourceFileName": "-",
        "sourceRelativePath": "",
        "sourceZipFileName": "",
        "promptDraftId": None,
        "taskId": task.id,
        "promptStatus": "연결 누락",
        "runpodStatus": str(task.status or "").upper(),
        "error": "RunPod 작업에 prompt_draft_id 연결이 없습니다.",
        "retryKind": "none",
        "retryable": False,
        "selectable": False,
        "actionLabel": "확인",
        "retryCount": int(task.dispatch_attempts or 0),
        "nextRetryAt": task.next_dispatch_at.isoformat() if task.next_dispatch_at else None,
    }


def _user_name(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user.name if user else None


def _normalized_search_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold()


def _batch_candidate_payload(batch: BatchJob, worker_name: str | None) -> dict[str, Any]:
    return {
        "id": batch.id,
        "workflowId": batch.workflow_id,
        "status": batch.status,
        "sourceDirName": batch.source_dir_name,
        "sourceZipFileName": batch.source_zip_file_name,
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
        "createdByName": worker_name or batch.created_by,
        "createdAt": batch.created_at.isoformat() if batch.created_at else None,
        "updatedAt": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def list_batch_job_candidates(
    db: Session,
    *,
    created_by: str | None,
    query: str,
    limit: int = 10,
) -> dict[str, Any]:
    needle = _normalized_search_text(query).strip()
    safe_limit = max(1, min(20, int(limit or 10)))
    if not needle:
        return {"items": []}

    statement = (
        select(BatchJob, User.name)
        .join(User, User.id == BatchJob.created_by, isouter=True)
        .order_by(BatchJob.created_at.desc(), BatchJob.id.desc())
        .limit(1000)
    )
    if created_by:
        statement = statement.where(BatchJob.created_by == created_by)

    items: list[dict[str, Any]] = []
    for batch, worker_name in db.execute(statement).all():
        haystacks = (
            batch.id,
            batch.source_dir_name,
            batch.source_zip_file_name,
            batch.created_by,
            worker_name,
        )
        if any(needle in _normalized_search_text(value) for value in haystacks):
            items.append(_batch_candidate_payload(batch, worker_name))
            if len(items) >= safe_limit:
                break
    return {"items": items}


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
            ImagePromptDraft.positive_prompt.is_not(None),
            func.length(func.trim(ImagePromptDraft.positive_prompt)) > 0,
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
            if _refresh_batch_row(db, batch):
                batch.status = BATCH_JOB_COMPLETE
                completed += 1
            refreshed += 1
        db.commit()
    finally:
        db.close()
    return {"refreshed": refreshed, "completed": completed}


def _refresh_batch_row(db: Session, batch: BatchJob) -> bool:
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
    return _batch_is_settled(db, batch)


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
    blank_ready = int(db.scalar(
        select(func.count())
        .select_from(ImagePromptDraft)
        .where(
            ImagePromptDraft.batch_job_id == batch_job_id,
            ImagePromptDraft.status == "READY",
            or_(
                ImagePromptDraft.positive_prompt.is_(None),
                func.length(func.trim(ImagePromptDraft.positive_prompt)) == 0,
            ),
        )
    ) or 0)
    valid_ready = max(0, drafts.get("READY", 0) - blank_ready)
    video_failed = sum(tasks.get(state, 0) for state in TERMINAL_TASK_STATES - SUCCESS_TASK_STATES)
    return {
        "promptWaiting": drafts.get("PENDING", 0),
        "promptGenerating": drafts.get("GENERATING", 0),
        "promptReady": valid_ready,
        "promptFailed": sum(drafts.get(state, 0) for state in FAILED_DRAFT_STATES) + blank_ready,
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
            ImagePromptDraft.positive_prompt.is_not(None),
            func.length(func.trim(ImagePromptDraft.positive_prompt)) > 0,
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


def retry_failed_batch_items(
    db: Session,
    batch_job_id: str,
    *,
    actor_id: str,
    can_manage: bool,
    stage: str = "all",
    draft_ids: list[str] | None = None,
    task_ids: list[str] | None = None,
) -> dict[str, Any]:
    batch = db.get(BatchJob, batch_job_id)
    if batch is None:
        raise ValueError("배치 작업을 찾을 수 없습니다.")
    if not can_manage and str(batch.created_by or "") != str(actor_id or ""):
        raise PermissionError("다른 작업자의 배치는 재처리할 수 없습니다.")
    normalized_stage = str(stage or "all").strip().lower()
    if normalized_stage not in {"all", "prompt", "runpod"}:
        raise ValueError("재처리 stage 값이 올바르지 않습니다.")

    selected_draft_ids = {str(draft_id) for draft_id in draft_ids or [] if str(draft_id or "").strip()}
    selected_task_ids = {str(task_id) for task_id in task_ids or [] if str(task_id or "").strip()}
    has_explicit_selection = bool(selected_draft_ids or selected_task_ids)
    skipped: list[dict[str, str]] = []
    prompt_retried = 0
    runpod_reworked = 0
    duplicate_prompt_ids = _duplicate_prompt_task_ids(db, batch.id)

    if normalized_stage in {"all", "prompt"}:
        prompt_query = select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == batch.id)
        if selected_draft_ids:
            prompt_query = prompt_query.where(ImagePromptDraft.id.in_(selected_draft_ids))
        elif has_explicit_selection:
            prompt_query = prompt_query.where(False)
        else:
            prompt_query = prompt_query.where(ImagePromptDraft.status.in_(FAILED_DRAFT_STATES))
        for draft in db.scalars(prompt_query.order_by(ImagePromptDraft.slot_index.asc(), ImagePromptDraft.id.asc())).all():
            if str(draft.status or "").upper() not in FAILED_DRAFT_STATES:
                skipped.append({"id": draft.id, "reason": "not_failed_prompt"})
                continue
            if draft.id in duplicate_prompt_ids:
                skipped.append({"id": draft.id, "reason": "duplicate_runpod_task"})
                continue
            linked_task_exists = db.scalar(
                select(func.count())
                .select_from(WorkflowTask)
                .where(
                    WorkflowTask.batch_job_id == batch.id,
                    WorkflowTask.prompt_draft_id == draft.id,
                    WorkflowTask.deleted_at.is_(None),
                )
            ) or 0
            if int(linked_task_exists) > 0:
                skipped.append({"id": draft.id, "reason": "already_has_runpod_task"})
                continue
            _reset_prompt_draft_for_retry(draft)
            prompt_retried += 1

    if normalized_stage in {"all", "runpod"}:
        task_query = select(WorkflowTask).where(WorkflowTask.batch_job_id == batch.id, WorkflowTask.deleted_at.is_(None))
        if selected_task_ids:
            task_query = task_query.where(WorkflowTask.id.in_(selected_task_ids))
        elif has_explicit_selection:
            task_query = task_query.where(False)
        else:
            task_query = task_query.where(WorkflowTask.status.in_(REWORKABLE_TASK_STATES))
        for task in db.scalars(task_query.order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())).all():
            status = str(task.status or "").upper()
            if status not in REWORKABLE_TASK_STATES:
                skipped.append({"id": task.id, "reason": "not_reworkable_runpod"})
                continue
            if not task.prompt_draft_id:
                skipped.append({"id": task.id, "reason": "missing_prompt_draft_link"})
                continue
            if str(task.prompt_draft_id) in duplicate_prompt_ids:
                skipped.append({"id": task.id, "reason": "duplicate_runpod_task"})
                continue
            _reset_runpod_task_for_rework(db, task, actor_id=actor_id)
            runpod_reworked += 1

    batch.status = BATCH_JOB_INCOMPLETE
    _refresh_batch_row(db, batch)
    db.commit()
    return {
        "batchJobId": batch.id,
        "promptRetried": prompt_retried,
        "runpodReworked": runpod_reworked,
        "skipped": skipped,
        "batch": _batch_payload(db, batch),
    }


def _duplicate_prompt_task_ids(db: Session, batch_job_id: str) -> set[str]:
    rows = db.execute(
        select(WorkflowTask.prompt_draft_id, func.count())
        .where(
            WorkflowTask.batch_job_id == batch_job_id,
            WorkflowTask.deleted_at.is_(None),
            WorkflowTask.prompt_draft_id.is_not(None),
        )
        .group_by(WorkflowTask.prompt_draft_id)
        .having(func.count() > 1)
    ).all()
    return {str(prompt_draft_id) for prompt_draft_id, _count in rows if prompt_draft_id}


def _reset_prompt_draft_for_retry(draft: ImagePromptDraft) -> None:
    source_metadata = {key: value for key, value in _source_metadata(draft).items() if value}
    draft.status = "PENDING"
    draft.positive_prompt = None
    draft.failure_message = None
    draft.warnings_json = []
    draft.raw_json = source_metadata
    draft.promotion_claimed_at = None
    draft.updated_at = now_seoul_naive()


def _reset_runpod_task_for_rework(db: Session, task: WorkflowTask, *, actor_id: str) -> None:
    now = now_seoul_naive()
    payload = dict(task.payload_json or {})
    for key in ("regeneratedFromTaskId", "runpodJobId", "generationSeed"):
        payload.pop(key, None)
    if not isinstance(payload.get("user"), dict) or not payload["user"].get("id"):
        payload["user"] = {
            "id": task.user_id or actor_id,
            "name": task.worker_name or task.user_id or actor_id,
            "role": "",
            "permissions": [],
        }
    if task.batch_job_id:
        payload["batchJobId"] = task.batch_job_id
    if task.prompt_draft_id:
        payload["promptDraftId"] = task.prompt_draft_id

    task.status = "PENDING_SUBMIT"
    task.progress = 0
    task.runpod_job_id = None
    task.completed_at = None
    task.elapsed_seconds = None
    task.runpod_submit_json = {}
    task.runpod_status_json = {}
    task.payload_json = payload
    task.wan_node_config = {}
    task.dispatch_claimed_at = None
    task.dispatch_attempts = 0
    task.next_dispatch_at = None
    task.last_dispatch_error = None
    task.started_at = now
    task.updated_at = now
    for link in list(task.output_assets):
        db.delete(link)
    for prompt in list(task.prompts):
        prompt.output_asset_ids = []
        prompt.updated_at = now


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
    "list_batch_job_candidates",
    "claim_batch_drafts_for_promotion",
    "still_owns_claim",
    "release_promotion_claim",
    "promote_ready_batch_drafts",
    "refresh_batch_job_counters",
    "list_active_batch_jobs",
    "list_batch_jobs",
    "mark_batch_downloaded",
]
