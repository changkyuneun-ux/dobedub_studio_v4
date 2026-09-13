"""Batch ZIP export: names, prefix and gzip bypass."""
from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager

from backend.app.db.models import Asset, BatchJob, ImagePromptDraft, TaskInputAsset, TaskOutputAsset, User, WorkflowTask
from backend.app.services import batch_zip_service


def test_entry_name_uses_output_prefix_and_mp4_extension():
    assert batch_zip_service.zip_entry_name("image1.jpg", set()) == "output/image1.mp4"


def test_entry_name_indexes_duplicates():
    used: set[str] = set()
    first = batch_zip_service.zip_entry_name("image1.jpg", used)
    used.add(first)
    second = batch_zip_service.zip_entry_name("image1.png", used)
    used.add(second)
    third = batch_zip_service.zip_entry_name("image1.webp", used)
    assert [first, second, third] == ["output/image1.mp4", "output/image1-1.mp4", "output/image1-2.mp4"]


def test_zip_response_headers_bypass_gzip_middleware():
    assert batch_zip_service.ZIP_RESPONSE_HEADERS["Content-Encoding"] == "identity"


def test_stream_batch_zip_produces_readable_archive(db_session, tmp_path, monkeypatch):
    source_path = tmp_path / "video.mp4"
    source_path.write_bytes(b"mp4-bytes")
    db_session.add(User(id="operator_1", name="Operator", role="OPERATOR"))
    db_session.add(BatchJob(
        id="batch_zip",
        workflow_id="Blowbang1.json",
        status="COMPLETE",
        total_images=1,
        created_by="operator_1",
    ))
    db_session.add_all([
        Asset(id="input_asset", asset_type="input", file_name="image1.jpg", mime_type="image/jpeg", size_bytes=1, storage_key="inputs/image1.jpg", metadata_json={}),
        Asset(id="output_asset", asset_type="output", file_name="runpod-output.mp4", mime_type="video/mp4", size_bytes=9, storage_key=str(source_path), metadata_json={}),
    ])
    db_session.add(WorkflowTask(
        id="task_zip",
        workflow_id="Blowbang1.json",
        status="COMPLETED",
        user_id="operator_1",
        batch_job_id="batch_zip",
    ))
    db_session.add(TaskInputAsset(task_id="task_zip", asset_id="input_asset", slot_index=1))
    db_session.add(TaskOutputAsset(task_id="task_zip", asset_id="output_asset", output_role="final"))
    db_session.commit()
    monkeypatch.setattr("backend.app.services.studio_api_service.get_asset", lambda _asset_id: ({}, source_path))

    chunks, skipped = batch_zip_service.stream_batch_zip("batch_zip", task_ids=None)

    with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert archive.namelist() == ["output/image1.mp4"]
        assert archive.read("output/image1.mp4") == b"mp4-bytes"
    assert skipped == 0


