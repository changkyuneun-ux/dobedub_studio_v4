import unittest

from backend.app.services.admin_service import normalize_workflow_id
from backend.app.services.workflow_parser import (
    find_image_slots,
    find_keyframe_images_ordered,
    find_prompt_node,
    keyframe_count,
    prompt_text,
)
from backend.app.services.workflow_patch_service import (
    apply_single_prompt,
    build_submission_request_snapshot,
    ui_config_to_param_config,
    validate_segment_resolution,
)


class AdminWorkflowIdTests(unittest.TestCase):
    def test_normalize_workflow_id_preserves_safe_name(self) -> None:
        self.assertEqual(normalize_workflow_id("wan2.2-i2v.json"), "wan2.2-i2v.json")

    def test_normalize_workflow_id_sanitizes_exported_filename(self) -> None:
        self.assertEqual(
            normalize_workflow_id("video_wan2_2_14B_flf2v_2 images (1).json"),
            "video_wan2_2_14B_flf2v_2-images-1.json",
        )

    def test_detects_indexed_reference_image_slots(self) -> None:
        workflow = {
            "video": {
                "class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {
                    "ref_images.ref_image_0": ["image-1", 0],
                    "ref_images.ref_image_1": ["image-2", 0],
                    "ref_images.ref_image_2": ["image-3", 0],
                },
            },
            "image-1": {"class_type": "LoadImage", "inputs": {"image": "one.png"}},
            "image-2": {"class_type": "LoadImage", "inputs": {"image": "two.png"}},
            "image-3": {"class_type": "LoadImage", "inputs": {"image": "three.png"}},
            "unrelated-image": {"class_type": "LoadImage", "inputs": {"image": "ignore.png"}},
        }

        self.assertEqual(keyframe_count(workflow, []), 3)
        self.assertEqual(find_keyframe_images_ordered(workflow, []), ["image-1", "image-2", "image-3"])
        self.assertEqual(
            find_image_slots(workflow),
            {"image_1": "image-1", "image_2": "image-2", "image_3": "image-3"},
        )

    def test_applies_minimax_prompt_to_primitive_string_input(self) -> None:
        workflow = {
            "video": {
                "class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {"prompt": ["prompt", 0]},
            },
            "prompt": {
                "class_type": "PrimitiveStringMultiline",
                "_meta": {"title": "Input Text (Prompt)"},
                "inputs": {"value": "original"},
            },
        }

        self.assertEqual(find_prompt_node(workflow, "Positive"), "prompt")
        self.assertEqual(prompt_text(workflow, "prompt"), "original")
        self.assertEqual(apply_single_prompt(workflow, "updated prompt", ""), [{"node": "prompt", "field": "positive"}])
        self.assertEqual(workflow["prompt"]["inputs"]["value"], "updated prompt")

    def test_accepts_original_upload_resolution_for_wan_node(self) -> None:
        validate_segment_resolution(
            {"width": {"default": 1280}, "height": {"default": 720}},
            {"width": 2040, "height": 1090},
            1,
        )

    def test_rejects_non_positive_upload_resolution(self) -> None:
        with self.assertRaisesRegex(ValueError, "height must be greater than zero"):
            validate_segment_resolution(
                {"height": {"default": 720}},
                {"height": 0},
                1,
            )

    def test_uses_workflow_default_when_resolution_is_not_supplied(self) -> None:
        validate_segment_resolution(
            {"width": {"default": 1280}, "height": {"default": 720}},
            {"width": None, "height": ""},
            1,
        )

    def test_submission_snapshot_keeps_input_image_prompt_and_length(self) -> None:
        snapshot = build_submission_request_snapshot(
            {
                "workflowId": "1-images.json",
                "keyframes": [{"index": 1, "uploadId": "asset_input_1", "fileName": "source.png"}],
                "segments": [{
                    "index": 1,
                    "positivePrompt": "A person turns gently, smooth movement.",
                    "negativePromptAddition": "low quality",
                    "config": {"frames": 81, "fps": 16},
                }],
            },
            [{"name": "source.png", "path": "/private/input/source.png"}],
        )

        self.assertEqual(snapshot["inputImages"], [{
            "slotIndex": 1,
            "assetId": "asset_input_1",
            "sourceFileName": "source.png",
            "runpodFileName": "source.png",
        }])
        self.assertEqual(snapshot["prompts"][0]["positivePrompt"], "A person turns gently, smooth movement.")
        self.assertEqual(snapshot["prompts"][0]["negativePrompt"], "low quality")
        self.assertEqual(snapshot["videoSettings"], [{"segmentIndex": 1, "length": 81, "fps": 16}])

    def test_param_config_accepts_legacy_length_alias_for_frames(self) -> None:
        self.assertEqual(ui_config_to_param_config({"length": 81})["frames"], 81)
        self.assertEqual(ui_config_to_param_config({"frame_count": 49})["frames"], 49)
