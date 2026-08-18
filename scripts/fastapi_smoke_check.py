#!/usr/bin/env python3
"""Smoke check for the new FastAPI backend skeleton."""

from __future__ import annotations

import sys
import os
import base64
import re
import tempfile
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import mysql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def redirect_app_paths(tmp_root: Path):
    data_dir = tmp_root / "data"
    metadata_dir = tmp_root / "metadata"
    uploads_dir = data_dir / "uploads"
    outputs_dir = data_dir / "outputs"
    reports_dir = data_dir / "reports"
    for path in (data_dir, metadata_dir, uploads_dir, outputs_dir, reports_dir):
        path.mkdir(parents=True, exist_ok=True)

    (data_dir / "history.json").write_text("[]", encoding="utf-8")
    (data_dir / "assets.json").write_text("{}", encoding="utf-8")
    (data_dir / "configs.json").write_text("[]", encoding="utf-8")

    os.environ["STUDIO_DATA_DIR"] = str(data_dir)
    os.environ["METADATA_DIR"] = str(metadata_dir)
    os.environ["WORKFLOWS_DIR"] = str(PROJECT_ROOT / "workflows")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_root / 'fastapi-smoke.db'}"
    os.environ["PERSISTENCE_BACKEND"] = "db"
    os.environ["RUNPOD_DRY_RUN"] = "1"


