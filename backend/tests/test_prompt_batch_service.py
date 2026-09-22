from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path

from sqlalchemy import event, inspect, select

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
            "workflowId": "1-images_81.json",
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


def test_batch_grok_generation_reads_s3_input_asset_bytes(db_session, monkeypatch):
    db_session.add(Asset(
        id="asset_s3_batch_prompt",
        asset_type="input_image",
        file_name="scene.png",
        mime_type="image/png",
        size_bytes=8,
        image_width=900,
        image_height=1200,
        storage_backend="s3",
        storage_key="local/uploads/asset_s3_batch_prompt/scene.png",
        metadata_json={},
    ))
    db_session.commit()
    monkeypatch.setattr(service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    calls = []

    class FakeS3Storage:
        def open_read(self, storage_key):
            assert storage_key == "local/uploads/asset_s3_batch_prompt/scene.png"
            return io.BytesIO(b"png-data")

    def fake_generate(*_args, **kwargs):
        calls.append(kwargs)
        return GrokImagePromptResult(
            "A character moves gently, locked camera, smooth movement.",
            "static_character",
            [],
            {"usage": {"input_tokens": 12, "output_tokens": 8}},
        )

    monkeypatch.setattr(service.studio_api_service, "s3_asset_storage", lambda: FakeS3Storage())
    monkeypatch.setattr(service, "generate_image_prompt", fake_generate)
    batch = service.create_prompt_generation_batch(
        db_session,
        {"workflowId": "1-images.json", "items": [{"assetId": "asset_s3_batch_prompt", "slotIndex": 1}]},
        created_by="dobedub",
    )

    result = service.process_prompt_generation_batch(db_session, batch["id"])

    assert result["status"] == service.BATCH_COMPLETED
    assert result["completedCount"] == 1
    assert calls[0]["asset_bytes"] == b"png-data"
    assert calls[0]["file_name"] == "scene.png"


def test_batch_stops_grok_calls_after_provider_auth_failure(db_session, monkeypatch, tmp_path):
    db_session.add_all([_asset("asset_auth_1"), _asset("asset_auth_2"), _asset("asset_auth_3")])
    db_session.commit()
    monkeypatch.setattr(service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    for asset_id in ("asset_auth_1", "asset_auth_2", "asset_auth_3"):
        (Path(tmp_path) / f"{asset_id}.png").write_bytes(b"x")
    monkeypatch.setattr(service.studio_api_service, "get_asset", lambda asset_id: (
        {"fileName": f"{asset_id}.png", "mimeType": "image/png", "imageWidth": 900, "imageHeight": 1200},
        Path(tmp_path) / f"{asset_id}.png",
    ))
    calls = []

    def fake_generate(*_args, **_kwargs):
        calls.append(1)
        raise GrokPromptError("Grok API HTTP 403: permission-denied", status_code=403)

    monkeypatch.setattr(service, "generate_image_prompt", fake_generate)
    batch = service.create_prompt_generation_batch(
        db_session,
        {
            "workflowId": "1-images.json",
            "items": [
                {"assetId": "asset_auth_1", "slotIndex": 1},
                {"assetId": "asset_auth_2", "slotIndex": 2},
                {"assetId": "asset_auth_3", "slotIndex": 3},
            ],
        },
        created_by="dobedub",
    )

    result = service.process_prompt_generation_batch(db_session, batch["id"])

    assert len(calls) == 1
    assert result["status"] == service.BATCH_COMPLETED_WITH_ERRORS
    assert result["completedCount"] == 0
    assert result["failedCount"] == 3
    assert {item["status"] for item in result["items"]} == {service.DRAFT_FAILED}
    assert all(item["error"] == "Grok API HTTP 403: permission-denied" for item in result["items"])


def test_empty_grok_prompt_counts_as_failed_not_completed(db_session, monkeypatch, tmp_path):
    db_session.add(_asset("asset_manual"))
    db_session.commit()
    monkeypatch.setattr(service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    image_path = Path(tmp_path) / "asset_manual.png"
    image_path.write_bytes(b"x")
    monkeypatch.setattr(service.studio_api_service, "get_asset", lambda _asset_id: (
        {"fileName": "asset_manual.png", "mimeType": "image/png", "imageWidth": 900, "imageHeight": 1200},
        image_path,
    ))
    monkeypatch.setattr(
        service,
        "generate_image_prompt",
        lambda *_args, **_kwargs: GrokImagePromptResult(
            "",
            "indoor_background",
            ["manual_input_required"],
            {"positivePrompt": "", "imageType": "indoor_background"},
        ),
    )
    batch = service.create_prompt_generation_batch(
        db_session,
        {"workflowId": "1-images.json", "items": [{"assetId": "asset_manual", "slotIndex": 1}]},
        created_by="dobedub",
    )

    result = service.process_prompt_generation_batch(db_session, batch["id"])
    attempt = db_session.scalar(
        select(PromptGenerationAttempt).where(PromptGenerationAttempt.draft_id == result["items"][0]["draftId"])
    )

    assert result["status"] == service.BATCH_COMPLETED_WITH_ERRORS
    assert result["completedCount"] == 0
    assert result["failedCount"] == 1
    assert result["items"][0]["status"] == service.DRAFT_FAILED
    assert "수동 입력" in result["items"][0]["error"]
    assert attempt.status == service.DRAFT_FAILED
    assert "수동 입력" in attempt.failure_message


def test_batch_uses_workflow_default_negative_prompt_when_request_is_blank(db_session, monkeypatch):
    db_session.add(_asset("asset_default_negative"))
    db_session.commit()
    monkeypatch.setattr(service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))

    result = service.create_prompt_generation_batch(
        db_session,
        {
            "workflowId": "1-images_81.json",
            "items": [
                {"assetId": "asset_default_negative", "slotIndex": 1, "negativePrompt": "   "},
            ],
        },
        created_by="dobedub",
    )

    draft = db_session.get(ImagePromptDraft, result["items"][0]["draftId"])
    assert draft.negative_prompt
    assert "photorealistic" in draft.negative_prompt


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
        _asset("asset_worker_a_old"),
        _asset("asset_worker_a_new"),
        _asset("asset_worker_b"),
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
        ImagePromptDraft(
            id="draft_worker_a_old",
            asset_id="asset_worker_a_old",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_PENDING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_worker_a_old",
            created_by="worker_a",
        ),
        ImagePromptDraft(
            id="draft_worker_a_new",
            asset_id="asset_worker_a_new",
            workflow_id="Pickme_Workflow.json",
            slot_index=1,
            status=service.DRAFT_GENERATING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_worker_a_new",
            created_by="worker_a",
        ),
        ImagePromptDraft(
            id="draft_worker_b",
            asset_id="asset_worker_b",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_PENDING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_worker_b",
            created_by="worker_b",
        ),
    ])
    db_session.commit()

    batches = service.list_active_prompt_generation_batches(db_session, created_by="worker_a")

    assert [batch["id"] for batch in batches] == ["pgb_worker_a_new", "pgb_worker_a_old"]


