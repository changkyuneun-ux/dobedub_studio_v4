"""Durable, workflow-scoped Grok image prompt batch processing."""
from __future__ import annotations

from datetime import datetime, timezone
import time
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import Asset, ImagePromptDraft, PromptGenerationAttempt, PromptGenerationBatch, User, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services import studio_api_service
from backend.app.services.grok_image_prompt_service import GrokPromptError, GrokPromptInputError, generate_image_prompt
from backend.app.services.grok_instruction_service import active_instruction_text


BATCH_PENDING = "PENDING"
BATCH_GENERATING = "GENERATING"
BATCH_COMPLETED = "COMPLETED"
BATCH_COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
DRAFT_PENDING = "PENDING"
DRAFT_GENERATING = "GENERATING"
DRAFT_READY = "READY"
DRAFT_FAILED = "FAILED"


def create_prompt_generation_batch(db: Session, payload: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    workflow_id = str(payload.get("workflowId") or "").strip()
    items = payload.get("items") or []
    if not workflow_id:
        raise ValueError("워크플로우를 먼저 선택하세요.")
    if not isinstance(items, list) or not items:
        raise ValueError("프롬프트를 생성할 입력 이미지를 하나 이상 선택하세요.")
    instruction_text, instruction_version = active_instruction_text(workflow_id)
    # Resolving before writes means an unconfigured workflow creates no partial batch.
    del instruction_text
    settings = get_settings()
    batch = PromptGenerationBatch(
        id=f"pgb_{uuid.uuid4().hex[:16]}",
        workflow_id=workflow_id,
        status=BATCH_PENDING,
        total_count=len(items),
        completed_count=0,
        failed_count=0,
        created_by=created_by,
    )
    db.add(batch)
    for fallback_slot, source in enumerate(items, start=1):
        if not isinstance(source, dict):
            raise ValueError("이미지 선택 형식이 올바르지 않습니다.")
        asset_id = str(source.get("assetId") or "").strip()
        if not asset_id:
            raise ValueError("각 이미지에 assetId가 필요합니다.")
        slot_index = _positive_int(source.get("slotIndex"), fallback_slot)
        requested_frames = _positive_int(source.get("requestedFrames"), 81)
        draft = ImagePromptDraft(
            id=f"grok_draft_{uuid.uuid4().hex[:16]}",
            asset_id=asset_id,
            workflow_id=workflow_id,
            slot_index=slot_index,
            status=DRAFT_PENDING,
            provider="grok",
            model=settings.grok_model,
            instruction_version=instruction_version,
            prompt_batch_id=batch.id,
            negative_prompt=str(source.get("negativePrompt") or "").strip() or None,
            requested_frames=requested_frames,
            warnings_json=[],
            raw_json={},
            created_by=created_by,
        )
        db.add(draft)
    db.commit()
    return prompt_generation_batch_payload(db, batch.id)


def process_next_prompt_generation_draft() -> dict[str, Any] | None:
    """Process one pending Grok item. Called by the application monitor loop."""
    db = SessionLocal()
    try:
        draft = db.scalar(
            select(ImagePromptDraft)
            .where(ImagePromptDraft.status == DRAFT_PENDING)
            .order_by(ImagePromptDraft.created_at.asc(), ImagePromptDraft.id.asc())
            .limit(1)
        )
        if draft is None:
            return None
        return _process_draft(db, draft)
    finally:
        db.close()


def process_prompt_generation_batch(db: Session, batch_id: str) -> dict[str, Any]:
    """Process all pending drafts for deterministic tests and one-off operations."""
    while True:
        draft = db.scalar(
            select(ImagePromptDraft)
            .where(ImagePromptDraft.prompt_batch_id == batch_id, ImagePromptDraft.status == DRAFT_PENDING)
            .order_by(ImagePromptDraft.created_at.asc(), ImagePromptDraft.id.asc())
            .limit(1)
        )
        if draft is None:
            break
        _process_draft(db, draft)
    return prompt_generation_batch_payload(db, batch_id)


def prompt_generation_batch_payload(db: Session, batch_id: str) -> dict[str, Any]:
    batch = db.get(PromptGenerationBatch, batch_id)
    if batch is None:
        raise ValueError("Prompt generation batch was not found.")
    drafts = db.scalars(
        select(ImagePromptDraft)
        .where(ImagePromptDraft.prompt_batch_id == batch_id)
        .order_by(ImagePromptDraft.slot_index.asc(), ImagePromptDraft.created_at.asc())
    ).all()
    counts = _batch_counts_from_drafts(batch, drafts)
    return {
        "id": batch.id,
        "workflowId": batch.workflow_id,
        "status": counts["status"],
        "totalCount": counts["total"],
        "completedCount": counts["completed"],
        "failedCount": counts["failed"],
        "pendingCount": counts["pending"],
        "items": [_draft_payload(db, draft) for draft in drafts],
    }


def latest_active_prompt_generation_batch(db: Session, *, created_by: str | None) -> dict[str, Any] | None:
    """Return the newest unfinished batch for the legacy durable-workspace API."""
    batches = list_active_prompt_generation_batches(db, created_by=created_by)
    return batches[0] if batches else None


def list_active_prompt_generation_batches(db: Session, *, created_by: str | None) -> list[dict[str, Any]]:
    """Return every unfinished prompt batch for the operator dashboard."""
    active_draft_exists = (
        select(ImagePromptDraft.id)
        .where(
            ImagePromptDraft.prompt_batch_id == PromptGenerationBatch.id,
            ImagePromptDraft.status.in_((DRAFT_PENDING, DRAFT_GENERATING)),
        )
        .exists()
    )
    statement = (
        select(PromptGenerationBatch)
        .where(
            or_(PromptGenerationBatch.status.in_((BATCH_PENDING, BATCH_GENERATING)), active_draft_exists),
        )
        .order_by(PromptGenerationBatch.created_at.desc(), PromptGenerationBatch.id.desc())
    )
    if created_by is not None:
        statement = statement.where(PromptGenerationBatch.created_by == created_by)
    batches = db.scalars(statement).all()
    payloads = [prompt_generation_batch_payload(db, batch.id) for batch in batches]
    return [payload for payload in payloads if payload["status"] in {BATCH_PENDING, BATCH_GENERATING}]


def list_prompt_drafts(
    db: Session,
    *,
    created_by: str | None,
    workflow_id: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 50,
    include_worker_stats: bool = True,
) -> dict[str, Any]:
    """Return the current user's image-scoped prompts for RunPod request selection."""
    statement = select(ImagePromptDraft)
    count_statement = select(func.count(ImagePromptDraft.id))
    if created_by is not None:
        statement = statement.where(ImagePromptDraft.created_by == created_by)
        count_statement = count_statement.where(ImagePromptDraft.created_by == created_by)
    if workflow_id:
        statement = statement.where(ImagePromptDraft.workflow_id == workflow_id)
        count_statement = count_statement.where(ImagePromptDraft.workflow_id == workflow_id)
    if status:
        statement = statement.where(ImagePromptDraft.status == status.upper())
        count_statement = count_statement.where(ImagePromptDraft.status == status.upper())
    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(200, int(page_size or 50)))
    total = int(db.scalar(count_statement) or 0)
    rows = db.scalars(
        statement.order_by(ImagePromptDraft.updated_at.desc(), ImagePromptDraft.id.desc())
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
    ).all()
    stats_rows = []
    if include_worker_stats:
        stats_statement = select(ImagePromptDraft.created_by, ImagePromptDraft.status, func.count()).group_by(ImagePromptDraft.created_by, ImagePromptDraft.status)
        if created_by is not None:
            stats_statement = stats_statement.where(ImagePromptDraft.created_by == created_by)
        if workflow_id:
            stats_statement = stats_statement.where(ImagePromptDraft.workflow_id == workflow_id)
        stats_rows = db.execute(stats_statement).all()
    user_names = _user_names(db, {
        str(worker_id)
        for worker_id, _draft_status, _count in stats_rows
        if worker_id
    } | {
        str(draft.created_by)
        for draft in rows
        if draft.created_by
    })
    worker_stats: dict[str, dict[str, Any]] = {}
    for worker_id, draft_status, count in stats_rows:
        key = str(worker_id or "")
        entry = worker_stats.setdefault(key, {"workerId": worker_id, "workerName": user_names.get(key, worker_id), "total": 0, "pendingCount": 0, "generatingCount": 0, "readyCount": 0, "failedCount": 0})
        entry["total"] += int(count or 0)
        normalized = str(draft_status or "").upper()
        if normalized == DRAFT_READY:
            entry["readyCount"] += int(count or 0)
        elif normalized == DRAFT_FAILED:
            entry["failedCount"] += int(count or 0)
        elif normalized == DRAFT_GENERATING:
            entry["generatingCount"] += int(count or 0)
        else:
            entry["pendingCount"] += int(count or 0)
    return {"items": _draft_payloads(db, rows, user_names=user_names), "workerStats": list(worker_stats.values()), "page": safe_page, "pageSize": safe_page_size, "total": total}


