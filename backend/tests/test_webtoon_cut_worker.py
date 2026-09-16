from __future__ import annotations

from pathlib import Path
import zipfile

import pytest
from sqlalchemy.dialects import mysql

from backend.app.db.models import Asset, WebtoonCutJob, WebtoonCutOutput
from backend.app.services.storage_backends import StoredObject
from backend.app.services.webtoon_panel_engine import CutResult, RenderedUnitResult


def _source_asset(asset_id: str = "asset_source") -> Asset:
    return Asset(
        id=asset_id,
        asset_type="webtoon_source_original",
        file_name="과학사_1권_내지_인쇄용_수정.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        storage_backend="s3",
        storage_key=f"prod/webtoon-cut/tests/{asset_id}/source.pdf",
        metadata_json={"createdBy": "user_1"},
    )


def _running_job(job_id: str = "wcut_worker_test") -> WebtoonCutJob:
    return WebtoonCutJob(
        id=job_id,
        status="running",
        input_kind="pdf",
        source_asset_id="asset_source",
        display_name="과학사_1권_내지_인쇄용_수정.pdf",
        safe_stem="science",
        total_units=1,
        metadata_json={"displayStem": "과학사_1권_내지_인쇄용_수정", "createdBy": "user_1"},
        created_by="user_1",
    )


class _FakeStorage:
    def save_file(self, key: str, path: Path, *, file_name: str, mime_type: str) -> StoredObject:
        return StoredObject(
            storage_backend="s3",
            storage_key=f"prod/{key}",
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
            public_url=f"s3://dobedub-studio/prod/{key}",
            bucket="dobedub-studio",
        )


def test_store_result_registers_cut_asset_without_nested_db_session(db_session, tmp_path, monkeypatch):
    from backend.app.db.session import SessionLocal as RealSessionLocal
    from backend.app.services import webtoon_cut_worker

    db_session.add(_source_asset())
    db_session.add(_running_job())
    db_session.commit()
    cut_path = tmp_path / "panel-01.png"
    cut_path.write_bytes(b"png")
    result = RenderedUnitResult(
        page_number=1,
        cuts=[CutResult(path=cut_path, cut_index=1, width=966, height=720, flags=[])],
        debug_overlay_path=None,
        mode="grid",
        flags=[],
    )
    session_opens = 0

    def counting_session_local():
        nonlocal session_opens
        session_opens += 1
        return RealSessionLocal()

    monkeypatch.setattr(webtoon_cut_worker, "SessionLocal", counting_session_local)
    monkeypatch.setattr(webtoon_cut_worker, "s3_asset_storage", lambda: _FakeStorage())

    webtoon_cut_worker._store_result("wcut_worker_test", result)

    assert session_opens == 1
    output = db_session.query(WebtoonCutOutput).filter_by(job_id="wcut_worker_test").one()
    asset = db_session.get(Asset, output.asset_id)
    job = db_session.get(WebtoonCutJob, "wcut_worker_test")
    assert asset is not None
    assert output.display_path == "과학사_1권_내지_인쇄용_수정/001-01.png"
    assert job.completed_units == 1
    assert job.generated_cut_count == 1


def test_process_job_marks_job_failed_when_worker_step_raises(db_session, tmp_path, monkeypatch):
    from backend.app.services import webtoon_cut_worker

    db_session.add(_source_asset())
    db_session.add(_running_job("wcut_failed_test"))
    db_session.commit()
    local_source = tmp_path / "source.png"
    local_source.write_bytes(b"png")

    monkeypatch.setattr(webtoon_cut_worker, "_materialize_asset", lambda _asset, _workdir: local_source)
    monkeypatch.setattr(webtoon_cut_worker, "_count_units", lambda _path, _input_kind: 1)
    monkeypatch.setattr(webtoon_cut_worker, "_is_zip", lambda _path: False)
    monkeypatch.setattr(webtoon_cut_worker, "_is_pdf", lambda _path: False)

    def raise_processing_error(*_args, **_kwargs):
        raise RuntimeError("synthetic split failure")

    monkeypatch.setattr(webtoon_cut_worker, "_process_image_job", raise_processing_error)

    result = webtoon_cut_worker.process_job("wcut_failed_test")

    job = db_session.get(WebtoonCutJob, "wcut_failed_test")
    assert result == {"processed": False, "jobId": "wcut_failed_test", "reason": "failed"}
    assert job.status == "failed"
    assert "synthetic split failure" in job.error_message


def test_process_image_job_passes_job_split_mode_to_runtime(db_session, tmp_path, monkeypatch):
    from backend.app.services import webtoon_cut_worker

    db_session.add(_source_asset())
    job = _running_job("wcut_dark_mode_test")
    job.input_kind = "image"
    job.metadata_json = {
        "displayStem": "dark-scroll",
        "createdBy": "user_1",
        "splitMode": "dark-webtoon",
    }
    db_session.add(job)
    db_session.commit()
    source = tmp_path / "dark-scroll.png"
    source.write_bytes(b"png")
    seen = []
    cut_path = tmp_path / "panel-01.png"
    cut_path.write_bytes(b"png")

    def fake_process_image_file(image_path, *, output_dir, page_number=None, split_mode="print"):
        seen.append((Path(image_path).name, page_number, split_mode))
        return RenderedUnitResult(
            page_number=page_number,
            cuts=[CutResult(path=cut_path, cut_index=1, width=72, height=36, flags=[])],
            debug_overlay_path=None,
            mode="dark_bg",
            flags=[],
        )

    monkeypatch.setattr(webtoon_cut_worker, "process_image_file", fake_process_image_file)
    monkeypatch.setattr(webtoon_cut_worker, "s3_asset_storage", lambda: _FakeStorage())

    webtoon_cut_worker._process_image_job("wcut_dark_mode_test", source, tmp_path)

    assert seen == [("dark-scroll.png", None, "dark-webtoon")]


def test_zip_unit_count_includes_pdf_pages_and_supported_images(tmp_path, monkeypatch):
    from backend.app.services import webtoon_cut_worker

    zip_path = tmp_path / "sources.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("book/volume.pdf", b"%PDF")
        archive.writestr("book/cover.jpg", b"jpg")
        archive.writestr("book/notes.txt", b"text")

    monkeypatch.setattr(webtoon_cut_worker, "page_count", lambda path: 12 if path.suffix == ".pdf" else 0)

    assert webtoon_cut_worker._count_units(zip_path, "zip") == 13


def test_pending_job_claim_statement_uses_skip_locked_for_multi_worker_ecs():
    from backend.app.services.webtoon_cut_worker import _pending_job_claim_statement

    compiled = str(_pending_job_claim_statement().compile(dialect=mysql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in compiled
