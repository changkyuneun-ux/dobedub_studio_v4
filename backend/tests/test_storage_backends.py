from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.services.storage_backends import LocalAssetStorage, S3AssetStorage


class FakeStreamingBody(BytesIO):
    pass


class FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], dict] = {}
        self.deleted: list[tuple[str, str]] = []
        self.presigned: list[tuple[str, dict, int]] = []

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            **kwargs,
            "Body": bytes(kwargs["Body"]),
            "ContentLength": len(kwargs["Body"]),
            "ETag": '"fake-etag"',
            "LastModified": datetime(2026, 9, 9),
        }
        return {"ETag": '"fake-etag"'}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        raw = Path(filename).read_bytes()
        self.objects[(bucket, key)] = {
            "Bucket": bucket,
            "Key": key,
            "Body": raw,
            "ContentLength": len(raw),
            "ContentType": (ExtraArgs or {}).get("ContentType"),
            "ETag": '"fake-upload-etag"',
            "LastModified": datetime(2026, 9, 9),
        }

    def head_object(self, **kwargs):
        stored = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {
            "ContentLength": stored["ContentLength"],
            "ContentType": stored.get("ContentType"),
            "ETag": stored.get("ETag"),
            "LastModified": stored.get("LastModified"),
        }

    def get_object(self, **kwargs):
        stored = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": FakeStreamingBody(stored["Body"])}

    def delete_object(self, **kwargs):
        self.deleted.append((kwargs["Bucket"], kwargs["Key"]))
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned.append((operation, Params, ExpiresIn))
        return f"https://example.test/{Params['Bucket']}/{Params['Key']}?op={operation}&expires={ExpiresIn}"


def test_local_storage_supports_read_and_stat(tmp_path):
    storage = LocalAssetStorage(tmp_path)

    stored = storage.save_bytes("request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_1/a.png", b"image", file_name="a.png", mime_type="image/png")

    assert stored.storage_backend == "local"
    assert stored.size_bytes == 5
    assert storage.stat(stored.storage_key).size_bytes == 5
    with storage.open_read(stored.storage_key) as stream:
        assert stream.read() == b"image"


def test_s3_storage_supports_stat_read_and_presigned_put():
    fake = FakeS3Client()
    storage = S3AssetStorage(bucket="dobedub-studio-local", prefix="local", client=fake)

    stored = storage.save_bytes(
        "request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_1/a.png",
        b"image",
        file_name="a.png",
        mime_type="image/png",
    )

    assert stored.storage_backend == "s3"
    assert stored.bucket == "dobedub-studio-local"
    assert stored.storage_key == "local/request-batches/rpb_1/items/rpi_1/jobs/task_1/inputs/asset_1/a.png"
    assert stored.etag == '"fake-etag"'
    stat = storage.stat(stored.storage_key)
    assert stat.size_bytes == 5
    assert stat.mime_type == "image/png"
    with storage.open_read(stored.storage_key) as stream:
        assert stream.read() == b"image"

    upload_url = storage.presigned_put(
        "request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_2/final.mp4",
        content_type="video/mp4",
        expires_in=900,
    )

    assert upload_url.startswith("https://example.test/dobedub-studio-local/local/request-batches/")
    assert fake.presigned[-1] == (
        "put_object",
        {
            "Bucket": "dobedub-studio-local",
            "Key": "local/request-batches/rpb_1/items/rpi_1/jobs/task_1/outputs/asset_2/final.mp4",
            "ContentType": "video/mp4",
        },
        900,
    )


def test_settings_read_local_s3_endpoint(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:4566")
    monkeypatch.setenv("S3_FORCE_PATH_STYLE", "1")

    settings = get_settings()

    assert settings.s3_endpoint_url == "http://127.0.0.1:4566"
    assert settings.s3_force_path_style is True