def update_prompt_draft(
    db: Session,
    draft_id: str,
    *,
    created_by: str,
    positive_prompt: str | None = None,
    negative_prompt: str | None = None,
    requested_frames: int | None = None,
) -> dict[str, Any]:
    draft = _owned_draft(db, draft_id, created_by)
    if positive_prompt is not None:
        draft.positive_prompt = str(positive_prompt).strip() or None
    if negative_prompt is not None:
        draft.negative_prompt = str(negative_prompt).strip() or None
    if requested_frames is not None:
        draft.requested_frames = _positive_int(requested_frames, 81)
    if draft.status in {DRAFT_PENDING, DRAFT_GENERATING, DRAFT_FAILED} and draft.positive_prompt:
        draft.status = DRAFT_READY
        draft.failure_message = None
    db.commit()
    db.refresh(draft)
    return _draft_payload(db, draft)


def retry_prompt_draft(db: Session, draft_id: str, *, created_by: str) -> dict[str, Any]:
    draft = _owned_draft(db, draft_id, created_by)
    draft.status = DRAFT_PENDING
    draft.positive_prompt = None
    draft.failure_message = None
    draft.warnings_json = []
    draft.raw_json = {}
    _refresh_batch_counts(db, draft.prompt_batch_id)
    db.commit()
    db.refresh(draft)
    return _draft_payload(db, draft)


