from __future__ import annotations

from datetime import timedelta

from backend.app.core.timezone_utils import now_seoul_naive
from backend.app.db.models import WorkflowTask
from backend.app.services import job_service
from backend.app.services.runpod_dispatch_service import RunpodDispatchRuntime, dispatch_next_pending_submission
from backend.app.services.task_policy_service import active_task_counts
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


def test_dispatcher_waits_for_idle_worker_then_dispatches_one_task(monkeypatch):
    calls: list[str] = []
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


def test_dispatcher_checks_worker_capacity_even_when_legacy_dry_run_is_enabled(monkeypatch):
    calls: list[str] = []
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