def test_stream_batch_zip_preserves_uploaded_directory_shape_with_output_suffixes(db_session, tmp_path, monkeypatch):
    first_path = tmp_path / "first.mp4"
    second_path = tmp_path / "second.mp4"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    db_session.add(User(id="operator_1", name="Operator", role="OPERATOR"))
    db_session.add(BatchJob(
        id="operator_hong_260906",
        workflow_id="Blowbang1.json",
        status="COMPLETE",
        source_dir_name="홍길동",
        source_zip_file_name="홍길동.zip",
        total_images=2,
        created_by="operator_1",
    ))
    db_session.add_all([
        Asset(id="input_a", asset_type="input", file_name="a.jpg", mime_type="image/jpeg", size_bytes=1, storage_key="inputs/a.jpg", metadata_json={}),
        Asset(id="input_b", asset_type="input", file_name="b.jpg", mime_type="image/jpeg", size_bytes=1, storage_key="inputs/b.jpg", metadata_json={}),
        Asset(id="output_a", asset_type="output", file_name="runpod-a.mp4", mime_type="video/mp4", size_bytes=5, storage_key=str(first_path), metadata_json={}),
        Asset(id="output_b", asset_type="output", file_name="runpod-b.mp4", mime_type="video/mp4", size_bytes=6, storage_key=str(second_path), metadata_json={}),
        ImagePromptDraft(
            id="draft_a",
            asset_id="input_a",
            workflow_id="Blowbang1.json",
            slot_index=1,
            provider="grok",
            model="grok",
            positive_prompt="a",
            raw_json={"sourceRelativePath": "홍길동/홍길동1/a.jpg", "sourceZipFileName": "홍길동.zip"},
            created_by="operator_1",
            batch_job_id="operator_hong_260906",
        ),
        ImagePromptDraft(
            id="draft_b",
            asset_id="input_b",
            workflow_id="Blowbang1.json",
            slot_index=2,
            provider="grok",
            model="grok",
            positive_prompt="b",
            raw_json={"sourceRelativePath": "홍길동/홍길동2/b.jpg", "sourceZipFileName": "홍길동.zip"},
            created_by="operator_1",
            batch_job_id="operator_hong_260906",
        ),
        WorkflowTask(
            id="task_a",
            workflow_id="Blowbang1.json",
            status="COMPLETED",
            user_id="operator_1",
            batch_job_id="operator_hong_260906",
            prompt_draft_id="draft_a",
        ),
        WorkflowTask(
            id="task_b",
            workflow_id="Blowbang1.json",
            status="COMPLETED",
            user_id="operator_1",
            batch_job_id="operator_hong_260906",
            prompt_draft_id="draft_b",
        ),
    ])
    db_session.add_all([
        TaskInputAsset(task_id="task_a", asset_id="input_a", slot_index=1),
        TaskInputAsset(task_id="task_b", asset_id="input_b", slot_index=1),
        TaskOutputAsset(task_id="task_a", asset_id="output_a", output_role="final"),
        TaskOutputAsset(task_id="task_b", asset_id="output_b", output_role="final"),
    ])
    db_session.commit()
    paths = {"output_a": first_path, "output_b": second_path}
    monkeypatch.setattr("backend.app.services.studio_api_service.get_asset", lambda asset_id: ({}, paths[asset_id]))

    chunks, skipped = batch_zip_service.stream_batch_zip("operator_hong_260906", task_ids=None)

    with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert archive.namelist() == [
            "홍길동_output/홍길동1_output/a.mp4",
            "홍길동_output/홍길동2_output/b.mp4",
        ]
        assert archive.read("홍길동_output/홍길동1_output/a.mp4") == b"first"
        assert archive.read("홍길동_output/홍길동2_output/b.mp4") == b"second"
    assert skipped == 0


def test_batch_zip_download_file_name_uses_source_zip_stem(api_client, db_session, tmp_path, monkeypatch):
    source_path = tmp_path / "video.mp4"
    source_path.write_bytes(b"mp4")
    db_session.add(User(
        id="history-user",
        name="History User",
        email=None,
        role="SUPER_ADMIN",
        permissions_json=["admin:*"],
        is_active=True,
    ))
    db_session.add(BatchJob(
        id="batch_zip_filename",
        workflow_id="Blowbang1.json",
        status="COMPLETE",
        source_dir_name="홍길동",
        source_zip_file_name="홍길동.zip",
        total_images=1,
        created_by="history-user",
    ))
    db_session.add_all([
        Asset(id="input_file", asset_type="input", file_name="a.jpg", mime_type="image/jpeg", size_bytes=1, storage_key="inputs/a.jpg", metadata_json={}),
        Asset(id="output_file", asset_type="output", file_name="out.mp4", mime_type="video/mp4", size_bytes=3, storage_key=str(source_path), metadata_json={}),
        WorkflowTask(id="task_file", workflow_id="Blowbang1.json", status="COMPLETED", user_id="history-user", batch_job_id="batch_zip_filename"),
        TaskInputAsset(task_id="task_file", asset_id="input_file", slot_index=1),
        TaskOutputAsset(task_id="task_file", asset_id="output_file", output_role="final"),
    ])
    db_session.commit()
    monkeypatch.setattr("backend.app.services.studio_api_service.get_asset", lambda _asset_id: ({}, source_path))

    from backend.app.core.security import create_access_token

    token = create_access_token({"id": "history-user", "name": "History User", "role": "SUPER_ADMIN"})
    response = api_client.get(
        "/api/batch-jobs/batch_zip_filename/download",
        headers={"Authorization": f"Bearer {token['accessToken']}"},
    )

    assert response.status_code == 200
    assert "filename*=UTF-8''%ED%99%8D%EA%B8%B8%EB%8F%99_output.zip" in response.headers["content-disposition"]


