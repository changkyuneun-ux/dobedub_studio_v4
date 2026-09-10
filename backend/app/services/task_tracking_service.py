from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.app.core.timezone_utils import (
    SEOUL_TIMEZONE,
    UTC_TIMEZONE,
    epoch_to_seoul_naive,
    format_seoul_datetime,
    now_seoul_naive,
    parse_timestamp,
    seoul_naive_to_epoch,
    timestamp_fields,
    timestamp_pair,
)
from backend.app.db.models import Asset, Collection, CollectionItem, ImagePromptDraft, PromptFeedback, TaskInputAsset, TaskOutputAsset, TaskPrompt, User, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services.json_repository import hydrate_input_images, hydrate_output_asset
from backend.app.services.metadata_service import get_workflow_widget_metadata
from backend.app.services import workflow_service


TERMINAL_STATES = {"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"}
ACTIVE_STATES = {"QUEUED", "IN_QUEUE", "IN_PROGRESS", "RUNNING"}
PENDING_SUBMISSION_STATES = {"PENDING_SUBMIT", "DISPATCHING"}
REWORKABLE_STATES = {"FAILED", "CANCELLED", "TIMED_OUT"}
REPLAYABLE_STATES = TERMINAL_STATES
STALE_DISPATCH_CLAIM_SECONDS = 300
RUNPOD_TIMESTAMP_KEYS = {
    "createdat", "queuedat", "startedat", "completedat", "finishedat", "endedat",
    "cancelledat", "updatedat", "laststartedat", "laststatuschange", "statuschangedat",
}
REVIEW_FLAG_LABELS = {
    "originalPreserved": "원본 유지 preserve original",
    # 과거 JSON 리뷰도 새 기준으로 검색 가능해야 한다.
    "intentMatched": "원본 유지 preserve original",
    "identityPreserved": "원본 유지 preserve original",
    "naturalMotion": "움직임 자연스러움 natural motion",
    "noDistortion": "왜곡 깨짐 없음 no distortion",
    "backgroundStable": "배경 안정성 background stable",
    "colorStable": "색감 안정 color stable",
}

# 이전 리뷰는 JSON 필드로 저장되어 있어 별도 데이터 마이그레이션 없이도 읽을 수
# 있다. 새 저장 요청에서는 아래 다섯 가지 운영 기준으로 정규화한다.
LEGACY_REVIEW_FLAG_ALIASES = {
    "originalPreserved": ("originalPreserved", "intentMatched", "identityPreserved"),
    "naturalMotion": ("naturalMotion",),
    "noDistortion": ("noDistortion",),
    "backgroundStable": ("backgroundStable",),
    "colorStable": ("colorStable",),
}


def record_job_created(job: dict, *, resolve_asset: Callable[[str], tuple[dict, Path]] | None = None) -> None:
    _with_session(lambda session: _record_job_created(session, job, resolve_asset=resolve_asset))


def record_job_status(job: dict, *, resolve_asset: Callable[[str], tuple[dict, Path]] | None = None) -> None:
    _with_session(lambda session: _record_job_status(session, job, resolve_asset=resolve_asset))


# 이력 조회는 언제나 한 페이지 분량으로 제한된다. page/page_size를 생략하면 전체
# 테이블을 읽던 이전 시그니처는 호출부가 실수하기 쉬웠고, 실제로 prompt_options()가
# 그 경로로 workflow_tasks 전체를 메모리에 올려 ECS OOM을 냈다.
MAX_HISTORY_PAGE_SIZE = 200
MAX_HISTORY_SELECTION_SIZE = 1000


def task_history_items(
    page: int = 1,
    page_size: int = MAX_HISTORY_PAGE_SIZE,
    *,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    date_from: str = "",
    date_to: str = "",
    batch_job_id: str = "",
    job_id: str = "",
) -> list[dict]:
    session = SessionLocal()
    try:
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(MAX_HISTORY_PAGE_SIZE, int(page_size or MAX_HISTORY_PAGE_SIZE)))
        conditions = _history_filter_conditions(
            workflow_id=workflow_id,
            result_status=result_status,
            worker_id=worker_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
            job_id=job_id,
        )
        id_statement = (
            select(WorkflowTask.id)
            # 작업 생성 직후부터 같은 Task History에서 상태를 추적한다. 완료/실패만
            # 보이던 이전 필터는 활성 Task를 숨겨 멀티 작업 운영을 불가능하게 했다.
            .where(*conditions)
            .order_by(WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
            .offset((safe_page - 1) * safe_page_size)
            .limit(safe_page_size)
        )
        task_ids = list(session.scalars(id_statement))
        if not task_ids:
            return []

        tasks = session.scalars(
            select(WorkflowTask)
            .options(
                selectinload(WorkflowTask.input_assets).selectinload(TaskInputAsset.asset),
                selectinload(WorkflowTask.output_assets).selectinload(TaskOutputAsset.asset),
            )
            .where(WorkflowTask.id.in_(task_ids))
        ).all()
        # 이 페이지가 참조하는 자산만 읽는다. assets 테이블 전체를 읽던 이전
        # 구현은 자산이 쌓일수록 모든 이력 조회를 함께 느리게 만들었다.
        assets_by_id = _assets_by_ids(session, _history_asset_ids(tasks))
        prompt_batch_ids_by_draft_id = _prompt_batch_ids_by_draft_id(session, tasks)
        default_negative_prompts_by_workflow_id = _default_negative_prompts_by_workflow_id({
            str(task.workflow_id or "")
            for task in tasks
            if task.workflow_id
        })
        tasks_by_id = {task.id: task for task in tasks}
        return [
            _task_to_history_item(
                tasks_by_id[task_id],
                assets_by_id,
                prompt_batch_ids_by_draft_id,
                default_negative_prompts_by_workflow_id,
            )
            for task_id in task_ids
            if task_id in tasks_by_id
        ]
    finally:
        session.close()


def task_history_total(
    *,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    date_from: str = "",
    date_to: str = "",
    batch_job_id: str = "",
    job_id: str = "",
) -> int:
    session = SessionLocal()
    try:
        conditions = _history_filter_conditions(
            workflow_id=workflow_id,
            result_status=result_status,
            worker_id=worker_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
            job_id=job_id,
        )
        statement = (
            select(func.count())
            .select_from(WorkflowTask)
            # soft delete된 작업은 총계에서도 제외(목록과 페이지네이션 일치).
            .where(*conditions)
        )
        return int(session.scalar(statement) or 0)
    finally:
        session.close()


def _history_status_stat_key(status: str | None) -> str:
    normalized = str(status or "").upper()
    if normalized in {"COMPLETED", "SUCCESS"}:
        return "completed"
    if normalized in {"FAILED", "TIMED_OUT"}:
        return "failed"
    if normalized == "CANCELLED":
        return "cancelled"
    if normalized in PENDING_SUBMISSION_STATES:
        return "pendingSubmit"
    return "active"


def task_history_stats(
    *,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    date_from: str = "",
    date_to: str = "",
    batch_job_id: str = "",
    job_id: str = "",
) -> dict[str, int]:
    session = SessionLocal()
    try:
        conditions = _history_filter_conditions(
            workflow_id=workflow_id,
            result_status=result_status,
            worker_id=worker_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
            job_id=job_id,
        )
        rows = session.execute(
            select(WorkflowTask.status, func.count())
            .select_from(WorkflowTask)
            .where(*conditions)
            .group_by(WorkflowTask.status)
        ).all()
        stats = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "pendingSubmit": 0,
            "active": 0,
        }
        for status, count in rows:
            value = int(count or 0)
            stats["total"] += value
            stats[_history_status_stat_key(status)] += value
        return stats
    finally:
        session.close()


def _history_filter_conditions(
    *,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    date_from: str = "",
    date_to: str = "",
    batch_job_id: str = "",
    job_id: str = "",
) -> list:
    conditions = [WorkflowTask.deleted_at.is_(None)]
    if workflow_id:
        conditions.append(WorkflowTask.workflow_id == workflow_id)
    if worker_id:
        conditions.append(WorkflowTask.user_id == worker_id)
    if batch_job_id:
        conditions.append(or_(
            WorkflowTask.batch_job_id == batch_job_id,
            select(ImagePromptDraft.id)
            .where(
                ImagePromptDraft.id == WorkflowTask.prompt_draft_id,
                ImagePromptDraft.prompt_batch_id == batch_job_id,
            )
            .exists(),
        ))
    if job_id:
        conditions.append(or_(
            WorkflowTask.id == job_id,
            WorkflowTask.runpod_job_id == job_id,
        ))
    from_value = _parse_history_date_boundary(date_from, end_of_day=False)
    if from_value is not None:
        conditions.append(WorkflowTask.created_at >= from_value)
    to_value = _parse_history_date_boundary(date_to, end_of_day=True)
    if to_value is not None:
        conditions.append(WorkflowTask.created_at <= to_value)
    result_condition = _history_result_status_condition(result_status)
    if result_condition is not None:
        conditions.append(result_condition)
    return conditions


def task_history_selection_ids(
    *,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    date_from: str = "",
    date_to: str = "",
    batch_job_id: str = "",
    job_id: str = "",
) -> dict[str, object]:
    """Return bounded terminal task IDs for cross-page history selection."""
    session = SessionLocal()
    try:
        conditions = _history_filter_conditions(
            workflow_id=workflow_id,
            result_status=result_status,
            worker_id=worker_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
            job_id=job_id,
        )
        rows = list(session.scalars(
            select(WorkflowTask.id)
            .where(*conditions, WorkflowTask.status.in_(TERMINAL_STATES))
            .order_by(WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
            .limit(MAX_HISTORY_SELECTION_SIZE + 1)
        ))
        return {
            "taskIds": rows[:MAX_HISTORY_SELECTION_SIZE],
            "truncated": len(rows) > MAX_HISTORY_SELECTION_SIZE,
        }
    finally:
        session.close()


def _parse_history_date_boundary(value: str, *, end_of_day: bool) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if len(raw) <= 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999) if end_of_day else parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    return parsed.replace(tzinfo=None)


def _history_result_status_condition(value: str):
    normalized = str(value or "").strip().upper()
    if not normalized:
        return None
    if normalized in {"COMPLETED", "SUCCESS"}:
        return WorkflowTask.status.in_({"COMPLETED", "SUCCESS"})
    if normalized == "FAILED":
        return WorkflowTask.status.in_({"FAILED", "TIMED_OUT"})
    if normalized == "CANCELLED":
        return WorkflowTask.status == "CANCELLED"
    if normalized == "TIMED_OUT":
        return WorkflowTask.status == "TIMED_OUT"
    if normalized in {"ACTIVE", "RUNNING", "IN_PROGRESS"}:
        return or_(WorkflowTask.status.is_(None), WorkflowTask.status.not_in(TERMINAL_STATES))
    return None


