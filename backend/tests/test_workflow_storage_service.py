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
