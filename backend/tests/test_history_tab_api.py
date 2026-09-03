from __future__ import annotations

from sqlalchemy.exc import OperationalError

from backend.app.core.security import create_access_token
from backend.app.db.models import Asset, ImagePromptDraft, PromptGenerationAttempt, User, WorkflowTask
from backend.app.db.session import SessionLocal
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
    assert body["pageSize"] == 20
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
            runpod_submit_json={"id": "runpod-job-1", "delayTime": 7.5},
            runpod_status_json={"status": "COMPLETED", "executionTime": 42.25, "output": {"filename": "result.mp4"}},
        ))
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/history/runpod?page=1&pageSize=50", headers=_authorized_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["pageSize"] == 20
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


def test_history_tabs_use_the_dedicated_history_api_contracts() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert 'promptHistory: (page = 1)' in client
    assert "/api/history/prompts?page=${page}" in client
    assert 'runpodHistory: (page = 1)' in client
    assert "/api/history/runpod?page=${page}" in client
    assert "apiClient.promptHistory(page)" in screen
    assert "apiClient.runpodHistory(runpodPage)" in screen
