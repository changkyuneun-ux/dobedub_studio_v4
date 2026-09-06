from __future__ import annotations

import json
import uuid
from pathlib import Path
from threading import RLock

from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, timestamp_pair, utc_now
from backend.app.repositories.factory import data_paths, history_repository, studio_repository
from backend.app.services import job_service, output_service, workflow_patch_service
from backend.app.db.models import Asset, ImagePromptDraft, RunpodRequestBatch, RunpodRequestItem, User, WorkflowTask
from backend.app.services.asset_storage import encode_file_base64, safe_filename
from backend.app.services.runpod_client import connection_status as runpod_connection_status
from backend.app.services.runpod_client import runpod_request as runpod_client_request
from backend.app.services.task_tracking_service import (
    active_task_ids,
    assets_total,
    list_assets,
    record_job_status,
    restore_job_from_task,
    reusable_task_prompts,
    task_history_items,
    task_history_total,
    task_prompts,
    update_task_prompt_quality,
    update_task_prompt_review,
)
from backend.app.services.task_policy_service import assert_task_submission_allowed
from backend.app.services.runpod_dispatch_service import RunpodDispatchRuntime, dispatch_next_pending_submission
from backend.app.services.runpod_request_batch_service import (
    attach_task_to_request_item,
    create_request_batch,
    latest_active_request_batch,
    mark_request_item_failed,
    request_batch_dashboard,
    request_batch_queue,
    request_batch_payload,
)
from backend.app.db.session import SessionLocal


JOBS: dict[str, dict] = {}
JOB_LOCK = RLock()
REUSABLE_REGENERATION_STATUSES = {
    "PENDING_SUBMIT",
    "DISPATCHING",
    "QUEUED",
    "IN_QUEUE",
    "IN_PROGRESS",
    "RUNNING",
    "COMPLETED",
    "SUCCESS",
}


def ensure_storage_dirs() -> None:
    settings = get_settings()
    paths = data_paths()
    for key in ("uploads", "outputs", "reports"):
        paths[key].mkdir(parents=True, exist_ok=True)
    settings.workflows_dir.mkdir(parents=True, exist_ok=True)
    settings.metadata_dir.mkdir(parents=True, exist_ok=True)


# 프롬프트 옵션 목록은 최근 이력에서 텍스트만 뽑아 종류별 상위 100건으로 자른다.
# 최근 200건이면 그 100건을 채우고도 남는다. 전체 이력을 읽던 이전 구현은
# workflow_tasks 전 행을 한 요청에서 메모리로 올려 ECS 메모리 부족의 직접 원인이었다.
PROMPT_OPTION_HISTORY_LIMIT = 200


def load_history(limit: int = PROMPT_OPTION_HISTORY_LIMIT) -> list[dict]:
    # Task history is DB-only (D-03): always read through task_tracking_service,
    # independent of PERSISTENCE_BACKEND (which still governs assets/configs/
    # uploads via studio_repository()).
    return task_history_items(1, limit)


def paginated_history(
    page: int = 1,
    page_size: int = 20,
    *,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    date_from: str = "",
    date_to: str = "",
    batch_job_id: str = "",
) -> dict:
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))
    workflow_id = str(workflow_id or "").strip()
    result_status = str(result_status or "").strip()
    worker_id = str(worker_id or "").strip()
    date_from = str(date_from or "").strip()
    date_to = str(date_to or "").strip()
    batch_job_id = str(batch_job_id or "").strip()
    return {
        "items": task_history_items(
            page,
            page_size,
            workflow_id=workflow_id,
            result_status=result_status,
            worker_id=worker_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
        ),
        "page": page,
        "pageSize": page_size,
        "total": task_history_total(
            workflow_id=workflow_id,
            result_status=result_status,
            worker_id=worker_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_job_id,
        ),
    }


