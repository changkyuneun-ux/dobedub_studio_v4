from __future__ import annotations

import json

import pytest

from backend.app.db.models import Asset
from backend.app.services import studio_api_service
from backend.app.services.storage_backends import S3AssetStorage


def test_s3_asset_to_runpod_image_uses_s3_uri(db_session, monkeypatch):
    monkeypatch.setenv("PERSISTENCE_BACKEND", "db")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    db_session.add(Asset(
        id="asset_s3_input",
        asset_type="input_image",
        file_name="scene.png",
        mime_type="image/png",
        size_bytes=5,
        storage_backend="s3",
        storage_key="prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_s3_input/scene.png",
        public_url="s3://dobedub-studio/prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_s3_input/scene.png",
        metadata_json={"requestBatchId": "rpb_1", "requestItemId": "rpi_1", "jobId": "task_1"},
    ))
    db_session.commit()

    image = studio_api_service.asset_to_runpod_image("asset_s3_input")

    assert image == {
        "assetId": "asset_s3_input",
        "name": "scene.png",
        "s3Uri": "s3://dobedub-studio/prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_s3_input/scene.png",
    }


def test_build_runpod_payload_uses_s3_images_and_scoped_output_prefix(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")

    payload = studio_api_service.build_runpod_payload(
        {"1": {"class_type": "Test"}},
        [{
            "assetId": "asset_s3_input",
            "name": "scene.png",
            "s3Uri": "s3://dobedub-studio/prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_s3_input/scene.png",
        }],
        {
            "requestBatchId": "rpb_1",
            "requestItemId": "rpi_1",
            "taskId": "task_1",
        },
    )

    assert payload["input"]["images"] == [{
        "assetId": "asset_s3_input",
        "name": "scene.png",
        "s3Uri": "s3://dobedub-studio/prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_s3_input/scene.png",
    }]
    assert payload["input"]["output"] == {
        "mode": "s3",
        "bucket": "dobedub-studio",
        "prefix": "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs",
        "manifestKey": "prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/manifests/runpod-result.json",
        "appJobId": "task_1",
    }


def test_build_runpod_payload_rejects_s3_submission_without_a_job_scope(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")

    with pytest.raises(ValueError, match="S3 output destination"):
        studio_api_service.build_runpod_payload({"1": {"class_type": "Test"}}, [], {})


def test_build_runpod_payload_uses_batch_item_output_prefix(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")

    payload = studio_api_service.build_runpod_payload(
        {"1": {"class_type": "Test"}},
        [],
        {
            "batchJobId": "송승화_Webtoon_capture_260909",
            "requestItemId": "item_0001",
            "taskId": "task_20260909_171753_c4a771",
        },
    )

    assert payload["input"]["output"] == {
        "mode": "s3",
        "bucket": "dobedub-studio",
        "prefix": "prod/batches/송승화_Webtoon_capture_260909/items/item_0001/jobs/task_20260909_171753_c4a771/outputs",
        "manifestKey": "prod/batches/송승화_Webtoon_capture_260909/items/item_0001/jobs/task_20260909_171753_c4a771/manifests/runpod-result.json",
        "appJobId": "task_20260909_171753_c4a771",
    }


def test_build_runpod_payload_uses_fallback_item_for_batch_without_request_item(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")

    payload = studio_api_service.build_runpod_payload(
        {"1": {"class_type": "Test"}},
        [],
        {
            "batchJobId": "함승현_Test_260909",
            "taskId": "task_20260909_173031_429aa5",
        },
    )

    assert payload["input"]["output"] == {
        "mode": "s3",
        "bucket": "dobedub-studio",
        "prefix": "prod/batches/함승현_Test_260909/items/item_0001/jobs/task_20260909_173031_429aa5/outputs",
        "manifestKey": "prod/batches/함승현_Test_260909/items/item_0001/jobs/task_20260909_173031_429aa5/manifests/runpod-result.json",
        "appJobId": "task_20260909_173031_429aa5",
    }


def test_build_runpod_payload_uses_job_output_prefix_for_direct_tasks(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("S3_PREFIX", "prod")

    payload = studio_api_service.build_runpod_payload(
        {"1": {"class_type": "Test"}},
        [],
        {"taskId": "task_direct_1"},
    )

    assert payload["input"]["output"] == {
        "mode": "s3",
        "bucket": "dobedub-studio",
        "prefix": "prod/jobs/task_direct_1/items/item_0001/outputs",
        "manifestKey": "prod/jobs/task_direct_1/items/item_0001/manifests/runpod-result.json",
        "appJobId": "task_direct_1",
    }


def test_prepare_workflow_patches_load_image_to_s3_image_name(tmp_path, db_session, monkeypatch):
    monkeypatch.setenv("PERSISTENCE_BACKEND", "db")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("WORKFLOWS_DIR", str(tmp_path))

    workflow_path = tmp_path / "1-images_81.json"
    workflow_path.write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
        "2": {"class_type": "WanImageToVideo", "inputs": {"image": ["1", 0], "width": 832, "height": 480}},
        "3": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video/ComfyUI"}},
    }), encoding="utf-8")
    db_session.add(Asset(
        id="asset_s3_input",
        asset_type="input_image",
        file_name="scene.png",
        mime_type="image/png",
        size_bytes=5,
        image_width=1920,
        image_height=1080,
        storage_backend="s3",
        storage_key="prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_s3_input/scene.png",
        public_url="s3://dobedub-studio/prod/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_s3_input/scene.png",
        metadata_json={"requestBatchId": "rpb_1", "requestItemId": "rpi_1", "jobId": "task_1"},
    ))
    db_session.commit()

    workflow, images, patch_summary = studio_api_service.prepare_workflow_for_job({
        "workflowId": "1-images_81.json",
        "keyframes": [{"index": 1, "uploadId": "asset_s3_input", "fileName": "ignored-source-name.png"}],
        "segments": [],
    })

    assert images[0]["name"] == "scene.png"
    assert workflow["1"]["inputs"]["image"] == "scene.png"
    assert patch_summary["images"] == [{"node": "1", "image": "scene.png"}]


def test_save_runpod_outputs_uploads_inline_outputs_to_s3_when_storage_backend_is_s3(db_session, monkeypatch, tmp_path):
    class FakeS3Client:
        def __init__(self):
            self.objects: dict[tuple[str, str], dict] = {}

        def put_object(self, **kwargs):
            self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
                "Body": kwargs["Body"],
                "ContentLength": len(kwargs["Body"]),
                "ContentType": kwargs.get("ContentType"),
            }
            return {"ETag": '"fake"'}

    fake = FakeS3Client()
    monkeypatch.setenv("PERSISTENCE_BACKEND", "db")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio-local")
    monkeypatch.setenv("S3_PREFIX", "local")
    monkeypatch.setattr(
        studio_api_service,
        "s3_asset_storage",
        lambda: S3AssetStorage(bucket="dobedub-studio-local", prefix="local", client=fake),
    )

    saved = studio_api_service.save_runpod_outputs(
        {"output": {"videos": [{"filename": "final.mp4", "data": "bXA0"}]}},
        {
            "taskId": "task_inline",
            "workflowId": "wan22_default_81.json",
            "payload": {
                "taskId": "task_inline",
                "batchJobId": "batch_inline",
                "requestItemId": "item_0001",
                "keyframes": [{"fileName": "scene.png"}],
                "segments": [{"index": 1}],
            },
        },
    )

    assert saved["assets"][0]["storageBackend"] == "s3"
    assert saved["assets"][0]["storageKey"].startswith(
        "local/batches/batch_inline/items/item_0001/jobs/task_inline/outputs/"
    )
    assert ("dobedub-studio-local", saved["assets"][0]["storageKey"]) in fake.objects
    assert fake.objects[("dobedub-studio-local", saved["assets"][0]["storageKey"])]["Body"] == b"mp4"


def test_save_runpod_outputs_uploads_inline_output_with_input_filename(db_session, monkeypatch, tmp_path):
    class FakeS3Client:
        def __init__(self):
            self.objects: dict[tuple[str, str], dict] = {}

        def put_object(self, **kwargs):
            self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
                "Body": kwargs["Body"],
                "ContentLength": len(kwargs["Body"]),
                "ContentType": kwargs.get("ContentType"),
            }
            return {"ETag": '"fake"'}

    fake = FakeS3Client()
    monkeypatch.setenv("PERSISTENCE_BACKEND", "db")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio-local")
    monkeypatch.setenv("S3_PREFIX", "local")
    monkeypatch.setattr(
        studio_api_service,
        "s3_asset_storage",
        lambda: S3AssetStorage(bucket="dobedub-studio-local", prefix="local", client=fake),
    )

    saved = studio_api_service.save_runpod_outputs(
        {"output": {"videos": [{"filename": "final.mp4", "data": "bXA0"}]}},
        {
            "taskId": "task_inline_name",
            "workflowId": "wan22_default_81.json",
            "payload": {
                "taskId": "task_inline_name",
                "batchJobId": "batch_inline_name",
                "requestItemId": "item_0001",
                "keyframes": [{"fileName": "이미지1.png"}],
                "segments": [{"index": 1}],
            },
        },
    )

    assert saved["assets"][0]["fileName"] == "이미지1.mp4"
    assert saved["assets"][0]["storageKey"].endswith("/이미지1.mp4")
