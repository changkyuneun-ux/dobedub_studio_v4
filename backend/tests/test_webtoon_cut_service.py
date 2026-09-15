from __future__ import annotations

from sqlalchemy import event

from backend.app.db.models import Asset, WebtoonCutJob, WebtoonCutOutput


def _asset(asset_id: str, *, file_name: str = "source.pdf", asset_type: str = "webtoon_source_original") -> Asset:
    return Asset(
        id=asset_id,
        asset_type=asset_type,
        file_name=file_name,
        mime_type="application/pdf",
        size_bytes=1024,
        storage_backend="s3",
        storage_key=f"webtoon-cut/tests/{asset_id}/{file_name}",
        metadata_json={"createdBy": "user_1"},
    )


def test_create_job_blocks_second_active_job_for_same_user(db_session):
    from backend.app.services.webtoon_cut_service import create_job

    db_session.add(_asset("asset_source"))
    db_session.commit()

    first = create_job(
        db_session,
        source_asset_id="asset_source",
        input_kind="pdf",
        created_by="user_1",
    )

    assert first["status"] == "pending"

    try:
        create_job(
            db_session,
            source_asset_id="asset_source",
            input_kind="pdf",
            created_by="user_1",
        )
    except ValueError as exc:
        assert "진행 중인 컷 분할 작업" in str(exc)
    else:
        raise AssertionError("expected active job guard")


def test_cancel_job_sets_cancelled_terminal_status(db_session):
    from backend.app.services.webtoon_cut_service import cancel_job, create_job

    db_session.add(_asset("asset_source"))
    db_session.commit()
    job = create_job(db_session, source_asset_id="asset_source", input_kind="pdf", created_by="user_1")

    cancelled = cancel_job(db_session, job["jobId"], created_by="user_1")

    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelRequestedAt"]


def test_filter_outputs_by_used_state(db_session):
    from backend.app.services.webtoon_cut_service import create_job, list_outputs, register_output

    db_session.add(_asset("asset_source"))
    db_session.add(_asset("asset_cut_1", file_name="001-01.png", asset_type="webtoon_cut_image"))
    db_session.add(_asset("asset_cut_2", file_name="001-02.png", asset_type="webtoon_cut_image"))
    db_session.commit()
    job = create_job(db_session, source_asset_id="asset_source", input_kind="pdf", created_by="user_1")
    register_output(
        db_session,
        job_id=job["jobId"],
        asset_id="asset_cut_1",
        display_path="source/001-01.png",
        page_number=1,
        cut_index=1,
        created_by="user_1",
    )
    register_output(
        db_session,
        job_id=job["jobId"],
        asset_id="asset_cut_2",
        display_path="source/001-02.png",
        page_number=1,
        cut_index=2,
        created_by="user_1",
        used_in_batch_count=1,
    )

    unused = list_outputs(db_session, job_id=job["jobId"], created_by="user_1", used_state="unused")
    batch_used = list_outputs(db_session, job_id=job["jobId"], created_by="user_1", used_state="batch")

    assert [item["assetId"] for item in unused["items"]] == ["asset_cut_1"]
    assert [item["assetId"] for item in batch_used["items"]] == ["asset_cut_2"]


def test_register_output_deduplicates_same_job_display_path(db_session):
    from backend.app.services.webtoon_cut_service import create_job, register_output

    db_session.add(_asset("asset_source"))
    db_session.add(_asset("asset_cut_1", file_name="001-01.png", asset_type="webtoon_cut_image"))
    db_session.add(_asset("asset_cut_2", file_name="001-01.png", asset_type="webtoon_cut_image"))
    db_session.commit()
    job = create_job(db_session, source_asset_id="asset_source", input_kind="pdf", created_by="user_1")

    first = register_output(
        db_session,
        job_id=job["jobId"],
        asset_id="asset_cut_1",
        display_path="source/001-01.png",
        page_number=1,
        cut_index=1,
        created_by="user_1",
    )
    duplicate = register_output(
        db_session,
        job_id=job["jobId"],
        asset_id="asset_cut_2",
        display_path="source/001-01.png",
        page_number=1,
        cut_index=1,
        created_by="user_1",
    )

    saved_job = db_session.get(WebtoonCutJob, job["jobId"])
    db_session.refresh(saved_job)
    assert duplicate["outputId"] == first["outputId"]
    assert duplicate["assetId"] == "asset_cut_1"
    assert saved_job.generated_cut_count == 1