def paginated_runpod_history(
    page: int = 1,
    *,
    workflow_id: str = "",
    result_status: str = "",
    worker_id: str = "",
    run_date: str = "",
    batch_job_id: str = "",
) -> dict:
    """Return the dedicated RunPod-history contract with its fixed 20-row page."""
    run_date = str(run_date or "").strip()
    return paginated_history(
        page,
        20,
        workflow_id=workflow_id,
        result_status=result_status,
        worker_id=worker_id,
        date_from=run_date,
        date_to=run_date,
        batch_job_id=batch_job_id,
    )


def append_history(item: dict) -> list[dict]:
    # Task history is DB-only (D-03): bypasses PERSISTENCE_BACKEND on purpose.
    with history_repository() as repository:
        return repository.append_history(item)


def delete_history_item(task_id: str) -> dict:
    # Task history is DB-only (D-03): bypasses PERSISTENCE_BACKEND on purpose.
    with history_repository() as repository:
        return repository.delete_history_item(task_id)


def paginated_assets(
    page: int = 1,
    page_size: int = 20,
    *,
    asset_type: str = "",
    workflow_id: str = "",
    date_from: str = "",
    date_to: str = "",
    collection_id: int | None = None,
    uncategorized: bool = False,
) -> dict:
    # A-01: history와 동일하게 DB 전용(D-03 선례). PERSISTENCE_BACKEND=json에서는
    # task_output_assets 조인 대상이 비어 있을 수 있으나, 운영 환경은 항상
    # PERSISTENCE_BACKEND=db이므로(docs/aws-ecs-deployment.md) 실사용 경로와는 무관.
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))
    filters = dict(
        asset_type=asset_type,
        workflow_id=workflow_id,
        date_from=date_from,
        date_to=date_to,
        collection_id=collection_id,
        uncategorized=uncategorized,
    )
    return {
        "items": list_assets(page, page_size, **filters),
        "page": page,
        "pageSize": page_size,
        "total": assets_total(**filters),
    }


def load_configs() -> list[dict]:
    with studio_repository() as repository:
        return repository.load_configs()


def append_config(item: dict) -> list[dict]:
    with studio_repository() as repository:
        return repository.append_config(item)


def create_config_snapshot(payload: dict) -> dict:
    source = payload.get("source") or "studio"
    snapshot = payload.get("snapshot") or {}
    workflow_id = snapshot.get("workflowId") or payload.get("workflowId") or "unknown"
    created_at = utc_now()
    config_id = f"config_{created_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    item = {
        "configId": config_id,
        **timestamp_fields("timestamp", created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="config-snapshot"),
        "source": source,
        "workflowId": workflow_id,
        "user": payload.get("user") or snapshot.get("user") or {},
        "name": payload.get("name") or f"{Path(workflow_id).stem} saved config",
        "snapshot": snapshot,
    }
    append_config(item)
    return item


def prompt_options() -> dict:
    history = load_history()
    configs = load_configs()
    options = {"positive": [], "negative": []}

    def add_option(kind, text, label, source, workflow_id="", segment_index=None):
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        option_id = f"{kind}_{uuid.uuid5(uuid.NAMESPACE_URL, f'{kind}:{source}:{label}:{cleaned}').hex[:12]}"
        if any(item["text"] == cleaned and item["label"] == label for item in options[kind]):
            return
        options[kind].append({
            "id": option_id,
            "label": label,
            "text": cleaned,
            "source": source,
            "workflowId": workflow_id,
            "segmentIndex": segment_index,
        })

    for item in history:
        workflow_id = item.get("workflowId") or item.get("workflowName") or item.get("workflow") or ""
        timestamp = item.get("timestamp") or "-"
        for prompt in item.get("positivePrompts") or []:
            label = f"{timestamp} / {Path(workflow_id).stem or 'workflow'} / Segment {prompt.get('index', 1)}"
            add_option("positive", prompt.get("text"), label, "history", workflow_id, prompt.get("index"))
        for prompt in item.get("negativePrompts") or []:
            label = f"{timestamp} / {Path(workflow_id).stem or 'workflow'} / Segment {prompt.get('index', 1)}"
            add_option("negative", prompt.get("text"), label, "history", workflow_id, prompt.get("index"))

    for item in configs:
        snapshot = item.get("snapshot") or {}
        workflow_id = snapshot.get("workflowId") or item.get("workflowId") or ""
        timestamp = item.get("timestamp") or "-"
        for segment in snapshot.get("segments") or []:
            label = f"{timestamp} / {Path(workflow_id).stem or 'workflow'} / Segment {segment.get('index', 1)}"
            add_option("positive", segment.get("positivePrompt"), label, "config", workflow_id, segment.get("index"))
            add_option("negative", segment.get("negativePromptAddition") or segment.get("negativePrompt"), label, "config", workflow_id, segment.get("index"))

    return {
        "positive": options["positive"][:100],
        "negative": options["negative"][:100],
    }


