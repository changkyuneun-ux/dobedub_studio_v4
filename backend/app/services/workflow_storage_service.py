"""Keep operator-managed workflow files separate from image-bundled defaults."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_FILE_NAME = "workflow-seed-manifest.json"


def workflow_seed_manifest_path(data_dir: Path) -> Path:
    return data_dir / MANIFEST_FILE_NAME


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "files": {}}
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        return {"version": 1, "files": {}}
    return {"version": 1, "files": value["files"]}


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def bootstrap_workflow_store(seed_dir: Path, runtime_dir: Path, data_dir: Path) -> dict:
    """Seed missing bundled workflow files without overwriting runtime changes.

    A record in the manifest marks the last image-bundled version copied to the
    runtime store. A later image upgrade can update that file only when the
    runtime copy still matches the recorded bundled hash. Files registered by
    an operator never have a manifest record and are therefore always kept.
    """
    seed_dir = seed_dir.expanduser()
    runtime_dir = runtime_dir.expanduser()
    data_dir = data_dir.expanduser()
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "seedDir": str(seed_dir),
        "runtimeDir": str(runtime_dir),
        "seedAvailable": seed_dir.is_dir(),
        "created": [],
        "updated": [],
        "preserved": [],
        "pruned": [],
    }
    pruned_workflow_ids = _prune_inactive_runtime_workflows(runtime_dir, data_dir, result)
    if not seed_dir.is_dir() or seed_dir.resolve() == runtime_dir.resolve():
        return result

    manifest_path = workflow_seed_manifest_path(data_dir)
    manifest = _load_manifest(manifest_path)
    files = manifest["files"]
    for source in sorted(seed_dir.glob("*.json")):
        if source.name in pruned_workflow_ids:
            continue
        destination = runtime_dir / source.name
        source_hash = _file_hash(source)
        recorded = files.get(source.name) if isinstance(files.get(source.name), dict) else {}
        recorded_hash = str(recorded.get("seedHash") or "")

        if not destination.exists():
            shutil.copy2(source, destination)
            files[source.name] = {"seedHash": source_hash}
            result["created"].append(source.name)
            continue

        destination_hash = _file_hash(destination)
        if recorded_hash and destination_hash == recorded_hash and source_hash != recorded_hash:
            shutil.copy2(source, destination)
            files[source.name] = {"seedHash": source_hash}
            result["updated"].append(source.name)
        elif not recorded_hash:
            # Existing runtime content predates this manifest. Treat it as
            # operator-managed rather than risking a destructive overwrite.
            result["preserved"].append(source.name)
        elif destination_hash != recorded_hash:
            result["preserved"].append(source.name)

    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _write_manifest(manifest_path, manifest)
    return result


def _load_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_object(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _prune_inactive_runtime_workflows(runtime_dir: Path, data_dir: Path, result: dict) -> set[str]:
    registry_path = data_dir / "workflow-registry.json"
    registry = _load_json_object(registry_path)
    items = registry.get("items") if isinstance(registry.get("items"), dict) else {}
    inactive_ids = sorted(
        str(workflow_id)
        for workflow_id, item in items.items()
        if isinstance(item, dict) and item.get("active") is False
    )
    if not inactive_ids:
        return set()

    for workflow_id in inactive_ids:
        workflow_path = runtime_dir / Path(workflow_id).name
        param_path = runtime_dir / f"{workflow_path.stem}.paramconfig.json"
        removed = False
        for path in (workflow_path, param_path):
            if path.exists() and path.is_file():
                path.unlink()
                removed = True
        items.pop(workflow_id, None)
        if removed:
            result["pruned"].append(workflow_id)
    registry["items"] = items
    _write_json_object(registry_path, registry)

    defaults_path = data_dir / "segment-defaults.json"
    defaults = _load_json_object(defaults_path)
    changed_defaults = False
    for workflow_id in inactive_ids:
        if workflow_id in defaults:
            defaults.pop(workflow_id, None)
            changed_defaults = True
    if changed_defaults:
        _write_json_object(defaults_path, defaults)
    return set(inactive_ids)


def workflow_store_status(seed_dir: Path, runtime_dir: Path, data_dir: Path) -> dict:
    manifest_path = workflow_seed_manifest_path(data_dir)
    manifest = _load_manifest(manifest_path)
    return {
        "seedDir": str(seed_dir),
        "runtimeDir": str(runtime_dir),
        "seedAvailable": seed_dir.is_dir(),
        "runtimeAvailable": runtime_dir.is_dir(),
        "manifestPath": str(manifest_path),
        "seededFileCount": len(manifest.get("files") or {}),
    }
