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
from backend.app.services.dashboard_service import RANGE_KEYS, RECENT_LIMIT_DEFAULT, RECENT_LIMIT_MAX, dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
LOGGER = logging.getLogger("dobedub.dashboard")


@router.get("/summary")
def get_dashboard_summary(
    range: str = Query(default="7d", alias="range"),
    limit: int = Query(default=RECENT_LIMIT_DEFAULT, ge=1),
    _: CurrentUser = Depends(current_user_from_headers),
    db: Session = Depends(get_db),
):
    if range not in RANGE_KEYS:
        raise HTTPException(status_code=400, detail=f"range must be one of {', '.join(RANGE_KEYS)}")
    try:
        return dashboard_summary(db, range_key=range, limit=min(limit, RECENT_LIMIT_MAX))
    except Exception as exc:  # noqa: BLE001 - surface the cause instead of a bare 500
        LOGGER.exception("dashboard.summary failed")
        raise HTTPException(status_code=500, detail=f"대시보드 집계 오류: {type(exc).__name__}: {exc}") from exc
