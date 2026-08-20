from __future__ import annotations

import json
import re
from pathlib import Path


VIDEO_NODE_TYPES = {
    "WanFirstLastFrameToVideo",
    "WanImageToVideo",
    "MiniMaxH3ReferenceToVideo",
}

PARAM_UI_KEYS = {
    "width": "width",
    "height": "height",
    "fps": "fps",
    "output_fps": "outputFps",
    "frames": "frames",
    "duration_seconds": "durationSeconds",
    "steps": "steps",
    "cfg_scale": "cfgScale",
    "motion_shift": "motionShift",
    "bit_depth": "bitDepth",
    "video_format": "videoFormat",
    "video_codec": "videoCodec",
}

PARAM_LABELS = {
    "width": "Width",
    "height": "Height",
    "fps": "FPS",
    "output_fps": "Final Output FPS",
    "frames": "Video Length (Frames)",
    "duration_seconds": "Video Length (Seconds)",
    "steps": "Sampling Steps",
    "cfg_scale": "CFG Scale",
    "motion_shift": "Motion Shift",
    "bit_depth": "Final Bit Depth",
    "video_format": "Final Format",
    "video_codec": "Final Codec",
}

PARAM_DESCRIPTIONS = {
    "width": "Wan video latent width입니다. 16의 배수만 허용되며, Height와 함께 workflow가 처리할 해상도를 결정합니다.",
    "height": "Wan video latent height입니다. 16의 배수만 허용되며, Width와 함께 workflow가 처리할 해상도를 결정합니다.",
    "fps": "초당 프레임 수입니다. 높을수록 재생은 부드럽지만 출력 프레임/처리량이 증가합니다.",
    "output_fps": "최종 출력 비디오의 초당 프레임 수입니다. 세그먼트 생성 FPS와 별도로 최종 결합 영상 저장에 적용됩니다.",
    "frames": "생성할 총 프레임 수입니다. 길이와 움직임 범위를 직접 결정합니다.",
    "duration_seconds": "영상 길이입니다. duration 기반 workflow에서는 내부 수식으로 프레임 길이에 반영됩니다.",
    "steps": "샘플링 반복 횟수입니다. 높을수록 디테일은 늘 수 있지만 생성 시간이 증가합니다.",
    "cfg_scale": "프롬프트 반영 강도입니다. 과도하게 높으면 왜곡이나 경직된 움직임이 생길 수 있습니다.",
    "motion_shift": "움직임 변화량입니다. workflow 내 연결된 sampling 노드에 동일하게 반영될 수 있습니다.",
    "bit_depth": "최종 출력 비디오의 비트 깊이입니다. 기본값 8을 권장합니다.",
    "video_format": "SaveVideo format 값입니다. ComfyUI 환경에서 지원하는 값만 사용해야 하며 기본값은 auto입니다.",
    "video_codec": "SaveVideo codec 값입니다. ComfyUI 환경에서 지원하는 값만 사용해야 하며 기본값은 auto입니다.",
}


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def node_title(node: dict) -> str:
    return (node.get("_meta") or {}).get("title") or node.get("class_type") or "Node"


def workflow_files(workflows_dir: Path) -> list[Path]:
    if not workflows_dir.exists():
        return []
    return sorted(path for path in workflows_dir.glob("*.json") if not path.name.endswith(".paramconfig.json"))


def load_workflow(workflow_id: str, workflows_dir: Path) -> dict:
    safe_name = Path(workflow_id).name
    path = workflows_dir / safe_name
    if not path.exists() or path.suffix.lower() != ".json":
        raise FileNotFoundError(safe_name)
    return read_json(path)


def load_param_config(workflow_id: str, workflows_dir: Path) -> dict | None:
    base = Path(workflow_id).stem
    path = workflows_dir / f"{base}.paramconfig.json"
    if not path.exists():
        return None
    config = read_json(path)
    # Generation seeds are assigned server-side for every task. Ignore legacy
    # paramconfig entries so old workflow metadata cannot re-enable a UI control.
    for segment in config.get("segments") or []:
        if isinstance(segment, dict):
            (segment.get("params") or {}).pop("seed", None)
    return config


def find_load_image_nodes(workflow: dict) -> list[str]:
    return [node_id for node_id, node in workflow.items() if node.get("class_type") == "LoadImage"]


def link_node(inputs: dict, role: str) -> str | None:
    link = inputs.get(role)
    if isinstance(link, list) and link:
        return str(link[0])
    return None


