from __future__ import annotations

from datetime import timedelta

from backend.app.core.timezone_utils import now_seoul_naive
from backend.app.db.models import Asset, ImagePromptDraft, RunpodRequestBatch, RunpodRequestItem, User, WorkflowTask
from backend.app.services.runpod_dispatch_service import RunpodDispatchRuntime, dispatch_next_pending_submission
from backend.app.services.runpod_request_batch_service import (
    create_request_batch,
    request_batch_queue,
    request_batch_dashboard,
    request_batch_payload,
    refresh_request_batch_summary,
    sync_request_batch_for_task,
)


def _draft(asset_id: str, *, draft_id: str, positive: str, frames: int = 81) -> ImagePromptDraft:
    return ImagePromptDraft(
        id=draft_id,
        asset_id=asset_id,
        workflow_id="1-images.json",
        slot_index=1,
        status="READY",
        provider="grok",
        model="grok-test",
        instruction_version="1-images.json@1",
        positive_prompt=positive,
        negative_prompt="blur",
        requested_frames=frames,
        warnings_json=[],
        raw_json={},
        created_by="operator",
    )


def _asset(asset_id: str) -> Asset:
    return Asset(
        id=asset_id,
        asset_type="input_image",
        file_name=f"{asset_id}.png",
        mime_type="image/png",
        size_bytes=1,
        storage_backend="local",
        storage_key=f"inputs/{asset_id}.png",
        image_width=720,
        image_height=1280,
    )


def test_request_batch_keeps_immutable_per_image_prompt_and_length_snapshots(db_session):
    db_session.add_all([
        _asset("asset_request_1"),
        _asset("asset_request_2"),
        _draft("asset_request_1", draft_id="draft_request_1", positive="first prompt", frames=49),
        _draft("asset_request_2", draft_id="draft_request_2", positive="second prompt", frames=81),
    ])
    db_session.commit()

    batch = create_request_batch(
        db_session,
        created_by="operator",
        items=[
            {"promptDraftId": "draft_request_1", "workflowId": "Pickme_Workflow.json", "requestedFrames": 161},
            {"promptDraftId": "draft_request_2", "requestedFrames": 49},
        ],
    )

    # Source drafts remain editable, but an already queued RunPod request must
    # retain the values the user actually submitted.
    source = db_session.get(ImagePromptDraft, "draft_request_1")
    assert source is not None
    source.positive_prompt = "later editor change"
    source.requested_frames = 49
    db_session.commit()

    snapshot = request_batch_payload(db_session, batch["id"], created_by="operator")
    assert snapshot["requestedCount"] == 2
    assert [(item["workflowId"], item["positivePrompt"], item["requestedFrames"]) for item in snapshot["items"]] == [
        ("Pickme_Workflow.json", "first prompt", 161),
        ("1-images.json", "second prompt", 49),
    ]


def test_request_batch_keeps_worker_owner_separate_from_submitter(db_session):
    db_session.add_all([
        User(id="worker", name="작업자", role="OPERATOR"),
        User(id="manager", name="관리자", role="ADMIN"),
        _asset("asset_owned_request"),
        ImagePromptDraft(
            id="draft_owned_request",
            asset_id="asset_owned_request",
            workflow_id="1-images.json",
            slot_index=1,
            status="READY",
            provider="grok",
            model="grok-test",
            instruction_version="1-images.json@1",
            positive_prompt="worker prompt",
            negative_prompt="blur",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            created_by="worker",
        ),
    ])
    db_session.commit()

    batch = create_request_batch(
        db_session,
        created_by="worker",
        submitted_by="manager",
        items=[{"promptDraftId": "draft_owned_request"}],
    )

    assert batch["createdBy"] == "worker"
    assert batch["createdByName"] == "작업자"
    assert batch["submittedBy"] == "manager"
    assert batch["submittedByName"] == "관리자"
    assert batch["items"][0]["workerId"] == "worker"
    assert batch["items"][0]["workerName"] == "작업자"


def test_request_batch_allows_its_submitter_to_read_without_transferring_worker_ownership(db_session):
    db_session.add_all([
        User(id="worker_reader", name="작업자", role="OPERATOR"),
        User(id="manager_reader", name="관리자", role="ADMIN"),
        _asset("asset_request_reader"),
        ImagePromptDraft(
            id="draft_request_reader",
            asset_id="asset_request_reader",
            workflow_id="1-images.json",
            slot_index=1,
            status="READY",
            provider="grok",
            model="grok-test",
            instruction_version="1-images.json@1",
            positive_prompt="worker-owned prompt",
            negative_prompt="blur",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            created_by="worker_reader",
        ),
    ])
    db_session.commit()
    batch = create_request_batch(
        db_session,
        created_by="worker_reader",
        submitted_by="manager_reader",
        items=[{"promptDraftId": "draft_request_reader"}],
    )

    visible_to_submitter = request_batch_payload(
        db_session,
        batch["id"],
        actor_id="manager_reader",
    )

    assert visible_to_submitter["createdBy"] == "worker_reader"
    assert visible_to_submitter["submittedBy"] == "manager_reader"
    assert visible_to_submitter["items"][0]["workerId"] == "worker_reader"


