from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backend.app.core.config import get_settings
from backend.app.db.models import BatchJob, TaskExecutionPolicy, User, WorkflowTask
from backend.app.services.dashboard_service import (
    RANGE_KEYS,
    _classify_status,
    _evaluate_alerts,
    _range_bounds,
    _seconds_between_for_dialect,
    dashboard_summary,
)

# 2026-09-13 09:41:12 UTC == 18:41:12 KST
NOW = datetime(2026, 9, 13, 9, 41, 12)
KST_MIDNIGHT_TODAY_UTC = datetime(2026, 9, 12, 15, 0, 0)


def _task(session, task_id, *, status, created, user_id="u1", workflow="wan22_i2v_720p.json", elapsed=None, started=None, worker=None, error=None, deleted=None, updated=None):
    task = WorkflowTask(
        id=task_id,
        workflow_id=workflow,
        execution_mode="runpod",
        status=status,
        progress=0,
        worker_name=worker,
        user_id=user_id,
        started_at=started,
        completed_at=None,
        deleted_at=deleted,
        elapsed_seconds=elapsed,
        last_dispatch_error=error,
        created_at=created,
        updated_at=updated or created,
    )
    session.add(task)
    return task


def _seed(session):
    session.add_all([
        User(id="u1", name="김민지", role="OPERATOR", permissions_json=[], is_active=True),
        User(id="u2", name="박서준", role="OPERATOR", permissions_json=[], is_active=True),
    ])
    session.add(TaskExecutionPolicy(id=1, max_active_tasks_per_user=3, max_active_tasks_total=5))
    session.add(BatchJob(id="b1", workflow_id="wan22_i2v_720p.json", status="INCOMPLETE"))
    day = timedelta(days=1)
    in_range = NOW - 2 * day
    _task(session, "t1", status="COMPLETED", created=in_range, elapsed=100, started=in_range + timedelta(seconds=30))
    _task(session, "t2", status="SUCCESS", created=in_range, elapsed=200, started=in_range + timedelta(seconds=30), user_id="u2")
    _task(session, "t3", status="FAILED", created=in_range, error="dispatch boom", user_id="u2")
    _task(session, "t4", status="TIMED_OUT", created=in_range, workflow="character_ref_i2v.json", worker="wk-7be1")
    _task(session, "t5", status="RUNNING", created=NOW - timedelta(minutes=5), workflow="character_ref_i2v.json")
    _task(session, "t6", status="PENDING_SUBMIT", created=NOW - timedelta(minutes=4))
    _task(session, "t7", status="COMPLETED", created=in_range, elapsed=300, deleted=NOW)  # deleted → excluded
    _task(session, "t8", status="COMPLETED", created=NOW - 12 * day, elapsed=50, user_id="ghost")  # previous window
    _task(session, "t9", status="COMPLETED", created=NOW - 10 * day, elapsed=50, user_id="ghost")  # previous window
    session.flush()


@pytest.fixture
def summary(db_session):
    _seed(db_session)
    with patch("backend.app.services.dashboard_service.migration_status", return_value={"alembicCurrent": "a", "alembicHead": "a", "migrationRequired": False, "error": None}):
        return dashboard_summary(db_session, range_key="7d", now=NOW, settings=get_settings(), include_sandbox=False)


def test_range_keys_and_bounds():
    assert RANGE_KEYS == ("today", "7d", "30d")
    since, until, previous = _range_bounds("today", NOW)
    assert since == KST_MIDNIGHT_TODAY_UTC and until == NOW
    assert previous == since - (until - since)
    since7, _, _ = _range_bounds("7d", NOW)
    assert since7 == KST_MIDNIGHT_TODAY_UTC - timedelta(days=6)
    since30, _, _ = _range_bounds("30d", NOW)
    assert since30 == KST_MIDNIGHT_TODAY_UTC - timedelta(days=29)
    with pytest.raises(ValueError):
        _range_bounds("1y", NOW)


def test_classify_status():
    assert _classify_status("completed") == "completed"
    assert _classify_status("SUCCESS") == "completed"
    assert _classify_status("TIMED_OUT") == "failed"
    assert _classify_status("IN_QUEUE") == "queued"
    assert _classify_status("DISPATCHING") == "active"
    assert _classify_status(None) == "other"