def load_image_ref(workflow: dict, inputs: dict, role: str) -> str | None:
    node_id = link_node(inputs, role)
    if node_id and workflow.get(node_id, {}).get("class_type") == "LoadImage":
        return node_id
    return None


def image_input_order(field: str) -> tuple[int, int | str]:
    """Keep standard I2V inputs and indexed reference images in run order."""
    if field == "start_image":
        return (0, 0)
    if field == "end_image":
        return (0, 1)
    reference_match = re.search(r"(?:^|\\.)ref_image_(\\d+)$", field)
    if reference_match:
        return (1, int(reference_match.group(1)))
    if field == "image":
        return (2, 0)
    return (3, field)


def linked_load_image_inputs(workflow: dict) -> list[tuple[str, str]]:
    """Return only LoadImage nodes wired into an image-to-video node.

    Some workflows, including MiniMax H3, expose reference images as indexed
    inputs such as ``ref_images.ref_image_0`` instead of ``start_image`` and
    ``end_image``.  Graph links are the source of truth, not the node title or
    the order in which LoadImage nodes happen to be serialized.
    """
    linked: list[tuple[str, str]] = []
    seen_node_ids: set[str] = set()
    for _video_node_id, node in workflow.items():
        if node.get("class_type") not in VIDEO_NODE_TYPES:
            continue
        for field in sorted((node.get("inputs") or {}).keys(), key=image_input_order):
            node_id = load_image_ref(workflow, node.get("inputs") or {}, field)
            if node_id and node_id not in seen_node_ids:
                linked.append((field, node_id))
                seen_node_ids.add(node_id)
    return linked


def find_segments(workflow: dict) -> list[dict]:
    video_nodes = [
        node_id for node_id, node in workflow.items()
        if node.get("class_type") in VIDEO_NODE_TYPES
    ]
    if len(video_nodes) <= 1:
        return []

    by_id = {}
    for video_node in video_nodes:
        inputs = workflow[video_node].get("inputs", {})
        by_id[video_node] = {
            "video_node": video_node,
            "start_image_node": load_image_ref(workflow, inputs, "start_image"),
            "end_image_node": load_image_ref(workflow, inputs, "end_image"),
            "positive_node": link_node(inputs, "positive"),
            "negative_node": link_node(inputs, "negative"),
        }

    end_nodes = {segment["end_image_node"] for segment in by_id.values() if segment["end_image_node"]}
    starts = [segment for segment in by_id.values() if segment["start_image_node"] not in end_nodes]
    if len(starts) != 1:
        return list(by_id.values())

    ordered = [starts[0]]
    used = {ordered[0]["video_node"]}
    while True:
        current = ordered[-1]
        next_segment = None
        for segment in by_id.values():
            if segment["video_node"] in used:
                continue
            if segment["start_image_node"] == current["end_image_node"]:
                next_segment = segment
                break
        if next_segment is None:
            break
        ordered.append(next_segment)
        used.add(next_segment["video_node"])

    ordered.extend(segment for segment in by_id.values() if segment["video_node"] not in used)
    return ordered


def find_image_slots(workflow: dict) -> dict:
    linked_inputs = linked_load_image_inputs(workflow)
    if linked_inputs:
        slots = {}
        for index, (field, node_id) in enumerate(linked_inputs, start=1):
            role = field if field in {"start_image", "end_image", "image"} else f"image_{index}"
            slots[role] = node_id
        return slots
    nodes = find_load_image_nodes(workflow)
    return {"image": nodes[0]} if nodes else {}


def prompt_text(workflow: dict, node_id: str | None) -> str:
    if not node_id:
        return ""
    inputs = workflow.get(node_id, {}).get("inputs", {})
    field = prompt_input_field(workflow, node_id)
    return inputs.get(field, "") or ""


def prompt_input_field(workflow: dict, node_id: str | None) -> str:
    """Return the editable prompt field for common ComfyUI text nodes."""
    inputs = workflow.get(node_id or "", {}).get("inputs", {})
    if "text" in inputs:
        return "text"
    if "value" in inputs:
        return "value"
    return "text"


