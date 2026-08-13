from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from backend.app.core.security import CurrentUser, require_permission
from backend.app.services.manual_service import manual_html_page

router = APIRouter(tags=["manual"])


@router.get("/manual", response_class=HTMLResponse)
def manual(_: CurrentUser = Depends(require_permission("manual:read"))):
    try:
        # 매뉴얼은 사용자별 내용이 아니며, 앱 프로세스 렌더 캐시와 브라우저 단기
        # 캐시를 함께 사용한다. 인증이 필요한 응답이므로 shared cache는 허용하지 않는다.
        return HTMLResponse(content=manual_html_page(), headers={"Cache-Control": "private, max-age=300"})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Manual not found: {exc}") from exc
