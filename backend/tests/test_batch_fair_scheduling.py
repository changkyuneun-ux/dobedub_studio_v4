"""Batch work must not starve interactive prompt or RunPod queues."""
from __future__ import annotations

from datetime import timedelta
import uuid

from backend.app.core.timezone_utils import now_seoul_naive
from backend.app.db.models import Asset, ImagePromptDraft, User, WorkflowTask
from backend.app.services.prompt_batch_service import process_next_prompt_generation_draft
from backend.app.services.task_tracking_service import claim_next_pending_submission


def _seed_user_and_asset(db_session) -> None:
    db_session.add(User(id="operator_1", name="Operator", role="OPERATOR"))
    db_session.add(Asset(
        id="asset_1",
        asset_type="input",
        file_name="asset_1.png",
        mime_type="image/png",
        size_bytes=1,
        storage_key="inputs/asset_1.png",
        metadata_json={},
    ))
    db_session.commit()


def _draft(db_session, *, created_at, batch_job_id: str | None):
    draft = ImagePromptDraft(
        id=f"grok_draft_{uuid.uuid4().hex[:16]}",
        asset_id="asset_1",
        workflow_id="Blowbang1.json",
        slot_index=1,
        status="PENDING",
        provider="grok",
        model="grok-test",
        instruction_version="wf@1",
        warnings_json=[],
        raw_json={},
        batch_job_id=batch_job_id,
        created_by="operator_1",
        created_at=created_at,
    )
    db_session.add(draft)
    return draft


def test_interactive_draft_is_picked_before_older_batch_drafts(db_session, monkeypatch):
    _seed_user_and_asset(db_session)
    now = now_seoul_naive()
    for offset in range(3):
        _draft(db_session, created_at=now - timedelta(minutes=10) + timedelta(seconds=offset), batch_job_id="batch_older")
    interactive = _draft(db_session, created_at=now, batch_job_id=None)
    db_session.commit()

    picked: list[str] = []
    monkeypatch.setattr(
        "backend.app.services.prompt_batch_service._process_draft",
        lambda _db, draft: picked.append(draft.id) or {"draftId": draft.id},
    )

    process_next_prompt_generation_draft()

    assert picked == [interactive.id]


def test_interactive_task_is_dispatched_before_older_batch_tasks(db_session):
    _seed_user_and_asset(db_session)
    now = now_seoul_naive()
    for offset in range(3):
        db_session.add(WorkflowTask(
            id=f"task_{uuid.uuid4().hex[:16]}",
            workflow_id="Blowbang1.json",
            status="PENDING_SUBMIT",
            user_id="operator_1",
            batch_job_id="batch_older",
            created_at=now - timedelta(minutes=10) + timedelta(seconds=offset),
        ))
    interactive_id = f"task_{uuid.uuid4().hex[:16]}"
    db_session.add(WorkflowTask(
        id=interactive_id,
        workflow_id="Blowbang1.json",
        status="PENDING_SUBMIT",
        user_id="operator_1",
        batch_job_id=None,
        created_at=now,
    ))
    db_session.commit()

    claimed = claim_next_pending_submission()

    assert claimed is not None
    assert claimed["taskId"] == interactive_id