def test_active_prompt_generation_batches_can_include_every_worker_for_managers(db_session):
    db_session.add_all([
        _asset("asset_worker_a_active"),
        _asset("asset_worker_b_active"),
        PromptGenerationBatch(
            id="pgb_worker_a_active",
            workflow_id="1-images.json",
            status=service.BATCH_PENDING,
            total_count=1,
            created_by="worker_a",
        ),
        PromptGenerationBatch(
            id="pgb_worker_b_active",
            workflow_id="Pickme_Workflow.json",
            status=service.BATCH_GENERATING,
            total_count=1,
            created_by="worker_b",
        ),
        ImagePromptDraft(
            id="draft_worker_a_active",
            asset_id="asset_worker_a_active",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_PENDING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_worker_a_active",
            created_by="worker_a",
        ),
        ImagePromptDraft(
            id="draft_worker_b_active",
            asset_id="asset_worker_b_active",
            workflow_id="Pickme_Workflow.json",
            slot_index=1,
            status=service.DRAFT_GENERATING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_worker_b_active",
            created_by="worker_b",
        ),
    ])
    db_session.commit()

    batches = service.list_active_prompt_generation_batches(db_session, created_by=None)

    assert [batch["id"] for batch in batches] == ["pgb_worker_b_active", "pgb_worker_a_active"]


def test_prompt_generation_management_excludes_folder_batch_batches(db_session):
    db_session.add_all([
        _asset("asset_manual_active"),
        _asset("asset_folder_batch_active"),
        PromptGenerationBatch(
            id="pgb_manual_active",
            workflow_id="1-images.json",
            status=service.BATCH_PENDING,
            total_count=1,
            created_by="dobedub",
        ),
        PromptGenerationBatch(
            id="pgb_folder_batch_active",
            workflow_id="1-images.json",
            status=service.BATCH_PENDING,
            total_count=1,
            created_by="dobedub",
            batch_job_id="batch_auto",
        ),
        ImagePromptDraft(
            id="draft_manual_active",
            asset_id="asset_manual_active",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_PENDING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_manual_active",
            created_by="dobedub",
        ),
        ImagePromptDraft(
            id="draft_folder_batch_active",
            asset_id="asset_folder_batch_active",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_PENDING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_folder_batch_active",
            created_by="dobedub",
            batch_job_id="batch_auto",
        ),
    ])
    db_session.commit()

    batches = service.list_active_prompt_generation_batches(db_session, created_by="dobedub")

    assert [batch["id"] for batch in batches] == ["pgb_manual_active"]


