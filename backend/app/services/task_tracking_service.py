from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models import Asset, PromptFeedback, TaskInputAsset, TaskOutputAsset, TaskPrompt, User, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services.json_repository import hydrate_input_images, hydrate_output_asset


TERMINAL_STATES = {"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"}
HISTORY_RESULT_STATES = {"COMPLETED", "SUCCESS", "FAILED", "TIMED_OUT"}
REVIEW_FLAG_LABELS = {
    "intentMatched": "프롬프트 의도 반영 intent matched prompt intent",
    "identityPreserved": "이미지 정체성 유지 identity preserved",
    "naturalMotion": "움직임 자연스러움 natural motion",
    "noDistortion": "왜곡 깨짐 없음 no distortion",
    "backgroundStable": "배경 안정성 background stable",
}


def record_job_created(job: dict, *, resolve_asset: Callable[[str], tuple[dict, Path]] | None = None) -> None:
    _with_session(lambda session: _record_job_created(session, job, resolve_asset=resolve_asset))


def record_job_status(job: dict, *, resolve_asset: Callable[[str], tuple[dict, Path]] | None = None) -> None:
    _with_session(lambda session: _record_job_status(session, job, resolve_asset=resolve_asset))


def task_history_items(page: int | None = None, page_size: int | None = None) -> list[dict]:
    session = SessionLocal()
    try:
        id_statement = (
            select(WorkflowTask.id)
            # B-05: soft delete된 작업(deleted_at IS NOT NULL)은 이력에서 제외.
            .where(func.upper(WorkflowTask.status).in_(HISTORY_RESULT_STATES), WorkflowTask.deleted_at.is_(None))
            .order_by(WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
        )
        if page is not None and page_size is not None:
            safe_page = max(1, int(page))
            safe_page_size = max(1, min(200, int(page_size)))
            id_statement = id_statement.offset((safe_page - 1) * safe_page_size).limit(safe_page_size)
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
        assets_by_id = _assets_by_id(session)
        tasks_by_id = {task.id: task for task in tasks}
        return [
            _task_to_history_item(tasks_by_id[task_id], assets_by_id)
            for task_id in task_ids
            if task_id in tasks_by_id
        ]
    finally:
        session.close()


def task_history_total() -> int:
    session = SessionLocal()
    try:
        statement = (
            select(func.count())
            .select_from(WorkflowTask)
            # B-05: soft delete된 작업은 총계에서도 제외(목록과 페이지네이션 일치).
            .where(func.upper(WorkflowTask.status).in_(HISTORY_RESULT_STATES), WorkflowTask.deleted_at.is_(None))
        )
        return int(session.scalar(statement) or 0)
    finally:
        session.close()


def list_assets(
    page: int | None = None,
    page_size: int | None = None,
    *,
    asset_type: str = "",
    workflow_id: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict]:
    """A-01: `GET /api/assets` 목록. history와 동일하게 DB 전용으로 구현한다(D-03
    선례 - 운영은 `PERSISTENCE_BACKEND=db`가 필수값이라 repository 추상화를 통하지
    않아도 실사용 경로와 어긋나지 않음). `taskId`/`outputRole`은 `task_output_assets`
    조인으로 채운다 - 업로드만 되고 아직 어떤 작업의 출력으로도 연결되지 않은 자산은
    두 필드가 빈 값으로 남는다(입력 이미지 등)."""
    session = SessionLocal()
    try:
        statement = select(Asset.id).order_by(Asset.created_at.desc(), Asset.id.desc())
        conditions = _asset_filter_conditions(session, asset_type=asset_type, workflow_id=workflow_id, date_from=date_from, date_to=date_to)
        if conditions:
            statement = statement.where(*conditions)
        if page is not None and page_size is not None:
            safe_page = max(1, int(page))
            safe_page_size = max(1, min(200, int(page_size)))
            statement = statement.offset((safe_page - 1) * safe_page_size).limit(safe_page_size)
        asset_ids = list(session.scalars(statement))
        if not asset_ids:
            return []

        assets_by_id = {
            asset.id: asset
            for asset in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()
        }
        # A-01 완료 기준: 응답에 연결된 taskId·output_role 포함. 동일 자산이 여러
        # 작업의 출력으로 연결될 일은 없지만(assets.id는 생성 시점에 1건만 만들어짐),
        # 만약을 대비해 가장 최근 링크 하나만 취한다.
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
            for task in (session.scalars(select(WorkflowTask).where(WorkflowTask.id.in_(task_ids))).all() if task_ids else [])
        }

        items = []
        for asset_id in asset_ids:
            asset = assets_by_id.get(asset_id)
            if not asset:
                continue
            item = _asset_to_json(asset)
            link = link_by_asset.get(asset_id)
            item["taskId"] = link.task_id if link else ""
            item["outputRole"] = link.output_role if link else ""
            item["segmentIndex"] = link.segment_index if link else None
            task = tasks_by_id.get(link.task_id) if link else None
            if task:
                item["workflowId"] = task.workflow_id
            items.append(item)
        return items
    finally:
        session.close()


