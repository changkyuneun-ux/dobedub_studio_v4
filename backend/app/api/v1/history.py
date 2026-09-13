from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, has_permission, require_permission
from backend.app.db.session import get_db
from backend.app.services import job_service, prompt_batch_service, studio_api_service, task_tracking_service
from backend.app.services.task_policy_service import TaskSubmissionLimitError

router = APIRouter(prefix="/history", tags=["history"])
LOGGER = logging.getLogger(__name__)


@router.get("")
# B-01: 기본값을 설계(3a) 기준인 20으로 통일. 50은 프론트가 사용자에게 제공하는
# 선택지 중 하나로만 남는다 - 프론트는 이제 20/50 중 사용자가 고른 값을 항상
# 명시 전송하므로 이 기본값은 pageSize를 아예 안 보내는 다른 호출자(스크립트,
# 향후 API 클라이언트 등)를 위한 안전망이다.
def history(page: int = 1, pageSize: int = 20, _: CurrentUser = Depends(require_permission("history:read"))):
    return studio_api_service.paginated_history(page, pageSize)


@router.get("/prompts")
def prompt_history(
    page: int = 1,
    generationStatus: str = "",
    runpodStatus: str = "",
    batchId: str = "",
    current_user: CurrentUser = Depends(require_permission("history:read")),
    db: Session = Depends(get_db),
):
    """Image-scoped Grok history, deliberately fixed to 10 rows per page."""
    # A manager needs the per-worker operational dashboard. Other users keep
    # the original isolation and only receive their own prompt history.
    created_by = None if has_permission(current_user.permissions, "jobs:manage") else current_user.id
    try:
        return prompt_batch_service.list_prompt_drafts(
            db,
            created_by=created_by,
            page=page,
            page_size=10,
            include_worker_stats=False,
            generation_status=generationStatus,
            runpod_status=runpodStatus,
            batch_job_id=batchId,
        )
    except SQLAlchemyError as exc:
        LOGGER.exception("Prompt history query failed")
        raise HTTPException(
            status_code=503,
            detail="프롬프트 이력 조회에 실패했습니다. 최신 DB 인덱스 마이그레이션 적용 상태를 확인해주세요.",
        ) from exc


@router.get("/runpod")
def runpod_history(
    page: int = 1,
    workflowId: str = "",
    resultStatus: str = "",
    workerId: str = "",
    runDate: str = "",
    batchId: str = "",
    jobId: str = "",
    _: CurrentUser = Depends(require_permission("history:read")),
):
    """RunPod task history, deliberately fixed to 10 rows per page."""
    return studio_api_service.paginated_runpod_history(
        page,
        workflow_id=workflowId,
        result_status=resultStatus,
        worker_id=workerId,
        run_date=runDate,
        batch_job_id=batchId,
        job_id=jobId,
    )


@router.get("/runpod/selection")
def runpod_history_selection(
    workflowId: str = "",
    resultStatus: str = "",
    workerId: str = "",
    runDate: str = "",
    batchId: str = "",
    jobId: str = "",
    _: CurrentUser = Depends(require_permission("history:read")),
):
    """Resolve all terminal task IDs for the current history filter."""
    return task_tracking_service.task_history_selection_ids(
        workflow_id=workflowId,
        result_status=resultStatus,
        worker_id=workerId,
        date_from=runDate,
        date_to=runDate,
        batch_job_id=batchId,
        job_id=jobId,
    )


@router.post("/runpod/rework")
def rework_runpod_history_items(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
    db: Session = Depends(get_db),
):
    try:
        return task_tracking_service.requeue_runpod_history_items(
            db,
            actor_id=current_user.id,
            can_manage=has_permission(current_user.permissions, "jobs:manage"),
            scope=str(payload.get("scope") or "selected"),
            task_ids=[str(task_id) for task_id in payload.get("taskIds") or []],
            workflow_id=str(payload.get("workflowId") or ""),
            result_status=str(payload.get("resultStatus") or ""),
            worker_id=str(payload.get("workerId") or ""),
            run_date=str(payload.get("runDate") or ""),
            batch_job_id=str(payload.get("batchId") or ""),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _rework_history_item_response(task_id: str, current_user: CurrentUser) -> dict:
    try:
        job = studio_api_service.rework_history_item(
            task_id,
            user={
                "id": current_user.id,
                "name": current_user.name,
                "role": current_user.role,
                "permissions": current_user.permissions,
            },
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"History item not found: {task_id}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TaskSubmissionLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "taskId": job["taskId"],
        "sourceTaskId": task_id,
        "runpodJobId": job.get("runpodJobId") or "",
        "status": str(job.get("status") or "PENDING_SUBMIT").upper(),
        "statusLabel": job.get("statusLabel") or job_service.localized_job_status(job),
        "lastDispatchError": job.get("lastDispatchError"),
        "generationSeed": job.get("generationSeed"),
    }


@router.post("/{task_id}/rework", status_code=201)
def rework_history_item(
    task_id: str,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    return _rework_history_item_response(task_id, current_user)


@router.post("/{task_id}/regenerate", status_code=201)
def regenerate_history_item(
    task_id: str,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    return _rework_history_item_response(task_id, current_user)


@router.post("/{task_id}/delete")
# 2026-08-12: A-04가 이 삭제를 audit_logs에 action="history.delete"로 남기던
# 것을 사용자 요청으로 제거했다 - 감사 로그는 "어드민 정보 수정사항"만
# 남기기로 범위를 좁혔고, 자기 작업 이력을 지우는 건 history:delete 권한만
# 있으면 되는 일반 사용자 동작이라 관리자 정보 수정이 아니다. db 세션은 더
# 이상 이 라우트에서 쓰이지 않아 파라미터에서 뺐다.
def delete_history_item(
    task_id: str,
    _: CurrentUser = Depends(require_permission("history:delete")),
):
    try:
        result = studio_api_service.delete_history_item(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"History item not found: {task_id}") from exc
    # 2026-08-10: 진행 중(터미널 상태가 아닌) 작업의 삭제 요청 - db_adapter.delete_history_item이
    # 이 경우 ValueError를 던진다. 3a 화면의 삭제 확인 모달이 "진행 중인 작업은 삭제할 수
    # 없습니다"라고 안내하지만 실제로 막는 코드가 없던 버그를 수정 - 프론트 버튼 비활성화와
    # 별개로 API 직접 호출도 여기서 막는다(방어적 이중 확인).
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result
