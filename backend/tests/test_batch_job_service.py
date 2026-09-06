"""Batch job orchestration: creation, promotion, counters and queries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import unicodedata
import uuid
import zipfile

import pytest
from sqlalchemy import inspect, select

from backend.app.core.security import create_access_token
from backend.app.db.models import (
    Asset,
    BatchJob,
    ImagePromptDraft,
    PromptGenerationBatch,
    RunpodRequestBatch,
    RunpodRequestItem,
    User,
    WorkflowTask,
)
from backend.app.db.session import SessionLocal
from backend.app.services import batch_job_service, job_service, prompt_batch_service, studio_api_service
from backend.app.services.task_tracking_service import record_job_status

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
        "source_zip_file_name",
        "requested_frames",
        "duration_seconds",
        "total_images",
        "prompt_completed_count",
        "prompt_failed_count",
        "video_requested_count",
        "video_completed_count",
        "video_failed_count",
        "prompt_waiting_count",
        "prompt_generating_count",
        "runpod_pending_submit_count",
        "runpod_queued_count",
        "runpod_in_progress_count",
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


def test_batch_aggregation_indexes_exist(db_session):
    inspector = inspect(db_session.get_bind())
    draft_indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("image_prompt_drafts")}
    task_indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("workflow_tasks")}
    assert draft_indexes.get("ix_image_prompt_drafts_batch_status") == ["batch_job_id", "status"]
    assert draft_indexes.get("ix_image_prompt_drafts_promotion") == ["status", "promotion_claimed_at", "batch_job_id"]
    assert task_indexes.get("ix_workflow_tasks_batch_deleted_status") == ["batch_job_id", "deleted_at", "status"]


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


def _seed_unique_assets(db_session, prefix: str, count: int) -> list[str]:
    ids = [f"{prefix}_{index}" for index in range(1, count + 1)]
    db_session.add_all([_asset(asset_id) for asset_id in ids])
    db_session.commit()
    return ids


def _asset_items_from_ids(asset_ids: list[str]) -> list[dict]:
    return [{"assetId": asset_id, "fileName": f"{asset_id}.jpg"} for asset_id in asset_ids]


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


def test_create_batch_job_id_uses_worker_kst_date_and_daily_sequence(db_session, monkeypatch):
    user = User(id="operator_1", name="장균은", role="OPERATOR")
    db_session.add(user)
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(
        batch_job_service,
        "utc_now",
        lambda: datetime(2026, 9, 3, 15, 5, 0, tzinfo=timezone.utc),
        raising=False,
    )

    first = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "shoot-0904", "requestedFrames": 81, "items": [_asset_items(2)[0]]},
        created_by=user.id,
    )
    second = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "shoot-0904", "requestedFrames": 81, "items": [_asset_items(2)[1]]},
        created_by=user.id,
    )

    assert first["id"] == "장균은_260904_1"
    assert second["id"] == "장균은_260904_2"


def test_create_zip_batch_job_id_uses_worker_zip_name_and_kst_date(db_session, monkeypatch):
    user = User(id="operator_1", name="장균은", role="OPERATOR")
    db_session.add(user)
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(
        batch_job_service,
        "utc_now",
        lambda: datetime(2026, 9, 3, 15, 5, 0, tzinfo=timezone.utc),
        raising=False,
    )

    result = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "픽미툰_씬",
            "sourceZipFileName": "픽미툰_씬.zip",
            "requestedFrames": 81,
            "items": [_asset_items(2)[0]],
        },
        created_by=user.id,
    )

    assert result["id"] == "장균은_픽미툰_씬_260904"
    assert result["sourceZipFileName"] == "픽미툰_씬.zip"


def test_create_zip_batch_job_preserves_source_relative_paths_on_drafts(db_session, monkeypatch):
    user = User(id="operator_1", name="장균은", role="OPERATOR")
    db_session.add(user)
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))

    result = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "홍길동",
            "sourceZipFileName": "홍길동.zip",
            "requestedFrames": 81,
            "items": [
                {"assetId": "asset_1", "fileName": "a.jpg", "relativePath": "홍길동/홍길동1/a.jpg"},
                {"assetId": "asset_2", "fileName": "b.jpg", "relativePath": "홍길동/홍길동2/b.jpg"},
            ],
        },
        created_by=user.id,
    )

    drafts = db_session.scalars(
        select(ImagePromptDraft)
        .where(ImagePromptDraft.batch_job_id == result["id"])
        .order_by(ImagePromptDraft.slot_index.asc())
    ).all()
    assert [draft.raw_json["sourceRelativePath"] for draft in drafts] == [
        "홍길동/홍길동1/a.jpg",
        "홍길동/홍길동2/b.jpg",
    ]
    assert {draft.raw_json["sourceZipFileName"] for draft in drafts} == {"홍길동.zip"}


def test_create_zip_batch_job_records_custom_negative_prompt_on_drafts(db_session, monkeypatch):
    user = User(id="operator_1", name="장균은", role="OPERATOR")
    db_session.add(user)
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))

    result = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "negative-source",
            "sourceZipFileName": "negative-source.zip",
            "requestedFrames": 81,
            "negativePrompt": "custom batch negative",
            "items": [
                {"assetId": "asset_1", "fileName": "a.jpg", "relativePath": "a.jpg"},
                {"assetId": "asset_2", "fileName": "b.jpg", "relativePath": "b.jpg"},
            ],
        },
        created_by=user.id,
    )

    drafts = db_session.scalars(
        select(ImagePromptDraft)
        .where(ImagePromptDraft.batch_job_id == result["id"])
        .order_by(ImagePromptDraft.slot_index.asc())
    ).all()
    assert [draft.negative_prompt for draft in drafts] == ["custom batch negative", "custom batch negative"]


def test_create_zip_batch_job_id_adds_suffix_for_same_worker_zip_and_day(db_session, monkeypatch):
    user = User(id="operator_1", name="장균은", role="OPERATOR")
    db_session.add(user)
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(
        batch_job_service,
        "utc_now",
        lambda: datetime(2026, 9, 3, 15, 5, 0, tzinfo=timezone.utc),
        raising=False,
    )

    first = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "shoot",
            "sourceZipFileName": "shoot.zip",
            "requestedFrames": 81,
            "items": [_asset_items(2)[0]],
        },
        created_by=user.id,
    )
    second = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "shoot",
            "sourceZipFileName": "shoot.zip",
            "requestedFrames": 81,
            "items": [_asset_items(2)[1]],
        },
        created_by=user.id,
    )

    assert first["id"] == "장균은_shoot_260904"
    assert second["id"] == "장균은_shoot_260904_2"
    assert len(second["id"]) <= 64


def test_create_zip_batch_job_id_truncates_long_zip_token_to_column_limit(db_session, monkeypatch):
    user = User(id="operator_1", name="장균은", role="OPERATOR")
    db_session.add(user)
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(
        batch_job_service,
        "utc_now",
        lambda: datetime(2026, 9, 3, 15, 5, 0, tzinfo=timezone.utc),
        raising=False,
    )

    result = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "long",
            "sourceZipFileName": f"{'verylongzipname' * 8}.zip",
            "requestedFrames": 81,
            "items": _asset_items(1),
        },
        created_by=user.id,
    )

    assert result["id"].startswith("장균은_")
    assert result["id"].endswith("_260904")
    assert len(result["id"]) <= 64


def test_create_batch_job_leaves_no_rows_when_the_link_step_fails(db_session, monkeypatch):
    db_session.add(_user())
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))

    def boom(*_args, **_kwargs):
        raise RuntimeError("link step failed")

    monkeypatch.setattr(batch_job_service, "_link_prompt_batch", boom)
    with pytest.raises(RuntimeError):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(2)},
            created_by="operator_1",
        )
    db_session.rollback()
    assert db_session.scalars(select(BatchJob)).all() == []
    assert db_session.scalars(select(PromptGenerationBatch)).all() == []
    assert db_session.scalars(select(ImagePromptDraft)).all() == []


def test_prompt_batch_creation_still_commits_for_existing_callers(db_session, monkeypatch):
    db_session.add(_user())
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    result = prompt_batch_service.create_prompt_generation_batch(
        db_session,
        {"workflowId": "Blowbang1.json", "items": [{"assetId": "asset_1", "slotIndex": 1, "requestedFrames": 81}]},
        created_by="operator_1",
    )
    db_session.rollback()
    assert db_session.get(PromptGenerationBatch, result["id"]) is not None


def _headers(user_id: str, *, name: str | None = None, role: str = "OPERATOR") -> dict[str, str]:
    token = create_access_token({"id": user_id, "name": name or user_id, "role": role})
    return {"Authorization": f"Bearer {token['accessToken']}"}


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_batch_zip_endpoint_imports_images_and_creates_batch_job(api_client, monkeypatch):
    session = SessionLocal()
    try:
        session.add(User(id="zip_operator", name="장균은", role="OPERATOR", permissions_json=["prompts:build", "jobs:run"], is_active=True))
        session.commit()
    finally:
        session.close()
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(
        batch_job_service,
        "utc_now",
        lambda: datetime(2026, 9, 3, 15, 5, 0, tzinfo=timezone.utc),
        raising=False,
    )

    response = api_client.post(
        "/api/batch-jobs/zip",
        headers=_headers("zip_operator", name="장균은"),
        data={"workflowId": "Blowbang1.json", "requestedFrames": "161"},
        files={"file": ("픽미툰_씬.zip", _zip_bytes({"root/0001.png": b"png", "root/nested/0002.jpg": b"jpg"}), "application/zip")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "장균은_픽미툰_씬_260904"
    assert payload["totalImages"] == 2
    assert payload["sourceDirName"] == "root"
    assert payload["requestedFrames"] == 161


def test_batch_job_search_finds_partial_worker_and_nfc_nfd_batch_ids(api_client):
    decomposed_id = unicodedata.normalize("NFD", "장균은_2권_08-10화_260906")
    session = SessionLocal()
    try:
        session.add(User(id="history-admin", name="History Admin", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True))
        session.add(User(id="zip_operator", name=unicodedata.normalize("NFD", "장균은"), role="OPERATOR", permissions_json=["prompts:build", "jobs:run"], is_active=True))
        session.add(BatchJob(
            id=decomposed_id,
            workflow_id="1-images.json",
            status="COMPLETE",
            source_dir_name=unicodedata.normalize("NFD", "2권 08-10화"),
            source_zip_file_name=unicodedata.normalize("NFD", "2권 08-10화.zip"),
            requested_frames=161,
            duration_seconds=10,
            total_images=170,
            video_completed_count=4,
            created_by="zip_operator",
        ))
        session.commit()
    finally:
        session.close()

    response = api_client.get(
        "/api/batch-jobs/search?query=장균은_2권&limit=10",
        headers=_headers("history-admin", name="History Admin", role="SUPER_ADMIN"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["id"] == decomposed_id
    assert payload["items"][0]["createdByName"] == unicodedata.normalize("NFD", "장균은")
    assert payload["items"][0]["sourceZipFileName"] == unicodedata.normalize("NFD", "2권 08-10화.zip")
    assert payload["items"][0]["totalImages"] == 170
    assert payload["items"][0]["videoCompletedCount"] == 4


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


def test_batch_job_history_uses_five_row_pages(db_session):
    user = _user()
    db_session.add(user)
    for index in range(7):
        db_session.add(BatchJob(
            id=f"batch_page_{index}",
            workflow_id="Blowbang1.json",
            status="COMPLETE",
            source_dir_name="d",
            source_zip_file_name=f"source_{index}.zip",
            requested_frames=161,
            duration_seconds=10,
            total_images=1,
            created_by=user.id,
            created_at=datetime(2026, 9, 6, 1, index, 0),
            updated_at=datetime(2026, 9, 6, 1, index, 0),
        ))
    db_session.commit()

    first = batch_job_service.list_batch_jobs(db_session, created_by=user.id, page=1)
    second = batch_job_service.list_batch_jobs(db_session, created_by=user.id, page=2)

    assert first["pageSize"] == 5
    assert len(first["items"]) == 5
    assert first["total"] == 7
    assert len(second["items"]) == 2


# --- promote_ready_batch_drafts -------------------------------------------
#
# 폴더 기반 Batch 작업은 Prompt 생성관리/RunPod 요청관리 큐를 거치지 않는다.
# 프롬프트가 READY가 되면 WorkflowTask를 직접 생성하고, 사용자는 Task History에서
# 상태를 확인한다. 테스트에서는 test_runpod_submission_queue.py와 같은 방식으로
# job_runtime만 가짜로 바꾸고 record_job_status는 실제로 호출한다.


def _stub_job_runtime() -> job_service.JobRuntime:
    return job_service.JobRuntime(
        jobs={},
        dry_run=False,
        prepare_workflow_for_job=lambda payload: (
            {"1": {"class_type": "KSampler", "inputs": {}}},
            [{"name": "input.png", "path": "/tmp/input.png"}],
            {"seed": {"mode": "automatic", "value": 1234}},
        ),
        build_runpod_payload=lambda workflow, images: {"input": {"workflow": workflow, "images": images}},
        runpod_request=lambda method, path, payload=None: {"id": "runpod_job_stub"},
        save_runpod_outputs=lambda _result, _job: {"assets": [], "remoteUrls": []},
        append_history=lambda _item: [],
        build_wan_node_config_snapshot=lambda _workflow_id, _segments: {},
        hydrate_input_images=lambda _item: [],
        record_job=lambda job: record_job_status(job, resolve_asset=None),
    )


def _batch_with_ready_drafts(db_session, monkeypatch, *, count: int, user_id: str = "operator_1") -> dict:
    db_session.add(_user(user_id))
    _seed_assets(db_session, count)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(studio_api_service, "job_runtime", _stub_job_runtime)
    created = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "d",
            "requestedFrames": 81,
            "items": _asset_items(count),
        },
        created_by=user_id,
    )
    return created


def _drafts_of(db_session, batch_job_id: str) -> list[ImagePromptDraft]:
    return list(db_session.scalars(
        select(ImagePromptDraft)
        .where(ImagePromptDraft.batch_job_id == batch_job_id)
        .order_by(ImagePromptDraft.slot_index.asc())
    ).all())


def test_promote_ready_drafts_creates_task_history_without_runpod_request_items(db_session, monkeypatch):
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=2)
    for draft in _drafts_of(db_session, created["id"]):
        draft.status = "READY"
        draft.positive_prompt = "a cinematic shot"
    db_session.commit()

    result = batch_job_service.promote_ready_batch_drafts()

    assert result["promoted"] == 2
    assert result["batches"] == [created["id"]]
    tasks = db_session.scalars(
        select(WorkflowTask)
        .where(WorkflowTask.batch_job_id == created["id"])
        .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
    ).all()
    assert len(tasks) == 2
    assert {task.config_json.get("frames") for task in tasks} == {81}
    assert {task.status for task in tasks} == {"PENDING_SUBMIT"}
    assert {task.request_batch_id for task in tasks} == {None}
    assert {task.request_item_id for task in tasks} == {None}
    assert db_session.scalars(select(RunpodRequestBatch)).all() == []
    assert db_session.scalars(select(RunpodRequestItem)).all() == []


def test_promote_later_ready_drafts_adds_task_history_rows_without_request_batches(db_session, monkeypatch):
    """One-by-one prompt completion still creates only task history rows."""
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=3)
    drafts = _drafts_of(db_session, created["id"])
    for draft in drafts:
        draft.status = "PENDING"
        draft.positive_prompt = None
    db_session.commit()

    for index, draft in enumerate(drafts, start=1):
        draft.status = "READY"
        draft.positive_prompt = f"batch prompt {index}"
        db_session.commit()

        result = batch_job_service.promote_ready_batch_drafts()

        assert result["promoted"] == 1
        tasks = db_session.scalars(
            select(WorkflowTask)
            .where(WorkflowTask.batch_job_id == created["id"])
            .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
        ).all()
        assert len(tasks) == index
        assert [task.prompt_draft_id for task in tasks] == [ready.id for ready in drafts[:index]]
        assert {task.request_batch_id for task in tasks} == {None}
        assert {task.request_item_id for task in tasks} == {None}
        assert db_session.scalars(select(RunpodRequestBatch)).all() == []
        assert db_session.scalars(select(RunpodRequestItem)).all() == []


def test_batch_promotion_does_not_append_the_same_draft_twice(db_session, monkeypatch):
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=1)
    draft = _drafts_of(db_session, created["id"])[0]
    draft.status = "READY"
    draft.positive_prompt = "single prompt"
    db_session.commit()

    first = batch_job_service.promote_ready_batch_drafts()
    second = batch_job_service.promote_ready_batch_drafts()

    assert first["promoted"] == 1
    assert second["promoted"] == 0
    tasks = db_session.scalars(select(WorkflowTask)).all()
    assert len(tasks) == 1
    assert tasks[0].prompt_draft_id == draft.id
    assert db_session.scalars(select(RunpodRequestBatch)).all() == []
    assert db_session.scalars(select(RunpodRequestItem)).all() == []


def test_promote_stamps_batch_job_id_on_created_tasks(db_session, monkeypatch):
    """G-5: 승격으로 만들어진 WorkflowTask도 batch_job_id를 갖는다."""
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=1)
    for draft in _drafts_of(db_session, created["id"]):
        draft.status = "READY"
        draft.positive_prompt = "a cinematic shot"
    db_session.commit()

    batch_job_service.promote_ready_batch_drafts()

    tasks = db_session.scalars(select(WorkflowTask)).all()
    assert len(tasks) == 1
    assert tasks[0].batch_job_id == created["id"]
    assert tasks[0].request_batch_id is None
    assert tasks[0].request_item_id is None


def test_promote_is_idempotent(db_session, monkeypatch):
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=2)
    for draft in _drafts_of(db_session, created["id"]):
        draft.status = "READY"
        draft.positive_prompt = "a cinematic shot"
    db_session.commit()

    first = batch_job_service.promote_ready_batch_drafts()
    second = batch_job_service.promote_ready_batch_drafts()

    assert first["promoted"] == 2
    assert second["promoted"] == 0
    assert second["batches"] == []
    tasks = db_session.scalars(select(WorkflowTask).where(WorkflowTask.batch_job_id == created["id"])).all()
    assert len(tasks) == 2
    assert db_session.scalars(select(RunpodRequestBatch)).all() == []
    assert db_session.scalars(select(RunpodRequestItem)).all() == []


def test_failed_drafts_are_never_promoted(db_session, monkeypatch):
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=3)
    drafts = _drafts_of(db_session, created["id"])
    drafts[0].status = "READY"
    drafts[0].positive_prompt = "ok"
    drafts[1].status = "FAILED"
    drafts[2].status = "MANUAL_REQUIRED"
    db_session.commit()

    result = batch_job_service.promote_ready_batch_drafts()

    assert result["promoted"] == 1
    tasks = db_session.scalars(select(WorkflowTask).where(WorkflowTask.batch_job_id == created["id"])).all()
    assert [task.prompt_draft_id for task in tasks] == [drafts[0].id]
    assert db_session.scalars(select(RunpodRequestBatch)).all() == []
    assert db_session.scalars(select(RunpodRequestItem)).all() == []


def test_promote_ignores_completed_batch_jobs(db_session, monkeypatch):
    """COMPLETE로 닫힌 배치의 뒤늦은 READY 초안은 다시 요청되지 않는다."""
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=1)
    for draft in _drafts_of(db_session, created["id"]):
        draft.status = "READY"
        draft.positive_prompt = "a cinematic shot"
    db_session.get(BatchJob, created["id"]).status = "COMPLETE"
    db_session.commit()

    assert batch_job_service.promote_ready_batch_drafts() == {"promoted": 0, "batches": []}


def test_existing_request_batch_path_records_no_batch_job_id(db_session):
    """G-5: 기존 RunPod 요청 관리 경로는 batch_job_id를 남기지 않는다."""
    from backend.app.services.runpod_request_batch_service import create_request_batch

    db_session.add_all([
        _user(),
        _asset("asset_1"),
        ImagePromptDraft(
            id="draft_plain_1",
            asset_id="asset_1",
            workflow_id="Blowbang1.json",
            slot_index=1,
            status="READY",
            provider="grok",
            model="grok-test",
            instruction_version="Blowbang1.json@1",
            positive_prompt="plain prompt",
            requested_frames=81,
            warnings_json=[],
            raw_json={},
            created_by="operator_1",
        ),
    ])
    db_session.commit()

    batch = create_request_batch(
        db_session,
        items=[{"promptDraftId": "draft_plain_1"}],
        created_by="operator_1",
    )
    row = db_session.get(RunpodRequestBatch, batch["id"])
    assert row.batch_job_id is None


def test_one_failing_batch_does_not_block_the_others(db_session, monkeypatch):
    """비활성 작업자의 배치 하나가 나머지 배치의 승격을 영구히 막으면 안 된다."""
    batch_job_service._PROMOTION_FAILURES.clear()
    _seed_assets(db_session, 2)
    db_session.add_all([
        User(id="inactive_op", name="Inactive", role="OPERATOR", is_active=False),
        _user("healthy_op"),
    ])
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("workflow instruction", "wf@1"))
    monkeypatch.setattr(studio_api_service, "job_runtime", _stub_job_runtime)
    broken = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81,
         "items": [{"assetId": "asset_1"}]},
        created_by="inactive_op",
    )
    healthy = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81,
         "items": [{"assetId": "asset_2"}]},
        created_by="healthy_op",
    )
    for batch_job_id in (broken["id"], healthy["id"]):
        for draft in _drafts_of(db_session, batch_job_id):
            draft.status = "READY"
            draft.positive_prompt = "a cinematic shot"
    db_session.commit()

    result = batch_job_service.promote_ready_batch_drafts()

    assert result == {"promoted": 1, "batches": [healthy["id"]]}
    assert broken["id"] in batch_job_service._PROMOTION_FAILURES


def test_claim_respects_the_per_cycle_limit(db_session, monkeypatch):
    db_session.add(_user())
    asset_ids = _seed_unique_assets(db_session, "claim_asset", 25)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items_from_ids(asset_ids)},
        created_by="operator_1",
    )
    for draft in _drafts_of(db_session, created["id"]):
        draft.status = "READY"
        draft.positive_prompt = "ok"
    db_session.commit()

    claimed, _ = batch_job_service.claim_batch_drafts_for_promotion(
        db_session, limit=batch_job_service.PROMOTION_LIMIT_PER_CYCLE
    )

    assert len(claimed) == batch_job_service.PROMOTION_LIMIT_PER_CYCLE == 20


def test_expired_claim_is_reclaimed_after_a_process_dies(db_session, monkeypatch):
    db_session.add(_user())
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(1)},
        created_by="operator_1",
    )
    draft = _drafts_of(db_session, created["id"])[0]
    draft.status = "READY"
    draft.positive_prompt = "ok"
    draft.promotion_claimed_at = datetime.utcnow() - timedelta(seconds=batch_job_service.STALE_PROMOTION_CLAIM_SECONDS + 60)
    db_session.commit()

    reclaimed, _ = batch_job_service.claim_batch_drafts_for_promotion(db_session, limit=10)

    assert [draft_id for _batch, _owner, draft_id in reclaimed] == [draft.id]


def test_refresh_batch_job_counters_completes_terminal_tasks(db_session, monkeypatch):
    db_session.add(_user())
    asset_ids = _seed_unique_assets(db_session, "counter_asset", 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items_from_ids(asset_ids)},
        created_by="operator_1",
    )
    drafts = _drafts_of(db_session, created["id"])
    for draft in drafts:
        draft.status = "READY"
        draft.positive_prompt = "ok"
    for index, state in enumerate(("COMPLETED", "FAILED"), start=1):
        db_session.add(WorkflowTask(
            id=f"task_{uuid.uuid4().hex[:16]}",
            workflow_id="Blowbang1.json",
            status=state,
            user_id="operator_1",
            batch_job_id=created["id"],
            prompt_draft_id=drafts[index - 1].id,
        ))
    db_session.commit()

    assert batch_job_service.refresh_batch_job_counters() == {"refreshed": 1, "completed": 1}
    db_session.expire_all()
    batch = db_session.get(BatchJob, created["id"])
    assert batch.status == "COMPLETE"
    assert batch.video_completed_count == 1
    assert batch.video_failed_count == 1


def test_refresh_batch_job_counters_does_not_close_unpromoted_ready_drafts(db_session, monkeypatch):
    db_session.add(_user())
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(1)},
        created_by="operator_1",
    )
    draft = _drafts_of(db_session, created["id"])[0]
    draft.status = "READY"
    draft.positive_prompt = "ok"
    db_session.commit()

    batch_job_service.refresh_batch_job_counters()

    db_session.expire_all()
    assert db_session.get(BatchJob, created["id"]).status == "INCOMPLETE"


def test_batch_job_detail_separates_prompt_and_runpod_failures(db_session, monkeypatch):
    db_session.add(_user())
    asset_ids = _seed_unique_assets(db_session, "detail_asset", 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceZipFileName": "source.zip", "requestedFrames": 161, "items": _asset_items_from_ids(asset_ids)},
        created_by="operator_1",
    )
    drafts = _drafts_of(db_session, created["id"])
    drafts[0].status = "FAILED"
    drafts[0].failure_message = "Grok 503"
    drafts[1].status = "READY"
    drafts[1].positive_prompt = "ok"
    db_session.add(WorkflowTask(
        id="task_failed_detail",
        workflow_id="Blowbang1.json",
        status="FAILED",
        user_id="operator_1",
        batch_job_id=created["id"],
        prompt_draft_id=drafts[1].id,
        last_dispatch_error="RunPod 404",
    ))
    db_session.commit()

    detail = batch_job_service.batch_job_detail(db_session, created["id"])

    assert detail["batch"]["id"] == created["id"]
    assert detail["warnings"] == []
    assert [
        (item["promptStatus"], item["runpodStatus"], item["retryKind"], item["retryable"])
        for item in detail["items"]
    ] == [
        ("FAILED", "미요청", "prompt", True),
        ("READY", "FAILED", "runpod", True),
    ]
    assert detail["items"][0]["error"] == "Grok 503"
    assert detail["items"][1]["error"] == "RunPod 404"


def test_batch_job_detail_normalizes_legacy_mojibake_source_paths(db_session, monkeypatch):
    db_session.add(_user())
    asset_ids = _seed_unique_assets(db_session, "mojibake_asset", 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    broken_root = unicodedata.normalize("NFD", "2권 08-10화-테스트").encode("utf-8").decode("cp437")
    broken_child = unicodedata.normalize("NFD", "2권 08화").encode("utf-8").decode("cp437")
    created = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceZipFileName": "2권 08-10화-테스트.zip",
            "requestedFrames": 161,
            "items": [{
                "assetId": asset_ids[0],
                "fileName": "0001.jpg",
                "relativePath": f"{broken_root}/{broken_child}/0001.jpg",
            }],
        },
        created_by="operator_1",
    )
    draft = _drafts_of(db_session, created["id"])[0]
    draft.status = "MANUAL_REQUIRED"
    db_session.commit()

    detail = batch_job_service.batch_job_detail(db_session, created["id"])

    assert detail["items"][0]["sourceRelativePath"] == "2권 08-10화-테스트/2권 08화/0001.jpg"
    assert "ß" not in detail["items"][0]["sourceRelativePath"]


def test_retry_failed_batch_items_reuses_existing_prompt_and_task_rows(db_session, monkeypatch):
    db_session.add(_user())
    asset_ids = _seed_unique_assets(db_session, "retry_asset", 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceZipFileName": "source.zip", "requestedFrames": 161, "items": _asset_items_from_ids(asset_ids)},
        created_by="operator_1",
    )
    drafts = _drafts_of(db_session, created["id"])
    drafts[0].status = "FAILED"
    drafts[0].positive_prompt = "bad"
    drafts[0].failure_message = "Grok timeout"
    drafts[1].status = "READY"
    drafts[1].positive_prompt = "ok"
    original_created_at = datetime(2026, 9, 6, 2, 0, 0)
    db_session.add(WorkflowTask(
        id="task_failed_retry",
        workflow_id="Blowbang1.json",
        status="FAILED",
        progress=100,
        user_id="operator_1",
        batch_job_id=created["id"],
        prompt_draft_id=drafts[1].id,
        runpod_job_id="runpod_failed",
        runpod_status_json={"error": "provider failed"},
        last_dispatch_error="provider failed",
        completed_at=datetime(2026, 9, 6, 2, 5, 0),
        created_at=original_created_at,
    ))
    db_session.commit()

    result = batch_job_service.retry_failed_batch_items(
        db_session,
        created["id"],
        actor_id="operator_1",
        can_manage=False,
        stage="all",
    )

    db_session.expire_all()
    retried_draft = db_session.get(ImagePromptDraft, drafts[0].id)
    reworked_task = db_session.get(WorkflowTask, "task_failed_retry")
    assert result["promptRetried"] == 1
    assert result["runpodReworked"] == 1
    assert result["skipped"] == []
    assert retried_draft.status == "PENDING"
    assert retried_draft.positive_prompt is None
    assert retried_draft.failure_message is None
    assert reworked_task.status == "PENDING_SUBMIT"
    assert reworked_task.runpod_job_id is None
    assert reworked_task.progress == 0
    assert reworked_task.created_at == original_created_at
    assert len(db_session.scalars(select(WorkflowTask).where(WorkflowTask.prompt_draft_id == drafts[1].id)).all()) == 1


def test_batch_job_detail_repairs_task_missing_batch_link_when_prompt_link_is_clear(db_session, monkeypatch):
    db_session.add(_user())
    asset_ids = _seed_unique_assets(db_session, "repair_asset", 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceZipFileName": "source.zip", "requestedFrames": 161, "items": _asset_items_from_ids(asset_ids)},
        created_by="operator_1",
    )
    draft = _drafts_of(db_session, created["id"])[0]
    draft.status = "READY"
    draft.positive_prompt = "ok"
    db_session.add(WorkflowTask(
        id="task_missing_batch_link",
        workflow_id="Blowbang1.json",
        status="FAILED",
        user_id="operator_1",
        prompt_draft_id=draft.id,
        payload_json={"promptDraftId": draft.id},
    ))
    db_session.commit()

    detail = batch_job_service.batch_job_detail(db_session, created["id"])

    repaired = db_session.get(WorkflowTask, "task_missing_batch_link")
    assert repaired.batch_job_id == created["id"]
    assert repaired.payload_json["batchJobId"] == created["id"]
    assert detail["warnings"][0]["type"] == "repaired_missing_batch_link"
    assert detail["items"][0]["taskId"] == "task_missing_batch_link"
    assert detail["items"][0]["retryKind"] == "runpod"
