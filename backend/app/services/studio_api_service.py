from __future__ import annotations

import base64
import json
import mimetypes
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath
from threading import RLock

from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, timestamp_pair, utc_now
from backend.app.repositories.factory import data_paths, history_repository, studio_repository
from backend.app.services import job_service, output_service, workflow_patch_service, workflow_service
from backend.app.db.models import Asset, ImagePromptDraft, RunpodRequestBatch, RunpodRequestItem, User, WorkflowTask
from backend.app.services.asset_storage import decode_data_url, encode_file_base64, image_dimensions, safe_filename
from backend.app.services.runpod_client import connection_status as runpod_connection_status
from backend.app.services.runpod_client import runpod_request as runpod_client_request
from backend.app.services.storage_backends import S3AssetStorage
from backend.app.services.task_tracking_service import (
    active_task_ids,
    assets_total,
    list_assets,
    record_job_status,
    requeue_task_for_rework,
    restore_existing_job_for_prompt_draft,
    restore_job_from_task,
    reusable_task_prompts,
    task_history_items,
    task_history_stats,
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
DEFAULT_REQUESTED_FRAMES = 81
DEFAULT_WORKFLOW_FPS = 16


def _workflow_default_fps(workflow_id: str) -> int:
    fps = DEFAULT_WORKFLOW_FPS
    try:
        schema = workflow_service.get_workflow_schema(workflow_id)
    except Exception:
        return fps
    for segment in schema.get("segments") or []:
        for control in segment.get("configControls") or []:
            if str(control.get("key")) not in {"output_fps", "fps"}:
                continue
            candidate = control.get("default")
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) and candidate > 0:
                return int(candidate)
    return fps


def _video_config_from_requested_frames(workflow_id: str, requested_frames: int | None) -> dict[str, int]:
    try:
        frames = int(requested_frames or DEFAULT_REQUESTED_FRAMES)
    except (TypeError, ValueError):
        frames = DEFAULT_REQUESTED_FRAMES
    frames = max(1, frames)
    fps = _workflow_default_fps(workflow_id)
    duration_seconds = max(1, round(frames / fps))
    return {
        "frames": frames,
        "frame_count": frames,
        "length": frames,
        "duration": duration_seconds,
        "duration_seconds": duration_seconds,
        "fps": fps,
        "output_fps": fps,
    }


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
    """Return the dedicated RunPod-history contract with its fixed 10-row page."""
    run_date = str(run_date or "").strip()
    response = paginated_history(
        page,
        10,
        workflow_id=workflow_id,
        result_status=result_status,
        worker_id=worker_id,
        date_from=run_date,
        date_to=run_date,
        batch_job_id=batch_job_id,
    )
    response["stats"] = task_history_stats(
        workflow_id=workflow_id,
        result_status=result_status,
        worker_id=worker_id,
        date_from=run_date,
        date_to=run_date,
        batch_job_id=batch_job_id,
    )
    return response


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
    settings = get_settings()
    if settings.storage_backend == "s3" and settings.persistence_backend == "db":
        return _create_s3_upload_from_data_url(payload)
    with studio_repository() as repository:
        return repository.create_upload(payload)