def assets_total(*, asset_type: str = "", workflow_id: str = "", date_from: str = "", date_to: str = "") -> int:
    session = SessionLocal()
    try:
        conditions = _asset_filter_conditions(session, asset_type=asset_type, workflow_id=workflow_id, date_from=date_from, date_to=date_to)
        statement = select(func.count()).select_from(Asset)
        if conditions:
            statement = statement.where(*conditions)
        return int(session.scalar(statement) or 0)
    finally:
        session.close()


def _asset_filter_conditions(
    session: Session,
    *,
    asset_type: str,
    workflow_id: str,
    date_from: str,
    date_to: str,
) -> list:
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
            Asset.id.in_(
                select(TaskOutputAsset.asset_id)
                .join(WorkflowTask, TaskOutputAsset.task_id == WorkflowTask.id)
                .where(WorkflowTask.workflow_id == workflow_id)
            )
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
        history_item = _task_to_history_item(task, _assets_by_id(session))
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
        created_at = task.created_at.timestamp() if task.created_at else datetime.utcnow().timestamp()
        return {
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
            "restoredFromDb": True,
        }
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
        assets_by_id = _assets_by_id(session)
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
        row.updated_at = datetime.utcnow()
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
        return _task_prompt_to_json(row, _assets_by_id(session), feedback_by_output_id)
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
        query = select(TaskPrompt).order_by(
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
        assets_by_id = _assets_by_id(session)
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


def _record_job_status(session: Session, job: dict, *, resolve_asset: Callable[[str], tuple[dict, Path]] | None) -> None:
    task = _upsert_task(session, job)
    _replace_input_assets(session, task, job, resolve_asset=resolve_asset)
    if not task.prompts:
        _replace_task_prompts(session, task, job)
    _replace_output_assets(session, task, job, resolve_asset=resolve_asset)
    _sync_task_prompt_outputs(session, task, job)


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
    now = datetime.utcnow()
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
    task.runpod_submit_json = job.get("runpodSubmit") or {}
    task.runpod_status_json = job.get("runpodStatus") or {}
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
    for index, asset_id in enumerate(_input_asset_ids(job), start=1):
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
    for asset in job.get("outputAssets") or []:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("assetId") or "").strip()
        if not asset_id:
            continue
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
        prompt.updated_at = datetime.utcnow()