def _owned_draft(db: Session, draft_id: str, created_by: str) -> ImagePromptDraft:
    draft = db.scalar(
        select(ImagePromptDraft).where(ImagePromptDraft.id == draft_id, ImagePromptDraft.created_by == created_by)
    )
    if draft is None:
        raise ValueError("Prompt draft was not found.")
    return draft


def _process_draft(db: Session, draft: ImagePromptDraft) -> dict[str, Any]:
    batch = db.get(PromptGenerationBatch, draft.prompt_batch_id) if draft.prompt_batch_id else None
    if batch is not None:
        batch.status = BATCH_GENERATING
    draft.status = DRAFT_GENERATING
    draft.failure_message = None
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    attempt = PromptGenerationAttempt(
        id=f"grok_attempt_{uuid.uuid4().hex[:16]}",
        draft_id=draft.id,
        attempt_no=_next_attempt_number(db, draft.id),
        status=DRAFT_GENERATING,
        endpoint=f"{get_settings().grok_base_url.rstrip('/')}/responses",
        model=get_settings().grok_model,
        started_at=started_at,
        response_json={},
    )
    db.add(attempt)
    db.commit()
    started_clock = time.monotonic()
    try:
        instruction_text, _ = active_instruction_text(draft.workflow_id)
        asset, asset_path = studio_api_service.get_asset(draft.asset_id)
        result = generate_image_prompt(
            get_settings(),
            asset_path=asset_path,
            mime_type=str(asset.get("mimeType") or ""),
            file_name=str(asset.get("fileName") or asset_path.name),
            image_width=asset.get("imageWidth"),
            image_height=asset.get("imageHeight"),
            instruction_text=instruction_text,
        )
        draft.status = "MANUAL_REQUIRED" if not result.positive_prompt else DRAFT_READY
        draft.positive_prompt = result.positive_prompt
        draft.warnings_json = result.warnings
        draft.raw_json = {"imageType": result.image_type, "response": result.raw_response}
        attempt.status = DRAFT_READY
        attempt.response_json = result.raw_response
        attempt.input_tokens, attempt.output_tokens = _usage_tokens(result.raw_response)
    except (GrokPromptError, GrokPromptInputError, ValueError, KeyError, FileNotFoundError) as exc:
        draft.status = DRAFT_FAILED
        draft.failure_message = str(exc)
        attempt.status = DRAFT_FAILED
        attempt.failure_message = str(exc)
    except Exception as exc:  # Preserve the batch and allow other images to continue.
        draft.status = DRAFT_FAILED
        draft.failure_message = "Grok image prompt generation failed."
        attempt.status = DRAFT_FAILED
        attempt.failure_message = str(exc)
    finally:
        attempt.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        attempt.latency_ms = max(0, round((time.monotonic() - started_clock) * 1000))
        _refresh_batch_counts(db, draft.prompt_batch_id)
        db.commit()
    return _draft_payload(db, draft)


