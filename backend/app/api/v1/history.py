from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.security import CurrentUser, require_permission
from backend.app.services import studio_api_service

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
# B-01: 기본값을 설계(3a) 기준인 20으로 통일. 50은 프론트가 사용자에게 제공하는
# 선택지 중 하나로만 남는다 - 프론트는 이제 20/50 중 사용자가 고른 값을 항상
# 명시 전송하므로 이 기본값은 pageSize를 아예 안 보내는 다른 호출자(스크립트,
# 향후 API 클라이언트 등)를 위한 안전망이다.
def history(page: int = 1, pageSize: int = 20, _: CurrentUser = Depends(require_permission("history:read"))):
    return studio_api_service.paginated_history(page, pageSize)


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
