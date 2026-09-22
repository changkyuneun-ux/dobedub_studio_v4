"""Workflow-scoped JSON instruction documents for Grok prompt generation.

Instruction documents intentionally live in a versioned JSON file rather than
the application database. A workflow owns one instruction set, so a prompt
request can never accidentally combine rules from another workflow.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
_VALID_ROLES = {"CORE", "ROUTER", "GUIDE"}
_SINGLETON_ROLES = {"CORE", "ROUTER"}
_ROLE_ORDER = {"CORE": 0, "ROUTER": 1, "GUIDE": 2}
_SCHEMA_VERSION = "2.0"
_SET_CODE = "grok_wan_i2v_transformer"
LEGACY_DEFAULT_WORKFLOW_ID = "1-images.json"
DEFAULT_WAN_WORKFLOW_ID = "wan22_default_81.json"


def _seed_path() -> Path:
    return get_settings().project_root / "backend" / "app" / "data" / "grok_instruction_set.json"


def _runtime_path() -> Path:
    return get_settings().grok_instruction_set_path


def _active_workflow_ids() -> list[str]:
    from backend.app.db.session import SessionLocal
    from backend.app.services.workflow_catalog_service import list_active_workflow_ids

    with SessionLocal() as db:
        return list_active_workflow_ids(db)


def ensure_instruction_set() -> Path:
    """Create the editable runtime set from the tracked seed only once."""
    path = _runtime_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        document_set, _ = _read_set(_seed_path())
    except (OSError, ValueError):
        document_set = _default_set()
    _write_set(document_set, path)
    return path


def list_instruction_documents(workflow_id: str) -> dict[str, Any]:
    return _response_for_workflow(_load_set(), _require_workflow_id(workflow_id))


def list_instruction_source_workflows() -> list[str]:
    """Return only workflows that can be copied as an instruction source."""
    document_set = _load_set()
    active_ids = set(_active_workflow_ids())
    return [
        workflow["workflowId"]
        for workflow in document_set["workflowInstructionSets"]
        if workflow.get("documents") and workflow["workflowId"] in active_ids
    ]


def resolve_workflow_instruction_set(workflow_id: str) -> dict[str, Any]:
    document_set = _load_set()
    workflow = _find_workflow(document_set, _require_workflow_id(workflow_id))
    if workflow is None:
        raise ValueError("선택한 워크플로우에 활성 프롬프트 지시문이 없습니다. 관리자에서 지시문을 설정하세요.")
    active_items = [item for item in _sorted_documents(workflow["documents"]) if item["isActive"]]
    if not active_items:
        raise ValueError("선택한 워크플로우에 활성 프롬프트 지시문이 없습니다. 관리자에서 지시문을 설정하세요.")
    validate_instruction_set(workflow)
    compiled = "\n\n".join(
        f"[{item['role']}] {item['title']}\n{item['contentMarkdown']}" for item in active_items
    ).strip()
    fingerprint = hashlib.sha256(compiled.encode("utf-8")).hexdigest()[:16]
    return {
        "workflowId": workflow["workflowId"],
        "version": workflow["version"],
        "compiledMarkdown": compiled,
        "instructionVersion": f"{workflow['workflowId']}@{workflow['version']}-{fingerprint}",
        "items": active_items,
    }


def active_instruction_text(workflow_id: str) -> tuple[str, str]:
    resolved = resolve_workflow_instruction_set(workflow_id)
    return resolved["compiledMarkdown"], resolved["instructionVersion"]


def save_instruction_document(payload: dict[str, Any], *, document_id: str | None) -> dict[str, Any]:
    workflow_id = _require_workflow_id(payload.get("workflowId"))
    document_set = _load_set()
    workflow = _get_or_create_workflow(document_set, workflow_id)
    documents = workflow["documents"]
    item = next((candidate for candidate in documents if candidate["id"] == document_id), None) if document_id else None
    if document_id and item is None:
        raise ValueError("선택한 워크플로우에서 지시문을 찾을 수 없습니다.")

    code = _normalize_code(payload.get("code") if payload.get("code") is not None else (item or {}).get("code"))
    title = str(payload.get("title") if payload.get("title") is not None else (item or {}).get("title") or "").strip()
    content = str(payload.get("contentMarkdown") or "").strip()
    if not code or not title or not content:
        raise ValueError("code, title, and contentMarkdown are required")
    duplicate = next((candidate for candidate in documents if candidate["code"] == code), None)
    if duplicate and (item is None or duplicate["id"] != item["id"]):
        raise ValueError(f"Instruction code already exists in this workflow: {code}")

    if item is None:
        item = {"id": f"grok_instruction_{uuid.uuid4().hex[:16]}", "version": 1}
        documents.append(item)
    else:
        item["version"] = _safe_int(item.get("version"), 1) + 1
    item.update(_document_fields(payload, code=code, title=title, content=content))
    validate_instruction_set(workflow)
    workflow["version"] = max(1, _safe_int(workflow.get("version"), 0) + 1)
    _save_set(document_set)
    response = list_instruction_documents(workflow_id)
    response["item"] = next(candidate for candidate in response["items"] if candidate["id"] == item["id"])
    return response


def delete_instruction_document(workflow_id: str, document_id: str) -> dict[str, Any]:
    """Remove one instruction from its owning workflow set only."""
    workflow_id = _require_workflow_id(workflow_id)
    document_set = _load_set()
    workflow = _find_workflow(document_set, workflow_id)
    if workflow is None:
        raise ValueError("선택한 워크플로우에 지시문이 없습니다.")
    documents = workflow["documents"]
    item = next((candidate for candidate in documents if candidate["id"] == document_id), None)
    if item is None:
        raise ValueError("선택한 워크플로우에서 지시문을 찾을 수 없습니다.")
    workflow["documents"] = [candidate for candidate in documents if candidate["id"] != document_id]
    workflow["version"] = max(1, _safe_int(workflow.get("version"), 0) + 1)
    _save_set(document_set)
    return list_instruction_documents(workflow_id)


def copy_instruction_documents(source_workflow_id: str, target_workflow_id: str) -> dict[str, Any]:
    """Create an independent instruction set for a workflow from another one.

    Copy is intentionally explicit and rejects a populated target. This keeps
    the workflow-to-instruction relationship one-to-one and avoids accidental
    reuse of the 1-images rule set.
    """
    source_workflow_id = _require_workflow_id(source_workflow_id)
    target_workflow_id = _require_workflow_id(target_workflow_id)
    if source_workflow_id == target_workflow_id:
        raise ValueError("같은 워크플로우로 지시문을 복사할 수 없습니다.")
    document_set = _load_set()
    source = _find_workflow(document_set, source_workflow_id)
    if source is None or not source.get("documents"):
        raise ValueError("복사할 원본 워크플로우 지시문이 없습니다.")
    target = _find_workflow(document_set, target_workflow_id)
    if target is not None and target.get("documents"):
        raise ValueError("대상 워크플로우에 이미 지시문이 있습니다. 기존 문서를 수정하거나 삭제한 뒤 복사하세요.")
    if target is None:
        target = _get_or_create_workflow(document_set, target_workflow_id)
    target["documents"] = [{
        **item,
        "id": f"grok_instruction_{uuid.uuid4().hex[:16]}",
        "version": 1,
        "source": f"Copied from {source_workflow_id}",
    } for item in source["documents"]]
    target["version"] = 1
    validate_instruction_set(target)
    _save_set(document_set)
    response = list_instruction_documents(target_workflow_id)
    response["copiedFromWorkflowId"] = source_workflow_id
    return response


def import_markdown_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a Markdown document into one editable JSON instruction entry."""
    workflow_id = _require_workflow_id(payload.get("workflowId"))
    content = str(payload.get("contentMarkdown") or "").strip()
    file_name = str(payload.get("fileName") or "").strip()
    if not content:
        raise ValueError("contentMarkdown is required")
    title = str(payload.get("title") or _first_heading(content) or Path(file_name).stem or "Untitled instruction").strip()
    code = _normalize_code(payload.get("code") or Path(file_name).stem or title) or "instruction"
    workflow = _get_or_create_workflow(_load_set(), workflow_id)
    existing_codes = {item["code"] for item in workflow["documents"]}
    base_code = code
    suffix = 2
    while code in existing_codes:
        code = f"{base_code}_{suffix}"
        suffix += 1
    return save_instruction_document(
        {
            "workflowId": workflow_id,
            "code": code,
            "title": title,
            "role": payload.get("role") or "GUIDE",
            "contentMarkdown": content,
            "source": file_name or payload.get("source") or "Markdown import",
            "sortOrder": _safe_int(payload.get("sortOrder"), _next_sort_order(workflow["documents"])),
            "isActive": bool(payload.get("isActive", True)),
        },
        document_id=None,
    )


