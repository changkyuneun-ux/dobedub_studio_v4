from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.db.models import WorkflowDefinition, WorkflowTask
from backend.app.services.workflow_visibility import canonical_workflow_id


def get_workflow_definition(db: Session, workflow_id: object) -> WorkflowDefinition | None:
    return db.get(WorkflowDefinition, canonical_workflow_id(workflow_id))


def assert_workflow_selectable(db: Session, workflow_id: object) -> str:
    canonical_id = canonical_workflow_id(workflow_id)
    definition = db.get(WorkflowDefinition, canonical_id)
    if definition is None:
        raise ValueError("Workflow is not registered")
    if definition.status != "ACTIVE":
        raise ValueError("Workflow is not active")
    if definition.current_revision_id is None:
        raise ValueError("Workflow has no active revision")
    return canonical_id


def list_active_workflow_ids(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(WorkflowDefinition.id)
            .where(
                WorkflowDefinition.status == "ACTIVE",
                WorkflowDefinition.current_revision_id.is_not(None),
            )
            .order_by(WorkflowDefinition.id)
        )
    )


def _empty_statistics() -> dict:
    return {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "inProgress": 0,
        "averageElapsedSeconds": None,
        "latestCreatedAt": None,
        "latestCompletedAt": None,
    }


def workflow_statistics(db: Session, workflow_ids: Iterable[str]) -> dict[str, dict]:
    """Return one grouped task aggregate and fold historical aliases in Python."""
    result = {canonical_workflow_id(workflow_id): _empty_statistics() for workflow_id in workflow_ids}
    completed_states = {"COMPLETED", "SUCCESS"}
    failed_states = {"FAILED", "TIMED_OUT"}
    cancelled_states = {"CANCELLED"}
    terminal_states = completed_states | failed_states | cancelled_states
    rows = db.execute(
        select(
            WorkflowTask.workflow_id,
            func.count(WorkflowTask.id),
            func.sum(case((WorkflowTask.status.in_(completed_states), 1), else_=0)),
            func.sum(case((WorkflowTask.status.in_(failed_states), 1), else_=0)),
            func.sum(case((WorkflowTask.status.in_(cancelled_states), 1), else_=0)),
            func.sum(case((WorkflowTask.status.not_in(terminal_states), 1), else_=0)),
            func.sum(WorkflowTask.elapsed_seconds),
            func.count(WorkflowTask.elapsed_seconds),
            func.max(WorkflowTask.created_at),
            func.max(WorkflowTask.completed_at),
        )
        .where(WorkflowTask.deleted_at.is_(None))
        .group_by(WorkflowTask.workflow_id)
    ).all()
    elapsed_totals: dict[str, tuple[float, int]] = {}
    for workflow_id, total, completed, failed, cancelled, in_progress, elapsed_sum, elapsed_count, latest_created, latest_completed in rows:
        canonical_id = canonical_workflow_id(workflow_id)
        target = result.setdefault(canonical_id, _empty_statistics())
        row_total = int(total or 0)
        previous_sum, previous_count = elapsed_totals.get(canonical_id, (0.0, 0))
        elapsed_totals[canonical_id] = (previous_sum + float(elapsed_sum or 0), previous_count + int(elapsed_count or 0))
        target["total"] += row_total
        target["completed"] += int(completed or 0)
        target["failed"] += int(failed or 0)
        target["cancelled"] += int(cancelled or 0)
        target["inProgress"] += int(in_progress or 0)
        for key, value in (("latestCreatedAt", latest_created), ("latestCompletedAt", latest_completed)):
            encoded = value.isoformat() if value else None
            if encoded and (target[key] is None or encoded > target[key]):
                target[key] = encoded
    for workflow_id, statistics in result.items():
        elapsed_sum, elapsed_count = elapsed_totals.get(workflow_id, (0.0, 0))
        statistics["averageElapsedSeconds"] = round(elapsed_sum / elapsed_count, 2) if elapsed_count else None
    return result
