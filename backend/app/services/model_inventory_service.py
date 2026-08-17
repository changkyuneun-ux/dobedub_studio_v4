from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.services.metadata_loader import is_link_value, node_title
from backend.app.services.workflow_parser import workflow_files


MODEL_FILE_SUFFIXES = {".bin", ".ckpt", ".gguf", ".pt", ".pth", ".safetensors"}

# A workflow's semantic model type does not always match the literal ComfyUI
# directory name. For example, current WAN workflows use `unet`, while other
# ComfyUI installations use `diffusion_models` for the same model family.
MODEL_BUCKET_DIRECTORIES = {
    "checkpoints": ("checkpoints",),
    "controlnet": ("controlnet",),
    "clip_vision": ("clip_vision",),
    "embeddings": ("embeddings",),
    "loras": ("loras",),
    "text_encoders": ("text_encoders", "clip"),
    "unet": ("unet", "diffusion_models"),
    "upscale_models": ("upscale_models",),
    "vae": ("vae",),
    "video_models": ("video_models",),
}


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _model_bucket(class_type: str, field: str) -> str:
    text = f"{class_type} {field}".lower()
    if "controlnet" in text or "control_net" in text:
        return "controlnet"
    if "clip_vision" in text or "clipvision" in text:
        return "clip_vision"
    if "embedding" in text:
        return "embeddings"
    if "upscale" in text:
        return "upscale_models"
    if "lora" in text:
        return "loras"
    if "vae" in text:
        return "vae"
    if "clip" in text or "text_encoder" in text or "text encoder" in text:
        return "text_encoders"
    if "unet" in text or "diffusion" in text:
        return "unet"
    if "checkpoint" in text or "ckpt" in text:
        return "checkpoints"
    if "video" in text and ("model" in text or "name" in text):
        return "video_models"
    return ""


def _normalize_model_name(value: str) -> str:
    return value.replace("\\", "/").lstrip("/").strip()


def _looks_like_model_file(value: str) -> bool:
    return Path(value).suffix.lower() in MODEL_FILE_SUFFIXES


def extract_workflow_references(workflows_dir: Path) -> list[dict]:
    """Extract only values selected by workflow nodes, never object-info options."""
    references = []
    for workflow_path in workflow_files(workflows_dir):
        workflow = _read_json(workflow_path)
        for node_id, node in workflow.items():
            class_type = str(node.get("class_type") or "")
            title = node_title(node)
            for field, value in (node.get("inputs") or {}).items():
                if is_link_value(value) or not isinstance(value, str):
                    continue
                model_name = _normalize_model_name(value)
                bucket = _model_bucket(class_type, str(field))
                if not bucket or not _looks_like_model_file(model_name):
                    continue
                references.append({
                    "workflowId": workflow_path.name,
                    "nodeId": str(node_id),
                    "nodeTitle": title,
                    "classType": class_type,
                    "field": str(field),
                    "bucket": bucket,
                    "fileName": Path(model_name).name,
                    "referencePath": model_name,
                })
    return sorted(references, key=lambda item: (item["bucket"], item["fileName"], item["workflowId"], item["nodeId"]))


def scan_model_files(models_dir: Path) -> list[dict]:
    files = []
    if not models_dir.is_dir():
        return files
    for bucket, directories in MODEL_BUCKET_DIRECTORIES.items():
        for directory in directories:
            base = models_dir / directory
            if not base.is_dir():
                continue
            for path in sorted(candidate for candidate in base.rglob("*") if candidate.is_file()):
                if path.suffix.lower() not in MODEL_FILE_SUFFIXES:
                    continue
                files.append({
                    "bucket": bucket,
                    "directory": directory,
                    "fileName": path.name,
                    "relativePath": str(path.relative_to(models_dir)),
                    "bucketRelativePath": str(path.relative_to(base)),
                    "sizeBytes": path.stat().st_size,
                })
    return files


def _reference_summary(references: list[dict]) -> list[dict]:
    summary: dict[tuple[str, str], dict] = {}
    for reference in references:
        key = (reference["bucket"], reference["referencePath"])
        item = summary.setdefault(key, {
            "bucket": reference["bucket"],
            "fileName": reference["fileName"],
            "referencePath": reference["referencePath"],
            "workflows": set(),
            "nodes": [],
        })
        item["workflows"].add(reference["workflowId"])
        node = {
            "workflowId": reference["workflowId"],
            "nodeId": reference["nodeId"],
            "nodeTitle": reference["nodeTitle"],
            "classType": reference["classType"],
            "field": reference["field"],
        }
        if node not in item["nodes"]:
            item["nodes"].append(node)
    result = []
    for item in summary.values():
        result.append({
            **item,
            "workflows": sorted(item["workflows"]),
            "nodes": sorted(item["nodes"], key=lambda node: (node["workflowId"], node["nodeId"], node["field"])),
        })
    return sorted(result, key=lambda item: (item["bucket"], item["fileName"], item["referencePath"]))


