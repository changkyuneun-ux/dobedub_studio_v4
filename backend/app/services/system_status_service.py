from __future__ import annotations

import os
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.services.metadata_service import get_metadata_status
from backend.app.services.prompt_llm_client import prompt_llm_status
from backend.app.services.runpod_client import mask_secret, runpod_is_configured
from backend.app.services.segment_defaults_loader import load_segment_defaults
from backend.app.services.workflow_parser import workflow_files
from backend.app.services.workflow_storage_service import workflow_store_status


def directory_status(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": path.exists(),
        "isDirectory": path.is_dir(),
        "writable": path.exists() and os.access(path, os.W_OK),
    }


def file_status(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": path.exists(),
        "isFile": path.is_file(),
    }


def workflow_inventory(workflows_dir: Path) -> dict:
    files = workflow_files(workflows_dir)
    return {
        "dir": str(workflows_dir),
        "exists": workflows_dir.exists(),
        "count": len(files),
        "items": [path.name for path in files],
    }


def segment_defaults_inventory(workflows: dict, data_dir: Path, bundled_defaults_path: Path) -> dict:
    defaults = load_segment_defaults(data_dir, bundled_defaults_path)
    workflow_items = workflows.get("items") or []
    missing = [workflow_id for workflow_id in workflow_items if workflow_id not in defaults]
    runtime_path = data_dir / "segment-defaults.json"
    return {
        "count": len(defaults),
        "workflowCount": len(workflow_items),
        "matchedCount": len(workflow_items) - len(missing),
        "missingWorkflows": missing,
        "bundledPath": file_status(bundled_defaults_path),
        "runtimePath": file_status(runtime_path),
    }


def system_status() -> dict:
    settings = get_settings()
    bundled_defaults_path = settings.project_root / "data" / "segment-defaults.json"
    workflows = workflow_inventory(settings.workflows_dir)
    data_dir = directory_status(settings.data_dir)
    outputs_dir = directory_status(settings.data_dir / "outputs")
    segment_defaults = segment_defaults_inventory(workflows, settings.data_dir, bundled_defaults_path)
    metadata = get_metadata_status()
    runpod_configured = runpod_is_configured(settings.runpod_api_key, settings.runpod_endpoint_id)
    ready = (
        workflows["exists"]
        and workflows["count"] > 0
        and segment_defaults["matchedCount"] == workflows["count"]
        and metadata.get("files", {}).get("workflowWidgetMap", {}).get("exists")
        and data_dir["writable"]
        and outputs_dir["writable"]
        and (settings.dry_run or runpod_configured)
    )
    return {
        "ok": bool(ready),
        **timestamp_fields("checkedAt", utc_now(), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="ecs-application"),
        "displayTimezone": "Asia/Seoul",
        "executionMode": "dry-run" if settings.dry_run else "runpod",
        "dryRun": settings.dry_run,
        "runpod": {
            "configured": runpod_configured,
            "endpointId": mask_secret(settings.runpod_endpoint_id),
            "baseUrl": settings.runpod_base_url,
        },
        "promptLlm": prompt_llm_status(settings),
        "workflows": workflows,
        "workflowStore": workflow_store_status(settings.workflow_seed_dir, settings.workflows_dir, settings.data_dir),
        "segmentDefaults": segment_defaults,
        "metadata": {
            "dir": metadata.get("metadataDir", str(settings.metadata_dir)),
            "exists": settings.metadata_dir.exists(),
            "manifest": file_status(settings.metadata_dir / "metadata-manifest.json"),
            "workflowWidgetMap": metadata.get("files", {}).get("workflowWidgetMap", file_status(settings.metadata_dir / "workflow-widget-map.json")),
            "models": metadata.get("files", {}).get("models", file_status(settings.metadata_dir / "comfyui-models.json")),
        },
        "database": {
            "persistenceBackend": settings.persistence_backend,
            "configured": bool(settings.database_url),
            "engine": settings.database_url.split(":", 1)[0] if settings.database_url else "",
            "url": mask_secret(settings.database_url),
            "migration": "alembic",
        },
        "assetStorage": {
            "backend": settings.storage_backend,
            "s3BucketConfigured": bool(settings.s3_bucket),
            "s3Prefix": settings.s3_prefix,
        },
        "storage": {
            "dataDir": data_dir,
            "outputsDir": outputs_dir,
        },
    }
