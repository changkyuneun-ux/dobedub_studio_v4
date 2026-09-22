from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import WorkflowDefinition, WorkflowRevision
from backend.app.services.workflow_parser import generate_param_config
from backend.app.services.workflow_release_service import PreparedWorkflowRelease, prepare_release, write_release_files


@dataclass(frozen=True)
class WorkflowImportItem:
    workflow_id: str
    source: str
    status: str
    prepared: PreparedWorkflowRelease


@dataclass(frozen=True)
class WorkflowImportPlan:
    runtime_dir: Path
    items: tuple[WorkflowImportItem, ...]


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON file: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return value


def _legacy_registry(data_dir: Path) -> dict:
    path = data_dir / "workflow-registry.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value.get("items") if isinstance(value, dict) and isinstance(value.get("items"), dict) else {}


def plan_workflow_import(
    db: Session,
    workflows_dir: Path,
    seed_dir: Path,
    data_dir: Path,
) -> WorkflowImportPlan:
    del db  # Planning is deliberately read-only with respect to RDS.
    registry = _legacy_registry(data_dir)
    seed_names = {
        path.name
        for path in seed_dir.glob("*.json")
        if not path.name.endswith(".paramconfig.json")
    }
    items: list[WorkflowImportItem] = []
    for workflow_path in sorted(workflows_dir.glob("*.json")):
        if workflow_path.name.endswith(".paramconfig.json"):
            continue
        workflow_id = workflow_path.name
        workflow_json = _read_object(workflow_path)
        param_path = workflows_dir / f"{workflow_path.stem}.paramconfig.json"
        param_config = _read_object(param_path) if param_path.is_file() else generate_param_config(workflow_id, workflow_json)
        legacy = registry.get(workflow_id) if isinstance(registry.get(workflow_id), dict) else {}
        source = "BUNDLED" if workflow_id in seed_names else "LEGACY_IMPORT"
        status = "ACTIVE" if bool(legacy.get("active", source == "BUNDLED")) else "INACTIVE"
        items.append(
            WorkflowImportItem(
                workflow_id=workflow_id,
                source=source,
                status=status,
                prepared=prepare_release(workflow_id, workflow_json, param_config),
            )
        )
    return WorkflowImportPlan(runtime_dir=workflows_dir, items=tuple(items))


def apply_workflow_import(
    db: Session,
    plan: WorkflowImportPlan,
    actor_id: str | None = None,
) -> dict:
    created_definitions = 0
    created_revisions = 0
    for item in plan.items:
        definition = db.get(WorkflowDefinition, item.workflow_id)
        if definition is None:
            definition = WorkflowDefinition(
                id=item.workflow_id,
                display_name=Path(item.workflow_id).stem,
                status=item.status,
                source=item.source,
                registered_by=actor_id,
                updated_by=actor_id,
            )
            db.add(definition)
            db.flush()
            created_definitions += 1

        revision = db.scalar(
            select(WorkflowRevision).where(
                WorkflowRevision.workflow_id == item.workflow_id,
                WorkflowRevision.workflow_sha256 == item.prepared.workflow_sha256,
                WorkflowRevision.param_config_sha256 == item.prepared.param_config_sha256,
            )
        )
        if revision is None:
            revision_number = int(
                (db.scalar(select(func.max(WorkflowRevision.revision)).where(WorkflowRevision.workflow_id == item.workflow_id)) or 0) + 1
            )
            files = write_release_files(plan.runtime_dir, item.workflow_id, revision_number, item.prepared)
            revision = WorkflowRevision(
                workflow_id=item.workflow_id,
                revision=revision_number,
                workflow_path=files.workflow_path,
                workflow_sha256=item.prepared.workflow_sha256,
                workflow_size_bytes=len(item.prepared.workflow_bytes),
                param_config_path=files.param_config_path,
                param_config_sha256=item.prepared.param_config_sha256,
                param_config_size_bytes=len(item.prepared.param_config_bytes),
                validation_status="VALID",
                validation_json={**item.prepared.validation, "imported": True},
                node_count=item.prepared.node_count,
                input_image_count=item.prepared.input_image_count,
                segment_count=item.prepared.segment_count,
                created_by=actor_id,
            )
            db.add(revision)
            db.flush()
            created_revisions += 1

        if definition.current_revision_id is None and definition.status == "ACTIVE":
            definition.current_revision_id = revision.id
    db.commit()
    return {
        "planned": len(plan.items),
        "createdDefinitions": created_definitions,
        "createdRevisions": created_revisions,
    }
