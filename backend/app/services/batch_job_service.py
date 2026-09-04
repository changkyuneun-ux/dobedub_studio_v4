"""Folder-scoped batch orchestration over the existing prompt and RunPod pipelines.

A batch job owns nothing that the existing pipelines already own. It records the
user's folder-level intent, links the prompt and RunPod batches it spawned, and
keeps denormalized counters so the dashboards never join across three tables.
"""
from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy.orm import Session

from backend.app.db.models import (
    BATCH_JOB_COMPLETE,
    BATCH_JOB_INCOMPLETE,
    BatchJob,
    ImagePromptDraft,
    PromptGenerationBatch,
    User,
)
from backend.app.services import prompt_batch_service, workflow_service

ALLOWED_FRAMES: frozenset[int] = frozenset({49, 81, 161})
DEFAULT_FRAMES = 81
DEFAULT_FPS = 16


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


__all__ = [
    "ALLOWED_FRAMES",
    "DEFAULT_FRAMES",
    "BATCH_JOB_INCOMPLETE",
    "BATCH_JOB_COMPLETE",
    "resolve_duration_seconds",
    "create_batch_job",
    "batch_job_payload",
]
