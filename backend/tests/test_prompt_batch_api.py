from __future__ import annotations

from backend.app.core.security import create_access_token
from backend.app.db.models import Asset, ImagePromptDraft, PromptGenerationBatch, User
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
                status=service.DRAFT_PENDING,
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
                status=service.DRAFT_PENDING,
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