def _create_s3_upload_from_data_url(payload: dict) -> dict:
    settings = get_settings()
    file_name = safe_filename(str(payload.get("fileName") or "upload.bin"))
    raw, decoded_mime_type = decode_data_url(payload.get("dataUrl", ""))
    if len(raw) == 0:
        raise ValueError("uploaded file is empty")
    mime_type = str(payload.get("mimeType") or decoded_mime_type or "application/octet-stream").strip() or "application/octet-stream"
    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    stored = s3_asset_storage().save_bytes(
        f"uploads/{asset_id}/{file_name}",
        raw,
        file_name=file_name,
        mime_type=mime_type,
    )
    image_width, image_height = image_dimensions(raw, mime_type)
    metadata = {
        "createdBy": payload.get("createdBy") or None,
        "downloadUrl": f"/api/files/{asset_id}",
        **timestamp_fields(
            "createdAt",
            utc_now(),
            naive_timezone=UTC_TIMEZONE,
            source_timezone="UTC",
            source="s3-upload",
        ),
    }
    if image_width and image_height:
        metadata["imageWidth"] = image_width
        metadata["imageHeight"] = image_height

    session = SessionLocal()
    try:
        asset = Asset(id=asset_id, created_at=utc_now().replace(tzinfo=None))
        asset.asset_type = "input_image"
        asset.file_name = file_name
        asset.mime_type = stored.mime_type
        asset.size_bytes = stored.size_bytes
        asset.storage_backend = "s3"
        asset.storage_key = stored.storage_key
        asset.public_url = stored.public_url or f"s3://{settings.s3_bucket}/{stored.storage_key}"
        asset.metadata_json = metadata
        session.add(asset)
        session.commit()
    finally:
        session.close()

    item = {
        "assetId": asset_id,
        "type": "input_image",
        "fileName": file_name,
        "mimeType": stored.mime_type,
        "sizeBytes": stored.size_bytes,
        "storageBackend": "s3",
        "storageKey": stored.storage_key,
        "publicUrl": stored.public_url or f"s3://{settings.s3_bucket}/{stored.storage_key}",
        "downloadUrl": f"/api/files/{asset_id}",
    }
    if image_width and image_height:
        item["imageWidth"] = image_width
        item["imageHeight"] = image_height
    return item


def create_s3_input_asset_from_bytes(
    *,
    raw: bytes,
    file_name: str,
    mime_type: str,
    batch_job_id: str,
    request_item_id: str,
    created_by: str | None = None,
    metadata: dict | None = None,
) -> dict:
    settings = get_settings()
    if settings.storage_backend != "s3" or settings.persistence_backend != "db":
        raise ValueError("STORAGE_BACKEND=s3 and PERSISTENCE_BACKEND=db are required for S3 input assets")
    safe_name = safe_filename(file_name)
    normalized_batch_id = str(batch_job_id or "").strip()
    normalized_item_id = str(request_item_id or "").strip()
    if not normalized_batch_id or not normalized_item_id:
        raise ValueError("batchJobId and requestItemId are required for S3 input assets")
    if not raw:
        raise ValueError("uploaded file is empty")
    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    stored = s3_asset_storage().save_bytes(
        f"batches/{normalized_batch_id}/items/{normalized_item_id}/inputs/{asset_id}/{safe_name}",
        raw,
        file_name=safe_name,
        mime_type=mime_type,
    )
    image_width, image_height = image_dimensions(raw, stored.mime_type)
    asset_metadata = {
        "createdBy": created_by or None,
        "batchJobId": normalized_batch_id,
        "requestItemId": normalized_item_id,
        "downloadUrl": f"/api/files/{asset_id}",
        **(metadata or {}),
        **timestamp_fields(
            "createdAt",
            utc_now(),
            naive_timezone=UTC_TIMEZONE,
            source_timezone="UTC",
            source="s3-batch-input",
        ),
    }
    if image_width and image_height:
        asset_metadata["imageWidth"] = image_width
        asset_metadata["imageHeight"] = image_height

    session = SessionLocal()
    try:
        asset = Asset(id=asset_id, created_at=utc_now().replace(tzinfo=None))
        asset.asset_type = "input_image"
        asset.file_name = safe_name
        asset.mime_type = stored.mime_type
        asset.size_bytes = stored.size_bytes
        asset.image_width = image_width
        asset.image_height = image_height
        asset.storage_backend = "s3"
        asset.storage_key = stored.storage_key
        asset.public_url = stored.public_url or f"s3://{settings.s3_bucket}/{stored.storage_key}"
        asset.metadata_json = asset_metadata
        session.add(asset)
        session.commit()
    finally:
        session.close()

    result = {
        "assetId": asset_id,
        "type": "input_image",
        "fileName": safe_name,
        "mimeType": stored.mime_type,
        "sizeBytes": stored.size_bytes,
        "storageBackend": "s3",
        "storageKey": stored.storage_key,
        "publicUrl": stored.public_url or f"s3://{settings.s3_bucket}/{stored.storage_key}",
        "downloadUrl": f"/api/files/{asset_id}",
    }
    if image_width and image_height:
        result["imageWidth"] = image_width
        result["imageHeight"] = image_height
    return result


