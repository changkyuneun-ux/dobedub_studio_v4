from __future__ import annotations

from backend.app.db.models import Asset, ImagePromptDraft, User
from backend.app.services import prompt_recovery_service as service


def _failed_draft(db_session) -> ImagePromptDraft:
    db_session.add(User(
        id="recovery-worker", name="Recovery Worker", role="OPERATOR",
        permissions_json=["prompts:build", "jobs:run"], is_active=True,
    ))
    db_session.add(Asset(
        id="recovery-asset", asset_type="input", file_name="source.png", mime_type="image/png",
        size_bytes=1, image_width=720, image_height=1280, storage_key="inputs/source.png", metadata_json={},
    ))
    draft = ImagePromptDraft(
        id="recovery-draft", asset_id="recovery-asset", workflow_id="1-images.json", slot_index=1,
        status="FAILED", provider="grok", model="grok-test", instruction_version="wf@1",
        requested_frames=81, warnings_json=["manual_input_required"], raw_json={}, created_by="recovery-worker",
    )
    db_session.add(draft)
    db_session.commit()
    return draft


def test_manager_repair_submits_as_original_worker(db_session, monkeypatch):
    draft = _failed_draft(db_session)
    captured = {}

    def fake_create(payload, *, user, batch_job_id=None):
        captured.update(payload=payload, user=user, batch_job_id=batch_job_id)
        return {"items": [{"promptDraftId": draft.id, "taskId": "task-queued", "status": "PENDING_SUBMIT"}]}

    monkeypatch.setattr(service.studio_api_service, "create_runpod_request_batch", fake_create)
    result = service.repair_and_submit_prompt(
        db_session, draft.id,
        actor={"id": "manager", "name": "Manager", "permissions": ["jobs:manage"]},
        can_manage=True,
        positive_prompt="A repaired prompt with subtle movement.",
    )

    assert result["promptSaved"] is True
    assert result["runpodQueued"] is True
    assert result["runpodTaskId"] == "task-queued"
    assert captured["payload"]["workerId"] == "recovery-worker"
    assert db_session.get(ImagePromptDraft, draft.id).created_by == "recovery-worker"


def test_queue_failure_preserves_repaired_prompt(db_session, monkeypatch):
    draft = _failed_draft(db_session)
    monkeypatch.setattr(
        service.studio_api_service,
        "create_runpod_request_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )

    result = service.repair_and_submit_prompt(
        db_session, draft.id,
        actor={"id": "recovery-worker", "name": "Worker", "permissions": ["jobs:run"]},
        can_manage=False,
        positive_prompt="Keep this repaired prompt.",
    )

    repaired = db_session.get(ImagePromptDraft, draft.id)
    assert result["promptSaved"] is True
    assert result["runpodQueued"] is False
    assert result["submissionError"] == "queue unavailable"
    assert repaired.status == "READY"
    assert repaired.positive_prompt == "Keep this repaired prompt."