def find_prompt_node(workflow: dict, label: str) -> str | None:
    for node_id, node in workflow.items():
        if node.get("class_type") != "CLIPTextEncode":
            continue
        title = node.get("_meta", {}).get("title", "")
        if label in title:
            return node_id

    if label != "Positive":
        return None

    # MiniMax H3 stores the positive prompt in a PrimitiveStringMultiline node
    # linked to the generation node's ``prompt`` input, not CLIPTextEncode.
    for _video_node_id, node in workflow.items():
        if node.get("class_type") not in VIDEO_NODE_TYPES:
            continue
        prompt_node = link_node(node.get("inputs") or {}, "prompt")
        if prompt_node and prompt_input_field(workflow, prompt_node) in {"text", "value"}:
            return prompt_node
    return None


def keyframe_count(workflow: dict, segments: list[dict]) -> int:
    if segments:
        ordered = []
        for segment in segments:
            for key in ("start_image_node", "end_image_node"):
                node_id = segment.get(key)
                if node_id and node_id not in ordered:
                    ordered.append(node_id)
        return len(ordered)
    return len(find_keyframe_images_ordered(workflow, segments))


def find_keyframe_images_ordered(workflow: dict, segments: list[dict] | None = None) -> list[str]:
    segments = segments if segments is not None else find_segments(workflow)
    ordered = []
    for segment in segments:
        for key in ("start_image_node", "end_image_node"):
            node_id = segment.get(key)
            if node_id and node_id not in ordered:
                ordered.append(node_id)
    if ordered:
        return ordered
    for _field, node_id in linked_load_image_inputs(workflow):
        if node_id and node_id not in ordered:
            ordered.append(node_id)
    if ordered:
        return ordered
    for node_id in find_load_image_nodes(workflow):
        if node_id not in ordered:
            ordered.append(node_id)
    return ordered


def default_config(index: int) -> dict:
    return {
        "fps": 16,
        "frames": 81 if index == 1 else 96,
        "steps": 20,
        "cfgScale": 5.0,
        "motionShift": 1.0,
    }


def linked_node_id(value) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    return None


def direct_input_value(workflow: dict, node_id: str, field: str):
    value = workflow.get(node_id, {}).get("inputs", {}).get(field)
    if isinstance(value, list):
        return None
    return value


def scoped_node_ids(workflow: dict, video_node_id: str | None) -> list[str]:
    if not video_node_id or ":" not in str(video_node_id):
        return list(workflow.keys())
    prefix = str(video_node_id).split(":", 1)[0] + ":"
    return [node_id for node_id in workflow if str(node_id).startswith(prefix)]


def node_title_lower(node: dict) -> str:
    return str(node_title(node)).lower()


def title_value_target(workflow: dict, node_ids: list[str], title_part: str, *, expected_classes: set[str] | None = None) -> dict | None:
    title_part = title_part.lower()
    for node_id in node_ids:
        node = workflow.get(node_id, {})
        if expected_classes and node.get("class_type") not in expected_classes:
            continue
        if title_part not in node_title_lower(node):
            continue
        if "value" in (node.get("inputs") or {}):
            return {"node": node_id, "field": "value"}
    return None


def target_value(workflow: dict, target: dict | None):
    if not target:
        return None
    return direct_input_value(workflow, str(target.get("node", "")), str(target.get("field", "")))


def linked_or_direct_target(workflow: dict, source_node_id: str, field: str) -> dict | None:
    inputs = workflow.get(source_node_id, {}).get("inputs") or {}
    value = inputs.get(field)
    linked_id = linked_node_id(value)
    if linked_id and workflow.get(linked_id):
        linked_inputs = workflow.get(linked_id, {}).get("inputs") or {}
        if "value" in linked_inputs:
            return {"node": linked_id, "field": "value"}
        if workflow.get(linked_id, {}).get("class_type") == "ComfySwitchNode":
            for switch_field in ("on_true", "on_false"):
                switch_target_id = linked_node_id(linked_inputs.get(switch_field))
                if switch_target_id and "value" in (workflow.get(switch_target_id, {}).get("inputs") or {}):
                    return {"node": switch_target_id, "field": "value"}
    if field in inputs and not isinstance(value, list):
        return {"node": source_node_id, "field": field}
    return None


def find_nodes_by_class(workflow: dict, node_ids: list[str], class_type: str) -> list[str]:
    return [node_id for node_id in node_ids if workflow.get(node_id, {}).get("class_type") == class_type]


