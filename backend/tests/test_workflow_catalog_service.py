from __future__ import annotations

import pytest

from backend.app.db.models import WorkflowDefinition, WorkflowRevision
from backend.app.services.workflow_catalog_service import assert_workflow_selectable, list_active_workflow_ids


def _definition_with_revision(db_session, workflow_id: str, status: str) -> WorkflowDefinition:
    definition = WorkflowDefinition(
        id=workflow_id,
        display_name=workflow_id.removesuffix(".json"),
        status=status,
        source="ADMIN_UPLOAD",
    )
    db_session.add(definition)
    db_session.flush()
    revision = WorkflowRevision(
        workflow_id=workflow_id,
        revision=1,
        workflow_path=f"releases/{workflow_id}/1/workflow.json",
        workflow_sha256="a" * 64,
        workflow_size_bytes=2,
        param_config_path=f"releases/{workflow_id}/1/paramconfig.json",
        param_config_sha256="b" * 64,
        param_config_size_bytes=2,
        validation_status="VALID",
        validation_json={},
    )
    db_session.add(revision)
    db_session.flush()
    definition.current_revision_id = revision.id
    db_session.commit()
    return definition


def test_any_registered_active_id_is_selectable(db_session):
    _definition_with_revision(db_session, "customer-flow-v7.json", "ACTIVE")

    assert assert_workflow_selectable(db_session, "customer-flow-v7.json") == "customer-flow-v7.json"


@pytest.mark.parametrize("status", ["INACTIVE", "ARCHIVED"])
def test_non_active_definition_is_not_selectable(db_session, status):
    _definition_with_revision(db_session, "held.json", status)

    with pytest.raises(ValueError, match="not active"):
        assert_workflow_selectable(db_session, "held.json")


def test_missing_definition_is_not_selectable(db_session):
    with pytest.raises(ValueError, match="not registered"):
        assert_workflow_selectable(db_session, "missing.json")


def test_active_definition_without_current_revision_is_not_selectable(db_session):
    db_session.add(WorkflowDefinition(id="unreleased.json", display_name="unreleased", status="ACTIVE", source="ADMIN_UPLOAD"))
    db_session.commit()

    with pytest.raises(ValueError, match="no active revision"):
        assert_workflow_selectable(db_session, "unreleased.json")


def test_active_workflow_ids_are_derived_from_database_state(db_session):
    _definition_with_revision(db_session, "z-dynamic.json", "ACTIVE")
    _definition_with_revision(db_session, "a-dynamic.json", "ACTIVE")
    _definition_with_revision(db_session, "held.json", "INACTIVE")

    assert list_active_workflow_ids(db_session) == ["a-dynamic.json", "z-dynamic.json"]
