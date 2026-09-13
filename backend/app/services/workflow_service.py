from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.services.segment_defaults_loader import get_workflow_segment_defaults
from backend.app.services.workflow_parser import (
    list_workflows as parse_workflow_list,
    workflow_schema as parse_workflow_schema,
)
from backend.app.services.workflow_visibility import is_retired_workflow


def bundled_segment_defaults_path(settings):
    return settings.project_root / "data" / "segment-defaults.json"


def list_workflows() -> list[dict]:
    settings = get_settings()
    from backend.app.services.admin_service import is_workflow_active

    return [
        workflow
        for workflow in parse_workflow_list(settings.workflows_dir)
        if not is_retired_workflow(workflow.get("id"))
        and is_workflow_active(str(workflow.get("id") or ""))
    ]


def get_workflow_schema(workflow_id: str) -> dict:
    settings = get_settings()
    return parse_workflow_schema(workflow_id, settings.workflows_dir)


def get_segment_defaults(workflow_id: str) -> dict:
    settings = get_settings()
    return get_workflow_segment_defaults(workflow_id, settings.data_dir, bundled_segment_defaults_path(settings))