def active_noise_seed_targets(workflow: dict, video_node_id: str | None = None) -> list[dict]:
    """Return only samplers that create a new latent-noise pattern.

    KSamplerAdvanced nodes with ``add_noise=disable`` consume an existing latent.
    Their seed must remain untouched to preserve the workflow's high/low-noise path.
    """
    targets = []
    for node_id in find_nodes_by_class(workflow, scoped_node_ids(workflow, video_node_id), "KSamplerAdvanced"):
        inputs = workflow.get(node_id, {}).get("inputs") or {}
        if str(inputs.get("add_noise") or "").lower() != "enable":
            continue
        target = linked_or_direct_target(workflow, node_id, "noise_seed")
        if target:
            target = {**target, "samplerNode": node_id}
        if target and target not in targets:
            targets.append(target)
    return targets


def sampler_targets(workflow: dict, node_ids: list[str], field: str) -> list[dict]:
    targets = []
    for node_id in find_nodes_by_class(workflow, node_ids, "KSamplerAdvanced"):
        target = linked_or_direct_target(workflow, node_id, field)
        if target and target not in targets:
            targets.append(target)
    return targets


def model_shift_targets(workflow: dict, node_ids: list[str]) -> list[dict]:
    targets = []
    for node_id in find_nodes_by_class(workflow, node_ids, "ModelSamplingSD3"):
        if "shift" in (workflow.get(node_id, {}).get("inputs") or {}):
            target = {"node": node_id, "field": "shift"}
            if target not in targets:
                targets.append(target)
    return targets


def first_value_from_targets(workflow: dict, targets: list[dict]):
    for target in targets:
        value = target_value(workflow, target)
        if value is not None:
            return value
    return None


def param_spec(targets: list[dict], param_type: str, default, **extra) -> dict | None:
    if not targets or default is None:
        return None
    spec = {
        "targets": targets,
        "type": param_type,
        "default": default,
    }
    for key, value in extra.items():
        if value is not None:
            spec[key] = value
    return spec


