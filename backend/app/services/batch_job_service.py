"""Folder-scoped batch orchestration over the existing prompt and RunPod pipelines.

A batch job owns nothing that the existing pipelines already own. It records the
user's folder-level intent, links the prompt and RunPod batches it spawned, and
keeps denormalized counters so the dashboards never join across three tables.
"""
from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    BATCH_JOB_COMPLETE,
    BATCH_JOB_INCOMPLETE,
    BatchJob,
    ImagePromptDraft,
    PromptGenerationBatch,
    RunpodRequestBatch,
    RunpodRequestItem,
    User,
)
from backend.app.db.session import SessionLocal
from backend.app.services import prompt_batch_service, workflow_service

ALLOWED_FRAMES: frozenset[int] = frozenset({49, 81, 161})
DEFAULT_FRAMES = 81
DEFAULT_FPS = 16

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


def create_batch_job(db: Session, payload: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    """Create the batch job and its prompt generation batch in one transaction."""
    workflow_id = str(payload.get("workflowId") or "").strip()
    if not workflow_id:
        raise ValueError("워크플로우를 먼저 선택하세요.")
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValueError("배치로 처리할 이미지를 하나 이상 선택하세요.")
    requested_frames = _validated_frames(payload.get("requestedFrames", DEFAULT_FRAMES))

    batch = BatchJob(
        id=f"batch_{uuid.uuid4().hex[:16]}",
        workflow_id=workflow_id,
        status=BATCH_JOB_INCOMPLETE,
        source_dir_name=str(payload.get("sourceDirName") or "").strip()[:512] or None,
        requested_frames=requested_frames,
        duration_seconds=resolve_duration_seconds(workflow_id, requested_frames),
        total_images=len(items),
        created_by=created_by,
    )
    db.add(batch)
    db.flush()

    # Reuse the existing prompt pipeline wholesale. It raises before any write
    # when the workflow has no active instruction, so a failed batch leaves no
    # rows behind and the uploaded assets stay deletable.
    prompt_batch = prompt_batch_service.create_prompt_generation_batch(
        db,
        {
            "workflowId": workflow_id,
            "items": [
                {
                    "assetId": str(item.get("assetId") or "").strip(),
                    "slotIndex": index,
                    "requestedFrames": requested_frames,
                }
                for index, item in enumerate(items, start=1)
            ],
        },
        created_by=created_by,
    )

    db.execute(
        PromptGenerationBatch.__table__.update()
        .where(PromptGenerationBatch.id == prompt_batch["id"])
        .values(batch_job_id=batch.id)
    )
    db.execute(
        ImagePromptDraft.__table__.update()
        .where(ImagePromptDraft.prompt_batch_id == prompt_batch["id"])
        .values(batch_job_id=batch.id)
    )
    db.commit()
    return batch_job_payload(db, batch.id)


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
    """Turn newly-READY batch prompts into RunPod requests.

    Called once per monitor cycle. Reuses studio_api_service wholesale so batch
    submissions are indistinguishable from interactive ones: same request-item
    snapshot, same durable task record, same dispatcher.
    """
    # Imported here: studio_api_service imports this module's siblings, and a
    # module-level import would create a cycle at application start.
    from backend.app.services import studio_api_service

    db = SessionLocal()
    promoted_batches: list[str] = []
    promoted = 0
    try:
        incomplete = db.execute(
            select(BatchJob.id, BatchJob.created_by).where(BatchJob.status == BATCH_JOB_INCOMPLETE)
        ).all()
        pending: list[tuple[str, str, list[str]]] = []
        for batch_id, created_by in incomplete:
            # A draft that already owns a request item — even a failed one —
            # must never be requested twice. This is what makes a repeated
            # monitor cycle a no-op instead of a duplicate RunPod submission.
            already = set(db.scalars(
                select(RunpodRequestItem.prompt_draft_id)
                .join(RunpodRequestBatch, RunpodRequestItem.request_batch_id == RunpodRequestBatch.id)
                .where(RunpodRequestBatch.batch_job_id == batch_id)
            ))
            draft_ids = [
                draft_id
                for draft_id in db.scalars(
                    select(ImagePromptDraft.id).where(
                        ImagePromptDraft.batch_job_id == batch_id,
                        ImagePromptDraft.status == "READY",
                    )
                )
                if draft_id not in already
            ]
            if draft_ids:
                pending.append((batch_id, str(created_by or ""), draft_ids))
    finally:
        # The session is closed before submitting: create_runpod_request_batch
        # opens its own sessions under JOB_LOCK and must not contend with a
        # read transaction held open across the whole promotion pass.
        db.close()

    for batch_id, owner_id, draft_ids in pending:
        if not owner_id:
            continue
        try:
            studio_api_service.create_runpod_request_batch(
                {
                    "workerId": owner_id,
                    "batchJobId": batch_id,
                    "items": [{"promptDraftId": draft_id} for draft_id in draft_ids],
                },
                user=_submitter_user(owner_id),
            )
        except Exception as exc:  # noqa: BLE001 - one bad batch must not stop the rest
            # A batch whose owner went inactive raises for every cycle from now
            # on. Without this the first such batch would permanently block
            # promotion for every other batch in the same monitor pass.
            _PROMOTION_FAILURES[batch_id] = str(exc)
            continue
        _PROMOTION_FAILURES.pop(batch_id, None)
        promoted += len(draft_ids)
        promoted_batches.append(batch_id)

    return {"promoted": promoted, "batches": promoted_batches}


def _submitter_user(owner_id: str) -> dict[str, Any]:
    """The batch job's owner is also the submitter of its promoted requests.

    create_runpod_request_batch reads only ``id``, but the real row is used so
    the created tasks carry the owner's own name and permissions exactly as an
    interactive submission by that user would.
    """
    db = SessionLocal()
    try:
        user = db.get(User, owner_id)
        if user is None:
            return {"id": owner_id}
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
    "promote_ready_batch_drafts",
]
