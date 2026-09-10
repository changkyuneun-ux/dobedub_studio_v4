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
    (seed_dir / "1-images_81.json").write_text('{"1":{"class_type":"LoadImage","inputs":{}}}', encoding="utf-8")
    (runtime_dir / "1-images.json").write_text('{"1":{"class_type":"LoadImage","inputs":{}}}', encoding="utf-8")
    (runtime_dir / "1-images.paramconfig.json").write_text('{"workflow":"1-images.json"}', encoding="utf-8")
    (data_dir / "workflow-registry.json").write_text(
        json.dumps({
            "items": {
                "1-images_81.json": {"active": True, "status": "ACTIVE"},
                "1-images.json": {"active": False, "status": "INACTIVE"},
            }
        }),
        encoding="utf-8",
    )
    (data_dir / "segment-defaults.json").write_text(
        json.dumps({
            "1-images_81.json": {"workflowName": "active", "segments": []},
            "1-images.json": {"workflowName": "inactive", "segments": []},
        }),
        encoding="utf-8",
    )

    result = service.bootstrap_workflow_store(seed_dir, runtime_dir, data_dir)

    assert result["pruned"] == ["1-images.json"]
    assert not (runtime_dir / "1-images.json").exists()
    assert not (runtime_dir / "1-images.paramconfig.json").exists()
    assert sorted(json.loads((data_dir / "workflow-registry.json").read_text(encoding="utf-8"))["items"]) == ["1-images_81.json"]
    assert sorted(json.loads((data_dir / "segment-defaults.json").read_text(encoding="utf-8"))) == ["1-images_81.json"]


def test_bootstrap_prunes_active_retired_workflows(tmp_path):
    seed_dir = tmp_path / "seed"
    runtime_dir = tmp_path / "runtime"
    data_dir = tmp_path / "data"
    seed_dir.mkdir()
    runtime_dir.mkdir()
    data_dir.mkdir()
    workflow_json = '{"1":{"class_type":"LoadImage","inputs":{}}}'
    (seed_dir / "Blowbang1.json").write_text(workflow_json, encoding="utf-8")
    (runtime_dir / "Blowbang1.json").write_text(workflow_json, encoding="utf-8")
    (runtime_dir / "Blowbang1.paramconfig.json").write_text('{"workflow":"Blowbang1.json"}', encoding="utf-8")
    (data_dir / "workflow-registry.json").write_text(
        json.dumps({"items": {"Blowbang1.json": {"active": True, "status": "ACTIVE"}}}),
        encoding="utf-8",
    )
    (data_dir / "segment-defaults.json").write_text(
        json.dumps({"Blowbang1.json": {"workflowName": "legacy", "segments": []}}),
        encoding="utf-8",
    )

    result = service.bootstrap_workflow_store(seed_dir, runtime_dir, data_dir)

    assert result["pruned"] == ["Blowbang1.json"]
    assert result["created"] == []
    assert not (runtime_dir / "Blowbang1.json").exists()
    assert not (runtime_dir / "Blowbang1.paramconfig.json").exists()
    assert json.loads((data_dir / "workflow-registry.json").read_text(encoding="utf-8"))["items"] == {}
    assert json.loads((data_dir / "segment-defaults.json").read_text(encoding="utf-8")) == {}


def test_bootstrap_prunes_retired_workflow_from_shared_seed_and_runtime_dir(tmp_path):
    workflow_dir = tmp_path / "workflows"
    data_dir = tmp_path / "data"
    workflow_dir.mkdir()
    data_dir.mkdir()
    workflow_json = '{"1":{"class_type":"LoadImage","inputs":{}}}'
    (workflow_dir / "Blowbang1.json").write_text(workflow_json, encoding="utf-8")
    (workflow_dir / "Blowbang1.paramconfig.json").write_text('{"workflow":"Blowbang1.json"}', encoding="utf-8")
    (workflow_dir / "1-images_81.json").write_text(workflow_json, encoding="utf-8")

    result = service.bootstrap_workflow_store(workflow_dir, workflow_dir, data_dir)

    assert result["pruned"] == ["Blowbang1.json"]
    assert not (workflow_dir / "Blowbang1.json").exists()
    assert not (workflow_dir / "Blowbang1.paramconfig.json").exists()
    assert (workflow_dir / "1-images_81.json").exists()


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


def test_bootstrap_prune_tolerates_concurrent_file_deletion(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    runtime_dir = tmp_path / "runtime"
    data_dir = tmp_path / "data"
    seed_dir.mkdir()
    runtime_dir.mkdir()
    data_dir.mkdir()
    (runtime_dir / "inactive.json").write_text('{"1":{"class_type":"LoadImage","inputs":{}}}', encoding="utf-8")
    (runtime_dir / "inactive.paramconfig.json").write_text('{"workflow":"inactive.json"}', encoding="utf-8")
    (data_dir / "workflow-registry.json").write_text(
        json.dumps({"items": {"inactive.json": {"active": False, "status": "INACTIVE"}}}),
        encoding="utf-8",
    )
    original_unlink = Path.unlink
    raced = False

    def racing_unlink(self, *args, **kwargs):
        nonlocal raced
        if self.name == "inactive.json" and not raced:
            raced = True
            original_unlink(self)
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", racing_unlink)

    result = service.bootstrap_workflow_store(seed_dir, runtime_dir, data_dir)

    assert result["pruned"] == ["inactive.json"]
    assert not (runtime_dir / "inactive.json").exists()
    assert not (runtime_dir / "inactive.paramconfig.json").exists()
