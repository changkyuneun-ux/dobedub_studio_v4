"""Migrate local media assets to S3 without changing task history semantics."""
from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import Asset, ImagePromptDraft, TaskInputAsset, TaskOutputAsset, WorkflowTask
from backend.app.services.asset_storage import safe_filename
from backend.app.services.studio_api_service import s3_asset_storage


MEDIA_ASSET_PREFIXES = ("input", "output")


@dataclass(frozen=True)
class MigrationResult:
    scanned: int
    migrated: int
    skipped: int
    missing: int
    errors: list[dict[str, str]]


def migrate_local_media_to_s3(
    db: Session,
    *,
    apply: bool = False,
    limit: int | None = None,
) -> MigrationResult:
    """Copy local input/output assets to S3 and update DB rows when apply=True."""
    query = (
        select(Asset)
        .where(Asset.storage_backend == "local")
        .order_by(Asset.created_at.asc(), Asset.id.asc())
    )
    if limit:
        query = query.limit(max(1, int(limit)))
    assets = [
        asset
        for asset in db.scalars(query).all()
        if _is_media_asset(asset)
    ]
    storage = s3_asset_storage() if apply else None
    migrated = 0
    skipped = 0
    missing = 0
    errors: list[dict[str, str]] = []
    for asset in assets:
        source_path = Path(str(asset.storage_key or ""))
        if not source_path.exists() or not source_path.is_file():
            missing += 1
            errors.append({"assetId": asset.id, "reason": "missing_local_file", "path": str(source_path)})
            continue
        try:
            target_key = _target_key_for_asset(db, asset)
            if apply and storage is not None:
                stored = storage.save_file(
                    _strip_configured_prefix(target_key),
                    source_path,
                    file_name=asset.file_name,
                    mime_type=asset.mime_type or mimetypes.guess_type(asset.file_name)[0] or "application/octet-stream",
                )
                asset.storage_backend = "s3"
                asset.storage_key = stored.storage_key
                asset.public_url = stored.public_url or f"s3://{get_settings().s3_bucket}/{stored.storage_key}"
                metadata = dict(asset.metadata_json or {})
                metadata["migratedFromStorageBackend"] = "local"
                metadata["migratedFromStorageKey"] = str(source_path)
                asset.metadata_json = metadata
            migrated += 1
        except Exception as exc:  # noqa: BLE001 - continue the batch and report per-asset failures
            skipped += 1
            errors.append({"assetId": asset.id, "reason": type(exc).__name__, "message": str(exc)})
    if apply:
        db.commit()
    return MigrationResult(
        scanned=len(assets),
        migrated=migrated,
        skipped=skipped,
        missing=missing,
        errors=errors,
    )


def migrate_s3_media_to_final_layout(
    db: Session,
    *,
    apply: bool = False,
    delete_source: bool = False,
    limit: int | None = None,
) -> MigrationResult:
    """Copy existing S3 media assets into the final batch-scoped S3 layout.

    This intentionally does not scan or migrate local/NFS-backed assets.  It is
    for correcting S3 objects that were already uploaded to legacy prefixes
    such as ``uploads/`` or top-level ``jobs/``.
    """
    query = (
        select(Asset)
        .where(Asset.storage_backend == "s3")
        .order_by(Asset.created_at.asc(), Asset.id.asc())
    )
    if limit:
        query = query.limit(max(1, int(limit)))
    assets = [
        asset
        for asset in db.scalars(query).all()
        if _is_media_asset(asset)
    ]
    plans: list[tuple[Asset, str]] = []
    skipped = 0
    missing = 0
    errors: list[dict[str, str]] = []

    for asset in assets:
        source_key = str(asset.storage_key or "").strip().lstrip("/")
        if not source_key:
            missing += 1
            errors.append({"assetId": asset.id, "reason": "missing_s3_key"})
            continue
        try:
            target_key = _final_s3_key_for_asset(db, asset)
        except ValueError as exc:
            skipped += 1
            errors.append({"assetId": asset.id, "reason": "missing_batch_scope", "message": str(exc)})
            continue
        if source_key == target_key or _is_final_batch_layout_key(source_key):
            skipped += 1
            continue
        plans.append((asset, target_key))

    storage = s3_asset_storage() if apply and plans else None
    migrated = 0
    for asset, target_key in plans:
        source_key = str(asset.storage_key or "").strip().lstrip("/")
        try:
            if apply and storage is not None:
                stored = storage.copy_stored_object(source_key, target_key)
                if delete_source:
                    storage.delete(source_key)
                metadata = dict(asset.metadata_json or {})
                metadata["migratedFromStorageBackend"] = "s3"
                metadata["migratedFromStorageKey"] = source_key
                asset.storage_key = stored.storage_key
                asset.public_url = stored.public_url or f"s3://{get_settings().s3_bucket}/{stored.storage_key}"
                asset.metadata_json = metadata
            migrated += 1
        except Exception as exc:  # noqa: BLE001 - continue the batch and report per-asset failures
            skipped += 1
            errors.append({"assetId": asset.id, "reason": type(exc).__name__, "message": str(exc)})

    if apply:
        db.commit()

    return MigrationResult(
        scanned=len(assets),
        migrated=migrated,
        skipped=skipped,
        missing=missing,
        errors=errors,
    )


