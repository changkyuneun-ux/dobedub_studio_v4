from __future__ import annotations

import json
from pathlib import Path

from backend.app.services import output_service, studio_api_service


def test_save_runpod_outputs_registers_s3_object_without_downloading(tmp_path):
    calls = []

    def register_asset(path: Path, asset_type: str):
        calls.append((path, asset_type))
        raise AssertionError("S3 object outputs must not be downloaded through ECS")

    saved = output_service.save_runpod_outputs(
        {
            "output": {
                "videos": [{
                    "type": "s3_object",
                    "assetId": "asset_output_001",
                    "bucket": "dobedub-studio",
                    "key": "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/final.mp4",
                    "filename": "final.mp4",
                    "mimeType": "video/mp4",
                    "sizeBytes": 123,
                    "node_id": "42",
                }]
            }
        },
        {"taskId": "task_1", "payload": {"requestBatchId": "rpb_1", "requestItemId": "rpi_1"}},
        tmp_path,
        register_asset,
    )

    assert calls == []
    assert saved == {
        "assets": [{
            "assetId": "asset_output_001",
            "fileName": "final.mp4",
            "downloadUrl": "/api/files/asset_output_001",
            "kind": "videos",
            "mimeType": "video/mp4",
            "sizeBytes": 123,
            "outputRole": "final",
            "segmentIndex": 1,
            "storageBackend": "s3",
            "storageKey": "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/final.mp4",
            "publicUrl": "s3://dobedub-studio/prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/final.mp4",
        }],
        "remoteUrls": [],
    }


def test_studio_save_runpod_outputs_reads_s3_manifest_when_runpod_status_has_no_inline_output(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")

    opened_keys = []

    class ManifestBody:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "jobId": "task_1",
                "status": "completed",
                "outputs": [{
                    "type": "video",
                    "assetId": "asset_output_001",
                    "bucket": "dobedub-studio",
                    "key": "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/final.mp4",
                    "filename": "final.mp4",
                    "contentType": "video/mp4",
                    "sizeBytes": 123,
                }],
            }).encode("utf-8")

    class FakeStorage:
        def open_read(self, storage_key):
            opened_keys.append(storage_key)
            return ManifestBody()

    def unexpected_register_asset(*_args, **_kwargs):
        raise AssertionError("S3 manifest outputs must be registered without ECS downloading media")

    monkeypatch.setattr(studio_api_service, "s3_asset_storage", lambda: FakeStorage())
    monkeypatch.setattr(studio_api_service, "register_asset", unexpected_register_asset)

    saved = studio_api_service.save_runpod_outputs(
        {"status": "COMPLETED", "output": {}},
        {
            "taskId": "task_1",
            "payload": {
                "requestBatchId": "rpb_1",
                "requestItemId": "rpi_1",
            },
        },
    )

    assert opened_keys == [
        "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/manifests/runpod-result.json"
    ]
    assert saved["assets"][0]["assetId"] == "asset_output_001"
    assert saved["assets"][0]["storageBackend"] == "s3"
    assert saved["assets"][0]["storageKey"] == (
        "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/final.mp4"
    )
