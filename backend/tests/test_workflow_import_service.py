from __future__ import annotations

import json

from backend.app.db.models import WorkflowDefinition, WorkflowRevision
from backend.app.services.workflow_import_service import apply_workflow_import, plan_workflow_import


WORKFLOW = {"1": {"class_type": "LoadImage", "inputs": {}}}


def _write_pair(directory, workflow_id):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / workflow_id).write_text(json.dumps(WORKFLOW), encoding="utf-8")
    (directory / f"{workflow_id.removesuffix('.json')}.paramconfig.json").write_text(
        json.dumps({"workflow": workflow_id}),
        encoding="utf-8",
    )


def test_import_plan_classifies_bundled_registry_and_efs_only_files_without_writes(db_session, tmp_path):
    seed = tmp_path / "seed"
    runtime = tmp_path / "runtime"
    data = tmp_path / "data"
    _write_pair(seed, "bundled.json")
    _write_pair(runtime, "bundled.json")
    _write_pair(runtime, "operator.json")
    _write_pair(runtime, "held.json")
    data.mkdir()
    (data / "workflow-registry.json").write_text(
        json.dumps({"items": {"held.json": {"active": False}}}),
        encoding="utf-8",
    )

    plan = plan_workflow_import(db_session, runtime, seed, data)

    assert [(item.workflow_id, item.source, item.status) for item in plan.items] == [
        ("bundled.json", "BUNDLED", "ACTIVE"),
        ("held.json", "LEGACY_IMPORT", "INACTIVE"),
        ("operator.json", "LEGACY_IMPORT", "INACTIVE"),
    ]
    assert db_session.query(WorkflowDefinition).count() == 0


def test_apply_import_is_idempotent_and_preserves_unknown_files(db_session, tmp_path):
    seed = tmp_path / "seed"
    runtime = tmp_path / "runtime"
    data = tmp_path / "data"
    _write_pair(seed, "bundled.json")
    _write_pair(runtime, "bundled.json")
    _write_pair(runtime, "operator.json")
    data.mkdir()

    first = apply_workflow_import(db_session, plan_workflow_import(db_session, runtime, seed, data))
    second = apply_workflow_import(db_session, plan_workflow_import(db_session, runtime, seed, data))

    assert first["createdDefinitions"] == 2
    assert second["createdDefinitions"] == 0
    assert db_session.query(WorkflowDefinition).count() == 2
    assert db_session.query(WorkflowRevision).count() == 2
    assert db_session.get(WorkflowDefinition, "bundled.json").status == "ACTIVE"
    assert db_session.get(WorkflowDefinition, "operator.json").status == "INACTIVE"
    assert (runtime / "operator.json").exists()