def segment_param_spec(workflow: dict, video_node_id: str | None, *, include_final_output: bool) -> dict:
    node_ids = scoped_node_ids(workflow, video_node_id)
    params = {}

    steps_targets = sampler_targets(workflow, node_ids, "steps")
    if not steps_targets:
        title_target = title_value_target(workflow, node_ids, "steps", expected_classes={"PrimitiveInt", "PrimitiveFloat"})
        steps_targets = [title_target] if title_target else []
    steps_default = first_value_from_targets(workflow, steps_targets)
    spec = param_spec(steps_targets, "int", steps_default, min=1, max=50)
    if spec:
        params["steps"] = spec

    cfg_targets = sampler_targets(workflow, node_ids, "cfg")
    if not cfg_targets:
        title_target = title_value_target(workflow, node_ids, "cfg", expected_classes={"PrimitiveInt", "PrimitiveFloat"})
        cfg_targets = [title_target] if title_target else []
    cfg_default = first_value_from_targets(workflow, cfg_targets)
    spec = param_spec(cfg_targets, "float", cfg_default, min=0.0, max=12.0)
    if spec:
        params["cfg_scale"] = spec

    shift_targets = model_shift_targets(workflow, node_ids)
    shift_default = first_value_from_targets(workflow, shift_targets)
    spec = param_spec(shift_targets, "float", shift_default, min=0.0, max=10.0, sync=len(shift_targets) > 1)
    if spec:
        params["motion_shift"] = spec

    video_inputs = workflow.get(video_node_id or "", {}).get("inputs") or {}
    for dimension in ("width", "height"):
        dimension_value = video_inputs.get(dimension)
        if dimension in video_inputs and not isinstance(dimension_value, list):
            spec = param_spec(
                [{"node": video_node_id, "field": dimension}],
                "int",
                dimension_value,
                min=256,
                max=1280,
                step=16,
                description=PARAM_DESCRIPTIONS[dimension],
            )
            if spec:
                params[dimension] = spec

    length_value = video_inputs.get("length")
    length_link = linked_node_id(length_value)
    duration_target = title_value_target(workflow, node_ids, "duration", expected_classes={"PrimitiveInt", "PrimitiveFloat"})
    if duration_target:
        spec = param_spec([duration_target], "float", target_value(workflow, duration_target), min=1.0, max=10.0, note="duration 기반 workflow입니다. 실제 length는 workflow 내부 수식으로 계산됩니다.")
        if spec:
            params["duration_seconds"] = spec
    elif length_link and workflow.get(length_link, {}).get("class_type") in {"PrimitiveInt", "PrimitiveFloat"}:
        spec = param_spec([{"node": length_link, "field": "value"}], "int", direct_input_value(workflow, length_link, "value"), min=15, max=121)
        if spec:
            params["frames"] = spec
    elif "length" in video_inputs and not isinstance(length_value, list):
        max_frames = max(241, int(length_value or 0))
        spec = param_spec([{"node": video_node_id, "field": "length"}], "int", length_value, min=15, max=max_frames)
        if spec:
            params["frames"] = spec

    create_video_nodes = find_nodes_by_class(workflow, node_ids, "CreateVideo")
    create_video_id = create_video_nodes[0] if create_video_nodes else ""
    fps_target = title_value_target(workflow, node_ids, "fps", expected_classes={"PrimitiveInt", "PrimitiveFloat"})
    if fps_target:
        spec = param_spec([fps_target], "int", target_value(workflow, fps_target), min=8, max=30)
    elif create_video_id:
        spec = param_spec([{"node": create_video_id, "field": "fps"}], "int", direct_input_value(workflow, create_video_id, "fps"), min=8, max=30)
    else:
        spec = None
    if spec:
        params["fps"] = spec

    if include_final_output:
        final_create_video_id, final_save_video_id = find_final_output_nodes(workflow)
        if final_create_video_id:
            spec = param_spec([{"node": final_create_video_id, "field": "fps"}], "int", direct_input_value(workflow, final_create_video_id, "fps"), min=8, max=60, description="최종 출력 CreateVideo 노드의 FPS입니다. 세그먼트 FPS와 별도로 최종 결합 영상에 적용됩니다.")
            if spec:
                params["output_fps"] = spec
            spec = param_spec([{"node": final_create_video_id, "field": "bit_depth"}], "int", direct_input_value(workflow, final_create_video_id, "bit_depth"), min=8, max=16, description="최종 출력 CreateVideo 노드의 bit_depth입니다. 기본값 8을 권장합니다.")
            if spec:
                params["bit_depth"] = spec
        elif create_video_id:
            spec = param_spec([{"node": create_video_id, "field": "bit_depth"}], "int", direct_input_value(workflow, create_video_id, "bit_depth"), min=8, max=16, description="최종 출력 CreateVideo 노드의 bit_depth입니다. 기본값 8을 권장합니다.")
            if spec:
                params["bit_depth"] = spec
        if final_save_video_id:
            spec = param_spec([{"node": final_save_video_id, "field": "format"}], "string", direct_input_value(workflow, final_save_video_id, "format"), options=["auto", "mp4"], description="최종 출력 SaveVideo 노드의 format입니다. ComfyUI에서 지원하는 값을 입력합니다.")
            if spec:
                params["video_format"] = spec
            spec = param_spec([{"node": final_save_video_id, "field": "codec"}], "string", direct_input_value(workflow, final_save_video_id, "codec"), options=["auto", "h264"], description="최종 출력 SaveVideo 노드의 codec입니다. ComfyUI에서 지원하는 값을 입력합니다.")
            if spec:
                params["video_codec"] = spec

    return params


def find_final_output_nodes(workflow: dict) -> tuple[str, str]:
    save_nodes = find_nodes_by_class(workflow, list(workflow.keys()), "SaveVideo")
    final_save = ""
    for node_id in save_nodes:
        node = workflow.get(node_id, {})
        text = f"{node_title(node)} {(node.get('inputs') or {}).get('filename_prefix', '')}".lower()
        if "final" in text or "최종" in text:
            final_save = node_id
            break
    if not final_save and save_nodes:
        top_level = [node_id for node_id in save_nodes if ":" not in str(node_id)]
        final_save = top_level[0] if top_level else save_nodes[0]
    create_video_id = ""
    if final_save:
        video_link = linked_node_id((workflow.get(final_save, {}).get("inputs") or {}).get("video"))
        if video_link and workflow.get(video_link, {}).get("class_type") == "CreateVideo":
            create_video_id = video_link
    return create_video_id, final_save


def generate_param_config(workflow_id: str, workflow: dict) -> dict:
    segments = find_segments(workflow)
    if segments:
        items = []
        for index, segment in enumerate(segments, start=1):
            items.append({
                "segment_index": index,
                "params": segment_param_spec(workflow, segment.get("video_node"), include_final_output=index == 1),
            })
    else:
        video_node = next(
            (
                node_id for node_id, node in workflow.items()
                if node.get("class_type") in VIDEO_NODE_TYPES
            ),
            "",
        )
        items = [{
            "segment_index": 1,
            "params": segment_param_spec(workflow, video_node, include_final_output=True),
        }]
    return {
        "_comment": "Admin workflow registration에서 workflow JSON을 기준으로 자동 생성한 paramconfig입니다. 필요 시 Admin에서 별도 paramconfig JSON을 업로드해 덮어쓸 수 있습니다.",
        "workflow": Path(workflow_id).name,
        "segments": items,
    }


