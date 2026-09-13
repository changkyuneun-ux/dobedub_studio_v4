from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from backend.app.core.timezone_utils import now_seoul_naive
from backend.app.db.models import Asset, ImagePromptDraft, TaskExecutionPolicy, User, WorkflowTask
from backend.app.services import job_service
from backend.app.services.runpod_dispatch_service import RunpodDispatchRuntime, dispatch_next_pending_submission
from backend.app.services.runpod_request_batch_service import request_batch_queue
from backend.app.services import studio_api_service
from backend.app.services.task_policy_service import TaskSubmissionLimitError, active_task_counts
from backend.app.services.task_tracking_service import claim_next_pending_submission, release_pending_submission


def _runtime(*, dry_run: bool, calls: list[tuple[str, str, dict | None]]) -> job_service.JobRuntime:
    def prepare(payload: dict):
        return {"1": {"class_type": "KSampler", "inputs": {}}}, [{"name": "input.png", "path": "/tmp/input.png"}], {
            "seed": {"mode": "automatic", "value": 1234},
            "requestSnapshot": {"workflowId": payload["workflowId"]},
        }

    def request(method: str, path: str, payload=None):
        calls.append((method, path, payload))
        return {"id": "runpod_queued_1"}

    return job_service.JobRuntime(
        jobs={},
        dry_run=dry_run,
        prepare_workflow_for_job=prepare,
        build_runpod_payload=lambda workflow, images: {"input": {"workflow": workflow, "images": images}},
        runpod_request=request,
        save_runpod_outputs=lambda _result, _job: {"assets": [], "remoteUrls": []},
        append_history=lambda _item: [],
        build_wan_node_config_snapshot=lambda _workflow_id, _segments: {},
        hydrate_input_images=lambda _item: [],
    )


def _payload() -> dict:
    return {
        "workflowId": "1-images.json",
        "keyframes": [{"index": 1, "uploadId": "asset_1", "fileName": "input.png"}],
        "segments": [{"index": 1, "positivePrompt": "walk", "negativePromptAddition": "blur", "config": {"frames": 81}}],
        "user": {"id": "operator", "name": "Operator"},
    }


def test_queue_job_defers_runpod_submission_until_dispatch():
    calls: list[tuple[str, str, dict | None]] = []
    runtime = _runtime(dry_run=False, calls=calls)

    job = job_service.queue_job(runtime, _payload())

    assert job["status"] == "PENDING_SUBMIT"
    assert job["runpodJobId"] == ""
    assert job["generationSeed"] == 1234
    assert job["workflowName"] == "1-images"
    assert calls == []

    dispatched = job_service.dispatch_queued_job(runtime, job)

    assert dispatched["status"] == "QUEUED"
    assert dispatched["runpodJobId"] == "runpod_queued_1"
    assert [call[:2] for call in calls] == [("POST", "/run")]


def test_pending_submission_does_not_consume_runpod_execution_policy_capacity(db_session):
    db_session.add(WorkflowTask(
        id="task_pending_policy",
        workflow_id="1-images.json",
        user_id=None,
        status="PENDING_SUBMIT",
    ))
    db_session.commit()

    counts = active_task_counts(db_session, "missing-user")

    assert counts["activeTotal"] == 0


def test_create_job_keeps_local_queue_open_when_active_policy_is_full(db_session, monkeypatch):
    db_session.add_all([
        TaskExecutionPolicy(id=1, max_active_tasks_per_user=1, max_active_tasks_total=1),
        WorkflowTask(
            id="task_active_policy",
            workflow_id="1-images.json",
            user_id="operator",
            status="IN_PROGRESS",
        ),
    ])
    db_session.commit()
    calls: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(studio_api_service, "job_runtime", lambda: _runtime(dry_run=False, calls=calls))

    job = studio_api_service.create_job(_payload(), user={"id": "operator", "name": "Operator"})

    assert job["status"] == "PENDING_SUBMIT"
    assert job["runpodJobId"] == ""
    assert calls == []


def test_create_job_reuses_existing_prompt_draft_task_instead_of_creating_a_second_one(db_session, monkeypatch):
    db_session.add(WorkflowTask(
        id="task_existing_prompt_draft",
        workflow_id="1-images.json",
        user_id="operator",
        worker_name="Operator",
        status="FAILED",
        prompt_draft_id="grok_draft_single_task",
        payload_json={**_payload(), "promptDraftId": "grok_draft_single_task"},
    ))
    db_session.commit()
    calls: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(studio_api_service, "job_runtime", lambda: _runtime(dry_run=False, calls=calls))

    job = studio_api_service.create_job(
        {**_payload(), "promptDraftId": "grok_draft_single_task"},
        user={"id": "operator", "name": "Operator"},
    )

    assert job["taskId"] == "task_existing_prompt_draft"
    tasks = db_session.scalars(
        select(WorkflowTask).where(WorkflowTask.prompt_draft_id == "grok_draft_single_task")
    ).all()
    assert [task.id for task in tasks] == ["task_existing_prompt_draft"]
    assert calls == []


