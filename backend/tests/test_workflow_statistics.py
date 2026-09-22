from datetime import datetime

from backend.app.db.models import WorkflowTask
from backend.app.services.workflow_catalog_service import workflow_statistics


def _task(task_id: str, workflow_id: str, status: str, *, elapsed: int | None = None, deleted: bool = False):
    return WorkflowTask(
        id=task_id,
        workflow_id=workflow_id,
        status=status,
        elapsed_seconds=elapsed,
        created_at=datetime(2026, 9, int(task_id[-1]), 1, 2),
        completed_at=datetime(2026, 9, int(task_id[-1]), 1, 3) if status in {"COMPLETED", "FAILED"} else None,
        deleted_at=datetime(2026, 9, 20) if deleted else None,
    )


def test_workflow_statistics_groups_aliases_and_excludes_deleted_rows(db_session):
    db_session.add_all([
        _task("task-1", "1-images_10s_chain_81.json", "COMPLETED", elapsed=10),
        _task("task-2", "1-images_10s_chain.json", "FAILED", elapsed=20),
        _task("task-3", "1-images_10s_chain_81.json", "CANCELLED"),
        _task("task-4", "1-images_10s_chain_81.json", "PENDING_SUBMIT"),
        _task("task-5", "1-images_10s_chain_81.json", "COMPLETED", elapsed=100, deleted=True),
    ])
    db_session.commit()

    stats = workflow_statistics(db_session, ["1-images_10s_chain_81.json", "empty.json"])

    chain = stats["1-images_10s_chain_81.json"]
    assert chain["total"] == 4
    assert chain["completed"] == 1
    assert chain["failed"] == 1
    assert chain["cancelled"] == 1
    assert chain["inProgress"] == 1
    assert chain["averageElapsedSeconds"] == 15.0
    assert chain["latestCreatedAt"].startswith("2026-09-04T01:02")
    assert chain["latestCompletedAt"].startswith("2026-09-02T01:03")
    assert stats["empty.json"] == {
        "total": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "inProgress": 0,
        "averageElapsedSeconds": None,
        "latestCreatedAt": None,
        "latestCompletedAt": None,
    }


def test_workflow_statistics_retains_unknown_historical_workflows(db_session):
    db_session.add(_task("task-1", "historical-only.json", "COMPLETED", elapsed=7))
    db_session.commit()

    stats = workflow_statistics(db_session, ["registered.json"])

    assert stats["registered.json"]["total"] == 0
    assert stats["historical-only.json"]["total"] == 1
