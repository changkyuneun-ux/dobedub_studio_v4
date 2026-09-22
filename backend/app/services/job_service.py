from __future__ import annotations

import copy
import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from backend.app.core.timezone_utils import SEOUL_TIMEZONE, UTC_TIMEZONE, now_seoul_naive, timestamp_fields
from backend.app.services.workflow_patch_service import normalize_resolution_tier


TERMINAL_RUNPOD_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
RUNPOD_NOT_FOUND_GRACE_SECONDS = 15 * 60
RUNPOD_NOT_FOUND_MIN_ATTEMPTS = 3


LOGGER = logging.getLogger(__name__)


@dataclass
class JobRuntime:
    jobs: dict[str, dict]
    dry_run: bool
    prepare_workflow_for_job: Callable[[dict], tuple[dict, list[dict], dict]]
    build_runpod_payload: Callable[..., dict]
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


def normalize_payload_resolution_tier(payload: dict) -> str:
    tier = normalize_resolution_tier(payload.get("resolutionTier"))
    payload["resolutionTier"] = tier
    for segment in payload.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        config = segment.setdefault("config", {})
        if isinstance(config, dict):
            config["resolutionTier"] = tier
    return tier


def submit_runpod_job(runtime: JobRuntime, payload: dict) -> dict:
    workflow, images, patch_summary = runtime.prepare_workflow_for_job(payload)
    LOGGER.info(
        "runpod_submission_snapshot %s",
        json.dumps({
            "event": "runpod_submission_snapshot",
            "taskId": str(payload.get("taskId") or ""),
            "workflowId": str(payload.get("workflowId") or ""),
            "resolutionTier": str(payload.get("resolutionTier") or "sd"),
            "generation": (patch_summary or {}).get("generation") or [],
        }, ensure_ascii=True, sort_keys=True),
    )
    response = runtime.runpod_request("POST", "/run", _build_runpod_payload(runtime, workflow, images, payload))
    runpod_job_id = response.get("id")
    if not runpod_job_id:
        raise RuntimeError(f"RunPod response did not include job id: {response}")
    return {
        "runpodJobId": runpod_job_id,
        "patchSummary": patch_summary,
        "runpodSubmit": response,
    }


def _build_runpod_payload(runtime: JobRuntime, workflow: dict, images: list[dict], payload: dict) -> dict:
    signature = inspect.signature(runtime.build_runpod_payload)
    if len(signature.parameters) >= 3:
        return runtime.build_runpod_payload(workflow, images, payload)
    return runtime.build_runpod_payload(workflow, images)


def queue_job(runtime: JobRuntime, payload: dict) -> dict:
    """Persist a validated job before any external RunPod request is made."""
    # The in-memory task and its DB record must preserve the exact request
    # submitted to RunPod, even if a caller later mutates its original object.
    payload = copy.deepcopy(payload)
    normalize_payload_resolution_tier(payload)
    now_seoul = now_seoul_naive()
    task_id = f"task_{now_seoul.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    now = time.time()
    workflow_id = payload.get("workflowId") or "unknown"
    workflow_name = str(payload.get("workflowName") or Path(str(workflow_id)).stem or workflow_id)
    payload["workflowName"] = workflow_name
    segments = payload.get("segments") or []
    first_config = (segments[0].get("config") if segments else {}) or {}
    # Validate now, while the request still belongs to the caller, but defer
    # the network call to the durable dispatcher. Persist the generated seed
    # so the workflow reconstructed at submission time is identical.
    _workflow, _images, patch_summary = runtime.prepare_workflow_for_job(payload)
    generation_seed = generation_seed_from_patch_summary(patch_summary)
    if generation_seed is not None:
        payload["generationSeed"] = generation_seed
    # A durable queued task always represents an actual RunPod submission. Test
    # callers replace runpod_request with a fake runtime rather than creating
    # local success records that differ from production behavior.
    execution_mode = "runpod"
    created_at_utc = datetime.fromtimestamp(now, tz=UTC_TIMEZONE)
    created_at_fields = timestamp_fields(
        "createdAt",
        created_at_utc,
        naive_timezone=UTC_TIMEZONE,
        source_timezone="UTC",
        source="ecs-application",
    )
    # Runtime elapsed-time calculations require this field to remain an epoch.
    # The formatted UTC/KST pair is carried in the companion fields below.
    created_at_fields.pop("createdAt", None)
    runtime.jobs[task_id] = {
        "taskId": task_id,
        "runpodJobId": "",
        "executionMode": execution_mode,
        "workflowId": workflow_id,
        "workflowName": workflow_name,
        "status": "PENDING_SUBMIT",
        "progress": 0,
        "createdAt": now,
        "createdAtEpoch": now,
        "startedAt": now_seoul.strftime("%Y-%m-%d %H:%M:%S"),
        **created_at_fields,
        **timestamp_fields("startedAt", now_seoul, naive_timezone=SEOUL_TIMEZONE, source_timezone="Asia/Seoul", source="ecs-application"),
        "payload": payload,
        "firstConfig": first_config,
        "generationSeed": generation_seed,
        "patchSummary": patch_summary,
        "runpodSubmit": {},
        "inputAssets": [
            keyframe.get("uploadId")
            for keyframe in (payload.get("keyframes") or [])
            if keyframe.get("uploadId")
        ],
    }
    record_job(runtime, runtime.jobs[task_id])
    return runtime.jobs[task_id]


