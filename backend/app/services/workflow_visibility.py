from __future__ import annotations

from pathlib import Path


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
    canonical_id = canonical_workflow_id(workflow_id)
    from backend.app.core.config import get_settings
    from backend.app.db.session import SessionLocal
    from backend.app.services.workflow_catalog_service import get_workflow_definition

    with SessionLocal() as db:
        definition = get_workflow_definition(db, canonical_id)
        if definition is not None:
            return definition.status != "ACTIVE" or definition.current_revision_id is None
    return not (get_settings().workflow_seed_dir / canonical_id).is_file()


def is_ten_second_chain_workflow(workflow_id: object) -> bool:
    return canonical_workflow_id(workflow_id) in TEN_SECOND_CHAIN_WORKFLOW_IDS


def assert_workflow_selectable(workflow_id: object) -> str:
    canonical_id = canonical_workflow_id(workflow_id)
    from backend.app.core.config import get_settings
    from backend.app.db.session import SessionLocal
    from backend.app.services.workflow_catalog_service import get_workflow_definition

    with SessionLocal() as db:
        definition = get_workflow_definition(db, canonical_id)
        if definition is not None:
            if definition.status != "ACTIVE":
                raise ValueError("Workflow is not active")
            if definition.current_revision_id is None:
                raise ValueError("Workflow has no active revision")
            return canonical_id
    if (get_settings().workflow_seed_dir / canonical_id).is_file():
        return canonical_id
    raise ValueError("Workflow is not registered")
