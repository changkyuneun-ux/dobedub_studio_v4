from __future__ import annotations

from pathlib import Path


# Kept on disk for historical task replay, but only these flat WAN workflows
# are selectable for new work. The explicit allowlist also prevents an old
# workflow JSON left on a persistent ECS volume from becoming selectable again.
SUPPORTED_WORKFLOW_IDS = frozenset({
    "1-images_81.json",
    "1-images_10s_chain_81.json",
    "wan22_10s_chain.json",
    "wan22_default_81.json",
})

TEN_SECOND_CHAIN_WORKFLOW_IDS = frozenset({
    "1-images_10s_chain_81.json",
    "wan22_10s_chain.json",
})


def is_retired_workflow(workflow_id: object) -> bool:
    return Path(str(workflow_id or "")).name not in SUPPORTED_WORKFLOW_IDS


def is_ten_second_chain_workflow(workflow_id: object) -> bool:
    return Path(str(workflow_id or "")).name in TEN_SECOND_CHAIN_WORKFLOW_IDS


def assert_workflow_selectable(workflow_id: object) -> None:
    if is_retired_workflow(workflow_id):
        raise ValueError("This workflow is not approved for new requests")
