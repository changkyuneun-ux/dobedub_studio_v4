from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.security import create_access_token, ensure_admin_user, hash_password, normalize_permissions, normalize_role, user_payload
from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import User
from backend.app.services.metadata_loader import ensure_metadata_current, read_json_if_exists
from backend.app.services.metadata_service import metadata_paths
from backend.app.services.permission_service import (
    permission_governance_catalog,
    role_permission_code_map,
    user_permission_payload,
    user_permission_payloads,
)
from backend.app.services.workflow_parser import (
    generate_param_config,
    list_workflows as parse_workflow_list,
    workflow_schema as parse_workflow_schema,
)


WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\.json$")


def list_admin_users(session: Session) -> dict:
    ensure_admin_user(session)
    users = session.scalars(select(User).order_by(User.created_at.desc(), User.id)).all()
    role_permissions = role_permission_code_map(session)
    permission_payloads = user_permission_payloads(session, users, role_permissions=role_permissions)
    items = [{**user_payload(user), **permission_payloads.get(user.id, {})} for user in users]
    return {
        "items": items,
        "permissionGovernance": permission_governance_catalog(session, role_permissions=role_permissions),
    }


def list_permission_governance(session: Session) -> dict:
    ensure_admin_user(session)
    return permission_governance_catalog(session)


def admin_user_payload(session: Session, user: User) -> dict:
    payload = user_payload(user)
    payload.update(user_permission_payload(session, user))
    return payload


def upsert_admin_user(session: Session, payload: dict, user_id: str | None = None) -> dict:
    target_id = str(user_id or payload.get("id") or "").strip()
    if not target_id:
        raise ValueError("id is required")
    user = session.get(User, target_id)
    if not user:
        user = User(id=target_id, name=str(payload.get("name") or target_id).strip())
        session.add(user)
    user.name = str(payload.get("name") or user.name or target_id).strip()
    user.email = _optional_string(payload.get("email"))
    user.role = normalize_role(str(payload.get("role") or user.role or "OPERATOR"))
    user.permissions_json = normalize_permissions(payload.get("permissions"))
    next_is_active = _payload_bool(payload.get("isActive", True))
    if user.id == "dobedub" and not next_is_active:
        raise ValueError("Default super admin cannot be deactivated")
    user.is_active = next_is_active
    password = str(payload.get("password") or "").strip()
    if password:
        user.password_hash = hash_password(password)
    user.updated_at = utc_now().replace(tzinfo=None)
    session.commit()
    return {"user": admin_user_payload(session, user), **list_admin_users(session)}


def deactivate_admin_user(session: Session, user_id: str) -> dict:
    user = session.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    if user.id == "dobedub":
        raise ValueError("Default super admin cannot be deactivated")
    user.is_active = False
    user.updated_at = utc_now().replace(tzinfo=None)
    session.commit()
    return list_admin_users(session)


def reset_admin_user_password(session: Session, user_id: str, password: str) -> dict:
    cleaned_password = str(password or "").strip()
    if not cleaned_password:
        raise ValueError("password is required")
    user = session.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    user.password_hash = hash_password(cleaned_password)
    user.updated_at = utc_now().replace(tzinfo=None)
    session.commit()
    return {"user": admin_user_payload(session, user)}


def admin_login(session: Session, payload: dict) -> dict:
    user_id = str(payload.get("id") or "").strip()
    password = str(payload.get("password") or "").strip()
    if not user_id or not password:
        raise ValueError("id and password are required")
    ensure_admin_user(session)
    user = session.get(User, user_id)
    if not user:
        raise ValueError("Invalid credentials")
    if not user.is_active:
        raise ValueError("User is inactive")
    if user.password_hash:
        from backend.app.core.security import verify_password
        if not verify_password(password, user.password_hash):
            raise ValueError("Invalid credentials")
    user.last_login_at = utc_now().replace(tzinfo=None)
    user.updated_at = utc_now().replace(tzinfo=None)
    session.commit()
    payload = admin_user_payload(session, user)
    return {"user": payload, **create_access_token(payload)}


def _payload_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "n", "inactive", "disabled"}
    return bool(value)


def workflow_registry_path() -> Path:
    return get_settings().data_dir / "workflow-registry.json"