def _refresh_batch_counts(db: Session, batch_id: str | None) -> None:
    if not batch_id:
        return
    # SessionLocal disables autoflush, so persist the just-updated draft state
    # before deriving batch counters from a SELECT.
    db.flush()
    batch = db.get(PromptGenerationBatch, batch_id)
    if batch is None:
        return
    drafts = db.scalars(select(ImagePromptDraft.status).where(ImagePromptDraft.prompt_batch_id == batch_id)).all()
    batch.completed_count = sum(status in {DRAFT_READY, "MANUAL_REQUIRED"} for status in drafts)
    batch.failed_count = sum(status == DRAFT_FAILED for status in drafts)
    if batch.completed_count + batch.failed_count >= batch.total_count:
        batch.status = BATCH_COMPLETED_WITH_ERRORS if batch.failed_count else BATCH_COMPLETED
    else:
        batch.status = BATCH_GENERATING


def _batch_counts_from_drafts(batch: PromptGenerationBatch, drafts: list[ImagePromptDraft]) -> dict[str, Any]:
    total = len(drafts) if drafts else int(batch.total_count or 0)
    completed = sum(draft.status in {DRAFT_READY, "MANUAL_REQUIRED"} for draft in drafts)
    failed = sum(draft.status == DRAFT_FAILED for draft in drafts)
    pending = sum(draft.status == DRAFT_PENDING for draft in drafts)
    if completed + failed >= total and total:
        status = BATCH_COMPLETED_WITH_ERRORS if failed else BATCH_COMPLETED
    elif any(draft.status == DRAFT_GENERATING for draft in drafts) or completed or failed:
        status = BATCH_GENERATING
    else:
        status = BATCH_PENDING
    return {"total": total, "completed": completed, "failed": failed, "pending": pending, "status": status}