def _is_media_asset(asset: Asset) -> bool:
    asset_type = str(asset.asset_type or "").lower()
    return any(asset_type.startswith(prefix) for prefix in MEDIA_ASSET_PREFIXES)


def _target_key_for_asset(db: Session, asset: Asset) -> str:
    input_task = _first_input_task(db, asset.id)
    if input_task is not None:
        return _task_scoped_key(db, input_task, "inputs", asset)
    output_task = _first_output_task(db, asset.id)
    if output_task is not None:
        return _task_scoped_key(db, output_task, "outputs", asset)
    return _prefixed(f"uploads/{asset.id}/{safe_filename(asset.file_name)}")


def _final_s3_key_for_asset(db: Session, asset: Asset) -> str:
    input_task = _first_input_task(db, asset.id)
    if input_task is not None:
        return _batch_scoped_key(db, input_task, "inputs", asset)
    output_task = _first_output_task(db, asset.id)
    if output_task is not None:
        return _batch_scoped_key(db, output_task, "outputs", asset)
    raise ValueError("asset is not linked to a workflow task")


def _first_input_task(db: Session, asset_id: str) -> WorkflowTask | None:
    return db.scalar(
        select(WorkflowTask)
        .join(TaskInputAsset, TaskInputAsset.task_id == WorkflowTask.id)
        .where(TaskInputAsset.asset_id == asset_id)
        .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
        .limit(1)
    )


def _first_output_task(db: Session, asset_id: str) -> WorkflowTask | None:
    return db.scalar(
        select(WorkflowTask)
        .join(TaskOutputAsset, TaskOutputAsset.task_id == WorkflowTask.id)
        .where(TaskOutputAsset.asset_id == asset_id)
        .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
        .limit(1)
    )


def _task_scoped_key(db: Session, task: WorkflowTask, leaf: str, asset: Asset) -> str:
    item_id = _task_item_id(db, task)
    file_name = safe_filename(asset.file_name)
    if task.batch_job_id:
        suffix = f"batches/{task.batch_job_id}/items/{item_id}/jobs/{task.id}/{leaf}/{asset.id}/{file_name}"
    elif task.request_batch_id:
        suffix = f"request-batches/{task.request_batch_id}/items/{item_id}/jobs/{task.id}/{leaf}/{asset.id}/{file_name}"
    else:
        suffix = f"jobs/{task.id}/items/{item_id}/{leaf}/{asset.id}/{file_name}"
    return _prefixed(suffix)


def _batch_scoped_key(db: Session, task: WorkflowTask, leaf: str, asset: Asset) -> str:
    item_id = _task_item_id(db, task)
    file_name = safe_filename(asset.file_name)
    if task.batch_job_id:
        suffix = f"batches/{task.batch_job_id}/items/{item_id}/jobs/{task.id}/{leaf}/{asset.id}/{file_name}"
    elif task.request_batch_id:
        suffix = f"request-batches/{task.request_batch_id}/items/{item_id}/jobs/{task.id}/{leaf}/{asset.id}/{file_name}"
    else:
        raise ValueError("task has no batchJobId or requestBatchId")
    return _prefixed(suffix)


def _is_final_batch_layout_key(storage_key: str) -> bool:
    key = _strip_configured_prefix(str(storage_key or "").strip().lstrip("/"))
    if not (
        key.startswith("request-batches/")
        or key.startswith("batches/")
    ):
        return False
    return "/items/" in key and "/jobs/" in key and ("/inputs/" in key or "/outputs/" in key or "/manifests/" in key)


def _task_item_id(db: Session, task: WorkflowTask) -> str:
    if task.request_item_id:
        return str(task.request_item_id)
    if task.prompt_draft_id:
        draft = db.get(ImagePromptDraft, task.prompt_draft_id)
        raw = draft.raw_json if draft is not None and isinstance(draft.raw_json, dict) else {}
        item_id = str(raw.get("requestItemId") or "").strip()
        if item_id:
            return item_id
    return "item_0001"


def _prefixed(suffix: str) -> str:
    prefix = get_settings().s3_prefix.strip("/")
    return f"{prefix}/{suffix.strip('/')}" if prefix else suffix.strip("/")


def _strip_configured_prefix(key: str) -> str:
    prefix = get_settings().s3_prefix.strip("/")
    if prefix and key.startswith(f"{prefix}/"):
        return key[len(prefix) + 1:]
    return key


__all__ = ["MigrationResult", "migrate_local_media_to_s3", "migrate_s3_media_to_final_layout"]
