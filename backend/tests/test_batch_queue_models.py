from __future__ import annotations

from backend.app.db.models import (
    Asset,
    ImagePromptDraft,
    PromptGenerationAttempt,
    PromptGenerationBatch,
    WorkflowTask,
)


def _source_asset() -> Asset:
    return Asset(
        id="asset_prompt_1",
        asset_type="input_image",
        file_name="source.png",
        mime_type="image/png",
        size_bytes=1,
        storage_backend="local",
        storage_key="inputs/source.png",
    )


def test_prompt_draft_records_batch_negative_prompt_and_frames(db_session):
    batch = PromptGenerationBatch(
        id="pgb_1",
        workflow_id="1-images.json",
        status="WAITING",
        created_by=None,
    )
    draft = ImagePromptDraft(
        id="prm_1",
        asset_id="asset_prompt_1",
        workflow_id="1-images.json",
        slot_index=1,
        status="GENERATING",
        provider="grok",
        model="grok-test",
        instruction_version="1-images.json@1",
        warnings_json=[],
        raw_json={},
        prompt_batch_id="pgb_1",
        negative_prompt="low quality",
        requested_frames=81,
    )
    db_session.add_all([_source_asset(), batch, draft])
    db_session.commit()

    stored = db_session.get(ImagePromptDraft, "prm_1")
    assert stored.requested_frames == 81
    assert stored.negative_prompt == "low quality"
    assert stored.prompt_batch_id == "pgb_1"


def test_attempt_records_grok_telemetry(db_session):
    attempt = PromptGenerationAttempt(
        id="pga_1",
        draft_id="prm_missing_by_design",
        attempt_no=1,
        status="COMPLETED",
        endpoint="https://api.x.ai/v1/responses",
        model="grok-test",
        latency_ms=1234,
        input_tokens=120,
        output_tokens=45,
        response_json={"ok": True},
    )
    db_session.add(attempt)
    db_session.commit()

    assert db_session.get(PromptGenerationAttempt, "pga_1").input_tokens == 120


def test_task_dispatch_columns_and_index_exist(db_session):
    task = WorkflowTask(
        id="task_dispatch_1",
        workflow_id="1-images.json",
        status="PENDING_SUBMIT",
        prompt_draft_id="prm_1",
        dispatch_attempts=0,
    )
    db_session.add(task)
    db_session.commit()

    stored = db_session.get(WorkflowTask, "task_dispatch_1")
    assert stored.dispatch_claimed_at is None
    assert stored.next_dispatch_at is None
    assert stored.last_dispatch_error is None
    assert "ix_workflow_tasks_dispatch" in {index.name for index in WorkflowTask.__table__.indexes}
