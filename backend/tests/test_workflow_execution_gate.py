from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.db.models import WorkflowDefinition, WorkflowRevision
from backend.app.services import workflow_service
from backend.app.services.workflow_visibility import assert_workflow_selectable


def _release(db_session, workflow_id: str, status: str):
    definition = WorkflowDefinition(id=workflow_id, display_name=workflow_id, status=status, source="ADMIN_UPLOAD")
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


def test_legacy_signature_uses_database_activation_without_filename_allowlist(db_session):
    _release(db_session, "dynamic-customer.json", "ACTIVE")

    assert assert_workflow_selectable("dynamic-customer.json") == "dynamic-customer.json"
    with pytest.raises(ValueError, match="not registered"):
        assert_workflow_selectable("never-registered.json")


def test_studio_workflow_list_keeps_payload_shape_and_filters_by_db_state(db_session, monkeypatch, tmp_path):
    _release(db_session, "active-dynamic.json", "ACTIVE")
    _release(db_session, "inactive-dynamic.json", "INACTIVE")
    parsed = [
        {"id": "active-dynamic.json", "name": "Active", "mode": "single"},
        {"id": "inactive-dynamic.json", "name": "Inactive", "mode": "single"},
        {"id": "filesystem-only.json", "name": "Filesystem", "mode": "single"},
    ]
    monkeypatch.setattr(workflow_service, "get_settings", lambda: SimpleNamespace(workflows_dir=tmp_path))
    monkeypatch.setattr(workflow_service, "parse_workflow_list", lambda _directory: parsed)

    assert workflow_service.list_workflows() == [parsed[0]]