def create_upload(payload: dict) -> dict:
    with studio_repository() as repository:
        return repository.create_upload(payload)


def get_asset(asset_id: str) -> tuple[dict, Path]:
    with studio_repository() as repository:
        return repository.get_asset(asset_id)


def register_asset(file_path: Path, asset_type: str, mime_type: str | None = None, file_name: str | None = None) -> dict:
    with studio_repository() as repository:
        return repository.register_asset(Path(file_path), asset_type, mime_type, file_name)


def hydrate_input_images(item: dict) -> list[dict]:
    with studio_repository() as repository:
        return repository.hydrate_input_images(item)


def asset_to_runpod_image(asset_id: str, fallback_name: str | None = None) -> dict:
    asset, path = get_asset(asset_id)
    return {
        "name": safe_filename(asset.get("fileName") or fallback_name or path.name),
        "path": str(path),
    }


def build_runpod_images(payload: dict) -> list[dict]:
    images = []
    keyframes = sorted(
        (keyframe for keyframe in payload.get("keyframes") or [] if isinstance(keyframe, dict)),
        key=lambda keyframe: int(keyframe.get("index") or 0),
    )
    for keyframe in keyframes:
        upload_id = keyframe.get("uploadId")
        if not upload_id:
            continue
        images.append(asset_to_runpod_image(upload_id, keyframe.get("fileName")))
    return images


def build_runpod_payload(workflow: dict, images: list[dict]) -> dict:
    input_body = {"workflow": workflow}
    if images:
        input_body["images"] = [
            {"name": image["name"], "image": encode_file_base64(Path(image["path"]))}
            for image in images
        ]
    return {"input": input_body}


def existing_save_video_outputs(workflow: dict, workflow_id: str, segments: list[dict]) -> dict:
    return output_service.existing_save_video_outputs(workflow, workflow_id, segments, get_settings().workflows_dir)


def prepare_workflow_for_job(payload: dict) -> tuple[dict, list[dict], dict]:
    return workflow_patch_service.prepare_workflow_for_job(
        payload,
        get_settings().workflows_dir,
        build_runpod_images,
        existing_save_video_outputs,
    )


def runpod_request(method: str, path: str, payload=None):
    settings = get_settings()
    return runpod_client_request(
        method,
        path,
        api_key=settings.runpod_api_key,
        endpoint_id=settings.runpod_endpoint_id,
        base_url=settings.runpod_base_url,
        timeout=settings.runpod_timeout,
        payload=payload,
    )


def runpod_connection() -> dict:
    settings = get_settings()
    return runpod_connection_status(
        api_key=settings.runpod_api_key,
        endpoint_id=settings.runpod_endpoint_id,
        base_url=settings.runpod_base_url,
        timeout=settings.runpod_timeout,
    )


def save_runpod_outputs(result: dict, job: dict) -> dict:
    return output_service.save_runpod_outputs(result, job, data_paths()["outputs"], register_asset)


def build_wan_node_config_snapshot(workflow_id: str, segments_payload: list[dict]) -> dict:
    return workflow_patch_service.build_wan_node_config_snapshot(workflow_id, segments_payload, get_settings().workflows_dir)