def validate_instruction_set(workflow_set: dict[str, Any]) -> None:
    documents = workflow_set.get("documents") or []
    for role in _SINGLETON_ROLES:
        count = sum(1 for item in documents if _normalize_role(item.get("role")) == role)
        if count > 1:
            raise ValueError(f"{role} 역할은 워크플로우당 1개만 설정할 수 있습니다. 기존 문서를 수정하거나 역할을 GUIDE로 변경하세요.")


def _load_set() -> dict[str, Any]:
    path = ensure_instruction_set()
    document_set, promoted = _read_set(path)
    migrated = _migrate_retired_default_documents(document_set)
    if promoted or migrated:
        _write_set(document_set, path)
    return document_set


def _migrate_retired_default_documents(document_set: dict[str, Any]) -> bool:
    """Copy existing production instructions into every approved workflow.

    Runtime instruction JSON is persisted outside the image. Older installs
    have the documents under ``1-images.json`` while newer installs have them
    only under ``wan22_default_81.json``. Fill an empty approved set from that
    existing source without overwriting a set an administrator has edited.
    """
    legacy = _find_workflow(document_set, LEGACY_DEFAULT_WORKFLOW_ID)
    source = legacy if legacy is not None and legacy.get("documents") else next(
        (
            _find_workflow(document_set, workflow_id)
            for workflow_id in _active_workflow_ids()
            if (_find_workflow(document_set, workflow_id) or {}).get("documents")
        ),
        None,
    )
    if source is None:
        return False

    migrated = False
    source_workflow_id = source["workflowId"]
    for workflow_id in _active_workflow_ids():
        target = _get_or_create_workflow(document_set, workflow_id)
        if target.get("documents"):
            continue
        target["documents"] = [{
            **item,
            "id": f"grok_instruction_{uuid.uuid4().hex[:16]}",
            "version": 1,
            "source": f"Migrated from {source_workflow_id}",
        } for item in source["documents"]]
        target["version"] = max(1, _safe_int(source.get("version"), 1))
        validate_instruction_set(target)
        migrated = True

    if source is legacy:
        legacy["documents"] = []
        legacy["version"] = max(1, _safe_int(legacy.get("version"), 1) + 1)
        migrated = True
    return migrated


