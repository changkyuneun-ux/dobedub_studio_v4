from __future__ import annotations

import io
from datetime import datetime

import pytest

from backend.app.core.security import create_access_token
from backend.app.db.models import Asset, User
from backend.app.db.session import SessionLocal
from backend.app.services import studio_api_service
from backend.app.services.grok_image_prompt_service import GrokImagePromptResult
from backend.app.services.storage_backends import S3AssetStorage


class FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], dict] = {}
        self.presigned: list[tuple[str, dict, int]] = []

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": kwargs["Body"],
            "ContentLength": len(kwargs["Body"]),
            "ContentType": kwargs.get("ContentType"),
            "ETag": '"fake-put-etag"',
        }
        return {"ETag": '"fake-put-etag"'}

    def head_object(self, **kwargs):
        stored = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {
            "ContentLength": stored["ContentLength"],
            "ContentType": stored["ContentType"],
            "ETag": stored.get("ETag", '"etag"'),
            "LastModified": stored.get("LastModified", datetime(2026, 9, 9)),
        }

    def get_object(self, **kwargs):
        stored = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": stored["Body"]}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned.append((operation, Params, ExpiresIn))
        return f"https://example.test/{Params['Bucket']}/{Params['Key']}?op={operation}"


def _install_fake_s3(monkeypatch, fake: FakeS3Client):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("PERSISTENCE_BACKEND", "db")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio-local")
    monkeypatch.setenv("S3_PREFIX", "local")
    monkeypatch.setattr(
        studio_api_service,
        "s3_asset_storage",
        lambda: S3AssetStorage(bucket="dobedub-studio-local", prefix="local", client=fake),
    )


def _headers(user_id: str) -> dict[str, str]:
    token = create_access_token({"id": user_id, "name": user_id, "role": "OPERATOR"})
    return {"Authorization": f"Bearer {token['accessToken']}"}


def test_presign_s3_upload_requires_item_scope(monkeypatch):
    _install_fake_s3(monkeypatch, FakeS3Client())

    with pytest.raises(ValueError, match="requestBatchId"):
        studio_api_service.create_s3_upload_presign(
            {"fileName": "scene.png", "mimeType": "image/png", "jobId": "task_1"},
            created_by="operator",
        )


def test_presign_and_complete_s3_upload_registers_scoped_asset(db_session, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)

    presign = studio_api_service.create_s3_upload_presign(
        {
            "fileName": "scene 001.png",
            "mimeType": "image/png",
            "requestBatchId": "rpb_2b7a1e329dc84413",
            "requestItemId": "rpi_47a88a1d24594f90",
            "jobId": "task_123",
        },
        created_by="operator",
    )

    assert presign["assetId"].startswith("asset_")
    assert presign["storageKey"] == (
        f"local/request-batches/rpb_2b7a1e329dc84413/items/rpi_47a88a1d24594f90/"
        f"jobs/task_123/inputs/{presign['assetId']}/scene_001.png"
    )
    assert presign["headers"] == {"Content-Type": "image/png"}

    fake.objects[("dobedub-studio-local", presign["storageKey"])] = {
        "ContentLength": 5,
        "ContentType": "image/png",
    }
    completed = studio_api_service.complete_s3_upload(
        {
            "assetId": presign["assetId"],
            "fileName": "scene 001.png",
            "mimeType": "image/png",
            "storageKey": presign["storageKey"],
            "sizeBytes": 5,
            "requestBatchId": "rpb_2b7a1e329dc84413",
            "requestItemId": "rpi_47a88a1d24594f90",
            "jobId": "task_123",
        },
        created_by="operator",
    )

    assert completed["assetId"] == presign["assetId"]
    assert completed["storageBackend"] == "s3"
    assert completed["storageKey"] == presign["storageKey"]
    assert completed["downloadUrl"] == f"/api/files/{presign['assetId']}"

    session = SessionLocal()
    try:
        asset = session.get(Asset, presign["assetId"])
        assert asset is not None
        assert asset.storage_backend == "s3"
        assert asset.storage_key == presign["storageKey"]
        assert asset.metadata_json["requestBatchId"] == "rpb_2b7a1e329dc84413"
        assert asset.metadata_json["requestItemId"] == "rpi_47a88a1d24594f90"
        assert asset.metadata_json["jobId"] == "task_123"
        assert asset.metadata_json["createdBy"] == "operator"
    finally:
        session.close()