def test_list_outputs_deduplicates_existing_duplicate_display_paths(db_session):
    from backend.app.services.webtoon_cut_service import create_job, list_outputs, register_output

    db_session.add(_asset("asset_source"))
    db_session.add(_asset("asset_cut_1", file_name="001-01.png", asset_type="webtoon_cut_image"))
    db_session.add(_asset("asset_cut_2", file_name="001-02.png", asset_type="webtoon_cut_image"))
    db_session.commit()
    job = create_job(db_session, source_asset_id="asset_source", input_kind="pdf", created_by="user_1")

    register_output(
        db_session,
        job_id=job["jobId"],
        asset_id="asset_cut_1",
        display_path="source/001-01.png",
        page_number=1,
        cut_index=1,
        created_by="user_1",
    )
    db_session.execute(
        WebtoonCutJob.__table__.update()
        .where(WebtoonCutJob.id == job["jobId"])
        .values(generated_cut_count=2)
    )
    db_session.add(
        WebtoonCutOutput(
            id="legacy_duplicate",
            job_id=job["jobId"],
            asset_id="asset_cut_2",
            status="ready",
            display_path="source/001-01.png",
            page_number=1,
            cut_index=1,
            flags_json=[],
            metadata_json={"createdBy": "user_1"},
            created_by="user_1",
        )
    )
    db_session.commit()

    outputs = list_outputs(db_session, job_id=job["jobId"], created_by="user_1")

    assert [item["displayPath"] for item in outputs["items"]] == ["source/001-01.png"]


def test_list_outputs_only_loads_requested_page_from_db(db_session):
    from backend.app.db.session import SessionLocal
    from backend.app.services.webtoon_cut_service import list_outputs

    db_session.add(_asset("asset_source"))
    db_session.add(
        WebtoonCutJob(
            id="wcut_many_outputs",
            status="completed",
            input_kind="pdf",
            source_asset_id="asset_source",
            display_name="source",
            safe_stem="source",
            created_by="user_1",
        )
    )
    for index in range(120):
        asset_id = f"asset_cut_{index:03d}"
        db_session.add(_asset(asset_id, file_name=f"{index:03d}-01.png", asset_type="webtoon_cut_image"))
        db_session.add(
            WebtoonCutOutput(
                id=f"wcut_out_{index:03d}",
                job_id="wcut_many_outputs",
                asset_id=asset_id,
                status="ready",
                display_path=f"source/{index:03d}-01.png",
                page_number=index + 1,
                cut_index=1,
                flags_json=[],
                metadata_json={"createdBy": "user_1"},
                created_by="user_1",
            )
        )
    db_session.commit()
    db_session.close()

    loaded_output_ids: list[str] = []

    def record_load(_session, instance):
        if isinstance(instance, WebtoonCutOutput):
            loaded_output_ids.append(instance.id)

    event.listen(SessionLocal, "loaded_as_persistent", record_load)
    try:
        with SessionLocal() as session:
            page = list_outputs(
                session,
                job_id="wcut_many_outputs",
                created_by="user_1",
                page=1,
                page_size=10,
            )
    finally:
        event.remove(SessionLocal, "loaded_as_persistent", record_load)

    assert len(page["items"]) == 10
    assert len(loaded_output_ids) <= 10