def s3_asset_storage() -> S3AssetStorage:
    settings = get_settings()
    return S3AssetStorage(
        bucket=settings.s3_bucket,
        prefix=settings.s3_prefix,
        endpoint_url=settings.s3_endpoint_url,
        force_path_style=settings.s3_force_path_style,
    )


def create_s3_upload_presign(payload: dict, *, created_by: str) -> dict:
    settings = get_settings()
    if settings.storage_backend != "s3":
        raise ValueError("STORAGE_BACKEND=s3 is required for S3 upload presign")
    file_name = safe_filename(str(payload.get("fileName") or "upload.bin"))
    mime_type = str(payload.get("mimeType") or "application/octet-stream").strip() or "application/octet-stream"
    asset_id = str(payload.get("assetId") or f"asset_{uuid.uuid4().hex[:12]}")
    key = _s3_input_key(payload, asset_id=asset_id, file_name=file_name)
    storage = s3_asset_storage()
    storage_key = storage._key(key)
    expires_in = 900
    return {
        "assetId": asset_id,
        "fileName": file_name,
        "mimeType": mime_type,
        "storageBackend": "s3",
        "storageKey": storage_key,
        "uploadUrl": storage.presigned_put(key, content_type=mime_type, expires_in=expires_in),
        "headers": {"Content-Type": mime_type},
        "expiresAt": (utc_now() + timedelta(seconds=expires_in)).isoformat(),
    }


def complete_s3_upload(payload: dict, *, created_by: str) -> dict:
    settings = get_settings()
    if settings.storage_backend != "s3":
        raise ValueError("STORAGE_BACKEND=s3 is required for S3 upload completion")
    asset_id = str(payload.get("assetId") or "").strip()
    storage_key = str(payload.get("storageKey") or "").strip().lstrip("/")
    if not asset_id or not storage_key:
        raise ValueError("assetId and storageKey are required")
    expected_key = s3_asset_storage()._key(_s3_input_key(payload, asset_id=asset_id, file_name=safe_filename(str(payload.get("fileName") or "upload.bin"))))
    if storage_key != expected_key:
        raise ValueError("storageKey does not match the request item scope")
    stored = s3_asset_storage().stat(storage_key)
    requested_size = payload.get("sizeBytes")
    if requested_size is not None and int(requested_size) != stored.size_bytes:
        raise ValueError("uploaded object size does not match sizeBytes")
    file_name = safe_filename(str(payload.get("fileName") or stored.file_name))
    mime_type = str(payload.get("mimeType") or stored.mime_type or "application/octet-stream")
    metadata = _s3_scope_metadata(payload)
    metadata["createdBy"] = created_by
    session = SessionLocal()
    try:
        asset = session.get(Asset, asset_id)
        if asset is None:
            asset = Asset(id=asset_id, created_at=utc_now().replace(tzinfo=None))
            session.add(asset)
        asset.asset_type = "input_image"
        asset.file_name = file_name
        asset.mime_type = mime_type
        asset.size_bytes = stored.size_bytes
        asset.storage_backend = "s3"
        asset.storage_key = storage_key
        asset.public_url = f"s3://{settings.s3_bucket}/{storage_key}"
        asset.metadata_json = metadata
        session.commit()
        return {
            "assetId": asset.id,
            "type": asset.asset_type,
            "fileName": asset.file_name,
            "mimeType": asset.mime_type,
            "sizeBytes": asset.size_bytes,
            "storageBackend": asset.storage_backend,
            "storageKey": asset.storage_key,
            "publicUrl": asset.public_url,
            "downloadUrl": f"/api/files/{asset.id}",
        }
    finally:
        session.close()