def test_active_prompt_generation_batches_ignores_stale_batch_status_without_extra_payload_queries(db_session):
    base_time = now_seoul_naive()
    for index in range(8):
        batch_id = f"pgb_stale_generating_{index}"
        asset_id = f"asset_stale_generating_{index}"
        db_session.add(_asset(asset_id))
        db_session.add(PromptGenerationBatch(
            id=batch_id,
            workflow_id="1-images.json",
            status=service.BATCH_GENERATING,
            total_count=1,
            created_by="worker_a",
            created_at=base_time + timedelta(seconds=index),
        ))
        db_session.add(ImagePromptDraft(
            id=f"draft_stale_generating_{index}",
            asset_id=asset_id,
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_READY,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            positive_prompt="ready",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id=batch_id,
            created_by="worker_a",
        ))
    db_session.add(_asset("asset_active_after_stale"))
    db_session.add(PromptGenerationBatch(
        id="pgb_active_after_stale",
        workflow_id="1-images.json",
        status=service.BATCH_GENERATING,
        total_count=1,
        created_by="worker_a",
        created_at=base_time + timedelta(seconds=20),
    ))
    db_session.add(ImagePromptDraft(
        id="draft_active_after_stale",
        asset_id="asset_active_after_stale",
        workflow_id="1-images.json",
        slot_index=1,
        status=service.DRAFT_GENERATING,
        provider="grok",
        model="grok-test",
        instruction_version="wf@1",
        requested_frames=81,
        warnings_json=[],
        raw_json={},
        prompt_batch_id="pgb_active_after_stale",
        created_by="worker_a",
    ))
    db_session.commit()

    statements: list[str] = []

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", before_cursor_execute)
    try:
        batches = service.list_active_prompt_generation_batches(db_session, created_by="worker_a")
    finally:
        event.remove(bind, "before_cursor_execute", before_cursor_execute)

    assert [batch["id"] for batch in batches] == ["pgb_active_after_stale"]
    assert len(statements) <= 7


def test_active_prompt_generation_batches_keep_stale_completed_batches_with_active_drafts(db_session):
    db_session.add_all([
        _asset("asset_stale_active"),
        PromptGenerationBatch(
            id="pgb_stale_completed_with_generating_draft",
            workflow_id="1-images.json",
            status=service.BATCH_COMPLETED,
            total_count=1,
            completed_count=1,
            failed_count=0,
            created_by="worker_a",
        ),
        ImagePromptDraft(
            id="draft_stale_active",
            asset_id="asset_stale_active",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_GENERATING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_stale_completed_with_generating_draft",
            created_by="worker_a",
        ),
    ])
    db_session.commit()

    batches = service.list_active_prompt_generation_batches(db_session, created_by="worker_a")

    assert [batch["id"] for batch in batches] == ["pgb_stale_completed_with_generating_draft"]
    assert batches[0]["status"] == service.BATCH_GENERATING


def test_active_prompt_generation_batches_fail_stale_generating_drafts(db_session):
    stale_time = now_seoul_naive() - timedelta(minutes=30)
    db_session.add_all([
        _asset("asset_stale_generation_failed"),
        PromptGenerationBatch(
            id="pgb_stale_generation_failed",
            workflow_id="1-images.json",
            status=service.BATCH_GENERATING,
            total_count=1,
            completed_count=0,
            failed_count=0,
            created_by="worker_a",
            updated_at=stale_time,
        ),
        ImagePromptDraft(
            id="draft_stale_generation_failed",
            asset_id="asset_stale_generation_failed",
            workflow_id="1-images.json",
            slot_index=1,
            status=service.DRAFT_GENERATING,
            provider="grok",
            model="grok-test",
            instruction_version="wf@1",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            prompt_batch_id="pgb_stale_generation_failed",
            created_by="worker_a",
            updated_at=stale_time,
        ),
        PromptGenerationAttempt(
            id="attempt_stale_generation_failed",
            draft_id="draft_stale_generation_failed",
            attempt_no=1,
            status=service.DRAFT_GENERATING,
            endpoint="https://api.x.ai/v1/responses",
            model="grok-test",
            started_at=stale_time,
            response_json={},
        ),
    ])
    db_session.commit()

    active_batches = service.list_active_prompt_generation_batches(db_session, created_by="worker_a")
    history = service.list_prompt_drafts(db_session, created_by="worker_a", include_worker_stats=False)

    assert active_batches == []
    failed_draft = db_session.get(ImagePromptDraft, "draft_stale_generation_failed")
    failed_attempt = db_session.get(PromptGenerationAttempt, "attempt_stale_generation_failed")
    batch = db_session.get(PromptGenerationBatch, "pgb_stale_generation_failed")
    assert failed_draft.status == service.DRAFT_FAILED
    assert "중단" in failed_draft.failure_message
    assert failed_attempt.status == service.DRAFT_FAILED
    assert failed_attempt.completed_at is not None
    assert batch.status == service.BATCH_COMPLETED_WITH_ERRORS
    assert batch.failed_count == 1
    assert history["total"] == 1
    assert history["items"][0]["status"] == service.DRAFT_FAILED


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