def _matches_reference(model_file: dict, reference: dict) -> bool:
    if model_file["bucket"] != reference["bucket"]:
        return False
    reference_path = reference["referencePath"]
    return model_file["bucketRelativePath"] == reference_path or model_file["fileName"] == reference["fileName"]


def build_model_inventory(workflows_dir: Path, models_dir: Path | None = None) -> dict:
    references = extract_workflow_references(workflows_dir)
    reference_summary = _reference_summary(references)
    inventory_available = models_dir is not None and models_dir.is_dir()
    model_files = scan_model_files(models_dir) if inventory_available and models_dir else []
    referenced_files = []
    missing_references = []
    used_paths = set()

    for reference in reference_summary:
        matches = [model_file for model_file in model_files if _matches_reference(model_file, reference)]
        if matches:
            referenced_files.append({**reference, "files": matches, "status": "present"})
            used_paths.update(model_file["relativePath"] for model_file in matches)
        elif inventory_available:
            missing_references.append({**reference, "status": "missing"})
        else:
            referenced_files.append({**reference, "files": [], "status": "not-scanned"})

    unused_candidates = [
        {**model_file, "status": "unused-candidate"}
        for model_file in model_files
        if model_file["relativePath"] not in used_paths
    ]
    bucket_summary = defaultdict(lambda: {"referenced": 0, "present": 0, "missing": 0, "unusedCandidates": 0, "unusedBytes": 0})
    for reference in reference_summary:
        bucket_summary[reference["bucket"]]["referenced"] += 1
    for reference in referenced_files:
        if reference["status"] == "present":
            bucket_summary[reference["bucket"]]["present"] += 1
    for reference in missing_references:
        bucket_summary[reference["bucket"]]["missing"] += 1
    for candidate in unused_candidates:
        bucket_summary[candidate["bucket"]]["unusedCandidates"] += 1
        bucket_summary[candidate["bucket"]]["unusedBytes"] += candidate["sizeBytes"]

    return {
        **timestamp_fields("generatedAt", utc_now(), naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="model-inventory"),
        "workflowsDir": str(workflows_dir),
        "modelsDir": str(models_dir) if models_dir else "",
        "inventoryAvailable": inventory_available,
        "safetyNotice": "unusedCandidates are comparison candidates only. Move/quarantine and test every active workflow before deletion.",
        "workflowReferences": references,
        "referencedFiles": referenced_files,
        "missingReferences": missing_references,
        "unusedCandidates": unused_candidates,
        "summary": {
            "workflowCount": len({reference["workflowId"] for reference in references}),
            "referenceCount": len(reference_summary),
            "actualModelFileCount": len(model_files),
            "unusedCandidateCount": len(unused_candidates),
            "unusedCandidateBytes": sum(candidate["sizeBytes"] for candidate in unused_candidates),
            "buckets": {bucket: values for bucket, values in sorted(bucket_summary.items())},
        },
    }


def write_inventory_reports(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "workflow-model-inventory.json"
    csv_path = output_dir / "workflow-model-inventory.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "recordType", "status", "bucket", "fileName", "relativePath", "sizeBytes",
            "referencePath", "workflows", "nodes",
        ])
        writer.writeheader()
        for reference in report["referencedFiles"]:
            writer.writerow({
                "recordType": "reference",
                "status": reference["status"],
                "bucket": reference["bucket"],
                "fileName": reference["fileName"],
                "referencePath": reference["referencePath"],
                "workflows": ", ".join(reference["workflows"]),
                "nodes": "; ".join(f"{node['workflowId']}:{node['nodeId']}:{node['field']}" for node in reference["nodes"]),
            })
        for candidate in report["unusedCandidates"]:
            writer.writerow({
                "recordType": "model-file",
                "status": candidate["status"],
                "bucket": candidate["bucket"],
                "fileName": candidate["fileName"],
                "relativePath": candidate["relativePath"],
                "sizeBytes": candidate["sizeBytes"],
            })
    return json_path, csv_path