def job_runtime() -> job_service.JobRuntime:
    return job_service.JobRuntime(
        jobs=JOBS,
        dry_run=get_settings().dry_run,
        prepare_workflow_for_job=prepare_workflow_for_job,
        build_runpod_payload=build_runpod_payload,
        runpod_request=runpod_request,
        save_runpod_outputs=save_runpod_outputs,
        append_history=append_history,
        build_wan_node_config_snapshot=build_wan_node_config_snapshot,
        hydrate_input_images=hydrate_input_images,
        record_job=lambda job: record_job_status(job, resolve_asset=get_asset),
    )


def create_job(payload: dict, *, user: dict[str, object]) -> dict:
    """Queue one local task for the durable RunPod dispatcher.

    The browser payload is intentionally not trusted for task ownership.  The
    authenticated request principal is copied into the immutable task snapshot.
    Active-task limits are checked when the dispatcher is about to submit to
    RunPod so users can keep registering work while existing jobs finish.
    """
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise ValueError("인증된 사용자 정보를 찾을 수 없습니다.")
    with JOB_LOCK:
        safe_payload = dict(payload)
        safe_payload["user"] = {
            "id": user_id,
            "name": str(user.get("name") or user_id),
            "role": str(user.get("role") or ""),
            "permissions": list(user.get("permissions") or []),
        }
        return job_service.queue_job(job_runtime(), safe_payload)


def regenerate_history_item(task_id: str, *, user: dict[str, object]) -> dict:
    restored = restore_job_from_task(task_id)
    if not restored:
        raise KeyError(task_id)
    status = str(restored.get("status") or "").upper()
    if status not in {"FAILED", "CANCELLED", "TIMED_OUT"}:
        raise ValueError("실패한 RunPod 작업만 재생성할 수 있습니다.")
    existing_retry = _existing_regeneration_for_task(task_id)
    if existing_retry:
        return existing_retry
    payload = dict(restored.get("payload") or {})
    workflow_id = restored.get("workflowId") or payload.get("workflowId")
    if not workflow_id:
        raise ValueError("재생성할 workflowId를 찾을 수 없습니다.")
    payload["workflowId"] = workflow_id
    if restored.get("workflowName"):
        payload["workflowName"] = restored["workflowName"]
    for key in ("requestBatchId", "requestItemId", "runpodJobId", "generationSeed"):
        payload.pop(key, None)
    payload["regeneratedFromTaskId"] = task_id
    return create_job(payload, user=user)


