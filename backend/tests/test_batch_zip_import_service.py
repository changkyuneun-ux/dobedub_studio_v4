from __future__ import annotations

from io import BytesIO
import unicodedata
import zipfile

import pytest

from backend.app.db.models import Asset
from backend.app.db.session import SessionLocal
from backend.app.services.storage_backends import S3AssetStorage


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _utf8_name_read_as_cp437(value: str) -> str:
    return unicodedata.normalize("NFD", value).encode("utf-8").decode("cp437")


def test_zip_import_recursively_registers_nested_images(monkeypatch, tmp_path):
    from backend.app.services import batch_zip_import_service

    registered: list[tuple[str, str, str]] = []

    def fake_register_asset(path, asset_type, mime_type=None, file_name=None):
        asset_id = f"asset_{len(registered) + 1}"
        registered.append((path.read_text(encoding="latin1"), asset_type, file_name))
        return {"assetId": asset_id, "fileName": file_name or path.name}

    monkeypatch.setattr(batch_zip_import_service.studio_api_service, "register_asset", fake_register_asset)

    result = batch_zip_import_service.import_zip_bytes(
        _zip_bytes({
            "shoot-0906/0001.jpg": b"one",
            "shoot-0906/nested/0002.png": b"two",
            "shoot-0906/__MACOSX/ignored.jpg": b"skip",
            "shoot-0906/.DS_Store": b"skip",
            "shoot-0906/readme.txt": b"skip",
        }),
        zip_file_name="shoot-0906.zip",
        work_dir=tmp_path,
    )

    assert result.source_dir_name == "shoot-0906"
    assert result.source_zip_file_name == "shoot-0906.zip"
    assert result.image_count == 2
    assert result.items == [
        {"assetId": "asset_1", "fileName": "0001.jpg", "relativePath": "shoot-0906/0001.jpg"},
        {"assetId": "asset_2", "fileName": "0002.png", "relativePath": "shoot-0906/nested/0002.png"},
    ]
    assert [entry[1] for entry in registered] == ["input_image", "input_image"]


def test_zip_import_uses_zip_stem_when_images_have_multiple_top_level_dirs(monkeypatch, tmp_path):
    from backend.app.services import batch_zip_import_service

    monkeypatch.setattr(
        batch_zip_import_service.studio_api_service,
        "register_asset",
        lambda path, asset_type, mime_type=None, file_name=None: {"assetId": f"asset_{file_name}", "fileName": file_name},
    )

    result = batch_zip_import_service.import_zip_bytes(
        _zip_bytes({"a/0001.jpg": PNG_1X1, "b/0002.jpg": PNG_1X1}),
        zip_file_name="픽미툰_씬.zip",
        work_dir=tmp_path,
    )

    assert result.source_dir_name == "픽미툰_씬"
    assert [item["relativePath"] for item in result.items] == ["a/0001.jpg", "b/0002.jpg"]


def test_zip_import_recovers_macos_korean_paths_without_utf8_flag(monkeypatch, tmp_path):
    from backend.app.services import batch_zip_import_service

    monkeypatch.setattr(
        batch_zip_import_service.studio_api_service,
        "register_asset",
        lambda path, asset_type, mime_type=None, file_name=None: {"assetId": f"asset_{file_name}", "fileName": file_name},
    )
    broken_root = _utf8_name_read_as_cp437("2권 08-10화-테스트")
    broken_child = _utf8_name_read_as_cp437("2권 08화")

    result = batch_zip_import_service.import_zip_bytes(
        _zip_bytes({f"{broken_root}/{broken_child}/0001.jpg": PNG_1X1}),
        zip_file_name="2권 08-10화-테스트.zip",
        work_dir=tmp_path,
    )

    assert result.source_dir_name == "2권 08-10화-테스트"
    assert result.items == [
        {
            "assetId": "asset_0001.jpg",
            "fileName": "0001.jpg",
            "relativePath": "2권 08-10화-테스트/2권 08화/0001.jpg",
        }
    ]


def test_zip_import_stores_batch_inputs_in_s3_when_storage_backend_is_s3(db_session, monkeypatch, tmp_path):
    from backend.app.services import batch_zip_import_service, studio_api_service

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
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("PERSISTENCE_BACKEND", "db")
    monkeypatch.setenv("S3_BUCKET", "dobedub-studio-local")
    monkeypatch.setenv("S3_PREFIX", "local")
    monkeypatch.setattr(
        studio_api_service,
        "s3_asset_storage",
        lambda: S3AssetStorage(bucket="dobedub-studio-local", prefix="local", client=fake),
    )

    result = batch_zip_import_service.import_zip_bytes(
        _zip_bytes({"shoot/0001.png": PNG_1X1, "shoot/0002.png": PNG_1X1}),
        zip_file_name="shoot.zip",
        work_dir=tmp_path,
        batch_job_id="operator_shoot_260909",
    )

    assert [item["requestItemId"] for item in result.items] == ["item_0001", "item_0002"]
    first_key = f"local/batches/operator_shoot_260909/items/item_0001/inputs/{result.items[0]['assetId']}/0001.png"
    second_key = f"local/batches/operator_shoot_260909/items/item_0002/inputs/{result.items[1]['assetId']}/0002.png"
    assert ("dobedub-studio-local", first_key) in fake.objects
    assert ("dobedub-studio-local", second_key) in fake.objects

    session = SessionLocal()
    try:
        first_asset = session.get(Asset, result.items[0]["assetId"])
        assert first_asset is not None
        assert first_asset.storage_backend == "s3"
        assert first_asset.storage_key == first_key
        assert first_asset.metadata_json["batchJobId"] == "operator_shoot_260909"
        assert first_asset.metadata_json["requestItemId"] == "item_0001"
    finally:
        session.close()


@pytest.mark.parametrize("entry_name", ["../evil.jpg", "/absolute/evil.jpg", "safe/../../evil.jpg"])
def test_zip_import_rejects_unsafe_paths(entry_name, tmp_path):
    from backend.app.services import batch_zip_import_service

    with pytest.raises(ValueError, match="안전하지 않은 ZIP 경로"):
        batch_zip_import_service.import_zip_bytes(
            _zip_bytes({entry_name: PNG_1X1}),
            zip_file_name="bad.zip",
            work_dir=tmp_path,
        )


def test_zip_import_rejects_zip_without_images(tmp_path):
    from backend.app.services import batch_zip_import_service

    with pytest.raises(ValueError, match="이미지 파일이 없습니다"):
        batch_zip_import_service.import_zip_bytes(
            _zip_bytes({"readme.txt": b"not image"}),
            zip_file_name="empty.zip",
            work_dir=tmp_path,
        )
