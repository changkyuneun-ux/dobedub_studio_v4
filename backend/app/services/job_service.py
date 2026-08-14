from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable

from backend.app.core.timezone_utils import now_seoul_naive


TERMINAL_RUNPOD_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


@dataclass
class JobRuntime:
    jobs: dict[str, dict]
    dry_run: bool
    prepare_workflow_for_job: Callable[[dict], tuple[dict, list[dict], dict]]
    build_runpod_payload: Callable[[dict, list[dict]], dict]
    runpod_request: Callable[[str, str, dict | None], dict]
    save_runpod_outputs: Callable[[dict, dict], dict]
    append_history: Callable[[dict], list[dict]]
    build_wan_node_config_snapshot: Callable[[str, list[dict]], dict]
    hydrate_input_images: Callable[[dict], list[dict]]
    record_job: Callable[[dict], None] | None = None


def generation_seed_from_patch_summary(patch_summary: dict | None) -> int | None:
    value = ((patch_summary or {}).get("seed") or {}).get("value")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def config_without_seed(config: dict | None) -> dict:
    return {
        key: value
        for key, value in (config or {}).items()
        if str(key).lower() != "seed"
    }


def submit_runpod_job(runtime: JobRuntime, payload: dict) -> dict:
    workflow, images, patch_summary = runtime.prepare_workflow_for_job(payload)
    response = runtime.runpod_request("POST", "/run", runtime.build_runpod_payload(workflow, images))
    runpod_job_id = response.get("id")
    if not runpod_job_id:
        raise RuntimeError(f"RunPod response did not include job id: {response}")
    return {
        "runpodJobId": runpod_job_id,
        "patchSummary": patch_summary,
        "runpodSubmit": response,
    }


def create_job(runtime: JobRuntime, payload: dict) -> dict:
    now_seoul = now_seoul_naive()
    task_id = f"task_{now_seoul.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    now = time.time()
    workflow_id = payload.get("workflowId") or "unknown"
    segments = payload.get("segments") or []
    first_config = (segments[0].get("config") if segments else {}) or {}
    runpod_data = {
        "runpodJobId": f"dryrun_{uuid.uuid4().hex[:10]}",
        "patchSummary": {},
        "runpodSubmit": {},
    }
    execution_mode = "dry-run"
    if not runtime.dry_run:
        runpod_data = submit_runpod_job(runtime, payload)
        execution_mode = "runpod"
    else:
        # Dry-run must follow the same i2v input validation path as an actual
        # submission, otherwise an empty-image task can slip into history.
        _workflow, _images, patch_summary = runtime.prepare_workflow_for_job(payload)
        runpod_data["patchSummary"] = patch_summary
    runtime.jobs[task_id] = {
        "taskId": task_id,
        "runpodJobId": runpod_data["runpodJobId"],
        "executionMode": execution_mode,
        "workflowId": workflow_id,
        "status": "queued",
        "progress": 0,
        "createdAt": now,
        "startedAt": now_seoul.strftime("%Y-%m-%d %H:%M:%S"),
        "payload": payload,
        "firstConfig": first_config,
        "generationSeed": generation_seed_from_patch_summary(runpod_data.get("patchSummary")),
        "patchSummary": runpod_data.get("patchSummary") or {},
        "runpodSubmit": runpod_data.get("runpodSubmit") or {},
        "inputAssets": [
            keyframe.get("uploadId")
            for keyframe in (payload.get("keyframes") or [])
            if keyframe.get("uploadId")
        ],
    }
    record_job(runtime, runtime.jobs[task_id])
    return runtime.jobs[task_id]


