from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backend.app.core.config import get_settings
from backend.app.db.models import BatchJob, TaskExecutionPolicy, User, WorkflowTask
from backend.app.services.dashboard_service import (
    DAILY_STATUS_KINDS,
    RANGE_KEYS,
    _classify_status,
    _daily_volume,
    _duration_cost_breakdown,
    _evaluate_alerts,
    _kst_day_range,
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
    assert set(summary["system"]) == {"comfy", "promptLlm", "grok", "workflows"}
    assert set(summary["system"]["comfy"]) == {"configured", "executionMode", "dryRun"}
    assert set(summary["system"]["grok"]) == {"configured", "enabled", "model", "timeoutSeconds"}
    assert set(summary["system"]["workflows"]) == {"count", "activeCount"}
    assert summary["sandbox"]["configured"] is False
    assert summary["db"]["migrationRequired"] is False
    assert set(summary) >= {
        "range", "since", "until", "kpi", "recent", "dailyVolume", "dailyVolumeFilters", "filterOptions",
        "byUser", "byWorkflow", "system", "sandbox", "worker", "db", "alerts", "checkedAt", "checkedAtKst",
    }
    assert summary["range"] == "7d"


# --- 2026-09-14: 일자별 작업량 그래프 + 활성 워크플로 수 + Grok 타일 -----------------------


def test_system_grok_block_reflects_settings():
    import dataclasses
    from backend.app.services.dashboard_service import _system_block
    settings = dataclasses.replace(
        get_settings(),
        grok_enabled=True,
        grok_api_key="xai-real-key",
        grok_model="grok-4-1-fast-reasoning",
        grok_request_timeout_seconds=120,
    )
    block = _system_block(settings)
    assert block["grok"] == {
        "configured": True,
        "enabled": True,
        "model": "grok-4-1-fast-reasoning",
        "timeoutSeconds": 120,
    }


def test_system_grok_block_not_configured_with_placeholder_key():
    import dataclasses
    from backend.app.services.dashboard_service import _system_block
    settings = dataclasses.replace(get_settings(), grok_enabled=True, grok_api_key="your_grok_api_key")
    block = _system_block(settings)
    assert block["grok"]["configured"] is False


def test_dashboard_summary_workflows_active_count(summary):
    workflows = summary["system"]["workflows"]
    assert workflows["count"] is not None
    assert workflows["activeCount"] is not None
    assert workflows["activeCount"] <= workflows["count"]


def test_kst_day_range_spans_inclusive_calendar_days():
    since, until, _ = _range_bounds("7d", NOW)
    days = _kst_day_range(since, until)
    assert len(days) == 7
    assert days == sorted(days)
    assert days[-1] == "2026-09-13"  # NOW의 KST 달력일


def test_daily_volume_buckets_by_kst_day_and_fills_empty_days(db_session):
    _seed(db_session)
    since, until, _ = _range_bounds("7d", NOW)
    days = _daily_volume(db_session, since, until)
    assert {kind for kind in DAILY_STATUS_KINDS} <= set(days[0].keys())
    assert len(days) == 7
    by_date = {row["date"]: row for row in days}
    total_submitted = sum(row["submitted"] for row in days)
    assert total_submitted == 6  # kpi.submitted와 동일(t1..t6)
    assert sum(row["completed"] for row in days) == 2
    assert sum(row["failed"] for row in days) == 2
    # kpi["active"](진행 중+대기 통합 게이지)와 달리, statusKind는 RUNNING=active/PENDING_SUBMIT=queued로 나뉜다
    assert sum(row["active"] for row in days) == 1
    assert sum(row["queued"] for row in days) == 1
    # 하루도 비어있지 않고 0으로 채워져 있어야 함
    assert all(isinstance(row["submitted"], int) for row in by_date.values())


def test_daily_volume_applies_filters(db_session):
    _seed(db_session)
    since, until, _ = _range_bounds("7d", NOW)
    filtered = _daily_volume(db_session, since, until, user_id="u2")
    assert sum(row["submitted"] for row in filtered) == 2  # t2(u2), t3(u2)

    filtered_workflow = _daily_volume(db_session, since, until, workflow_id="character_ref_i2v.json")
    assert sum(row["submitted"] for row in filtered_workflow) == 2  # t4, t5

    filtered_status = _daily_volume(db_session, since, until, status_kind="failed")
    assert sum(row["submitted"] for row in filtered_status) == 2  # t3, t4


def test_dashboard_summary_daily_volume_respects_query_filters(db_session):
    _seed(db_session)
    with patch("backend.app.services.dashboard_service.migration_status", return_value={"alembicCurrent": "a", "alembicHead": "a", "migrationRequired": False, "error": None}):
        filtered_summary = dashboard_summary(
            db_session, range_key="7d", now=NOW, settings=get_settings(), include_sandbox=False,
            filter_user_id="u2",
        )
    assert sum(row["submitted"] for row in filtered_summary["dailyVolume"]) == 2
    assert filtered_summary["dailyVolumeFilters"] == {"user": "u2", "workflow": None, "status": None}


def test_filter_options_lists_distinct_users_and_workflows(summary):
    options = summary["filterOptions"]
    user_ids = {item["id"] for item in options["users"]}
    workflow_ids = {item["id"] for item in options["workflows"]}
    assert {"u1", "u2"} <= user_ids
    assert {"wan22_i2v_720p.json", "character_ref_i2v.json"} <= workflow_ids


def test_duration_cost_breakdown_separates_utc_and_kst_counts(db_session):
    """RunPod cost rows stay UTC-billed, but job counts expose both UTC and KST days."""
    db_session.add(User(id="duration_user", name="작업자", role="OPERATOR", permissions_json=[], is_active=True))
    _task(
        db_session,
        "kst_only",
        status="COMPLETED",
        created=datetime(2026, 9, 15, 16, 0, 0),  # KST 2026-09-16, UTC 2026-09-15
        workflow="1-images_10s_chain_81.json",
        user_id="duration_user",
    ).runpod_status_json = {"executionTime": 10_000}
    _task(
        db_session,
        "utc_and_kst",
        status="COMPLETED",
        created=datetime(2026, 9, 16, 1, 0, 0),  # KST 2026-09-16
        workflow="1-images_10s_chain_81.json",
        user_id="duration_user",
    ).runpod_status_json = {"executionTime": 10_000}
    _task(
        db_session,
        "utc_only",
        status="FAILED",
        created=datetime(2026, 9, 16, 16, 0, 0),  # KST 2026-09-17
        workflow="wan22_default_81.json",
        user_id="duration_user",
    ).runpod_status_json = {"executionTime": 5_000}
    db_session.flush()

    with patch(
        "backend.app.services.dashboard_service._cached_serverless_billing",
        return_value=({"2026-09-16": {"totalAmount": 12.0}}, None),
    ):
        result = _duration_cost_breakdown(
            db_session,
            get_settings(),
            datetime(2026, 9, 16, 0, 0, 0),
            datetime(2026, 9, 17, 0, 0, 0),
        )

    row = result["byDay"]["2026-09-16"]
    assert row["submitted"] == 2
    assert row["completed"] == 1
    assert row["failed"] == 1
    assert row["kst"] == {"submitted": 2, "completed": 2, "failed": 0}
    assert row["totalCostUsd"] == 12.0
    assert row["split"]["tenSec"]["count"] == 1
    assert row["split"]["fiveSec"]["count"] == 1


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
        result = dashboard_summary(db_session, range_key="7d", now=NOW, settings=get_settings(), sandbox_sync=True)
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
        result = dashboard_summary(db_session, range_key="7d", now=NOW, settings=get_settings(), sandbox_sync=True)
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


def test_sandbox_block_never_blocks_the_request(db_session, monkeypatch):
    # 2026-09-13 성능: 캐시 없음 → pending 즉시 응답(백그라운드 갱신), 캐시 만료 → stale 즉시 응답.
    from backend.app.services import dashboard_service

    dashboard_service._sandbox_cache["value"] = None
    started: list[str] = []
    monkeypatch.setattr(dashboard_service, "_start_sandbox_refresh", lambda settings: started.append("refresh"))
    with patch("backend.app.services.sandbox_pod_service.sandbox_pod_is_configured", return_value=True):
        first = dashboard_service._sandbox_block(get_settings(), db_session)
    assert first["pending"] is True and first["configured"] is True
    assert started == ["refresh"]

    dashboard_service._sandbox_cache["value"] = {**dashboard_service._empty_sandbox(configured=True), "podCount": 2}
    dashboard_service._sandbox_cache["at"] = 0.0  # expired
    with patch("backend.app.services.sandbox_pod_service.sandbox_pod_is_configured", return_value=True):
        stale = dashboard_service._sandbox_block(get_settings(), db_session)
    assert stale["podCount"] == 2 and stale["stale"] is True
    assert started == ["refresh", "refresh"]
    dashboard_service._sandbox_cache["value"] = None