def create_job(runtime: JobRuntime, payload: dict) -> dict:
    """Compatibility alias. New callers must use the durable queue semantics."""
    return queue_job(runtime, payload)


def dispatch_queued_job(runtime: JobRuntime, job: dict) -> dict:
    """Submit one DB-claimed task and retain its original request snapshot."""
    if str(job.get("status") or "").upper() not in {"PENDING_SUBMIT", "DISPATCHING"}:
        raise ValueError("Only a pending submission can be dispatched")

    payload = copy.deepcopy(job.get("payload") or {})
    if not payload:
        raise ValueError("Queued task payload is missing")
    normalize_payload_resolution_tier(payload)
    if job.get("generationSeed") is not None:
        payload["generationSeed"] = job["generationSeed"]
    payload["taskId"] = job["taskId"]

    runpod_data = submit_runpod_job(runtime, payload)
    execution_mode = "runpod"

    now_seoul = now_seoul_naive()
    job.update({
        "payload": payload,
        "runpodJobId": runpod_data["runpodJobId"],
        "executionMode": execution_mode,
        "status": "QUEUED",
        "progress": 0,
        "startedAt": now_seoul.strftime("%Y-%m-%d %H:%M:%S"),
        "patchSummary": runpod_data.get("patchSummary") or {},
        "runpodSubmit": runpod_data.get("runpodSubmit") or {},
        "generationSeed": generation_seed_from_patch_summary(runpod_data.get("patchSummary")) or job.get("generationSeed"),
    })
    job.update(timestamp_fields("startedAt", now_seoul, naive_timezone=SEOUL_TIMEZONE, source_timezone="Asia/Seoul", source="ecs-application"))
    record_job(runtime, job)
    return job


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

    if state == "COMPLETED":
        # The provider terminal state must survive even when output registration
        # (S3/local storage or asset DB writes) has a separate failure.
        job["runpodStatus"] = {**runpod_status, "outputImportStatus": "PENDING"}
        job["outputImportStatus"] = "PENDING"
        record_job(runtime, job)
        _save_completed_outputs_safely(runtime, job, runpod_status)
    else:
        record_job(runtime, job)
    return runpod_status, elapsed, progress


def _save_completed_outputs_if_needed(runtime: JobRuntime, job: dict, runpod_status: dict) -> None:
    if job.get("outputsSaved"):
        return
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
    job["outputImportStatus"] = "COMPLETED"
    job.pop("outputSaveError", None)
    if isinstance(job.get("runpodStatus"), dict):
        job["runpodStatus"] = {
            **job["runpodStatus"],
            "outputImportStatus": "COMPLETED",
        }
        job["runpodStatus"].pop("outputSaveError", None)
    record_job(runtime, job)


