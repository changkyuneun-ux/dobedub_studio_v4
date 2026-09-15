from __future__ import annotations

from backend.app.db.models import WebtoonCutJob, WebtoonCutOutput


def test_webtoon_cut_models_are_registered_in_metadata(db_session):
    from backend.app.db.base import Base

    table_names = set(Base.metadata.tables)

    assert "webtoon_cut_jobs" in table_names
    assert "webtoon_cut_sources" in table_names
    assert "webtoon_cut_units" in table_names
    assert "webtoon_cut_outputs" in table_names
    assert "webtoon_cut_downloads" in table_names

    job = WebtoonCutJob(
        id="wcut_test",
        status="pending",
        input_kind="pdf",
        source_asset_id="asset_source",
        display_name="과학사.pdf",
        safe_stem="science",
        created_by="user_1",
    )
    output = WebtoonCutOutput(
        id="wcut_out_1",
        job_id="wcut_test",
        asset_id="asset_cut",
        display_path="과학사/017-01.png",
        page_number=17,
        cut_index=1,
        width=966,
        height=720,
        flags_json=[],
        created_by="user_1",
    )
    db_session.add(job)
    db_session.add(output)
    db_session.commit()

    saved = db_session.get(WebtoonCutOutput, "wcut_out_1")
    assert saved is not None
    assert saved.job_id == "wcut_test"
    assert saved.display_path == "과학사/017-01.png"