def list_assets(
    page: int | None = None,
    page_size: int | None = None,
    *,
    asset_type: str = "",
    workflow_id: str = "",
    date_from: str = "",
    date_to: str = "",
    collection_id: int | None = None,
    uncategorized: bool = False,
) -> list[dict]:
    """2026-08-11 재구성: "Asset 관리" 화면 통합 요청으로 자산 목록을 **출력(output)
    기준**으로 바꿨다 - 예전에는 `assets` 테이블 전체(입력 이미지·출력 영상 구분 없이)를
    평평하게 나열했지만, 이제는 `task_output_assets`에 연결된 자산만 최상위 행으로 삼고,
    같은 작업(task_id)의 입력 이미지들은 그 출력 행에 `inputAssets`로 종속시킨다
    (design_handoff 첨부 목업 - Asset_id/생성일/생성자/Input asset Images/Collection
    분류 열 구조). 한 번도 출력으로 이어지지 못한 입력 전용 업로드(중단된 작업의
    키프레임 등)는 사용자 결정에 따라 이 목록에서 제외한다 - 갈 곳이 없어지는 게
    아니라 애초에 "출력 자산" 목록이 아니므로 대상이 아니다.
    `collection_id`/`uncategorized`는 신규 필터: 컬렉션 하나를 지정하거나(다대다이므로
    한 자산이 여러 컬렉션 필터에 동시에 걸릴 수 있음), 반대로 "미분류"(어느 컬렉션에도
    없는 자산)만 볼 수 있다."""
    session = SessionLocal()
    try:
        statement = (
            select(TaskOutputAsset.asset_id)
            .join(Asset, Asset.id == TaskOutputAsset.asset_id)
            .order_by(Asset.created_at.desc(), TaskOutputAsset.id.desc())
        )
        conditions = _asset_filter_conditions(
            asset_type=asset_type,
            workflow_id=workflow_id,
            date_from=date_from,
            date_to=date_to,
            collection_id=collection_id,
            uncategorized=uncategorized,
        )
        if conditions:
            statement = statement.where(*conditions)
        if page is not None and page_size is not None:
            safe_page = max(1, int(page))
            safe_page_size = max(1, min(200, int(page_size)))
            statement = statement.offset((safe_page - 1) * safe_page_size).limit(safe_page_size)
        # 동일 자산이 여러 작업의 출력으로 연결될 일은 없지만(assets.id는 생성
        # 시점에 1건만 만들어짐), 방어적으로 중복은 첫 값만 남긴다.
        asset_ids: list[str] = []
        seen = set()
        for asset_id in session.scalars(statement):
            if asset_id in seen:
                continue
            seen.add(asset_id)
            asset_ids.append(asset_id)
        if not asset_ids:
            return []

        links = session.scalars(
            select(TaskOutputAsset)
            .where(TaskOutputAsset.asset_id.in_(asset_ids))
            .order_by(TaskOutputAsset.created_at.desc(), TaskOutputAsset.id.desc())
        ).all()
        link_by_asset: dict[str, TaskOutputAsset] = {}
        for link in links:
            link_by_asset.setdefault(link.asset_id, link)
        task_ids = {link.task_id for link in link_by_asset.values()}
        tasks_by_id = {
            task.id: task
            for task in (
                session.scalars(
                    select(WorkflowTask).options(selectinload(WorkflowTask.user)).where(WorkflowTask.id.in_(task_ids))
                ).all()
                if task_ids
                else []
            )
        }
        # 종속 입력 이미지: 같은 task_id의 TaskInputAsset을 slot 순서로 모아둔다.
        input_links = session.scalars(
            select(TaskInputAsset)
            .where(TaskInputAsset.task_id.in_(task_ids))
            .order_by(TaskInputAsset.task_id, TaskInputAsset.slot_index.asc())
        ).all() if task_ids else []
        # 결과 행과 그 행이 참조하는 입력 이미지까지만 읽는다. 이전 구현은 이 화면에
        # 표시하지 않는 모든 asset을 매번 읽어 RDS 데이터가 늘수록 컬렉션 변경 후
        # 새로고침이 느려졌다.
        related_asset_ids = set(asset_ids)
        related_asset_ids.update(link.asset_id for link in input_links)
        assets_by_id = _assets_by_ids(session, related_asset_ids)
        inputs_by_task: dict[str, list[dict]] = {}
        for link in input_links:
            asset_json = assets_by_id.get(link.asset_id)
            if not asset_json:
                continue
            inputs_by_task.setdefault(link.task_id, []).append(dict(asset_json))
        # 이 자산이 속한 컬렉션들(다대다) - "Collection 분류" 칩 목록.
        collection_items = session.execute(
            select(CollectionItem.asset_id, Collection.id, Collection.name)
            .join(Collection, Collection.id == CollectionItem.collection_id)
            .where(CollectionItem.asset_id.in_(asset_ids))
        ).all()
        collections_by_asset: dict[str, list[dict]] = {}
        for asset_id, cid, cname in collection_items:
            collections_by_asset.setdefault(asset_id, []).append({"id": cid, "name": cname})

        items = []
        for asset_id in asset_ids:
            asset_json = assets_by_id.get(asset_id)
            if not asset_json:
                continue
            item = dict(asset_json)
            link = link_by_asset.get(asset_id)
            item["taskId"] = link.task_id if link else ""
            item["outputRole"] = link.output_role if link else ""
            item["segmentIndex"] = link.segment_index if link else None
            task = tasks_by_id.get(link.task_id) if link else None
            if task:
                item["workflowId"] = task.workflow_id
                item["createdBy"] = task.user.name if task.user else task.user_id
            else:
                item["createdBy"] = None
            item["inputAssets"] = inputs_by_task.get(link.task_id, []) if link else []
            item["collections"] = collections_by_asset.get(asset_id, [])
            items.append(item)
        return items
    finally:
        session.close()


def assets_total(
    *,
    asset_type: str = "",
    workflow_id: str = "",
    date_from: str = "",
    date_to: str = "",
    collection_id: int | None = None,
    uncategorized: bool = False,
) -> int:
    session = SessionLocal()
    try:
        conditions = _asset_filter_conditions(
            asset_type=asset_type,
            workflow_id=workflow_id,
            date_from=date_from,
            date_to=date_to,
            collection_id=collection_id,
            uncategorized=uncategorized,
        )
        statement = select(func.count(func.distinct(TaskOutputAsset.asset_id))).select_from(TaskOutputAsset).join(
            Asset, Asset.id == TaskOutputAsset.asset_id
        )
        if conditions:
            statement = statement.where(*conditions)
        return int(session.scalar(statement) or 0)
    finally:
        session.close()


def _asset_filter_conditions(
    *,
    asset_type: str,
    workflow_id: str,
    date_from: str,
    date_to: str,
    collection_id: int | None = None,
    uncategorized: bool = False,
) -> list:
    # 2026-08-11: list_assets/assets_total이 이제 TaskOutputAsset을 기준으로
    # 조회하므로(위 참조) 여기 조건도 그 기준 테이블(및 조인된 Asset)을 대상으로
    # 건다 - 예전엔 Asset 단독 쿼리였다.
    conditions = []
    if asset_type:
        conditions.append(Asset.asset_type == asset_type)
    parsed_from = _parse_datetime(date_from) if date_from else None
    if parsed_from:
        conditions.append(Asset.created_at >= parsed_from)
    parsed_to = _parse_datetime(date_to) if date_to else None
    if parsed_to:
        conditions.append(Asset.created_at <= parsed_to)
    if workflow_id:
        conditions.append(
            TaskOutputAsset.task_id.in_(
                select(WorkflowTask.id).where(WorkflowTask.workflow_id == workflow_id)
            )
        )
    if collection_id:
        conditions.append(
            TaskOutputAsset.asset_id.in_(
                select(CollectionItem.asset_id).where(CollectionItem.collection_id == int(collection_id))
            )
        )
    if uncategorized:
        conditions.append(
            ~select(CollectionItem.asset_id).where(CollectionItem.asset_id == TaskOutputAsset.asset_id).exists()
        )
    return conditions


def delete_task_record(task_id: str) -> dict:
    session = SessionLocal()
    try:
        task = session.get(WorkflowTask, task_id)
        if not task:
            raise KeyError(task_id)
        session.delete(task)
        session.commit()
        return {"deleted": True, "taskId": task_id}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def restore_job_from_task(task_id: str) -> dict | None:
    session = SessionLocal()
    try:
        task = session.scalar(
            select(WorkflowTask)
            .options(
                selectinload(WorkflowTask.input_assets).selectinload(TaskInputAsset.asset),
                selectinload(WorkflowTask.output_assets).selectinload(TaskOutputAsset.asset),
            )
            .where(WorkflowTask.id == task_id)
            .limit(1)
        )
        if not task:
            return None
        history_item = _task_to_history_item(
            task,
            _assets_by_ids(session, _history_asset_ids([task])),
            _prompt_batch_ids_by_draft_id(session, [task]),
            _default_negative_prompts_by_workflow_id({str(task.workflow_id or "")}),
        )
        payload = dict(task.payload_json or {})
        segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
        first_segment = segments[0] if segments else {}
        first_config = first_segment.get("config") or task.config_json or {}
        output_assets = history_item.get("outputAssets") or []
        final_asset = next((asset for asset in output_assets if asset.get("outputRole") == "final"), None)
        output_url = (
            history_item.get("outputUrl")
            or (final_asset or output_assets[0]).get("downloadUrl")
            if output_assets
            else ""
        )
        created_at = seoul_naive_to_epoch(task.created_at) if task.created_at else seoul_naive_to_epoch(now_seoul_naive())
        result = {
            "taskId": task.id,
            "runpodJobId": task.runpod_job_id or "",
            "executionMode": task.execution_mode or "dry-run",
            "workflowId": task.workflow_id,
            "status": task.status,
            "progress": int(task.progress or 0),
            "createdAt": created_at,
            "startedAt": _format_datetime(task.started_at or task.created_at),
            "payload": payload,
            "firstConfig": first_config,
            "patchSummary": task.patch_summary or {},
            "generationSeed": history_item.get("generationSeed"),
            "runpodSubmit": task.runpod_submit_json or {},
            "runpodStatus": task.runpod_status_json or {},
            "inputAssets": history_item.get("inputAssets") or [],
            "outputAssets": output_assets,
            "outputUrl": output_url,
            "outputsSaved": bool(output_assets),
            "wanNodeConfig": task.wan_node_config or {},
            "historySaved": str(task.status or "").upper() in TERMINAL_STATES,
            "lastDispatchError": task.last_dispatch_error,
            "restoredFromDb": True,
        }
        created_at_fields = _task_timestamp_fields(task, "createdAt", task.created_at)
        # Keep the restored in-memory job invariant: createdAt is an epoch used
        # by JobService to calculate elapsed time and monitor progress.
        created_at_fields.pop("createdAt", None)
        result.update(created_at_fields)
        result.update(_task_timestamp_fields(task, "startedAt", task.started_at or task.created_at))
        result.update(_task_timestamp_fields(task, "completedAt", task.completed_at))
        return result
    finally:
        session.close()