def test_kpi_counts_only_live_tasks_in_range(summary):
    kpi = summary["kpi"]
    assert kpi["submitted"] == 6  # t1..t6 (t7 deleted, t8/t9 previous window)
    assert kpi["completed"] == 2 and kpi["failed"] == 2
    assert kpi["successRate"] == 0.5
    assert kpi["failedDispatch"] == 1 and kpi["failedTimeout"] == 1
    assert kpi["active"] == 2 and kpi["queued"] == 1
    assert kpi["avgElapsedSeconds"] == 150
    assert kpi["avgDelaySeconds"] == 30
    assert kpi["activeUsers"] == 2
    assert kpi["batchJobsInProgress"] == 1
    assert kpi["submittedDeltaPercent"] == 200.0  # 6 vs 2 in previous window


def test_recent_by_user_by_workflow(summary):
    recent = summary["recent"]
    assert [item["taskId"] for item in recent][:2] == ["t6", "t5"]
    assert all(item["taskId"] != "t7" for item in recent)
    first = recent[0]
    assert first["user"] == {"id": "u1", "name": "김민지"}
    assert first["workflowName"] == "wan22_i2v_720p"
    assert first["statusKind"] == "queued"
    assert "createdAtKst" in first

    by_user = {row["userId"]: row for row in summary["byUser"]}
    assert by_user["u1"]["submitted"] == 4 and by_user["u1"]["failed"] == 1
    assert by_user["u2"]["name"] == "박서준" and by_user["u2"]["failed"] == 1
    assert summary["byUser"][0]["userId"] == "u1"

    by_workflow = {row["workflowId"]: row for row in summary["byWorkflow"]}
    assert by_workflow["wan22_i2v_720p.json"]["workflowName"] == "wan22_i2v_720p"
    assert by_workflow["wan22_i2v_720p.json"]["submitted"] == 4
    assert by_workflow["wan22_i2v_720p.json"]["avgElapsedSeconds"] == 150
    assert by_workflow["character_ref_i2v.json"]["avgElapsedSeconds"] is None


def test_worker_system_db_and_top_level_contract(summary):
    assert summary["worker"] == {"active": 1, "queued": 1, "maxActiveTasksTotal": 5, "maxActiveTasksPerUser": 3}
    assert set(summary["system"]) == {"comfy", "promptLlm", "workflows"}
    assert set(summary["system"]["comfy"]) == {"configured", "executionMode", "dryRun"}
    assert summary["sandbox"]["configured"] is False
    assert summary["db"]["migrationRequired"] is False
    assert set(summary) >= {"range", "since", "until", "kpi", "recent", "byUser", "byWorkflow", "system", "sandbox", "worker", "db", "alerts", "checkedAt", "checkedAtKst"}
    assert summary["range"] == "7d"


def test_alert_rules():
    base = dict(worker={"active": 1, "queued": 0, "maxActiveTasksTotal": 5}, db={"migrationRequired": False}, sandbox={"conflict": False, "duplicateStoppedPodIds": []})
    assert _evaluate_alerts(recent_hour={"failed": 2, "completed": 10}, **base) == []
    spike = _evaluate_alerts(recent_hour={"failed": 3, "completed": 0, "topFailure": "character_ref_i2v (wk-7be1)"}, **base)
    assert [a["id"] for a in spike] == ["failure_spike"] and "character_ref_i2v" in spike[0]["message"]
    assert _evaluate_alerts(recent_hour={"failed": 1, "completed": 3}, **base) == []  # 25%, sample 4
    assert [a["id"] for a in _evaluate_alerts(recent_hour={"failed": 2, "completed": 4}, **base)] == ["failure_spike"]  # 33%, sample 6
    assert [a["id"] for a in _evaluate_alerts(recent_hour={"failed": 1, "completed": 4}, **base)] == []  # 20%
    saturated = _evaluate_alerts(recent_hour={"failed": 0, "completed": 0}, worker={"active": 5, "queued": 2, "maxActiveTasksTotal": 5}, db={"migrationRequired": False}, sandbox=base["sandbox"])
    assert saturated[0]["id"] == "worker_saturated" and "5/5" in saturated[0]["message"]
    migration = _evaluate_alerts(recent_hour={"failed": 0, "completed": 0}, worker=base["worker"], db={"migrationRequired": True, "alembicCurrent": "0037", "alembicHead": "0038"}, sandbox=base["sandbox"])
    assert migration[0]["id"] == "migration_pending" and "0037 → 0038" in migration[0]["message"]
    sandbox = _evaluate_alerts(recent_hour={"failed": 0, "completed": 0}, worker=base["worker"], db=base["db"], sandbox={"conflict": True, "runningCount": 2, "duplicateStoppedPodIds": ["caiuvooekq9qqw"]})
    assert [a["id"] for a in sandbox] == ["sandbox_conflict", "sandbox_duplicate_pod"]


