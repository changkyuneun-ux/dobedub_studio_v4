from __future__ import annotations

from backend.app.core.security import create_access_token
from backend.app.db.models import Asset, ImagePromptDraft, PromptGenerationBatch, RunpodRequestBatch, RunpodRequestItem, TaskOutputAsset, TaskPrompt, User, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services import prompt_batch_service as service
from backend.app.services.task_tracking_service import record_job_status


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


def test_edited_successful_prompt_is_marked_for_requeue_and_reuses_linked_task(api_client):
    session = SessionLocal()
    try:
        session.add_all([
            _asset("asset_prompt_requeue"),
            Asset(id="asset_old_video", asset_type="output", file_name="old.mp4", mime_type="video/mp4", size_bytes=1, storage_key="outputs/old.mp4", metadata_json={}),
            User(id="prompt-requeue-manager", name="Manager", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="prompt-requeue-owner", name="Owner", role="OPERATOR", permissions_json=["prompts:build", "jobs:run"], is_active=True),
            ImagePromptDraft(
                id="draft_prompt_requeue", asset_id="asset_prompt_requeue", workflow_id="1-images.json",
                slot_index=1, status=service.DRAFT_READY, provider="grok", model="grok-test",
                instruction_version="wf@1", positive_prompt="edited prompt", requested_frames=81,
                warnings_json=[], raw_json={}, created_by="prompt-requeue-owner",
            ),
            RunpodRequestBatch(id="request_batch_requeue", workflow_id="1-images.json", requested_count=1, status="COMPLETED", created_by="prompt-requeue-owner"),
        ])
        session.flush()
        task = WorkflowTask(
            id="task_prompt_requeue", workflow_id="1-images.json", execution_mode="runpod", status="COMPLETED",
            progress=100, user_id="prompt-requeue-owner", worker_name="Owner",
            positive_prompts=[{"index": 1, "text": "original prompt"}], negative_prompts=[],
            config_json={}, wan_node_config={}, patch_summary={},
            payload_json={"promptDraftId": "draft_prompt_requeue", "segments": [{"index": 1, "positivePrompt": "original prompt", "config": {}}]},
            runpod_submit_json={"id": "old-job"}, runpod_status_json={"status": "COMPLETED"},
            prompt_draft_id="draft_prompt_requeue", request_batch_id="request_batch_requeue", request_item_id="request_item_requeue",
        )
        session.add(task)
        session.flush()
        session.add_all([
            RunpodRequestItem(id="request_item_requeue", request_batch_id="request_batch_requeue", sequence_no=1, prompt_draft_id="draft_prompt_requeue", asset_id="asset_prompt_requeue", workflow_id="1-images.json", positive_prompt="original prompt", requested_frames=81, status="COMPLETED", task_id="task_prompt_requeue"),
            TaskPrompt(task_id="task_prompt_requeue", workflow_id="1-images.json", segment_index=1, positive_prompt="original prompt", negative_prompt="", input_asset_ids=["asset_prompt_requeue"], output_asset_ids=["asset_old_video"], metadata_json={}),
            TaskOutputAsset(task_id="task_prompt_requeue", asset_id="asset_old_video", output_role="final"),
        ])
        session.commit()
    finally:
        session.close()

    history = api_client.get("/api/prompts/image-drafts?workerId=prompt-requeue-owner", headers=_headers("prompt-requeue-manager", role="SUPER_ADMIN"))
    assert history.status_code == 200, history.text
    row = history.json()["items"][0]
    assert row["requeueRequired"] is True
    assert row["runpodTaskId"] == "task_prompt_requeue"

    response = api_client.post(
        "/api/prompts/image-drafts/draft_prompt_requeue/requeue-runpod",
        headers=_headers("prompt-requeue-manager", role="SUPER_ADMIN"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["taskId"] == "task_prompt_requeue"
    assert response.json()["status"] == "PENDING_SUBMIT"
    assert response.json()["outputAssets"] == []

    session = SessionLocal()
    try:
        task = session.get(WorkflowTask, "task_prompt_requeue")
        request_item = session.get(RunpodRequestItem, "request_item_requeue")
        prompt = session.query(TaskPrompt).filter_by(task_id=task.id).one()
        assert task.status == "PENDING_SUBMIT"
        assert task.positive_prompts == [{"index": 1, "text": "edited prompt"}]
        assert task.payload_json["segments"][0]["positivePrompt"] == "edited prompt"
        assert request_item.positive_prompt == "edited prompt"
        assert request_item.status == "PENDING_SUBMIT"
        assert prompt.positive_prompt == "edited prompt"
        assert prompt.output_asset_ids == ["asset_old_video"]
        assert [link.asset_id for link in task.output_assets] == ["asset_old_video"]
    finally:
        session.close()

    failed_job = dict(response.json())
    failed_job["status"] = "FAILED"
    failed_job["outputAssets"] = []
    record_job_status(failed_job, resolve_asset=None)
    session = SessionLocal()
    try:
        task = session.get(WorkflowTask, "task_prompt_requeue")
        assert [link.asset_id for link in task.output_assets] == ["asset_old_video"]
    finally:
        session.close()

    session = SessionLocal()
    try:
        session.add(Asset(id="asset_new_video", asset_type="output", file_name="new.mp4", mime_type="video/mp4", size_bytes=1, storage_key="outputs/new.mp4", metadata_json={}))
        session.commit()
    finally:
        session.close()
    completed_job = dict(response.json())
    completed_job["status"] = "COMPLETED"
    completed_job["outputAssets"] = [{"assetId": "asset_new_video", "outputRole": "final"}]
    record_job_status(completed_job, resolve_asset=None)
    session = SessionLocal()
    try:
        task = session.get(WorkflowTask, "task_prompt_requeue")
        assert [link.asset_id for link in task.output_assets] == ["asset_new_video"]
        assert "preserveOutputAssetsUntilSuccess" not in task.payload_json
    finally:
        session.close()