def _draft_payloads(
    db: Session,
    drafts: list[ImagePromptDraft],
    *,
    user_names: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    if not drafts:
        return []
    draft_ids = [draft.id for draft in drafts]
    assets = {
        asset.id: asset
        for asset in db.scalars(select(Asset).where(Asset.id.in_({draft.asset_id for draft in drafts}))).all()
    }
    attempts = _latest_attempts_by_draft(db, draft_ids)
    runpod_tasks = _latest_runpod_tasks_by_draft(db, draft_ids)
    names = dict(user_names or {})
    missing_user_ids = {
        str(draft.created_by)
        for draft in drafts
        if draft.created_by and str(draft.created_by) not in names
    }
    if missing_user_ids:
        names.update(_user_names(db, missing_user_ids))
    return [
        _draft_payload_from_related(
            draft,
            asset=assets.get(draft.asset_id),
            attempt=attempts.get(draft.id),
            runpod_task=runpod_tasks.get(draft.id),
            created_by_name=names.get(str(draft.created_by or ""), draft.created_by),
        )
        for draft in drafts
    ]


def _latest_attempts_by_draft(db: Session, draft_ids: list[str]) -> dict[str, PromptGenerationAttempt]:
    latest_attempt_numbers = (
        select(
            PromptGenerationAttempt.draft_id.label("draft_id"),
            func.max(PromptGenerationAttempt.attempt_no).label("attempt_no"),
        )
        .where(PromptGenerationAttempt.draft_id.in_(draft_ids))
        .group_by(PromptGenerationAttempt.draft_id)
        .subquery()
    )
    attempts = db.scalars(
        select(PromptGenerationAttempt).join(
            latest_attempt_numbers,
            (PromptGenerationAttempt.draft_id == latest_attempt_numbers.c.draft_id)
            & (PromptGenerationAttempt.attempt_no == latest_attempt_numbers.c.attempt_no),
        )
    ).all()
    latest: dict[str, PromptGenerationAttempt] = {}
    for attempt in sorted(attempts, key=lambda item: (item.draft_id, item.attempt_no, item.id)):
        latest[attempt.draft_id] = attempt
    return latest


def _latest_runpod_tasks_by_draft(db: Session, draft_ids: list[str]) -> dict[str, WorkflowTask]:
    tasks = db.scalars(
        select(WorkflowTask)
        .where(WorkflowTask.prompt_draft_id.in_(draft_ids), WorkflowTask.deleted_at.is_(None))
        .order_by(WorkflowTask.prompt_draft_id.asc(), WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
    ).all()
    latest: dict[str, WorkflowTask] = {}
    for task in tasks:
        draft_id = str(task.prompt_draft_id or "")
        if draft_id and draft_id not in latest:
            latest[draft_id] = task
    return latest


def _draft_payload(db: Session, draft: ImagePromptDraft) -> dict[str, Any]:
    return _draft_payloads(db, [draft])[0]


def _draft_payload_from_related(
    draft: ImagePromptDraft,
    *,
    asset: Asset | None,
    attempt: PromptGenerationAttempt | None,
    runpod_task: WorkflowTask | None,
    created_by_name: str | None,
) -> dict[str, Any]:
    return {
        "draftId": draft.id,
        "assetId": draft.asset_id,
        "workflowId": draft.workflow_id,
        "promptBatchId": draft.prompt_batch_id,
        "slotIndex": draft.slot_index,
        "provider": draft.provider,
        "model": draft.model,
        "instructionVersion": draft.instruction_version,
        "createdBy": draft.created_by,
        "createdByName": created_by_name,
        "createdAt": draft.created_at.isoformat() if draft.created_at else None,
        "updatedAt": draft.updated_at.isoformat() if draft.updated_at else None,
        "requestedFrames": draft.requested_frames,
        "status": draft.status,
        "positivePrompt": draft.positive_prompt,
        "negativePrompt": draft.negative_prompt,
        "error": draft.failure_message,
        "asset": {
            "assetId": asset.id,
            "fileName": asset.file_name,
            "mimeType": asset.mime_type,
            "sizeBytes": asset.size_bytes,
            "imageWidth": asset.image_width,
            "imageHeight": asset.image_height,
        } if asset else None,
        "runpodTaskId": runpod_task.id if runpod_task else None,
        "runpodStatus": runpod_task.status if runpod_task else None,
        "grokResponse": {
            "endpoint": attempt.endpoint if attempt else None,
            "model": attempt.model if attempt else None,
            "latencyMs": attempt.latency_ms if attempt else None,
            "inputTokens": attempt.input_tokens if attempt else None,
            "outputTokens": attempt.output_tokens if attempt else None,
        },
    }


def _user_names(db: Session, user_ids: set[str]) -> dict[str, str | None]:
    if not user_ids:
        return {}
    users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
    names = {user.id: user.name for user in users}
    for user_id in user_ids:
        names.setdefault(user_id, user_id)
    return names


def _user_name(db: Session, user_id: str | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.name if user else user_id


def _next_attempt_number(db: Session, draft_id: str) -> int:
    attempts = db.scalars(select(PromptGenerationAttempt.attempt_no).where(PromptGenerationAttempt.draft_id == draft_id)).all()
    return max(attempts, default=0) + 1


def _usage_tokens(response: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None, None
    return _optional_int(usage.get("input_tokens", usage.get("prompt_tokens"))), _optional_int(usage.get("output_tokens", usage.get("completion_tokens")))


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, fallback: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return fallback
