"""Batch job orchestration: creation, promotion, counters and queries."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, select

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


# --- promote_ready_batch_drafts -------------------------------------------
#
# 승격은 studio_api_service.create_runpod_request_batch()를 그대로 재사용한다.
# 그 경로는 워크플로 JSON 패치와 RunPod 호출까지 이어지므로, 테스트에서는
# test_runpod_submission_queue.py와 같은 방식으로 job_runtime만 가짜로 바꾼다.
# record_job은 실제 record_job_status를 쓰기 때문에 WorkflowTask 행은 실제로
# 생성되고, G-5(배치 ID가 task까지 전달되는지)를 그대로 검증할 수 있다.


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


def test_promote_ready_drafts_creates_runpod_request_items(db_session, monkeypatch):
    created = _batch_with_ready_drafts(db_session, monkeypatch, count=2)
    for draft in _drafts_of(db_session, created["id"]):
        draft.status = "READY"
        draft.positive_prompt = "a cinematic shot"
    db_session.commit()

    result = batch_job_service.promote_ready_batch_drafts()

    assert result["promoted"] == 2
    assert result["batches"] == [created["id"]]
    request_batches = db_session.scalars(
        select(RunpodRequestBatch).where(RunpodRequestBatch.batch_job_id == created["id"])
    ).all()
    assert len(request_batches) == 1
    items = db_session.scalars(
        select(RunpodRequestItem).where(RunpodRequestItem.request_batch_id == request_batches[0].id)
    ).all()
    assert len(items) == 2
    assert {item.requested_frames for item in items} == {81}
    # G-5: batch_job_id는 행 생성 시점에 박혀 있어야 한다. 나중에 patch하면
    # 바로 뒤에 만들어지는 WorkflowTask가 NULL을 물려받는다.
    assert {item.status for item in items} == {"PENDING_SUBMIT"}


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
    assert tasks[0].request_item_id


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
    total_items = db_session.scalars(
        select(RunpodRequestItem)
        .join(RunpodRequestBatch, RunpodRequestItem.request_batch_id == RunpodRequestBatch.id)
        .where(RunpodRequestBatch.batch_job_id == created["id"])
    ).all()
    assert len(total_items) == 2


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
    items = db_session.scalars(
        select(RunpodRequestItem)
        .join(RunpodRequestBatch, RunpodRequestItem.request_batch_id == RunpodRequestBatch.id)
        .where(RunpodRequestBatch.batch_job_id == created["id"])
    ).all()
    assert [item.prompt_draft_id for item in items] == [drafts[0].id]


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
