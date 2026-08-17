from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import AuditLog


def record_audit_log(
    session: Session,
    *,
    actor_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    before: Any = None,
    after: Any = None,
    ip: str | None = None,
) -> None:
    """A-04: 감사 로그 기록.

    주의 - 기록 실패가 본 동작을 막으면 안 된다. job_service.record_job(305-312)의
    "예외를 삼키고 진행" 패턴과 동일하게, 이 함수는 호출부(라우트 핸들러)에서 본
    작업이 이미 성공(및 커밋)한 뒤에 호출되므로 여기서 예외가 나도 본 작업 자체는
    이미 끝난 상태다. audit_logs 쓰기만 롤백하고 조용히 반환한다 - 호출자에게
    예외를 전파하지 않는다.
    """
    try:
        session.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_json=before,
                after_json=after,
                ip=ip,
                created_at=utc_now().replace(tzinfo=None),
            )
        )
        session.commit()
    except Exception:  # pragma: no cover - audit persistence must not interrupt the main action.
        session.rollback()


def list_audit_logs(
    session: Session,
    page: int = 1,
    page_size: int = 20,
    *,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_id: str | None = None,
) -> dict:
    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(200, int(page_size or 20)))

    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if target_type:
        filters.append(AuditLog.target_type == target_type)
    if target_id:
        filters.append(AuditLog.target_id == target_id)
    if actor_id:
        filters.append(AuditLog.actor_id == actor_id)

    count_query = select(func.count()).select_from(AuditLog)
    list_query = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    for condition in filters:
        count_query = count_query.where(condition)
        list_query = list_query.where(condition)

    total = session.scalar(count_query) or 0
    rows = session.scalars(
        list_query.offset((safe_page - 1) * safe_page_size).limit(safe_page_size)
    ).all()
    return {
        "items": [_audit_log_payload(row) for row in rows],
        "page": safe_page,
        "pageSize": safe_page_size,
        "total": total,
    }


def _audit_log_payload(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "actorId": row.actor_id,
        "action": row.action,
        "targetType": row.target_type,
        "targetId": row.target_id,
        "beforeJson": row.before_json,
        "afterJson": row.after_json,
        "ip": row.ip,
        **timestamp_fields("createdAt", row.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="audit-log"),
    }
