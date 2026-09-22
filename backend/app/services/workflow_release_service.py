from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from backend.app.db.models import WorkflowRevision


WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\.json$")


@dataclass(frozen=True)
class PreparedWorkflowRelease:
    workflow_bytes: bytes
    param_config_bytes: bytes
    workflow_sha256: str
    param_config_sha256: str
    node_count: int
    input_image_count: int
    segment_count: int
    validation: dict


@dataclass(frozen=True)
class ReleaseFiles:
    workflow_path: str
    param_config_path: str


def _validate_workflow_id(workflow_id: str) -> None:
    if (
        workflow_id != workflow_id.strip()
        or Path(workflow_id).name != workflow_id
        or not WORKFLOW_ID_PATTERN.fullmatch(workflow_id)
        or workflow_id.endswith(".paramconfig.json")
    ):
        raise ValueError("Invalid workflowId")


def _canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def prepare_release(workflow_id: str, workflow_json: dict, param_config_json: dict) -> PreparedWorkflowRelease:
    _validate_workflow_id(workflow_id)
    if not isinstance(workflow_json, dict) or not workflow_json:
        raise ValueError("workflowJson must contain at least one node")
    if not isinstance(param_config_json, dict):
        raise ValueError("paramConfigJson must be an object")

    invalid_node_ids: list[str] = []
    class_types: list[str] = []
    for node_id, node in workflow_json.items():
        if not isinstance(node, dict):
            invalid_node_ids.append(str(node_id))
            continue
        class_type = str(node.get("class_type") or node.get("type") or "").strip()
        if class_type:
            class_types.append(class_type)
        if not class_type or ("inputs" not in node and "widgets_values" not in node):
            invalid_node_ids.append(str(node_id))
    if invalid_node_ids:
        raise ValueError(f"Invalid workflow nodes: {', '.join(invalid_node_ids[:5])}")

    workflow_bytes = _canonical_json_bytes(workflow_json)
    param_config_bytes = _canonical_json_bytes(param_config_json)
    validation = {
        "ok": True,
        "nodeCount": len(workflow_json),
        "classTypeCount": len(class_types),
        "hasLoadImage": "LoadImage" in class_types,
        "hasSaveVideo": "SaveVideo" in class_types,
    }
    return PreparedWorkflowRelease(
        workflow_bytes=workflow_bytes,
        param_config_bytes=param_config_bytes,
        workflow_sha256=hashlib.sha256(workflow_bytes).hexdigest(),
        param_config_sha256=hashlib.sha256(param_config_bytes).hexdigest(),
        node_count=len(workflow_json),
        input_image_count=sum(class_type == "LoadImage" for class_type in class_types),
        segment_count=sum(class_type == "SaveVideo" for class_type in class_types),
        validation=validation,
    )


def _safe_destination(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    destination = (root / relative_path).resolve()
    if destination != root and root not in destination.parents:
        raise ValueError("Workflow release path escapes workflow directory")
    return destination


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_release_files(
    workflows_dir: Path,
    workflow_id: str,
    revision: int,
    prepared: PreparedWorkflowRelease,
) -> ReleaseFiles:
    _validate_workflow_id(workflow_id)
    if revision < 1:
        raise ValueError("revision must be positive")
    stem = Path(workflow_id).stem
    workflow_relative = f"releases/{stem}/{revision}/workflow.json"
    param_relative = f"releases/{stem}/{revision}/paramconfig.json"
    workflow_path = _safe_destination(workflows_dir, workflow_relative)
    param_path = _safe_destination(workflows_dir, param_relative)
    try:
        _atomic_write(workflow_path, prepared.workflow_bytes)
        _atomic_write(param_path, prepared.param_config_bytes)
    except Exception:
        workflow_path.unlink(missing_ok=True)
        param_path.unlink(missing_ok=True)
        raise
    return ReleaseFiles(workflow_path=workflow_relative, param_config_path=param_relative)


def promote_release_files(workflows_dir: Path, workflow_id: str, files: ReleaseFiles) -> None:
    _validate_workflow_id(workflow_id)
    workflow_source = _safe_destination(workflows_dir, files.workflow_path)
    param_source = _safe_destination(workflows_dir, files.param_config_path)
    if not workflow_source.is_file() or not param_source.is_file():
        raise ValueError("Workflow release file is missing")
    _atomic_write(_safe_destination(workflows_dir, workflow_id), workflow_source.read_bytes())
    _atomic_write(
        _safe_destination(workflows_dir, f"{Path(workflow_id).stem}.paramconfig.json"),
        param_source.read_bytes(),
    )


def verify_release_files(workflows_dir: Path, revision: WorkflowRevision) -> dict:
    statuses: dict[str, str] = {}
    for key, relative_path, expected_hash in (
        ("workflow", revision.workflow_path, revision.workflow_sha256),
        ("paramConfig", revision.param_config_path, revision.param_config_sha256),
    ):
        path = _safe_destination(workflows_dir, relative_path)
        if not path.is_file():
            statuses[key] = "MISSING"
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            statuses[key] = "HASH_MISMATCH"
        else:
            statuses[key] = "OK"
    return {"ok": all(value == "OK" for value in statuses.values()), **statuses}
