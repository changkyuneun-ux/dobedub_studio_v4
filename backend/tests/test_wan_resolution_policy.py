import pytest

from backend.app.services.workflow_patch_service import (
    apply_node_config_to_workflow,
    apply_wan_generation_policy,
    fit_wan_size,
    wan_image_to_video_generation_snapshot,
)


@pytest.mark.parametrize(
    ("img_w", "img_h", "tier", "expected"),
    [
        (1090, 2040, "sd", (464, 864)),
        (1090, 2040, "hd", (688, 1312)),
        (1920, 1080, "sd", (848, 480)),
        (1920, 1080, "hd", (1280, 720)),
        (1000, 1000, "sd", (640, 640)),
        (1000, 1000, "hd", (960, 960)),
        (800, 4000, "sd", (272, 1424)),
        (800, 4000, "hd", (416, 2144)),
        (3000, 1000, "sd", (1104, 368)),
        (3000, 1000, "hd", (1648, 544)),
        (500, 600, "sd", (496, 592)),
        (500, 600, "hd", (496, 592)),
    ],
)
def test_fit_wan_size_matches_worker_pixel_budget_examples(img_w, img_h, tier, expected):
    assert fit_wan_size(img_w, img_h, tier) == expected


def test_fit_wan_size_rejects_invalid_tier_and_dimensions():
    with pytest.raises(ValueError):
        fit_wan_size(1000, 1000, "uhd")
    with pytest.raises(ValueError):
        fit_wan_size(0, 1000, "sd")
    with pytest.raises(ValueError):
        fit_wan_size(1000, -1, "sd")


def test_wan_generation_snapshot_reports_all_nodes_and_rejects_single_161_length():
    workflow = {
        "98": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": 848, "height": 480, "length": 161, "batch_size": 1},
        }
    }

    with pytest.raises(ValueError, match="length=161"):
        wan_image_to_video_generation_snapshot(workflow, tier="sd")


def test_wan_generation_snapshot_rejects_total_length_over_worker_limit():
    workflow = {
        "98": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": 848, "height": 480, "length": 81, "batch_size": 1},
        },
        "201": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": 848, "height": 480, "length": 81, "batch_size": 1},
        },
        "202": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": 848, "height": 480, "length": 1, "batch_size": 1},
        },
    }

    with pytest.raises(ValueError, match="total Wan video length"):
        wan_image_to_video_generation_snapshot(workflow, tier="sd")


def test_wan_generation_snapshot_includes_budget_and_pixel_count():
    workflow = {
        "98": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": 848, "height": 480, "length": 81, "batch_size": 1},
        },
        "201": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": 848, "height": 480, "length": 81, "batch_size": 1},
        },
    }

    assert wan_image_to_video_generation_snapshot(workflow, tier="sd") == [
        {
            "nodeId": "98",
            "classType": "WanImageToVideo",
            "width": 848,
            "height": 480,
            "length": 81,
            "batchSize": 1,
            "pixelCount": 407040,
            "tier": "sd",
            "pixelBudget": 409600,
        },
        {
            "nodeId": "201",
            "classType": "WanImageToVideo",
            "width": 848,
            "height": 480,
            "length": 81,
            "batchSize": 1,
            "pixelCount": 407040,
            "tier": "sd",
            "pixelBudget": 409600,
        },
    ]


def test_wan_first_last_frame_resolution_uses_pixel_budget_fit(tmp_path):
    workflow = {
        "81": {
            "class_type": "WanFirstLastFrameToVideo",
            "inputs": {"width": 640, "height": 640, "length": 161, "batch_size": 1},
        },
    }
    (tmp_path / "wan-flf.paramconfig.json").write_text(
        """
        {
          "segments": [{
            "params": {
              "width": {"default": 640, "targets": [{"node": "81", "field": "width"}]},
              "height": {"default": 640, "targets": [{"node": "81", "field": "height"}]},
              "frames": {"default": 81, "targets": [{"node": "81", "field": "length"}]}
            }
          }]
        }
        """,
        encoding="utf-8",
    )

    applied = apply_node_config_to_workflow(
        workflow,
        "wan-flf.json",
        [{"config": {"width": 1090, "height": 2040, "frames": 81}}],
        tmp_path,
    )

    assert workflow["81"]["inputs"]["width"] == 464
    assert workflow["81"]["inputs"]["height"] == 864
    assert workflow["81"]["inputs"]["length"] == 81
    assert {"segment": 1, "param": "width", "node": "81", "field": "width", "value": 464} in applied


def test_wan_generation_policy_patches_first_last_frame_nodes():
    workflow = {
        "81": {
            "class_type": "WanFirstLastFrameToVideo",
            "inputs": {"width": 640, "height": 640, "length": 161, "batch_size": 4},
        },
    }

    applied = apply_wan_generation_policy(
        workflow,
        [{"config": {"width": 1920, "height": 1080, "frames": 49}}],
        resolution_tier="sd",
    )

    assert applied == [{
        "node": "81",
        "classType": "WanFirstLastFrameToVideo",
        "width": 848,
        "height": 480,
        "length": 49,
        "batch_size": 1,
        "resolutionTier": "sd",
    }]
    assert workflow["81"]["inputs"] == {"width": 848, "height": 480, "length": 49, "batch_size": 1}


def test_wan_generation_snapshot_rejects_non_unit_batch_size():
    workflow = {
        "81": {
            "class_type": "WanFirstLastFrameToVideo",
            "inputs": {"width": 848, "height": 480, "length": 81, "batch_size": 2},
        },
    }

    with pytest.raises(ValueError, match="batch_size must be 1"):
        wan_image_to_video_generation_snapshot(workflow, tier="sd")


def test_wan_generation_snapshot_rejects_linked_or_zero_generation_values():
    linked_dimension_workflow = {
        "98": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": ["primitive", 0], "height": 480, "length": 81, "batch_size": 1},
        },
    }
    zero_length_workflow = {
        "98": {
            "class_type": "WanImageToVideo",
            "inputs": {"width": 848, "height": 480, "length": 0, "batch_size": 1},
        },
    }

    with pytest.raises(ValueError, match="width must be a literal integer"):
        wan_image_to_video_generation_snapshot(linked_dimension_workflow, tier="sd")
    with pytest.raises(ValueError, match="length must be positive"):
        wan_image_to_video_generation_snapshot(zero_length_workflow, tier="sd")