def restore_existing_job_for_prompt_draft(prompt_draft_id: str, *, batch_job_id: str | None = None) -> dict | None:
    normalized_draft_id = str(prompt_draft_id or "").strip()
    if not normalized_draft_id:
        return None
    session = SessionLocal()
    try:
        task = session.scalar(
            select(WorkflowTask)
            .where(
                WorkflowTask.deleted_at.is_(None),
                WorkflowTask.prompt_draft_id == normalized_draft_id,
            )
            .order_by(WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
            .limit(1)
        )
        if task is None:
            return None
        task_id = task.id
        normalized_batch_job_id = str(batch_job_id or "").strip()
        if normalized_batch_job_id and not task.batch_job_id:
            payload = dict(task.payload_json or {})
            payload["batchJobId"] = normalized_batch_job_id
            task.payload_json = payload
            task.batch_job_id = normalized_batch_job_id
            task.updated_at = now_seoul_naive()
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return restore_job_from_task(task_id)


def _reset_task_for_rework(session: Session, task: WorkflowTask, *, actor_id: str, reset_created_at: bool = True) -> None:
    now = now_seoul_naive()
    payload = dict(task.payload_json or {})
    for key in ("regeneratedFromTaskId", "runpodJobId", "generationSeed"):
        payload.pop(key, None)
    if not isinstance(payload.get("user"), dict) or not payload["user"].get("id"):
        payload["user"] = {
            "id": task.user_id or actor_id,
            "name": task.worker_name or (task.user.name if task.user else None) or task.user_id or actor_id,
            "role": task.user.role if task.user else "",
            "permissions": task.user.permissions_json if task.user else [],
        }

    task.status = "PENDING_SUBMIT"
    task.progress = 0
    task.runpod_job_id = None
    task.completed_at = None
    task.elapsed_seconds = None
    task.runpod_submit_json = {}
    task.runpod_status_json = {}
    task.payload_json = payload
    task.wan_node_config = {}
    task.dispatch_claimed_at = None
    task.dispatch_attempts = 0
    task.next_dispatch_at = None
    task.last_dispatch_error = None
    task.started_at = now
    task.updated_at = now
    if reset_created_at:
        task.created_at = now
    for link in list(task.output_assets):
        session.delete(link)
    for prompt in list(task.prompts):
        prompt.output_asset_ids = []
        prompt.updated_at = now
    _sync_request_batch(session, task)


def requeue_task_for_rework(task_id: str, *, actor_id: str, can_manage: bool = False) -> dict:
    """Reset an existing terminal task so the dispatcher resubmits the same row."""
    session = SessionLocal()
    try:
        task = session.scalar(
            select(WorkflowTask)
            .options(
                selectinload(WorkflowTask.output_assets),
                selectinload(WorkflowTask.prompts),
                selectinload(WorkflowTask.user),
            )
            .where(WorkflowTask.id == task_id, WorkflowTask.deleted_at.is_(None))
            .limit(1)
        )
        if task is None:
            raise KeyError(task_id)
        if not can_manage and str(task.user_id or "") != str(actor_id or ""):
            raise PermissionError("다른 작업자의 RunPod 작업은 재작업할 수 없습니다.")
        status = str(task.status or "").upper()
        if status not in REPLAYABLE_STATES:
            raise ValueError("종료된 RunPod 작업만 재실행할 수 있습니다.")

        _reset_task_for_rework(session, task, actor_id=actor_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    restored = restore_job_from_task(task_id)
    if restored is None:
        raise KeyError(task_id)
    return restored


def requeue_runpod_history_items(
    session: Session,
    *,
    actor_id: str,
    can_manage: bool = False,
    scope: str = "selected",
    task_ids: list[str] | None = None,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    run_date: str = "",
    batch_job_id: str = "",
) -> dict:
    """Reset RunPod history rows using either explicit selection or current query filters."""
    normalized_scope = str(scope or "selected").strip().lower()
    skipped: list[dict[str, str]] = []
    selected_ids = [str(task_id).strip() for task_id in (task_ids or []) if str(task_id).strip()]

    if normalized_scope == "selected":
        if not selected_ids:
            raise ValueError("재실행할 RunPod 작업을 선택해주세요.")
        statement = (
            select(WorkflowTask)
            .options(
                selectinload(WorkflowTask.output_assets),
                selectinload(WorkflowTask.prompts),
                selectinload(WorkflowTask.user),
            )
            .where(
                WorkflowTask.id.in_(selected_ids),
                WorkflowTask.deleted_at.is_(None),
            )
        )
        if not can_manage:
            statement = statement.where(WorkflowTask.user_id == actor_id)
        tasks = list(session.scalars(statement))
        task_by_id = {task.id: task for task in tasks}
        ordered_tasks = []
        for task_id in selected_ids:
            task = task_by_id.get(task_id)
            if task is None:
                skipped.append({"id": task_id, "reason": "not_found_or_forbidden"})
                continue
            ordered_tasks.append(task)
    elif normalized_scope == "query":
        if not batch_job_id:
            raise ValueError("조회 조건 재실행에는 Batch ID가 필요합니다.")
        normalized_result = str(result_status or "").strip().upper()
        if normalized_result in {"COMPLETED", "SUCCESS", "ACTIVE", "RUNNING", "IN_PROGRESS"}:
            raise ValueError("조회 결과 재실행은 실패 또는 취소 RunPod 작업에만 사용할 수 있습니다.")
        effective_result = result_status if normalized_result in {"FAILED", "CANCELLED", "TIMED_OUT"} else ""
        conditions = _history_filter_conditions(
            workflow_id=workflow_id,
            result_status=effective_result,
            worker_id=worker_id,
            date_from=run_date,
            date_to=run_date,
            batch_job_id=batch_job_id,
        )
        if not effective_result:
            conditions.append(WorkflowTask.status.in_(REWORKABLE_STATES))
        if not can_manage:
            conditions.append(WorkflowTask.user_id == actor_id)
        ordered_tasks = list(session.scalars(
            select(WorkflowTask)
            .options(
                selectinload(WorkflowTask.output_assets),
                selectinload(WorkflowTask.prompts),
                selectinload(WorkflowTask.user),
            )
            .where(*conditions)
            .order_by(WorkflowTask.created_at.desc())
        ))
    else:
        raise ValueError("지원하지 않는 RunPod 재실행 범위입니다.")

    reworked_ids: list[str] = []
    for task in ordered_tasks:
        status = str(task.status or "").upper()
        if status not in REPLAYABLE_STATES:
            skipped.append({"id": task.id, "reason": "not_terminal"})
            continue
        _reset_task_for_rework(session, task, actor_id=actor_id)
        reworked_ids.append(task.id)

    session.commit()
    return {
        "scope": normalized_scope,
        "requested": len(selected_ids) if normalized_scope == "selected" else len(ordered_tasks),
        "reworked": len(reworked_ids),
        "taskIds": reworked_ids,
        "skipped": skipped,
    }


def active_task_ids() -> list[str]:
    """Return persisted non-terminal tasks for the server-side monitor."""
    session = SessionLocal()
    try:
        return list(
            session.scalars(
                select(WorkflowTask.id)
                .where(
                    WorkflowTask.deleted_at.is_(None),
                    func.upper(WorkflowTask.status).in_(ACTIVE_STATES),
                )
                .order_by(WorkflowTask.created_at.asc())
            )
        )
    finally:
        session.close()


def pending_output_import_task_ids() -> list[str]:
    """Return completed RunPod tasks whose manifest-backed output is absent.

    The status monitor owns this retry path, so a delayed RunPod S3 manifest
    is eventually imported even after every browser has left the page.
    """
    session = SessionLocal()
    try:
        missing_output = ~select(TaskOutputAsset.id).where(
            TaskOutputAsset.task_id == WorkflowTask.id,
        ).exists()
        return list(session.scalars(
            select(WorkflowTask.id)
            .where(
                WorkflowTask.deleted_at.is_(None),
                WorkflowTask.execution_mode == "runpod",
                WorkflowTask.runpod_job_id.is_not(None),
                WorkflowTask.status.in_({"COMPLETED", "SUCCESS"}),
                missing_output,
            )
            .order_by(WorkflowTask.updated_at.asc(), WorkflowTask.id.asc())
            .limit(20)
        ))
    finally:
        session.close()


def claim_next_pending_submission() -> dict | None:
    """Atomically claim the oldest retry-eligible local RunPod submission.

    The claim is persisted before the provider call so browser/session loss
    cannot make a queued task disappear. The conditional update keeps two app
    processes from submitting the same task twice.
    """
    session = SessionLocal()
    try:
        now = now_seoul_naive()
        _recover_stale_dispatching_submissions(session, now)
        candidate_ids = list(session.scalars(
            select(WorkflowTask.id)
            .where(
                WorkflowTask.deleted_at.is_(None),
                WorkflowTask.status == "PENDING_SUBMIT",
                or_(WorkflowTask.next_dispatch_at.is_(None), WorkflowTask.next_dispatch_at <= now),
            )
            .order_by(
                WorkflowTask.batch_job_id.is_not(None).asc(),
                WorkflowTask.created_at.asc(),
                WorkflowTask.id.asc(),
            )
            .limit(10)
        ))
        for task_id in candidate_ids:
            result = session.execute(
                update(WorkflowTask)
                .where(
                    WorkflowTask.id == task_id,
                    WorkflowTask.status == "PENDING_SUBMIT",
                    WorkflowTask.deleted_at.is_(None),
                )
                .values(
                    status="DISPATCHING",
                    dispatch_claimed_at=now,
                    dispatch_attempts=WorkflowTask.dispatch_attempts + 1,
                    next_dispatch_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount:
                task = session.get(WorkflowTask, task_id)
                if task is not None:
                    _sync_request_batch(session, task)
                session.commit()
                return {"taskId": task_id, "status": "DISPATCHING"}
        session.rollback()
        return None
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def recover_stale_dispatching_submissions() -> int:
    """Return abandoned RunPod submission claims to the durable queue."""
    session = SessionLocal()
    try:
        recovered = _recover_stale_dispatching_submissions(session, now_seoul_naive())
        session.commit()
        return recovered
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _recover_stale_dispatching_submissions(session: Session, now: datetime) -> int:
    cutoff = now - timedelta(seconds=STALE_DISPATCH_CLAIM_SECONDS)
    stale_tasks = session.scalars(
        select(WorkflowTask)
        .where(
            WorkflowTask.deleted_at.is_(None),
            WorkflowTask.status == "DISPATCHING",
            WorkflowTask.runpod_job_id.is_(None),
            WorkflowTask.dispatch_claimed_at.is_not(None),
            WorkflowTask.dispatch_claimed_at <= cutoff,
        )
        .order_by(WorkflowTask.dispatch_claimed_at.asc(), WorkflowTask.id.asc())
        .limit(10)
    ).all()
    for task in stale_tasks:
        task.status = "PENDING_SUBMIT"
        task.dispatch_claimed_at = None
        task.next_dispatch_at = None
        task.last_dispatch_error = "Recovered stale RunPod submission claim"
        task.updated_at = now
        _sync_request_batch(session, task)
    if stale_tasks:
        session.flush()
    return len(stale_tasks)


def release_pending_submission(task_id: str, error: str, *, retry_after_seconds: int = 15) -> None:
    """Return a claimed submission to the durable queue after a transient failure."""
    session = SessionLocal()
    try:
        now = now_seoul_naive()
        task = session.get(WorkflowTask, task_id)
        if not task:
            raise KeyError(task_id)
        if task.status != "DISPATCHING":
            return
        task.status = "PENDING_SUBMIT"
        task.dispatch_claimed_at = None
        task.next_dispatch_at = now + timedelta(seconds=max(1, int(retry_after_seconds)))
        task.last_dispatch_error = str(error or "RunPod submission deferred")[:4000]
        task.updated_at = now
        _sync_request_batch(session, task)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def task_prompts(task_id: str) -> list[dict]:
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(TaskPrompt)
            .where(TaskPrompt.task_id == task_id)
            .order_by(TaskPrompt.segment_index, TaskPrompt.id)
        ).all()
        assets_by_id = _assets_by_ids(session, _prompt_asset_ids(rows))
        feedback_by_output_id = _prompt_feedback_by_output_id(session, [row.prompt_generation_output_id for row in rows])
        return [_task_prompt_to_json(row, assets_by_id, feedback_by_output_id) for row in rows]
    finally:
        session.close()


def update_task_prompt_quality(task_id: str, segment_index: int, payload: dict) -> dict:
    session = SessionLocal()
    try:
        row = session.scalar(
            select(TaskPrompt)
            .where(TaskPrompt.task_id == task_id, TaskPrompt.segment_index == int(segment_index))
            .order_by(TaskPrompt.id)
            .limit(1)
        )
        if not row:
            raise KeyError(f"{task_id}:{segment_index}")
        rating = payload.get("qualityRating")
        row.quality_rating = None if rating in (None, "") else max(1, min(5, int(rating)))
        row.quality_comment = str(payload.get("qualityComment") or payload.get("comment") or "").strip() or None
        row.updated_at = now_seoul_naive()
        session.commit()
        feedback_by_output_id = _prompt_feedback_by_output_id(session, [row.prompt_generation_output_id])
        return _task_prompt_to_json(row, feedback_by_output_id=feedback_by_output_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_task_prompt_review(task_id: str, segment_index: int, payload: dict) -> dict:
    session = SessionLocal()
    try:
        row = session.scalar(
            select(TaskPrompt)
            .where(TaskPrompt.task_id == task_id, TaskPrompt.segment_index == int(segment_index))
            .order_by(TaskPrompt.id)
            .limit(1)
        )
        if not row:
            raise KeyError(f"{task_id}:{segment_index}")
        _apply_prompt_review(row, payload)
        session.commit()
        feedback_by_output_id = _prompt_feedback_by_output_id(session, [row.prompt_generation_output_id])
        return _task_prompt_to_json(row, _assets_by_ids(session, _prompt_asset_ids([row])), feedback_by_output_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reusable_task_prompts(
    *,
    keyword: str = "",
    workflow_id: str = "",
    min_rating: int | None = None,
    reviewed_only: bool = False,
    reuse_eligible: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    session = SessionLocal()
    try:
        query = select(TaskPrompt).options(
            # 2026-08-11: 4c 프롬프트 재사용 목록에 "생성자" 컬럼 추가 요청 -
            # task_prompts에는 생성자 정보가 없고 이 프롬프트를 만든 작업
            # (workflow_tasks.user_id → users.name)에만 있다. N+1 쿼리를 피하려고
            # _assets_by_id와 같은 방식으로 selectinload로 미리 조인해온다.
            selectinload(TaskPrompt.task).selectinload(WorkflowTask.user)
        ).order_by(
            # MySQL does not support the `NULLS LAST` clause emitted by
            # SQLAlchemy's nullslast(). Sorting the null marker first works
            # consistently on both SQLite and MySQL.
            TaskPrompt.quality_rating.is_(None).asc(),
            TaskPrompt.quality_rating.desc(),
            TaskPrompt.updated_at.desc(),
            TaskPrompt.id.desc(),
        )
        if workflow_id:
            workflow_text = str(workflow_id)
            workflow_candidates = {workflow_text}
            if workflow_text.endswith(".json"):
                workflow_candidates.add(workflow_text[:-5])
            else:
                workflow_candidates.add(f"{workflow_text}.json")
            query = query.where(TaskPrompt.workflow_id.in_(sorted(workflow_candidates)))
        if min_rating is not None:
            query = query.where(TaskPrompt.quality_rating >= int(min_rating))
        if reviewed_only:
            query = query.where(TaskPrompt.review_status == "reviewed")
        if reuse_eligible is not None:
            query = query.where(TaskPrompt.reuse_eligible.is_(bool(reuse_eligible)))
        # B-05: soft delete된 작업에 속한 프롬프트는 재사용 목록에서 제외한다
        # (3a 삭제 안내 "이 작업의 프롬프트 평가와 재사용 등록도 함께 사라집니다").
        # task_id가 없는 프롬프트(작업 미연결)는 NOT EXISTS라 그대로 남는다.
        query = query.where(
            ~select(WorkflowTask.id)
            .where(WorkflowTask.id == TaskPrompt.task_id, WorkflowTask.deleted_at.is_not(None))
            .exists()
        )
        # 프롬프트 재사용 목록 페이지네이션(2026-08-11): 키워드는 asset 파일명·
        # 평가 코멘트 등 JSON으로 합성된 필드까지 검색해야 해서
        # (`_reusable_prompt_matches_keyword`) SQL WHERE로 옮길 수 없다. 그래서
        # SQL 단계에서는 workflow/rating/reviewed/reuse_eligible 필터만 적용한
        # 전체 후보를 가져온 뒤, 파이썬에서 키워드 필터 + total 계산 + 페이지
        # 슬라이스를 적용한다. 이전 버전은 키워드가 있으면 무조건 200건까지만
        # 조회해 필터링한 뒤 그중 앞 `limit`개만 반환했는데, 조건에 맞는 결과가
        # 200건 뒤쪽에 있으면 조용히 누락되는 버그였다 - 이 화면은 reuse_eligible로
        # 걸러진 소량의 큐레이션된 데이터만 다루므로 전체 후보를 메모리에 올리는
        # 비용이 감내할 만하다고 판단했다.
        rows = session.scalars(query).all()
        assets_by_id = _assets_by_ids(session, _prompt_asset_ids(rows))
        feedback_by_output_id = _prompt_feedback_by_output_id(session, [row.prompt_generation_output_id for row in rows])
        items = [_task_prompt_to_json(row, assets_by_id, feedback_by_output_id) for row in rows]
        cleaned_keyword = str(keyword or "").strip()
        if cleaned_keyword:
            items = [item for item in items if _reusable_prompt_matches_keyword(item, cleaned_keyword)]
        total = len(items)
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(200, int(page_size or 20)))
        start = (safe_page - 1) * safe_page_size
        page_items = items[start:start + safe_page_size]
        return {"items": page_items, "page": safe_page, "pageSize": safe_page_size, "total": total}
    finally:
        session.close()


def _with_session(callback: Callable[[Session], None]) -> None:
    session = SessionLocal()
    try:
        callback(session)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


def _record_job_created(session: Session, job: dict, *, resolve_asset: Callable[[str], tuple[dict, Path]] | None) -> None:
    payload = job.get("payload") or {}
    task = _upsert_task(session, job)
    _replace_input_assets(session, task, job, resolve_asset=resolve_asset)
    _replace_task_prompts(session, task, job)
    _sync_request_batch(session, task)


def _record_job_status(session: Session, job: dict, *, resolve_asset: Callable[[str], tuple[dict, Path]] | None) -> None:
    task = _upsert_task(session, job)
    _replace_input_assets(session, task, job, resolve_asset=resolve_asset)
    if not task.prompts:
        _replace_task_prompts(session, task, job)
    _replace_output_assets(session, task, job, resolve_asset=resolve_asset)
    _sync_task_prompt_outputs(session, task, job)
    _sync_request_batch(session, task)


def _sync_request_batch(session: Session, task: WorkflowTask) -> None:
    """Keep the request aggregate derived from the durable task state."""
    if not task.request_item_id:
        return
    # Local import keeps task tracking independent from request-batch creation
    # and avoids a module cycle during application startup.
    from backend.app.services.runpod_request_batch_service import sync_request_batch_for_task

    sync_request_batch_for_task(session, task)


# RunPod은 완료된 결과물을 provider 응답 안에 base64로 그대로 실어 보낸다
# (output.images[*].data). output_service.save_runpod_outputs()가 이미 그 바이트를
# 디코딩해 asset 저장소에 파일로 기록하므로, 같은 값을 DB 컬럼에도 남기면 완전한
# 중복본이 된다. 그 중복본은 응답에 실리지도 않으면서 - 이 컬럼에서 실제로 쓰는
# 값은 _runpod_response_summary()의 filename/executionTime/delayTime/jobId 네
# 개뿐이다 - 모든 task 조회가 행당 최대 1.6MB를 메모리로 끌어오게 만들었다.
# 프롬프트 이력 화면처럼 영상을 보여주지도 않는 화면이 느려지고 ECS에서 메모리가
# 부족해진 근본 원인이므로, 영속화 직전에 본문만 잘라내고 봉투(상태·ID·타이밍·
# 파일명)는 그대로 남긴다.
PROVIDER_PAYLOAD_MAX_STRING = 4096


def prune_provider_payload(value, *, max_string_length: int = PROVIDER_PAYLOAD_MAX_STRING):
    """Strip provider result bytes, keeping the response envelope intact.

    Only oversized strings are removed, so a provider schema change cannot
    smuggle a new base64 field back into the column. Each stripped value keeps
    its original length as ``<key>Bytes`` so operators can still tell how large
    the discarded body was.
    """
    if isinstance(value, dict):
        pruned: dict = {}
        for key, item in value.items():
            if isinstance(item, str) and len(item) > max_string_length:
                pruned[key] = ""
                pruned[f"{key}Bytes"] = len(item)
                pruned[f"{key}Stripped"] = True
                continue
            pruned[key] = prune_provider_payload(item, max_string_length=max_string_length)
        return pruned
    if isinstance(value, list):
        return [prune_provider_payload(item, max_string_length=max_string_length) for item in value]
    if isinstance(value, str) and len(value) > max_string_length:
        return ""
    return value


def _payload_without_seed(payload: dict) -> dict:
    sanitized = dict(payload)
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return sanitized
    sanitized_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            sanitized_segments.append(segment)
            continue
        sanitized_segment = dict(segment)
        config = segment.get("config")
        if isinstance(config, dict):
            sanitized_segment["config"] = {
                key: value for key, value in config.items() if str(key).lower() != "seed"
            }
        sanitized_segments.append(sanitized_segment)
    sanitized["segments"] = sanitized_segments
    return sanitized


def _upsert_task(session: Session, job: dict) -> WorkflowTask:
    payload = job.get("payload") or {}
    user_payload = payload.get("user") or {}
    user = _ensure_user(session, user_payload)
    task_id = str(job.get("taskId") or "").strip()
    if not task_id:
        raise ValueError("job.taskId is required")

    task = session.get(WorkflowTask, task_id)
    now = now_seoul_naive()
    if not task:
        task = WorkflowTask(id=task_id, created_at=_from_epoch(job.get("createdAt")) or now, updated_at=now)
        session.add(task)

    segments = payload.get("segments") or []
    first_segment = segments[0] if segments else {}
    raw_first_config = first_segment.get("config") or job.get("firstConfig") or {}
    first_config = {
        key: value
        for key, value in raw_first_config.items()
        if str(key).lower() != "seed"
    }
    stored_payload = _payload_without_seed(payload)
    if job.get("generationSeed") is not None:
        stored_payload["generationSeed"] = job.get("generationSeed")
    status = str(job.get("status") or "queued")
    completed_at = now if status.upper() in TERMINAL_STATES else task.completed_at

    task.runpod_job_id = job.get("runpodJobId") or None
    task.workflow_id = job.get("workflowId") or payload.get("workflowId") or "unknown"
    task.execution_mode = job.get("executionMode") or "dry-run"
    task.status = status
    task.progress = int(job.get("progress") or 0)
    task.worker_name = user_payload.get("name") or user_payload.get("id") or task.worker_name
    task.user_id = user.id if user else task.user_id
    task.started_at = _parse_datetime(job.get("startedAt")) or task.started_at
    task.completed_at = completed_at
    task.elapsed_seconds = _elapsed_seconds(job)
    task.positive_prompts = [
        {"index": segment.get("index") or index + 1, "text": segment.get("positivePrompt", "")}
        for index, segment in enumerate(segments)
    ]
    task.negative_prompts = [
        {"index": segment.get("index") or index + 1, "text": segment.get("negativePromptAddition", "") or segment.get("negativePrompt", "")}
        for index, segment in enumerate(segments)
    ]
    task.config_json = first_config
    task.wan_node_config = job.get("wanNodeConfig") or {}
    task.patch_summary = job.get("patchSummary") or {}
    task.payload_json = stored_payload
    task.runpod_submit_json = prune_provider_payload(job.get("runpodSubmit") or {})
    task.runpod_status_json = prune_provider_payload(job.get("runpodStatus") or {})
    # Queue jobs retain their immutable request references in payload.  The
    # persistence record must copy them into indexed columns as well; otherwise
    # a RunPod request batch cannot observe the task after navigation/restart.
    task.prompt_draft_id = str(job.get("promptDraftId") or payload.get("promptDraftId") or task.prompt_draft_id or "") or None
    task.request_batch_id = str(job.get("requestBatchId") or payload.get("requestBatchId") or task.request_batch_id or "") or None
    task.request_item_id = str(job.get("requestItemId") or payload.get("requestItemId") or task.request_item_id or "") or None
    task.batch_job_id = str(job.get("batchJobId") or payload.get("batchJobId") or task.batch_job_id or "") or None
    if status.upper() in ACTIVE_STATES or status.upper() in TERMINAL_STATES:
        task.dispatch_claimed_at = None
        task.next_dispatch_at = None
        task.last_dispatch_error = None
    task.time_context_json = _time_context(task, job, now)
    task.updated_at = now
    session.flush()
    return task


def _replace_input_assets(
    session: Session,
    task: WorkflowTask,
    job: dict,
    *,
    resolve_asset: Callable[[str], tuple[dict, Path]] | None,
) -> None:
    for link in list(task.input_assets):
        session.delete(link)
    session.flush()
    seen_asset_ids: set[str] = set()
    unique_asset_ids: list[str] = []
    for asset_id in _input_asset_ids(job):
        if asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        unique_asset_ids.append(asset_id)
    for index, asset_id in enumerate(unique_asset_ids, start=1):
        _ensure_asset(session, asset_id, resolve_asset=resolve_asset)
        if session.get(Asset, asset_id):
            session.add(TaskInputAsset(task_id=task.id, asset_id=asset_id, slot_index=index))


def _replace_output_assets(
    session: Session,
    task: WorkflowTask,
    job: dict,
    *,
    resolve_asset: Callable[[str], tuple[dict, Path]] | None,
) -> None:
    for link in list(task.output_assets):
        session.delete(link)
    session.flush()
    seen_asset_ids: set[str] = set()
    for asset in job.get("outputAssets") or []:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("assetId") or "").strip()
        if not asset_id:
            continue
        if asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        _ensure_asset(session, asset_id, asset_payload=asset, resolve_asset=resolve_asset)
        if session.get(Asset, asset_id):
            session.add(TaskOutputAsset(
                task_id=task.id,
                asset_id=asset_id,
                output_role=asset.get("outputRole") or "final",
                segment_index=_to_int(asset.get("segmentIndex")),
            ))


def _replace_task_prompts(session: Session, task: WorkflowTask, job: dict) -> None:
    for row in list(task.prompts):
        session.delete(row)
    session.flush()

    payload = job.get("payload") or {}
    workflow_id = task.workflow_id
    input_asset_ids = _input_asset_ids(job)
    for index, segment in enumerate(payload.get("segments") or [], start=1):
        segment_index = int(segment.get("index") or index)
        config = segment.get("config") or {}
        session.add(TaskPrompt(
            task_id=task.id,
            workflow_id=workflow_id,
            segment_index=segment_index,
            model_name=_segment_model_name(segment, config),
            prompt_generation_output_id=_prompt_generation_output_id(segment),
            positive_prompt=str(segment.get("positivePrompt") or ""),
            negative_prompt=str(segment.get("negativePromptAddition") or segment.get("negativePrompt") or ""),
            input_asset_ids=input_asset_ids,
            output_asset_ids=[],
            quality_rating=None,
            quality_comment=None,
            reuse_count=0,
            metadata_json={
                "segment": segment,
                "config": config,
                "workflowId": workflow_id,
                "runpodJobId": job.get("runpodJobId"),
                "promptSource": segment.get("promptSource") or segment.get("source") or "",
                # B-08: 신규 Task는 RunPod 제출 직전의 워크플로우를 기준으로
                # 선택 모델 값을 보관한다. 나중에 workflow JSON이 바뀌어도 이
                # 작업의 Checkpoint/VAE/LoRA/CLIP/UNet 조회값은 변하지 않는다.
                "modelReferences": (job.get("patchSummary") or {}).get("modelReferences") or [],
                "modelReferenceSource": "submission_snapshot",
            },
        ))


def _sync_task_prompt_outputs(session: Session, task: WorkflowTask, job: dict) -> None:
    output_assets = [asset for asset in job.get("outputAssets") or [] if isinstance(asset, dict)]
    final_ids = [asset.get("assetId") for asset in output_assets if asset.get("outputRole") == "final" and asset.get("assetId")]
    prompts = session.scalars(select(TaskPrompt).where(TaskPrompt.task_id == task.id)).all()
    for prompt in prompts:
        segment_ids = [
            asset.get("assetId")
            for asset in output_assets
            if asset.get("outputRole") == "segment"
            and _to_int(asset.get("segmentIndex")) == prompt.segment_index
            and asset.get("assetId")
        ]
        prompt.output_asset_ids = segment_ids or final_ids
        prompt.updated_at = now_seoul_naive()


def _ensure_user(session: Session, user_payload: dict) -> User | None:
    user_id = str(user_payload.get("id") or user_payload.get("email") or "").strip()
    if not user_id:
        return None
    user = session.get(User, user_id)
    is_new_user = user is None
    if not user:
        user = User(id=user_id, created_at=now_seoul_naive(), updated_at=now_seoul_naive())
        session.add(user)
    user.name = user_payload.get("name") or user_id
    user.email = user_payload.get("email")
    # 2026-08-11 버그 수정: `or user.role` fallback은 payload에 role이 아예 없을 때만
    # 보호해줄 뿐, Job 제출 시점의 stale-하지만-존재하는 role 값은 그대로 덮어써서
    # db_adapter.py와 같은 승격-취소 버그를 일으켰다. role/permissions는
    # admin_service.upsert_admin_user()(관리자 역할 변경 API)에서만 바뀌어야
    # 하므로, 신규 사용자 최초 생성 시에만 반영한다.
    if is_new_user:
        user.role = user_payload.get("role") or "OPERATOR"
        user.permissions_json = user_payload.get("permissions") or []
    user.updated_at = now_seoul_naive()
    return user


def _ensure_asset(
    session: Session,
    asset_id: str,
    *,
    asset_payload: dict | None = None,
    resolve_asset: Callable[[str], tuple[dict, Path]] | None,
) -> Asset | None:
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        return None
    payload = dict(asset_payload or {})
    if resolve_asset and not payload.get("path"):
        try:
            resolved, path = resolve_asset(asset_id)
            payload = {**resolved, "path": str(path), **payload}
        except (KeyError, FileNotFoundError):
            pass
    if not payload:
        return session.get(Asset, asset_id)

    asset = session.get(Asset, asset_id)
    if not asset:
        asset = Asset(id=asset_id)
        session.add(asset)
    file_name = payload.get("fileName") or payload.get("filename") or Path(payload.get("path") or asset_id).name
    asset.asset_type = payload.get("type") or payload.get("assetType") or payload.get("kind") or "asset"
    asset.file_name = file_name
    asset.mime_type = payload.get("mimeType") or "application/octet-stream"
    asset.size_bytes = int(payload.get("sizeBytes") or 0)
    asset.storage_backend = payload.get("storageBackend") or "local"
    asset.storage_key = payload.get("path") or payload.get("storageKey") or asset.storage_key or ""
    asset.public_url = payload.get("publicUrl")
    asset_metadata = {
        key: value
        for key, value in payload.items()
        if key not in {
            "assetId", "id", "type", "assetType", "fileName", "filename", "mimeType", "sizeBytes",
            "path", "storageKey", "storageBackend", "publicUrl", "createdAt", "createdAtUtc",
            "createdAtKst", "createdAtSourceTimezone", "createdAtSource",
        }
    }
    asset_time = {
        "utc": payload.get("createdAtUtc"),
        "kst": payload.get("createdAtKst") or payload.get("createdAt"),
        "sourceTimezone": payload.get("createdAtSourceTimezone"),
        "source": payload.get("createdAtSource"),
    }
    if any(asset_time.values()):
        asset_metadata["timeContext"] = {"createdAt": asset_time}
    asset.metadata_json = asset_metadata
    asset.created_at = _asset_created_at(payload) or asset.created_at or now_seoul_naive()
    return asset


def _input_asset_ids(job: dict) -> list[str]:
    payload = job.get("payload") or {}
    result = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)

    for asset_id in job.get("inputAssets") or []:
        add(asset_id)
    for keyframe in payload.get("keyframes") or []:
        if isinstance(keyframe, dict):
            add(keyframe.get("uploadId"))
    return result


def _segment_model_name(segment: dict, config: dict) -> str | None:
    for key in ("modelName", "model", "checkpoint", "diffusionModel", "vae", "lora"):
        value = segment.get(key) or config.get(key)
        if value:
            return str(value)
    return None


def _prompt_generation_output_id(segment: dict) -> str | None:
    for key in ("promptGenerationOutputId", "promptOutputId", "generatedPromptOutputId"):
        value = segment.get(key)
        if value:
            return str(value)
    generated_prompt = segment.get("generatedPrompt") if isinstance(segment.get("generatedPrompt"), dict) else {}
    value = generated_prompt.get("outputId")
    return str(value) if value else None


def _elapsed_seconds(job: dict) -> int | None:
    if job.get("createdAt") is None:
        return None
    try:
        return max(0, int(seoul_naive_to_epoch(now_seoul_naive()) - float(job["createdAt"])))
    except (TypeError, ValueError):
        return None


def _from_epoch(value: Any) -> datetime | None:
    try:
        return epoch_to_seoul_naive(float(value))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    parsed = parse_timestamp(value, naive_timezone=SEOUL_TIMEZONE)
    return parsed.astimezone(SEOUL_TIMEZONE).replace(tzinfo=None) if parsed else None


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _prompt_batch_ids_by_draft_id(session: Session, tasks: list[WorkflowTask]) -> dict[str, str]:
    draft_ids = sorted({
        str(task.prompt_draft_id)
        for task in tasks
        if task.prompt_draft_id
    })
    if not draft_ids:
        return {}
    return {
        str(draft_id): str(prompt_batch_id)
        for draft_id, prompt_batch_id in session.execute(
            select(ImagePromptDraft.id, ImagePromptDraft.prompt_batch_id)
            .where(
                ImagePromptDraft.id.in_(draft_ids),
                ImagePromptDraft.prompt_batch_id.is_not(None),
            )
        ).all()
        if prompt_batch_id
    }


def _default_negative_prompts_by_workflow_id(workflow_ids: set[str]) -> dict[str, list[dict[str, str | int]]]:
    defaults: dict[str, list[dict[str, str | int]]] = {}
    for workflow_id in sorted(workflow_id for workflow_id in workflow_ids if workflow_id):
        try:
            schema = workflow_service.get_workflow_schema(workflow_id)
        except Exception:
            defaults[workflow_id] = []
            continue
        defaults[workflow_id] = [
            {"index": int(segment.get("index") or index + 1), "text": text}
            for index, segment in enumerate(schema.get("segments") or [])
            for text in [str(segment.get("defaultNegativePrompt") or "").strip()]
            if text
        ]
    return defaults


def _history_item_has_negative_prompt(item: dict) -> bool:
    if str(item.get("negativePrompt") or "").strip():
        return True
    for entry in item.get("negativePrompts") or []:
        if isinstance(entry, dict) and str(entry.get("text") or entry.get("negativePrompt") or "").strip():
            return True
        if isinstance(entry, str) and entry.strip():
            return True
    for segment in item.get("segments") or []:
        if isinstance(segment, dict) and str(segment.get("negativePromptAddition") or segment.get("negativePrompt") or "").strip():
            return True
    return False


def _task_to_history_item(
    task: WorkflowTask,
    assets_by_id: dict[str, dict],
    prompt_batch_ids_by_draft_id: dict[str, str] | None = None,
    default_negative_prompts_by_workflow_id: dict[str, list[dict[str, str | int]]] | None = None,
) -> dict:
    item = dict(task.payload_json or {})
    item.setdefault("taskId", task.id)
    item.update(_task_timestamp_fields(task, "timestamp", task.started_at or task.created_at))
    item.setdefault("workflowId", task.workflow_id)
    # Older tasks predate the explicit display name. Keep their history readable
    # without rewriting stored payloads or requiring a data migration.
    item.setdefault("workflowName", Path(task.workflow_id).stem)
    item.setdefault("promptDraftId", task.prompt_draft_id or "")
    item["batchJobId"] = task.batch_job_id
    prompt_batch_id = prompt_batch_ids_by_draft_id.get(str(task.prompt_draft_id or "")) if prompt_batch_ids_by_draft_id else None
    item.setdefault("promptBatchId", prompt_batch_id)
    item.setdefault("runpodJobId", task.runpod_job_id or "")
    item.setdefault("executionMode", task.execution_mode)
    item.setdefault("workerName", task.worker_name or "-")
    item["status"] = _history_status_label(task.status)
    item.setdefault("progress", int(task.progress or 0))
    item.setdefault("positivePrompts", task.positive_prompts or [])
    item.setdefault("negativePrompts", task.negative_prompts or [])
    default_negative_prompts = (
        default_negative_prompts_by_workflow_id or {}
    ).get(str(task.workflow_id or ""), [])
    if default_negative_prompts and not _history_item_has_negative_prompt(item):
        item["negativePrompts"] = default_negative_prompts
        item["negativePrompt"] = " | ".join(
            f"{entry['index']}: {entry['text']}"
            for entry in default_negative_prompts
        )
    item.setdefault("configJson", task.config_json or {})
    item.setdefault("durationSeconds", _history_duration_seconds(task, item))
    item.setdefault("wanNodeConfig", task.wan_node_config or {})
    item.setdefault("patchSummary", task.patch_summary or {})
    # Keeps application and provider time origins inspectable in Task History.
    item["timeContext"] = task.time_context_json or {
        "contractVersion": 0,
        "legacy": True,
        "message": "Stored timezone is unknown for this legacy task.",
    }
    item.setdefault(
        "generationSeed",
        ((task.patch_summary or {}).get("seed") or {}).get("value"),
    )
    input_links = sorted(task.input_assets, key=lambda link: link.slot_index)
    item["inputAssets"] = [link.asset_id for link in input_links]
    item["inputImages"] = item.get("inputImages") or hydrate_input_images(item, assets_by_id)
    output_assets = []
    for link in sorted(task.output_assets, key=lambda link: (link.segment_index or 0, link.id or 0)):
        asset = assets_by_id.get(link.asset_id)
        if not asset:
            continue
        output_assets.append(hydrate_output_asset(
            {
                **asset,
                "outputRole": link.output_role,
                "segmentIndex": link.segment_index,
            },
            assets_by_id,
        ))
    item["outputAssets"] = output_assets or item.get("outputAssets", [])
    item.setdefault("outputUrl", _first_output_url(item["outputAssets"]))
    item["runpodResponse"] = _runpod_response_summary(task, item["outputAssets"])
    requested_generation = (task.patch_summary or {}).get("generation") if isinstance(task.patch_summary, dict) else None
    item["requestedGeneration"] = requested_generation if isinstance(requested_generation, list) else []
    item["runpodGeneration"] = _runpod_generation(task.runpod_status_json or {})
    if item["runpodGeneration"]:
        item["runpodResponse"]["generation"] = item["runpodGeneration"]
    item.update(_task_timestamp_fields(task, "completedAt", task.completed_at))
    item.setdefault("elapsedSeconds", task.elapsed_seconds)
    return item


def _history_duration_seconds(task: WorkflowTask, item: dict) -> int | None:
    for source in _history_duration_sources(task, item):
        seconds = _positive_int(
            source.get("durationSeconds")
            or source.get("duration_seconds")
            or source.get("duration")
        )
        if seconds is not None:
            return seconds
        frames = _positive_int(source.get("frames") or source.get("length") or source.get("frame_count"))
        if frames is None:
            continue
        fps = _positive_int(source.get("outputFps") or source.get("output_fps") or source.get("fps")) or 16
        return max(1, round(frames / fps))
    return None


def _history_duration_sources(task: WorkflowTask, item: dict) -> list[dict]:
    sources: list[dict] = []
    for source in (item.get("configJson"), item.get("config"), task.config_json):
        if isinstance(source, dict):
            sources.append(source)
    payload = task.payload_json or {}
    if isinstance(payload, dict):
        for segment in payload.get("segments") or []:
            config = segment.get("config") if isinstance(segment, dict) else None
            if isinstance(config, dict):
                sources.append(config)
    patch_summary = task.patch_summary or {}
    if isinstance(patch_summary, dict):
        for setting in patch_summary.get("videoSettings") or []:
            if isinstance(setting, dict):
                sources.append(setting)
    return sources


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _runpod_response_summary(task: WorkflowTask, output_assets: list[dict]) -> dict:
    """Normalize provider timing/output fields without changing raw RunPod storage."""
    provider_payload = task.runpod_status_json or {}
    submit_payload = task.runpod_submit_json or {}
    filename = (
        _find_provider_value(provider_payload, ("filename", "fileName"))
        or _find_provider_value(submit_payload, ("filename", "fileName"))
        or _first_output_filename(output_assets)
    )
    summary = {
        "filename": filename or None,
        "delaySeconds": _find_provider_value(submit_payload, ("delayTime", "delay_time", "delaySeconds")),
        "executionSeconds": _find_provider_value(provider_payload, ("executionTime", "execution_time", "executionSeconds")),
        "jobId": task.runpod_job_id or _find_provider_value(submit_payload, ("id", "jobId", "job_id")) or None,
    }
    generation = _runpod_generation(provider_payload)
    if generation:
        summary["generation"] = generation
    return summary


def _runpod_generation(provider_payload: dict) -> list:
    if not isinstance(provider_payload, dict):
        return []
    candidates = [
        provider_payload.get("generation"),
        (provider_payload.get("output") or {}).get("generation") if isinstance(provider_payload.get("output"), dict) else None,
        (provider_payload.get("manifest") or {}).get("generation") if isinstance(provider_payload.get("manifest"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []


def _find_provider_value(payload: object, keys: tuple[str, ...]) -> object | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for value in payload.values():
            found = _find_provider_value(value, keys)
            if found not in (None, ""):
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _find_provider_value(value, keys)
            if found not in (None, ""):
                return found
    return None


def _first_output_filename(output_assets: list[dict]) -> str | None:
    final = next((asset for asset in output_assets if asset.get("outputRole") == "final"), None)
    asset = final or (output_assets[0] if output_assets else None)
    return str(asset.get("fileName")) if isinstance(asset, dict) and asset.get("fileName") else None


def _assets_by_ids(session: Session, asset_ids: set[str] | list[str]) -> dict[str, dict]:
    """지정된 자산만 JSON으로 변환한다.

    자산 관리 화면은 페이지 단위로 출력 자산과 연결된 입력 이미지만 필요하다. 전체
    asset 테이블을 읽는 헬퍼는 이력 복원처럼 전체 참조가 필요한 기존 경로에만 남긴다.
    """
    ids = sorted({str(asset_id) for asset_id in asset_ids if asset_id})
    if not ids:
        return {}
    return {
        asset.id: _asset_to_json(asset)
        for asset in session.scalars(select(Asset).where(Asset.id.in_(ids))).all()
    }


def _history_asset_ids(tasks: list[WorkflowTask]) -> set[str]:
    """이력 항목 조립에 실제로 필요한 자산 ID만 모은다.

    입력/출력 링크 외에 payload의 keyframe uploadId도 포함한다 -
    hydrate_input_images()가 링크에 없는 업로드 ID로도 자산을 찾기 때문이다.
    """
    asset_ids: set[str] = set()
    for task in tasks:
        asset_ids.update(link.asset_id for link in task.input_assets if link.asset_id)
        asset_ids.update(link.asset_id for link in task.output_assets if link.asset_id)
        payload = task.payload_json if isinstance(task.payload_json, dict) else {}
        for keyframe in payload.get("keyframes") or []:
            if isinstance(keyframe, dict) and keyframe.get("uploadId"):
                asset_ids.add(str(keyframe["uploadId"]))
    return asset_ids


def _prompt_asset_ids(rows) -> set[str]:
    """task_prompts 행들이 참조하는 입력/출력 자산 ID만 모은다."""
    asset_ids: set[str] = set()
    for row in rows:
        for asset_id in (row.input_asset_ids or []):
            if asset_id:
                asset_ids.add(str(asset_id))
        for asset_id in (row.output_asset_ids or []):
            if asset_id:
                asset_ids.add(str(asset_id))
    return asset_ids


def _prompt_feedback_by_output_id(session: Session, output_ids: list[str | None]) -> dict[str, PromptFeedback]:
    """B-02: `prompt_feedback`("프롬프트 생성 품질" 평가, `task_prompts.quality_rating`
    ("영상 결과 평가")과는 역할이 분리된 별도 저장소)에서 이 배치의 `prompt_generation_output_id`들에
    연결된 기존 평가를 한 번에 읽어온다 - `_assets_by_ids`와 동일하게 N+1 쿼리를 피하기 위한
    배치 조회. 같은 output에 대해 평가가 여러 번 저장될 수 있어(재평가), created_at 오름차순으로
    가져와 나중 값으로 덮어써 가장 최신 평가만 남긴다."""
    cleaned_ids = sorted({output_id for output_id in output_ids if output_id})
    if not cleaned_ids:
        return {}
    rows = session.scalars(
        select(PromptFeedback)
        .where(PromptFeedback.output_id.in_(cleaned_ids))
        .order_by(PromptFeedback.created_at.asc(), PromptFeedback.id.asc())
    ).all()
    return {row.output_id: row for row in rows}


def _prompt_feedback_to_json(feedback: PromptFeedback | None) -> dict | None:
    if not feedback:
        return None
    result = {
        "id": feedback.id,
        "rating": feedback.rating,
        "notes": feedback.notes,
        "editedPositivePrompt": feedback.edited_positive_prompt,
        "editedNegativePrompt": feedback.edited_negative_prompt,
        **timestamp_fields("createdAt", feedback.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
    }
    return result


def _asset_to_json(asset: Asset) -> dict:
    item = dict(asset.metadata_json or {})
    time_context = item.pop("timeContext", {})
    created_context = time_context.get("createdAt") if isinstance(time_context, dict) else None
    if isinstance(created_context, dict) and created_context.get("utc") and created_context.get("kst"):
        created_at_fields = {
            "createdAt": created_context.get("kst") or created_context.get("utc"),
            "createdAtUtc": created_context.get("utc"),
            "createdAtKst": created_context.get("kst"),
            "createdAtSourceTimezone": created_context.get("sourceTimezone") or "UTC",
            "createdAtSource": created_context.get("source") or "asset-storage",
        }
    else:
        # Before the timestamp contract, uploads were created by the local
        # application clock (KST), while RunPod output assets were persisted by
        # the UTC storage path. Keep the DB value untouched, but make the
        # historical source assumption visible in the API response.
        is_input = str(asset.asset_type or "").lower().startswith("input")
        naive_timezone = SEOUL_TIMEZONE if is_input else UTC_TIMEZONE
        source_timezone = "Asia/Seoul" if is_input else "UTC"
        created_at_fields = timestamp_fields(
            "createdAt",
            asset.created_at,
            naive_timezone=naive_timezone,
            source_timezone=source_timezone,
            source="legacy-input-asset" if is_input else "legacy-output-asset",
        )
    item.update({
        "assetId": asset.id,
        "type": asset.asset_type,
        "fileName": asset.file_name,
        "mimeType": asset.mime_type,
        "sizeBytes": asset.size_bytes,
        "imageWidth": asset.image_width,
        "imageHeight": asset.image_height,
        "path": asset.storage_key,
        "storageBackend": asset.storage_backend,
        "publicUrl": asset.public_url,
        **created_at_fields,
    })
    item.setdefault("downloadUrl", f"/api/files/{asset.id}")
    return item


def _first_output_url(output_assets: list[dict]) -> str:
    if not output_assets:
        return ""
    final_asset = next((asset for asset in output_assets if asset.get("outputRole") == "final"), None)
    return (final_asset or output_assets[0]).get("downloadUrl") or ""


def _history_status_label(status: Any) -> str:
    text = str(status or "").upper()
    if text in {"COMPLETED", "SUCCESS"}:
        return "Completed"
    if text == "CANCELLED":
        return "Cancelled"
    if text == "TIMED_OUT":
        return "Timed Out"
    if text == "FAILED":
        return "Failed"
    return status or "queued"


def _format_datetime(value: datetime | None) -> str:
    return format_seoul_datetime(value)


def _task_prompt_to_json(
    row: TaskPrompt,
    assets_by_id: dict[str, dict] | None = None,
    feedback_by_output_id: dict[str, PromptFeedback] | None = None,
) -> dict:
    input_ids = row.input_asset_ids or []
    output_ids = row.output_asset_ids or []
    task_user = row.task.user if row.task else None
    created_by = (task_user.name if task_user else None) or (row.task.user_id if row.task else None)
    model_references, model_reference_source = _task_model_references(row)
    result = {
        "id": row.id,
        "taskId": row.task_id,
        "workflowId": row.workflow_id,
        "segmentIndex": row.segment_index,
        "createdBy": created_by,
        "modelProfileId": row.model_profile_id,
        "modelName": row.model_name,
        "modelReferences": model_references,
        "modelReferenceSource": model_reference_source,
        "promptGenerationOutputId": row.prompt_generation_output_id,
        # B-02: task_prompts의 quality_rating/reviewFlags 등은 "영상 결과 평가"
        # 전용이다. "프롬프트 생성 품질" 평가는 prompt_feedback에 별도로 저장되며,
        # 여기서는 그 최신 값을 읽기 전용으로 함께 내려 화면(3f)이 "이미 평가함"
        # 상태를 표시할 수 있게 한다 - 저장은 반드시 POST /api/prompts/feedback로만.
        "promptFeedback": _prompt_feedback_to_json((feedback_by_output_id or {}).get(row.prompt_generation_output_id)),
        "positivePrompt": row.positive_prompt,
        "negativePrompt": row.negative_prompt,
        "inputAssetIds": input_ids,
        "outputAssetIds": output_ids,
        "inputAssets": _prompt_assets(input_ids, assets_by_id),
        "outputAssets": _prompt_assets(output_ids, assets_by_id),
        "qualityRating": row.quality_rating,
        "qualityComment": row.quality_comment,
        "reuseEligible": bool(row.reuse_eligible),
        "reviewStatus": row.review_status or "unreviewed",
        "reviewFlags": row.review_flags_json or {},
        "reviewedBy": row.reviewed_by,
        **timestamp_fields("reviewedAt", row.reviewed_at, naive_timezone=SEOUL_TIMEZONE, source_timezone="Asia/Seoul", source="task-review"),
        "reuseCount": row.reuse_count,
        "metadata": row.metadata_json or {},
        **timestamp_fields("createdAt", row.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
        **timestamp_fields("updatedAt", row.updated_at, naive_timezone=SEOUL_TIMEZONE, source_timezone="Asia/Seoul", source="task-review"),
    }
    return result


def _asset_created_at(payload: dict) -> datetime | None:
    value = payload.get("createdAtUtc") or payload.get("createdAt")
    source_timezone = str(payload.get("createdAtSourceTimezone") or "").strip()
    naive_timezone = SEOUL_TIMEZONE if source_timezone == "Asia/Seoul" or payload.get("createdAtKst") else UTC_TIMEZONE
    parsed = parse_timestamp(value, naive_timezone=naive_timezone)
    return parsed.astimezone(UTC_TIMEZONE).replace(tzinfo=None) if parsed else None


def _task_timestamp_fields(task: WorkflowTask, field_name: str, value: datetime | None) -> dict:
    context = task.time_context_json or {}
    application = context.get("application") if isinstance(context.get("application"), dict) else {}
    existing = application.get(field_name) if isinstance(application.get(field_name), dict) else None
    if existing and (existing.get("utc") or existing.get("kst")):
        return {
            field_name: existing.get("kst") or existing.get("utc"),
            f"{field_name}Utc": existing.get("utc"),
            f"{field_name}Kst": existing.get("kst"),
            f"{field_name}SourceTimezone": existing.get("sourceTimezone"),
            f"{field_name}Source": existing.get("source"),
        }
    naive_timezone, source_timezone, source = _task_stored_timestamp_source(task, field_name, value)
    return timestamp_fields(
        field_name,
        value,
        naive_timezone=naive_timezone,
        source_timezone=source_timezone,
        source=source,
    )


def _task_stored_timestamp_source(
    task: WorkflowTask,
    field_name: str,
    value: datetime | None,
) -> tuple[object, str, str]:
    """Classify legacy naive task values without rewriting their DB rows.

    Task tracking historically stored application timestamps in KST. A short
    period of RunPod status synchronization, however, wrote a UTC `startedAt`
    into the same column. A task start/completion more than two hours before
    its KST creation time is therefore the UTC variant and can be normalized
    safely for the API response.
    """
    if value and field_name in {"timestamp", "startedAt", "completedAt"} and task.created_at:
        if value < task.created_at - timedelta(hours=2):
            return UTC_TIMEZONE, "UTC", "legacy-runpod-status"
    return SEOUL_TIMEZONE, "Asia/Seoul", "legacy-task-tracking"


def _timestamp_pair_or_task_value(
    task: WorkflowTask,
    field_name: str,
    candidate: Any,
    fallback: datetime | None,
) -> dict[str, str | None]:
    """Use a provider timestamp only when it is parseable; otherwise fallback."""
    if parse_timestamp(candidate, naive_timezone=SEOUL_TIMEZONE):
        return timestamp_pair(
            candidate,
            naive_timezone=SEOUL_TIMEZONE,
            source_timezone="Asia/Seoul",
            source="ecs-application",
        )
    naive_timezone, source_timezone, source = _task_stored_timestamp_source(task, field_name, fallback)
    return timestamp_pair(
        fallback,
        naive_timezone=naive_timezone,
        source_timezone=source_timezone,
        source=source,
    )


def _time_context(task: WorkflowTask, job: dict, now: datetime) -> dict:
    previous = dict(task.time_context_json or {})
    application = dict(previous.get("application") or {})
    application["createdAt"] = timestamp_pair(
        job.get("createdAt"),
        naive_timezone=UTC_TIMEZONE,
        source_timezone="UTC",
        source="ecs-application",
    )
    application["startedAt"] = _timestamp_pair_or_task_value(
        task,
        "startedAt",
        job.get("startedAt"),
        task.started_at or task.created_at,
    )
    application["timestamp"] = application["startedAt"]
    application["updatedAt"] = timestamp_pair(
        now,
        naive_timezone=SEOUL_TIMEZONE,
        source_timezone="Asia/Seoul",
        source="ecs-application",
    )
    if task.completed_at:
        application["completedAt"] = timestamp_pair(
            task.completed_at,
            naive_timezone=SEOUL_TIMEZONE,
            source_timezone="Asia/Seoul",
            source="ecs-application",
        )

    runpod = dict(previous.get("runpod") or {})
    for source_name, payload in (("submit", job.get("runpodSubmit")), ("status", job.get("runpodStatus"))):
        runpod[source_name] = _extract_runpod_timestamps(payload)
    return {
        **previous,
        "contractVersion": 1,
        "application": application,
        "runpod": runpod,
    }


def _extract_runpod_timestamps(payload: Any) -> dict[str, dict]:
    result: dict[str, dict] = {}

    def visit(value: Any, path: str = "", depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                normalized = "".join(character for character in key_text.lower() if character.isalnum())
                next_path = f"{path}.{key_text}" if path else key_text
                if normalized in RUNPOD_TIMESTAMP_KEYS and item not in (None, ""):
                    pair = timestamp_pair(
                        item,
                        naive_timezone=SEOUL_TIMEZONE,
                        source_timezone="Asia/Seoul",
                        source="runpod",
                    )
                    result[next_path] = {"raw": str(item), **pair}
                visit(item, next_path, depth + 1)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]", depth + 1)

    visit(payload)
    return result


def _task_model_references(row: TaskPrompt) -> tuple[list[dict], str]:
    """Resolve a task's selected model files without allowing model reuse.

    New tasks own an immutable submission snapshot in metadata_json. Older rows
    did not have that snapshot, so they fall back to the currently registered
    workflow metadata and explicitly report that source to the caller.
    """
    metadata = row.metadata_json or {}
    snapshot = metadata.get("modelReferences")
    snapshot_items = []
    if isinstance(snapshot, list):
        snapshot_items = [item for item in snapshot if isinstance(item, dict) and item.get("bucket") and item.get("value")]
        if snapshot_items and metadata.get("modelReferenceSource") == "submission_snapshot":
            # 신규 작업은 제출 직전의 실제 workflow 선택값이므로 이후 workflow
            # 변경값을 합치지 않는다. 이력이 항상 실행 당시를 재현하도록 한다.
            return _unique_model_references(snapshot_items), "submission_snapshot"

    current_items = _current_workflow_model_references(row.workflow_id)
    if snapshot_items:
        combined = _unique_model_references([*snapshot_items, *current_items])
        if combined:
            return combined, "metadata_json_plus_current_workflow"
    if current_items:
        return current_items, "current_workflow_metadata"
    return [], "unavailable"


def _current_workflow_model_references(workflow_id: str) -> list[dict]:
    try:
        workflow_metadata = get_workflow_widget_metadata(workflow_id)
    except (FileNotFoundError, OSError, ValueError):
        return []

    tracked_buckets = {"checkpoints", "vae", "loras", "text_encoders", "unet", "video_models", "models"}
    items = []
    for node in workflow_metadata.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        for field in node.get("inputs") or []:
            if not isinstance(field, dict):
                continue
            bucket = str(field.get("modelBucket") or "")
            value = field.get("value")
            if bucket not in tracked_buckets or not isinstance(value, str) or not value.strip():
                continue
            items.append({
                "bucket": bucket,
                "nodeId": str(node.get("nodeId") or ""),
                "nodeTitle": str(node.get("title") or node.get("classType") or ""),
                "classType": str(node.get("classType") or ""),
                "field": str(field.get("field") or ""),
                "value": value.strip(),
            })
    return _unique_model_references(items)


def _unique_model_references(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        key = (
            str(item.get("bucket") or ""),
            str(item.get("nodeId") or ""),
            str(item.get("field") or ""),
            str(item.get("value") or ""),
        )
        if not all(key) or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _apply_prompt_review(row: TaskPrompt, payload: dict) -> None:
    rating = payload.get("qualityRating")
    if rating in (None, ""):
        raise ValueError("평가 등급을 선택하세요.")
    normalized_rating = int(rating)
    if normalized_rating not in {1, 2, 3, 4, 5}:
        raise ValueError("평가 등급은 1부터 5까지 선택할 수 있습니다.")
    row.quality_rating = normalized_rating
    row.quality_comment = str(payload.get("qualityComment") or payload.get("comment") or "").strip() or None
    submitted_flags = payload.get("reviewFlags") or {}
    submitted_flags = submitted_flags if isinstance(submitted_flags, dict) else {}
    row.review_flags_json = {
        key: any(bool(submitted_flags.get(alias)) for alias in aliases)
        for key, aliases in LEGACY_REVIEW_FLAG_ALIASES.items()
    }
    row.reuse_eligible = bool(payload.get("reuseEligible"))
    has_reason = any(bool(value) for value in row.review_flags_json.values())
    if not has_reason and not row.quality_comment:
        raise ValueError("평가 사유를 하나 이상 선택하거나 코멘트를 입력하세요.")
    row.review_status = "reviewed"
    row.reviewed_by = str(payload.get("reviewedBy") or payload.get("userId") or "").strip() or row.reviewed_by
    row.reviewed_at = now_seoul_naive() if row.review_status == "reviewed" else None
    row.updated_at = now_seoul_naive()


def _prompt_assets(asset_ids: list, assets_by_id: dict[str, dict] | None) -> list[dict]:
    if not assets_by_id:
        return []
    result = []
    for asset_id in asset_ids:
        asset = assets_by_id.get(str(asset_id))
        if asset:
            result.append(asset)
    return result


def _reusable_prompt_matches_keyword(item: dict, keyword: str) -> bool:
    needle = str(keyword or "").strip().lower()
    if not needle:
        return True
    haystack_parts = [
        item.get("taskId"),
        item.get("workflowId"),
        item.get("modelName"),
        item.get("positivePrompt"),
        item.get("negativePrompt"),
        item.get("qualityComment"),
        item.get("reviewStatus"),
        item.get("createdAt"),
        item.get("updatedAt"),
    ]
    for asset in (item.get("inputAssets") or []) + (item.get("outputAssets") or []):
        haystack_parts.extend([
            asset.get("assetId"),
            asset.get("fileName"),
            asset.get("mimeType"),
            asset.get("kind"),
            asset.get("outputRole"),
        ])
    for key, enabled in (item.get("reviewFlags") or {}).items():
        if enabled:
            haystack_parts.extend([key, REVIEW_FLAG_LABELS.get(str(key), "")])
    return needle in " ".join(str(part or "") for part in haystack_parts).lower()