def load_workflow_registry() -> dict:
    path = workflow_registry_path()
    if not path.exists():
        return {"items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"items": {}}
    return data if isinstance(data, dict) and isinstance(data.get("items"), dict) else {"items": {}}


def save_workflow_registry(registry: dict) -> None:
    path = workflow_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".{datetime.utcnow().timestamp():.0f}.tmp")
    tmp_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def segment_defaults_path() -> Path:
    return get_settings().data_dir / "segment-defaults.json"


def load_segment_defaults_file() -> dict:
    path = segment_defaults_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_segment_defaults_file(defaults: dict) -> None:
    path = segment_defaults_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".{datetime.utcnow().timestamp():.0f}.tmp")
    tmp_path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def sync_workflow_segment_defaults(workflow_id: str) -> dict:
    settings = get_settings()
    schema = parse_workflow_schema(workflow_id, settings.workflows_dir)
    defaults = load_segment_defaults_file()
    defaults[workflow_id] = {
        "workflowName": schema.get("name") or Path(workflow_id).stem,
        "segments": [
            {
                "id": f"segment-{segment.get('index') or index + 1}",
                "name": segment.get("displayName") or segment.get("subgraphName") or f"Segment {index + 1}",
                "config": segment_default_config(segment.get("config") or {}),
            }
            for index, segment in enumerate(schema.get("segments") or [])
        ],
    }
    save_segment_defaults_file(defaults)
    return defaults[workflow_id]


def segment_default_config(config: dict) -> dict:
    excluded_keys = {"seed", "Seed"}
    return {
        key: value
        for key, value in config.items()
        if key not in excluded_keys and value is not None
    }


def workflow_registry_item(workflow_id: str) -> dict:
    registry = load_workflow_registry()
    return dict(registry.get("items", {}).get(workflow_id) or {})


def is_workflow_active(workflow_id: str) -> bool:
    item = workflow_registry_item(workflow_id)
    return bool(item.get("active", True))


def list_admin_workflows() -> dict:
    settings = get_settings()
    workflows = parse_workflow_list(settings.workflows_dir)
    registry = load_workflow_registry()
    registry_items = registry.get("items", {})
    metadata_map_path = settings.metadata_dir / "workflow-widget-map.json"
    metadata_map = read_json_if_exists(metadata_map_path, {"workflows": {}}) or {"workflows": {}}
    metadata_workflows = metadata_map.get("workflows") or {}
    items = []
    for workflow in workflows:
        workflow_id = workflow.get("id")
        meta = dict(registry_items.get(workflow_id) or {})
        path = settings.workflows_dir / str(workflow_id)
        param_path = settings.workflows_dir / f"{Path(str(workflow_id)).stem}.paramconfig.json"
        workflow_metadata = metadata_workflows.get(str(workflow_id)) or {}
        items.append({
            **workflow,
            "active": bool(meta.get("active", True)),
            "status": meta.get("status") or ("ACTIVE" if meta.get("active", True) else "INACTIVE"),
            "description": meta.get("description") or "",
            **timestamp_fields("registeredAt", meta.get("registeredAt"), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="workflow-registry"),
            **timestamp_fields("updatedAt", meta.get("updatedAt"), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="workflow-registry"),
            "fileExists": path.exists(),
            "paramConfigExists": param_path.exists(),
            "paramConfigGenerated": bool(meta.get("paramConfigGenerated")),
            "metadataExists": bool(workflow_metadata),
            "metadataNodeCount": workflow_metadata.get("nodeCount"),
            "metadataSubgraphCount": len(workflow_metadata.get("segments") or []),
        })
    return {"items": items, "registryPath": str(workflow_registry_path())}