def poll_runpod_job(runtime: JobRuntime, job: dict) -> tuple[dict, float, int]:
    if str(job.get("status", "")).upper() == "CANCELLED":
        return job.get("runpodStatus") or {"status": "CANCELLED"}, max(0, time.time() - job["createdAt"]), 100
    runpod_status = runtime.runpod_request("GET", f"/status/{job['runpodJobId']}", None)
    state = runpod_status.get("status", "UNKNOWN")
    elapsed = max(0, time.time() - job["createdAt"])
    progress_by_state = {
        "IN_QUEUE": 8,
        "IN_PROGRESS": 45,
        "COMPLETED": 100,
        "FAILED": 100,
        "CANCELLED": 100,
        "TIMED_OUT": 100,
    }
    progress = progress_by_state.get(state, job.get("progress", 12))
    job["status"] = state
    job["progress"] = progress
    job["runpodStatus"] = runpod_status

    if state == "COMPLETED" and not job.get("outputsSaved"):
        saved = runtime.save_runpod_outputs(runpod_status, job)
        job["outputAssets"] = saved["assets"]
        job["remoteOutputUrls"] = saved["remoteUrls"]
        final_asset = next((asset for asset in saved["assets"] if asset.get("outputRole") == "final"), None)
        job["outputUrl"] = (
            final_asset["downloadUrl"]
            if final_asset
            else saved["assets"][0]["downloadUrl"]
            if saved["assets"]
            else (saved["remoteUrls"][0] if saved["remoteUrls"] else "")
        )
        job["outputsSaved"] = True
    record_job(runtime, job)
    return runpod_status, elapsed, progress


def cancel_job(runtime: JobRuntime, task_id: str) -> dict:
    job = runtime.jobs.get(task_id)
    if not job:
        raise KeyError(task_id)
    status = str(job.get("status", "")).upper()
    if status in TERMINAL_RUNPOD_STATES:
        return job_status(runtime, task_id)
    cancel_response = {}
    if job.get("executionMode") == "runpod":
        cancel_response = runtime.runpod_request("POST", f"/cancel/{job['runpodJobId']}", None)
    else:
        cancel_response = {"status": "CANCELLED", "message": "Dry-run job cancelled locally."}
    job["status"] = "CANCELLED"
    job["progress"] = 100
    job["cancelRequested"] = True
    job["cancelledAt"] = now_seoul_naive().strftime("%Y-%m-%d %H:%M:%S")
    job["runpodCancel"] = cancel_response
    job["runpodStatus"] = {"status": "CANCELLED", "cancel": cancel_response}
    job["historySaved"] = True
    record_job(runtime, job)
    return job_status(runtime, task_id)


def job_status(runtime: JobRuntime, task_id: str) -> dict:
    job = runtime.jobs.get(task_id)
    if not job:
        raise KeyError(task_id)
    elapsed = max(0, time.time() - job["createdAt"])
    if job.get("executionMode") == "runpod":
        runpod_status, elapsed, progress = poll_runpod_job(runtime, job)
        terminal = runpod_status.get("status") in TERMINAL_RUNPOD_STATES
    else:
        progress = min(100, int(elapsed * 18))
        if progress >= 100:
            job["status"] = "success"
        elif progress > 10:
            job["status"] = "running"
        job["progress"] = progress
        terminal = progress >= 100

    if terminal and str(job.get("status", "")).upper() == "CANCELLED":
        job["historySaved"] = True
    elif terminal and not job.get("historySaved"):
        save_job_history(runtime, job)
        job["historySaved"] = True
        record_job(runtime, job)

    return {
        "taskId": task_id,
        "runpodJobId": job["runpodJobId"],
        "status": api_job_status(job),
        "rawStatus": job["status"],
        "elapsedSeconds": round(elapsed, 1),
        "progress": progress,
        "workerSummary": "RunPod serverless" if job.get("executionMode") == "runpod" else "dry-run worker",
        "statusLabel": localized_job_status(job),
        "message": job_status_message(job),
        "generationSeed": job.get("generationSeed"),
        "outputUrl": job.get("outputUrl", ""),
        "outputAssets": job.get("outputAssets", []),
        "cancelRequested": bool(job.get("cancelRequested")),
    }


def api_job_status(job: dict) -> str:
    status = str(job.get("status", "")).upper()
    if status in {"COMPLETED", "SUCCESS"}:
        return "success"
    if status in {"FAILED"}:
        return "fail"
    if status in {"CANCELLED"}:
        return "cancelled"
    if status in {"TIMED_OUT"}:
        return "timed_out"
    if status in {"IN_QUEUE", "QUEUED"}:
        return "queued"
    return "running"