def login_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"id": "dobedub", "password": "password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def main():
    with tempfile.TemporaryDirectory(prefix="dobedub-fastapi-smoke-") as tmp:
        redirect_app_paths(Path(tmp))
        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
        from backend.app.main import create_app

        client = TestClient(create_app())
        response = client.get("/api/v1/health")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["backend"] == "fastapi"
        assert payload["app"] == "dobedub-studio"
        assert payload["ok"] is True
        assert "system" in payload
        assert "legacy" in payload
        assert "runpod" in payload["system"]
        assert "promptLlm" in payload["system"]

        admin_headers = login_headers(client)

        response = client.get("/api/v1/workflows", headers=admin_headers)
        assert response.status_code == 200, response.text
        workflows = response.json()
        assert any(item.get("id") == "1-images.json" for item in workflows)

        response = client.get("/api/v1/workflows/1-images.json/schema", headers=admin_headers)
        assert response.status_code == 200, response.text
        schema = response.json()
        assert schema["workflowId"] == "1-images.json"
        assert schema["keyframeCount"] == 1
        schema_control_keys = {control.get("key") for control in schema["segments"][0].get("configControls", [])}
        assert {"width", "height"}.issubset(schema_control_keys)

        response = client.get("/api/v1/workflows/1-images.json/segment-defaults", headers=admin_headers)
        assert response.status_code == 200, response.text
        defaults = response.json()
        assert len(defaults["segments"]) == 1
        assert "seed" not in defaults["segments"][0].get("config", {})

        response = client.get("/api/v1/workflows/1-images.json/widget-metadata", headers=admin_headers)
        assert response.status_code == 200, response.text
        widget_metadata = response.json()
        assert widget_metadata["workflowId"] == "1-images.json"
        assert widget_metadata["nodeCount"] > 0

        response = client.get("/api/v1/metadata/status", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True

        response = client.get("/api/health")
        assert response.status_code == 200, response.text
        assert response.json()["backend"] == "fastapi"
        assert "system" in response.json()

        response = client.post("/api/auth/login", json={"id": "dobedub", "password": "password"})
        assert response.status_code == 200, response.text
        assert response.json()["user"]["name"] == "장균은"
        assert response.json()["accessToken"]

        response = client.get("/manual", headers=admin_headers)
        assert response.status_code == 200, response.text
        manual_html = response.text
        manual_links = re.findall(r'<a href="(#[^"]+)">', manual_html)
        assert manual_links
        for href in manual_links:
            assert f'id="{href[1:]}"' in manual_html, href
        manual_images = re.findall(r'<img src="/docs/manual-assets/([^"]+)"', manual_html)
        assert manual_images
        for image_name in manual_images:
            assert (PROJECT_ROOT / "docs" / "manual-assets" / image_name).is_file(), image_name
        expected_manual_images = {
            "v4-00-login.jpg",
            "v4-01-workspace.jpg",
            "v4-02-segment-config-empty.png",
            "v4-02-segment-config-complete.png",
            "v4-03-task-history.jpg",
            "v4-04-prompt-reuse.jpg",
            "v4-05-assets.jpg",
            "v4-06-admin-roles.jpg",
            "v4-07-admin-users.jpg",
            "v4-08-admin-user-detail.jpg",
            "v4-10-admin-catalog-tree-expanded.jpg",
            "v4-11-admin-negative-defaults.jpg",
            "v4-12-admin-workflows.jpg",
            "v4-13-admin-sandbox-pod-current.png",
            "v4-14-admin-system-status.jpg",
            "v4-15-admin-metadata.jpg",
            "v4-16-admin-audit-log.jpg",
            "v4-17-admin-resource-map.jpg",
        }
        assert expected_manual_images.issubset(set(manual_images))

        data_url = "data:image/png;base64," + base64.b64encode(b"fake-image").decode("ascii")
        response = client.post("/api/uploads", headers=admin_headers, json={"fileName": "example.png", "dataUrl": data_url})
        assert response.status_code == 201, response.text
        upload = response.json()
        assert upload["assetId"]

        response = client.get(f"/api/files/{upload['assetId']}", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.content == b"fake-image"

        # Assets are intentionally protected: browser image/video tags cannot attach
        # JWT headers, so the frontend must load task assets through apiClient.assetBlob.
        response = client.get(f"/api/files/{upload['assetId']}")
        assert response.status_code == 401, response.text

        response = client.get(f"/api/files/{upload['assetId']}", headers={**admin_headers, "Range": "bytes=0-3"})
        assert response.status_code == 206, response.text
        assert response.content == b"fake"

        segment = schema["segments"][0]
        job_payload = {
            "workflowId": "1-images.json",
            "keyframes": [{"index": 1, "uploadId": upload["assetId"], "fileName": upload["fileName"]}],
            "segments": [{
                "index": 1,
                "nodeId": segment.get("nodeId", ""),
                "subgraphName": segment.get("subgraphName", ""),
                "displayName": segment.get("displayName", ""),
                "positivePrompt": "fastapi smoke prompt",
                "negativePromptAddition": "fastapi smoke negative",
                "config": {
                    **segment.get("config", {}),
                    "width": 736,
                    "height": 704,
                    "durationSeconds": 3,
                },
            }],
            "user": {"id": "dobedub", "name": "장균은"},
        }
        missing_image_payload = {**job_payload, "keyframes": [{"index": 1, "uploadId": None, "fileName": "example.png"}]}
        response = client.post("/api/jobs", headers=admin_headers, json=missing_image_payload)
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "입력파일을 업로드하세요. 이 워크플로우는 i2v 전용입니다. t2i, t2v는 지원하지 않습니다."

        invalid_resolution_payload = {
            **job_payload,
            "segments": [{
                **job_payload["segments"][0],
                "config": {**job_payload["segments"][0]["config"], "width": 730},
            }],
        }
        response = client.post("/api/jobs", headers=admin_headers, json=invalid_resolution_payload)
        assert response.status_code == 400, response.text
        assert "multiple of 16" in response.json()["detail"]

        response = client.post("/api/jobs", headers=admin_headers, json=job_payload)
        assert response.status_code == 201, response.text
        created_job = response.json()
        task_id = created_job["taskId"]
        assert isinstance(created_job.get("generationSeed"), int)
        assert created_job["generationSeed"] > 0
        response = client.get("/api/history?page=1&pageSize=10", headers=admin_headers)
        assert response.status_code == 200, response.text
        initial_history = response.json()["items"]
        assert any(item.get("taskId") == task_id and item.get("status") in {"queued", "QUEUED"} for item in initial_history), initial_history
        last_status = {}
        for _ in range(80):
            response = client.get(f"/api/jobs/{task_id}", headers=admin_headers)
            assert response.status_code == 200, response.text
            last_status = response.json()
            if last_status["status"] == "success":
                break
            time.sleep(0.1)
        assert last_status["status"] == "success", last_status
        assert last_status.get("generationSeed") == created_job["generationSeed"]

        # 작업 결과 평가 API: 등급은 필수이고, 사유 또는 코멘트 중 하나가 반드시
        # 있어야 한다. 정상 저장 시에는 서버가 로그인 사용자를 평가자로 기록한다.
        response = client.patch(
            f"/api/jobs/{task_id}/prompts/1/review",
            headers=admin_headers,
            json={"qualityRating": 5, "reuseEligible": True},
        )
        assert response.status_code == 400, response.text
        assert "평가 사유" in response.json()["detail"]

        response = client.patch(
            f"/api/jobs/{task_id}/prompts/1/review",
            headers=admin_headers,
            json={
                "qualityRating": 5,
                "qualityComment": "smoke review",
                "reuseEligible": True,
                "reviewFlags": {"naturalMotion": True},
            },
        )
        assert response.status_code == 200, response.text
        reviewed_prompt = response.json()
        assert reviewed_prompt["qualityRating"] == 5
        assert reviewed_prompt["reviewStatus"] == "reviewed"
        assert reviewed_prompt["reviewFlags"]["naturalMotion"] is True
        assert reviewed_prompt["reviewedBy"] == "장균은"
        assert reviewed_prompt["modelReferenceSource"] == "submission_snapshot"
        assert reviewed_prompt["modelReferences"]
        assert {item["bucket"] for item in reviewed_prompt["modelReferences"]}.issubset(
            {"checkpoints", "vae", "loras", "text_encoders", "unet", "video_models", "models"}
        )

        # 과거 task_prompts에는 제출 시점의 모델 스냅샷이 없다. 그 경우에도
        # task_id의 workflowId로 현재 메타데이터를 조회해 모델 정보를 보완한다.
        from backend.app.db.models import TaskPrompt
        from backend.app.db.session import SessionLocal

        session = SessionLocal()
        try:
            legacy_prompt = session.scalar(
                select(TaskPrompt).where(
                    TaskPrompt.task_id == task_id,
                    TaskPrompt.segment_index == 1,
                )
            )
            assert legacy_prompt is not None
            legacy_prompt.metadata_json = {
                "modelReferences": [{
                    "bucket": "vae",
                    "nodeId": "legacy",
                    "nodeTitle": "Legacy VAE",
                    "classType": "VAELoader",
                    "field": "vae_name",
                    "value": "legacy-vae.safetensors",
                }]
            }
            session.commit()
        finally:
            session.close()
        response = client.get(f"/api/jobs/{task_id}/prompts", headers=admin_headers)
        assert response.status_code == 200, response.text
        legacy_prompt_item = response.json()["items"][0]
        assert legacy_prompt_item["modelReferenceSource"] == "metadata_json_plus_current_workflow"
        assert any(item["value"] == "legacy-vae.safetensors" for item in legacy_prompt_item["modelReferences"])

        response = client.get("/api/history?page=1&pageSize=10", headers=admin_headers)
        assert response.status_code == 200, response.text
        history = response.json()
        assert history["total"] >= 1
        history_item = next(item for item in history["items"] if item.get("taskId") == task_id)
        assert history_item["inputAssets"] == [upload["assetId"]]
        assert history_item["inputImages"][0]["assetId"] == upload["assetId"]
        assert history_item.get("generationSeed") == created_job["generationSeed"]
        assert "seed" not in history_item.get("configJson", {})
        seed_patch = history_item.get("patchSummary", {}).get("seed", {})
        assert seed_patch.get("mode") == "automatic"
        assert seed_patch.get("value") == created_job["generationSeed"]
        assert seed_patch.get("targets")
        node_config_patch = history_item.get("patchSummary", {}).get("nodeConfig", [])
        assert any(item.get("param") == "width" and item.get("value") == 736 for item in node_config_patch)
        assert any(item.get("param") == "height" and item.get("value") == 704 for item in node_config_patch)
        assert any(item.get("param") == "duration_seconds" and item.get("value") == 3 for item in node_config_patch)
        from backend.app.services import workflow_parser
        workflow = workflow_parser.load_workflow("1-images.json", PROJECT_ROOT / "workflows")
        for target in seed_patch["targets"]:
            sampler = workflow.get(str(target.get("samplerNode")), {})
            assert sampler.get("class_type") == "KSamplerAdvanced"
            assert str((sampler.get("inputs") or {}).get("add_noise")).lower() == "enable"

        response = client.get("/api/prompts", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert "positive" in response.json()

        response = client.get("/api/prompts/reusable?reuseEligible=true", headers=admin_headers)
        assert response.status_code == 200, response.text
        reusable_items = response.json()["items"]
        assert any(item.get("taskId") == task_id for item in reusable_items)
        reused_task_prompt = next(item for item in reusable_items if item.get("taskId") == task_id)
        assert reused_task_prompt["modelReferences"]

        response = client.put(
            "/api/admin/task-execution-policy",
            headers=admin_headers,
            json={"maxActiveTasksPerUser": 1, "maxActiveTasksTotal": 1},
        )
        assert response.status_code == 200, response.text
        assert response.json()["maxActiveTasksPerUser"] == 1
        response = client.post("/api/jobs", headers=admin_headers, json=job_payload)
        assert response.status_code == 201, response.text
        limited_task_id = response.json()["taskId"]
        response = client.post("/api/jobs", headers=admin_headers, json=job_payload)
        assert response.status_code == 409, response.text
        assert "사용자 동시 활성 Task 한도(1개)에 도달했습니다" in response.json()["detail"]
        response = client.post(f"/api/jobs/{limited_task_id}/cancel", headers=admin_headers)
        assert response.status_code == 200, response.text
        response = client.put(
            "/api/admin/task-execution-policy",
            headers=admin_headers,
            json={"maxActiveTasksPerUser": 3, "maxActiveTasksTotal": 10},
        )
        assert response.status_code == 200, response.text

        from backend.app.db.models import TaskPrompt
        from backend.app.services.task_tracking_service import reusable_task_prompts

        reusable_task_prompts(reuse_eligible=True)
        mysql_reuse_query = select(TaskPrompt).order_by(
            TaskPrompt.quality_rating.is_(None).asc(),
            TaskPrompt.quality_rating.desc(),
            TaskPrompt.updated_at.desc(),
            TaskPrompt.id.desc(),
        )
        assert "NULLS LAST" not in str(mysql_reuse_query.compile(dialect=mysql.dialect())).upper()

        response = client.post("/api/configs", headers=admin_headers, json={"workflowId": "1-images.json", "snapshot": job_payload})
        assert response.status_code == 201, response.text
        response = client.get("/api/configs", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["items"]

        response = client.post("/api/reports", headers=admin_headers, json={"historyItem": history["items"][0]})
        assert response.status_code == 201, response.text
        report = response.json()
        response = client.get(report["downloadUrl"], headers=admin_headers)
        assert response.status_code == 200, response.text
        assert b"DOBEDUB STUDIO" in response.content

        response = client.post("/api/jobs", headers=admin_headers, json=job_payload)
        assert response.status_code == 201, response.text
        cancel_task_id = response.json()["taskId"]
        response = client.post(f"/api/jobs/{cancel_task_id}/cancel", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"

        response = client.post(f"/api/history/{task_id}/delete", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["deleted"] is True

        response = client.get("/manual", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert "dobedub studio" in response.text
        assert "v4-00-login.jpg" in response.text
        assert "v4-10-admin-catalog-tree-expanded.jpg" in response.text
        assert 'href="#1-서비스-개요"' in response.text
        assert "manualSearch" not in response.text
        assert "<script>" not in response.text
        assert "프롬프트 재사용" in response.text
        assert "Admin Console" in response.text

    print("OK fastapi smoke check passed")


if __name__ == "__main__":
    main()
