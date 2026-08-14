from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from backend.app.services.workflow_parser import (
    PARAM_DESCRIPTIONS,
    PARAM_LABELS,
    PARAM_UI_KEYS,
    VIDEO_NODE_TYPES,
    find_keyframe_images_ordered,
    find_prompt_node,
    find_segments,
    load_param_config,
    node_title,
    workflow_files,
)


WRITE_JSON_LOCK = threading.Lock()


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with WRITE_JSON_LOCK:
        try:
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()


def read_json_if_exists(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return read_json(path)
    except json.JSONDecodeError:
        return default


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path, project_root: Path) -> str:
    return str(path.relative_to(project_root)) if path.is_relative_to(project_root) else str(path)


def metadata_source_paths(workflows_dir: Path, data_dir: Path, bundled_defaults_path: Path, object_info_path: Path) -> list[Path]:
    paths = []
    if workflows_dir.exists():
        paths.extend(sorted(workflows_dir.glob("*.json")))
    runtime_defaults_path = data_dir / "segment-defaults.json"
    if runtime_defaults_path.exists():
        paths.append(runtime_defaults_path)
    elif bundled_defaults_path.exists():
        paths.append(bundled_defaults_path)
    if object_info_path.exists():
        paths.append(object_info_path)
    return [path for path in paths if path.is_file()]


