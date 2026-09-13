"""Recover request items left behind before WorkflowTask creation."""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.db.models import Asset, ImagePromptDraft, RunpodRequestBatch, RunpodRequestItem, User, WorkflowTask
from backend.app.services import request_item_recovery_service


def test_stale_orphan_request_item_gets_materialized(db_session, monkeypatch):
    db_session.add(User(id="operator_1", name="Operator", role="OPERATOR"))
    db_session.add(Asset(
        id="asset_1",
        asset_type="input",
        file_name="image1.jpg",
        mime_type="image/jpeg",
        size_bytes=1,
        storage_key="inputs/image1.jpg",
        metadata_json={},
    ))
    db_session.add(ImagePromptDraft(
        id="draft_1",
        asset_id="asset_1",
        workflow_id="Blowbang1.json",
        slot_index=1,
        status="READY",
        provider="grok",
        model="grok-test",
        instruction_version="wf@1",
        positive_prompt="ok",
        requested_frames=81,
        warnings_json=[],
        raw_json={},
        created_by="operator_1",
    ))
    db_session.add(RunpodRequestBatch(
        id="rpb_orphan",
        workflow_id="Blowbang1.json",
        requested_count=1,
        status="QUEUED",
        created_by="operator_1",
    ))
    db_session.add(RunpodRequestItem(
        id="rpi_orphan",
        request_batch_id="rpb_orphan",
        sequence_no=1,
        prompt_draft_id="draft_1",
        asset_id="asset_1",
        workflow_id="Blowbang1.json",
        positive_prompt="ok",
        requested_frames=81,
        status="PENDING_SUBMIT",
        created_at=datetime.utcnow() - timedelta(seconds=request_item_recovery_service.STALE_ORPHAN_ITEM_SECONDS + 60),
    ))
    db_session.commit()

    def fake_create_job(payload, *, user):
        task = WorkflowTask(
            id="task_recovered",
            workflow_id=payload["workflowId"],
            status="PENDING_SUBMIT",
            user_id=user["id"],
            prompt_draft_id=payload["promptDraftId"],
            request_batch_id=payload["requestBatchId"],
            request_item_id=payload["requestItemId"],
        )
        db_session.add(task)
        db_session.commit()
        return {"taskId": task.id}

    monkeypatch.setattr("backend.app.services.studio_api_service.create_job", fake_create_job)

    assert request_item_recovery_service.materialize_orphan_request_items() == {"materialized": 1, "failed": 0}
    db_session.expire_all()
    item = db_session.get(RunpodRequestItem, "rpi_orphan")
    assert item.task_id == "task_recovered"
    assert item.materialization_claimed_at is None
