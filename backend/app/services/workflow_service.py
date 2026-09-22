from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.db.session import SessionLocal
from backend.app.services.segment_defaults_loader import get_workflow_segment_defaults
from backend.app.services.workflow_catalog_service import list_active_workflow_ids
from backend.app.services.workflow_parser import (
    list_workflows as parse_workflow_list,
    workflow_schema as parse_workflow_schema,
)
from backend.app.services.workflow_visibility import assert_workflow_selectable, canonical_workflow_id


def bundled_segment_defaults_path(settings):
    return settings.project_root / "data" / "segment-defaults.json"


def list_workflows() -> list[dict]:
    settings = get_settings()
    seed_dir = getattr(settings, "workflow_seed_dir", None)
    with SessionLocal() as db:
        active_ids = set(list_active_workflow_ids(db))
    return [
        workflow
        for workflow in parse_workflow_list(settings.workflows_dir)
        if canonical_workflow_id(workflow.get("id")) in active_ids
        or (seed_dir is not None and (seed_dir / canonical_workflow_id(workflow.get("id"))).is_file())
    ]


def get_workflow_schema(workflow_id: str) -> dict:
    settings = get_settings()
    canonical_id = assert_workflow_selectable(workflow_id)
    return parse_workflow_schema(canonical_id, settings.workflows_dir)


def get_segment_defaults(workflow_id: str) -> dict:
    settings = get_settings()
    return get_workflow_segment_defaults(workflow_id, settings.data_dir, bundled_segment_defaults_path(settings))
