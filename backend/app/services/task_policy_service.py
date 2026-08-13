from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import TaskExecutionPolicy, WorkflowTask


DEFAULT_MAX_ACTIVE_TASKS_PER_USER = 3
DEFAULT_MAX_ACTIVE_TASKS_TOTAL = 10
ACTIVE_TASK_STATUSES = {"QUEUED", "IN_QUEUE", "IN_PROGRESS", "RUNNING"}


class TaskSubmissionLimitError(ValueError):
    """Raised only when an active-task submission limit is reached."""


def task_execution_policy(session: Session) -> TaskExecutionPolicy:
    policy = session.get(TaskExecutionPolicy, 1)
    if policy:
        return policy
    policy = TaskExecutionPolicy(
        id=1,
        max_active_tasks_per_user=DEFAULT_MAX_ACTIVE_TASKS_PER_USER,
        max_active_tasks_total=DEFAULT_MAX_ACTIVE_TASKS_TOTAL,
    )
    session.add(policy)
    session.flush()
    return policy


def task_execution_policy_payload(session: Session) -> dict:
    policy = task_execution_policy(session)
    return {
        "maxActiveTasksPerUser": int(policy.max_active_tasks_per_user),
        "maxActiveTasksTotal": int(policy.max_active_tasks_total),
        "updatedBy": policy.updated_by,
        "updatedAt": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def update_task_execution_policy(
    session: Session,
    *,
    max_active_tasks_per_user: object,
    max_active_tasks_total: object,
    updated_by: str,
) -> dict:
    per_user = _positive_limit(max_active_tasks_per_user, "maxActiveTasksPerUser")
    total = _positive_limit(max_active_tasks_total, "maxActiveTasksTotal")
    if per_user > total:
        raise ValueError("사용자당 동시 활성 Task 수는 전체 동시 활성 Task 수보다 클 수 없습니다.")
    policy = task_execution_policy(session)
    policy.max_active_tasks_per_user = per_user
    policy.max_active_tasks_total = total
    policy.updated_by = updated_by
    policy.updated_at = datetime.utcnow()
    session.commit()
    return task_execution_policy_payload(session)


def active_task_counts(session: Session, user_id: str | None = None) -> dict:
    conditions = [
        WorkflowTask.deleted_at.is_(None),
        func.upper(WorkflowTask.status).in_(ACTIVE_TASK_STATUSES),
    ]
    total = int(session.scalar(select(func.count()).select_from(WorkflowTask).where(*conditions)) or 0)
    user_total = total
    if user_id:
        user_total = int(
            session.scalar(
                select(func.count()).select_from(WorkflowTask).where(*conditions, WorkflowTask.user_id == user_id)
            )
            or 0
        )
    return {"activeForUser": user_total, "activeTotal": total}


def assert_task_submission_allowed(session: Session, user_id: str) -> dict:
    policy = task_execution_policy(session)
    counts = active_task_counts(session, user_id)
    if counts["activeForUser"] >= policy.max_active_tasks_per_user:
        raise TaskSubmissionLimitError(
            f"사용자 동시 활성 Task 한도({policy.max_active_tasks_per_user}개)에 도달했습니다. "
            "Task History에서 진행 상태를 확인하거나 완료 후 다시 제출하세요."
        )
    if counts["activeTotal"] >= policy.max_active_tasks_total:
        raise TaskSubmissionLimitError(
            f"전체 동시 활성 Task 한도({policy.max_active_tasks_total}개)에 도달했습니다. 잠시 후 다시 시도하세요."
        )
    return {**task_execution_policy_payload(session), **counts}


def _positive_limit(value: object, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed < 1 or parsed > 100:
        raise ValueError(f"{field_name} must be between 1 and 100")
    return parsed
