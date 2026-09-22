from __future__ import annotations

import json

import pytest

from backend.app.db.models import WorkflowRevision
from backend.app.services.workflow_release_service import (
    prepare_release,
    promote_release_files,
    verify_release_files,
    write_release_files,
)


WORKFLOW_A = {
    "2": {"class_type": "SaveVideo", "inputs": {}},
    "1": {"class_type": "LoadImage", "inputs": {}},
}


def test_release_hash_is_deterministic():
    first = prepare_release("flow.json", WORKFLOW_A, {"b": 2, "a": 1})
    second = prepare_release(
        "flow.json",
        {
            "1": {"inputs": {}, "class_type": "LoadImage"},
            "2": {"inputs": {}, "class_type": "SaveVideo"},
        },
        {"a": 1, "b": 2},
    )

    assert first.workflow_sha256 == second.workflow_sha256
    assert first.param_config_sha256 == second.param_config_sha256
    assert first.node_count == 2
    assert first.input_image_count == 1
    assert first.segment_count == 1


@pytest.mark.parametrize("workflow_id", ["../flow.json", "nested/flow.json", "flow.paramconfig.json", " flow.json"])
def test_release_rejects_unsafe_workflow_ids(workflow_id):
    with pytest.raises(ValueError, match="Invalid workflowId"):
        prepare_release(workflow_id, WORKFLOW_A, {})


def test_write_promote_and_verify_release_files(tmp_path):
    prepared = prepare_release("flow.json", WORKFLOW_A, {"workflow": "flow.json"})
    files = write_release_files(tmp_path, "flow.json", 1, prepared)

    assert files.workflow_path == "releases/flow/1/workflow.json"
    assert files.param_config_path == "releases/flow/1/paramconfig.json"
    assert json.loads((tmp_path / files.workflow_path).read_text(encoding="utf-8")) == WORKFLOW_A

    promote_release_files(tmp_path, "flow.json", files)
    assert (tmp_path / "flow.json").read_bytes() == prepared.workflow_bytes
    assert (tmp_path / "flow.paramconfig.json").read_bytes() == prepared.param_config_bytes

    revision = WorkflowRevision(
        workflow_id="flow.json",
        revision=1,
        workflow_path=files.workflow_path,
        workflow_sha256=prepared.workflow_sha256,
        workflow_size_bytes=len(prepared.workflow_bytes),
        param_config_path=files.param_config_path,
        param_config_sha256=prepared.param_config_sha256,
        param_config_size_bytes=len(prepared.param_config_bytes),
        validation_status="VALID",
        validation_json=prepared.validation,
    )
    assert verify_release_files(tmp_path, revision) == {"ok": True, "workflow": "OK", "paramConfig": "OK"}

    (tmp_path / files.workflow_path).write_text("{}", encoding="utf-8")
    assert verify_release_files(tmp_path, revision) == {"ok": False, "workflow": "HASH_MISMATCH", "paramConfig": "OK"}