def test_request_batch_dashboard_groups_counts_by_worker_owner(db_session):
    draft_a = _draft("asset_dashboard_a", draft_id="draft_dashboard_a", positive="first prompt")
    draft_a.created_by = "worker_dashboard_a"
    draft_b = _draft("asset_dashboard_b", draft_id="draft_dashboard_b", positive="second prompt")
    draft_b.created_by = "worker_dashboard_b"
    db_session.add_all([
        User(id="worker_dashboard_a", name="작업자 A", role="OPERATOR"),
        User(id="worker_dashboard_b", name="작업자 B", role="OPERATOR"),
        User(id="manager_dashboard", name="관리자", role="ADMIN"),
        _asset("asset_dashboard_a"),
        _asset("asset_dashboard_b"),
        draft_a,
        draft_b,
    ])
    db_session.commit()

    create_request_batch(
        db_session,
        created_by="worker_dashboard_a",
        submitted_by="manager_dashboard",
        items=[{"promptDraftId": "draft_dashboard_a"}],
    )
    create_request_batch(
        db_session,
        created_by="worker_dashboard_b",
        submitted_by="manager_dashboard",
        items=[{"promptDraftId": "draft_dashboard_b"}],
    )

    dashboard = request_batch_dashboard(db_session)
    by_worker = {item["workerId"]: item for item in dashboard["workers"]}

    assert dashboard["totals"]["requestWaiting"] == 2
    assert by_worker["worker_dashboard_a"]["workerName"] == "작업자 A"
    assert by_worker["worker_dashboard_a"]["requestWaiting"] == 1
    assert by_worker["worker_dashboard_b"]["requestWaiting"] == 1


def test_request_queue_and_dashboard_share_one_filtered_incomplete_scope(db_session):
    """The dashboard must count the same pending rows the request screen lists."""
    db_session.add_all([
        _asset("asset_queue_1"),
        _asset("asset_queue_2"),
        _asset("asset_queue_3"),
        _draft("asset_queue_1", draft_id="draft_queue_1", positive="first"),
        _draft("asset_queue_2", draft_id="draft_queue_2", positive="second"),
        _draft("asset_queue_3", draft_id="draft_queue_3", positive="third"),
    ])
    db_session.commit()

    batch = create_request_batch(
        db_session,
        created_by="operator",
        items=[
            {"promptDraftId": "draft_queue_1"},
            {"promptDraftId": "draft_queue_2"},
        ],
    )
    in_progress_item = db_session.get(RunpodRequestItem, batch["items"][1]["id"])
    assert in_progress_item is not None
    in_progress_item.status = "IN_PROGRESS"
    refresh_request_batch_summary(db_session, batch["id"])
    db_session.commit()

    first_page = request_batch_queue(db_session, created_by="operator", page=1, page_size=2)
    second_page = request_batch_queue(db_session, created_by="operator", page=2, page_size=2)
    dashboard = request_batch_dashboard(db_session, created_by="operator")

    assert first_page["total"] == 3
    assert first_page["page"] == 1
    assert first_page["pageSize"] == 2
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1
    assert {item["promptDraftId"] for item in first_page["items"] + second_page["items"]} == {
        "draft_queue_1",
        "draft_queue_2",
        "draft_queue_3",
    }
    assert dashboard["totals"] == {
        "incomplete": 3,
        "requestWaiting": 2,
        "runpodQueued": 0,
        "inProgress": 1,
        "failed": 0,
    }


