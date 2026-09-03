from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import event, inspect

from backend.app.core.timezone_utils import now_seoul_naive
from backend.app.db.models import Asset, ImagePromptDraft, PromptGenerationAttempt, PromptGenerationBatch, User, WorkflowTask
from backend.app.services import prompt_batch_service as service
from backend.app.services.grok_image_prompt_service import GrokPromptError, GrokImagePromptResult


def _asset(asset_id: str) -> Asset:
    return Asset(
        id=asset_id,
        asset_type="input",
        file_name=f"{asset_id}.png",
        mime_type="image/png",
        size_bytes=1,
        image_width=900,
        image_height=1200,
        storage_key=f"inputs/{asset_id}.png",
        metadata_json={},
    )


def test_batch_persists_items_and_grok_attempt_metadata(db_session, monkeypatch, tmp_path):
    db_session.add_all([_asset("asset_1"), _asset("asset_2")])
    db_session.commit()
    monkeypatch.setattr(service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(service.studio_api_service, "get_asset", lambda asset_id: (
        {"fileName": f"{asset_id}.png", "mimeType": "image/png", "imageWidth": 900, "imageHeight": 1200},
        Path(tmp_path) / f"{asset_id}.png",
    ))
    for asset_id in ("asset_1", "asset_2"):
        (Path(tmp_path) / f"{asset_id}.png").write_bytes(b"x")
    outcomes = iter([
        GrokImagePromptResult("A person moves gently, smooth movement.", "static_character", [], {"usage": {"input_tokens": 12, "output_tokens": 8}}),
        GrokPromptError("upstream unavailable"),
    ])

    def fake_generate(*_args, **_kwargs):
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(service, "generate_image_prompt", fake_generate)
    batch = service.create_prompt_generation_batch(
        db_session,
        {
            "workflowId": "1-images.json",
            "items": [
                {"assetId": "asset_1", "slotIndex": 1, "requestedFrames": 81},
                {"assetId": "asset_2", "slotIndex": 2, "requestedFrames": 49},
            ],
        },
        created_by="dobedub",
    )

    result = service.process_prompt_generation_batch(db_session, batch["id"])

    assert result["status"] == service.BATCH_COMPLETED_WITH_ERRORS
    assert result["completedCount"] == 1
    assert result["failedCount"] == 1
    assert result["items"][0]["requestedFrames"] == 81
    assert result["items"][0]["grokResponse"]["inputTokens"] == 12
    assert result["items"][1]["positivePrompt"] is None
    assert db_session.query(PromptGenerationAttempt).count() == 2


def test_batch_requires_configured_workflow_instruction(db_session, monkeypatch):
    monkeypatch.setattr(service, "active_instruction_text", lambda _: (_ for _ in ()).throw(ValueError("활성 프롬프트 지시문이 없습니다")))

    try:
        service.create_prompt_generation_batch(
            db_session,
            {"workflowId": "unconfigured.json", "items": [{"assetId": "asset_1"}]},
            created_by="dobedub",
        )
    except ValueError as exc:
        assert "활성 프롬프트 지시문" in str(exc)
    else:
        raise AssertionError("configured workflow instructions should be required")


def test_active_prompt_generation_batches_are_user_scoped_and_newest_first(db_session):
    db_session.add_all([
        PromptGenerationBatch(
            id="pgb_worker_a_old",
            workflow_id="1-images.json",
            status=service.BATCH_PENDING,
            total_count=1,
            created_by="worker_a",
        ),
        PromptGenerationBatch(
            id="pgb_worker_a_new",
            workflow_id="Pickme_Workflow.json",
            status=service.BATCH_GENERATING,
            total_count=2,
            created_by="worker_a",
        ),
        PromptGenerationBatch(
            id="pgb_worker_a_complete",
            workflow_id="1-images.json",
            status=service.BATCH_COMPLETED,
            total_count=1,
            created_by="worker_a",
        ),
        PromptGenerationBatch(
            id="pgb_worker_b",
            workflow_id="1-images.json",
            status=service.BATCH_PENDING,
            total_count=1,
            created_by="worker_b",
        ),
    ])
    db_session.commit()

    batches = service.list_active_prompt_generation_batches(db_session, created_by="worker_a")

    assert [batch["id"] for batch in batches] == ["pgb_worker_a_new", "pgb_worker_a_old"]


def test_prompt_generation_batch_payload_counts_current_draft_statuses(db_session):
    db_session.add_all([
        _asset("asset_batch_ready_1"),
        _asset("asset_batch_ready_2"),
        PromptGenerationBatch(
            id="pgb_stale_counts",
            workflow_id="1-images.json",
            status=service.BATCH_GENERATING,
            total_count=2,
            completed_count=0,
            failed_count=0,
            created_by="worker_a",
        ),
        ImagePromptDraft(
            id="draft_batch_ready_1",
            asset_id="asset_batch_ready_1",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_READY,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            positive_prompt="ready 1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_stale_counts",
            created_by="worker_a",
        ),
        ImagePromptDraft(
            id="draft_batch_ready_2",
            asset_id="asset_batch_ready_2",
            workflow_id="1-images.json",
            slot_index=2,
            status=service.DRAFT_READY,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            positive_prompt="ready 2",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_stale_counts",
            created_by="worker_a",
        ),
    ])
    db_session.commit()

    payload = service.prompt_generation_batch_payload(db_session, "pgb_stale_counts")
    active_batches = service.list_active_prompt_generation_batches(db_session, created_by="worker_a")

    assert payload["status"] == service.BATCH_COMPLETED
    assert payload["completedCount"] == 2
    assert payload["failedCount"] == 0
    assert payload["pendingCount"] == 0
    assert active_batches == []


def test_ready_drafts_can_be_listed_edited_and_retried(db_session, monkeypatch):
    db_session.add(_asset("asset_edit"))
    db_session.add(
        ImagePromptDraft(
            id="grok_draft_edit",
            asset_id="asset_edit",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_READY,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            positive_prompt="original prompt",
            negative_prompt="original negative",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            created_by="dobedub",
        )
    )
    db_session.commit()

    listed = service.list_prompt_drafts(db_session, created_by="dobedub", workflow_id="1-images.json")
    assert [item["draftId"] for item in listed["items"]] == ["grok_draft_edit"]

    updated = service.update_prompt_draft(
        db_session,
        "grok_draft_edit",
        created_by="dobedub",
        positive_prompt="edited prompt",
        negative_prompt="edited negative",
        requested_frames=49,
    )
    assert updated["positivePrompt"] == "edited prompt"
    assert updated["requestedFrames"] == 49

    retried = service.retry_prompt_draft(db_session, "grok_draft_edit", created_by="dobedub")
    assert retried["status"] == service.DRAFT_PENDING
    assert retried["positivePrompt"] is None


def test_prompt_history_payload_includes_asset_and_linked_runpod_task(db_session):
    db_session.add(_asset("asset_history"))
    db_session.add(ImagePromptDraft(
        id="grok_draft_history",
        asset_id="asset_history",
        workflow_id="1-images.json",
        slot_index=1,
        status=service.DRAFT_READY,
        provider="grok",
        model="grok-test",
        instruction_version="wf@1",
        positive_prompt="a woman turns toward camera",
        requested_frames=81,
        warnings_json=[],
        raw_json={},
        created_by="dobedub",
    ))
    db_session.add(WorkflowTask(
        id="task_from_draft",
        workflow_id="1-images.json",
        status="COMPLETED",
        positive_prompts=["a woman turns toward camera"],
        negative_prompts=[],
        config_json={},
        wan_node_config={},
        patch_summary={},
        payload_json={},
        runpod_submit_json={},
        runpod_status_json={},
        prompt_draft_id="grok_draft_history",
    ))
    db_session.commit()

    payload = service.list_prompt_drafts(db_session, created_by="dobedub")

    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["asset"]["fileName"] == "asset_history.png"
    assert item["asset"]["imageWidth"] == 900
    assert item["runpodTaskId"] == "task_from_draft"
    assert item["runpodStatus"] == "COMPLETED"
    assert item["createdBy"] == "dobedub"
    assert item["createdAt"]


def test_management_draft_listing_includes_worker_names_and_statistics(db_session):
    db_session.add_all([
        User(id="worker_a", name="작업자 A", role="OPERATOR"),
        User(id="worker_b", name="작업자 B", role="OPERATOR"),
        _asset("asset_worker_a"),
        _asset("asset_worker_b"),
        ImagePromptDraft(
            id="draft_worker_a", asset_id="asset_worker_a", workflow_id="1-images.json", slot_index=1,
            status=service.DRAFT_READY, provider="grok", model="grok-test", instruction_version="wf@1",
            positive_prompt="ready", requested_frames=81, warnings_json=[], raw_json={}, created_by="worker_a",
        ),
        ImagePromptDraft(
            id="draft_worker_b", asset_id="asset_worker_b", workflow_id="Pickme_Workflow.json", slot_index=1,
            status=service.DRAFT_FAILED, provider="grok", model="grok-test", instruction_version="wf@1",
            positive_prompt=None, requested_frames=81, warnings_json=[], raw_json={}, created_by="worker_b",
        ),
    ])
    db_session.commit()

    payload = service.list_prompt_drafts(db_session, created_by=None)

    assert {item["createdByName"] for item in payload["items"]} == {"작업자 A", "작업자 B"}
    stats = {item["workerId"]: item for item in payload["workerStats"]}
    assert stats["worker_a"]["readyCount"] == 1
    assert stats["worker_b"]["failedCount"] == 1


def test_prompt_history_listing_batches_related_records_instead_of_querying_per_row(db_session):
    base_time = now_seoul_naive()
    for index in range(8):
        worker_id = f"worker_history_{index}"
        asset_id = f"asset_history_{index}"
        draft_id = f"draft_history_{index}"
        db_session.add(User(id=worker_id, name=f"작업자 {index}", role="OPERATOR"))
        db_session.add(_asset(asset_id))
        db_session.add(ImagePromptDraft(
            id=draft_id,
            asset_id=asset_id,
            workflow_id="1-images.json",
            slot_index=index + 1,
            status=service.DRAFT_READY,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            positive_prompt=f"ready prompt {index}",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            created_by=worker_id,
            updated_at=base_time + timedelta(seconds=index),
        ))
        db_session.add(PromptGenerationAttempt(
            id=f"attempt_old_{index}",
            draft_id=draft_id,
            attempt_no=1,
            status=service.DRAFT_FAILED,
            endpoint="https://api.x.ai/v1/responses",
            model="grok-test",
            response_json={},
        ))
        db_session.add(PromptGenerationAttempt(
            id=f"attempt_new_{index}",
            draft_id=draft_id,
            attempt_no=2,
            status=service.DRAFT_READY,
            endpoint="https://api.x.ai/v1/responses",
            model="grok-test",
            latency_ms=100 + index,
            input_tokens=10 + index,
            output_tokens=20 + index,
            response_json={},
        ))
        db_session.add(WorkflowTask(
            id=f"task_old_{index}",
            workflow_id="1-images.json",
            status="FAILED",
            positive_prompts=[],
            negative_prompts=[],
            config_json={},
            wan_node_config={},
            patch_summary={},
            payload_json={},
            runpod_submit_json={},
            runpod_status_json={},
            prompt_draft_id=draft_id,
            created_at=base_time + timedelta(seconds=index),
        ))
        db_session.add(WorkflowTask(
            id=f"task_new_{index}",
            workflow_id="1-images.json",
            status="COMPLETED",
            positive_prompts=[],
            negative_prompts=[],
            config_json={},
            wan_node_config={},
            patch_summary={},
            payload_json={},
            runpod_submit_json={},
            runpod_status_json={},
            prompt_draft_id=draft_id,
            created_at=base_time + timedelta(minutes=1, seconds=index),
        ))
    db_session.commit()

    statements: list[str] = []

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", before_cursor_execute)
    try:
        payload = service.list_prompt_drafts(db_session, created_by=None, page_size=8)
    finally:
        event.remove(bind, "before_cursor_execute", before_cursor_execute)

    assert payload["total"] == 8
    assert len(payload["items"]) == 8
    assert payload["items"][0]["runpodTaskId"] == "task_new_7"
    assert payload["items"][0]["grokResponse"]["inputTokens"] == 17
    assert len(statements) <= 8


def test_prompt_history_tables_have_mysql_friendly_lookup_indexes(db_session):
    indexes = {
        table_name: {index["name"] for index in inspect(db_session.get_bind()).get_indexes(table_name)}
        for table_name in ("image_prompt_drafts", "prompt_generation_attempts", "workflow_tasks")
    }

    assert "ix_image_prompt_drafts_owner_workflow_status_updated" in indexes["image_prompt_drafts"]
    assert "ix_image_prompt_drafts_owner_updated_id" in indexes["image_prompt_drafts"]
    assert "ix_image_prompt_drafts_workflow_status_updated" in indexes["image_prompt_drafts"]
    assert "ix_image_prompt_drafts_workflow_updated_id" in indexes["image_prompt_drafts"]
    assert "ix_image_prompt_drafts_workflow_owner_status" in indexes["image_prompt_drafts"]
    assert "ix_image_prompt_drafts_updated_id" in indexes["image_prompt_drafts"]
    assert "ix_prompt_generation_attempts_draft_attempt_latest" in indexes["prompt_generation_attempts"]
    assert "ix_workflow_tasks_prompt_draft_latest" in indexes["workflow_tasks"]