def test_stream_batch_zip_reads_s3_output_assets_without_local_path(db_session, monkeypatch):
    db_session.add(User(id="operator_1", name="Operator", role="OPERATOR"))
    db_session.add(BatchJob(
        id="batch_s3_zip",
        workflow_id="Blowbang1.json",
        status="COMPLETE",
        total_images=1,
        created_by="operator_1",
    ))
    db_session.add_all([
        Asset(id="input_s3", asset_type="input", file_name="image1.jpg", mime_type="image/jpeg", size_bytes=1, storage_key="inputs/image1.jpg", metadata_json={}),
        Asset(
            id="output_s3",
            asset_type="output",
            file_name="runpod-output.mp4",
            mime_type="video/mp4",
            size_bytes=9,
            storage_backend="s3",
            storage_key="prod/batches/batch_s3_zip/items/item_1/jobs/task_1/outputs/output_s3/runpod-output.mp4",
            metadata_json={},
        ),
    ])
    db_session.add(WorkflowTask(
        id="task_s3_zip",
        workflow_id="Blowbang1.json",
        status="COMPLETED",
        user_id="operator_1",
        batch_job_id="batch_s3_zip",
    ))
    db_session.add(TaskInputAsset(task_id="task_s3_zip", asset_id="input_s3", slot_index=1))
    db_session.add(TaskOutputAsset(task_id="task_s3_zip", asset_id="output_s3", output_role="final"))
    db_session.commit()

    class FakeS3Storage:
        def stat(self, storage_key):
            assert storage_key == "prod/batches/batch_s3_zip/items/item_1/jobs/task_1/outputs/output_s3/runpod-output.mp4"
            return object()

        @contextmanager
        def open_read(self, storage_key):
            assert storage_key == "prod/batches/batch_s3_zip/items/item_1/jobs/task_1/outputs/output_s3/runpod-output.mp4"
            yield io.BytesIO(b"s3-mp4-bytes")

    monkeypatch.setattr("backend.app.services.studio_api_service.s3_asset_storage", lambda: FakeS3Storage())

    chunks, skipped = batch_zip_service.stream_batch_zip("batch_s3_zip", task_ids=None)

    with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert archive.namelist() == ["output/image1.mp4"]
        assert archive.read("output/image1.mp4") == b"s3-mp4-bytes"
    assert skipped == 0


def test_stream_batch_zip_skips_missing_s3_output_assets(db_session, monkeypatch):
    db_session.add(User(id="operator_1", name="Operator", role="OPERATOR"))
    db_session.add(BatchJob(
        id="batch_s3_missing_zip",
        workflow_id="Blowbang1.json",
        status="COMPLETE",
        total_images=1,
        created_by="operator_1",
    ))
    db_session.add_all([
        Asset(id="input_s3_missing", asset_type="input", file_name="image1.jpg", mime_type="image/jpeg", size_bytes=1, storage_key="inputs/image1.jpg", metadata_json={}),
        Asset(
            id="output_s3_missing",
            asset_type="output",
            file_name="runpod-output.mp4",
            mime_type="video/mp4",
            size_bytes=9,
            storage_backend="s3",
            storage_key="prod/batches/batch_s3_missing_zip/items/item_1/jobs/task_1/outputs/output_s3_missing/runpod-output.mp4",
            metadata_json={},
        ),
    ])
    db_session.add(WorkflowTask(
        id="task_s3_missing_zip",
        workflow_id="Blowbang1.json",
        status="COMPLETED",
        user_id="operator_1",
        batch_job_id="batch_s3_missing_zip",
    ))
    db_session.add(TaskInputAsset(task_id="task_s3_missing_zip", asset_id="input_s3_missing", slot_index=1))
    db_session.add(TaskOutputAsset(task_id="task_s3_missing_zip", asset_id="output_s3_missing", output_role="final"))
    db_session.commit()

    class FakeS3Storage:
        def stat(self, storage_key):
            raise FileNotFoundError(storage_key)

        def open_read(self, storage_key):
            raise FileNotFoundError(storage_key)

    monkeypatch.setattr("backend.app.services.studio_api_service.s3_asset_storage", lambda: FakeS3Storage())

    try:
        batch_zip_service.stream_batch_zip("batch_s3_missing_zip", task_ids=None)
    except ValueError as exc:
        assert str(exc) == "내려받을 완료 영상이 없습니다."
    else:
        raise AssertionError("missing S3 output must be skipped until no downloadable assets remain")