def test_request_queue_status_filter_limits_requestable_rows_and_dashboard_scope(db_session):
    db_session.add_all([
        _asset("asset_filter_ready"),
        _asset("asset_filter_pending"),
        _asset("asset_filter_queued"),
        _asset("asset_filter_progress"),
        _asset("asset_filter_failed"),
        _draft("asset_filter_ready", draft_id="draft_filter_ready", positive="ready"),
        _draft("asset_filter_pending", draft_id="draft_filter_pending", positive="pending"),
        _draft("asset_filter_queued", draft_id="draft_filter_queued", positive="queued"),
        _draft("asset_filter_progress", draft_id="draft_filter_progress", positive="progress"),
        _draft("asset_filter_failed", draft_id="draft_filter_failed", positive="failed"),
    ])
    db_session.commit()

    batch = create_request_batch(
        db_session,
        created_by="operator",
        items=[
            {"promptDraftId": "draft_filter_pending"},
            {"promptDraftId": "draft_filter_queued"},
            {"promptDraftId": "draft_filter_progress"},
            {"promptDraftId": "draft_filter_failed"},
        ],
    )
    by_draft = {item["promptDraftId"]: db_session.get(RunpodRequestItem, item["id"]) for item in batch["items"]}
    by_draft["draft_filter_queued"].status = "IN_QUEUE"
    by_draft["draft_filter_progress"].status = "IN_PROGRESS"
    by_draft["draft_filter_failed"].status = "FAILED"
    refresh_request_batch_summary(db_session, batch["id"])
    db_session.commit()

    all_rows = request_batch_queue(db_session, created_by="operator", page=1, page_size=10)
    requestable = request_batch_queue(db_session, created_by="operator", status_filter="requestable")
    requestable_dashboard = request_batch_dashboard(db_session, created_by="operator", status_filter="requestable")
    progress = request_batch_queue(db_session, created_by="operator", status_filter="inProgress")

    assert all_rows["total"] == 5
    assert [(item["kind"], item["promptDraftId"], item["canSubmit"]) for item in requestable["items"]] == [
        ("PROMPT_DRAFT", "draft_filter_ready", True),
    ]
    assert requestable_dashboard["totals"] == {
        "incomplete": 1,
        "requestWaiting": 1,
        "runpodQueued": 0,
        "inProgress": 0,
        "failed": 0,
    }
    assert progress["total"] == 1
    assert progress["items"][0]["promptDraftId"] == "draft_filter_progress"


def test_failed_pre_submission_request_does_not_hide_unrequested_ready_draft(db_session):
    """A draft with no WorkflowTask is still unrequested even after a failed batch attempt."""
    db_session.add_all([
        _asset("asset_failed_before_task"),
        _draft("asset_failed_before_task", draft_id="draft_failed_before_task", positive="retryable"),
        RunpodRequestBatch(
            id="rpb_failed_before_task",
            workflow_id="1-images.json",
            requested_count=1,
            queued_count=0,
            failed_count=1,
            status="FAILED",
            created_by="operator",
            submitted_by="operator",
        ),
        RunpodRequestItem(
            id="rpi_failed_before_task",
            request_batch_id="rpb_failed_before_task",
            sequence_no=1,
            prompt_draft_id="draft_failed_before_task",
            asset_id="asset_failed_before_task",
            workflow_id="1-images.json",
            positive_prompt="retryable",
            requested_frames=81,
            status="FAILED",
            failure_message="RunPod task was not created",
        ),
    ])
    db_session.commit()

    queue = request_batch_queue(db_session, created_by="operator", page=1, page_size=10)
    dashboard = request_batch_dashboard(db_session, created_by="operator")

    assert [(item["kind"], item["promptDraftId"], item["canSubmit"]) for item in queue["items"]] == [
        ("PROMPT_DRAFT", "draft_failed_before_task", True),
    ]
    assert dashboard["totals"]["requestWaiting"] == 1


def test_success_request_item_is_not_counted_as_incomplete_queue_data(db_session):
    """Dirty legacy SUCCESS item rows must not make queue totals diverge from the dashboard."""
    db_session.add_all([
        _asset("asset_success_item"),
        RunpodRequestBatch(
            id="rpb_success_item",
            workflow_id="1-images.json",
            requested_count=1,
            completed_count=1,
            status="QUEUED",
            created_by="operator",
            submitted_by="operator",
        ),
        RunpodRequestItem(
            id="rpi_success_item",
            request_batch_id="rpb_success_item",
            sequence_no=1,
            prompt_draft_id=None,
            asset_id="asset_success_item",
            workflow_id="1-images.json",
            positive_prompt="already done",
            requested_frames=81,
            status="SUCCESS",
            task_id="task_success_item",
        ),
        WorkflowTask(
            id="task_success_item",
            workflow_id="1-images.json",
            status="SUCCESS",
        ),
    ])
    db_session.commit()

    queue = request_batch_queue(db_session, created_by="operator")
    dashboard = request_batch_dashboard(db_session, created_by="operator")

    assert queue["total"] == 0
    assert queue["items"] == []
    assert dashboard["totals"] == {
        "incomplete": 0,
        "requestWaiting": 0,
        "runpodQueued": 0,
        "inProgress": 0,
        "failed": 0,
    }