def test_owner_and_manager_can_repair_failed_prompt_without_changing_owner(db_session):
    db_session.add_all([
        _asset("asset_repair_owner"),
        _asset("asset_repair_manager"),
        User(id="worker-a", name="Worker A", role="OPERATOR", permissions_json=["prompts:build"], is_active=True),
        User(id="manager-a", name="Manager A", role="ADMIN", permissions_json=["prompts:build", "jobs:manage"], is_active=True),
    ])
    for draft_id, asset_id, status in (
        ("draft_repair_owner", "asset_repair_owner", service.DRAFT_FAILED),
        ("draft_repair_manager", "asset_repair_manager", service.DRAFT_MANUAL_REQUIRED),
    ):
        db_session.add(ImagePromptDraft(
            id=draft_id, asset_id=asset_id, workflow_id="1-images.json", slot_index=1,
            status=status, provider="grok", model="grok-test", instruction_version="wf@1",
            warnings_json=["manual_input_required"], raw_json={}, created_by="worker-a",
        ))
    db_session.commit()

    owner = service.repair_failed_prompt_draft(
        db_session, "draft_repair_owner", actor_id="worker-a", can_manage=False,
        positive_prompt="Owner repaired prompt.",
    )
    manager = service.repair_failed_prompt_draft(
        db_session, "draft_repair_manager", actor_id="manager-a", can_manage=True,
        positive_prompt="Manager repaired prompt.",
    )

    assert owner["status"] == manager["status"] == service.DRAFT_READY
    assert owner["createdBy"] == manager["createdBy"] == "worker-a"
    assert db_session.get(ImagePromptDraft, "draft_repair_owner").warnings_json == []
    assert db_session.get(ImagePromptDraft, "draft_repair_manager").warnings_json == []


def test_foreign_worker_cannot_repair_failed_prompt(db_session):
    db_session.add(_asset("asset_repair_denied"))
    db_session.add(ImagePromptDraft(
        id="draft_repair_denied", asset_id="asset_repair_denied", workflow_id="1-images.json", slot_index=1,
        status=service.DRAFT_FAILED, provider="grok", model="grok-test", instruction_version="wf@1",
        warnings_json=[], raw_json={}, created_by="worker-a",
    ))
    db_session.commit()

    try:
        service.repair_failed_prompt_draft(
            db_session, "draft_repair_denied", actor_id="worker-b", can_manage=False,
            positive_prompt="Not allowed.",
        )
    except service.PromptDraftPermissionError:
        pass
    else:
        raise AssertionError("foreign worker repair must be rejected")


def test_retry_existing_draft_reopens_the_same_pending_batch(db_session):
    db_session.add(_asset("asset_retry_same_batch"))
    db_session.add(PromptGenerationBatch(
        id="pgb_retry_same_batch",
        workflow_id="1-images.json",
        status=service.BATCH_COMPLETED,
        total_count=1,
        completed_count=1,
        failed_count=0,
        created_by="worker_a",
    ))
    db_session.add(ImagePromptDraft(
        id="draft_retry_same_batch",
        asset_id="asset_retry_same_batch",
        workflow_id="1-images.json",
        slot_index=1,
        status=service.DRAFT_READY,
        provider="grok",
        model="grok-test",
        instruction_version="wf@1",
        positive_prompt="ready prompt",
        requested_frames=81,
        warnings_json=[],
        raw_json={"response": {"id": "old"}},
        prompt_batch_id="pgb_retry_same_batch",
        created_by="worker_a",
    ))
    db_session.commit()

    retried = service.retry_prompt_draft(db_session, "draft_retry_same_batch", created_by="worker_a")

    assert retried["draftId"] == "draft_retry_same_batch"
    assert retried["promptBatchId"] == "pgb_retry_same_batch"
    assert retried["status"] == service.DRAFT_PENDING
    batch = db_session.get(PromptGenerationBatch, "pgb_retry_same_batch")
    assert batch is not None
    assert batch.status == service.BATCH_PENDING
    assert batch.completed_count == 0
    assert batch.failed_count == 0


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