def test_get_job_finds_jobs_beyond_first_list_page(db_session):
    from backend.app.db.models import WebtoonCutJob
    from backend.app.services.webtoon_cut_service import get_job

    db_session.add(_asset("asset_source"))
    db_session.commit()
    for index in range(105):
        db_session.add(
            WebtoonCutJob(
                id=f"wcut_{index:03d}",
                status="completed",
                input_kind="pdf",
                source_asset_id="asset_source",
                display_name=f"source-{index:03d}",
                safe_stem=f"source-{index:03d}",
                created_by="user_1",
            )
        )
    db_session.commit()

    found = get_job(db_session, "wcut_104", created_by="user_1")

    assert found["jobId"] == "wcut_104"
    assert found["displayName"] == "source-104"


def test_handoff_marks_selected_outputs_as_used(db_session):
    from backend.app.services.webtoon_cut_service import (
        create_batch_input_from_outputs,
        create_grok_prompt_input_from_outputs,
        create_job,
        list_outputs,
        register_output,
    )

    db_session.add(_asset("asset_source"))
    db_session.add(_asset("asset_cut_1", file_name="001-01.png", asset_type="webtoon_cut_image"))
    db_session.add(_asset("asset_cut_2", file_name="001-02.png", asset_type="webtoon_cut_image"))
    db_session.commit()
    job = create_job(db_session, source_asset_id="asset_source", input_kind="pdf", created_by="user_1")
    first = register_output(
        db_session,
        job_id=job["jobId"],
        asset_id="asset_cut_1",
        display_path="source/001-01.png",
        page_number=1,
        cut_index=1,
        created_by="user_1",
    )
    second = register_output(
        db_session,
        job_id=job["jobId"],
        asset_id="asset_cut_2",
        display_path="source/001-02.png",
        page_number=1,
        cut_index=2,
        created_by="user_1",
    )

    grok = create_grok_prompt_input_from_outputs(db_session, job_id=job["jobId"], output_ids=[first["outputId"]], created_by="user_1")
    batch = create_batch_input_from_outputs(db_session, job_id=job["jobId"], output_ids=[second["outputId"]], created_by="user_1")
    prompt_used = list_outputs(db_session, job_id=job["jobId"], created_by="user_1", used_state="grok")
    batch_used = list_outputs(db_session, job_id=job["jobId"], created_by="user_1", used_state="batch")

    assert grok["inputAssetIds"] == ["asset_cut_1"]
    assert grok["items"][0]["sourceRelativePath"] == "source/001-01.png"
    assert batch["inputAssetIds"] == ["asset_cut_2"]
    assert [item["assetId"] for item in prompt_used["items"]] == ["asset_cut_1"]
    assert [item["assetId"] for item in batch_used["items"]] == ["asset_cut_2"]


def test_delete_job_soft_hides_terminal_jobs_from_history(db_session):
    from backend.app.services.webtoon_cut_service import create_job, delete_job, list_jobs

    db_session.add(_asset("asset_source"))
    db_session.commit()
    job = create_job(db_session, source_asset_id="asset_source", input_kind="zip", created_by="user_1")
    saved_job = db_session.get(WebtoonCutJob, job["jobId"])
    saved_job.status = "cancelled"
    db_session.commit()

    result = delete_job(db_session, job_id=job["jobId"], created_by="user_1")
    history = list_jobs(db_session, created_by="user_1")
    hidden_job = db_session.get(WebtoonCutJob, job["jobId"])

    assert result == {"deleted": True, "jobId": job["jobId"]}
    assert hidden_job.deleted_at is not None
    assert history["items"] == []


def test_delete_job_rejects_active_jobs(db_session):
    from backend.app.services.webtoon_cut_service import create_job, delete_job

    db_session.add(_asset("asset_source"))
    db_session.commit()
    job = create_job(db_session, source_asset_id="asset_source", input_kind="zip", created_by="user_1")

    try:
        delete_job(db_session, job_id=job["jobId"], created_by="user_1")
    except ValueError as exc:
        assert "진행 중인 컷 분할 작업은 삭제할 수 없습니다" in str(exc)
    else:
        raise AssertionError("active jobs must not be deleted")