def _existing_regeneration_for_task(task_id: str) -> dict | None:
    session = SessionLocal()
    try:
        tasks = list(session.scalars(
            select(WorkflowTask)
            .where(
                WorkflowTask.deleted_at.is_(None),
                func.upper(WorkflowTask.status).in_(REUSABLE_REGENERATION_STATUSES),
            )
            .order_by(WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
        ))
        for task in tasks:
            payload = task.payload_json if isinstance(task.payload_json, dict) else {}
            if str(payload.get("regeneratedFromTaskId") or "") == task_id:
                return restore_job_from_task(task.id)
        return None
    finally:
        session.close()


def job_payload_from_prompt_draft(draft_id: str, *, user: dict[str, object]) -> dict:
    """Build one single-keyframe job from a persisted, reviewed Grok draft.

    The batch flow intentionally does not combine draft records into a multi-keyframe
    graph yet.  Each selected image becomes an independently traceable RunPod task.
    """
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise ValueError("인증된 사용자 정보를 찾을 수 없습니다.")
    session = SessionLocal()
    try:
        draft = session.scalar(
            select(ImagePromptDraft).where(ImagePromptDraft.id == draft_id, ImagePromptDraft.created_by == user_id)
        )
        if draft is None:
            raise ValueError("프롬프트 초안을 찾을 수 없습니다.")
        if draft.status != "READY" or not str(draft.positive_prompt or "").strip():
            raise ValueError("완료된 Positive Prompt가 있는 초안만 RunPod 요청에 추가할 수 있습니다.")
        asset = session.get(Asset, draft.asset_id)
        if asset is None:
            raise ValueError("입력 이미지 자산을 찾을 수 없습니다.")
        frames = max(1, int(draft.requested_frames or 81))
        # Draft-based jobs are submitted outside the legacy workspace form.
        # Carry the persisted source dimensions so the Wan node receives the
        # exact uploaded image size, just as it does for a direct submission.
        config = {"frames": frames, "frame_count": frames, "length": frames, "fps": 16}
        if asset.image_width and int(asset.image_width) > 0:
            config["width"] = int(asset.image_width)
        if asset.image_height and int(asset.image_height) > 0:
            config["height"] = int(asset.image_height)
        return {
            "workflowId": draft.workflow_id,
            # The job history must show the registered workflow label rather
            # than the JSON filename. The parser uses the filename stem as the
            # stable display name for registered workflows.
            "workflowName": Path(draft.workflow_id).stem,
            "promptDraftId": draft.id,
            "keyframes": [{"index": 1, "uploadId": asset.id, "fileName": asset.file_name}],
            "segments": [{
                "index": 1,
                "positivePrompt": draft.positive_prompt,
                "negativePromptAddition": draft.negative_prompt or "",
                "config": config,
            }],
        }
    finally:
        session.close()


def job_payload_from_request_item(item_id: str, *, user: dict[str, object], worker_id: str | None = None) -> dict:
    """Build a job solely from the request item's immutable snapshot."""
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise ValueError("인증된 사용자 정보를 찾을 수 없습니다.")
    session = SessionLocal()
    try:
        item = session.scalar(
            select(RunpodRequestItem)
            .where(RunpodRequestItem.id == item_id)
            .limit(1)
        )
        if item is None:
            raise ValueError("RunPod 요청 항목을 찾을 수 없습니다.")
        batch_owner = session.get(RunpodRequestBatch, item.request_batch_id)
        if batch_owner is None or batch_owner.created_by != (worker_id or user_id):
            raise ValueError("RunPod 요청 항목에 접근할 수 없습니다.")
        asset = session.get(Asset, item.asset_id)
        if asset is None:
            raise ValueError("입력 이미지 자산을 찾을 수 없습니다.")
        config = {"frames": item.requested_frames, "frame_count": item.requested_frames, "length": item.requested_frames, "fps": 16}
        if asset.image_width and int(asset.image_width) > 0:
            config["width"] = int(asset.image_width)
        if asset.image_height and int(asset.image_height) > 0:
            config["height"] = int(asset.image_height)
        return {
            "workflowId": item.workflow_id,
            "workflowName": Path(item.workflow_id).stem,
            "promptDraftId": item.prompt_draft_id,
            "requestBatchId": item.request_batch_id,
            "requestItemId": item.id,
            "batchJobId": batch_owner.batch_job_id,
            "keyframes": [{"index": 1, "uploadId": asset.id, "fileName": asset.file_name}],
            "segments": [{
                "index": 1,
                "positivePrompt": item.positive_prompt,
                "negativePromptAddition": item.negative_prompt or "",
                "config": config,
            }],
        }
    finally:
        session.close()


def create_runpod_request_batch(
    payload: dict, *, user: dict[str, object], batch_job_id: str | None = None
) -> dict:
    """Create durable local tasks for selected drafts without calling RunPod yet."""
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        raise ValueError("인증된 사용자 정보를 찾을 수 없습니다.")
    worker_id = str(payload.get("workerId") or user_id).strip()
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        draft_ids = payload.get("promptDraftIds") or []
        raw_items = [{"promptDraftId": draft_id} for draft_id in draft_ids]
    with JOB_LOCK:
        session = SessionLocal()
        try:
            worker = session.get(User, worker_id)
            if worker is None or not worker.is_active:
                raise ValueError("선택한 작업자를 찾을 수 없거나 비활성 상태입니다.")
            # The selected worker owns the created tasks even when a manager
            # submits the batch. Keep only a plain snapshot beyond this session
            # boundary so a detached ORM object cannot alter the ownership flow.
            worker_user = {
                "id": worker.id,
                "name": worker.name,
                "role": worker.role,
                "permissions": worker.permissions_json or [],
            }
            batch = create_request_batch(
                session,
                items=raw_items,
                created_by=worker_id,
                submitted_by=user_id,
                # Only the batch pipeline passes this as an explicit keyword
                # argument; it is never read out of the request body, so an
                # HTTP caller has no way to attach a task to someone else's
                # batch job. The interactive path leaves it unset, so
                # non-batch requests stay unlabelled.
                batch_job_id=str(batch_job_id or "").strip() or None,
            )
        finally:
            session.close()

        if "createdItemIds" in batch:
            created_item_ids = {str(item_id) for item_id in batch.get("createdItemIds", [])}
            materialization_items = [
                item for item in batch["items"]
                if str(item.get("id") or "") in created_item_ids
            ]
        else:
            materialization_items = list(batch["items"])
        for item in materialization_items:
            try:
                job_payload = job_payload_from_request_item(item["id"], user=user, worker_id=worker_id)
                job = create_job(job_payload, user=worker_user)
                link_session = SessionLocal()
                try:
                    attach_task_to_request_item(link_session, item_id=item["id"], task_id=job["taskId"])
                finally:
                    link_session.close()
            except Exception as exc:
                error_session = SessionLocal()
                try:
                    mark_request_item_failed(error_session, item_id=item["id"], message=str(exc))
                finally:
                    error_session.close()
        result_session = SessionLocal()
        try:
            return request_batch_payload(result_session, batch["id"], created_by=worker_id)
        finally:
            result_session.close()


def active_runpod_request_batch(*, user: dict[str, object], worker_id: str | None = None) -> dict | None:
    user_id = str(user.get("id") or "").strip()
    selected_worker = str(worker_id or user_id).strip()
    session = SessionLocal()
    try:
        return latest_active_request_batch(session, created_by=selected_worker)
    finally:
        session.close()


def runpod_request_dashboard(
    *,
    worker_id: str | None = None,
    workflow_id: str = "",
    status_filter: str = "",
) -> dict:
    session = SessionLocal()
    try:
        return request_batch_dashboard(
            session,
            created_by=worker_id,
            workflow_id=workflow_id,
            status_filter=status_filter,
        )
    finally:
        session.close()


def runpod_request_queue(
    *,
    worker_id: str | None = None,
    workflow_id: str = "",
    status_filter: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict:
    session = SessionLocal()
    try:
        return request_batch_queue(
            session,
            created_by=worker_id,
            workflow_id=workflow_id,
            status_filter=status_filter,
            page=page,
            page_size=page_size,
        )
    finally:
        session.close()


def runpod_request_batch(batch_id: str, *, user: dict[str, object]) -> dict:
    session = SessionLocal()
    try:
        return request_batch_payload(
            session,
            batch_id,
            actor_id=str(user.get("id") or ""),
            can_manage=bool(user.get("canManage")),
        )
    finally:
        session.close()


def _dispatch_pending_job(task_id: str) -> dict:
    with JOB_LOCK:
        restored = restore_job_from_task(task_id)
        if not restored:
            raise KeyError(task_id)
        _assert_dispatch_allowed(task_id)
        JOBS[task_id] = restored
        return job_service.dispatch_queued_job(job_runtime(), restored)


def _assert_dispatch_allowed(task_id: str) -> None:
    session = SessionLocal()
    try:
        task = session.get(WorkflowTask, task_id)
        if task is None:
            raise KeyError(task_id)
        payload = task.payload_json if isinstance(task.payload_json, dict) else {}
        payload_user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        user_id = str(task.user_id or payload_user.get("id") or "__unknown__").strip()
        assert_task_submission_allowed(session, user_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispatch_next_queued_job() -> dict:
    settings = get_settings()
    return dispatch_next_pending_submission(RunpodDispatchRuntime(
        dry_run=settings.dry_run,
        connection_status=runpod_connection,
        dispatch_task=_dispatch_pending_job,
    ))


def job_status(task_id: str) -> dict:
    with JOB_LOCK:
        if task_id not in JOBS:
            restored = restore_job_from_task(task_id)
            if restored:
                JOBS[task_id] = restored
        return job_service.job_status(job_runtime(), task_id)


def cancel_job(task_id: str) -> dict:
    with JOB_LOCK:
        if task_id not in JOBS:
            restored = restore_job_from_task(task_id)
            if restored:
                JOBS[task_id] = restored
        return job_service.cancel_job(job_runtime(), task_id)


def monitor_active_jobs() -> dict:
    """Poll persisted active tasks so status survives browser/session loss.

    A failed RunPod status lookup is isolated to the affected task.  The next
    monitor cycle retries it rather than changing a task to failed merely
    because the status API had a transient error.
    """
    dispatch = dispatch_next_queued_job()
    task_ids = active_task_ids()
    failures: list[str] = []
    for task_id in task_ids:
        try:
            job_status(task_id)
        except Exception:
            failures.append(task_id)
    return {"checked": len(task_ids), "failures": failures, "dispatch": dispatch}


def job_prompts(task_id: str) -> list[dict]:
    return task_prompts(task_id)


def update_job_prompt_quality(task_id: str, segment_index: int, payload: dict) -> dict:
    return update_task_prompt_quality(task_id, segment_index, payload)


def update_job_prompt_review(task_id: str, segment_index: int, payload: dict) -> dict:
    return update_task_prompt_review(task_id, segment_index, payload)


def reusable_prompts(
    *,
    keyword: str = "",
    workflow_id: str = "",
    min_rating: int | None = None,
    reviewed_only: bool = False,
    reuse_eligible: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    return reusable_task_prompts(
        keyword=keyword,
        workflow_id=workflow_id,
        min_rating=min_rating,
        reviewed_only=reviewed_only,
        reuse_eligible=reuse_eligible,
        page=page,
        page_size=page_size,
    )


def report_markdown(payload: dict) -> str:
    item = payload.get("historyItem") or payload.get("snapshot") or {}
    segments = item.get("segments") if isinstance(item.get("segments"), list) else []
    config = item.get("configJson") or item.get("config") or {}
    wan_node_config = item.get("wanNodeConfig") or {}
    if segments:
        config = segments[0].get("config") or config

    created_at = timestamp_pair(utc_now(), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="report")
    lines = [
        "# DOBEDUB STUDIO 작업 리포트",
        "",
        f"- 생성일시: {created_at['kst']} / UTC {created_at['utc']}",
        f"- Task ID: {item.get('taskId', '-')}",
        f"- Workflow: {item.get('workflowId') or item.get('workflow') or item.get('workflowName') or '-'}",
        f"- Status: {item.get('status', '-')}",
        f"- FPS: {config.get('fps') or item.get('fps') or '-'}",
        f"- Applied Seed: {item.get('generationSeed') or config.get('seed') or item.get('seed') or '-'}",
        f"- Segments: {item.get('segmentCount') or len(segments) or item.get('segments') or '-'}",
        "",
        "## Prompt",
        "",
        item.get("positivePrompt") or item.get("prompt") or "-",
        "",
        "## Negative Prompt",
        "",
        item.get("negativePrompt") or "-",
        "",
        "## Node Config",
        "",
        "```json",
        json.dumps(wan_node_config or config, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines) + "\n"


def create_report(payload: dict) -> dict:
    created_at = utc_now()
    report_id = f"report_{created_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    markdown = report_markdown(payload)
    reports_dir = data_paths()["reports"]
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report_id}.md"
    path.write_text(markdown, encoding="utf-8")
    return {
        "reportId": report_id,
        "downloadUrl": f"/api/reports/{report_id}",
        "markdown": markdown,
        **timestamp_fields("createdAt", created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="report"),
    }


def report_path(report_id: str) -> Path:
    path = data_paths()["reports"] / f"{Path(report_id).name}.md"
    if not path.exists():
        raise FileNotFoundError(report_id)
    return path
