from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.app.services.runpod_client import idle_worker_capacity
from backend.app.services.task_tracking_service import claim_next_pending_submission, release_pending_submission


@dataclass(frozen=True)
class RunpodDispatchRuntime:
    dry_run: bool
    connection_status: Callable[[], dict]
    dispatch_task: Callable[[str], dict]


def dispatch_next_pending_submission(runtime: RunpodDispatchRuntime) -> dict:
    """Submit one oldest queued task only when Serverless capacity is idle."""
    try:
        health = runtime.connection_status()
        if not health.get("ok"):
            return {"status": "waiting", "reason": health.get("message") or "RunPod health unavailable"}
        capacity = idle_worker_capacity(health)
    except Exception as exc:
        return {"status": "waiting", "reason": f"RunPod health check failed: {exc}"}

    if not capacity["known"]:
        return {"status": "waiting", "reason": f"RunPod worker capacity is unknown ({capacity['source']})"}
    if capacity["idle"] < 1:
        return {"status": "waiting", "reason": "RunPod has no idle worker"}

    claimed = claim_next_pending_submission()
    if not claimed:
        return {"status": "idle"}
    task_id = claimed["taskId"]
    try:
        job = runtime.dispatch_task(task_id)
    except Exception as exc:
        release_pending_submission(task_id, str(exc))
        return {"status": "deferred", "taskId": task_id, "reason": str(exc)}
    return {"status": "dispatched", "taskId": task_id, "runpodJobId": job.get("runpodJobId")}
