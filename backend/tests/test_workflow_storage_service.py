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


def test_bootstrap_preserves_inactive_and_unregistered_runtime_files(tmp_path):
    seed_dir = tmp_path / "seed"
    runtime_dir = tmp_path / "runtime"
    data_dir = tmp_path / "data"
    seed_dir.mkdir()
    runtime_dir.mkdir()
    data_dir.mkdir()
    for name in ("inactive.json", "unregistered.json"):
        (runtime_dir / name).write_text('{"1":{"class_type":"LoadImage","inputs":{}}}', encoding="utf-8")
    (data_dir / "workflow-registry.json").write_text(
        json.dumps({"items": {"inactive.json": {"active": False}}}),
        encoding="utf-8",
    )

    result = service.bootstrap_workflow_store(seed_dir, runtime_dir, data_dir)

    assert (runtime_dir / "inactive.json").exists()
    assert (runtime_dir / "unregistered.json").exists()
    assert "pruned" not in result


def test_bootstrap_preserves_registry_and_segment_defaults(tmp_path):
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

    before_registry = (data_dir / "workflow-registry.json").read_text(encoding="utf-8")
    before_defaults = (data_dir / "segment-defaults.json").read_text(encoding="utf-8")

    result = service.bootstrap_workflow_store(seed_dir, runtime_dir, data_dir)

    assert result["created"] == ["1-images_81.json"]
    assert (runtime_dir / "1-images.json").exists()
    assert (runtime_dir / "1-images.paramconfig.json").exists()
    assert (data_dir / "workflow-registry.json").read_text(encoding="utf-8") == before_registry
    assert (data_dir / "segment-defaults.json").read_text(encoding="utf-8") == before_defaults
