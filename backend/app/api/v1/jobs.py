from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.security import CurrentUser, require_any_permission, require_permission
from backend.app.services import studio_api_service
from backend.app.services.task_policy_service import TaskSubmissionLimitError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=201)
def create_job(payload: dict, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    if not payload.get("workflowId"):
        raise HTTPException(status_code=400, detail="workflowId is required")
    try:
        job = studio_api_service.create_job(
            payload,
            user={
                "id": current_user.id,
                "name": current_user.name,
                "role": current_user.role,
                "permissions": current_user.permissions,
            },
        )
    except TaskSubmissionLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "taskId": job["taskId"],
        "runpodJobId": job["runpodJobId"],
        "status": "queued",
        "generationSeed": job.get("generationSeed"),
    }


@router.get("/{task_id}")
def job_status(task_id: str, _: CurrentUser = Depends(require_any_permission(("jobs:run", "history:read")))):
    try:
        return studio_api_service.job_status(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {task_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{task_id}/prompts")
def job_prompts(task_id: str, _: CurrentUser = Depends(require_any_permission(("history:read", "prompts:review")))):
    prompts = studio_api_service.job_prompts(task_id)
    if not prompts:
        raise HTTPException(status_code=404, detail=f"Job prompts not found: {task_id}")
    return {"taskId": task_id, "items": prompts}


@router.patch("/{task_id}/prompts/{segment_index}/quality")
def update_job_prompt_quality(task_id: str, segment_index: int, payload: dict, _: CurrentUser = Depends(require_permission("prompts:review"))):
    try:
        return studio_api_service.update_job_prompt_quality(task_id, segment_index, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job prompt not found: {task_id}/{segment_index}") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{task_id}/prompts/{segment_index}/review")
def update_job_prompt_review(
    task_id: str,
    segment_index: int,
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("prompts:review")),
):
    try:
        # 평가자는 브라우저가 아닌 인증된 서버 세션으로 확정한다. 클라이언트가
        # reviewedBy/userId를 임의로 보내도 다른 사용자 이름으로 저장되지 않는다.
        review_payload = {
            **(payload if isinstance(payload, dict) else {}),
            "reviewedBy": current_user.name or current_user.id,
            "userId": current_user.id,
        }
        return studio_api_service.update_job_prompt_review(task_id, segment_index, review_payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job prompt not found: {task_id}/{segment_index}") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/cancel")
def cancel_job(task_id: str, _: CurrentUser = Depends(require_permission("jobs:cancel"))):
    try:
        return studio_api_service.cancel_job(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {task_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
