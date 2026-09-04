from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.security import CurrentUser, has_permission, require_any_permission, require_permission
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
        "status": "pending_submit",
        "generationSeed": job.get("generationSeed"),
    }


@router.post("/from-prompt-draft", status_code=201)
def create_job_from_prompt_draft(payload: dict, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    draft_id = str(payload.get("promptDraftId") or "").strip()
    if not draft_id:
        raise HTTPException(status_code=400, detail="promptDraftId is required")
    user = {
        "id": current_user.id,
        "name": current_user.name,
        "role": current_user.role,
        "permissions": current_user.permissions,
    }
    try:
        batch = studio_api_service.create_runpod_request_batch(
            {"items": [{"promptDraftId": draft_id}]},
            user=user,
        )
        item = batch["items"][0]
    except TaskSubmissionLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "taskId": item.get("taskId"),
        "runpodJobId": item.get("runpodJobId") or "",
        "status": str(item.get("status") or "pending_submit").lower(),
        "requestBatchId": batch["id"],
    }


@router.post("/request-batches", status_code=201)
def create_runpod_request_batch(payload: dict, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    worker_id = str(payload.get("workerId") or current_user.id).strip()
    if worker_id != current_user.id and not has_permission(current_user.permissions, "jobs:manage"):
        raise HTTPException(status_code=403, detail="다른 작업자 요청을 제출하려면 jobs:manage 권한이 필요합니다.")
    try:
        return studio_api_service.create_runpod_request_batch(
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


@router.get("/request-batches/active")
def active_runpod_request_batch(
    workerId: str = "",
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    worker_id = workerId.strip() or current_user.id
    can_manage = has_permission(current_user.permissions, "jobs:manage")
    if worker_id != current_user.id and not can_manage:
        raise HTTPException(status_code=403, detail="다른 작업자 요청 조회에는 jobs:manage 권한이 필요합니다.")
    return {"item": studio_api_service.active_runpod_request_batch(user={"id": current_user.id}, worker_id=worker_id)}


@router.get("/request-batches/dashboard")
def runpod_request_dashboard(
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    can_manage = has_permission(current_user.permissions, "jobs:manage")
    return studio_api_service.runpod_request_dashboard(
        worker_id=None if can_manage else current_user.id,
    )


@router.get("/request-batches/queue")
def runpod_request_queue(
    workerId: str = "",
    workflowId: str = "",
    statusFilter: str = "",
    page: int = 1,
    pageSize: int = 10,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    selected_worker = workerId.strip()
    can_manage = has_permission(current_user.permissions, "jobs:manage")
    if selected_worker in {"*", "all"}:
        if not can_manage:
            raise HTTPException(status_code=403, detail="전체 작업자 조회에는 jobs:manage 권한이 필요합니다.")
        selected_worker = ""
    elif selected_worker and selected_worker != current_user.id and not can_manage:
        raise HTTPException(status_code=403, detail="다른 작업자 요청 조회에는 jobs:manage 권한이 필요합니다.")
    return studio_api_service.runpod_request_queue(
        worker_id=selected_worker or (None if can_manage and workerId.strip() in {"*", "all"} else current_user.id),
        workflow_id=workflowId.strip(),
        status_filter=statusFilter.strip(),
        page=page,
        page_size=pageSize,
    )


@router.get("/request-batches/{batch_id}")
def get_runpod_request_batch(batch_id: str, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    try:
        return studio_api_service.runpod_request_batch(
            batch_id,
            user={
                "id": current_user.id,
                "canManage": has_permission(current_user.permissions, "jobs:manage"),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
