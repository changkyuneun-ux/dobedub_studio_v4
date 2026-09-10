from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.services import output_service, studio_api_service
from backend.app.services.storage_backends import StoredObject


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
            "assetId": "asset_task_1_001",
            "fileName": "upload.mp4",
            "downloadUrl": "/api/files/asset_task_1_001",
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


def test_s3_output_asset_ids_are_scoped_to_task(tmp_path):
    def register_asset(path: Path, asset_type: str):
        raise AssertionError("S3 object outputs must not be downloaded through ECS")

    first = output_service.save_runpod_outputs(
        {
            "output": {
                "videos": [{
                    "type": "s3_object",
                    "assetId": "asset_output_001",
                    "bucket": "dobedub-studio",
                    "key": "prod/request-batches/rpb_1/items/rpi_1/jobs/task_a/outputs/asset_output_001/final.mp4",
                    "filename": "final.mp4",
                    "mimeType": "video/mp4",
                    "sizeBytes": 123,
                }]
            }
        },
        {"taskId": "task_a", "payload": {"requestBatchId": "rpb_1", "requestItemId": "rpi_1"}},
        tmp_path,
        register_asset,
    )
    second = output_service.save_runpod_outputs(
        {
            "output": {
                "videos": [{
                    "type": "s3_object",
                    "assetId": "asset_output_001",
                    "bucket": "dobedub-studio",
                    "key": "prod/request-batches/rpb_1/items/rpi_2/jobs/task_b/outputs/asset_output_001/final.mp4",
                    "filename": "final.mp4",
                    "mimeType": "video/mp4",
                    "sizeBytes": 456,
                }]
            }
        },
        {"taskId": "task_b", "payload": {"requestBatchId": "rpb_1", "requestItemId": "rpi_2"}},
        tmp_path,
        register_asset,
    )

    assert first["assets"][0]["assetId"] == "asset_task_a_001"
    assert second["assets"][0]["assetId"] == "asset_task_b_001"
    assert first["assets"][0]["assetId"] != second["assets"][0]["assetId"]
    assert first["assets"][0]["storageKey"].endswith("/task_a/outputs/asset_output_001/final.mp4")
    assert second["assets"][0]["storageKey"].endswith("/task_b/outputs/asset_output_001/final.mp4")


def test_s3_object_output_filename_uses_input_file_stem(tmp_path):
    def register_asset(path: Path, asset_type: str):
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
                }]
            }
        },
        {
            "taskId": "task_1",
            "payload": {
                "requestBatchId": "rpb_1",
                "requestItemId": "rpi_1",
                "keyframes": [{"fileName": "이미지1.png"}],
            },
        },
        tmp_path,
        register_asset,
    )

    assert saved["assets"][0]["fileName"] == "이미지1.mp4"


def test_studio_save_runpod_outputs_reads_s3_manifest_when_runpod_status_has_no_inline_output(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")

    opened_keys = []
    copied = []
    deleted = []

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

        def copy_stored_object(self, source_key, target_key):
            copied.append((source_key, target_key))
            return StoredObject(
                storage_backend="s3",
                storage_key=target_key,
                file_name=Path(target_key).name,
                mime_type="video/mp4",
                size_bytes=123,
                public_url=f"s3://dobedub-studio/{target_key}",
                bucket="dobedub-studio",
            )

        def delete(self, storage_key):
            deleted.append(storage_key)
            return True

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
                "keyframes": [{"fileName": "이미지1.png"}],
            },
        },
    )

    assert opened_keys == [
        "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/manifests/runpod-result.json"
    ]
    assert saved["assets"][0]["assetId"] == "asset_task_1_001"
    assert saved["assets"][0]["fileName"] == "이미지1.mp4"
    assert saved["assets"][0]["storageBackend"] == "s3"
    assert saved["assets"][0]["storageKey"] == (
        "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/이미지1.mp4"
    )
    assert copied == [(
        "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/final.mp4",
        "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/이미지1.mp4",
    )]
    assert deleted == [
        "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_output_001/final.mp4"
    ]


def test_studio_save_runpod_outputs_uses_zip_source_name_for_s3_manifest(monkeypatch):
    class ManifestBody:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "outputs": [{
                    "type": "video",
                    "assetId": "asset_output_001",
                    "bucket": "dobedub-studio",
                    "key": "prod/batches/batch_1/items/item_0003/jobs/task_1/outputs/asset_output_001/final.mp4",
                    "filename": "final.mp4",
                    "contentType": "video/mp4",
                    "sizeBytes": 123,
                }],
            }).encode("utf-8")

    class FakeStorage:
        def open_read(self, _storage_key):
            return ManifestBody()

        def copy_stored_object(self, _source_key, target_key):
            return StoredObject(
                storage_backend="s3",
                storage_key=target_key,
                file_name=Path(target_key).name,
                mime_type="video/mp4",
                size_bytes=123,
                public_url=f"s3://dobedub-studio/{target_key}",
                bucket="dobedub-studio",
            )

        def delete(self, _storage_key):
            return True

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")
    monkeypatch.setattr(studio_api_service, "s3_asset_storage", lambda: FakeStorage())

    saved = studio_api_service.save_runpod_outputs(
        {"status": "COMPLETED", "output": {}},
        {
            "taskId": "task_1",
            "payload": {
                "batchJobId": "batch_1",
                "requestItemId": "item_0003",
                "sourceRelativePath": "Test/제목 없음-4.jpg",
                "keyframes": [{"fileName": "-4.jpg"}],
            },
        },
    )

    assert saved["assets"][0]["fileName"] == "제목_없음-4.mp4"
    assert saved["assets"][0]["storageKey"] == (
        "prod/batches/batch_1/items/item_0003/jobs/task_1/outputs/asset_output_001/제목_없음-4.mp4"
    )


def test_studio_save_runpod_outputs_marks_missing_s3_manifest_retryable(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")

    class MissingManifestStorage:
        def open_read(self, _storage_key):
            raise FileNotFoundError("manifest is not available yet")

    monkeypatch.setattr(studio_api_service, "s3_asset_storage", lambda: MissingManifestStorage())

    with pytest.raises(studio_api_service.OutputImportPending, match="manifest"):
        studio_api_service.save_runpod_outputs(
            {"status": "COMPLETED", "output": {}},
            {"taskId": "task_1", "payload": {"requestBatchId": "rpb_1", "requestItemId": "rpi_1"}},
        )
