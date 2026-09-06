"""Batch ZIP export: names, prefix and gzip bypass."""
from __future__ import annotations

import io
import zipfile

from backend.app.db.models import Asset, BatchJob, TaskInputAsset, TaskOutputAsset, User, WorkflowTask
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