def test_request_batch_summary_follows_persisted_task_status(db_session):
    db_session.add_all([
        _asset("asset_request_status"),
        _draft("asset_request_status", draft_id="draft_request_status", positive="walk forward"),
    ])
    db_session.commit()
    batch = create_request_batch(
        db_session,
        created_by="operator",
        items=[{"promptDraftId": "draft_request_status", "requestedFrames": 81}],
    )
    item_id = batch["items"][0]["id"]
    task = WorkflowTask(
        id="task_request_status",
        workflow_id="1-images.json",
        status="PENDING_SUBMIT",
        request_batch_id=batch["id"],
        request_item_id=item_id,
    )
    db_session.add(task)
    sync_request_batch_for_task(db_session, task)
    db_session.commit()

    queued = request_batch_payload(db_session, batch["id"], created_by="operator")
    assert queued["status"] == "QUEUED"
    assert queued["queuedCount"] == 1
    assert queued["items"][0]["taskId"] == "task_request_status"

    task.status = "SUCCESS"
    sync_request_batch_for_task(db_session, task)
    db_session.commit()

    completed = request_batch_payload(db_session, batch["id"], created_by="operator")
    assert completed["status"] == "COMPLETED"
    assert completed["completedCount"] == 1
    assert completed["items"][0]["status"] == "COMPLETED"


def test_request_batch_repairs_legacy_task_link_from_immutable_payload(db_session):
    """A queued task keeps its batch link even when an older writer missed columns."""
    db_session.add_all([
        _asset("asset_request_repair"),
        _draft("asset_request_repair", draft_id="draft_request_repair", positive="turn toward camera"),
    ])
    db_session.commit()
    batch = create_request_batch(
        db_session,
        created_by="operator",
        items=[{"promptDraftId": "draft_request_repair", "requestedFrames": 81}],
    )
    item_id = batch["items"][0]["id"]
    task = WorkflowTask(
        id="task_request_repair",
        workflow_id="1-images.json",
        status="IN_PROGRESS",
        # Matches the historic records that were written before the task
        # tracking layer copied request IDs out of payload_json.
        payload_json={
            "requestBatchId": batch["id"],
            "requestItemId": item_id,
        },
    )
    db_session.add(task)
    db_session.flush()
    item = db_session.get(RunpodRequestItem, item_id)
    assert item is not None
    item.task_id = task.id
    db_session.commit()

    repaired = request_batch_payload(db_session, batch["id"], created_by="operator")

    db_session.expire_all()
    stored = db_session.get(WorkflowTask, task.id)
    assert stored is not None
    assert stored.request_batch_id == batch["id"]
    assert stored.request_item_id == item_id
    assert repaired["inProgressCount"] == 1
    assert repaired["items"][0]["status"] == "IN_PROGRESS"


def test_dispatcher_claims_only_the_oldest_pending_task_when_one_worker_is_idle(db_session):
    now = now_seoul_naive()
    db_session.add_all([
        WorkflowTask(
            id="task_dispatch_oldest",
            workflow_id="1-images.json",
            status="PENDING_SUBMIT",
            created_at=now - timedelta(minutes=1),
        ),
        WorkflowTask(
            id="task_dispatch_next",
            workflow_id="1-images.json",
            status="PENDING_SUBMIT",
            created_at=now,
        ),
    ])
    db_session.commit()
    submitted: list[str] = []

    result = dispatch_next_pending_submission(RunpodDispatchRuntime(
        dry_run=False,
        connection_status=lambda: {"ok": True, "workers": {"idle": 1}},
        dispatch_task=lambda task_id: submitted.append(task_id) or {"taskId": task_id, "runpodJobId": "rp_1"},
    ))

    db_session.expire_all()
    assert result == {"status": "dispatched", "taskId": "task_dispatch_oldest", "runpodJobId": "rp_1"}
    assert submitted == ["task_dispatch_oldest"]
    assert db_session.get(WorkflowTask, "task_dispatch_oldest").status == "DISPATCHING"
    assert db_session.get(WorkflowTask, "task_dispatch_next").status == "PENDING_SUBMIT"


def test_dispatcher_releases_claimed_task_after_provider_submission_failure(db_session):
    db_session.add(WorkflowTask(
        id="task_dispatch_failure",
        workflow_id="1-images.json",
        status="PENDING_SUBMIT",
    ))
    db_session.commit()

    def reject_provider(_task_id: str) -> dict:
        raise RuntimeError("RunPod submit unavailable")

    result = dispatch_next_pending_submission(RunpodDispatchRuntime(
        dry_run=False,
        connection_status=lambda: {"ok": True, "workers": {"idle": 1}},
        dispatch_task=reject_provider,
    ))

    db_session.expire_all()
    restored = db_session.get(WorkflowTask, "task_dispatch_failure")
    assert result == {
        "status": "deferred",
        "taskId": "task_dispatch_failure",
        "reason": "RunPod submit unavailable",
    }
    assert restored.status == "PENDING_SUBMIT"
    assert restored.dispatch_attempts == 1
    assert restored.last_dispatch_error == "RunPod submit unavailable"
    assert restored.next_dispatch_at is not None