def register_admin_workflow(payload: dict) -> dict:
    workflow_id = normalize_workflow_id(payload.get("workflowId") or payload.get("fileName"))
    workflow_json = payload.get("workflowJson")
    if not isinstance(workflow_json, dict):
        raise ValueError("workflowJson object is required")
    validation = validate_workflow_registration_payload(workflow_json)
    settings = get_settings()
    settings.workflows_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = settings.workflows_dir / workflow_id
    backup_path = backup_existing_workflow_files(workflow_id)
    workflow_path.write_text(json.dumps(workflow_json, ensure_ascii=False, indent=2), encoding="utf-8")
    param_config = payload.get("paramConfigJson")
    param_config_generated = False
    if isinstance(param_config, dict):
        param_path = settings.workflows_dir / f"{Path(workflow_id).stem}.paramconfig.json"
        param_path.write_text(json.dumps(param_config, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        param_config = generate_param_config(workflow_id, workflow_json)
        param_path = settings.workflows_dir / f"{Path(workflow_id).stem}.paramconfig.json"
        param_path.write_text(json.dumps(param_config, ensure_ascii=False, indent=2), encoding="utf-8")
        param_config_generated = True
    registry = load_workflow_registry()
    items = registry.setdefault("items", {})
    now = utc_now().isoformat().replace("+00:00", "Z")
    existing = dict(items.get(workflow_id) or {})
    items[workflow_id] = {
        **existing,
        "active": bool(payload.get("active", existing.get("active", False))),
        "status": "ACTIVE" if payload.get("active", existing.get("active", False)) else "INACTIVE",
        "description": _optional_string(payload.get("description")) or existing.get("description") or "",
        "paramConfigGenerated": param_config_generated,
        "lastValidation": validation,
        "lastBackupPath": str(backup_path) if backup_path else existing.get("lastBackupPath"),
        "registeredAt": existing.get("registeredAt") or now,
        "updatedAt": now,
    }
    save_workflow_registry(registry)
    segment_defaults = sync_workflow_segment_defaults(workflow_id)
    manifest = ensure_metadata_current(*metadata_paths(), force=True)
    response = list_admin_workflows()
    response["registeredWorkflowId"] = workflow_id
    response["paramConfigGenerated"] = param_config_generated
    response["paramConfigJson"] = param_config
    response["segmentDefaultsUpdated"] = True
    response["segmentDefaults"] = segment_defaults
    response["metadataUpdated"] = True
    response["metadataManifest"] = manifest
    response["validation"] = validation
    response["backupPath"] = str(backup_path) if backup_path else None
    return response


def set_admin_workflow_active(workflow_id: str, active: bool) -> dict:
    workflow_id = normalize_workflow_id(workflow_id)
    settings = get_settings()
    if not (settings.workflows_dir / workflow_id).exists():
        raise ValueError("Workflow file not found")
    registry = load_workflow_registry()
    items = registry.setdefault("items", {})
    item = dict(items.get(workflow_id) or {})
    item["active"] = bool(active)
    item["status"] = "ACTIVE" if active else "INACTIVE"
    item["updatedAt"] = utc_now().isoformat().replace("+00:00", "Z")
    item.setdefault("registeredAt", item["updatedAt"])
    items[workflow_id] = item
    save_workflow_registry(registry)
    return list_admin_workflows()


def normalize_workflow_id(value: object) -> str:
    workflow_id = Path(str(value or "").strip()).name
    if not workflow_id.endswith(".json"):
        workflow_id = f"{workflow_id}.json"
    if not WORKFLOW_ID_PATTERN.match(workflow_id) or workflow_id.endswith(".paramconfig.json"):
        raise ValueError("Invalid workflowId")
    return workflow_id


def validate_workflow_registration_payload(workflow_json: dict) -> dict:
    node_count = len(workflow_json)
    if node_count == 0:
        raise ValueError("workflowJson must contain at least one node")
    invalid_node_ids = []
    class_types = []
    for node_id, node in workflow_json.items():
        if not isinstance(node, dict):
            invalid_node_ids.append(str(node_id))
            continue
        class_type = str(node.get("class_type") or node.get("type") or "").strip()
        if class_type:
            class_types.append(class_type)
        if "inputs" not in node and "widgets_values" not in node:
            invalid_node_ids.append(str(node_id))
    if invalid_node_ids:
        raise ValueError(f"Invalid workflow nodes: {', '.join(invalid_node_ids[:5])}")
    if not class_types:
        raise ValueError("workflowJson has no node class_type/type metadata")
    return {
        "ok": True,
        "nodeCount": node_count,
        "classTypeCount": len(class_types),
        "hasLoadImage": any(class_type == "LoadImage" for class_type in class_types),
        "hasSaveVideo": any(class_type == "SaveVideo" for class_type in class_types),
    }


def backup_existing_workflow_files(workflow_id: str) -> Path | None:
    settings = get_settings()
    workflow_path = settings.workflows_dir / workflow_id
    param_path = settings.workflows_dir / f"{Path(workflow_id).stem}.paramconfig.json"
    existing_files = [path for path in (workflow_path, param_path) if path.exists()]
    if not existing_files:
        return None
    backup_dir = settings.data_dir / "workflow-backups" / Path(workflow_id).stem / datetime.utcnow().strftime("%Y%m%d%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for source in existing_files:
        shutil.copy2(source, backup_dir / source.name)
    return backup_dir


def _optional_string(value: object) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
