"""Manual failed-prompt repair followed by durable RunPod queue creation."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import BatchJob, ImagePromptDraft
from backend.app.services import studio_api_service
from backend.app.services.prompt_batch_service import repair_failed_prompt_draft


def repair_and_submit_prompt(
    db: Session,
    draft_id: str,
    *,
    actor: dict[str, object],
    can_manage: bool,
    positive_prompt: str,
) -> dict[str, Any]:
    draft_payload = repair_failed_prompt_draft(
        db,
        draft_id,
        actor_id=str(actor.get("id") or ""),
        can_manage=can_manage,
        positive_prompt=positive_prompt,
    )
    draft = db.get(ImagePromptDraft, draft_id)
    if draft is None:  # Defensive: repair has already established existence.
        raise ValueError("프롬프트 초안을 찾을 수 없습니다.")
    item: dict[str, object] = {
        "promptDraftId": draft.id,
        "workflowId": draft.workflow_id,
        "requestedFrames": int(draft.requested_frames or 81),
        "resolutionTier": "sd",
    }
    if draft.batch_job_id:
        batch = db.get(BatchJob, draft.batch_job_id)
        if batch is None or str(batch.status or "").upper() != "INCOMPLETE":
            return _result(draft_payload, error="취소되었거나 완료된 Batch 작업에는 제출할 수 없습니다.")
        item["resolutionTier"] = str(batch.resolution_tier or "sd")
        item["requestedFrames"] = int(batch.requested_frames or draft.requested_frames or 81)
    try:
        response = studio_api_service.create_runpod_request_batch(
            {"workerId": draft.created_by, "items": [item]},
            user=actor,
            batch_job_id=draft.batch_job_id,
        )
        queued_item = next((entry for entry in response.get("items", []) if entry.get("promptDraftId") == draft.id), None)
        if not queued_item or not queued_item.get("taskId"):
            return _result(draft_payload, error="RunPod 로컬 대기 작업을 만들지 못했습니다.")
        return {
            **_result(draft_payload),
            "runpodQueued": True,
            "runpodTaskId": queued_item.get("taskId"),
            "runpodStatus": queued_item.get("status") or "PENDING_SUBMIT",
        }
    except Exception as exc:  # Prompt repair is intentionally retained for retry/audit.
        return _result(draft_payload, error=str(exc))


def _result(draft: dict[str, Any], *, error: str | None = None) -> dict[str, Any]:
    return {
        "draft": draft,
        "promptSaved": True,
        "runpodQueued": False,
        "runpodTaskId": None,
        "runpodStatus": None,
        "submissionError": error,
    }