def s3_asset_download(asset_id: str, *, include_url: bool = True) -> dict | None:
    if get_settings().persistence_backend != "db":
        return None
    session = SessionLocal()
    try:
        asset = session.get(Asset, asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if asset.storage_backend != "s3":
            return None
        item = {
            "assetId": asset.id,
            "fileName": asset.file_name,
            "mimeType": asset.mime_type,
            "sizeBytes": asset.size_bytes,
            "storageKey": asset.storage_key,
            "metadata": asset.metadata_json or {},
        }
        if include_url:
            item["url"] = s3_asset_storage().presigned_url(asset.storage_key, expires_in=900)
        return item
    finally:
        session.close()


def _s3_input_key(payload: dict, *, asset_id: str, file_name: str) -> str:
    scope = _s3_scope_metadata(payload)
    if not scope.get("requestBatchId") and not scope.get("batchJobId"):
        raise ValueError("requestBatchId or batchJobId is required for S3 upload scope")
    if not scope.get("requestItemId") or not scope.get("jobId"):
        raise ValueError("requestItemId and jobId are required for S3 upload scope")
    if scope.get("batchJobId"):
        return (
            f"batches/{scope['batchJobId']}/items/{scope['requestItemId']}/"
            f"jobs/{scope['jobId']}/inputs/{asset_id}/{file_name}"
        )
    return (
        f"request-batches/{scope['requestBatchId']}/items/{scope['requestItemId']}/"
        f"jobs/{scope['jobId']}/inputs/{asset_id}/{file_name}"
    )


def _s3_scope_metadata(payload: dict) -> dict[str, str]:
    request_batch_id = str(payload.get("requestBatchId") or "").strip()
    batch_job_id = str(payload.get("batchJobId") or "").strip()
    request_item_id = str(payload.get("requestItemId") or "").strip()
    job_id = str(payload.get("jobId") or payload.get("taskId") or "").strip()
    prompt_batch_id = str(payload.get("promptBatchId") or "").strip()
    if not request_batch_id and not batch_job_id and not job_id:
        raise ValueError("requestBatchId, batchJobId, or jobId is required for S3 upload scope")
    if request_batch_id and (not request_item_id or not job_id):
        raise ValueError("requestItemId and jobId are required for S3 upload scope")
    if batch_job_id and not job_id:
        raise ValueError("jobId is required for batch S3 upload scope")
    if job_id and not request_item_id:
        # Folder batches deliberately do not create RunPod request items. Their
        # task id already makes the S3 path unique, so use a storage-only item
        # token without adding a fake request_item_id to the DB relationship.
        request_item_id = "item_0001"
    metadata = {
        "requestItemId": request_item_id,
        "jobId": job_id,
    }
    if request_batch_id:
        metadata["requestBatchId"] = request_batch_id
    if batch_job_id:
        metadata["batchJobId"] = batch_job_id
    if prompt_batch_id:
        metadata["promptBatchId"] = prompt_batch_id
    return metadata


def get_asset(asset_id: str) -> tuple[dict, Path]:
    with studio_repository() as repository:
        return repository.get_asset(asset_id)


def read_asset_bytes(asset_id: str) -> tuple[dict, bytes]:
    try:
        asset = asset_metadata(asset_id)
    except KeyError:
        asset = {}
    if asset.get("storageBackend") == "s3" and asset.get("storageKey"):
        with s3_asset_storage().open_read(str(asset["storageKey"])) as stream:
            return asset, stream.read()

    asset, path = get_asset(asset_id)
    return asset, path.read_bytes()


def asset_metadata(asset_id: str) -> dict:
    session = SessionLocal()
    try:
        asset = session.get(Asset, asset_id)
        if asset is None:
            raise KeyError(asset_id)
        return {
            "assetId": asset.id,
            "type": asset.asset_type,
            "fileName": asset.file_name,
            "mimeType": asset.mime_type,
            "sizeBytes": asset.size_bytes,
            "storageBackend": asset.storage_backend,
            "storageKey": asset.storage_key,
            "publicUrl": asset.public_url,
            **(asset.metadata_json or {}),
        }
    finally:
        session.close()


def register_asset(file_path: Path, asset_type: str, mime_type: str | None = None, file_name: str | None = None) -> dict:
    with studio_repository() as repository:
        return repository.register_asset(Path(file_path), asset_type, mime_type, file_name)


def hydrate_input_images(item: dict) -> list[dict]:
    with studio_repository() as repository:
        return repository.hydrate_input_images(item)


def asset_to_runpod_image(asset_id: str, fallback_name: str | None = None) -> dict:
    if get_settings().storage_backend == "s3":
        try:
            asset = asset_metadata(asset_id)
        except KeyError:
            asset = {}
        if asset.get("storageBackend") == "s3" and asset.get("storageKey"):
            settings = get_settings()
            return {
                "assetId": asset_id,
                "name": safe_filename(str(asset.get("fileName") or fallback_name or asset_id)),
                "s3Uri": f"s3://{settings.s3_bucket}/{asset['storageKey']}",
            }
    asset, path = get_asset(asset_id)
    return {
        "assetId": asset_id,
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


def build_runpod_payload(workflow: dict, images: list[dict], job_scope: dict | None = None) -> dict:
    input_body = {"workflow": workflow}
    if images:
        input_body["images"] = [_runpod_image_payload(image) for image in images]
    output_destination = _runpod_s3_output_destination(job_scope or {})
    if output_destination:
        input_body["output"] = output_destination
    return {"input": input_body}


def _runpod_image_payload(image: dict) -> dict:
    if image.get("s3Uri"):
        return {
            "assetId": image.get("assetId"),
            "name": image["name"],
            "s3Uri": image["s3Uri"],
        }
    return {"name": image["name"], "image": encode_file_base64(Path(image["path"]))}


def _runpod_s3_output_destination(job_scope: dict) -> dict | None:
    settings = get_settings()
    if settings.storage_backend != "s3":
        return None
    try:
        output_prefix = _s3_job_storage_key(job_scope, "outputs")
        manifest_key = _s3_job_storage_key(job_scope, "manifests/runpod-result.json")
    except ValueError:
        return None
    return {
        "mode": "s3",
        "bucket": settings.s3_bucket,
        "prefix": output_prefix,
        "manifestKey": manifest_key,
        "appJobId": str(job_scope.get("taskId") or job_scope.get("jobId") or "").strip(),
    }


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
    result = _result_with_s3_manifest_outputs(result, job)
    result = _result_with_inline_outputs_stored_to_s3(result, job)
    return output_service.save_runpod_outputs(result, job, data_paths()["outputs"], register_asset)


def _result_with_inline_outputs_stored_to_s3(result: dict, job: dict) -> dict:
    if get_settings().storage_backend != "s3":
        return result
    output = (result or {}).get("output") or {}
    output_items: list[tuple[str, dict]] = []
    for kind in ("videos", "images", "gifs"):
        for item in output.get(kind) or []:
            if isinstance(item, dict):
                output_items.append((kind, item))
    if not output_items:
        return result

    converted = {"videos": [], "images": [], "gifs": []}
    total = len(output_items)
    changed = False
    for index, (kind, item) in enumerate(output_items, start=1):
        if item.get("type") == "s3_object":
            converted[kind].append(item)
            continue
        data = item.get("data")
        if not data:
            converted[kind].append(item)
            continue
        metadata = output_service.infer_output_metadata(item, index, total, job)
        file_name = output_service.output_file_name(kind, item, index, job, metadata, total)
        raw = base64.b64decode(data)
        asset_id = str(item.get("assetId") or f"asset_{uuid.uuid4().hex[:12]}")
        mime_type = str(item.get("mimeType") or mimetypes.guess_type(file_name)[0] or "application/octet-stream")
        storage_key = _s3_job_storage_key({**(job.get("payload") or {}), "taskId": job.get("taskId")}, f"outputs/{asset_id}/{file_name}")
        stored = s3_asset_storage().save_bytes(
            storage_key.removeprefix(f"{get_settings().s3_prefix.strip('/')}/") if get_settings().s3_prefix.strip("/") and storage_key.startswith(f"{get_settings().s3_prefix.strip('/')}/") else storage_key,
            raw,
            file_name=file_name,
            mime_type=mime_type,
        )
        converted[_manifest_output_kind({"filename": file_name, "mimeType": mime_type})].append({
            "type": "s3_object",
            "assetId": asset_id,
            "bucket": stored.bucket or get_settings().s3_bucket,
            "key": stored.storage_key,
            "filename": file_name,
            "mimeType": stored.mime_type,
            "sizeBytes": stored.size_bytes,
            "node_id": item.get("node_id") or item.get("nodeId") or item.get("node"),
        })
        changed = True

    if not changed:
        return result
    enriched = dict(result)
    enriched["output"] = converted
    return enriched


def _result_with_s3_manifest_outputs(result: dict, job: dict) -> dict:
    if get_settings().storage_backend != "s3" or _has_inline_runpod_outputs(result):
        return result
    try:
        manifest_key = _s3_job_storage_key({**(job.get("payload") or {}), "taskId": job.get("taskId")}, "manifests/runpod-result.json")
        storage = s3_asset_storage()
        with storage.open_read(manifest_key) as stream:
            raw = stream.read()
    except Exception:
        return result
    manifest = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    output = {"videos": [], "images": [], "gifs": []}
    items = [item for item in manifest.get("outputs") or [] if isinstance(item, dict)]
    total = len(items)
    for index, item in enumerate(items, start=1):
        normalized = _manifest_output_item(item)
        if not normalized:
            continue
        kind = _manifest_output_kind(normalized)
        metadata = output_service.infer_output_metadata(normalized, index, total, job)
        desired_file_name = output_service.output_file_name(kind, normalized, index, job, metadata, total)
        normalized = _manifest_output_with_source_filename(storage, normalized, desired_file_name)
        output[_manifest_output_kind(normalized)].append(normalized)
    if not any(output.values()):
        return result
    enriched = dict(result)
    enriched["output"] = output
    return enriched


def _has_inline_runpod_outputs(result: dict) -> bool:
    output = (result or {}).get("output") or {}
    return any(output.get(kind) for kind in ("videos", "images", "gifs"))


def _manifest_output_item(item: dict) -> dict | None:
    storage_key = str(item.get("key") or item.get("storageKey") or "").strip().lstrip("/")
    if not storage_key:
        return None
    mime_type = str(item.get("mimeType") or item.get("contentType") or "application/octet-stream")
    file_name = safe_filename(str(item.get("filename") or item.get("fileName") or Path(storage_key).name))
    return {
        "type": "s3_object",
        "assetId": str(item.get("assetId") or f"asset_{uuid.uuid4().hex[:12]}"),
        "bucket": str(item.get("bucket") or get_settings().s3_bucket),
        "key": storage_key,
        "filename": file_name,
        "mimeType": mime_type,
        "sizeBytes": int(item.get("sizeBytes") or 0),
        "node_id": item.get("node_id") or item.get("nodeId") or item.get("node"),
    }


def _manifest_output_with_source_filename(storage: S3AssetStorage, item: dict, file_name: str) -> dict:
    safe_name = PurePosixPath(str(file_name or "")).name
    if not safe_name:
        return item
    storage_key = str(item.get("key") or "").strip().lstrip("/")
    if not storage_key:
        return item
    target_key = str(PurePosixPath(storage_key).with_name(safe_name))
    if target_key == storage_key and item.get("filename") == safe_name:
        return item
    stored = storage.copy_stored_object(storage_key, target_key)
    return {
        **item,
        "key": stored.storage_key,
        "filename": safe_name,
        "mimeType": item.get("mimeType") or stored.mime_type,
        "sizeBytes": int(item.get("sizeBytes") or stored.size_bytes or 0),
    }


def _manifest_output_kind(item: dict) -> str:
    mime_type = str(item.get("mimeType") or "")
    suffix = Path(str(item.get("filename") or item.get("key") or "")).suffix.lower()
    if mime_type.startswith("video/") or suffix in output_service.VIDEO_SUFFIXES:
        return "videos"
    if mime_type.startswith("image/gif") or suffix == ".gif":
        return "gifs"
    return "images"


def _s3_job_storage_key(job_scope: dict, leaf: str) -> str:
    scope = _s3_scope_metadata(job_scope)
    if scope.get("batchJobId"):
        suffix = (
            f"batches/{scope['batchJobId']}/items/{scope['requestItemId']}/"
            f"jobs/{scope['jobId']}/{leaf.strip('/')}"
        )
    elif not scope.get("requestBatchId"):
        suffix = (
            f"jobs/{scope['jobId']}/items/{scope['requestItemId']}/"
            f"{leaf.strip('/')}"
        )
    else:
        suffix = (
            f"request-batches/{scope['requestBatchId']}/items/{scope['requestItemId']}/"
            f"jobs/{scope['jobId']}/{leaf.strip('/')}"
        )
    prefix = get_settings().s3_prefix.strip("/")
    return f"{prefix}/{suffix}" if prefix else suffix


def build_wan_node_config_snapshot(workflow_id: str, segments_payload: list[dict]) -> dict:
    resolution_tier = "sd"
    for segment in segments_payload or []:
        config = segment.get("config") if isinstance(segment, dict) else {}
        if isinstance(config, dict) and config.get("resolutionTier"):
            resolution_tier = str(config.get("resolutionTier"))
            break
    return workflow_patch_service.build_wan_node_config_snapshot(
        workflow_id,
        segments_payload,
        get_settings().workflows_dir,
        resolution_tier,
    )


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
        existing_job = restore_existing_job_for_prompt_draft(
            str(safe_payload.get("promptDraftId") or ""),
            batch_job_id=str(safe_payload.get("batchJobId") or "").strip() or None,
        )
        if existing_job:
            JOBS[existing_job["taskId"]] = existing_job
            return existing_job
        return job_service.queue_job(job_runtime(), safe_payload)


def rework_history_item(task_id: str, *, user: dict[str, object]) -> dict:
    user_id = str(user.get("id") or "").strip()
    permissions = {str(permission) for permission in user.get("permissions") or []}
    can_manage = "admin:*" in permissions or "jobs:manage" in permissions
    job = requeue_task_for_rework(task_id, actor_id=user_id, can_manage=can_manage)
    with JOB_LOCK:
        JOBS[task_id] = job
    return job


def regenerate_history_item(task_id: str, *, user: dict[str, object]) -> dict:
    """Backward-compatible alias for the renamed RunPod rework operation."""
    return rework_history_item(task_id, user=user)


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
        # Draft-based jobs are submitted outside the legacy workspace form.
        # Carry the persisted source dimensions so the Wan node receives the
        # exact uploaded image size, just as it does for a direct submission.
        config = _video_config_from_requested_frames(draft.workflow_id, draft.requested_frames)
        if asset.image_width and int(asset.image_width) > 0:
            config["width"] = int(asset.image_width)
        if asset.image_height and int(asset.image_height) > 0:
            config["height"] = int(asset.image_height)
        raw_metadata = draft.raw_json if isinstance(draft.raw_json, dict) else {}
        return {
            "workflowId": draft.workflow_id,
            # The job history must show the registered workflow label rather
            # than the JSON filename. The parser uses the filename stem as the
            # stable display name for registered workflows.
            "workflowName": Path(draft.workflow_id).stem,
            "promptDraftId": draft.id,
            "requestItemId": str(raw_metadata.get("requestItemId") or "").strip() or None,
            "resolutionTier": "sd",
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
        config = _video_config_from_requested_frames(item.workflow_id, item.requested_frames)
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
            "resolutionTier": workflow_patch_service.normalize_resolution_tier(getattr(item, "resolution_tier", None)),
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
        except Exception as exc:
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
