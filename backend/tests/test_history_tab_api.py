from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.app.core.security import create_access_token
from backend.app.db.models import Asset, BatchJob, ImagePromptDraft, PromptGenerationAttempt, TaskOutputAsset, User, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services.task_tracking_service import active_task_ids
from pathlib import Path


def _authorized_headers() -> dict[str, str]:
    token = create_access_token({"id": "history-user", "name": "History User", "role": "SUPER_ADMIN"})
    return {"Authorization": f"Bearer {token['accessToken']}"}


def test_prompt_history_returns_image_prompt_and_grok_metadata(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(Asset(
            id="asset_history_prompt",
            asset_type="input_image",
            file_name="source.png",
            mime_type="image/png",
            size_bytes=123,
            storage_key="uploads/source.png",
        ))
        session.add(ImagePromptDraft(
            id="grok_draft_history_1",
            asset_id="asset_history_prompt",
            workflow_id="1-images.json",
            slot_index=1,
            status="READY",
            provider="grok",
            model="grok-vision-model",
            instruction_version="v1",
            positive_prompt="A gentle motion.",
            created_by="history-user",
        ))
        session.add(PromptGenerationAttempt(
            id="grok_attempt_history_1",
            draft_id="grok_draft_history_1",
            attempt_no=1,
            status="READY",
            endpoint="https://api.x.ai/v1/responses",
            model="grok-vision-model",
            latency_ms=1250,
            input_tokens=120,
            output_tokens=44,
            response_json={},
        ))
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/history/prompts?page=1&pageSize=200", headers=_authorized_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["pageSize"] == 10
    assert body["total"] == 1
    item = body["items"][0]
    assert item["createdBy"] == "history-user"
    assert item["assetId"] == "asset_history_prompt"
    assert item["positivePrompt"] == "A gentle motion."
    assert item["grokResponse"] == {
        "endpoint": "https://api.x.ai/v1/responses",
        "model": "grok-vision-model",
        "latencyMs": 1250,
        "inputTokens": 120,
        "outputTokens": 44,
    }


def test_prompt_history_returns_worker_names_without_per_worker_stats(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            User(id="history-user", name="History User", email=None, role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="history-worker-a", name="작업자 A", email=None, role="OPERATOR", permissions_json=[], is_active=True),
            User(id="history-worker-b", name="작업자 B", email=None, role="OPERATOR", permissions_json=[], is_active=True),
            Asset(id="asset_history_stats_a", asset_type="input_image", file_name="a.png", mime_type="image/png", size_bytes=1, storage_key="uploads/a.png"),
            Asset(id="asset_history_stats_b", asset_type="input_image", file_name="b.png", mime_type="image/png", size_bytes=1, storage_key="uploads/b.png"),
            ImagePromptDraft(
                id="grok_draft_history_stats_a", asset_id="asset_history_stats_a", workflow_id="1-images.json",
                slot_index=1, status="READY", model="grok", positive_prompt="ready", created_by="history-worker-a",
            ),
            ImagePromptDraft(
                id="grok_draft_history_stats_b", asset_id="asset_history_stats_b", workflow_id="1-images.json",
                slot_index=1, status="FAILED", model="grok", failure_message="failed", created_by="history-worker-b",
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/history/prompts?page=1", headers=_authorized_headers())

    assert response.status_code == 200
    body = response.json()
    assert {item["createdByName"] for item in body["items"]} >= {"작업자 A", "작업자 B"}
    assert body["workerStats"] == []


def test_prompt_history_database_errors_return_actionable_message(api_client, monkeypatch):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.commit()
    finally:
        session.close()

    from backend.app.api.v1 import history as history_api

    def fail_prompt_history(*_args, **_kwargs):
        raise OperationalError(
            "select image_prompt_drafts",
            {},
            Exception("(1038) Out of sort memory, consider increasing server sort buffer size"),
        )

    monkeypatch.setattr(history_api.prompt_batch_service, "list_prompt_drafts", fail_prompt_history)

    response = api_client.get("/api/history/prompts?page=1", headers=_authorized_headers())

    assert response.status_code == 503
    assert response.json()["detail"] == "프롬프트 이력 조회에 실패했습니다. 최신 DB 인덱스 마이그레이션 적용 상태를 확인해주세요."


def test_prompt_history_filters_generation_result_and_runpod_status(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add_all([
            Asset(id="asset_prompt_ready_unrequested", asset_type="input_image", file_name="ready.png", mime_type="image/png", size_bytes=1, storage_key="uploads/ready.png"),
            Asset(id="asset_prompt_failed", asset_type="input_image", file_name="failed.png", mime_type="image/png", size_bytes=1, storage_key="uploads/failed.png"),
            Asset(id="asset_prompt_manual_required", asset_type="input_image", file_name="manual.png", mime_type="image/png", size_bytes=1, storage_key="uploads/manual.png"),
            Asset(id="asset_prompt_runpod_failed", asset_type="input_image", file_name="runpod-failed.png", mime_type="image/png", size_bytes=1, storage_key="uploads/runpod-failed.png"),
            Asset(id="asset_prompt_runpod_cancelled", asset_type="input_image", file_name="runpod-cancelled.png", mime_type="image/png", size_bytes=1, storage_key="uploads/runpod-cancelled.png"),
            BatchJob(
                id="history-user_zip_260906",
                workflow_id="1-images.json",
                status="INCOMPLETE",
                source_zip_file_name="zip.zip",
                total_images=1,
                created_by="history-user",
            ),
            ImagePromptDraft(
                id="grok_draft_ready_unrequested", asset_id="asset_prompt_ready_unrequested", workflow_id="1-images.json",
                slot_index=1, status="READY", model="grok", positive_prompt="ready", created_by="history-user",
            ),
            ImagePromptDraft(
                id="grok_draft_generation_failed", asset_id="asset_prompt_failed", workflow_id="1-images.json",
                slot_index=1, status="FAILED", model="grok", failure_message="failed", created_by="history-user",
            ),
            ImagePromptDraft(
                id="grok_draft_manual_required_batch", asset_id="asset_prompt_manual_required", workflow_id="1-images.json",
                slot_index=1, status="MANUAL_REQUIRED", model="grok", failure_message="manual review", created_by="history-user",
                batch_job_id="history-user_zip_260906",
            ),
            ImagePromptDraft(
                id="grok_draft_runpod_failed", asset_id="asset_prompt_runpod_failed", workflow_id="1-images.json",
                slot_index=1, status="READY", model="grok", positive_prompt="ready but runpod failed", created_by="history-user",
            ),
            ImagePromptDraft(
                id="grok_draft_runpod_cancelled", asset_id="asset_prompt_runpod_cancelled", workflow_id="1-images.json",
                slot_index=1, status="READY", model="grok", positive_prompt="ready but runpod cancelled", created_by="history-user",
            ),
            WorkflowTask(
                id="task_prompt_runpod_failed",
                workflow_id="1-images.json",
                status="FAILED",
                prompt_draft_id="grok_draft_runpod_failed",
            ),
            WorkflowTask(
                id="task_prompt_runpod_cancelled",
                workflow_id="1-images.json",
                status="CANCELLED",
                prompt_draft_id="grok_draft_runpod_cancelled",
            ),
        ])
        session.commit()
    finally:
        session.close()

    failed_generation = api_client.get(
        "/api/history/prompts?page=1&generationStatus=FAILED",
        headers=_authorized_headers(),
    )
    unrequested_success = api_client.get(
        "/api/history/prompts?page=1&generationStatus=SUCCESS&runpodStatus=UNREQUESTED",
        headers=_authorized_headers(),
    )
    failed_runpod = api_client.get(
        "/api/history/prompts?page=1&runpodStatus=FAILED",
        headers=_authorized_headers(),
    )
    cancelled_runpod = api_client.get(
        "/api/history/prompts?page=1&runpodStatus=CANCELLED",
        headers=_authorized_headers(),
    )

    assert failed_generation.status_code == 200
    failed_items = failed_generation.json()["items"]
    assert {item["draftId"] for item in failed_items} == {"grok_draft_generation_failed", "grok_draft_manual_required_batch"}
    assert next(item for item in failed_items if item["draftId"] == "grok_draft_manual_required_batch")["batchJobId"] == "history-user_zip_260906"
    assert unrequested_success.status_code == 200
    assert [item["draftId"] for item in unrequested_success.json()["items"]] == ["grok_draft_ready_unrequested"]
    assert failed_runpod.status_code == 200
    assert [item["draftId"] for item in failed_runpod.json()["items"]] == ["grok_draft_runpod_failed"]
    assert cancelled_runpod.status_code == 200
    assert [item["draftId"] for item in cancelled_runpod.json()["items"]] == ["grok_draft_runpod_cancelled"]


def test_prompt_failed_batch_drafts_do_not_appear_in_runpod_history(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add_all([
            BatchJob(
                id="history-user_failed_zip_260906",
                workflow_id="1-images.json",
                status="INCOMPLETE",
                source_zip_file_name="failed.zip",
                total_images=2,
                created_by="history-user",
            ),
            Asset(id="asset_prompt_failed_only", asset_type="input_image", file_name="failed.png", mime_type="image/png", size_bytes=1, storage_key="uploads/failed.png"),
            Asset(id="asset_prompt_manual_only", asset_type="input_image", file_name="manual.png", mime_type="image/png", size_bytes=1, storage_key="uploads/manual.png"),
            ImagePromptDraft(
                id="grok_draft_failed_no_runpod", asset_id="asset_prompt_failed_only", workflow_id="1-images.json",
                slot_index=1, status="FAILED", model="grok", failure_message="failed", created_by="history-user",
                batch_job_id="history-user_failed_zip_260906",
            ),
            ImagePromptDraft(
                id="grok_draft_manual_no_runpod", asset_id="asset_prompt_manual_only", workflow_id="1-images.json",
                slot_index=2, status="MANUAL_REQUIRED", model="grok", failure_message="manual", created_by="history-user",
                batch_job_id="history-user_failed_zip_260906",
            ),
        ])
        session.commit()
    finally:
        session.close()

    prompts = api_client.get(
        "/api/history/prompts?page=1&generationStatus=FAILED",
        headers=_authorized_headers(),
    )
    runpod = api_client.get(
        "/api/history/runpod?page=1&batchId=history-user_failed_zip_260906",
        headers=_authorized_headers(),
    )

    assert prompts.status_code == 200
    assert {item["draftId"] for item in prompts.json()["items"]} >= {"grok_draft_failed_no_runpod", "grok_draft_manual_no_runpod"}
    assert runpod.status_code == 200
    assert runpod.json()["items"] == []


def test_runpod_history_returns_task_and_provider_response(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(WorkflowTask(
            id="task_history_runpod_1",
            runpod_job_id="runpod-job-1",
            workflow_id="1-images.json",
            status="COMPLETED",
            worker_name="History User",
            user_id="history-user",
            prompt_draft_id="grok_draft_history_1",
            payload_json={},
            config_json={"durationSeconds": 5, "frames": 81, "fps": 16},
            elapsed_seconds=65,
            runpod_submit_json={"id": "runpod-job-1", "delayTime": 7.5},
            runpod_status_json={"status": "COMPLETED", "executionTime": 42.25, "output": {"filename": "result.mp4"}},
        ))
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/history/runpod?page=1&pageSize=50", headers=_authorized_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["pageSize"] == 10
    assert body["total"] == 1
    item = body["items"][0]
    assert item["taskId"] == "task_history_runpod_1"
    assert item["workflowName"] == "1-images"
    assert item["promptDraftId"] == "grok_draft_history_1"
    assert item["runpodResponse"] == {
        "filename": "result.mp4",
        "delaySeconds": 7.5,
        "executionSeconds": 42.25,
        "jobId": "runpod-job-1",
    }
    assert item["durationSeconds"] == 5
    assert item["elapsedSeconds"] == 65
    assert item["negativePrompts"]
    assert "photorealistic" in item["negativePrompts"][0]["text"]


def test_runpod_history_exposes_legacy_prompt_batch_id(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(Asset(
            id="asset_legacy_prompt_batch",
            asset_type="input_image",
            file_name="legacy.png",
            mime_type="image/png",
            size_bytes=100,
            storage_key="uploads/legacy.png",
        ))
        session.add(ImagePromptDraft(
            id="grok_draft_legacy_batch",
            asset_id="asset_legacy_prompt_batch",
            workflow_id="1-images.json",
            slot_index=1,
            status="READY",
            provider="grok",
            model="grok",
            positive_prompt="walk",
            prompt_batch_id="pgb_legacy_visible",
            created_by="history-user",
        ))
        session.add(WorkflowTask(
            id="task_history_legacy_prompt_batch",
            workflow_id="1-images.json",
            status="COMPLETED",
            worker_name="History User",
            user_id="history-user",
            prompt_draft_id="grok_draft_legacy_batch",
            payload_json={"promptDraftId": "grok_draft_legacy_batch"},
        ))
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/history/runpod?page=1&pageSize=20", headers=_authorized_headers())

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["batchJobId"] is None
    assert item["promptBatchId"] == "pgb_legacy_visible"


def test_runpod_history_batch_filter_matches_legacy_prompt_batch_id(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(Asset(
            id="asset_legacy_prompt_batch_filter",
            asset_type="input_image",
            file_name="legacy-filter.png",
            mime_type="image/png",
            size_bytes=100,
            storage_key="uploads/legacy-filter.png",
        ))
        session.add(ImagePromptDraft(
            id="grok_draft_legacy_batch_filter",
            asset_id="asset_legacy_prompt_batch_filter",
            workflow_id="1-images.json",
            slot_index=1,
            status="READY",
            provider="grok",
            model="grok",
            positive_prompt="walk",
            prompt_batch_id="pgb_legacy_filter",
            created_by="history-user",
        ))
        session.add_all([
            WorkflowTask(
                id="task_history_legacy_prompt_batch_filter",
                workflow_id="1-images.json",
                status="COMPLETED",
                worker_name="History User",
                user_id="history-user",
                prompt_draft_id="grok_draft_legacy_batch_filter",
                payload_json={"promptDraftId": "grok_draft_legacy_batch_filter"},
            ),
            WorkflowTask(
                id="task_history_other_batch",
                workflow_id="1-images.json",
                status="COMPLETED",
                worker_name="History User",
                user_id="history-user",
                payload_json={},
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/history/runpod?page=1&batchId=pgb_legacy_filter", headers=_authorized_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["taskId"] == "task_history_legacy_prompt_batch_filter"


def test_runpod_history_filters_by_workflow(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add_all([
            WorkflowTask(id="task_history_workflow_a", workflow_id="1-images.json", status="COMPLETED", worker_name="History User", user_id="history-user", payload_json={}),
            WorkflowTask(id="task_history_workflow_b", workflow_id="Pickme_Workflow.json", status="COMPLETED", worker_name="History User", user_id="history-user", payload_json={}),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/history/runpod?page=1&workflowId=Pickme_Workflow.json", headers=_authorized_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["taskId"] for item in body["items"]] == ["task_history_workflow_b"]


def test_runpod_history_filters_by_result_status_and_workflow(api_client):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add_all([
            WorkflowTask(id="task_history_completed_a", workflow_id="1-images.json", status="COMPLETED", worker_name="History User", user_id="history-user", payload_json={}),
            WorkflowTask(id="task_history_failed_a", workflow_id="1-images.json", status="FAILED", worker_name="History User", user_id="history-user", payload_json={}),
            WorkflowTask(id="task_history_cancelled_a", workflow_id="1-images.json", status="CANCELLED", worker_name="History User", user_id="history-user", payload_json={}),
            WorkflowTask(id="task_history_active_a", workflow_id="1-images.json", status="QUEUED", worker_name="History User", user_id="history-user", payload_json={}),
            WorkflowTask(id="task_history_failed_b", workflow_id="Pickme_Workflow.json", status="FAILED", worker_name="History User", user_id="history-user", payload_json={}),
        ])
        session.commit()
    finally:
        session.close()

    failed = api_client.get(
        "/api/history/runpod?page=1&workflowId=1-images.json&resultStatus=FAILED",
        headers=_authorized_headers(),
    )
    active = api_client.get(
        "/api/history/runpod?page=1&workflowId=1-images.json&resultStatus=ACTIVE",
        headers=_authorized_headers(),
    )
    cancelled = api_client.get(
        "/api/history/runpod?page=1&workflowId=1-images.json&resultStatus=CANCELLED",
        headers=_authorized_headers(),
    )

    assert failed.status_code == 200
    failed_body = failed.json()
    assert failed_body["total"] == 1
    assert [item["taskId"] for item in failed_body["items"]] == ["task_history_failed_a"]
    assert active.status_code == 200
    active_body = active.json()
    assert active_body["total"] == 1
    assert [item["taskId"] for item in active_body["items"]] == ["task_history_active_a"]
    assert cancelled.status_code == 200
    cancelled_body = cancelled.json()
    assert cancelled_body["total"] == 1
    assert [(item["taskId"], item["status"]) for item in cancelled_body["items"]] == [("task_history_cancelled_a", "Cancelled")]


def test_runpod_history_filters_by_worker_and_execution_date(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            User(id="history-user", name="History User", email=None, role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="worker-date-a", name="작업자 날짜 A", email=None, role="OPERATOR", permissions_json=[], is_active=True),
            User(id="worker-date-b", name="작업자 날짜 B", email=None, role="OPERATOR", permissions_json=[], is_active=True),
            WorkflowTask(
                id="task_history_worker_date_a",
                workflow_id="1-images.json",
                status="COMPLETED",
                worker_name="작업자 날짜 A",
                user_id="worker-date-a",
                created_at=datetime(2026, 9, 3, 4, 0, 0),
                payload_json={},
            ),
            WorkflowTask(
                id="task_history_worker_date_b",
                workflow_id="1-images.json",
                status="COMPLETED",
                worker_name="작업자 날짜 B",
                user_id="worker-date-b",
                created_at=datetime(2026, 9, 3, 5, 0, 0),
                payload_json={},
            ),
            WorkflowTask(
                id="task_history_worker_other_date",
                workflow_id="1-images.json",
                status="COMPLETED",
                worker_name="작업자 날짜 A",
                user_id="worker-date-a",
                created_at=datetime(2026, 9, 4, 4, 0, 0),
                payload_json={},
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.get(
        f"/api/history/runpod?page=1&workerId={quote('worker-date-a')}&runDate=2026-09-03",
        headers=_authorized_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["taskId"] for item in body["items"]] == ["task_history_worker_date_a"]


def test_runpod_history_filters_selected_batch_id_exactly(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            User(id="history-user", name="History User", email=None, role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            WorkflowTask(
                id="task_history_batch_original",
                workflow_id="1-images.json",
                status="COMPLETED",
                worker_name="Legacy Worker",
                user_id="history-user",
                batch_job_id="batch_legacy_260904",
                payload_json={},
            ),
            WorkflowTask(
                id="task_history_batch_retry",
                workflow_id="1-images.json",
                status="COMPLETED",
                worker_name="Legacy Worker",
                user_id="history-user",
                batch_job_id="batch_legacy_260904_2",
                payload_json={},
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.get(
        "/api/history/runpod?page=1&batchId=batch_legacy_260904",
        headers=_authorized_headers(),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["taskId"] for item in response.json()["items"]] == ["task_history_batch_original"]


def test_runpod_history_can_rework_failed_task_without_creating_a_new_task(api_client, monkeypatch):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(Asset(
            id="asset_stale_output",
            asset_type="output_video",
            file_name="stale.mp4",
            mime_type="video/mp4",
            size_bytes=1,
            storage_key="outputs/stale.mp4",
        ))
        session.add(WorkflowTask(
            id="task_history_failed_regen",
            runpod_job_id="runpod-old-failed",
            workflow_id="1-images.json",
            status="FAILED",
            progress=100,
            worker_name="History User",
            user_id="history-user",
            prompt_draft_id="grok_draft_regen",
            runpod_submit_json={"id": "runpod-old-failed"},
            runpod_status_json={"status": "FAILED", "error": "old failure"},
            last_dispatch_error="old error",
            payload_json={
                "workflowId": "1-images.json",
                "workflowName": "1-images",
                "promptDraftId": "grok_draft_regen",
                "keyframes": [],
                "segments": [{"index": 1, "positivePrompt": "retry this scene", "negativePrompt": "blur"}],
            },
        ))
        session.flush()
        session.add(TaskOutputAsset(task_id="task_history_failed_regen", asset_id="asset_stale_output", output_role="final"))
        session.commit()
    finally:
        session.close()

    from backend.app.api.v1 import history as history_api

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("rework must update the existing task, not create a new one")

    monkeypatch.setattr(history_api.studio_api_service, "create_job", fail_if_called)

    response = api_client.post("/api/history/task_history_failed_regen/rework", headers=_authorized_headers())

    assert response.status_code == 201
    assert response.json() == {
        "taskId": "task_history_failed_regen",
        "sourceTaskId": "task_history_failed_regen",
        "runpodJobId": "",
        "status": "PENDING_SUBMIT",
        "statusLabel": "요청 대기",
        "lastDispatchError": None,
        "generationSeed": None,
    }
    session = SessionLocal()
    try:
        tasks = session.scalars(select(WorkflowTask)).all()
        assert [task.id for task in tasks] == ["task_history_failed_regen"]
        task = tasks[0]
        assert task.status == "PENDING_SUBMIT"
        assert task.progress == 0
        assert task.runpod_job_id is None
        assert task.runpod_submit_json == {}
        assert task.runpod_status_json == {}
        assert task.last_dispatch_error is None
        assert task.payload_json["promptDraftId"] == "grok_draft_regen"
        assert "regeneratedFromTaskId" not in task.payload_json
        assert session.scalars(select(TaskOutputAsset)).all() == []
    finally:
        session.close()


def test_legacy_regenerate_endpoint_uses_same_rework_semantics(api_client, monkeypatch):
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(WorkflowTask(
            id="task_history_failed_existing_retry",
            workflow_id="1-images.json",
            status="FAILED",
            worker_name="History User",
            user_id="history-user",
            payload_json={"workflowId": "1-images.json", "segments": []},
        ))
        session.commit()
    finally:
        session.close()

    from backend.app.api.v1 import history as history_api

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("legacy endpoint must not create a retry child task")

    monkeypatch.setattr(history_api.studio_api_service.job_service, "queue_job", fail_if_called)

    response = api_client.post("/api/history/task_history_failed_existing_retry/regenerate", headers=_authorized_headers())

    assert response.status_code == 201
    assert response.json() == {
        "taskId": "task_history_failed_existing_retry",
        "sourceTaskId": "task_history_failed_existing_retry",
        "runpodJobId": "",
        "status": "PENDING_SUBMIT",
        "statusLabel": "요청 대기",
        "lastDispatchError": None,
        "generationSeed": None,
    }


def test_monitor_marks_runpod_job_not_found_as_failed(db_session, monkeypatch):
    from backend.app.services import studio_api_service

    studio_api_service.JOBS.clear()
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(WorkflowTask(
            id="task_missing_runpod_job",
            runpod_job_id="missing-runpod-job",
            workflow_id="1-images.json",
            execution_mode="runpod",
            status="IN_PROGRESS",
            progress=45,
            worker_name="History User",
            user_id="history-user",
            payload_json={
                "workflowId": "1-images.json",
                "workflowName": "1-images",
                "user": {"id": "history-user", "name": "History User"},
                "segments": [{"index": 1, "positivePrompt": "prompt", "negativePrompt": "", "config": {}}],
            },
            runpod_submit_json={"id": "missing-runpod-job"},
            runpod_status_json={"status": "IN_PROGRESS"},
            created_at=datetime(2026, 9, 6, 12, 0, 0),
            updated_at=datetime(2026, 9, 6, 12, 0, 0),
        ))
        session.commit()
    finally:
        session.close()

    def provider_404(*_args, **_kwargs):
        raise RuntimeError('RunPod HTTP 404: {"status":404,"title":"Not Found","detail":"job not found"}')

    monkeypatch.setattr(studio_api_service, "runpod_request", provider_404)

    result = studio_api_service.monitor_active_jobs()

    assert result["failures"] == []
    assert "task_missing_runpod_job" not in active_task_ids()

    session = SessionLocal()
    try:
        task = session.get(WorkflowTask, "task_missing_runpod_job")
        assert task is not None
        assert task.status == "FAILED"
        assert task.progress == 100
        assert "job not found" in str(task.runpod_status_json.get("error"))
    finally:
        session.close()


def test_monitor_keeps_transient_runpod_status_errors_retryable(db_session, monkeypatch):
    from backend.app.services import studio_api_service

    studio_api_service.JOBS.clear()
    session = SessionLocal()
    try:
        session.add(User(
            id="history-user",
            name="History User",
            email=None,
            role="SUPER_ADMIN",
            permissions_json=["admin:*"],
            is_active=True,
        ))
        session.add(WorkflowTask(
            id="task_transient_runpod_error",
            runpod_job_id="transient-runpod-job",
            workflow_id="1-images.json",
            execution_mode="runpod",
            status="IN_PROGRESS",
            progress=45,
            worker_name="History User",
            user_id="history-user",
            payload_json={
                "workflowId": "1-images.json",
                "workflowName": "1-images",
                "user": {"id": "history-user", "name": "History User"},
                "segments": [{"index": 1, "positivePrompt": "prompt", "negativePrompt": "", "config": {}}],
            },
            runpod_submit_json={"id": "transient-runpod-job"},
            runpod_status_json={"status": "IN_PROGRESS"},
            created_at=datetime(2026, 9, 6, 12, 0, 0),
            updated_at=datetime(2026, 9, 6, 12, 0, 0),
        ))
        session.commit()
    finally:
        session.close()

    def provider_timeout(*_args, **_kwargs):
        raise RuntimeError("RunPod HTTP 503: endpoint warming")

    monkeypatch.setattr(studio_api_service, "runpod_request", provider_timeout)

    result = studio_api_service.monitor_active_jobs()

    assert result["failures"] == ["task_transient_runpod_error"]
    assert "task_transient_runpod_error" in active_task_ids()


def test_history_tabs_use_the_dedicated_history_api_contracts() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    runpod_history_client = client.split("runpodHistory: (params:", 1)[1].split("batchJobs:", 1)[0]

    assert "promptHistory: (params:" in client
    assert 'query.set("generationStatus", params.generationStatus)' in client
    assert 'query.set("runpodStatus", params.runpodStatus)' in client
    assert "runpodHistory: (params:" in client
    assert 'query.set("workflowId", params.workflowId)' in client
    assert 'query.set("resultStatus", params.resultStatus)' in client
    assert 'query.set("workerId", params.workerId)' in client
    assert 'query.set("runDate", params.runDate)' in runpod_history_client
    assert 'query.set("dateFrom", params.dateFrom)' not in runpod_history_client
    assert 'query.set("dateTo", params.dateTo)' not in runpod_history_client
    assert "apiClient.promptHistory({ page, generationStatus: generationFilter, runpodStatus: runpodFilter, batchId: selectedPromptBatchJobId })" in screen
    assert "apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId })" in screen
    assert 'query.set("batchId", params.batchId)' in client
    assert "v3-runpod-history-toolbar" in screen
    assert "v3-runpod-history-actions" in screen
    assert "runpodWorkerFilter" in screen
    assert "runpodRunDate" in screen
    assert "runpodDateFrom" not in screen
    assert "runpodDateTo" not in screen
    assert "batchSearchText" in screen
    assert "selectedBatchJobId" in screen
    assert "selectedPromptHistoryDraftId" in screen
    assert "setItems(response.items)" in screen
    assert "useEffect(() => {\n    selectPromptHistoryItem(items[0] || null);\n  }, [items]);" in screen
    assert "apiClient.retryImagePromptDraft(item.draftId)" in screen
    assert "워크플로우 내장 Negative Prompt" not in screen
    assert "<span>복사</span>" not in screen
    assert ">Copy</button>" not in screen
    assert "Grok API 응답" in screen
    assert 'historyTab === "prompt" ?' in screen
    assert "<PromptGrokResponseDetail item={selectedPromptHistoryItem} />" in screen
    assert "onSelectGrokItem={setSelectedPromptHistoryItem}" in screen
    assert "v3-prompt-history-detail" not in screen
