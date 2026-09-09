from __future__ import annotations

import base64
import json
import re
import uuid
from pathlib import Path
from typing import Callable

from backend.app.services.asset_storage import VIDEO_SUFFIXES, safe_filename
from backend.app.services.workflow_parser import link_node, load_param_config


def save_video_nodes(workflow: dict) -> list[str]:
    return [
        node_id for node_id, node in workflow.items()
        if node.get("class_type") == "SaveVideo"
    ]


def save_video_template_inputs(workflow: dict) -> dict:
    for node_id in save_video_nodes(workflow):
        inputs = workflow.get(node_id, {}).get("inputs") or {}
        if inputs:
            return json.loads(json.dumps(inputs))
    return {"format": "auto", "codec": "auto"}


def next_numeric_node_id(workflow: dict) -> str:
    numeric_ids = [
        int(node_id) for node_id in workflow
        if str(node_id).isdigit()
    ]
    return str((max(numeric_ids) if numeric_ids else 1000) + 1)


def segment_create_video_nodes(workflow: dict, workflow_id: str, segment_count: int, workflows_dir: Path) -> list[str]:
    param_config = load_param_config(workflow_id, workflows_dir)
    specs = (param_config or {}).get("segments") or []
    result = []
    for index in range(segment_count):
        params = (specs[index].get("params") if index < len(specs) else {}) or {}
        fps_targets = params.get("fps", {}).get("targets") or []
        create_node = ""
        for target in fps_targets:
            node_id = str(target.get("node"))
            if workflow.get(node_id, {}).get("class_type") == "CreateVideo":
                create_node = node_id
                break
        result.append(create_node)
    return result


def existing_save_video_outputs(workflow: dict, workflow_id: str, segments: list[dict], workflows_dir: Path) -> dict:
    create_nodes = segment_create_video_nodes(workflow, workflow_id, len(segments), workflows_dir)
    final_nodes = []
    segment_outputs = []

    for save_node in save_video_nodes(workflow):
        inputs = workflow.get(save_node, {}).get("inputs") or {}
        filename_prefix = str(inputs.get("filename_prefix") or "")
        linked_create_node = link_node(inputs, "video")
        segment_index = None

        segment_match = re.search(r"segment[_-]?(\d+)", filename_prefix, re.IGNORECASE)
        if segment_match:
            segment_index = int(segment_match.group(1))
        elif linked_create_node and linked_create_node in create_nodes:
            segment_index = create_nodes.index(linked_create_node) + 1

        is_segment_output = bool(segment_index and len(segments) > 1 and "final" not in filename_prefix.lower())
        if is_segment_output:
            segment_outputs.append({
                "segment": segment_index,
                "createVideoNode": linked_create_node,
                "saveNode": save_node,
                "filenamePrefix": filename_prefix,
            })
            continue

        final_nodes.append(save_node)

    if not final_nodes and save_video_nodes(workflow):
        final_nodes.append(save_video_nodes(workflow)[0])

    segment_outputs.sort(key=lambda item: item.get("segment") or 0)
    return {"finalOutputNodes": final_nodes, "segmentOutputs": segment_outputs}


def workflow_output_token(workflow_id: str) -> str:
    match = re.search(r"(\d+)\s*[-_]?key", workflow_id or "", re.IGNORECASE)
    if match:
        return f"{match.group(1)}key"
    stem = Path(workflow_id or "workflow").stem
    return re.sub(r"[^A-Za-z0-9]+", "", stem) or "workflow"


def first_upload_stem(job: dict) -> str:
    payload = job.get("payload") or {}
    keyframes = payload.get("keyframes") or []
    first_name = keyframes[0].get("fileName") if keyframes else ""
    return Path(safe_filename(first_name or "upload")).stem or "upload"


def output_file_name(
    kind: str,
    item: dict,
    index: int,
    job: dict,
    metadata: dict | None = None,
    total: int = 1,
) -> str:
    original = safe_filename(item.get("filename") or f"{kind}_{index}")
    suffix = Path(original).suffix
    default_suffix = {"videos": ".mp4", "images": ".png", "gifs": ".gif"}.get(kind, "")
    if not suffix:
        suffix = default_suffix
    sequence = job.setdefault("outputSequence", uuid.uuid4().hex[:6])
    metadata = metadata or {}
    if metadata.get("outputRole") == "segment":
        role_suffix = f"_segment{metadata.get('segmentIndex') or index}"
    elif total > 1 and metadata.get("outputRole") == "final":
        role_suffix = "_final"
    else:
        role_suffix = f"_{index:02d}" if index > 1 else ""
    return f"{first_upload_stem(job)}_{workflow_output_token(job.get('workflowId'))}_{sequence}{role_suffix}{suffix}"