def test_failure_spike_uses_last_hour_updates(db_session):
    _seed(db_session)
    for index in range(3):
        _task(db_session, f"h{index}", status="FAILED", created=NOW - timedelta(minutes=30), updated=NOW - timedelta(minutes=10), workflow="character_ref_i2v.json", worker="wk-7be1")
    db_session.flush()
    with patch("backend.app.services.dashboard_service.migration_status", return_value={"alembicCurrent": "a", "alembicHead": "a", "migrationRequired": False, "error": None}):
        result = dashboard_summary(db_session, range_key="today", now=NOW, settings=get_settings(), include_sandbox=False)
    ids = [alert["id"] for alert in result["alerts"]]
    assert "failure_spike" in ids
    assert "character_ref_i2v (wk-7be1)" in next(a["message"] for a in result["alerts"] if a["id"] == "failure_spike")


def test_sandbox_block_isolates_runpod_failure(db_session):
    _seed(db_session)
    from backend.app.services import dashboard_service

    dashboard_service._sandbox_cache["value"] = None
    with patch("backend.app.services.dashboard_service.migration_status", return_value={"alembicCurrent": "a", "alembicHead": "a", "migrationRequired": False, "error": None}), \
            patch("backend.app.services.sandbox_pod_service.sandbox_pod_is_configured", return_value=True), \
            patch("backend.app.services.sandbox_pod_service.sandbox_pod_status", side_effect=RuntimeError("runpod down")):
        result = dashboard_summary(db_session, range_key="7d", now=NOW, settings=get_settings())
    assert result["sandbox"]["configured"] is True
    assert "runpod down" in result["sandbox"]["error"]
    assert result["kpi"]["submitted"] == 6
    dashboard_service._sandbox_cache["value"] = None


def test_sandbox_block_flags_duplicate_stopped_pods(db_session):
    _seed(db_session)
    from backend.app.services import dashboard_service

    dashboard_service._sandbox_cache["value"] = None
    status = {
        "activePodId": "p2", "activePodName": "dobedub_comfyUI_Sandbox_RTX PRO 6000", "desiredStatus": "RUNNING", "gpuTier": "fallback", "gpuTypeId": "PRO6000",
        "conflict": False,
        "pods": [
            {"podId": "p1", "desiredStatus": "EXITED", "gpuTypeId": "5090"},
            {"podId": "p3", "desiredStatus": "EXITED", "gpuTypeId": "5090"},
            {"podId": "p2", "desiredStatus": "RUNNING", "gpuTypeId": "PRO6000"},
        ],
    }
    with patch("backend.app.services.dashboard_service.migration_status", return_value={"alembicCurrent": "a", "alembicHead": "a", "migrationRequired": False, "error": None}), \
            patch("backend.app.services.sandbox_pod_service.sandbox_pod_is_configured", return_value=True), \
            patch("backend.app.services.sandbox_pod_service.sandbox_pod_status", return_value=status):
        result = dashboard_summary(db_session, range_key="7d", now=NOW, settings=get_settings())
    assert result["sandbox"]["podCount"] == 3 and result["sandbox"]["runningCount"] == 1
    assert result["sandbox"]["duplicateStoppedPodIds"] == ["p3"]
    assert "sandbox_duplicate_pod" in [a["id"] for a in result["alerts"]]
    dashboard_service._sandbox_cache["value"] = None


def test_seconds_between_compiles_per_dialect():
    # 2026-09-13 hotfix: 프로덕션 MySQL에서 julianday가 나가 500이 났다.
    from sqlalchemy.dialects import mysql, postgresql, sqlite

    later, earlier = WorkflowTask.started_at, WorkflowTask.created_at
    assert "TIMESTAMPDIFF(SECOND" in str(_seconds_between_for_dialect("mysql", later, earlier).compile(dialect=mysql.dialect())).upper()
    assert "TIMESTAMPDIFF(SECOND" in str(_seconds_between_for_dialect("mariadb", later, earlier).compile(dialect=mysql.dialect())).upper()
    assert "EXTRACT(EPOCH" in str(_seconds_between_for_dialect("postgresql", later, earlier).compile(dialect=postgresql.dialect())).upper()
    assert "JULIANDAY" in str(_seconds_between_for_dialect("sqlite", later, earlier).compile(dialect=sqlite.dialect())).upper()
