from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, create_access_token, current_user_from_headers
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.services.admin_service import admin_login, admin_user_payload

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
# 2026-08-12: A-05가 로그인 시도를 audit_logs에 action="login"으로 남기던 것을
# 사용자 요청으로 제거했다 - 감사 로그는 "어드민 정보 수정사항"만 남기기로
# 범위를 좁혔고, 로그인 자체는 정보 변경이 아니다. 기존에 쌓여 있던 login
# 레코드는 마이그레이션 20260812_0018로 별도 삭제했다.
def login(payload: dict, db: Session = Depends(get_db)):
    try:
        result = admin_login(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Login failed: {exc}") from exc
    return result


@router.get("/session")
def session(current_user: CurrentUser = Depends(current_user_from_headers), db: Session = Depends(get_db)):
    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    try:
        return {"user": admin_user_payload(db, user)}
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Session refresh failed: {exc}") from exc


@router.post("/refresh")
# A-06: 무중단 세션 연장. 아직 유효한 토큰으로 호출하면(current_user_from_headers가
# 만료/위조 토큰을 401로 막는다) 같은 사용자에게 새 만료시각의 토큰을 재발급한다.
# 응답 형태는 login과 동일(user, accessToken, expiresAt) - 프론트가 세션을 그대로
# 교체하면 된다. 비활성화된 사용자는 연장하지 않는다.
def refresh(current_user: CurrentUser = Depends(current_user_from_headers), db: Session = Depends(get_db)):
    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    try:
        payload = admin_user_payload(db, user)
        return {"user": payload, **create_access_token(payload)}
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Session refresh failed: {exc}") from exc
