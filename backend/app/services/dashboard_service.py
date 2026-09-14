"""Login landing dashboard: system status tiles + job KPIs (spec 2026-09-13-dashboard-landing-design.md).

Everything here is DB aggregation plus configuration checks. The only external
call is the Sandbox Pod list (REST v1, one request) behind a short cache; its
failure is isolated into ``sandbox.error`` so the rest of the dashboard renders.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import case, distinct, func, select, text
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.core.timezone_utils import SEOUL_TIMEZONE, UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import BatchJob, TaskExecutionPolicy, User, WorkflowTask
from backend.app.services.migration_status_service import migration_status
from backend.app.services.admin_service import count_active_workflows
from backend.app.services.prompt_llm_client import prompt_llm_status
from backend.app.services.runpod_client import runpod_is_configured
from backend.app.services.task_policy_service import (
    ACTIVE_TASK_STATUSES,
    DEFAULT_MAX_ACTIVE_TASKS_PER_USER,
    DEFAULT_MAX_ACTIVE_TASKS_TOTAL,
)
from backend.app.services.workflow_parser import workflow_files

LOGGER = logging.getLogger("dobedub.dashboard")

RANGE_KEYS = ("today", "7d", "30d")
_RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30}
COMPLETED_STATUSES = frozenset({"COMPLETED", "SUCCESS"})
FAILED_STATUSES = frozenset({"FAILED", "TIMED_OUT", "CANCELLED"})
QUEUED_STATUSES = frozenset({"PENDING_SUBMIT", "QUEUED", "IN_QUEUE"})
RUNNING_STATUSES = frozenset({"IN_PROGRESS", "RUNNING", "DISPATCHING"})
IN_FLIGHT_STATUSES = frozenset(ACTIVE_TASK_STATUSES) | QUEUED_STATUSES | RUNNING_STATUSES
RECENT_LIMIT_DEFAULT = 20
RECENT_LIMIT_MAX = 50
TOP_N = 5
FAILURE_SPIKE_MIN_COUNT = 3
FAILURE_SPIKE_MIN_SAMPLE = 5
FAILURE_SPIKE_RATE = 0.30

# 2026-09-13 성능: Sandbox 블록은 stale-while-revalidate. 요청은 캐시(만료돼도)를 즉시 돌려주고
# 갱신은 백그라운드 스레드가 한다. 캐시가 아예 없으면 pending=True로 응답하고 프론트가 잠시 후
# 재조회한다 — RunPod 호출(수 초, 최대 20초)이 대시보드 응답 시간에 더해지지 않게.
_SANDBOX_CACHE_TTL_SECONDS = 30.0
_sandbox_cache: dict[str, object] = {"at": 0.0, "value": None}
_sandbox_refresh_lock = threading.Lock()
_sandbox_refreshing = False


# --- pure helpers ------------------------------------------------------------


def _classify_status(status: str | None) -> str:
    value = str(status or "").strip().upper()
    if value in COMPLETED_STATUSES:
        return "completed"
    if value in FAILED_STATUSES:
        return "failed"
    if value in QUEUED_STATUSES:
        return "queued"
    if value in RUNNING_STATUSES:
        return "active"
    return "other"


def _range_bounds(range_key: str, now: datetime) -> tuple[datetime, datetime, datetime]:
    """Return ``(since_utc, until_utc, previous_since_utc)`` as naive UTC datetimes.

    ``today`` starts at the current KST midnight; ``7d``/``30d`` start at the KST
    midnight N-1 days before today, so the window always ends "now".
    """
    if range_key not in _RANGE_DAYS:
        raise ValueError(f"range must be one of {', '.join(RANGE_KEYS)}")
    now_utc = now if now.tzinfo is None else now.astimezone(UTC_TIMEZONE).replace(tzinfo=None)
    now_kst = now_utc.replace(tzinfo=UTC_TIMEZONE).astimezone(SEOUL_TIMEZONE)
    start_kst = (now_kst - timedelta(days=_RANGE_DAYS[range_key] - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = start_kst.astimezone(UTC_TIMEZONE).replace(tzinfo=None)
    previous_since_utc = since_utc - (now_utc - since_utc)
    return since_utc, now_utc, previous_since_utc


def _evaluate_alerts(*, recent_hour: dict, worker: dict, db: dict, sandbox: dict) -> list[dict]:
    alerts: list[dict] = []
    if sandbox.get("conflict"):
        alerts.append({
            "id": "sandbox_conflict",
            "level": "danger",
            "message": f"실행 중인 Sandbox Pod {sandbox.get('runningCount') or 2}개 · 하나만 남기고 정지하세요",
            "route": "admin.sandbox",
        })
    duplicates = list(sandbox.get("duplicateStoppedPodIds") or [])
    if duplicates:
        alerts.append({
            "id": "sandbox_duplicate_pod",
            "level": "warning",
            "message": f"중복 Sandbox Pod {len(duplicates)}개 정지 상태({', '.join(duplicates)}) · 삭제 권장",
            "route": "admin.sandbox",
        })
    failed = int(recent_hour.get("failed") or 0)
    completed = int(recent_hour.get("completed") or 0)
    sample = failed + completed
    rate = (failed / sample) if sample else 0.0
    if failed >= FAILURE_SPIKE_MIN_COUNT or (sample >= FAILURE_SPIKE_MIN_SAMPLE and rate >= FAILURE_SPIKE_RATE):
        detail = recent_hour.get("topFailure")
        suffix = f" · {detail}" if detail else ""
        alerts.append({
            "id": "failure_spike",
            "level": "warning",
            "message": f"최근 1시간 실패 {failed}건 (실패율 {round(rate * 100)}%){suffix}",
            "route": "review.history",
        })
    limit = int(worker.get("maxActiveTasksTotal") or 0)
    active = int(worker.get("active") or 0)
    if limit and active >= limit:
        alerts.append({
            "id": "worker_saturated",
            "level": "warning",
            "message": f"Runpod Worker 상한 도달 {active}/{limit} · 대기열 {int(worker.get('queued') or 0)}",
            "route": "admin.taskPolicy",
        })
    if db.get("migrationRequired"):
        alerts.append({
            "id": "migration_pending",
            "level": "danger",
            "message": f"DB 마이그레이션 필요 ({db.get('alembicCurrent') or '-'} → {db.get('alembicHead') or '-'})",
            "route": "admin.status",
        })
    return alerts


# --- SQL blocks --------------------------------------------------------------


def _live_tasks():
    return WorkflowTask.deleted_at.is_(None)


def _status_upper():
    return func.upper(WorkflowTask.status)


def _seconds_between(session: Session, later, earlier):
    """``later - earlier`` in seconds for the session's dialect.

    2026-09-13 hotfix: production runs MySQL (pymysql) — the first release only
    branched postgresql/sqlite and sent SQLite's ``julianday`` to MySQL
    (``FUNCTION julianday does not exist``).
    """
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else "sqlite"
    return _seconds_between_for_dialect(dialect, later, earlier)


def _seconds_between_for_dialect(dialect: str, later, earlier):
    if dialect in {"mysql", "mariadb"}:
        return func.timestampdiff(text("SECOND"), earlier, later)
    if dialect == "postgresql":
        return func.extract("epoch", later - earlier)
    return (func.julianday(later) - func.julianday(earlier)) * 86400.0


def _kpi(session: Session, since: datetime, until: datetime, previous_since: datetime) -> dict:
    in_range = [_live_tasks(), WorkflowTask.created_at >= since, WorkflowTask.created_at < until]
    status = _status_upper()
    completed_case = case((status.in_(COMPLETED_STATUSES), 1), else_=0)
    failed_case = case((status.in_(FAILED_STATUSES), 1), else_=0)
    row = session.execute(
        select(
            func.count(WorkflowTask.id),
            func.sum(completed_case),
            func.sum(failed_case),
            func.sum(case((status.in_(FAILED_STATUSES) & WorkflowTask.last_dispatch_error.isnot(None), 1), else_=0)),
            func.sum(case((status == "TIMED_OUT", 1), else_=0)),
            func.avg(case((status.in_(COMPLETED_STATUSES), WorkflowTask.elapsed_seconds), else_=None)),
            func.avg(
                case(
                    (WorkflowTask.started_at.isnot(None), _seconds_between(session, WorkflowTask.started_at, WorkflowTask.created_at)),
                    else_=None,
                )
            ),
            func.count(distinct(WorkflowTask.user_id)),
        ).where(*in_range)
    ).one()
    submitted, completed, failed, failed_dispatch, failed_timeout, avg_elapsed, avg_delay, active_users = row
    previous_submitted = int(
        session.scalar(
            select(func.count(WorkflowTask.id)).where(
                _live_tasks(), WorkflowTask.created_at >= previous_since, WorkflowTask.created_at < since
            )
        )
        or 0
    )
    current = session.execute(
        select(
            func.sum(case((status.in_(IN_FLIGHT_STATUSES), 1), else_=0)),
            func.sum(case((status.in_(QUEUED_STATUSES), 1), else_=0)),
        ).where(_live_tasks())
    ).one()
    batch_in_progress = int(session.scalar(select(func.count(BatchJob.id)).where(BatchJob.status == "INCOMPLETE")) or 0)
    completed = int(completed or 0)
    failed = int(failed or 0)
    submitted = int(submitted or 0)
    finished = completed + failed
    return {
        "submitted": submitted,
        "submittedDeltaPercent": (round((submitted - previous_submitted) / previous_submitted * 100, 1) if previous_submitted else None),
        "completed": completed,
        "successRate": (round(completed / finished, 4) if finished else None),
        "active": int(current[0] or 0),
        "queued": int(current[1] or 0),
        "failed": failed,
        "failedDispatch": int(failed_dispatch or 0),
        "failedTimeout": int(failed_timeout or 0),
        "avgElapsedSeconds": (round(float(avg_elapsed)) if avg_elapsed is not None else None),
        "avgDelaySeconds": (round(float(avg_delay)) if avg_delay is not None else None),
        "activeUsers": int(active_users or 0),
        "batchJobsInProgress": batch_in_progress,
    }


def _workflow_name(workflow_id: str | None) -> str:
    return Path(str(workflow_id or "")).stem or str(workflow_id or "")


def _recent(session: Session, since: datetime, until: datetime, limit: int) -> list[dict]:
    rows = session.execute(
        select(WorkflowTask, User.name)
        .outerjoin(User, User.id == WorkflowTask.user_id)
        .where(_live_tasks(), WorkflowTask.created_at >= since, WorkflowTask.created_at < until)
        .order_by(WorkflowTask.created_at.desc())
        .limit(limit)
    ).all()
    items: list[dict] = []
    for task, user_name in rows:
        items.append({
            "taskId": task.id,
            **timestamp_fields("createdAt", task.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="workflow-task"),
            "user": {"id": task.user_id, "name": user_name or task.user_id},
            "workflowId": task.workflow_id,
            "workflowName": _workflow_name(task.workflow_id),
            "workerName": task.worker_name,
            "status": str(task.status or "").upper(),
            "statusKind": _classify_status(task.status),
            "elapsedSeconds": task.elapsed_seconds,
            "lastDispatchError": task.last_dispatch_error,
            "batchJobId": task.batch_job_id,
        })
    return items


DAILY_STATUS_KINDS = ("submitted", "completed", "failed", "active", "queued", "other")


def _kst_day(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC_TIMEZONE) if value.tzinfo is None else value.astimezone(UTC_TIMEZONE)
    return aware.astimezone(SEOUL_TIMEZONE).date().isoformat()


def _kst_day_range(since: datetime, until: datetime) -> list[str]:
    """[since, until) 구간이 걸치는 KST 달력일 목록을 오름차순으로 반환한다."""
    start_day = _kst_day(since)
    end_day = _kst_day(until - timedelta(seconds=1)) if until > since else start_day
    start = datetime.fromisoformat(start_day)
    end = datetime.fromisoformat(end_day)
    days: list[str] = []
    cursor = start
    while cursor <= end:
        days.append(cursor.date().isoformat())
        cursor += timedelta(days=1)
    return days


def _daily_volume(
    session: Session,
    since: datetime,
    until: datetime,
    *,
    user_id: str | None = None,
    workflow_id: str | None = None,
    status_kind: str | None = None,
) -> list[dict]:
    """일자별(KST) 작업 제출량을 집계한다.

    2026-09-14: 대시보드 "최근 작업" 목록(개별 작업 테이블)을, 작업 현황에서
    선택한 기간(오늘/7일/30일)에 맞춘 일자별 작업량 그래프로 대체하기 위해
    추가됨. "최근 작업" 테이블은 limit(기본 20건)으로 잘려 있어 그래프 집계에
    쓰기엔 부정확하므로, 여기서는 범위 내 전체 작업을 대상으로 별도 집계한다.
    필터(작업자/워크플로/상태)는 SQL WHERE 절에서 적용한다.
    """
    conditions = [_live_tasks(), WorkflowTask.created_at >= since, WorkflowTask.created_at < until]
    if user_id:
        conditions.append(WorkflowTask.user_id == user_id)
    if workflow_id:
        conditions.append(WorkflowTask.workflow_id == workflow_id)
    rows = session.execute(select(WorkflowTask.created_at, WorkflowTask.status).where(*conditions)).all()

    buckets: dict[str, dict[str, int]] = {
        day: {"date": day, **{kind: 0 for kind in DAILY_STATUS_KINDS}}
        for day in _kst_day_range(since, until)
    }
    for created_at, status in rows:
        if created_at is None:
            continue
        kind = _classify_status(status)
        if status_kind and kind != status_kind:
            continue
        day = _kst_day(created_at)
        bucket = buckets.setdefault(day, {"date": day, **{k: 0 for k in DAILY_STATUS_KINDS}})
        bucket["submitted"] += 1
        bucket[kind] = bucket.get(kind, 0) + 1

    return [buckets[day] for day in sorted(buckets)]


def _filter_options(session: Session, since: datetime, until: datetime) -> dict:
    """일자별 그래프 필터(작업자/워크플로) 드롭다운 옵션 — 범위 내 전체 작업 기준(필터 자체와 무관하게 고정).
    """
    rows = session.execute(
        select(distinct(WorkflowTask.user_id), User.name)
        .outerjoin(User, User.id == WorkflowTask.user_id)
        .where(_live_tasks(), WorkflowTask.created_at >= since, WorkflowTask.created_at < until)
    ).all()
    users = sorted(
        ({"id": user_id, "name": name or user_id or "-"} for user_id, name in rows if user_id),
        key=lambda item: item["name"],
    )
    workflow_rows = session.execute(
        select(distinct(WorkflowTask.workflow_id))
        .where(_live_tasks(), WorkflowTask.created_at >= since, WorkflowTask.created_at < until)
    ).all()
    workflows = sorted(
        ({"id": workflow_id, "name": _workflow_name(workflow_id)} for (workflow_id,) in workflow_rows if workflow_id),
        key=lambda item: item["name"],
    )
    return {"users": users, "workflows": workflows}


def _by_user(session: Session, since: datetime, until: datetime, top: int = TOP_N) -> list[dict]:
    status = _status_upper()
    rows = session.execute(
        select(
            WorkflowTask.user_id,
            User.name,
            func.count(WorkflowTask.id).label("submitted"),
            func.sum(case((status.in_(FAILED_STATUSES), 1), else_=0)).label("failed"),
        )
        .outerjoin(User, User.id == WorkflowTask.user_id)
        .where(_live_tasks(), WorkflowTask.created_at >= since, WorkflowTask.created_at < until)
        .group_by(WorkflowTask.user_id, User.name)
        .order_by(func.count(WorkflowTask.id).desc(), WorkflowTask.user_id)
        .limit(top)
    ).all()
    return [
        {"userId": user_id, "name": name or user_id or "-", "submitted": int(submitted or 0), "failed": int(failed or 0)}
        for user_id, name, submitted, failed in rows
    ]


def _by_workflow(session: Session, since: datetime, until: datetime, top: int = TOP_N) -> list[dict]:
    status = _status_upper()
    rows = session.execute(
        select(
            WorkflowTask.workflow_id,
            func.count(WorkflowTask.id).label("submitted"),
            func.avg(case((status.in_(COMPLETED_STATUSES), WorkflowTask.elapsed_seconds), else_=None)).label("avg_elapsed"),
        )
        .where(_live_tasks(), WorkflowTask.created_at >= since, WorkflowTask.created_at < until)
        .group_by(WorkflowTask.workflow_id)
        .order_by(func.count(WorkflowTask.id).desc(), WorkflowTask.workflow_id)
        .limit(top)
    ).all()
    return [
        {
            "workflowId": workflow_id,
            "workflowName": _workflow_name(workflow_id),
            "submitted": int(submitted or 0),
            "avgElapsedSeconds": (round(float(avg_elapsed)) if avg_elapsed is not None else None),
        }
        for workflow_id, submitted, avg_elapsed in rows
    ]


def _worker(session: Session) -> dict:
    status = _status_upper()
    row = session.execute(
        select(
            func.sum(case((status.in_(ACTIVE_TASK_STATUSES), 1), else_=0)),
            func.sum(case((status.in_(QUEUED_STATUSES), 1), else_=0)),
        ).where(_live_tasks())
    ).one()
    policy = session.get(TaskExecutionPolicy, 1)
    return {
        "active": int(row[0] or 0),
        "queued": int(row[1] or 0),
        "maxActiveTasksTotal": int(policy.max_active_tasks_total) if policy else DEFAULT_MAX_ACTIVE_TASKS_TOTAL,
        "maxActiveTasksPerUser": int(policy.max_active_tasks_per_user) if policy else DEFAULT_MAX_ACTIVE_TASKS_PER_USER,
    }


def _recent_hour(session: Session, until: datetime) -> dict:
    since = until - timedelta(hours=1)
    status = _status_upper()
    # created_at 하한(30일)으로 인덱스 범위 스캔을 유도한다(updated_at에는 인덱스가 없음).
    window = [_live_tasks(), WorkflowTask.created_at >= until - timedelta(days=30), WorkflowTask.updated_at >= since, WorkflowTask.updated_at < until]
    row = session.execute(
        select(
            func.sum(case((status.in_(FAILED_STATUSES), 1), else_=0)),
            func.sum(case((status.in_(COMPLETED_STATUSES), 1), else_=0)),
        ).where(*window)
    ).one()
    top = session.execute(
        select(WorkflowTask.workflow_id, WorkflowTask.worker_name, func.count(WorkflowTask.id).label("n"))
        .where(*window, status.in_(FAILED_STATUSES))
        .group_by(WorkflowTask.workflow_id, WorkflowTask.worker_name)
        .order_by(func.count(WorkflowTask.id).desc())
        .limit(1)
    ).first()
    top_failure = None
    if top:
        top_failure = _workflow_name(top[0]) + (f" ({top[1]})" if top[1] else "")
    return {"failed": int(row[0] or 0), "completed": int(row[1] or 0), "topFailure": top_failure}


# --- system / sandbox blocks --------------------------------------------------


def _system_block(settings: Settings) -> dict:
    llm = prompt_llm_status(settings)
    try:
        workflow_count = len(workflow_files(settings.workflows_dir))
    except Exception:  # noqa: BLE001
        workflow_count = None
    try:
        _, active_workflow_count = count_active_workflows()
    except Exception:  # noqa: BLE001
        active_workflow_count = None
    grok_configured = bool(
        settings.grok_enabled
        and settings.grok_api_key
        and not settings.grok_api_key.startswith("your_")
    )
    return {
        "comfy": {
            "configured": runpod_is_configured(settings.runpod_api_key, settings.runpod_endpoint_id),
            "executionMode": "dry-run" if settings.dry_run else "runpod",
            "dryRun": bool(settings.dry_run),
        },
        "promptLlm": {
            "configured": bool(llm.get("configured")),
            "provider": llm.get("provider"),
            "model": llm.get("model"),
            "timeoutSeconds": llm.get("timeout"),
        },
        # 2026-09-14: 대시보드 상단 타일 요청 — "QWEN PROMPT LLM" 대신 Grok 이미지 프롬프트
        # 생성 상태를 보여준다(promptLlm 블록 자체는 admin 시스템 상태 화면 등 다른 화면이
        # 참조하므로 그대로 둔다).
        "grok": {
            "configured": grok_configured,
            "enabled": bool(settings.grok_enabled),
            "model": settings.grok_model,
            "timeoutSeconds": settings.grok_request_timeout_seconds,
        },
        "workflows": {"count": workflow_count, "activeCount": active_workflow_count},
    }


def _sandbox_block(settings: Settings, session: Session, *, use_cache: bool = True, sync: bool = False) -> dict:
    """Return the Sandbox tile block without blocking on RunPod.

    ``sync=True`` (tests / explicit refresh) computes inline. Otherwise a fresh cache is
    returned as-is, a stale cache is returned while a background refresh runs, and an
    empty cache yields ``pending=True`` (the frontend re-polls shortly after).
    """
    from backend.app.services.sandbox_pod_service import sandbox_pod_is_configured

    if not sandbox_pod_is_configured(settings):
        return _empty_sandbox(configured=False)
    now = time.monotonic()
    cached = _sandbox_cache.get("value")
    fresh = cached is not None and now - float(_sandbox_cache.get("at") or 0.0) < _SANDBOX_CACHE_TTL_SECONDS
    if sync or not use_cache:
        return _refresh_sandbox_cache(settings)
    if cached is not None and fresh:
        return dict(cached)  # type: ignore[arg-type]
    _start_sandbox_refresh(settings)
    if cached is not None:
        return {**cached, "stale": True}  # type: ignore[dict-item]
    return {**_empty_sandbox(configured=True), "pending": True}


def _start_sandbox_refresh(settings: Settings) -> None:
    global _sandbox_refreshing
    with _sandbox_refresh_lock:
        if _sandbox_refreshing:
            return
        _sandbox_refreshing = True

    def _run() -> None:
        global _sandbox_refreshing
        try:
            _refresh_sandbox_cache(settings)
        finally:
            with _sandbox_refresh_lock:
                _sandbox_refreshing = False

    threading.Thread(target=_run, name="dashboard-sandbox-refresh", daemon=True).start()


def _refresh_sandbox_cache(settings: Settings) -> dict:
    """Call RunPod (list only, no probes) and store the tile block. Uses its own DB session."""
    from backend.app.db.session import SessionLocal
    from backend.app.services.sandbox_pod_service import sandbox_pod_status

    db = SessionLocal()
    try:
        status = sandbox_pod_status(settings, db, include_live=False)
        pods = list(status.get("pods") or [])
        stopped_by_gpu: dict[str, list[str]] = {}
        for pod in pods:
            if str(pod.get("desiredStatus") or "").upper() == "EXITED" and pod.get("gpuTypeId"):
                stopped_by_gpu.setdefault(str(pod["gpuTypeId"]), []).append(str(pod.get("podId")))
        duplicates = [pod_id for ids in stopped_by_gpu.values() if len(ids) > 1 for pod_id in ids[1:]]
        value = {
            "configured": True,
            "activePodId": status.get("activePodId"),
            "activePodName": status.get("activePodName") or status.get("podName"),
            "desiredStatus": status.get("desiredStatus"),
            "gpuTier": status.get("gpuTier"),
            "gpuTypeId": status.get("gpuTypeId"),
            "podCount": len(pods),
            "runningCount": sum(1 for pod in pods if str(pod.get("desiredStatus") or "").upper() == "RUNNING"),
            "conflict": bool(status.get("conflict")),
            "duplicateStoppedPodIds": duplicates,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - isolate RunPod failures into the tile
        LOGGER.warning("dashboard sandbox block failed: %s", exc)
        value = {**_empty_sandbox(configured=True), "error": f"{type(exc).__name__}: {exc}"}
    finally:
        db.close()
    _sandbox_cache["at"] = time.monotonic()
    _sandbox_cache["value"] = value
    return dict(value)


def _empty_sandbox(*, configured: bool) -> dict:
    return {
        "configured": configured,
        "activePodId": None,
        "activePodName": None,
        "desiredStatus": None,
        "gpuTier": None,
        "gpuTypeId": None,
        "podCount": 0,
        "runningCount": 0,
        "conflict": False,
        "duplicateStoppedPodIds": [],
        "error": None,
        "pending": False,
        "stale": False,
    }


# --- entry point -------------------------------------------------------------


def dashboard_summary(
    session: Session,
    *,
    range_key: str = "7d",
    limit: int = RECENT_LIMIT_DEFAULT,
    now: datetime | None = None,
    settings: Settings | None = None,
    include_sandbox: bool = True,
    sandbox_sync: bool = False,
    filter_user_id: str | None = None,
    filter_workflow_id: str | None = None,
    filter_status_kind: str | None = None,
) -> dict:
    settings = settings or get_settings()
    current = now or utc_now().replace(tzinfo=None)
    since, until, previous_since = _range_bounds(range_key, current)
    limit = max(1, min(int(limit or RECENT_LIMIT_DEFAULT), RECENT_LIMIT_MAX))
    worker = _worker(session)
    db = migration_status(session)
    sandbox = _sandbox_block(settings, session, sync=sandbox_sync) if include_sandbox else _empty_sandbox(configured=False)
    recent_hour = _recent_hour(session, until)
    return {
        "range": range_key,
        **timestamp_fields("since", since, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="dashboard"),
        **timestamp_fields("until", until, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="dashboard"),
        "kpi": _kpi(session, since, until, previous_since),
        "recent": _recent(session, since, until, limit),
        # 2026-09-14: "최근 작업" 목록을 대체하는 일자별(KST) 작업량 그래프 데이터.
        # 필터(작업자/워크플로/상태)가 지정되면 그 조건으로 집계한다.
        "dailyVolume": _daily_volume(
            session, since, until,
            user_id=filter_user_id, workflow_id=filter_workflow_id, status_kind=filter_status_kind,
        ),
        "dailyVolumeFilters": {"user": filter_user_id, "workflow": filter_workflow_id, "status": filter_status_kind},
        "filterOptions": _filter_options(session, since, until),
        "byUser": _by_user(session, since, until),
        "byWorkflow": _by_workflow(session, since, until),
        "system": _system_block(settings),
        "sandbox": sandbox,
        "worker": worker,
        "db": db,
        "alerts": _evaluate_alerts(recent_hour=recent_hour, worker=worker, db=db, sandbox=sandbox),
        **timestamp_fields("checkedAt", until, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="ecs-application"),
    }
