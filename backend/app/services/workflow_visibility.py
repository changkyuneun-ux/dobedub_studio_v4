from __future__ import annotations

from pathlib import Path


# Kept on disk for historical task replay, but no longer selectable for new work.
RETIRED_WORKFLOW_IDS = frozenset({
    "1-images.json",
    "Blowbang1.json",
    "Pickme_Workflow.json",
    "video_wan2_2_14B_flf2v_2-images-1.json",
    "video_minimax_h3_r2v.json",
})


def is_retired_workflow(workflow_id: object) -> bool:
    return Path(str(workflow_id or "")).name in RETIRED_WORKFLOW_IDS