def _save_completed_outputs_safely(runtime: JobRuntime, job: dict, runpod_status: dict) -> None:
    try:
        _save_completed_outputs_if_needed(runtime, job, runpod_status)
    except Exception as exc:
        error = str(exc)
        job["outputImportStatus"] = "PENDING"
        job["outputSaveError"] = error
        if isinstance(job.get("runpodStatus"), dict):
            job["runpodStatus"] = {
                **job["runpodStatus"],
                "outputSaveError": error,
                "outputImportStatus": "PENDING",
            }
        LOGGER.exception("RunPod job completed but output persistence failed: task=%s", job.get("taskId"))
        record_job(runtime, job)


def is_runpod_job_not_found_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "runpod http 404" in message and ("job not found" in message or "not found" in message)


def mark_runpod_job_not_found(runtime: JobRuntime, job: dict, error: str) -> dict:
    job["status"] = "FAILED"
    job["progress"] = 100
    job["runpodStatus"] = {
        "status": "FAILED",
        "error": error,
        "providerStatus": "NOT_FOUND",
    }
    job["historySaved"] = True
    record_job(runtime, job)
    return job


def reconcile_runpod_job_not_found(
    runtime: JobRuntime,
    job: dict,
    error: str,
    *,
    now_epoch: float | None = None,
) -> str:
    """Resolve an ambiguous RunPod 404 against durable output storage.

    RunPod's status record and the worker-written S3 manifest are independent
    signals.  A missing provider status must not win over a late manifest, and
    it must remain retryable long enough for an in-flight worker to publish its
    result.  The reconciliation envelope is persisted inside runpodStatus so a
    process restart cannot reset the grace period.
    """
    observed_at = float(now_epoch if now_epoch is not None else time.time())
    previous_status = job.get("runpodStatus") if isinstance(job.get("runpodStatus"), dict) else {}
    previous_recovery = (
        previous_status.get("notFoundRecovery")
        if isinstance(previous_status.get("notFoundRecovery"), dict)
        else {}
    )
    attempts = max(0, int(previous_recovery.get("attempts") or 0)) + 1
    first_seen = float(previous_recovery.get("firstSeenEpoch") or observed_at)
    recovery = {
        "attempts": attempts,
        "firstSeenEpoch": first_seen,
        "lastSeenEpoch": observed_at,
    }

    manifest_probe = {
        "status": "COMPLETED",
        "id": job.get("runpodJobId"),
        "providerStatus": "NOT_FOUND",
    }
    try:
        _save_completed_outputs_if_needed(runtime, job, manifest_probe)
    except Exception:
        elapsed = max(0.0, observed_at - first_seen)
        if attempts < RUNPOD_NOT_FOUND_MIN_ATTEMPTS or elapsed < RUNPOD_NOT_FOUND_GRACE_SECONDS:
            active_status = str(job.get("status") or previous_status.get("status") or "IN_PROGRESS").upper()
            if active_status in TERMINAL_RUNPOD_STATES:
                active_status = "IN_PROGRESS"
                job["status"] = active_status
                job["progress"] = min(95, max(1, int(job.get("progress") or 45)))
            job["runpodStatus"] = {
                **previous_status,
                "status": active_status,
                "error": error,
                "providerStatus": "NOT_FOUND_RECONCILING",
                "notFoundRecovery": recovery,
            }
            record_job(runtime, job)
            return "retry"

        job["status"] = "FAILED"
        job["progress"] = 100
        recovery["final"] = True
        job["runpodStatus"] = {
            "status": "FAILED",
            "error": error,
            "providerStatus": "NOT_FOUND",
            "notFoundRecovery": recovery,
        }
        job["historySaved"] = True
        record_job(runtime, job)
        return "failed"

    job["status"] = "COMPLETED"
    job["progress"] = 100
    job["historySaved"] = True
    job["runpodStatus"] = {
        **(job.get("runpodStatus") or {}),
        "status": "COMPLETED",
        "providerStatus": "RECOVERED_FROM_MANIFEST",
        "notFoundRecovery": recovery,
    }
    job["runpodStatus"].pop("error", None)
    record_job(runtime, job)
    return "recovered"