def metadata_fingerprint(workflows_dir: Path, data_dir: Path, bundled_defaults_path: Path, object_info_path: Path, project_root: Path) -> tuple[str, list[dict]]:
    digest = hashlib.sha256()
    sources = []
    for path in metadata_source_paths(workflows_dir, data_dir, bundled_defaults_path, object_info_path):
        relative = relative_path(path, project_root)
        file_hash = file_sha256(path)
        digest.update(relative.encode("utf-8"))
        digest.update(file_hash.encode("utf-8"))
        sources.append({
            "path": relative,
            "sha256": file_hash,
            "sizeBytes": path.stat().st_size,
            "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return digest.hexdigest(), sources


def is_link_value(value):
    return isinstance(value, list) and len(value) >= 2 and isinstance(value[0], str)


def serializable_input_value(value):
    if is_link_value(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def object_info_class(object_info, class_type):
    if not isinstance(object_info, dict):
        return {}
    return object_info.get(class_type) or {}


def object_info_input_options(class_info, field):
    if not isinstance(class_info, dict):
        return []
    inputs = class_info.get("input") or {}
    for group in ("required", "optional"):
        fields = inputs.get(group) or {}
        spec = fields.get(field)
        if isinstance(spec, list) and spec and isinstance(spec[0], list):
            return [str(item) for item in spec[0]]
    return []


def model_bucket_for_field(class_type, field):
    field_text = str(field or "").lower()
    class_text = str(class_type or "").lower()
    if not (
        field_text.endswith("_name")
        or field_text in {"ckpt_name", "vae_name", "lora_name", "clip_name", "unet_name", "model_name"}
        or "model_name" in field_text
        or "checkpoint" in field_text
    ):
        return ""
    text = f"{class_text} {field_text}"
    if "lora" in text:
        return "loras"
    if "vae" in text:
        return "vae"
    if "clip" in text or "text_encoder" in text or "text encoder" in text:
        return "text_encoders"
    if "unet" in text or "diffusion" in text:
        return "unet"
    if "ckpt" in text or "checkpoint" in text:
        return "checkpoints"
    if "upscale" in text:
        return "upscale_models"
    if "wan" in text or "video" in text:
        return "video_models"
    if "model" in text:
        return "models"
    return ""


def add_model_value(model_map, bucket, value):
    if not bucket or not isinstance(value, str) or not value.strip():
        return
    values = model_map.setdefault(bucket, [])
    if value not in values:
        values.append(value)


def workflow_model_references(workflow, object_info=None):
    model_map = {}
    for node in workflow.values():
        class_type = node.get("class_type", "")
        class_info = object_info_class(object_info, class_type)
        for field, value in (node.get("inputs") or {}).items():
            if is_link_value(value):
                continue
            bucket = model_bucket_for_field(class_type, field)
            add_model_value(model_map, bucket, value)
            for option in object_info_input_options(class_info, field):
                add_model_value(model_map, bucket, option)
    return {key: sorted(values) for key, values in sorted(model_map.items())}


def workflow_model_reference_items(workflow, object_info=None):
    """Return selected model files with their owning ComfyUI node.

    `workflow_model_references()` intentionally also collects available widget
    options for the metadata catalog. Task history needs a different view: only
    the file value that was selected in the workflow submitted to RunPod.
    """
    tracked_buckets = {"checkpoints", "vae", "loras", "text_encoders", "unet", "video_models", "models"}
    items = []
    for node_id, node in sorted(workflow.items(), key=lambda item: str(item[0])):
        class_type = node.get("class_type", "")
        for field, value in (node.get("inputs") or {}).items():
            if is_link_value(value):
                continue
            bucket = model_bucket_for_field(class_type, field)
            if bucket not in tracked_buckets or not isinstance(value, str) or not value.strip():
                continue
            items.append({
                "bucket": bucket,
                "nodeId": str(node_id),
                "nodeTitle": node_title(node),
                "classType": class_type,
                "field": str(field),
                "value": value.strip(),
            })
    return items


def target_metadata(workflow, target):
    node_id = str(target.get("node", ""))
    field = target.get("field", "")
    node = workflow.get(node_id, {})
    return {
        "nodeId": node_id,
        "field": field,
        "classType": node.get("class_type", ""),
        "title": node_title(node) if node else "",
    }


def metadata_param_controls(workflow, segment_spec):
    controls = []
    for param_name, param_spec in (segment_spec.get("params") or {}).items():
        targets = [target_metadata(workflow, target) for target in (param_spec.get("targets") or [])]
        controls.append({
            "param": param_name,
            "uiKey": PARAM_UI_KEYS.get(param_name, param_name),
            "label": PARAM_LABELS.get(param_name, param_name),
            "type": param_spec.get("type", "float"),
            "min": param_spec.get("min"),
            "max": param_spec.get("max"),
            "step": param_spec.get("step"),
            "default": param_spec.get("default"),
            "randomizable": bool(param_spec.get("randomizable")),
            "sync": bool(param_spec.get("sync")),
            "options": param_spec.get("options") or [],
            "description": param_spec.get("description") or param_spec.get("note") or PARAM_DESCRIPTIONS.get(param_name, ""),
            "note": param_spec.get("note", ""),
            "targets": targets,
        })
    return controls


def workflow_nodes_metadata(workflow, object_info=None):
    nodes = []
    for node_id, node in sorted(workflow.items(), key=lambda item: item[0]):
        class_type = node.get("class_type", "")
        class_info = object_info_class(object_info, class_type)
        inputs = []
        links = []
        for field, value in (node.get("inputs") or {}).items():
            if is_link_value(value):
                links.append({"field": field, "sourceNodeId": value[0], "sourceOutput": value[1]})
                continue
            bucket = model_bucket_for_field(class_type, field)
            inputs.append({
                "field": field,
                "value": serializable_input_value(value),
                "modelBucket": bucket,
                "options": object_info_input_options(class_info, field),
            })
        nodes.append({
            "nodeId": node_id,
            "classType": class_type,
            "title": node_title(node),
            "inputs": inputs,
            "links": links,
            "hasObjectInfo": bool(class_info),
        })
    return nodes


def build_workflow_widget_metadata(workflow_id, workflow, workflows_dir: Path, object_info=None):
    param_config = load_param_config(workflow_id, workflows_dir) or {}
    segments = find_segments(workflow)
    segment_specs = param_config.get("segments") or []
    video_nodes = [
        node_id for node_id, node in workflow.items()
        if node.get("class_type") in VIDEO_NODE_TYPES
    ]
    if segments:
        segment_items = []
        for index, segment in enumerate(segments, start=1):
            video_node = segment.get("video_node")
            spec = segment_specs[index - 1] if index - 1 < len(segment_specs) else {}
            segment_items.append({
                "index": index,
                "nodeId": video_node,
                "subgraphName": node_title(workflow.get(video_node, {})),
                "displayName": f"{node_title(workflow.get(video_node, {}))}_{index}",
                "classType": workflow.get(video_node, {}).get("class_type", ""),
                "positiveNode": segment.get("positive_node"),
                "negativeNode": segment.get("negative_node"),
                "startImageNode": segment.get("start_image_node"),
                "endImageNode": segment.get("end_image_node"),
                "params": metadata_param_controls(workflow, spec),
            })
    else:
        video_node = video_nodes[0] if video_nodes else ""
        spec = segment_specs[0] if segment_specs else {}
        ordered_keyframes = find_keyframe_images_ordered(workflow, [])
        segment_items = [{
            "index": 1,
            "nodeId": video_node,
            "subgraphName": node_title(workflow.get(video_node, {})),
            "displayName": f"{node_title(workflow.get(video_node, {}))}_1",
            "classType": workflow.get(video_node, {}).get("class_type", ""),
            "positiveNode": find_prompt_node(workflow, "Positive"),
            "negativeNode": find_prompt_node(workflow, "Negative"),
            "startImageNode": ordered_keyframes[0] if ordered_keyframes else "",
            "endImageNode": "",
            "params": metadata_param_controls(workflow, spec),
        }]
    return {
        "workflowId": workflow_id,
        "name": Path(workflow_id).stem,
        "nodeCount": len(workflow),
        "nodes": workflow_nodes_metadata(workflow, object_info),
        "segments": segment_items,
        "models": workflow_model_references(workflow, object_info),
    }


def merge_model_metadata(workflow_metadata_items):
    merged = {}
    for item in workflow_metadata_items.values():
        for bucket, values in (item.get("models") or {}).items():
            merged.setdefault(bucket, [])
            for value in values:
                if value not in merged[bucket]:
                    merged[bucket].append(value)
    return {key: sorted(values) for key, values in sorted(merged.items())}


def rebuild_metadata(project_root: Path, workflows_dir: Path, data_dir: Path, metadata_dir: Path, bundled_defaults_path: Path):
    metadata_dir.mkdir(parents=True, exist_ok=True)
    object_info_path = metadata_dir / "comfyui-object-info.json"
    workflow_widget_map_path = metadata_dir / "workflow-widget-map.json"
    models_metadata_path = metadata_dir / "comfyui-models.json"
    metadata_manifest_path = metadata_dir / "metadata-manifest.json"
    object_info = read_json_if_exists(object_info_path, {})
    fingerprint, sources = metadata_fingerprint(workflows_dir, data_dir, bundled_defaults_path, object_info_path, project_root)
    workflows = {}
    for path in workflow_files(workflows_dir):
        workflow = read_json(path)
        workflows[path.name] = build_workflow_widget_metadata(path.name, workflow, workflows_dir, object_info)
    models = merge_model_metadata(workflows)
    manifest = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "workflow-json",
        "workflowDirectory": relative_path(workflows_dir, project_root),
        "fingerprint": fingerprint,
        "workflowCount": len(workflows),
        "hasObjectInfoSnapshot": object_info_path.exists(),
        "sources": sources,
    }
    write_json(workflow_widget_map_path, {
        "manifest": manifest,
        "workflows": workflows,
    })
    write_json(models_metadata_path, {
        "manifest": manifest,
        "models": models,
    })
    write_json(metadata_manifest_path, manifest)
    return manifest


def ensure_metadata_current(project_root: Path, workflows_dir: Path, data_dir: Path, metadata_dir: Path, bundled_defaults_path: Path, force=False):
    object_info_path = metadata_dir / "comfyui-object-info.json"
    workflow_widget_map_path = metadata_dir / "workflow-widget-map.json"
    models_metadata_path = metadata_dir / "comfyui-models.json"
    metadata_manifest_path = metadata_dir / "metadata-manifest.json"
    fingerprint, _ = metadata_fingerprint(workflows_dir, data_dir, bundled_defaults_path, object_info_path, project_root)
    manifest = read_json_if_exists(metadata_manifest_path, {})
    if (
        not force
        and manifest.get("fingerprint") == fingerprint
        and workflow_widget_map_path.exists()
        and models_metadata_path.exists()
    ):
        return manifest
    return rebuild_metadata(project_root, workflows_dir, data_dir, metadata_dir, bundled_defaults_path)


def metadata_status(project_root: Path, workflows_dir: Path, data_dir: Path, metadata_dir: Path, bundled_defaults_path: Path):
    manifest = ensure_metadata_current(project_root, workflows_dir, data_dir, metadata_dir, bundled_defaults_path)
    object_info_path = metadata_dir / "comfyui-object-info.json"
    workflow_widget_map_path = metadata_dir / "workflow-widget-map.json"
    models_metadata_path = metadata_dir / "comfyui-models.json"
    return {
        "ok": True,
        "metadataDir": str(metadata_dir),
        "manifest": manifest,
        "files": {
            "objectInfo": {
                "path": str(object_info_path),
                "exists": object_info_path.exists(),
            },
            "workflowWidgetMap": {
                "path": str(workflow_widget_map_path),
                "exists": workflow_widget_map_path.exists(),
            },
            "models": {
                "path": str(models_metadata_path),
                "exists": models_metadata_path.exists(),
            },
        },
    }


def workflow_widget_metadata(workflow_id: str, project_root: Path, workflows_dir: Path, data_dir: Path, metadata_dir: Path, bundled_defaults_path: Path):
    ensure_metadata_current(project_root, workflows_dir, data_dir, metadata_dir, bundled_defaults_path)
    workflow_widget_map_path = metadata_dir / "workflow-widget-map.json"
    data = read_json_if_exists(workflow_widget_map_path, {"workflows": {}})
    item = (data.get("workflows") or {}).get(Path(workflow_id).name)
    if not item:
        raise FileNotFoundError(workflow_id)
    return item


def model_metadata(project_root: Path, workflows_dir: Path, data_dir: Path, metadata_dir: Path, bundled_defaults_path: Path):
    ensure_metadata_current(project_root, workflows_dir, data_dir, metadata_dir, bundled_defaults_path)
    return read_json_if_exists(metadata_dir / "comfyui-models.json", {"models": {}})
