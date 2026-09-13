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

LEGACY_WORKFLOW_ID_MAP = {
    "1-images.json": "1-images_81.json",
    "1-images_10s_chain.json": "1-images_10s_chain_81.json",
    "Wan22_default.json": "wan22_default_81.json",
    "wan22_default.json": "wan22_default_81.json",
}

TEN_SECOND_CHAIN_WORKFLOW_IDS = frozenset({
    "1-images_10s_chain_81.json",
    "wan22_10s_chain.json",
})


def canonical_workflow_id(workflow_id: object) -> str:
    name = Path(str(workflow_id or "")).name
    return LEGACY_WORKFLOW_ID_MAP.get(name, name)


def is_retired_workflow(workflow_id: object) -> bool:
    return Path(str(workflow_id or "")).name not in SUPPORTED_WORKFLOW_IDS


def is_ten_second_chain_workflow(workflow_id: object) -> bool:
    return canonical_workflow_id(workflow_id) in TEN_SECOND_CHAIN_WORKFLOW_IDS


def assert_workflow_selectable(workflow_id: object) -> str:
    canonical_id = canonical_workflow_id(workflow_id)
    if canonical_id not in SUPPORTED_WORKFLOW_IDS:
        raise ValueError("This workflow is not approved for new requests")
    return canonical_id
