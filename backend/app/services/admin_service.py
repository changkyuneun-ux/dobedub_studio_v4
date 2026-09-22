from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.security import create_access_token, ensure_admin_user, hash_password, normalize_permissions, normalize_role, user_payload
from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import User, WorkflowDefinition, WorkflowRevision
from backend.app.services.permission_service import (
    permission_governance_catalog,
    role_permission_code_map,
    user_permission_payload,
    user_permission_payloads,
)
from backend.app.services.workflow_parser import (
    generate_param_config,
    workflow_schema as parse_workflow_schema,
)
from backend.app.services.workflow_catalog_service import workflow_statistics
from backend.app.services.workflow_release_service import (
    ReleaseFiles,
    prepare_release,
    promote_release_files,
    verify_release_files,
    write_release_files,
)


WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\.json$")
WORKFLOW_ID_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
WORKFLOW_ID_REPEATED_SEPARATORS = re.compile(r"[-_]{2,}")


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


def is_workflow_active(workflow_id: str, db: Session | None = None) -> bool:
    if db is None:
        from backend.app.db.session import SessionLocal

        with SessionLocal() as session:
            definition = session.get(WorkflowDefinition, workflow_id)
            return bool(definition and definition.status == "ACTIVE" and definition.current_revision_id)
    definition = db.get(WorkflowDefinition, workflow_id)
    return bool(definition and definition.status == "ACTIVE" and definition.current_revision_id)


def count_active_workflows(db: Session | None = None) -> tuple[int, int]:
    """전체 워크플로 정의 수와 그중 활성(active) 상태인 수를 반환한다.

    Sandbox 대시보드 WORKFLOWS 타일에서 "N 정의" 대신 "active N개"를 보여주기
    위해 추가됨(2026-09-14). list_admin_workflows()처럼 메타데이터 전체를
    읽지 않고 DB 상태만 집계해 계산한다.
    """
    if db is None:
        from backend.app.db.session import SessionLocal

        with SessionLocal() as session:
            return count_active_workflows(session)
    total = db.scalar(select(func.count()).select_from(WorkflowDefinition)) or 0
    active = db.scalar(
        select(func.count()).select_from(WorkflowDefinition).where(WorkflowDefinition.status == "ACTIVE")
    ) or 0
    return int(total), int(active)


