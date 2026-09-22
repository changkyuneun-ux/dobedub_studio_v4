from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.db.models import WorkflowDefinition, WorkflowRevision
from backend.app.services import workflow_service
from backend.app.services.workflow_visibility import assert_workflow_selectable, canonical_workflow_id


@pytest.mark.parametrize(
    ("legacy_id", "canonical_id"),
    [
        ("1-images.json", "1-images_81.json"),
        ("1-images_10s_chain.json", "1-images_10s_chain_81.json"),
        ("Wan22_default.json", "wan22_default_81.json"),
        ("wan22_default.json", "wan22_default_81.json"),
    ],
)
def test_legacy_workflow_ids_are_canonicalized(legacy_id, canonical_id):
    assert canonical_workflow_id(legacy_id) == canonical_id


def test_studio_list_uses_database_status_without_filename_allowlist(db_session, monkeypatch, tmp_path):
    settings = SimpleNamespace(workflows_dir=tmp_path, workflow_seed_dir=tmp_path)
    monkeypatch.setattr(workflow_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        workflow_service,
        "parse_workflow_list",
        lambda _directory: [
            {"id": "partner-v9.json", "name": "partner-v9"},
            {"id": "held.json", "name": "held"},
        ],
    )
    active = WorkflowDefinition(id="partner-v9.json", display_name="partner-v9", status="ACTIVE", source="ADMIN_UPLOAD")
    held = WorkflowDefinition(id="held.json", display_name="held", status="INACTIVE", source="ADMIN_UPLOAD")
    db_session.add_all([active, held])
    db_session.flush()
    revision = WorkflowRevision(
        workflow_id=active.id,
        revision=1,
        workflow_path="releases/partner-v9/1/workflow.json",
        workflow_sha256="a" * 64,
        workflow_size_bytes=1,
        param_config_path="releases/partner-v9/1/paramconfig.json",
        param_config_sha256="b" * 64,
        param_config_size_bytes=1,
        validation_status="VALID",
    )
    db_session.add(revision)
    db_session.flush()
    active.current_revision_id = revision.id
    db_session.commit()

    assert [item["id"] for item in workflow_service.list_workflows()] == ["partner-v9.json"]


def test_unregistered_workflow_is_rejected_when_not_bundled(db_session, monkeypatch, tmp_path):
    from backend.app import core
    del core  # import package before patching the local runtime import
    monkeypatch.setattr(
        "backend.app.core.config.get_settings",
        lambda: SimpleNamespace(workflow_seed_dir=Path(tmp_path)),
    )
    with pytest.raises(ValueError, match="not registered"):
        assert_workflow_selectable("unknown.json")
