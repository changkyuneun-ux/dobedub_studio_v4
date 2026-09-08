from __future__ import annotations

import pytest

from backend.app.services import job_service


def _runtime_with_job(job: dict) -> job_service.JobRuntime:
    def unexpected_runpod_request(*_args, **_kwargs):
        raise AssertionError("terminal RunPod jobs must use the stored status")

    return job_service.JobRuntime(
        jobs={job["taskId"]: job},
        dry_run=False,
        prepare_workflow_for_job=lambda _payload: ({}, [], {}),
        build_runpod_payload=lambda _workflow, _images: {"input": {}},
        runpod_request=unexpected_runpod_request,
        save_runpod_outputs=lambda _result, _job: {"assets": [], "remoteUrls": []},
        append_history=lambda _job: [],
        build_wan_node_config_snapshot=lambda _workflow_id, _segments: {},
        hydrate_input_images=lambda _job: [],
        record_job=lambda _job: None,
    )


def test_completed_runpod_job_status_uses_stored_terminal_state_without_provider_poll():
    job = {
        "taskId": "task_completed_1",
        "runpodJobId": "runpod-completed-1",
        "executionMode": "runpod",
        "workflowId": "1-images.json",
        "status": "COMPLETED",
        "progress": 100,
        "createdAt": 1_000_000.0,
        "startedAt": "2026-09-08 23:00:00",
        "runpodStatus": {"status": "COMPLETED", "id": "runpod-completed-1"},
        "historySaved": True,
        "outputsSaved": True,
        "outputAssets": [],
    }

    result = job_service.job_status(_runtime_with_job(job), "task_completed_1")

    assert result["rawStatus"] == "COMPLETED"
    assert result["status"] == "success"
    assert result["progress"] == 100
