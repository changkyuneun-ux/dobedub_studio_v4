"""Login landing dashboard API (spec 2026-09-13-dashboard-landing-design.md §4).

Global policy: any authenticated user may read the dashboard — no permission
code is required, so this router is deliberately absent from the permission
resource catalog.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, current_user_from_headers
from backend.app.db.session import get_db
from backend.app.services.dashboard_service import (
    DAILY_STATUS_KINDS,
    RANGE_KEYS,
    RECENT_LIMIT_DEFAULT,
    RECENT_LIMIT_MAX,
    dashboard_summary,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
LOGGER = logging.getLogger("dobedub.dashboard")
# "submitted"/"other"는 필터용 상태 값이 아니라 집계용 합계·잔여 분류이므로 제외한다.
_FILTERABLE_STATUS_KINDS = {kind for kind in DAILY_STATUS_KINDS if kind not in {"submitted", "other"}}


@router.get("/summary")
def get_dashboard_summary(
    range: str = Query(default="7d", alias="range"),
    limit: int = Query(default=RECENT_LIMIT_DEFAULT, ge=1),
    user: str | None = Query(default=None, description="일자별 작업량 그래프 필터: 작업자 ID"),
    workflow: str | None = Query(default=None, description="일자별 작업량 그래프 필터: 워크플로 ID"),
    status: str | None = Query(default=None, description="일자별 작업량 그래프 필터: 상태(completed/failed/active/queued)"),
    _: CurrentUser = Depends(current_user_from_headers),
    db: Session = Depends(get_db),
):
    if range not in RANGE_KEYS:
        raise HTTPException(status_code=400, detail=f"range must be one of {', '.join(RANGE_KEYS)}")
    if status and status not in _FILTERABLE_STATUS_KINDS:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(sorted(_FILTERABLE_STATUS_KINDS))}")
    try:
        return dashboard_summary(
            db,
            range_key=range,
            limit=min(limit, RECENT_LIMIT_MAX),
            filter_user_id=user or None,
            filter_workflow_id=workflow or None,
            filter_status_kind=status or None,
        )
    except Exception as exc:  # noqa: BLE001 - surface the cause instead of a bare 500
        LOGGER.exception("dashboard.summary failed")
        raise HTTPException(status_code=500, detail=f"대시보드 집계 오류: {type(exc).__name__}: {exc}") from exc