def config_from_param_spec(workflow_id: str, index: int, workflows_dir: Path) -> tuple[dict, list[dict]]:
    param_config = load_param_config(workflow_id, workflows_dir)
    fallback = default_config(index)
    if not param_config:
        return fallback, []
    specs = param_config.get("segments") or []
    segment_spec = specs[index - 1] if index - 1 < len(specs) else {}
    params = segment_spec.get("params") or {}
    config = {}
    controls = []
    for param_name, param_spec in params.items():
        ui_key = PARAM_UI_KEYS.get(param_name)
        if not ui_key:
            continue
        default_value = param_spec.get("default")
        if default_value is None:
            continue
        config[ui_key] = default_value
        controls.append({
            "key": ui_key,
            "param": param_name,
            "label": PARAM_LABELS.get(param_name, param_name),
            "type": param_spec.get("type", "float"),
            "min": param_spec.get("min"),
            "max": param_spec.get("max"),
            "step": param_spec.get("step"),
            "default": default_value,
            "randomizable": bool(param_spec.get("randomizable")),
            "options": param_spec.get("options") or [],
            "description": param_spec.get("description") or param_spec.get("note") or PARAM_DESCRIPTIONS.get(param_name, ""),
            "note": param_spec.get("note", ""),
            "targets": param_spec.get("targets") or [],
        })
    for key, value in fallback.items():
        config.setdefault(key, value)
    return config, controls


def workflow_schema(workflow_id: str, workflows_dir: Path) -> dict:
    workflow = load_workflow(workflow_id, workflows_dir)
    segments = find_segments(workflow)
    slots = find_image_slots(workflow)

    def subgraph_info(video_node, index):
        node = workflow.get(video_node or "", {})
        title = (node.get("_meta") or {}).get("title") or node.get("class_type") or "Subgraph"
        return {
            "nodeId": video_node or "",
            "subgraphName": title,
            "displayName": f"{title}_{index}",
        }

    if segments:
        mode = "multi_segment"
        segment_items = []
        for index, segment in enumerate(segments, start=1):
            config, controls = config_from_param_spec(workflow_id, index, workflows_dir)
            segment_items.append({
                "index": index,
                **subgraph_info(segment.get("video_node"), index),
                "startImageIndex": index,
                "endImageIndex": index + 1,
                "defaultPositivePrompt": prompt_text(workflow, segment.get("positive_node")),
                "defaultNegativePrompt": prompt_text(workflow, segment.get("negative_node")),
                "config": config,
                "configControls": controls,
            })
    else:
        mode = "dual" if {"start_image", "end_image"}.issubset(slots) else "single"
        config, controls = config_from_param_spec(workflow_id, 1, workflows_dir)
        video_node = next(
            (
                node_id for node_id, node in workflow.items()
                if node.get("class_type") in VIDEO_NODE_TYPES
            ),
            "",
        )
        segment_items = [{
            "index": 1,
            **subgraph_info(video_node, 1),
            "startImageIndex": 1,
            "endImageIndex": 2 if mode == "dual" else None,
            "defaultPositivePrompt": prompt_text(workflow, find_prompt_node(workflow, "Positive")),
            "defaultNegativePrompt": prompt_text(workflow, find_prompt_node(workflow, "Negative")),
            "config": config,
            "configControls": controls,
        }]

    return {
        "workflowId": workflow_id,
        "name": Path(workflow_id).stem,
        "mode": mode,
        "keyframeCount": keyframe_count(workflow, segments),
        "segmentCount": len(segment_items),
        "segments": segment_items,
    }


def list_workflows(workflows_dir: Path) -> list[dict]:
    result = []
    for path in workflow_files(workflows_dir):
        try:
            schema = workflow_schema(path.name, workflows_dir)
        except Exception:
            continue
        result.append({
            "id": path.name,
            "name": path.stem,
            "mode": schema["mode"],
            "keyframeCount": schema["keyframeCount"],
            "segmentCount": schema["segmentCount"],
        })
    return result
