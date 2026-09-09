from __future__ import annotations

import json
from pathlib import Path

from backend.app.services import workflow_storage_service as service


def test_manifest_write_survives_interleaved_startup_writes(tmp_path, monkeypatch):
    manifest_path = tmp_path / "workflow-seed-manifest.json"
    original_write_text = Path.write_text
    triggered = False

    def racing_write_text(self, *args, **kwargs):
        nonlocal triggered
        result = original_write_text(self, *args, **kwargs)
        if self.parent == tmp_path and self.name.startswith("workflow-seed-manifest") and not triggered:
            triggered = True
            service._write_manifest(manifest_path, {"version": 1, "files": {"second.json": {"seedHash": "b"}}})
        return result

    monkeypatch.setattr(Path, "write_text", racing_write_text)

    service._write_manifest(manifest_path, {"version": 1, "files": {"first.json": {"seedHash": "a"}}})

    assert json.loads(manifest_path.read_text(encoding="utf-8"))["files"] == {"first.json": {"seedHash": "a"}}


def test_bootstrap_prunes_inactive_runtime_workflows(tmp_path):
    seed_dir = tmp_path / "seed"
    runtime_dir = tmp_path / "runtime"
    data_dir = tmp_path / "data"
    seed_dir.mkdir()
    runtime_dir.mkdir()
    data_dir.mkdir()
    (seed_dir / "active.json").write_text('{"1":{"class_type":"LoadImage","inputs":{}}}', encoding="utf-8")
    (runtime_dir / "inactive.json").write_text('{"1":{"class_type":"LoadImage","inputs":{}}}', encoding="utf-8")
    (runtime_dir / "inactive.paramconfig.json").write_text('{"workflow":"inactive.json"}', encoding="utf-8")
    (data_dir / "workflow-registry.json").write_text(
        json.dumps({
            "items": {
                "active.json": {"active": True, "status": "ACTIVE"},
                "inactive.json": {"active": False, "status": "INACTIVE"},
            }
        }),
        encoding="utf-8",
    )
    (data_dir / "segment-defaults.json").write_text(
        json.dumps({
            "active.json": {"workflowName": "active", "segments": []},
            "inactive.json": {"workflowName": "inactive", "segments": []},
        }),
        encoding="utf-8",
    )

    result = service.bootstrap_workflow_store(seed_dir, runtime_dir, data_dir)

    assert result["pruned"] == ["inactive.json"]
    assert not (runtime_dir / "inactive.json").exists()
    assert not (runtime_dir / "inactive.paramconfig.json").exists()
    assert sorted(json.loads((data_dir / "workflow-registry.json").read_text(encoding="utf-8"))["items"]) == ["active.json"]
    assert sorted(json.loads((data_dir / "segment-defaults.json").read_text(encoding="utf-8"))) == ["active.json"]


def test_bootstrap_does_not_reseed_pruned_inactive_workflow(tmp_path):
    seed_dir = tmp_path / "seed"
    runtime_dir = tmp_path / "runtime"
    data_dir = tmp_path / "data"
    seed_dir.mkdir()
    runtime_dir.mkdir()
    data_dir.mkdir()
    workflow_json = '{"1":{"class_type":"LoadImage","inputs":{}}}'
    (seed_dir / "inactive.json").write_text(workflow_json, encoding="utf-8")
    (runtime_dir / "inactive.json").write_text(workflow_json, encoding="utf-8")
    (data_dir / "workflow-registry.json").write_text(
        json.dumps({"items": {"inactive.json": {"active": False, "status": "INACTIVE"}}}),
        encoding="utf-8",
    )

    result = service.bootstrap_workflow_store(seed_dir, runtime_dir, data_dir)

    assert result["pruned"] == ["inactive.json"]
    assert result["created"] == []
    assert not (runtime_dir / "inactive.json").exists()