def _revision_payload(revision: WorkflowRevision | None) -> dict:
    if revision is None:
        return {}
    return {
        "id": revision.id,
        "revision": revision.revision,
        "workflowSha256": revision.workflow_sha256,
        "paramConfigSha256": revision.param_config_sha256,
        "validationStatus": revision.validation_status,
        "validation": revision.validation_json or {},
        "nodeCount": revision.node_count,
        "inputImageCount": revision.input_image_count,
        "segmentCount": revision.segment_count,
        **timestamp_fields("createdAt", revision.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
    }


def list_admin_workflows(db: Session) -> dict:
    settings = get_settings()
    items = []
    definitions = list(db.scalars(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.status != "ARCHIVED")
        .order_by(WorkflowDefinition.id)
    ))
    statistics = workflow_statistics(db, (definition.id for definition in definitions))
    for definition in definitions:
        latest = db.scalar(
            select(WorkflowRevision)
            .where(WorkflowRevision.workflow_id == definition.id)
            .order_by(WorkflowRevision.revision.desc())
            .limit(1)
        )
        current = db.get(WorkflowRevision, definition.current_revision_id) if definition.current_revision_id else None
        inspected = current or latest
        integrity = verify_release_files(settings.workflows_dir, inspected) if inspected else {"ok": False, "workflow": "MISSING", "paramConfig": "MISSING"}
        validation = (latest.validation_json if latest else {}) or {}
        items.append({
            "id": definition.id,
            "name": definition.display_name,
            "label": definition.display_name,
            "mode": "multi_segment" if int(validation.get("hasSaveVideo") or 0) else "single",
            "keyframeCount": int(latest.input_image_count if latest else 0),
            "segmentCount": int(latest.segment_count if latest else 0),
            "active": definition.status == "ACTIVE",
            "status": definition.status,
            "source": definition.source,
            "description": definition.description or "",
            "registeredBy": definition.registered_by,
            "updatedBy": definition.updated_by,
            **timestamp_fields("registeredAt", definition.registered_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
            **timestamp_fields("updatedAt", definition.updated_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
            **timestamp_fields("activatedAt", definition.activated_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
            **timestamp_fields("deactivatedAt", definition.deactivated_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="database"),
            "currentRevision": current.revision if current else None,
            "latestRevision": latest.revision if latest else None,
            "currentRevisionMetadata": _revision_payload(current),
            "latestRevisionMetadata": _revision_payload(latest),
            "integrity": integrity,
            "integrityStatus": "OK" if integrity.get("ok") else "ERROR",
            "fileExists": integrity.get("workflow") == "OK",
            "paramConfigExists": integrity.get("paramConfig") == "OK",
            "paramConfigGenerated": bool((latest.validation_json if latest else {}).get("paramConfigGenerated")),
            "metadataExists": bool(latest),
            "metadataNodeCount": latest.node_count if latest else None,
            "metadataSubgraphCount": latest.segment_count if latest else None,
            "statistics": statistics.get(definition.id, {}),
        })
    return {"items": items, "registryPath": None, "metadataSource": "database"}


def register_admin_workflow(db: Session, payload: dict, actor_id: str | None = None) -> dict:
    workflow_id = normalize_workflow_id(payload.get("workflowId") or payload.get("fileName"))
    workflow_json = payload.get("workflowJson")
    if not isinstance(workflow_json, dict):
        raise ValueError("workflowJson object is required")
    settings = get_settings()
    settings.workflows_dir.mkdir(parents=True, exist_ok=True)
    param_config = payload.get("paramConfigJson")
    param_config_generated = False
    if not isinstance(param_config, dict):
        param_config = generate_param_config(workflow_id, workflow_json)
        param_config_generated = True
    prepared = prepare_release(workflow_id, workflow_json, param_config)
    definition = db.get(WorkflowDefinition, workflow_id)
    if definition is None:
        definition = WorkflowDefinition(
            id=workflow_id,
            display_name=Path(workflow_id).stem,
            description=_optional_string(payload.get("description")),
            status="INACTIVE",
            source="ADMIN_UPLOAD",
            registered_by=actor_id,
            updated_by=actor_id,
        )
        db.add(definition)
        db.flush()
    else:
        definition.description = _optional_string(payload.get("description")) or definition.description
        definition.updated_by = actor_id
        if definition.status == "ARCHIVED":
            definition.status = "INACTIVE"
            definition.archived_at = None

    duplicate = db.scalar(
        select(WorkflowRevision).where(
            WorkflowRevision.workflow_id == workflow_id,
            WorkflowRevision.workflow_sha256 == prepared.workflow_sha256,
            WorkflowRevision.param_config_sha256 == prepared.param_config_sha256,
        )
    )
    files = None
    if duplicate is None:
        next_revision = int(
            (db.scalar(select(func.max(WorkflowRevision.revision)).where(WorkflowRevision.workflow_id == workflow_id)) or 0) + 1
        )
        files = write_release_files(settings.workflows_dir, workflow_id, next_revision, prepared)
        validation = {**prepared.validation, "paramConfigGenerated": param_config_generated}
        duplicate = WorkflowRevision(
            workflow_id=workflow_id,
            revision=next_revision,
            workflow_path=files.workflow_path,
            workflow_sha256=prepared.workflow_sha256,
            workflow_size_bytes=len(prepared.workflow_bytes),
            param_config_path=files.param_config_path,
            param_config_sha256=prepared.param_config_sha256,
            param_config_size_bytes=len(prepared.param_config_bytes),
            validation_status="VALID",
            validation_json=validation,
            node_count=prepared.node_count,
            input_image_count=prepared.input_image_count,
            segment_count=prepared.segment_count,
            created_by=actor_id,
        )
        db.add(duplicate)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if files:
            (settings.workflows_dir / files.workflow_path).unlink(missing_ok=True)
            (settings.workflows_dir / files.param_config_path).unlink(missing_ok=True)
        raise
    response = list_admin_workflows(db)
    response["registeredWorkflowId"] = workflow_id
    response["paramConfigGenerated"] = param_config_generated
    response["paramConfigJson"] = param_config
    response["segmentDefaultsUpdated"] = False
    response["metadataUpdated"] = True
    response["validation"] = duplicate.validation_json
    response["revision"] = duplicate.revision
    return response


def set_admin_workflow_active(
    db: Session,
    workflow_id: str,
    active: bool,
    actor_id: str | None = None,
    revision_id: int | None = None,
) -> dict:
    workflow_id = normalize_workflow_id(workflow_id)
    definition = db.get(WorkflowDefinition, workflow_id)
    if definition is None:
        raise ValueError("Workflow is not registered")
    settings = get_settings()
    now = utc_now().replace(tzinfo=None)
    if active:
        revision = db.get(WorkflowRevision, revision_id) if revision_id else db.scalar(
            select(WorkflowRevision)
            .where(WorkflowRevision.workflow_id == workflow_id)
            .order_by(WorkflowRevision.revision.desc())
            .limit(1)
        )
        if revision is None or revision.workflow_id != workflow_id or revision.validation_status != "VALID":
            raise ValueError("Workflow has no valid revision")
        integrity = verify_release_files(settings.workflows_dir, revision)
        if not integrity.get("ok"):
            raise ValueError("Workflow release file integrity check failed")
        promote_release_files(
            settings.workflows_dir,
            workflow_id,
            ReleaseFiles(workflow_path=revision.workflow_path, param_config_path=revision.param_config_path),
        )
        sync_workflow_segment_defaults(workflow_id)
        definition.status = "ACTIVE"
        definition.current_revision_id = revision.id
        definition.activated_at = now
    else:
        definition.status = "INACTIVE"
        definition.deactivated_at = now
    definition.updated_by = actor_id
    db.commit()
    return list_admin_workflows(db)


def list_workflow_revisions(db: Session, workflow_id: str) -> dict:
    normalized = normalize_workflow_id(workflow_id)
    if db.get(WorkflowDefinition, normalized) is None:
        raise ValueError("Workflow is not registered")
    revisions = list(
        db.scalars(
            select(WorkflowRevision)
            .where(WorkflowRevision.workflow_id == normalized)
            .order_by(WorkflowRevision.revision.desc())
        )
    )
    return {"workflowId": normalized, "items": [_revision_payload(revision) for revision in revisions]}


def archive_admin_workflow(db: Session, workflow_id: str, actor_id: str | None = None) -> dict:
    normalized = normalize_workflow_id(workflow_id)
    definition = db.get(WorkflowDefinition, normalized)
    if definition is None:
        raise ValueError("Workflow is not registered")
    if definition.status == "ACTIVE":
        raise ValueError("Deactivate workflow before archiving")
    now = utc_now().replace(tzinfo=None)
    definition.status = "ARCHIVED"
    definition.archived_at = now
    definition.updated_by = actor_id
    db.commit()
    return list_admin_workflows(db)


def normalize_workflow_id(value: object) -> str:
    raw_name = Path(str(value or "").strip()).name
    if raw_name.lower().endswith(".json"):
        raw_name = raw_name[:-5]
    # Workflow JSON files are often exported with spaces, parentheses, or a
    # browser-generated copy suffix. Store them under a predictable safe ID.
    base_name = WORKFLOW_ID_UNSAFE_CHARS.sub("-", raw_name).strip("._-")
    base_name = WORKFLOW_ID_REPEATED_SEPARATORS.sub("-", base_name)
    workflow_id = f"{base_name}.json" if base_name else ""
    if not WORKFLOW_ID_PATTERN.match(workflow_id) or workflow_id.endswith(".paramconfig.json"):
        raise ValueError("Invalid workflowId")
    return workflow_id


def _optional_string(value: object) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