def cancel_job(runtime: JobRuntime, task_id: str) -> dict:
    job = runtime.jobs.get(task_id)
    if not job:
        raise KeyError(task_id)
    status = str(job.get("status", "")).upper()
    if status in TERMINAL_RUNPOD_STATES:
        return job_status(runtime, task_id)
    cancel_response = {}
    if job.get("executionMode") == "runpod" and job.get("runpodJobId"):
        cancel_response = runtime.runpod_request("POST", f"/cancel/{job['runpodJobId']}", None)
    else:
        cancel_response = {"status": "CANCELLED", "message": "Dry-run job cancelled locally."}
    job["status"] = "CANCELLED"
    job["progress"] = 100
    job["cancelRequested"] = True
    cancelled_at = now_seoul_naive()
    job.update(timestamp_fields("cancelledAt", cancelled_at, naive_timezone=SEOUL_TIMEZONE, source_timezone="Asia/Seoul", source="ecs-application"))
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
    status = str(job.get("status") or "").upper()
    if status in {"PENDING_SUBMIT", "DISPATCHING"}:
        progress = 0
        terminal = False
    elif job.get("executionMode") == "runpod" and status in TERMINAL_RUNPOD_STATES:
        progress = 100
        job["progress"] = progress
        runpod_status = job.get("runpodStatus") or {"status": status}
        if status == "COMPLETED":
            _save_completed_outputs_safely(runtime, job, runpod_status)
        terminal = True
    elif job.get("executionMode") == "runpod":
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

    result = {
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
        "outputImportStatus": job.get("outputImportStatus") or ("COMPLETED" if job.get("outputsSaved") else "PENDING"),
        "cancelRequested": bool(job.get("cancelRequested")),
        "lastDispatchError": job.get("lastDispatchError"),
    }
    for field_name in ("createdAt", "startedAt", "completedAt", "cancelledAt"):
        if field_name == "createdAt":
            # `createdAt` remains an epoch in the in-memory job.  Publish the
            # explicit display pair without changing that runtime value.
            for suffix in ("Utc", "Kst", "SourceTimezone", "Source"):
                result[f"{field_name}{suffix}"] = job.get(f"{field_name}{suffix}")
        else:
            for suffix in ("", "Utc", "Kst", "SourceTimezone", "Source"):
                key = f"{field_name}{suffix}"
                if key in job:
                    result[key] = job.get(key)
    result["runpodTimeContext"] = _runpod_time_context(job)
    return result


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
    if status in {"PENDING_SUBMIT", "DISPATCHING"}:
        return "queued"
    return "running"


def _runpod_time_context(job: dict) -> dict:
    """Keep RunPod's original timestamp payload alongside application times."""
    return {
        "submit": job.get("runpodSubmit") or {},
        "status": job.get("runpodStatus") or {},
    }


def display_job_status(job: dict) -> str:
    status = str(job.get("status", "")).upper()
    if status in {"COMPLETED", "SUCCESS"}:
        return "Completed"
    if status == "CANCELLED":
        return "Cancelled"
    if status == "TIMED_OUT":
        return "Timed Out"
    if status == "FAILED":
        return "Failed"
    return job.get("status", "running")


def localized_job_status(job: dict) -> str:
    status = str(job.get("status", "")).upper()
    labels = {
        "PENDING_SUBMIT": "요청 대기",
        "DISPATCHING": "제출 중",
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
        "workflowName": job.get("workflowName") or payload.get("workflowName") or job["workflowId"],
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
    if str(job.get("status") or "").upper() == "PENDING_SUBMIT":
        return "RunPod 유휴 worker를 기다리는 중입니다."
    if str(job.get("status") or "").upper() == "DISPATCHING":
        return "RunPod worker에 요청을 제출하는 중입니다."
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
