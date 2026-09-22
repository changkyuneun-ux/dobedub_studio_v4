from __future__ import annotations

from backend.app.core.security import create_access_token
from backend.app.db.models import Asset, ImagePromptDraft, PromptGenerationBatch, RunpodRequestItem, User, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services import prompt_batch_service as service


def _headers(user_id: str, *, role: str) -> dict[str, str]:
    token = create_access_token({"id": user_id, "name": user_id, "role": role})
    return {"Authorization": f"Bearer {token['accessToken']}"}


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


def test_prompt_generation_active_list_shows_all_workers_to_managers(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            _asset("asset_visible_to_manager"),
            User(id="prompt-manager", name="Prompt Manager", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="worker-visible", name="Worker Visible", role="OPERATOR", permissions_json=["prompts:build"], is_active=True),
            PromptGenerationBatch(
                id="pgb_visible_to_manager",
                workflow_id="1-images.json",
                status=service.BATCH_GENERATING,
                total_count=1,
                created_by="worker-visible",
            ),
            ImagePromptDraft(
                id="draft_visible_to_manager",
                asset_id="asset_visible_to_manager",
                workflow_id="1-images.json",
                slot_index=1,
                status=service.DRAFT_GENERATING,
                provider="grok",
                model="grok-test",
                instruction_version="wf@1",
                requested_frames=81,
                warnings_json=[],
                raw_json={},
                prompt_batch_id="pgb_visible_to_manager",
                created_by="worker-visible",
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/prompts/image-drafts/batches/active-list", headers=_headers("prompt-manager", role="SUPER_ADMIN"))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["pgb_visible_to_manager"]


def test_prompt_generation_active_list_keeps_regular_users_scoped_to_their_own_batches(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            _asset("asset_owner_visible"),
            _asset("asset_other_hidden"),
            User(id="worker-owner", name="Owner", role="OPERATOR", permissions_json=["prompts:build"], is_active=True),
            User(id="worker-other", name="Other", role="OPERATOR", permissions_json=["prompts:build"], is_active=True),
            PromptGenerationBatch(
                id="pgb_owner_visible",
                workflow_id="1-images.json",
                status=service.BATCH_PENDING,
                total_count=1,
                created_by="worker-owner",
            ),
            PromptGenerationBatch(
                id="pgb_other_hidden",
                workflow_id="1-images.json",
                status=service.BATCH_PENDING,
                total_count=1,
                created_by="worker-other",
            ),
            ImagePromptDraft(
                id="draft_owner_visible",
                asset_id="asset_owner_visible",
                workflow_id="1-images.json",
                slot_index=1,
                    status=service.DRAFT_GENERATING,
                provider="grok",
                model="grok-test",
                instruction_version="wf@1",
                requested_frames=81,
                warnings_json=[],
                raw_json={},
                prompt_batch_id="pgb_owner_visible",
                created_by="worker-owner",
            ),
            ImagePromptDraft(
                id="draft_other_hidden",
                asset_id="asset_other_hidden",
                workflow_id="1-images.json",
                slot_index=1,
                    status=service.DRAFT_GENERATING,
                provider="grok",
                model="grok-test",
                instruction_version="wf@1",
                requested_frames=81,
                warnings_json=[],
                raw_json={},
                prompt_batch_id="pgb_other_hidden",
                created_by="worker-other",
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/prompts/image-drafts/batches/active-list", headers=_headers("worker-owner", role="OPERATOR"))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["pgb_owner_visible"]


def test_manager_can_edit_another_workers_successful_prompt_without_submitting_runpod(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            _asset("asset_prompt_edit_by_manager"),
            User(id="prompt-edit-manager", name="Prompt Edit Manager", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="prompt-edit-owner", name="Prompt Edit Owner", role="OPERATOR", permissions_json=["prompts:build"], is_active=True),
            ImagePromptDraft(
                id="draft_prompt_edit_by_manager",
                asset_id="asset_prompt_edit_by_manager",
                workflow_id="1-images.json",
                slot_index=1,
                status=service.DRAFT_READY,
                provider="grok",
                model="grok-test",
                instruction_version="wf@1",
                positive_prompt="original successful prompt",
                requested_frames=81,
                warnings_json=[],
                raw_json={},
                created_by="prompt-edit-owner",
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.patch(
        "/api/prompts/image-drafts/draft_prompt_edit_by_manager",
        headers=_headers("prompt-edit-manager", role="SUPER_ADMIN"),
        json={"positivePrompt": "edited successful prompt"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["positivePrompt"] == "edited successful prompt"
    assert response.json()["status"] == service.DRAFT_READY


def test_failed_prompt_manual_repair_becomes_requestable_without_creating_runpod_work(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            _asset("asset_prompt_manual_repair"),
            User(id="prompt-repair-manager", name="Prompt Repair Manager", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="prompt-repair-owner", name="Prompt Repair Owner", role="OPERATOR", permissions_json=["prompts:build", "jobs:run"], is_active=True),
            ImagePromptDraft(
                id="draft_prompt_manual_repair",
                asset_id="asset_prompt_manual_repair",
                workflow_id="1-images.json",
                slot_index=1,
                status=service.DRAFT_FAILED,
                provider="grok",
                model="grok-test",
                instruction_version="wf@1",
                requested_frames=81,
                warnings_json=["manual_input_required"],
                raw_json={},
                created_by="prompt-repair-owner",
            ),
        ])
        session.commit()
    finally:
        session.close()

    response = api_client.patch(
        "/api/prompts/image-drafts/draft_prompt_manual_repair",
        headers=_headers("prompt-repair-manager", role="SUPER_ADMIN"),
        json={"positivePrompt": "Manually repaired prompt.", "repairFailed": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == service.DRAFT_READY
    session = SessionLocal()
    try:
        assert session.query(RunpodRequestItem).filter_by(prompt_draft_id="draft_prompt_manual_repair").count() == 0
        assert session.query(WorkflowTask).filter_by(prompt_draft_id="draft_prompt_manual_repair").count() == 0
    finally:
        session.close()

    queue = api_client.get(
        "/api/jobs/request-batches/queue?workerId=prompt-repair-owner",
        headers=_headers("prompt-repair-manager", role="SUPER_ADMIN"),
    )
    assert queue.status_code == 200, queue.text
    repaired = next(item for item in queue.json()["items"] if item.get("promptDraftId") == "draft_prompt_manual_repair")
    assert repaired["status"] == "READY"
    assert repaired["canSubmit"] is True
