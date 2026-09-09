from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Callable

from backend.app.services import metadata_loader, workflow_parser
from backend.app.services.workflow_parser import PARAM_LABELS, PARAM_UI_KEYS


I2V_INPUT_IMAGE_REQUIRED_MESSAGE = "입력파일을 업로드하세요. 이 워크플로우는 i2v 전용입니다. t2i, t2v는 지원하지 않습니다."
MAX_GENERATION_SEED = (1 << 53) - 1
WAN_IMAGE_TO_VIDEO_CLASS = "WanImageToVideo"
WAN_VIDEO_NODE_CLASSES = frozenset({
    "WanImageToVideo",
    "WanFirstLastFrameToVideo",
    "WanFunControlToVideo",
    "WanVaceToVideo",
})
WAN_PIXEL_BUDGET = {"sd": 409_600, "hd": 921_600}
WAN_MULTIPLE = 16
WAN_MAX_FRAMES = 81
WAN_MAX_TOTAL_FRAMES = 162


def normalize_resolution_tier(tier: str | None) -> str:
    normalized = str(tier or "sd").strip().lower()
    if normalized not in WAN_PIXEL_BUDGET:
        allowed = ", ".join(sorted(WAN_PIXEL_BUDGET))
        raise ValueError(f"resolutionTier must be one of: {allowed}")
    return normalized