def _save_set(document_set: dict[str, Any]) -> None:
    _write_set(document_set, _runtime_path())


def _read_set(path: Path) -> tuple[dict[str, Any], bool]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = {"schemaVersion": "1.0", "documents": raw}
    if not isinstance(raw, dict):
        raise ValueError("Grok instruction JSON must be an object")
    if str(raw.get("schemaVersion") or "") == _SCHEMA_VERSION and isinstance(raw.get("workflowInstructionSets"), list):
        return _normalize_v2_set(raw), False
    if not isinstance(raw.get("documents"), list):
        raise ValueError("Grok instruction JSON must contain a documents array")
    return _promote_legacy_set(raw), True


def _normalize_v2_set(raw: dict[str, Any]) -> dict[str, Any]:
    workflow_sets: list[dict[str, Any]] = []
    seen_workflows: set[str] = set()
    for index, source in enumerate(raw.get("workflowInstructionSets") or []):
        if not isinstance(source, dict):
            continue
        workflow_id = str(source.get("workflowId") or "").strip()
        if not workflow_id or workflow_id in seen_workflows:
            continue
        seen_workflows.add(workflow_id)
        workflow = {
            "workflowId": workflow_id,
            "version": max(1, _safe_int(source.get("version"), 1)),
            "documents": _normalize_documents(source.get("documents"), prefix=f"{workflow_id}:{index}"),
        }
        validate_instruction_set(workflow)
        workflow_sets.append(workflow)
    return {
        "schemaVersion": _SCHEMA_VERSION,
        "setCode": str(raw.get("setCode") or _SET_CODE),
        "responseContract": raw.get("responseContract") if isinstance(raw.get("responseContract"), dict) else _default_set()["responseContract"],
        "workflowInstructionSets": workflow_sets,
    }


