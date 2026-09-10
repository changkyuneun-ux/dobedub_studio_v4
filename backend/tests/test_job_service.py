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


def test_completed_runpod_job_status_retries_unsaved_outputs_without_provider_poll():
    saved_calls = []
    recorded = []
    job = {
        "taskId": "task_completed_unsaved",
        "runpodJobId": "runpod-completed-unsaved",
        "executionMode": "runpod",
        "workflowId": "1-images.json",
        "status": "COMPLETED",
        "progress": 100,
        "createdAt": 1_000_000.0,
        "startedAt": "2026-09-08 23:00:00",
        "runpodStatus": {"status": "COMPLETED", "id": "runpod-completed-unsaved"},
        "historySaved": True,
        "outputsSaved": False,
        "outputAssets": [],
    }

    runtime = _runtime_with_job(job)
    runtime.save_runpod_outputs = lambda result, stored_job: saved_calls.append((result, stored_job["taskId"])) or {
        "assets": [{
            "assetId": "asset_s3_output",
            "downloadUrl": "/api/files/asset_s3_output",
            "outputRole": "final",
        }],
        "remoteUrls": [],
    }
    runtime.record_job = lambda stored_job: recorded.append(stored_job.copy())

    result = job_service.job_status(runtime, "task_completed_unsaved")

    assert saved_calls == [({"status": "COMPLETED", "id": "runpod-completed-unsaved"}, "task_completed_unsaved")]
    assert result["outputUrl"] == "/api/files/asset_s3_output"
    assert result["outputAssets"][0]["assetId"] == "asset_s3_output"
    assert job["outputsSaved"] is True
    assert recorded


def test_completed_runpod_status_is_persisted_when_output_save_fails():
    recorded = []
    job = {
        "taskId": "task_completed_output_failure",
        "runpodJobId": "runpod-completed-output-failure",
        "executionMode": "runpod",
        "workflowId": "1-images.json",
        "status": "IN_PROGRESS",
        "progress": 45,
        "createdAt": 1_000_000.0,
        "startedAt": "2026-09-10 08:47:00",
        "runpodStatus": {"status": "IN_PROGRESS", "id": "runpod-completed-output-failure"},
        "outputsSaved": False,
        "outputAssets": [],
    }

    runtime = _runtime_with_job(job)
    runtime.runpod_request = lambda *_args, **_kwargs: {
        "status": "COMPLETED",
        "id": "runpod-completed-output-failure",
        "output": {"images": [{"data": "video", "filename": "result.mp4"}]},
    }
    runtime.save_runpod_outputs = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("S3 write failed"))
    runtime.record_job = lambda stored_job: recorded.append(stored_job.copy())

    result, _elapsed, progress = job_service.poll_runpod_job(runtime, job)

    assert result["status"] == "COMPLETED"
    assert progress == 100
    assert job["status"] == "COMPLETED"
    assert job["outputsSaved"] is False
    assert job["outputSaveError"] == "S3 write failed"
    assert recorded[0]["status"] == "COMPLETED"
    assert recorded[-1]["runpodStatus"]["outputSaveError"] == "S3 write failed"
    assert recorded[-1]["runpodStatus"]["outputImportStatus"] == "PENDING"


def test_runpod_submission_logs_generation_snapshot_before_provider_request(caplog):
    payload = {"taskId": "task_submission_log", "workflowId": "1-images_81.json", "resolutionTier": "hd"}
    runtime = job_service.JobRuntime(
        jobs={},
        dry_run=False,
        prepare_workflow_for_job=lambda _payload: ({}, [], {"generation": [{"nodeId": "98", "width": 832, "height": 480, "length": 81, "resolutionTier": "hd"}]}),
        build_runpod_payload=lambda _workflow, _images, _payload: {"input": {}},
        runpod_request=lambda *_args: {"id": "runpod-submission-log"},
        save_runpod_outputs=lambda *_args: {"assets": [], "remoteUrls": []},
        append_history=lambda _job: [],
        build_wan_node_config_snapshot=lambda _workflow_id, _segments: {},
        hydrate_input_images=lambda _job: [],
    )

    with caplog.at_level("INFO", logger="backend.app.services.job_service"):
        job_service.submit_runpod_job(runtime, payload)

    assert "runpod_submission_snapshot" in caplog.text
    assert '"taskId": "task_submission_log"' in caplog.text
    assert '"resolutionTier": "hd"' in caplog.text