def _ensure_user(session: Session, user_payload: dict) -> User | None:
    user_id = str(user_payload.get("id") or user_payload.get("email") or "").strip()
    if not user_id:
        return None
    user = session.get(User, user_id)
    is_new_user = user is None
    if not user:
        user = User(id=user_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
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
    user.updated_at = datetime.utcnow()
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
    asset.metadata_json = {
        key: value
        for key, value in payload.items()
        if key not in {"assetId", "id", "type", "assetType", "fileName", "filename", "mimeType", "sizeBytes", "path", "storageKey", "storageBackend", "publicUrl", "createdAt"}
    }
    asset.created_at = _parse_datetime(payload.get("createdAt")) or asset.created_at or datetime.utcnow()
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
        return max(0, int(datetime.utcnow().timestamp() - float(job["createdAt"])))
    except (TypeError, ValueError):
        return None


def _from_epoch(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text.removesuffix("Z"), pattern)
        except ValueError:
            continue
    return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _task_to_history_item(task: WorkflowTask, assets_by_id: dict[str, dict]) -> dict:
    item = dict(task.payload_json or {})
    item.setdefault("taskId", task.id)
    item.setdefault("timestamp", _format_datetime(task.started_at or task.created_at))
    item.setdefault("workflowId", task.workflow_id)
    item.setdefault("workflowName", task.workflow_id)
    item.setdefault("runpodJobId", task.runpod_job_id or "")
    item.setdefault("executionMode", task.execution_mode)
    item.setdefault("workerName", task.worker_name or "-")
    item["status"] = _history_status_label(task.status)
    item.setdefault("progress", int(task.progress or 0))
    item.setdefault("positivePrompts", task.positive_prompts or [])
    item.setdefault("negativePrompts", task.negative_prompts or [])
    item.setdefault("configJson", task.config_json or {})
    item.setdefault("wanNodeConfig", task.wan_node_config or {})
    item.setdefault("patchSummary", task.patch_summary or {})
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
    item.setdefault("completedAt", _format_datetime(task.completed_at) if task.completed_at else "")
    item.setdefault("elapsedSeconds", task.elapsed_seconds)
    return item


def _assets_by_id(session: Session) -> dict[str, dict]:
    return {_asset.id: _asset_to_json(_asset) for _asset in session.scalars(select(Asset)).all()}


def _prompt_feedback_by_output_id(session: Session, output_ids: list[str | None]) -> dict[str, PromptFeedback]:
    """B-02: `prompt_feedback`("프롬프트 생성 품질" 평가, `task_prompts.quality_rating`
    ("영상 결과 평가")과는 역할이 분리된 별도 저장소)에서 이 배치의 `prompt_generation_output_id`들에
    연결된 기존 평가를 한 번에 읽어온다 - `_assets_by_id`와 동일하게 N+1 쿼리를 피하기 위한
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
    return {
        "id": feedback.id,
        "rating": feedback.rating,
        "notes": feedback.notes,
        "editedPositivePrompt": feedback.edited_positive_prompt,
        "editedNegativePrompt": feedback.edited_negative_prompt,
        "createdAt": feedback.created_at.isoformat() if feedback.created_at else None,
    }


def _asset_to_json(asset: Asset) -> dict:
    item = dict(asset.metadata_json or {})
    item.update({
        "assetId": asset.id,
        "type": asset.asset_type,
        "fileName": asset.file_name,
        "mimeType": asset.mime_type,
        "sizeBytes": asset.size_bytes,
        "path": asset.storage_key,
        "storageBackend": asset.storage_backend,
        "publicUrl": asset.public_url,
        "createdAt": _format_datetime(asset.created_at),
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
    if text in {"FAILED", "CANCELLED", "TIMED_OUT"}:
        return "Failed"
    return status or "queued"


def _format_datetime(value: datetime | None) -> str:
    return (value or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")


def _task_prompt_to_json(
    row: TaskPrompt,
    assets_by_id: dict[str, dict] | None = None,
    feedback_by_output_id: dict[str, PromptFeedback] | None = None,
) -> dict:
    input_ids = row.input_asset_ids or []
    output_ids = row.output_asset_ids or []
    return {
        "id": row.id,
        "taskId": row.task_id,
        "workflowId": row.workflow_id,
        "segmentIndex": row.segment_index,
        "modelProfileId": row.model_profile_id,
        "modelName": row.model_name,
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
        "reviewedAt": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "reuseCount": row.reuse_count,
        "metadata": row.metadata_json or {},
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _apply_prompt_review(row: TaskPrompt, payload: dict) -> None:
    rating = payload.get("qualityRating")
    row.quality_rating = None if rating in (None, "") else max(1, min(5, int(rating)))
    row.quality_comment = str(payload.get("qualityComment") or payload.get("comment") or "").strip() or None
    flags = payload.get("reviewFlags") or {}
    row.review_flags_json = flags if isinstance(flags, dict) else {}
    row.reuse_eligible = bool(payload.get("reuseEligible"))
    if row.reuse_eligible and not any(bool(value) for value in row.review_flags_json.values()):
        raise ValueError("재사용 가능으로 저장하려면 재사용 사유를 하나 이상 체크해야 합니다.")
    row.review_status = "reviewed" if row.quality_rating is not None else "unreviewed"
    row.reviewed_by = str(payload.get("reviewedBy") or payload.get("userId") or "").strip() or row.reviewed_by
    row.reviewed_at = datetime.utcnow() if row.review_status == "reviewed" else None
    row.updated_at = datetime.utcnow()


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