def test_create_job_carries_batch_id_onto_existing_prompt_draft_task(db_session, monkeypatch):
    db_session.add(WorkflowTask(
        id="task_existing_unlabelled_batch",
        workflow_id="1-images.json",
        user_id="operator",
        worker_name="Operator",
        status="PENDING_SUBMIT",
        prompt_draft_id="grok_draft_missing_batch",
        payload_json={**_payload(), "promptDraftId": "grok_draft_missing_batch"},
    ))
    db_session.commit()
    calls: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(studio_api_service, "job_runtime", lambda: _runtime(dry_run=False, calls=calls))

    job = studio_api_service.create_job(
        {**_payload(), "promptDraftId": "grok_draft_missing_batch", "batchJobId": "worker_upload_260906"},
        user={"id": "operator", "name": "Operator"},
    )

    assert job["taskId"] == "task_existing_unlabelled_batch"
    db_session.expire_all()
    stored = db_session.get(WorkflowTask, "task_existing_unlabelled_batch")
    assert stored.batch_job_id == "worker_upload_260906"
    assert stored.payload_json["batchJobId"] == "worker_upload_260906"
    assert calls == []


def test_runpod_request_queue_excludes_failed_prompt_generation_drafts(db_session):
    db_session.add(User(
        id="operator",
        name="Operator",
        email=None,
        role="OPERATOR",
        permissions_json=[],
        is_active=True,
    ))
    db_session.add_all([
        Asset(id="asset_queue_ready", asset_type="input_image", file_name="ready.png", mime_type="image/png", size_bytes=1, storage_key="uploads/ready.png"),
        Asset(id="asset_queue_failed", asset_type="input_image", file_name="failed.png", mime_type="image/png", size_bytes=1, storage_key="uploads/failed.png"),
        Asset(id="asset_queue_manual", asset_type="input_image", file_name="manual.png", mime_type="image/png", size_bytes=1, storage_key="uploads/manual.png"),
        ImagePromptDraft(
            id="draft_queue_ready",
            asset_id="asset_queue_ready",
            workflow_id="1-images.json",
            slot_index=1,
            status="READY",
            model="grok",
            positive_prompt="ready prompt",
            created_by="operator",
        ),
        ImagePromptDraft(
            id="draft_queue_failed",
            asset_id="asset_queue_failed",
            workflow_id="1-images.json",
            slot_index=2,
            status="FAILED",
            model="grok",
            failure_message="grok failed",
            created_by="operator",
        ),
        ImagePromptDraft(
            id="draft_queue_manual",
            asset_id="asset_queue_manual",
            workflow_id="1-images.json",
            slot_index=3,
            status="MANUAL_REQUIRED",
            model="grok",
            positive_prompt="",
            failure_message="empty prompt",
            created_by="operator",
        ),
    ])
    db_session.commit()

    queue = request_batch_queue(db_session, created_by="operator")

    assert [item["promptDraftId"] for item in queue["items"]] == ["draft_queue_ready"]


def test_dispatch_checks_active_policy_before_calling_runpod(db_session, monkeypatch):
    db_session.add_all([
        TaskExecutionPolicy(id=1, max_active_tasks_per_user=1, max_active_tasks_total=1),
        WorkflowTask(
            id="task_active_dispatch_policy",
            workflow_id="1-images.json",
            user_id="operator",
            status="IN_PROGRESS",
        ),
        WorkflowTask(
            id="task_waiting_dispatch_policy",
            workflow_id="1-images.json",
            user_id="operator",
            status="DISPATCHING",
            payload_json=_payload(),
        ),
    ])
    db_session.commit()
    monkeypatch.setattr(
        job_service,
        "dispatch_queued_job",
        lambda _runtime, _job: (_ for _ in ()).throw(AssertionError("RunPod should not receive over-limit tasks")),
    )

    try:
        studio_api_service._dispatch_pending_job("task_waiting_dispatch_policy")
    except TaskSubmissionLimitError:
        pass
    else:
        raise AssertionError("expected dispatch to enforce active policy")


def test_claim_and_release_keep_task_waiting_until_capacity_is_available(db_session):
    task = WorkflowTask(
        id="task_pending_dispatch",
        workflow_id="1-images.json",
        status="PENDING_SUBMIT",
        created_at=now_seoul_naive() - timedelta(seconds=1),
    )
    db_session.add(task)
    db_session.commit()

    claimed = claim_next_pending_submission()

    assert claimed is not None
    assert claimed["taskId"] == "task_pending_dispatch"
    assert claimed["status"] == "DISPATCHING"

    release_pending_submission("task_pending_dispatch", "no idle worker", retry_after_seconds=15)
    db_session.expire_all()
    stored = db_session.get(WorkflowTask, "task_pending_dispatch")
    assert stored.status == "PENDING_SUBMIT"
    assert stored.last_dispatch_error == "no idle worker"
    assert stored.next_dispatch_at is not None