def _promote_legacy_set(raw: dict[str, Any]) -> dict[str, Any]:
    workflow = {
        "workflowId": LEGACY_DEFAULT_WORKFLOW_ID,
        "version": max(1, _safe_int(raw.get("version"), 1)),
        "documents": _normalize_documents(raw.get("documents"), prefix="legacy"),
    }
    validate_instruction_set(workflow)
    return {
        "schemaVersion": _SCHEMA_VERSION,
        "setCode": str(raw.get("setCode") or _SET_CODE),
        "responseContract": raw.get("responseContract") if isinstance(raw.get("responseContract"), dict) else _default_set()["responseContract"],
        "workflowInstructionSets": [workflow],
    }


def _normalize_documents(source_documents: Any, *, prefix: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, source in enumerate(source_documents if isinstance(source_documents, list) else []):
        if not isinstance(source, dict):
            continue
        code = _normalize_code(source.get("code"))
        title = str(source.get("title") or "").strip()
        content = str(source.get("contentMarkdown") or "").strip()
        if not code or not title or not content or code in seen_codes:
            continue
        seen_codes.add(code)
        documents.append({
            "id": str(source.get("id") or f"grok_instruction_{uuid.uuid5(uuid.NAMESPACE_URL, f'{prefix}:{code}').hex[:16]}"),
            "code": code,
            "title": title,
            "role": _normalize_role(source.get("role")),
            "contentMarkdown": content,
            "source": str(source.get("source") or "").strip() or None,
            "sortOrder": _safe_int(source.get("sortOrder"), (index + 1) * 10),
            "version": max(1, _safe_int(source.get("version"), 1)),
            "isActive": bool(source.get("isActive", True)),
        })
    return documents


def _response_for_workflow(document_set: dict[str, Any], workflow_id: str) -> dict[str, Any]:
    workflow = _find_workflow(document_set, workflow_id)
    documents = _sorted_documents(workflow["documents"]) if workflow else []
    return {
        "items": documents,
        "instructionSet": {
            "schemaVersion": document_set["schemaVersion"],
            "setCode": document_set["setCode"],
            "responseContract": document_set["responseContract"],
            "workflowId": workflow_id,
            "version": workflow["version"] if workflow else None,
            "documents": [{key: item[key] for key in ("id", "code", "title", "role", "sortOrder", "version", "isActive", "source")} for item in documents],
        },
    }


def _get_or_create_workflow(document_set: dict[str, Any], workflow_id: str) -> dict[str, Any]:
    workflow = _find_workflow(document_set, workflow_id)
    if workflow is not None:
        return workflow
    workflow = {"workflowId": workflow_id, "version": 1, "documents": []}
    document_set["workflowInstructionSets"].append(workflow)
    return workflow


def _find_workflow(document_set: dict[str, Any], workflow_id: str) -> dict[str, Any] | None:
    return next((item for item in document_set["workflowInstructionSets"] if item["workflowId"] == workflow_id), None)


def _write_set(document_set: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document_set, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sorted_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(documents, key=lambda item: (_ROLE_ORDER[item["role"]], item["sortOrder"], item["title"], item["id"]))


def _document_fields(payload: dict[str, Any], *, code: str, title: str, content: str) -> dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "role": _normalize_role(payload.get("role")),
        "contentMarkdown": content,
        "source": str(payload.get("source") or "").strip() or None,
        "sortOrder": _safe_int(payload.get("sortOrder"), 100),
        "isActive": bool(payload.get("isActive", True)),
    }


def _next_sort_order(documents: list[dict[str, Any]]) -> int:
    return max((item["sortOrder"] for item in documents), default=0) + 10


def _require_workflow_id(value: Any) -> str:
    workflow_id = str(value or "").strip()
    if not workflow_id:
        raise ValueError("워크플로우를 먼저 선택하세요.")
    return workflow_id


def _first_heading(content: str) -> str:
    for line in content.splitlines():
        heading = re.sub(r"^\s*#+\s*", "", line).strip()
        if heading:
            return heading[:191]
    return ""


def _normalize_code(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")[:128]


def _normalize_role(value: Any) -> str:
    role = str(value or "GUIDE").strip().upper()
    return role if role in _VALID_ROLES else "GUIDE"


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return max(0, min(10000, int(value)))
    except (TypeError, ValueError):
        return fallback


def _default_set() -> dict[str, Any]:
    return {
        "schemaVersion": _SCHEMA_VERSION,
        "setCode": _SET_CODE,
        "responseContract": {
            "format": "json_object",
            "fields": ["positivePrompt", "imageType", "warnings"],
            "instruction": "Return exactly one JSON object with these fields and no Markdown fence or commentary.",
        },
        "workflowInstructionSets": [],
    }
