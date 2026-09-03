"""RunPod 결과 base64가 DB 조회 경로로 다시 새어 들어오지 않게 막는 회귀 테스트.

RunPod은 완료된 결과물을 응답 안에 base64로 실어 보낸다. output_service가 이미
그 바이트를 파일로 저장하므로 DB에 남는 복사본은 중복이고, 어떤 응답에도 실리지
않으면서 모든 task 조회가 행당 최대 1.6MB를 메모리로 끌어오게 만들었다. 영상을
표시하지도 않는 프롬프트 이력 화면이 느려지고 ECS가 메모리 부족을 낸 원인이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import event, select

from backend.app.db.models import Asset, WorkflowTask
from backend.app.repositories.db_adapter import DbStudioRepository
from backend.app.services.task_tracking_service import (
    MAX_HISTORY_PAGE_SIZE,
    PROVIDER_PAYLOAD_MAX_STRING,
    prune_provider_payload,
    task_history_items,
)


BASE64_BODY = "A" * 1_598_498


def _runpod_status(body: str = BASE64_BODY) -> dict:
    return {
        "delayTime": 352853,
        "executionTime": 75438,
        "id": "runpod-job-1",
        "status": "COMPLETED",
        "workerId": "worker-1",
        "output": {"images": [{"data": body, "filename": "result.mp4", "type": "base64"}]},
    }


def test_prune_keeps_response_envelope_and_drops_the_media_body():
    pruned = prune_provider_payload(_runpod_status())

    # 이력 응답이 실제로 읽는 네 값은 그대로 남아야 한다.
    assert pruned["status"] == "COMPLETED"
    assert pruned["id"] == "runpod-job-1"
    assert pruned["delayTime"] == 352853
    assert pruned["executionTime"] == 75438

    image = pruned["output"]["images"][0]
    assert image["filename"] == "result.mp4"
    assert image["data"] == ""
    # 얼마나 큰 본문을 버렸는지는 운영자가 확인할 수 있어야 한다.
    assert image["dataBytes"] == len(BASE64_BODY)
    assert image["dataStripped"] is True


def test_prune_leaves_normal_sized_values_untouched():
    # 가장 긴 실제 프롬프트도 임계값에 한참 못 미친다.
    payload = {
        "status": "IN_QUEUE",
        "positivePrompt": "x" * 701,
        "segments": [{"index": 1, "text": "짧은 프롬프트"}],
        "count": 3,
        "flag": True,
        "missing": None,
    }
    assert prune_provider_payload(payload) == payload


def test_prune_strips_any_oversized_string_not_only_the_known_key():
    # provider 응답 스키마가 바뀌어 다른 이름으로 본문이 들어와도 막아야 한다.
    pruned = prune_provider_payload({"output": {"video_b64": "B" * (PROVIDER_PAYLOAD_MAX_STRING + 1)}})
    assert pruned["output"]["video_b64"] == ""
    assert pruned["output"]["video_b64Stripped"] is True


def test_persisted_task_never_stores_the_provider_media_body(db_session, tmp_path):
    output_path = tmp_path / "result.mp4"
    output_path.write_bytes(b"video-bytes")
    db_session.add(Asset(
        id="asset_pruning_output",
        asset_type="output_video",
        file_name="result.mp4",
        mime_type="video/mp4",
        size_bytes=output_path.stat().st_size,
        storage_backend="local",
        storage_key=str(output_path),
        metadata_json={},
    ))
    db_session.commit()

    repository = DbStudioRepository(db_session, uploads_dir=tmp_path, outputs_dir=tmp_path)
    repository.append_history({
        "taskId": "task_pruning",
        "timestamp": "2026-09-03 12:00:00",
        "workflowId": "1-images.json",
        "executionMode": "runpod",
        "user": {"id": "worker_pruning", "name": "Pruning Worker"},
        "status": "Completed",
        "positivePrompts": [{"index": 1, "text": "positive"}],
        "negativePrompts": [{"index": 1, "text": "negative"}],
        "configJson": {"fps": 16},
        "outputAssets": [{
            "assetId": "asset_pruning_output",
            "fileName": "result.mp4",
            "mimeType": "video/mp4",
            "outputRole": "final",
            "segmentIndex": 1,
        }],
        "runpodStatus": _runpod_status(),
    })

    stored = db_session.get(WorkflowTask, "task_pruning")
    assert stored is not None
    assert BASE64_BODY not in json.dumps(stored.runpod_status_json)
    assert stored.runpod_status_json["output"]["images"][0]["dataBytes"] == len(BASE64_BODY)
    # 봉투는 남아 이력의 provider 요약을 계속 만들 수 있어야 한다.
    assert stored.runpod_status_json["status"] == "COMPLETED"
    assert stored.runpod_status_json["executionTime"] == 75438


def test_history_query_is_always_bounded(db_session):
    # 인자 없이 호출해도 전체 테이블을 읽어서는 안 된다. prompt_options()가 그
    # 경로로 workflow_tasks 전 행을 메모리에 올린 것이 ECS OOM의 직접 원인이었다.
    statements: list[str] = []
    bind = db_session.get_bind()

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(" ".join(statement.split()))

    event.listen(bind, "before_cursor_execute", record)
    try:
        task_history_items()
    finally:
        event.remove(bind, "before_cursor_execute", record)

    task_id_queries = [s for s in statements if "FROM workflow_tasks" in s and "SELECT workflow_tasks.id" in s]
    assert task_id_queries, statements
    assert any("LIMIT" in s for s in task_id_queries), task_id_queries
    assert MAX_HISTORY_PAGE_SIZE == 200


def test_history_query_does_not_read_the_whole_assets_table(db_session, tmp_path):
    upload_path = tmp_path / "input.png"
    upload_path.write_bytes(b"png")
    db_session.add_all([
        Asset(
            id=f"asset_unrelated_{index}",
            asset_type="input_image",
            file_name="input.png",
            mime_type="image/png",
            size_bytes=3,
            storage_backend="local",
            storage_key=str(upload_path),
            metadata_json={},
        )
        for index in range(3)
    ])
    db_session.add(WorkflowTask(
        id="task_no_assets",
        workflow_id="1-images.json",
        execution_mode="runpod",
        status="Completed",
        progress=100,
        worker_name="-",
        payload_json={},
        config_json={},
        wan_node_config={},
        patch_summary={},
        positive_prompts=[],
        negative_prompts=[],
        runpod_submit_json={},
        runpod_status_json={},
    ))
    db_session.commit()

    statements: list[str] = []
    bind = db_session.get_bind()

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(" ".join(statement.split()))

    event.listen(bind, "before_cursor_execute", record)
    try:
        task_history_items(1, 20)
    finally:
        event.remove(bind, "before_cursor_execute", record)

    # 참조하는 자산이 없으면 assets 조회 자체가 없어야 한다. 전체를 읽던 이전
    # 구현은 자산이 쌓일수록 모든 이력 조회를 함께 느리게 만들었다.
    unfiltered = [s for s in statements if "FROM assets" in s and "WHERE" not in s]
    assert not unfiltered, unfiltered
