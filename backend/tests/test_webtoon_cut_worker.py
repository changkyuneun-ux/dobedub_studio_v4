from __future__ import annotations

from pathlib import Path

import pytest

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