def fit_wan_size(img_w: int, img_h: int, tier: str = "sd") -> tuple[int, int]:
    width = int(img_w)
    height = int(img_h)
    if width <= 0 or height <= 0:
        raise ValueError("Wan source image dimensions must be positive integers.")
    budget = WAN_PIXEL_BUDGET[normalize_resolution_tier(tier)]
    scale = min(1.0, (budget / (width * height)) ** 0.5)
    fitted_width = max(WAN_MULTIPLE, int(width * scale) // WAN_MULTIPLE * WAN_MULTIPLE)
    fitted_height = max(WAN_MULTIPLE, int(height * scale) // WAN_MULTIPLE * WAN_MULTIPLE)
    while fitted_width * fitted_height > budget:
        if fitted_width >= fitted_height:
            fitted_width -= WAN_MULTIPLE
        else:
            fitted_height -= WAN_MULTIPLE
    return fitted_width, fitted_height


def pick_wan_size(img_w: int, img_h: int) -> tuple[int, int]:
    return fit_wan_size(img_w, img_h, "sd")


def wan_image_to_video_nodes(workflow: dict) -> list[tuple[str, dict]]:
    return wan_video_nodes(workflow)


def wan_video_nodes(workflow: dict) -> list[tuple[str, dict]]:
    return [
        (str(node_id), node)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") in WAN_VIDEO_NODE_CLASSES
    ]


def _literal_int(value: object, *, class_type: str, node_id: str, field: str) -> int:
    if isinstance(value, bool) or isinstance(value, list) or value is None:
        raise ValueError(f"{class_type} node {node_id} {field} must be a literal integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{class_type} node {node_id} {field} must be a literal integer.") from exc


def wan_image_to_video_generation_snapshot(workflow: dict, *, tier: str = "sd") -> list[dict]:
    normalized_tier = normalize_resolution_tier(tier)
    budget = WAN_PIXEL_BUDGET[normalized_tier]
    generation: list[dict] = []
    total_length = 0
    for node_id, node in wan_video_nodes(workflow):
        class_type = str(node.get("class_type") or "WanVideo")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        width = _literal_int(inputs.get("width"), class_type=class_type, node_id=node_id, field="width")
        height = _literal_int(inputs.get("height"), class_type=class_type, node_id=node_id, field="height")
        length = _literal_int(inputs.get("length"), class_type=class_type, node_id=node_id, field="length")
        batch_size = _literal_int(inputs.get("batch_size", inputs.get("batchSize", 1)), class_type=class_type, node_id=node_id, field="batch_size")
        pixel_count = width * height
        if width <= 0 or height <= 0:
            raise ValueError(f"{class_type} node {node_id} width/height must be positive.")
        if length <= 0:
            raise ValueError(f"{class_type} node {node_id} length must be positive.")
        if width % WAN_MULTIPLE or height % WAN_MULTIPLE:
            raise ValueError(f"{class_type} node {node_id} width/height must be multiples of {WAN_MULTIPLE}.")
        if pixel_count > budget:
            raise ValueError(f"{class_type} node {node_id} pixel count {pixel_count} exceeds {normalized_tier} budget {budget}.")
        if length == 161:
            raise ValueError(f"{class_type} node {node_id} length=161 is prohibited.")
        if length > WAN_MAX_FRAMES:
            raise ValueError(f"{class_type} node {node_id} length must be <= {WAN_MAX_FRAMES}.")
        if batch_size != 1:
            raise ValueError(f"{class_type} node {node_id} batch_size must be 1.")
        total_length += length
        generation.append({
            "nodeId": node_id,
            "classType": class_type,
            "width": width,
            "height": height,
            "length": length,
            "batchSize": batch_size,
            "pixelCount": pixel_count,
            "tier": normalized_tier,
            "pixelBudget": budget,
        })
    if total_length > WAN_MAX_TOTAL_FRAMES:
        raise ValueError(f"total Wan video length must be <= {WAN_MAX_TOTAL_FRAMES}.")
    return generation


def validate_i2v_input_images(payload: dict, workflow: dict, segments: list[dict]) -> None:
    """Require one uploaded asset for every image input the selected i2v workflow needs."""
    required_count = workflow_parser.keyframe_count(workflow, segments)
    if required_count < 1:
        raise ValueError(I2V_INPUT_IMAGE_REQUIRED_MESSAGE)

    uploaded_keyframes = [
        keyframe
        for keyframe in payload.get("keyframes") or []
        if isinstance(keyframe, dict) and str(keyframe.get("uploadId") or "").strip()
    ]
    uploaded_indices = [str(keyframe.get("index") or "") for keyframe in uploaded_keyframes]
    expected_indices = set(range(1, required_count + 1))
    if (
        len(uploaded_keyframes) != required_count
        or not all(index.isdigit() for index in uploaded_indices)
        or {int(index) for index in uploaded_indices} != expected_indices
    ):
        raise ValueError(I2V_INPUT_IMAGE_REQUIRED_MESSAGE)


def apply_keyframe_images(workflow: dict, image_names: list[str], segments: list[dict] | None = None) -> list[dict]:
    applied = []
    for node_id, file_name in zip(workflow_parser.find_keyframe_images_ordered(workflow, segments), image_names):
        if node_id and file_name and workflow.get(node_id):
            workflow[node_id]["inputs"]["image"] = file_name
            applied.append({"node": node_id, "image": file_name})
    return applied


def validate_applied_images(workflow: dict, image_names: list[str], segments: list[dict] | None = None) -> None:
    missing = []
    nodes = workflow_parser.find_keyframe_images_ordered(workflow, segments)
    for node_id, expected_name in zip(nodes, image_names):
        actual_name = workflow.get(node_id, {}).get("inputs", {}).get("image")
        if actual_name != expected_name:
            missing.append({"node": node_id, "expected": expected_name, "actual": actual_name})
    if missing:
        raise ValueError(f"Workflow image patch failed: {json.dumps(missing, ensure_ascii=False)}")


def apply_image_slots(workflow: dict, image_names: dict[str, str]) -> list[dict]:
    slots = workflow_parser.find_image_slots(workflow)
    applied = []
    for role, file_name in image_names.items():
        node_id = slots.get(role)
        if node_id and file_name and workflow.get(node_id):
            workflow[node_id]["inputs"]["image"] = file_name
            applied.append({"role": role, "node": node_id, "image": file_name})
    return applied


def set_prompt_text(workflow: dict, node_id: str | None, text: str | None) -> str | None:
    if not node_id or text is None:
        return node_id
    inputs = workflow.get(node_id, {}).setdefault("inputs", {})
    inputs[workflow_parser.prompt_input_field(workflow, node_id)] = str(text).strip()
    return node_id


def apply_segment_prompts(
    workflow: dict,
    segments: list[dict],
    positive_texts: list[str] | None = None,
    negative_additions: list[str] | None = None,
) -> list[dict]:
    positive_texts = positive_texts or []
    negative_additions = negative_additions or []
    applied = []
    for index, segment in enumerate(segments):
        positive_text = positive_texts[index] if index < len(positive_texts) else ""
        negative_text = negative_additions[index] if index < len(negative_additions) else ""
        if segment.get("positive_node") and str(positive_text).strip():
            set_prompt_text(workflow, segment["positive_node"], positive_text)
            applied.append({"segment": index + 1, "node": segment["positive_node"], "field": "positive"})
        if segment.get("negative_node") and str(negative_text).strip():
            set_prompt_text(workflow, segment["negative_node"], negative_text)
            applied.append({"segment": index + 1, "node": segment["negative_node"], "field": "negative"})
    return applied


def apply_single_prompt(workflow: dict, positive_text: str | None, negative_text: str | None) -> list[dict]:
    applied = []
    positive_node = workflow_parser.find_prompt_node(workflow, "Positive")
    negative_node = workflow_parser.find_prompt_node(workflow, "Negative")
    if positive_node and str(positive_text or "").strip():
        set_prompt_text(workflow, positive_node, positive_text)
        applied.append({"node": positive_node, "field": "positive"})
    if negative_node and str(negative_text or "").strip():
        set_prompt_text(workflow, negative_node, negative_text)
        applied.append({"node": negative_node, "field": "negative"})
    return applied


def build_submission_request_snapshot(payload: dict, images: list[dict]) -> dict:
    """Record the user-visible inputs that are about to be embedded in a RunPod request.

    The handler accepts uploaded bytes separately in ``input.images`` while the
    prompts are written into the patched workflow.  Persisting this compact
    snapshot makes that pairing inspectable without storing a second copy of
    the image bytes or server-local file paths.
    """
    ordered_keyframes = sorted(
        (keyframe for keyframe in payload.get("keyframes") or [] if isinstance(keyframe, dict)),
        key=lambda keyframe: int(keyframe.get("index") or 0),
    )
    input_images = []
    for index, keyframe in enumerate(ordered_keyframes):
        asset_id = str(keyframe.get("uploadId") or "").strip()
        if not asset_id:
            continue
        runpod_image = images[index] if index < len(images) else {}
        input_images.append({
            "slotIndex": int(keyframe.get("index") or index + 1),
            "assetId": asset_id,
            "sourceFileName": str(keyframe.get("fileName") or "").strip(),
            "runpodFileName": str(runpod_image.get("name") or "").strip(),
        })

    prompts = []
    settings = []
    for index, segment in enumerate(payload.get("segments") or [], start=1):
        if not isinstance(segment, dict):
            continue
        config = segment.get("config") if isinstance(segment.get("config"), dict) else {}
        prompts.append({
            "segmentIndex": int(segment.get("index") or index),
            "positivePrompt": str(segment.get("positivePrompt") or ""),
            "negativePrompt": str(segment.get("negativePromptAddition") or segment.get("negativePrompt") or ""),
        })
        settings.append({
            "segmentIndex": int(segment.get("index") or index),
            "length": config.get("length") or config.get("frames") or config.get("frame_count"),
            "fps": config.get("fps") or config.get("output_fps"),
        })
    return {
        "workflowId": str(payload.get("workflowId") or ""),
        "resolutionTier": normalize_resolution_tier(payload.get("resolutionTier")),
        "inputImages": input_images,
        "prompts": prompts,
        "videoSettings": settings,
    }


def ui_config_to_param_config(node_config: dict) -> dict:
    return {
        "width": node_config.get("width"),
        "height": node_config.get("height"),
        "fps": node_config.get("fps"),
        "output_fps": node_config.get("outputFps", node_config.get("output_fps")),
        "frames": node_config.get("frames", node_config.get("frame_count", node_config.get("length"))),
        "duration_seconds": node_config.get("durationSeconds", node_config.get("duration_seconds")),
        "steps": node_config.get("steps"),
        "cfg_scale": node_config.get("cfgScale", node_config.get("cfg_scale")),
        "motion_shift": node_config.get("motionShift", node_config.get("motion_shift")),
        "bit_depth": node_config.get("bitDepth", node_config.get("bit_depth")),
        "video_format": node_config.get("videoFormat", node_config.get("video_format")),
        "video_codec": node_config.get("videoCodec", node_config.get("video_codec")),
    }


def _wan_size_from_config(node_config: dict, tier: str = "sd") -> tuple[int, int] | None:
    width = node_config.get("width")
    height = node_config.get("height")
    if width is None or height is None:
        return None
    if isinstance(width, str) and not width.strip():
        return None
    if isinstance(height, str) and not height.strip():
        return None
    try:
        return fit_wan_size(int(width), int(height), tier)
    except (TypeError, ValueError):
        return None


def _wan_resolution_param_value(workflow: dict, param_name: str, param_spec: dict, node_config: dict, tier: str = "sd"):
    if param_name not in {"width", "height"}:
        return None
    preset = _wan_size_from_config(node_config, tier)
    if not preset:
        return None
    has_wan_target = any(
        workflow.get(str(target.get("node")), {}).get("class_type") in WAN_VIDEO_NODE_CLASSES
        for target in param_spec.get("targets") or []
    )
    if not has_wan_target:
        return None
    return preset[0] if param_name == "width" else preset[1]


def validate_segment_resolution(params: dict, node_config: dict, segment_index: int) -> None:
    """Validate dimensions without replacing the Wan node's own size policy.

    Workspace injects the source image dimensions unchanged. Individual Wan
    nodes may round, scale, or reject a size according to their installed
    implementation, so the application only rejects non-positive integers.
    """
    for key in ("width", "height"):
        spec = params.get(key)
        if not spec:
            continue
        # ui_config_to_param_config intentionally exposes every field.  A
        # missing field is therefore represented as None rather than being
        # absent, so get(key, default) alone does not reach the workflow
        # default.  Draft submissions rely on that fallback when an older
        # asset record has no stored dimensions.
        value = node_config.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = spec.get("default")
        try:
            dimension = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Segment {segment_index} {key} must be an integer.") from exc
        if dimension <= 0:
            raise ValueError(f"Segment {segment_index} {key} must be greater than zero.")


def apply_automatic_generation_seed(
    workflow: dict,
    segments: list[dict],
    generation_seed: int | None = None,
) -> dict:
    """Assign one server-generated seed to every sampler, preserving queued jobs."""
    if generation_seed is None:
        generation_seed = secrets.randbelow(MAX_GENERATION_SEED) + 1
    scope_segments = segments or [{"video_node": None}]
    applied = []
    for index, segment in enumerate(scope_segments, start=1):
        for target in workflow_parser.active_noise_seed_targets(workflow, segment.get("video_node")):
            node_id = str(target.get("node") or "")
            field = str(target.get("field") or "")
            if not node_id or not field or not workflow.get(node_id):
                continue
            workflow[node_id].setdefault("inputs", {})[field] = generation_seed
            applied.append({
                "segment": index,
                "samplerNode": target.get("samplerNode"),
                "node": node_id,
                "field": field,
                "value": generation_seed,
            })
    return {
        "mode": "automatic",
        "value": generation_seed if applied else None,
        "targets": applied,
    }


def apply_node_config_to_workflow(
    workflow: dict,
    workflow_id: str,
    segments_payload: list[dict],
    workflows_dir: Path,
    resolution_tier: str = "sd",
) -> list[dict]:
    param_config = workflow_parser.load_param_config(workflow_id, workflows_dir)
    if not param_config:
        return []
    specs = param_config.get("segments") or []
    applied = []
    for index, segment in enumerate(segments_payload):
        segment_spec = specs[index] if index < len(specs) else {}
        params = segment_spec.get("params") or {}
        node_config = ui_config_to_param_config(segment.get("config") or {})
        validate_segment_resolution(params, node_config, index + 1)
        for param_name, param_spec in params.items():
            if param_name == "seed":
                continue
            value = _wan_resolution_param_value(workflow, param_name, param_spec, node_config, resolution_tier)
            if value is None:
                value = node_config.get(param_name, param_spec.get("default"))
            if value is None:
                continue
            for target in param_spec.get("targets") or []:
                node_id = str(target.get("node"))
                field = target.get("field")
                if workflow.get(node_id) and field:
                    workflow[node_id].setdefault("inputs", {})[field] = value
                    applied.append({
                        "segment": index + 1,
                        "param": param_name,
                        "node": node_id,
                        "field": field,
                        "value": value,
                    })
    return applied


def apply_wan_generation_policy(
    workflow: dict,
    segments_payload: list[dict],
    *,
    resolution_tier: str = "sd",
) -> list[dict]:
    nodes = wan_video_nodes(workflow)
    if not nodes:
        return []
    normalized_tier = normalize_resolution_tier(resolution_tier)
    first_config = ((segments_payload or [{}])[0].get("config") if segments_payload else {}) or {}
    size = _wan_size_from_config(first_config, normalized_tier)
    applied = []
    for node_id, node in nodes:
        inputs = node.setdefault("inputs", {})
        if size:
            inputs["width"], inputs["height"] = size
        requested_length = None
        if len(nodes) == 1:
            requested_length = first_config.get("length") or first_config.get("frames") or first_config.get("frame_count")
        try:
            length = int(requested_length) if requested_length is not None else WAN_MAX_FRAMES
        except (TypeError, ValueError):
            length = WAN_MAX_FRAMES
        length = max(1, min(WAN_MAX_FRAMES, length))
        inputs["length"] = length
        inputs["batch_size"] = 1
        applied.append({
            "node": node_id,
            "classType": node.get("class_type"),
            "width": inputs.get("width"),
            "height": inputs.get("height"),
            "length": inputs.get("length"),
            "batch_size": inputs.get("batch_size"),
            "resolutionTier": normalized_tier,
        })
    wan_image_to_video_generation_snapshot(workflow, tier=normalized_tier)
    return applied


def build_wan_node_config_snapshot(
    workflow_id: str,
    segments_payload: list[dict],
    workflows_dir: Path,
    resolution_tier: str = "sd",
) -> dict:
    try:
        workflow = workflow_parser.load_workflow(workflow_id, workflows_dir)
    except FileNotFoundError:
        workflow = {}
    param_config = workflow_parser.load_param_config(workflow_id, workflows_dir) or {}
    specs = param_config.get("segments") or []
    snapshot_segments = []
    for index, segment in enumerate(segments_payload or []):
        segment_spec = specs[index] if index < len(specs) else {}
        params = segment_spec.get("params") or {}
        ui_values = ui_config_to_param_config(segment.get("config") or {})
        param_items = []
        for param_name, param_spec in params.items():
            if param_name == "seed":
                continue
            ui_key = PARAM_UI_KEYS.get(param_name, param_name)
            value = _wan_resolution_param_value(workflow, param_name, param_spec, ui_values, resolution_tier)
            if value is None:
                value = ui_values.get(param_name, param_spec.get("default"))
            param_items.append({
                "param": param_name,
                "uiKey": ui_key,
                "label": PARAM_LABELS.get(param_name, param_name),
                "value": value,
                "default": param_spec.get("default"),
                "type": param_spec.get("type", "float"),
                "min": param_spec.get("min"),
                "max": param_spec.get("max"),
                "step": param_spec.get("step"),
                "options": param_spec.get("options") or [],
                "targets": [
                    metadata_loader.target_metadata(workflow, target)
                    for target in (param_spec.get("targets") or [])
                ],
            })
        snapshot_segments.append({
            "index": segment.get("index") or index + 1,
            "nodeId": segment.get("nodeId", ""),
            "subgraphName": segment.get("subgraphName", ""),
            "displayName": segment.get("displayName", "") or segment.get("subgraphName", "") or f"Subgraph_{index + 1}",
            "config": segment.get("config") or {},
            "params": param_items,
        })
    return {
        "workflowId": workflow_id,
        "resolutionTier": normalize_resolution_tier(resolution_tier),
        "capturedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "segments": snapshot_segments,
    }


def prepare_workflow_for_job(
    payload: dict,
    workflows_dir: Path,
    build_runpod_images: Callable[[dict], list[dict]],
    existing_save_video_outputs: Callable[[dict, str, list[dict]], dict],
) -> tuple[dict, list[dict], dict]:
    workflow_id = payload.get("workflowId") or "unknown"
    resolution_tier = normalize_resolution_tier(payload.get("resolutionTier"))
    workflow = workflow_parser.load_workflow(workflow_id, workflows_dir)
    segments = workflow_parser.find_segments(workflow)
    segment_payloads = payload.get("segments") or []
    validate_i2v_input_images(payload, workflow, segments)
    images = build_runpod_images(payload)
    image_names = [image["name"] for image in images]
    output_summary = existing_save_video_outputs(workflow, workflow_id, segments)
    patch_summary = {
        "images": [],
        "prompts": [],
        "nodeConfig": [],
        "finalOutputNodes": output_summary["finalOutputNodes"],
        "segmentOutputs": output_summary["segmentOutputs"],
        "resolutionTier": resolution_tier,
    }

    if image_names:
        patch_summary["images"] = apply_keyframe_images(workflow, image_names, segments)
        validate_applied_images(workflow, image_names, segments)

    if segments:
        patch_summary["prompts"] = apply_segment_prompts(
            workflow,
            segments,
            [segment.get("positivePrompt", "") for segment in segment_payloads],
            [segment.get("negativePromptAddition", "") for segment in segment_payloads],
        )
    else:
        first_segment = segment_payloads[0] if segment_payloads else {}
        patch_summary["prompts"] = apply_single_prompt(
            workflow,
            first_segment.get("positivePrompt", ""),
            first_segment.get("negativePromptAddition", ""),
        )

    patch_summary["nodeConfig"] = apply_node_config_to_workflow(
        workflow,
        workflow_id,
        segment_payloads,
        workflows_dir,
        resolution_tier,
    )
    patch_summary["wanGenerationPolicy"] = apply_wan_generation_policy(
        workflow,
        segment_payloads,
        resolution_tier=resolution_tier,
    )
    patch_summary["generation"] = wan_image_to_video_generation_snapshot(workflow, tier=resolution_tier)
    queued_seed = payload.get("generationSeed")
    try:
        queued_seed = int(queued_seed) if queued_seed is not None else None
    except (TypeError, ValueError):
        queued_seed = None
    patch_summary["seed"] = apply_automatic_generation_seed(workflow, segments, queued_seed)
    patch_summary["requestSnapshot"] = build_submission_request_snapshot(payload, images)
    # 실행 제출 직전의 워크플로우에서 선택된 모델 파일만 스냅샷한다. 메타데이터
    # 카탈로그의 전체 옵션과 달리 이 값은 task_id의 재현/조회 전용이다.
    patch_summary["modelReferences"] = metadata_loader.workflow_model_reference_items(workflow)
    return workflow, images, patch_summary