def test_claim_recovers_stale_dispatching_submission_without_runpod_job(db_session):
    stale_claimed_at = now_seoul_naive() - timedelta(minutes=10)
    db_session.add_all([
        WorkflowTask(
            id="task_stale_dispatch",
            workflow_id="1-images.json",
            status="DISPATCHING",
            runpod_job_id=None,
            dispatch_claimed_at=stale_claimed_at,
            dispatch_attempts=1,
            created_at=stale_claimed_at,
        ),
        WorkflowTask(
            id="task_recent_dispatch",
            workflow_id="1-images.json",
            status="DISPATCHING",
            runpod_job_id=None,
            dispatch_claimed_at=now_seoul_naive(),
            dispatch_attempts=1,
        ),
    ])
    db_session.commit()

    claimed = claim_next_pending_submission()

    assert claimed is not None
    assert claimed["taskId"] == "task_stale_dispatch"
    db_session.expire_all()
    recovered = db_session.get(WorkflowTask, "task_stale_dispatch")
    recent = db_session.get(WorkflowTask, "task_recent_dispatch")
    assert recovered.status == "DISPATCHING"
    assert recovered.dispatch_attempts == 2
    assert recovered.dispatch_claimed_at is not None
    assert recovered.dispatch_claimed_at > stale_claimed_at
    assert recovered.last_dispatch_error == "Recovered stale RunPod submission claim"
    assert recent.status == "DISPATCHING"
    assert recent.dispatch_attempts == 1


def test_dispatcher_waits_for_idle_worker_then_dispatches_one_task(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.app.services.runpod_dispatch_service.recover_stale_dispatching_submissions",
        lambda: 0,
    )
    monkeypatch.setattr(
        "backend.app.services.runpod_dispatch_service.claim_next_pending_submission",
        lambda: {"taskId": "task_oldest", "status": "DISPATCHING"},
    )

    waiting = dispatch_next_pending_submission(RunpodDispatchRuntime(
        dry_run=False,
        connection_status=lambda: {"ok": True, "workers": {"idle": 0}},
        dispatch_task=lambda task_id: calls.append(task_id) or {"taskId": task_id},
    ))
    assert waiting["status"] == "waiting"
    assert calls == []

    dispatched = dispatch_next_pending_submission(RunpodDispatchRuntime(
        dry_run=False,
        connection_status=lambda: {"ok": True, "workers": {"idle": 1}},
        dispatch_task=lambda task_id: calls.append(task_id) or {"taskId": task_id, "runpodJobId": "rp_1"},
    ))
    assert dispatched == {"status": "dispatched", "taskId": "task_oldest", "runpodJobId": "rp_1"}
    assert calls == ["task_oldest"]


def test_dispatcher_recovers_stale_dispatching_claim_before_capacity_check(db_session):
    stale_claimed_at = now_seoul_naive() - timedelta(minutes=10)
    db_session.add(WorkflowTask(
        id="task_stale_waiting_capacity",
        workflow_id="1-images.json",
        status="DISPATCHING",
        runpod_job_id=None,
        dispatch_claimed_at=stale_claimed_at,
        dispatch_attempts=1,
        created_at=stale_claimed_at,
    ))
    db_session.commit()

    result = dispatch_next_pending_submission(RunpodDispatchRuntime(
        dry_run=False,
        connection_status=lambda: {"ok": True, "workers": {"idle": 0}},
        dispatch_task=lambda _task_id: (_ for _ in ()).throw(AssertionError("should not dispatch without capacity")),
    ))

    assert result["status"] == "waiting"
    db_session.expire_all()
    stored = db_session.get(WorkflowTask, "task_stale_waiting_capacity")
    assert stored.status == "PENDING_SUBMIT"
    assert stored.dispatch_claimed_at is None
    assert stored.last_dispatch_error == "Recovered stale RunPod submission claim"


def test_dispatcher_checks_worker_capacity_even_when_legacy_dry_run_is_enabled(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.app.services.runpod_dispatch_service.recover_stale_dispatching_submissions",
        lambda: 0,
    )
    monkeypatch.setattr(
        "backend.app.services.runpod_dispatch_service.claim_next_pending_submission",
        lambda: {"taskId": "task_oldest", "status": "DISPATCHING"},
    )

    result = dispatch_next_pending_submission(RunpodDispatchRuntime(
        dry_run=True,
        connection_status=lambda: {"ok": True, "workers": {"idle": 0}},
        dispatch_task=lambda task_id: calls.append(task_id) or {"taskId": task_id},
    ))

    assert result["status"] == "waiting"
    assert result["reason"] == "RunPod has no idle worker"
    assert calls == []


def test_dispatch_queued_job_does_not_replace_runpod_with_a_local_dry_run():
    calls: list[tuple[str, str, dict | None]] = []
    runtime = _runtime(dry_run=True, calls=calls)

    job = job_service.queue_job(runtime, _payload())
    dispatched = job_service.dispatch_queued_job(runtime, job)

    assert dispatched["executionMode"] == "runpod"
    assert dispatched["runpodJobId"] == "runpod_queued_1"
    assert [call[:2] for call in calls] == [("POST", "/run")]
