"""Batch job orchestration: creation, promotion, counters and queries."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, select

from backend.app.db.models import Asset, BatchJob, ImagePromptDraft, PromptGenerationBatch, RunpodRequestBatch, User, WorkflowTask
from backend.app.services import batch_job_service, prompt_batch_service

# NOTE: this module deliberately relies on the shared `db_session` fixture
# (backend/tests/conftest.py) rather than instantiating SessionLocal()
# directly. Base.metadata.create_all()/drop_all() run only inside that
# fixture's setup/teardown, so a bare SessionLocal() call sees no tables at
# all when this file is collected on its own.


def test_batch_job_table_exists(db_session):
    inspector = inspect(db_session.get_bind())
    assert "batch_jobs" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("batch_jobs")}
    assert {
        "id",
        "workflow_id",
        "status",
        "source_dir_name",
        "requested_frames",
        "duration_seconds",
        "total_images",
        "prompt_completed_count",
        "prompt_failed_count",
        "video_requested_count",
        "video_completed_count",
        "video_failed_count",
        "last_downloaded_at",
        "created_by",
        "created_at",
        "updated_at",
    } <= columns


@pytest.mark.parametrize(
    "table, model",
    [
        ("prompt_generation_batches", PromptGenerationBatch),
        ("runpod_request_batches", RunpodRequestBatch),
        ("image_prompt_drafts", ImagePromptDraft),
        ("workflow_tasks", WorkflowTask),
    ],
)
def test_batch_job_id_column_added(db_session, table, model):
    inspector = inspect(db_session.get_bind())
    assert "batch_job_id" in {column["name"] for column in inspector.get_columns(table)}
    assert hasattr(model, "batch_job_id")


# --- create_batch_job / batch_job_payload ---------------------------------
#
# conftest.py only provides `db_session`, `api_client` and `fake_runpod` (no
# `operator_user`/`seeded_assets`/`other_user`). Users and assets needed here
# are created locally, following the `_asset()` helper pattern already used
# in test_prompt_batch_service.py.


def _asset(asset_id: str) -> Asset:
    return Asset(
        id=asset_id,
        asset_type="input",
        file_name=f"{asset_id}.png",
        mime_type="image/png",
        size_bytes=1,
        image_width=900,
        image_height=1200,
        storage_key=f"inputs/{asset_id}.png",
        metadata_json={},
    )


def _user(user_id: str = "operator_1") -> User:
    return User(id=user_id, name="Operator One", role="OPERATOR")


def _asset_items(count: int) -> list[dict]:
    return [{"assetId": f"asset_{index}", "fileName": f"image{index}.jpg"} for index in range(1, count + 1)]


def _seed_assets(db_session, count: int) -> None:
    db_session.add_all([_asset(f"asset_{index}") for index in range(1, count + 1)])
    db_session.commit()


def test_create_batch_job_persists_batch_prompt_batch_and_drafts(db_session, monkeypatch):
    user = _user()
    db_session.add(user)
    _seed_assets(db_session, 3)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))

    result = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "shoot-0904",
            "requestedFrames": 81,
            "items": _asset_items(3),
        },
        created_by=user.id,
    )

    assert result["totalImages"] == 3
    assert result["status"] == "INCOMPLETE"
    assert result["sourceDirName"] == "shoot-0904"
    assert result["requestedFrames"] == 81
    # 오늘 등록된 워크플로우 중 output_fps 컨트롤을 노출하는 것이 없으므로
    # fps 16 기본값이 적용된다. 81 프레임 = 5초.
    assert result["durationSeconds"] == 5

    batch = db_session.get(BatchJob, result["id"])
    assert batch is not None

    prompt_batches = db_session.scalars(
        select(PromptGenerationBatch).where(PromptGenerationBatch.batch_job_id == batch.id)
    ).all()
    assert len(prompt_batches) == 1
    assert prompt_batches[0].total_count == 3

    drafts = db_session.scalars(
        select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == batch.id)
    ).all()
    assert len(drafts) == 3
    assert {draft.status for draft in drafts} == {"PENDING"}
    # 사용자가 고른 Length가 모든 draft에 그대로 적용된다.
    assert {draft.requested_frames for draft in drafts} == {81}


@pytest.mark.parametrize("frames, expected_seconds", [(49, 3), (81, 5), (161, 10)])
def test_duration_seconds_matches_frame_choice(db_session, monkeypatch, frames, expected_seconds):
    user = _user()
    db_session.add(user)
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))

    result = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": frames, "items": _asset_items(1)},
        created_by=user.id,
    )
    assert result["requestedFrames"] == frames
    assert result["durationSeconds"] == expected_seconds


@pytest.mark.parametrize("frames", [0, 30, 100, 200, -1])
def test_create_batch_job_rejects_unsupported_frames(db_session, monkeypatch, frames):
    user = _user()
    db_session.add(user)
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))

    with pytest.raises(ValueError, match="영상 길이"):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": frames, "items": _asset_items(1)},
            created_by=user.id,
        )


def test_create_batch_job_rejects_empty_items(db_session):
    user = _user()
    db_session.add(user)
    db_session.commit()

    with pytest.raises(ValueError, match="이미지"):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": []},
            created_by=user.id,
        )


def test_create_batch_job_leaves_no_partial_rows_when_workflow_has_no_instruction(db_session):
    """G-7: 실패한 생성은 batch_jobs 행을 남기지 않아야 고아 자산을 지울 수 있다."""
    user = _user()
    db_session.add(user)
    _seed_assets(db_session, 2)

    before = db_session.scalars(select(BatchJob.id)).all()
    with pytest.raises(ValueError):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "workflow-without-instructions", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(2)},
            created_by=user.id,
        )
    db_session.rollback()
    after = db_session.scalars(select(BatchJob.id)).all()
    assert after == before


def test_resolve_duration_seconds_falls_back_to_16fps_when_no_output_fps_control():
    # 오늘 등록된 워크플로우 중 output_fps configControl을 노출하는 것이 없으므로
    # 항상 fallback(16fps)이 적용된다: 49->3, 81->5, 161->10.
    assert batch_job_service.resolve_duration_seconds("Blowbang1.json", 49) == 3
    assert batch_job_service.resolve_duration_seconds("Blowbang1.json", 81) == 5
    assert batch_job_service.resolve_duration_seconds("Blowbang1.json", 161) == 10


def test_resolve_duration_seconds_survives_missing_workflow():
    # 워크플로우 파일이 없어도 배치 생성 흐름을 막지 않도록 fallback으로 계산한다.
    assert batch_job_service.resolve_duration_seconds("does-not-exist.json", 81) == 5


def test_batch_job_payload_missing_batch_raises(db_session):
    with pytest.raises(ValueError):
        batch_job_service.batch_job_payload(db_session, "batch_missing")
