from __future__ import annotations

import json

from backend.app.db.models import Asset
from backend.app.services import studio_api_service


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


def test_prepare_workflow_patches_load_image_to_s3_image_name(tmp_path, db_session, monkeypatch):
    monkeypatch.setenv("PERSISTENCE_BACKEND", "db")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio")
    monkeypatch.setenv("WORKFLOWS_DIR", str(tmp_path))

    workflow_path = tmp_path / "s3-i2v.json"
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
        "workflowId": "s3-i2v.json",
        "keyframes": [{"index": 1, "uploadId": "asset_s3_input", "fileName": "ignored-source-name.png"}],
        "segments": [],
    })

    assert images[0]["name"] == "scene.png"
    assert workflow["1"]["inputs"]["image"] == "scene.png"
    assert patch_summary["images"] == [{"node": "1", "image": "scene.png"}]