def infer_output_metadata(item: dict, index: int, total: int, job: dict) -> dict:
    patch_summary = job.get("patchSummary") or {}
    segment_outputs = patch_summary.get("segmentOutputs") or []
    final_nodes = set(str(node_id) for node_id in (patch_summary.get("finalOutputNodes") or []))
    node_id = str(item.get("node_id") or item.get("nodeId") or item.get("node") or "")
    filename = str(item.get("filename") or item.get("fileName") or "")
    segment_count = len((job.get("payload") or {}).get("segments") or [])

    for output in segment_outputs:
        if node_id and node_id == str(output.get("saveNode")):
            return {"outputRole": "segment", "segmentIndex": output.get("segment")}
    if node_id and node_id in final_nodes:
        return {"outputRole": "final", "segmentIndex": None}

    match = re.search(r"segment[_-]?(\d+)", filename, re.IGNORECASE)
    if match:
        return {"outputRole": "segment", "segmentIndex": int(match.group(1))}

    if segment_count <= 1:
        return {"outputRole": "final", "segmentIndex": 1}
    if total == segment_count:
        return {"outputRole": "segment", "segmentIndex": index}
    if total == segment_count + 1:
        return (
            {"outputRole": "final", "segmentIndex": None}
            if index == 1
            else {"outputRole": "segment", "segmentIndex": index - 1}
        )
    return {"outputRole": "final" if index == 1 else "extra", "segmentIndex": None}


def save_runpod_outputs(
    result: dict,
    job: dict,
    outputs_dir: Path,
    register_asset: Callable[[Path, str], dict],
) -> dict:
    output = result.get("output") or {}
    saved = []
    remote_urls = []
    outputs_dir.mkdir(parents=True, exist_ok=True)
    output_items = []
    for kind in ("videos", "images", "gifs"):
        for item in output.get(kind) or []:
            output_items.append((kind, item))
    total = len(output_items)
    for index, (kind, item) in enumerate(output_items, start=1):
        data = item.get("data")
        if item.get("type") == "s3_object":
            metadata = infer_output_metadata(item, index, total, job)
            asset_id = s3_output_asset_id(item, index, job)
            file_name = safe_filename(item.get("filename") or item.get("fileName") or f"{kind}_{index}")
            bucket = str(item.get("bucket") or "")
            storage_key = str(item.get("key") or item.get("storageKey") or "")
            mime_type = str(item.get("mimeType") or "application/octet-stream")
            effective_kind = "videos" if mime_type.startswith("video/") or Path(file_name).suffix.lower() in VIDEO_SUFFIXES else kind
            saved.append({
                "assetId": asset_id,
                "fileName": file_name,
                "downloadUrl": f"/api/files/{asset_id}",
                "kind": effective_kind,
                "mimeType": mime_type,
                "sizeBytes": int(item.get("sizeBytes") or 0),
                "outputRole": metadata.get("outputRole"),
                "segmentIndex": metadata.get("segmentIndex"),
                "storageBackend": "s3",
                "storageKey": storage_key,
                "publicUrl": f"s3://{bucket}/{storage_key}" if bucket and storage_key else None,
            })
            continue
        if item.get("type") == "s3_url" and data:
            remote_urls.append(data)
            continue
        if not data:
            continue
        metadata = infer_output_metadata(item, index, total, job)
        file_name = output_file_name(kind, item, index, job, metadata, total)
        raw = base64.b64decode(data)
        path = outputs_dir / file_name
        with path.open("wb") as stream:
            stream.write(raw)
        asset = register_asset(path, f"output_{kind.rstrip('s')}")
        effective_kind = "videos" if asset["mimeType"].startswith("video/") or path.suffix.lower() in VIDEO_SUFFIXES else kind
        saved.append({
            "assetId": asset["assetId"],
            "fileName": asset["fileName"],
            "downloadUrl": f"/api/files/{asset['assetId']}",
            "kind": effective_kind,
            "mimeType": asset["mimeType"],
            "sizeBytes": asset["sizeBytes"],
            "outputRole": metadata.get("outputRole"),
            "segmentIndex": metadata.get("segmentIndex"),
        })
    return {"assets": saved, "remoteUrls": remote_urls}


def s3_output_asset_id(item: dict, index: int, job: dict) -> str:
    task_id = str(job.get("taskId") or (job.get("payload") or {}).get("taskId") or "").strip()
    if task_id:
        safe_task_id = re.sub(r"[^A-Za-z0-9_-]+", "_", task_id).strip("_")[:48]
        return f"asset_{safe_task_id}_{index:03d}"
    return str(item.get("assetId") or f"asset_{uuid.uuid4().hex[:12]}")