def test_s3_upload_presign_and_complete_api(api_client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    session = SessionLocal()
    try:
        session.add(User(id="operator", name="operator", role="OPERATOR", permissions_json=["jobs:run"], is_active=True))
        session.commit()
    finally:
        session.close()

    presign_response = api_client.post(
        "/api/uploads/presign",
        headers=_headers("operator"),
        json={
            "fileName": "scene.png",
            "mimeType": "image/png",
            "requestBatchId": "rpb_api",
            "requestItemId": "rpi_api",
            "jobId": "task_api",
        },
    )

    assert presign_response.status_code == 201
    presign = presign_response.json()
    fake.objects[("dobedub-studio-local", presign["storageKey"])] = {
        "ContentLength": 5,
        "ContentType": "image/png",
    }

    complete_response = api_client.post(
        "/api/uploads/complete",
        headers=_headers("operator"),
        json={
            "assetId": presign["assetId"],
            "fileName": "scene.png",
            "mimeType": "image/png",
            "storageKey": presign["storageKey"],
            "sizeBytes": 5,
            "requestBatchId": "rpb_api",
            "requestItemId": "rpi_api",
            "jobId": "task_api",
        },
    )

    assert complete_response.status_code == 201
    completed = complete_response.json()
    assert completed["assetId"] == presign["assetId"]
    assert completed["storageBackend"] == "s3"


def test_legacy_upload_api_stores_input_image_in_s3(api_client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    session = SessionLocal()
    try:
        session.add(User(id="operator", name="operator", role="OPERATOR", permissions_json=["jobs:run"], is_active=True))
        session.commit()
    finally:
        session.close()

    response = api_client.post(
        "/api/uploads",
        headers=_headers("operator"),
        json={
            "fileName": "scene.png",
            "mimeType": "image/png",
            "dataUrl": (
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            ),
        },
    )

    assert response.status_code == 201
    uploaded = response.json()
    expected_key = f"local/uploads/{uploaded['assetId']}/scene.png"
    assert ("dobedub-studio-local", expected_key) in fake.objects
    assert fake.objects[("dobedub-studio-local", expected_key)]["ContentType"] == "image/png"

    session = SessionLocal()
    try:
        asset = session.get(Asset, uploaded["assetId"])
        assert asset is not None
        assert asset.asset_type == "input_image"
        assert asset.storage_backend == "s3"
        assert asset.storage_key == expected_key
        assert asset.public_url == f"s3://dobedub-studio-local/{expected_key}"
        assert asset.metadata_json["createdBy"] == "operator"
    finally:
        session.close()


def test_s3_file_access_redirects_to_presigned_get(api_client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    session = SessionLocal()
    try:
        session.add(User(id="operator", name="operator", role="OPERATOR", permissions_json=["jobs:run", "history:read"], is_active=True))
        session.add(Asset(
            id="asset_s3_file",
            asset_type="input_image",
            file_name="scene.png",
            mime_type="image/png",
            size_bytes=5,
            storage_backend="s3",
            storage_key="local/request-batches/rpb_api/items/rpi_api/jobs/task_api/inputs/asset_s3_file/scene.png",
            public_url="s3://dobedub-studio-local/local/request-batches/rpb_api/items/rpi_api/jobs/task_api/inputs/asset_s3_file/scene.png",
            metadata_json={"createdBy": "operator"},
        ))
        session.commit()
    finally:
        session.close()

    response = api_client.get(
        "/api/files/asset_s3_file",
        headers=_headers("operator"),
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://example.test/dobedub-studio-local/local/request-batches/")
    assert fake.presigned[-1][0] == "get_object"


def test_s3_file_download_streams_through_api_without_redirect(api_client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    session = SessionLocal()
    try:
        session.add(User(id="operator", name="operator", role="OPERATOR", permissions_json=["jobs:run", "history:read"], is_active=True))
        session.add(Asset(
            id="asset_s3_download",
            asset_type="output_video",
            file_name="final.mp4",
            mime_type="video/mp4",
            size_bytes=8,
            storage_backend="s3",
            storage_key="local/request-batches/rpb_api/items/rpi_api/jobs/task_api/outputs/asset_s3_download/final.mp4",
            public_url="s3://dobedub-studio-local/local/request-batches/rpb_api/items/rpi_api/jobs/task_api/outputs/asset_s3_download/final.mp4",
            metadata_json={"createdBy": "operator"},
        ))
        session.commit()
    finally:
        session.close()
    fake.objects[("dobedub-studio-local", "local/request-batches/rpb_api/items/rpi_api/jobs/task_api/outputs/asset_s3_download/final.mp4")] = {
        "Body": io.BytesIO(b"mp4-data"),
        "ContentLength": 8,
        "ContentType": "video/mp4",
    }

    response = api_client.get(
        "/api/files/asset_s3_download?download=1",
        headers=_headers("operator"),
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.content == b"mp4-data"
    assert response.headers["content-disposition"] == 'attachment; filename="final.mp4"'
    assert fake.presigned == []


def test_s3_uploaded_image_can_generate_grok_prompt(api_client, monkeypatch):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    monkeypatch.setenv("GROK_ENABLED", "1")
    monkeypatch.setenv("GROK_API_KEY", "test-key")
    monkeypatch.setattr(
        "backend.app.api.v1.prompts.active_instruction_text",
        lambda _workflow_id: ("workflow instruction", "wf@1"),
    )
    calls = []

    def fake_generate(_settings, **kwargs):
        calls.append(kwargs)
        return GrokImagePromptResult(
            "A character gently shifts posture, locked camera, smooth movement.",
            "static_character",
            [],
            {"output_text": "{}"},
        )

    monkeypatch.setattr("backend.app.api.v1.prompts.generate_image_prompt", fake_generate)
    session = SessionLocal()
    try:
        session.add(User(id="operator", name="operator", role="OPERATOR", permissions_json=["jobs:run", "prompts:build"], is_active=True))
        session.add(Asset(
            id="asset_grok_s3",
            asset_type="input_image",
            file_name="scene.png",
            mime_type="image/png",
            size_bytes=5,
            storage_backend="s3",
            storage_key="local/uploads/asset_grok_s3/scene.png",
            public_url="s3://dobedub-studio-local/local/uploads/asset_grok_s3/scene.png",
            metadata_json={"createdBy": "operator"},
        ))
        session.commit()
    finally:
        session.close()
    fake.objects[("dobedub-studio-local", "local/uploads/asset_grok_s3/scene.png")] = {
        "Body": io.BytesIO(b"png-data"),
        "ContentLength": 8,
        "ContentType": "image/png",
    }

    response = api_client.post(
        "/api/prompts/image-drafts/generate",
        headers=_headers("operator"),
        json={"assetId": "asset_grok_s3", "workflowId": "1-images.json", "slotIndex": 1},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "READY"
    assert calls[0]["asset_bytes"] == b"png-data"
    assert calls[0]["file_name"] == "scene.png"