def display_job_status(job: dict) -> str:
    status = str(job.get("status", "")).upper()
    if status in {"COMPLETED", "SUCCESS"}:
        return "Completed"
    if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
        return "Failed"
    return job.get("status", "running")


def localized_job_status(job: dict) -> str:
    status = str(job.get("status", "")).upper()
    labels = {
        "QUEUED": "대기",
        "IN_QUEUE": "대기",
        "IN_PROGRESS": "실행 중",
        "RUNNING": "실행 중",
        "COMPLETED": "완료",
        "SUCCESS": "완료",
        "FAILED": "실패",
        "CANCELLED": "취소됨",
        "TIMED_OUT": "시간 초과",
    }
    return labels.get(status, "확인 중")


def save_job_history(runtime: JobRuntime, job: dict):
    payload = job["payload"]
    user = payload.get("user") or {}
    segments = payload.get("segments") or []
    first_segment = segments[0] if segments else {}
    config = config_without_seed(first_segment.get("config") or job.get("firstConfig") or {})
    wan_node_config = runtime.build_wan_node_config_snapshot(job["workflowId"], segments)
    job["wanNodeConfig"] = wan_node_config
    runtime.append_history({
        "taskId": job["taskId"],
        "timestamp": job["startedAt"],
        "workflowId": job["workflowId"],
        "workflowName": job["workflowId"],
        "runpodJobId": job.get("runpodJobId", ""),
        "executionMode": job.get("executionMode", "dry-run"),
        "user": user,
        "workerName": user.get("name") or user.get("id") or "-",
        "status": display_job_status(job),
        "prompt": first_segment.get("positivePrompt", ""),
        "positivePrompt": " | ".join(
            f"{segment.get('index')}: {segment.get('positivePrompt', '')}"
            for segment in segments
        ),
        "negativePrompt": " | ".join(
            f"{segment.get('index')}: {segment.get('negativePromptAddition', '')}"
            for segment in segments
        ),
        "positivePrompts": [
            {"index": segment.get("index") or index + 1, "text": segment.get("positivePrompt", "")}
            for index, segment in enumerate(segments)
        ],
        "negativePrompts": [
            {"index": segment.get("index") or index + 1, "text": segment.get("negativePromptAddition", "")}
            for index, segment in enumerate(segments)
        ],
        "segmentCount": len(segments) or 1,
        "configJson": config,
        "wanNodeConfig": wan_node_config,
        "fps": config.get("fps", 16),
        "generationSeed": job.get("generationSeed"),
        "outputUrl": job.get("outputUrl", ""),
        "outputAssets": job.get("outputAssets", []),
        "remoteOutputUrls": job.get("remoteOutputUrls", []),
        "inputAssets": job.get("inputAssets", []),
        "inputImages": runtime.hydrate_input_images({
            "keyframes": payload.get("keyframes") or [],
            "inputAssets": job.get("inputAssets", []),
        }),
        "segments": segments,
        "keyframes": payload.get("keyframes") or [],
        "patchSummary": job.get("patchSummary", {}),
    })


def job_status_message(job: dict) -> str:
    if job.get("executionMode") == "runpod":
        status = job.get("status", "UNKNOWN")
        if status == "COMPLETED" and job.get("outputUrl"):
            return "RunPod job completed. Output is ready."
        if status in TERMINAL_RUNPOD_STATES:
            return f"RunPod 상태: {localized_job_status(job)} ({status})"
        return f"RunPod 상태: {localized_job_status(job)} ({status})"
    return "Dry-run job running. Set RUNPOD_DRY_RUN=0 after wiring RunPod execution."


def record_job(runtime: JobRuntime, job: dict) -> None:
    if not runtime.record_job:
        return
    try:
        runtime.record_job(job)
    except Exception as exc:  # pragma: no cover - audit persistence must not interrupt generation.
        job["trackingError"] = str(exc)
