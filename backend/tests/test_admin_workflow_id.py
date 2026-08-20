import unittest

from backend.app.services.admin_service import normalize_workflow_id
from backend.app.services.workflow_parser import (
    find_image_slots,
    find_keyframe_images_ordered,
    find_prompt_node,
    keyframe_count,
    prompt_text,
)
from backend.app.services.workflow_patch_service import apply_single_prompt


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
