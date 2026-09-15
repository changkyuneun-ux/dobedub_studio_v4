"""Login landing dashboard: system status tiles + job KPIs (spec 2026-09-13-dashboard-landing-design.md).

Everything here is DB aggregation plus configuration checks. The only external
call is the Sandbox Pod list (REST v1, one request) behind a short cache; its
failure is isolated into ``sandbox.error`` so the rest of the dashboard renders.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import case, distinct, func, select, text
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.core.timezone_utils import SEOUL_TIMEZONE, UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import BatchJob, TaskExecutionPolicy, User, WorkflowTask
from backend.app.services.migration_status_service import migration_status
from backend.app.services.admin_service import count_active_workflows
from backend.app.services.prompt_llm_client import prompt_llm_status
from backend.app.services.runpod_client import fetch_serverless_billing_daily, runpod_is_configured
from backend.app.services.task_policy_service import (
    ACTIVE_TASK_STATUSES,
    DEFAULT_MAX_ACTIVE_TASKS_PER_USER,
    DEFAULT_MAX_ACTIVE_TASKS_TOTAL,
)
from backend.app.services.workflow_parser import workflow_files
from backend.app.services.workflow_visibility import (
    SUPPORTED_WORKFLOW_IDS,
    TEN_SECOND_CHAIN_WORKFLOW_IDS,
    canonical_workflow_id,
)

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

# 2026-09-15: 컷 길이별(5초/10초) 서버리스 비용 배분. RunPod 인프라 측 최적화가
# 완료된 UTC 2026-09-10 이후 구간만 분리 집계한다 - 그 이전은 10초컷 데이터가
# 사실상 없고(실 프로덕션 조회로 확인) 워크플로 구성이 지금과 달라 실행시간
# 기준 배분이 왜곡될 수 있다. 09-10 이전은 dailyVolume과 동일하게 합계만 노출.
DURATION_SPLIT_CUTOFF_UTC = date(2026, 9, 10)
_BILLING_CACHE_TTL_SECONDS = 300.0
# 2026-09-15 버그 수정: 빌링 조회 실패(네트워크/인증/RunPod 측 오류)를 "그 구간
# 청구가 실제로 0원"인 것처럼 5분간 캐시해 대시보드에 $0.00으로 보여주던 문제.
# 실패는 훨씬 짧게(20초)만 캐시해 빠르게 재시도하고, 성공/실패를 구분해 카드가
# "미조회"와 "실제 0원"을 다르게 표시할 수 있게 한다.
_BILLING_ERROR_RETRY_SECONDS = 20.0
_billing_cache: dict[str, object] = {"at": 0.0, "range": None, "value": None, "error": None}


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


def _duration_bucket(workflow_id: str | None) -> str:
    """workflow_id를 5초/10초/미분류로 분류한다(workflow_visibility가 유일한 판단 기준)."""
    if not workflow_id:
        return "unclassified"
    canonical = canonical_workflow_id(workflow_id)
    if canonical not in SUPPORTED_WORKFLOW_IDS:
        return "unclassified"
    return "tenSec" if canonical in TEN_SECOND_CHAIN_WORKFLOW_IDS else "fiveSec"


def _execution_seconds(status_json: dict | None) -> float:
    """runpod_status_json에서 RunPod가 보고한 executionTime(ms)을 초 단위로 뽑는다.

    누락 시 0을 반환한다 - 그 잡은 실행시간 가중치에 기여하지 않고, 같은 날 다른
    작업들의 executionTime으로만 비용이 배분된다. 그 날 하나도 없으면 그 날은
    통째로 unclassified 처리된다(결측률은 실 프로덕션 조회로 0.03% 수준 확인됨).
    """
    if not isinstance(status_json, dict):
        return 0.0
    value = status_json.get("executionTime")
    if value is None:
        return 0.0
    try:
        return max(0.0, float(value)) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _cached_serverless_billing(settings: Settings, since_day: date, until_day: date) -> tuple[dict[str, dict], str | None]:
    """RunPod 서버리스 일별 청구를 짧게 캐시한다(대시보드 응답마다 외부 호출 방지).

    반환값은 ``(일별 청구 dict, 에러 메시지 또는 None)``. Sandbox 블록
    (_sandbox_cache)과 달리 백그라운드 스레드 갱신은 하지 않는다 - 청구
    데이터는 분 단위로만 바뀌므로 성공 시 TTL(5분) 동안은 캐시를 그대로 쓰고,
    만료되면 이 요청이 동기 호출한다. 실패(네트워크/인증/RunPod 측 오류)는
    "그 구간 청구가 0원"이 아니라 "조회 실패"로 구분해 반환하고, 짧게(20초)만
    캐시해 빠르게 재시도한다 - 실패를 0원으로 착각해 5분간 그대로 보여주는
    사고를 막기 위함(2026-09-15 실사용 중 발견: 건수는 정상 표시되는데 비용만
    전부 $0.00으로 보이는 문제의 원인이었다).
    """
    cache_key = f"{since_day.isoformat()}..{until_day.isoformat()}"
    now = time.monotonic()
    same_range = _billing_cache.get("range") == cache_key
    age = now - float(_billing_cache.get("at") or 0.0)
    cached_error = _billing_cache.get("error")

    if same_range and cached_error is None and _billing_cache.get("value") is not None and age < _BILLING_CACHE_TTL_SECONDS:
        return dict(_billing_cache["value"]), None  # type: ignore[arg-type]
    if same_range and cached_error is not None and age < _BILLING_ERROR_RETRY_SECONDS:
        return {}, str(cached_error)

    try:
        by_day = fetch_serverless_billing_daily(
            api_key=settings.runpod_api_key,
            serverless_id=settings.runpod_endpoint_id,
            start_time=f"{since_day.isoformat()}T00:00:00Z",
            end_time=f"{(until_day + timedelta(days=1)).isoformat()}T00:00:00Z",
        )
        error: str | None = None
    except Exception as exc:  # noqa: BLE001 - 빌링 API 실패를 격리하되 원인은 카드에 노출
        LOGGER.warning("dashboard duration-cost billing fetch failed: %s", exc)
        by_day = {}
        error = f"{type(exc).__name__}: {exc}"

    _billing_cache["at"] = time.monotonic()
    _billing_cache["range"] = cache_key
    _billing_cache["value"] = by_day
    _billing_cache["error"] = error
    return dict(by_day), error


def _utc_day_range(since: datetime, until: datetime) -> list[str]:
    """[since, until) 구간이 걸치는 UTC 달력일 목록을 오름차순으로 반환한다.

    RunPod 서버리스 빌링이 UTC 캘린더일로 집계되므로(_kst_day_range와 달리 KST
    변환을 하지 않는다) 이 카드의 날짜 축은 dailyVolume 등 다른 카드와 최대
    ~9시간(KST-UTC) 어긋날 수 있다 - 09-10 자정 KST 전후 소수 작업이 다른
    카드에서는 09-10일에, 이 카드에서는 09-09일에 잡힐 수 있음(실측상 영향은
    미미하며, 총 비용 정합성이 이 카드의 핵심 요구사항이라 UTC 기준을 우선함).
    """
    start = since.date()
    end = (until - timedelta(microseconds=1)).date() if until > since else start
    days: list[str] = []
    cursor = start
    while cursor <= end:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _duration_cost_breakdown(session: Session, settings: Settings, since: datetime, until: datetime) -> dict:
    """일자별(UTC) RunPod 서버리스 작업 현황 + 실제 청구액을 합쳐 반환한다.

    2026-09-10(UTC) 이전은 5초/10초 구분 없이 그 날의 전체 제출/완료/실패
    건수와 RunPod 청구 총액만 담는다(``split: null``) - 요청 반영: "9월 10일
    이후부터 구분, 9월 9일까지는 전체 건수와 비용으로 표기". 2026-09-10부터는
    같은 항목에 5초컷/10초컷/미분류로 나눈 실행시간 비중 배분 비용을
    ``split``에 추가한다. 한 날짜의 split.fiveSec+tenSec+unclassified 비용
    합은 그 날 totalCostUsd와 항상 일치하고(반올림 오차는 unclassified가
    흡수), 전체 구간 totalCostUsd 합은 RunPod 청구 합계와 일치한다(청구
    레코드가 없는 날은 0비용으로 채움 - RunPod API가 무청구일을 레코드
    생략으로 표현하기 때문).
    """
    rows = session.execute(
        select(
            WorkflowTask.workflow_id,
            WorkflowTask.created_at,
            WorkflowTask.status,
            WorkflowTask.runpod_status_json,
        ).where(
            _live_tasks(),
            WorkflowTask.execution_mode == "runpod",
            WorkflowTask.created_at >= since,
            WorkflowTask.created_at < until,
        )
    ).all()

    day_keys = _utc_day_range(since, until)
    if not day_keys:
        return {"byDay": {}, "summary": None, "billingError": None}

    per_day: dict[str, dict] = {
        day: {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "count": {"fiveSec": 0, "tenSec": 0, "unclassified": 0},
            "execSeconds": {"fiveSec": 0.0, "tenSec": 0.0, "unclassified": 0.0},
        }
        for day in day_keys
    }

    for workflow_id, created_at, status, status_json in rows:
        if created_at is None:
            continue
        day_key = created_at.date().isoformat()
        entry = per_day.get(day_key)
        if entry is None:
            # _utc_day_range는 since/until에서 직접 계산하므로 이 경로는 이론상
            # 발생하지 않지만, 타임존/경계값 실수를 조용히 흡수하지 않기 위해
            # 방어적으로 새 버킷을 만든다(요청 구간 밖 UTC일이 섞였다는 신호).
            entry = per_day.setdefault(day_key, {
                "submitted": 0, "completed": 0, "failed": 0,
                "count": {"fiveSec": 0, "tenSec": 0, "unclassified": 0},
                "execSeconds": {"fiveSec": 0.0, "tenSec": 0.0, "unclassified": 0.0},
            })
        entry["submitted"] += 1
        status_kind = _classify_status(status)
        if status_kind == "completed":
            entry["completed"] += 1
        elif status_kind == "failed":
            entry["failed"] += 1
        if created_at.date() >= DURATION_SPLIT_CUTOFF_UTC:
            bucket = _duration_bucket(workflow_id)
            entry["count"][bucket] += 1
            entry["execSeconds"][bucket] += _execution_seconds(status_json)

    since_day = date.fromisoformat(day_keys[0])
    until_day = date.fromisoformat(day_keys[-1])
    billing_by_day, billing_error = _cached_serverless_billing(settings, since_day, until_day)

    by_day: dict[str, dict] = {}
    # 빌링 조회 실패 시 costUsd를 0으로 채우면 "실제로 무료"와 구분이 안 되므로
    # None으로 남긴다(건수는 DB 조회만으로 구해지므로 정상 표시). 프론트는
    # billingError 유무로 "-"/"조회 실패" 표시와 "$0.00" 표시를 구분한다.
    summary_cost = {"fiveSec": 0.0, "tenSec": 0.0, "unclassified": 0.0}
    summary_count = {"fiveSec": 0, "tenSec": 0, "unclassified": 0}
    summary_since: str | None = None
    summary_until: str | None = None

    for day_key in sorted(per_day):
        entry = per_day[day_key]
        if billing_error is not None:
            day_total_cost = None
        else:
            # RunPod 빌링 API는 비용이 0인 날의 레코드를 아예 생략하므로, 없는
            # 날은 0으로 채운다(0을 "데이터 없음"으로 오인하지 않도록 유의 -
            # billing_error가 None일 때만 유효한 구분이다).
            day_total_cost = float((billing_by_day.get(day_key) or {}).get("totalAmount") or 0.0)
        row = {
            "submitted": entry["submitted"],
            "completed": entry["completed"],
            "failed": entry["failed"],
            "totalCostUsd": None if day_total_cost is None else round(day_total_cost, 4),
            "split": None,
        }
        if date.fromisoformat(day_key) >= DURATION_SPLIT_CUTOFF_UTC:
            exec_seconds = entry["execSeconds"]
            weight_total = sum(exec_seconds.values())
            if day_total_cost is None:
                cost: dict[str, float | None] = {"fiveSec": None, "tenSec": None, "unclassified": None}
            else:
                cost = {"fiveSec": 0.0, "tenSec": 0.0, "unclassified": 0.0}
                if weight_total > 0 and day_total_cost > 0:
                    cost["fiveSec"] = day_total_cost * exec_seconds["fiveSec"] / weight_total
                    cost["tenSec"] = day_total_cost * exec_seconds["tenSec"] / weight_total
                    cost["unclassified"] = day_total_cost - cost["fiveSec"] - cost["tenSec"]
                elif day_total_cost > 0:
                    cost["unclassified"] = day_total_cost

            row["split"] = {
                "fiveSec": {"count": entry["count"]["fiveSec"], "costUsd": None if cost["fiveSec"] is None else round(cost["fiveSec"], 4)},
                "tenSec": {"count": entry["count"]["tenSec"], "costUsd": None if cost["tenSec"] is None else round(cost["tenSec"], 4)},
                "unclassified": {"count": entry["count"]["unclassified"], "costUsd": None if cost["unclassified"] is None else round(cost["unclassified"], 4)},
            }
            summary_since = summary_since or day_key
            summary_until = day_key
            for bucket in ("fiveSec", "tenSec", "unclassified"):
                if cost[bucket] is not None:
                    summary_cost[bucket] += cost[bucket]
                summary_count[bucket] += entry["count"][bucket]

        by_day[day_key] = row

    summary = None
    if summary_since is not None:
        def _per_job(bucket: str):
            if billing_error is not None or not summary_count[bucket]:
                return None
            return round(summary_cost[bucket] / summary_count[bucket], 4)

        summary = {
            "sinceUtc": summary_since,
            "untilUtc": summary_until,
            "fiveSec": {
                "count": summary_count["fiveSec"],
                "costUsd": None if billing_error is not None else round(summary_cost["fiveSec"], 4),
                "costPerJobUsd": _per_job("fiveSec"),
            },
            "tenSec": {
                "count": summary_count["tenSec"],
                "costUsd": None if billing_error is not None else round(summary_cost["tenSec"], 4),
                "costPerJobUsd": _per_job("tenSec"),
            },
            "unclassified": {
                "count": summary_count["unclassified"],
                "costUsd": None if billing_error is not None else round(summary_cost["unclassified"], 4),
                "costPerJobUsd": _per_job("unclassified"),
            },
        }

    return {"byDay": by_day, "summary": summary, "billingError": billing_error}


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
        # 2026-09-15: 컷 길이별(5초/10초) 서버리스 비용 배분 카드. UTC 09-10 이전
        # 구간은 byDay[day].split이 null(전체 제출/완료/실패/비용만) - 프론트가
        # split 유무로 "구분 전/후"를 렌더링한다.
        "durationCostBreakdown": _duration_cost_breakdown(session, settings, since, until),
        "system": _system_block(settings),
        "sandbox": sandbox,
        "worker": worker,
        "db": db,
        "alerts": _evaluate_alerts(recent_hour=recent_hour, worker=worker, db=db, sandbox=sandbox),
        **timestamp_fields("checkedAt", until, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="ecs-application"),
    }
