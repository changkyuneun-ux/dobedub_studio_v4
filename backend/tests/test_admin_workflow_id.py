import unittest

from backend.app.services.admin_service import normalize_workflow_id
from backend.app.services.workflow_parser import find_keyframe_images_ordered, keyframe_count


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
        }

        self.assertEqual(keyframe_count(workflow, []), 3)
        self.assertEqual(find_keyframe_images_ordered(workflow, []), ["image-1", "image-2", "image-3"])
