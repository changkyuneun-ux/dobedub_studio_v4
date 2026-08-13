#!/usr/bin/env python3
"""Verify Prompt DB migration, example catalog data, catalog API, and scene JSON builder."""

from __future__ import annotations

import os
import sys
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


PROMPT_TABLES = {
    "prompt_scopes",
    "prompt_category_groups",
    "prompt_subcategories",
    "prompt_subcategory_keywords",
    "prompt_categories",
    "prompt_category_terms",
    "prompt_terms",
    "prompt_term_relations",
    "prompt_term_renderings",
    "prompt_rules",
    "prompt_templates",
    "prompt_generation_requests",
    "prompt_generation_outputs",
    "prompt_feedback",
    "prompt_system_prompts",
    "model_profiles",
}


def all_subcategories(catalog: dict) -> list[dict]:
    """B-06 3단계: 구형 catalog["categories"] 배열이 API 응답에서 완전히 제거되어,
    이제 catalog["groups"][].subcategories[]를 평탄화해 동일한 역할(코드로 조회 가능한
    카테고리 목록)로 사용한다. ROOT 카테고리(POSITIVE_ROOT/NEGATIVE_ROOT)는 신형
    계층에 애초에 편입되지 않으므로 여기 포함되지 않는다."""
    return [
        subcategory
        for group in catalog["groups"]
        for subcategory in group["subcategories"]
    ]


def login_headers(client) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"id": "dobedub", "password": "password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dobedub-prompt-db-smoke-") as tmp:
        database_path = Path(tmp) / "prompt-smoke.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
        os.environ["PERSISTENCE_BACKEND"] = "db"

        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        command.upgrade(config, "head")

        engine = create_engine(os.environ["DATABASE_URL"], future=True)
        tables = set(inspect(engine).get_table_names())
        missing = PROMPT_TABLES - tables
        assert not missing, f"Missing prompt tables: {sorted(missing)}"
        engine.dispose()

        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.db.models import PromptSystemPrompt
        from backend.app.db.session import SessionLocal
        from backend.app.services.prompt_builder_service import apply_example_prompt_catalog
        from backend.app.services.prompt_system_prompt_service import (
            LEGACY_DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT,
        )

        raw_client = TestClient(app)
        admin_headers = login_headers(raw_client)

        class AuthedClient:
            def get(self, path: str, **kwargs):
                return raw_client.get(path, headers={**admin_headers, **kwargs.pop("headers", {})}, **kwargs)

            def post(self, path: str, **kwargs):
                return raw_client.post(path, headers={**admin_headers, **kwargs.pop("headers", {})}, **kwargs)

            def put(self, path: str, **kwargs):
                return raw_client.put(path, headers={**admin_headers, **kwargs.pop("headers", {})}, **kwargs)

        client = AuthedClient()
        with SessionLocal() as db:
            catalog = apply_example_prompt_catalog(db, force=True)
        assert catalog["groups"]
        positive_groups = [group for group in catalog["groups"] if group["scopeCode"] == "POSITIVE"]
        negative_groups = [group for group in catalog["groups"] if group["scopeCode"] == "NEGATIVE"]
        assert positive_groups and negative_groups
        work_style_group = next(group for group in positive_groups if group["code"] == "positive_work_style")
        genre_subcategory = next(subcategory for subcategory in work_style_group["subcategories"] if subcategory["code"] == "GENRE")
        assert genre_subcategory["terms"]
        subcategories = all_subcategories(catalog)
        assert len(subcategories) >= 28
        genre_category = next(category for category in subcategories if category["code"] == "GENRE")
        action_category = next(category for category in subcategories if category["code"] == "CHARACTER_ACTION")
        subject_category = next(category for category in subcategories if category["code"] == "SUBJECT_TYPE")
        category_codes = {category["code"] for category in subcategories}
        expected_extension_categories = {
            "OBJECT_ACTION",
            "MOTION_SPEED",
            "MOTION_INTENSITY",
            "CAMERA_ANGLE",
            "LENS_TYPE",
            "FOCUS_STYLE",
            "CLOTHING",
            "POSE",
            "GAZE_DIRECTION",
            "FACIAL_EXPRESSION",
            "EMOTION",
            "ANIMATION_STYLE",
            "RENDERING_STYLE",
            "SCENE_TRANSITION",
            "SHOT_DURATION",
            "NEGATIVE_QUALITY",
            "NEGATIVE_CAMERA",
            "NEGATIVE_TEXT",
            "NEGATIVE_IDENTITY",
            "NEGATIVE_EXCLUSION",
        }
        assert expected_extension_categories.issubset(category_codes)
        # B-06 3단계: ROOT 카테고리는 신형 계층에 편입되지 않는다(parentCategoryId 개념
        # 자체가 사라짐). 기존의 "ROOT 항목을 직접 수정/비활성화 시도 → 400" 테스트 대신,
        # upsert_prompt_category의 FIXED_PROMPT_ROOT_CODES 가드가 신형 계층에서도 ROOT
        # 코드로 생성/수정하는 것을 막는지를 검증한다.
        root_create_response = client.post("/api/prompts/categories", json={
            "code": "POSITIVE_ROOT",
            "groupId": work_style_group["id"],
            "groupCode": work_style_group["code"],
            "scopeType": "GLOBAL",
            "selectionMode": "multi",
            "required": False,
            "nameKo": "루트 생성 시도",
            "nameEn": "Root Create Attempt",
            "sortOrder": 999,
        })
        assert root_create_response.status_code == 400, root_create_response.text
        root_rename_response = client.put(f"/api/prompts/categories/{genre_category['id']}", json={
            **genre_category,
            "code": "NEGATIVE_ROOT",
        })
        assert root_rename_response.status_code == 400, root_rename_response.text
        assert genre_category["selectionMode"] == "multi"
        assert action_category["selectionMode"] == "multi"
        assert subject_category["selectionMode"] == "single"
        assert subject_category["required"] is True
        assert genre_category["scopeType"] == "GLOBAL"
        assert next(category for category in subcategories if category["code"] == "LENS_TYPE")["selectionMode"] == "single"
        assert next(category for category in subcategories if category["code"] == "CLOTHING")["scopeType"] == "ENTITY"
        assert next(category for category in subcategories if category["code"] == "NEGATIVE_TEXT")["scopeType"] == "OUTPUT"
        assert any(
            term["code"] == "negative_identity_drift"
            for category in subcategories
            for term in category["terms"]
        )
        assert any(
            term["code"] == "negative_new_objects"
            for category in subcategories
            for term in category["terms"]
        )
        term_ids = [
            term["id"]
            for category in subcategories
            for term in category["terms"]
            if term["code"] in {"genre_cinematic", "subject_person", "action_gentle_walk", "negative_distortion"}
        ]
        assert len(term_ids) == 4
        subject_term_ids = [
            term["id"]
            for category in subcategories
            for term in category["terms"]
            if term["code"] in {"subject_person", "subject_product"}
        ]
        assert len(subject_term_ids) == 2

        catalog_response = client.get("/api/prompts/catalog")
        assert catalog_response.status_code == 200
        assert catalog_response.json()["templates"]
        assert catalog_response.json()["relations"]
        assert catalog_response.json()["groups"]

        admin_group_response = client.post("/api/prompts/category-groups", json={
            "code": "positive_admin_group",
            "scopeType": "POSITIVE",
            "nameKo": "관리 카테고리",
            "nameEn": "Admin Category",
            "description": "created by smoke test",
            "sortOrder": 998,
        })
        assert admin_group_response.status_code == 200, admin_group_response.text
        admin_group = next(group for group in admin_group_response.json()["groups"] if group["code"] == "positive_admin_group")
        admin_group_update = client.put(f"/api/prompts/category-groups/{admin_group['id']}", json={
            **admin_group,
            "scopeType": "POSITIVE",
            "nameKo": "관리 카테고리 수정",
        })
        assert admin_group_update.status_code == 200, admin_group_update.text
        updated_group = next(group for group in admin_group_update.json()["groups"] if group["code"] == "positive_admin_group")
        assert updated_group["nameKo"] == "관리 카테고리 수정"

        admin_category_response = client.post("/api/prompts/categories", json={
            "code": "TEST_ADMIN_CATEGORY",
            "groupId": updated_group["id"],
            "groupCode": updated_group["code"],
            "scopeType": "SCENE",
            "selectionMode": "multi",
            "required": False,
            "maxSelectCount": 2,
            "nameKo": "관리 테스트",
            "nameEn": "Admin Test",
            "description": "created by smoke test",
            "sortOrder": 999,
        })
        assert admin_category_response.status_code == 200, admin_category_response.text
        admin_catalog = admin_category_response.json()
        admin_group_after_category = next(group for group in admin_catalog["groups"] if group["id"] == updated_group["id"])
        admin_category = next(subcategory for subcategory in admin_group_after_category["subcategories"] if subcategory["code"] == "TEST_ADMIN_CATEGORY")
        assert admin_category["selectionMode"] == "multi"

        # B-06 4단계: 3단계 당시엔 legacy_category_id가 없는(새로 만든) 서브카테고리
        # 아래에 신규 용어를 추가할 수 없어 400으로 차단됐었다(discrepancy로 보고).
        # 4단계가 prompt_terms.category_id를 nullable로 완화하며 그 제약을 완전히
        # 해소했다 - 방금 새로 만든 TEST_ADMIN_CATEGORY 아래에도 신규 용어가 정상
        # 생성되어야 한다.
        new_category_term_response = client.post("/api/prompts/terms", json={
            "categoryId": admin_category["id"],
            "code": "test_new_category_term",
            "canonicalKey": "test.new_category.term",
            "labelKo": "신규 카테고리 term",
            "labelEn": "new category term",
            "promptText": "new category prompt term",
            "negativeText": "",
            "riskLevel": "NONE",
            "sortOrder": 10,
        })
        assert new_category_term_response.status_code == 200, new_category_term_response.text
        new_category_group_after_term = next(group for group in new_category_term_response.json()["groups"] if group["id"] == updated_group["id"])
        new_category_subcategory_after_term = next(subcategory for subcategory in new_category_group_after_term["subcategories"] if subcategory["code"] == "TEST_ADMIN_CATEGORY")
        new_category_term = next(term for term in new_category_subcategory_after_term["terms"] if term["code"] == "test_new_category_term")
        assert new_category_term["promptText"] == "new category prompt term"

        # 완료 기준 확인: "4e에서 만든 서브카테고리와 용어가 2b 프롬프트 생성에 그대로
        # 나타난다" - 이관 이력이 전혀 없는, 순수하게 4단계 이후 새로 만든 카테고리/
        # 용어로 검증한다(이관된 카테고리로만 검증하면 이 케이스를 놓친다).
        new_category_scene_response = client.post("/api/prompts/scene", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "termIds": [new_category_term["id"]],
        })
        assert new_category_scene_response.status_code == 200, new_category_scene_response.text
        assert new_category_term["id"] in new_category_scene_response.json()["usedTermIds"]

        new_category_term_deactivate_response = client.post(f"/api/prompts/terms/{new_category_term['id']}/deactivate")
        assert new_category_term_deactivate_response.status_code == 200, new_category_term_deactivate_response.text

        admin_category_update = client.put(f"/api/prompts/categories/{admin_category['id']}", json={
            **admin_category,
            "selectionMode": "single",
            "nameKo": "관리 테스트 수정",
        })
        assert admin_category_update.status_code == 200, admin_category_update.text
        admin_group_after_update = next(group for group in admin_category_update.json()["groups"] if group["id"] == updated_group["id"])
        updated_category = next(subcategory for subcategory in admin_group_after_update["subcategories"] if subcategory["code"] == "TEST_ADMIN_CATEGORY")
        assert updated_category["selectionMode"] == "single"

        # 성공 경로: 이관 이력이 있는 기존 서브카테고리(GENRE) 아래 신규 용어 추가도
        # (신규 카테고리와 마찬가지로) 정상 동작해야 한다. prompt_terms에는 콘텐츠
        # 저장을 위해 1행이 늘지만(스키마상 불가피 - prompt_subcategory_keywords에는
        # 콘텐츠 컬럼이 없음), 구형 조인 테이블 prompt_category_terms는 늘지 않고
        # prompt_subcategory_keywords만 늘어난다 - 이는 별도 검증 스크립트에서 직접
        # 테이블 카운트로 확인한다.
        admin_term_response = client.post("/api/prompts/terms", json={
            "categoryId": genre_subcategory["id"],
            "code": "test_admin_term",
            "canonicalKey": "test.admin.term",
            "labelKo": "관리 term",
            "labelEn": "admin term",
            "promptText": "admin prompt term",
            "negativeText": "",
            "riskLevel": "NONE",
            "sortOrder": 10,
        })
        assert admin_term_response.status_code == 200, admin_term_response.text
        admin_group_after_term = next(group for group in admin_term_response.json()["groups"] if group["id"] == work_style_group["id"])
        admin_subcategory_after_term = next(subcategory for subcategory in admin_group_after_term["subcategories"] if subcategory["code"] == "GENRE")
        admin_term = next(term for term in admin_subcategory_after_term["terms"] if term["code"] == "test_admin_term")
        assert admin_term["promptText"] == "admin prompt term"

        term_deactivate_response = client.post(f"/api/prompts/terms/{admin_term['id']}/deactivate")
        assert term_deactivate_response.status_code == 200, term_deactivate_response.text
        term_deactivated_group = next(group for group in term_deactivate_response.json()["groups"] if group["id"] == work_style_group["id"])
        term_deactivated_subcategory = next(subcategory for subcategory in term_deactivated_group["subcategories"] if subcategory["code"] == "GENRE")
        assert not any(term["code"] == "test_admin_term" for term in term_deactivated_subcategory["terms"])

        category_deactivate_response = client.post(f"/api/prompts/categories/{updated_category['id']}/deactivate")
        assert category_deactivate_response.status_code == 200, category_deactivate_response.text
        category_deactivated_group = next(group for group in category_deactivate_response.json()["groups"] if group["id"] == updated_group["id"])
        assert not any(subcategory["code"] == "TEST_ADMIN_CATEGORY" for subcategory in category_deactivated_group["subcategories"])
        group_deactivate_response = client.post(f"/api/prompts/category-groups/{updated_group['id']}/deactivate")
        assert group_deactivate_response.status_code == 200, group_deactivate_response.text
        assert not any(group["code"] == "positive_admin_group" for group in group_deactivate_response.json()["groups"])

        schema_response = client.get("/api/prompts/scene-schema")
        assert schema_response.status_code == 200
        scene_schema = schema_response.json()
        assert scene_schema["$id"].endswith("/scene-json-v1.schema.json")
        assert scene_schema["properties"]["version"]["const"] == "1.0"
        assert scene_schema["properties"]["scenes"]["minItems"] == 1
        assert "entity" not in scene_schema["$defs"]
        assert "relation" not in scene_schema["$defs"]
        assert "description" in scene_schema["$defs"]["sceneItem"]["required"]

        scene_response = client.post("/api/prompts/scene", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "termIds": term_ids,
            "constraints": {
                "preserve_identity": True,
                "avoid_new_objects": True,
                "i2v_mode": True,
            },
        })
        assert scene_response.status_code == 200, scene_response.text
        scene = scene_response.json()
        assert scene["requestId"].startswith("prompt_req_")
        assert "cinematic WAN image-to-video shot" in scene["positivePromptDraft"]
        assert "gentle, natural walking motion" in scene["positivePromptDraft"]
        assert "gentle walking motion" not in scene["positivePromptDraft"]
        assert "distorted anatomy" in scene["negativePromptDraft"]
        assert scene["modelProfile"]["modelFamily"] == "WAN"
        assert scene["scene"]["version"] == "1.0"
        assert set(scene_schema["required"]).issubset(scene["scene"].keys())
        first_scene = scene["scene"]["scenes"][0]
        assert set(scene_schema["$defs"]["sceneItem"]["required"]).issubset(first_scene.keys())
        assert "entities" not in first_scene
        assert "relations" not in first_scene
        assert "person" in first_scene["summary"]
        assert "preserve identity" not in first_scene["summary"]
        assert scene["constraints"]["preserve_identity"] is True
        assert "gentle walking" in first_scene["summary"]
        assert len(scene["usedTermIds"]) == 5
        assert any(warning["code"] == "term_implied" for warning in scene["warnings"])
        assert any(warning["code"] == "term_recommended" for warning in scene["warnings"])

        from backend.app.services.prompt_builder_service import (
            scene_json_v1_schema_validation_available,
            validate_scene_json_v1,
            validate_scene_json_v1_with_schema,
        )

        assert validate_scene_json_v1(scene["scene"]) == []
        assert validate_scene_json_v1_with_schema(scene["scene"]) == []
        assert scene_json_v1_schema_validation_available()
        invalid_scene = {**scene["scene"], "scenes": []}
        invalid_errors = validate_scene_json_v1(invalid_scene)
        invalid_schema_errors = validate_scene_json_v1_with_schema(invalid_scene)
        assert invalid_errors
        assert invalid_schema_errors
        assert invalid_errors[0]["code"] == "scene_schema_invalid"
        assert invalid_schema_errors[0]["code"] == "scene_schema_invalid"

        validation_response = client.post("/api/prompts/scene", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "termIds": subject_term_ids,
        })
        assert validation_response.status_code == 200, validation_response.text
        validation_scene = validation_response.json()
        assert "person" in validation_scene["scene"]["scenes"][0]["summary"]
        assert any(warning["code"] == "selection_limit_trimmed" for warning in validation_scene["warnings"])

        description_response = client.post("/api/prompts/scene", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "termIds": term_ids,
            "description": "main person gently turns toward the camera",
        })
        assert description_response.status_code == 200, description_response.text
        description_scene = description_response.json()["scene"]
        description_scene_item = description_scene["scenes"][0]
        assert description_scene_item["description"] == "main person gently turns toward the camera"
        assert "main person gently turns toward the camera" not in description_scene_item["summary"]
        assert "entities" not in description_scene_item
        assert "relations" not in description_scene_item
        assert validate_scene_json_v1_with_schema(description_scene) == []

        description_only_response = client.post("/api/prompts/scene", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "termIds": [],
            "description": "girl dance exciting",
        })
        assert description_only_response.status_code == 200, description_only_response.text
        description_only_scene = description_only_response.json()
        description_only_item = description_only_scene["scene"]["scenes"][0]
        assert description_only_scene["usedTermIds"] == []
        assert description_only_item["summary"] == ""
        assert description_only_item["description"] == "girl dance exciting"
        assert validate_scene_json_v1_with_schema(description_only_scene["scene"]) == []

        extension_term_ids = [
            term["id"]
            for category in subcategories
            for term in category["terms"]
            if term["code"] in {
                "subject_person",
                "object_remain_stable",
                "motion_speed_slow",
                "motion_intensity_subtle",
                "camera_angle_eye_level",
                "lens_standard",
                "focus_subject_locked",
                "clothing_preserve",
                "pose_preserve",
                "gaze_camera",
                "expression_soft_smile",
                "emotion_calm",
                "animation_realistic_i2v",
                "rendering_photoreal",
                "transition_none",
                "duration_short_3s",
                "negative_low_quality",
                "negative_camera_shake",
                "negative_text_overlay",
            }
        ]
        extension_response = client.post("/api/prompts/scene", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "termIds": extension_term_ids,
        })
        assert extension_response.status_code == 200, extension_response.text
        extension_scene = extension_response.json()["scene"]["scenes"][0]
        assert "remain stable" in extension_scene["summary"]
        assert "preserve clothing" in extension_scene["summary"]
        assert "eye-level angle" in extension_scene["camera"]["angle"]
        assert "standard lens" in extension_scene["camera"]["lens"]
        assert "subject-locked focus" in extension_scene["camera"]["focus"]
        assert "realistic image-to-video" in extension_scene["style"]["animationStyle"]
        assert "photorealistic rendering" in extension_scene["style"]["renderingStyle"]
        assert "slow motion pace" in extension_scene["motion"]["speed"]
        assert "subtle motion intensity" in extension_scene["motion"]["intensity"]
        assert "avoid low quality" in extension_scene["negativeTerms"]

        camera_term_ids = [
            term["id"]
            for category in subcategories
            for term in category["terms"]
            if term["code"] in {"camera_static", "camera_slow_tracking", "subject_person"}
        ]
        conflict_response = client.post("/api/prompts/scene", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "termIds": camera_term_ids,
        })
        assert conflict_response.status_code == 200, conflict_response.text
        conflict_scene = conflict_response.json()
        assert any(warning["code"] == "term_relation_conflict" for warning in conflict_scene["warnings"])

        generate_response = client.post("/api/prompts/generate", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "provider": "mock",
            "termIds": term_ids,
            "scene": scene["scene"],
            "constraints": scene["constraints"],
        })
        assert generate_response.status_code == 200, generate_response.text
        generated = generate_response.json()
        assert generated["provider"] == "mock"
        assert "preserve identity" in generated["positivePrompt"]
        assert "identity drift" in generated["negativePrompt"]

        system_prompt_response = client.get("/api/prompts/system-prompt")
        assert system_prompt_response.status_code == 200, system_prompt_response.text
        system_prompt = system_prompt_response.json()
        assert system_prompt["code"] == "qwen_wan_i2v_positive"
        assert system_prompt["modelFamily"] == "qwen"
        assert "DOBEDUB STUDIO" in system_prompt["promptText"]
        assert "Negative prompts are managed separately" in system_prompt["promptText"]
        assert "Scene Detail normalization rules" in system_prompt["promptText"]
        assert "regardless of the input order" in system_prompt["promptText"]

        # Only the untouched legacy template is upgraded; custom text is handled below.
        with SessionLocal() as db:
            stored_system_prompt = db.get(PromptSystemPrompt, system_prompt["id"])
            assert stored_system_prompt is not None
            stored_system_prompt.prompt_text = LEGACY_DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT
            db.commit()
        upgraded_system_prompt_response = client.get("/api/prompts/system-prompt")
        assert upgraded_system_prompt_response.status_code == 200, upgraded_system_prompt_response.text
        assert "Scene Detail normalization rules" in upgraded_system_prompt_response.json()["promptText"]

        custom_system_prompt_text = (
            "CUSTOM QWEN SYSTEM PROMPT. Return only valid JSON with positivePrompt, "
            "negativePrompt, warnings. negativePrompt must be an empty string."
        )
        save_system_prompt_response = client.put("/api/prompts/system-prompt", json={
            "promptText": custom_system_prompt_text,
        })
        assert save_system_prompt_response.status_code == 200, save_system_prompt_response.text
        saved_system_prompt = save_system_prompt_response.json()
        assert saved_system_prompt["promptText"] == custom_system_prompt_text

        class FakeRunpodResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"status":"COMPLETED","output":"{\\"choices\\":[{\\"tokens\\":[\\"Final JSON:\\\\n{\\\\\\"positivePrompt\\\\\\":\\\\\\"runpod cinematic prompt\\\\\\",\\\\\\"negativePrompt\\\\\\":\\\\\\"runpod negative prompt\\\\\\",\\\\\\"warnings\\\\\\":[]}\\"]}] }"}'

        class FakeAsyncRunpodResponse:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return self.body

        os.environ["PROMPT_LLM_PROVIDER"] = "runpod_vllm"
        os.environ["PROMPT_LLM_API_KEY"] = "test_prompt_llm_key"
        os.environ["PROMPT_LLM_ENDPOINT_ID"] = "test_prompt_llm_endpoint"
        os.environ["PROMPT_LLM_RUNPOD_EXECUTION_MODE"] = "async"
        async_submit_response = FakeAsyncRunpodResponse(b'{"id":"prompt_job_001","status":"IN_QUEUE"}')
        async_complete_response = FakeAsyncRunpodResponse(
            b'{"id":"prompt_job_001","status":"COMPLETED","output":"{\\"positivePrompt\\":\\"async cinematic prompt\\",\\"negativePrompt\\":\\"async negative prompt\\",\\"warnings\\":[]}"}'
        )
        with patch(
            "backend.app.services.prompt_llm_client.urllib.request.urlopen",
            side_effect=[async_submit_response, async_complete_response],
        ) as async_urlopen:
            async_generate_response = client.post("/api/prompts/generate", json={
                "workflowId": "1-images.json",
                "segmentIndex": 1,
                "language": "ko",
                "termIds": term_ids,
                "scene": scene["scene"],
                "constraints": scene["constraints"],
            })
            assert async_generate_response.status_code == 202, async_generate_response.text
            async_request = async_generate_response.json()
            assert async_request["status"] == "IN_QUEUE"
            assert async_request["externalJobId"] == "prompt_job_001"
            from backend.app.services.prompt_builder_service import monitor_active_prompt_generations

            monitor_active_prompt_generations()
            async_status_response = client.get(f"/api/prompts/generate/{async_request['requestId']}")
        assert async_status_response.status_code == 200, async_status_response.text
        assert async_status_response.json()["status"] == "COMPLETED"
        assert async_status_response.json()["positivePrompt"] == "async cinematic prompt."
        assert async_urlopen.call_args_list[0][0][0].full_url.endswith("/test_prompt_llm_endpoint/run")
        assert async_urlopen.call_args_list[1][0][0].full_url.endswith("/test_prompt_llm_endpoint/status/prompt_job_001")

        os.environ["PROMPT_LLM_PROVIDER"] = "runpod_vllm"
        os.environ["PROMPT_LLM_API_KEY"] = "test_prompt_llm_key"
        os.environ["PROMPT_LLM_ENDPOINT_ID"] = "test_prompt_llm_endpoint"
        os.environ["PROMPT_LLM_RUNPOD_EXECUTION_MODE"] = "sync"
        with patch("backend.app.services.prompt_llm_client.urllib.request.urlopen", return_value=FakeRunpodResponse()) as fake_urlopen:
            runpod_generate_response = client.post("/api/prompts/generate", json={
                "workflowId": "1-images.json",
                "segmentIndex": 1,
                "language": "ko",
                "termIds": term_ids,
                "scene": scene["scene"],
                "constraints": scene["constraints"],
            })
        os.environ["PROMPT_LLM_PROVIDER"] = "mock"
        assert runpod_generate_response.status_code == 200, runpod_generate_response.text
        runpod_generated = runpod_generate_response.json()
        assert runpod_generated["provider"] == "runpod_vllm"
        assert runpod_generated["positivePrompt"] == "runpod cinematic prompt."
        assert runpod_generated["negativePrompt"] == "runpod negative prompt"
        runpod_request = fake_urlopen.call_args[0][0]
        assert runpod_request.full_url.endswith("/test_prompt_llm_endpoint/runsync")
        runpod_request_body = json.loads(runpod_request.data.decode("utf-8"))
        assert "CUSTOM QWEN SYSTEM PROMPT" in json.dumps(runpod_request_body, ensure_ascii=False)

        import io
        from urllib.error import HTTPError

        os.environ["PROMPT_LLM_PROVIDER"] = "runpod_vllm"
        os.environ["PROMPT_LLM_COLD_START_RETRY_DELAYS_SECONDS"] = "1"
        cold_start_error = HTTPError("https://example.invalid/runsync", 502, "Bad Gateway", {}, io.BytesIO(b"worker starting"))
        with patch(
            "backend.app.services.prompt_llm_client.urllib.request.urlopen",
            side_effect=[cold_start_error, FakeRunpodResponse()],
        ) as retry_urlopen, patch("backend.app.services.prompt_llm_client.time.sleep") as retry_sleep:
            cold_start_response = client.post("/api/prompts/generate", json={
                "workflowId": "1-images.json",
                "segmentIndex": 1,
                "language": "ko",
                "termIds": term_ids,
                "scene": scene["scene"],
                "constraints": scene["constraints"],
            })
        os.environ.pop("PROMPT_LLM_COLD_START_RETRY_DELAYS_SECONDS", None)
        os.environ["PROMPT_LLM_PROVIDER"] = "mock"
        assert cold_start_response.status_code == 200, cold_start_response.text
        assert retry_urlopen.call_count == 2
        retry_sleep.assert_called_once_with(1)

        class FakeEchoedRunpodResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"status":"COMPLETED","output":[{"choices":[{"tokens":["Echo example: {\\"positivePrompt\\":\\"example prompt\\",\\"negativePrompt\\":\\"\\",\\"warnings\\":[]}\\nFinal: {\\"positivePrompt\\":\\"actual final prompt\\",\\"negativePrompt\\":\\"\\",\\"warnings\\":[]}"]}]}]}'

        os.environ["PROMPT_LLM_PROVIDER"] = "runpod_vllm"
        with patch("backend.app.services.prompt_llm_client.urllib.request.urlopen", return_value=FakeEchoedRunpodResponse()):
            echoed_generate_response = client.post("/api/prompts/generate", json={
                "workflowId": "1-images.json",
                "segmentIndex": 1,
                "language": "ko",
                "termIds": term_ids,
                "scene": scene["scene"],
                "constraints": scene["constraints"],
            })
        os.environ["PROMPT_LLM_PROVIDER"] = "mock"
        assert echoed_generate_response.status_code == 200, echoed_generate_response.text
        assert echoed_generate_response.json()["positivePrompt"] == "actual final prompt."

        class FakePlaceholderRunpodResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"status":"COMPLETED","output":"{\\"positivePrompt\\":\\"string\\",\\"negativePrompt\\":\\"\\",\\"warnings\\":[\\"string\\"]}"}'

        os.environ["PROMPT_LLM_PROVIDER"] = "runpod_vllm"
        with patch("backend.app.services.prompt_llm_client.urllib.request.urlopen", return_value=FakePlaceholderRunpodResponse()):
            placeholder_generate_response = client.post("/api/prompts/generate", json={
                "workflowId": "1-images.json",
                "segmentIndex": 1,
                "language": "ko",
                "termIds": term_ids,
                "scene": scene["scene"],
                "constraints": scene["constraints"],
            })
        os.environ["PROMPT_LLM_PROVIDER"] = "mock"
        assert placeholder_generate_response.status_code == 502, placeholder_generate_response.text
        assert "invalid response after one retry" in placeholder_generate_response.text
        os.environ.pop("PROMPT_LLM_RUNPOD_EXECUTION_MODE", None)

        invalid_generate_response = client.post("/api/prompts/generate", json={
            "workflowId": "1-images.json",
            "segmentIndex": 1,
            "language": "ko",
            "provider": "mock",
            "termIds": term_ids,
            "scene": invalid_scene,
            "constraints": scene["constraints"],
        })
        assert invalid_generate_response.status_code == 400
        assert "Scene JSON v1 validation failed" in invalid_generate_response.text

        # B-02: prompt_feedback.taskId는 이제 필수다(2b/3f 두 기록을 연결하는
        # 완료 기준) - 이 테스트는 job/run 흐름을 거치지 않으므로 최소한의
        # WorkflowTask 행을 직접 만들어 그 id를 taskId로 사용한다.
        from backend.app.db.models import WorkflowTask

        with SessionLocal() as db:
            db.add(WorkflowTask(id="smoke_test_task_1", workflow_id="1-images.json", status="COMPLETED"))
            db.commit()

        missing_task_response = client.post("/api/prompts/feedback", json={
            "outputId": generated["outputId"],
            "rating": 5,
        })
        assert missing_task_response.status_code == 400, missing_task_response.text
        assert "taskId is required" in missing_task_response.text

        unknown_task_response = client.post("/api/prompts/feedback", json={
            "outputId": generated["outputId"],
            "taskId": "does-not-exist",
            "rating": 5,
        })
        assert unknown_task_response.status_code == 400, unknown_task_response.text
        assert "Task not found" in unknown_task_response.text

        feedback_response = client.post("/api/prompts/feedback", json={
            "outputId": generated["outputId"],
            "taskId": "smoke_test_task_1",
            "rating": 5,
            "editedPositivePrompt": generated["positivePrompt"],
            "editedNegativePrompt": generated["negativePrompt"],
            "notes": "smoke test",
        })
        assert feedback_response.status_code == 201, feedback_response.text
        assert feedback_response.json()["rating"] == 5
        assert feedback_response.json()["taskId"] == "smoke_test_task_1"

        # 완료 기준: task_prompts에 붙은 세그먼트를 GET /jobs/{taskId}/prompts로
        # 조회하면 방금 저장한 prompt_feedback(프롬프트 생성 품질)이 함께 내려와야
        # 한다 - "영상 결과 평가"(qualityRating)와 값이 섞이지 않는지도 같이 확인.
        from backend.app.db.models import TaskPrompt

        with SessionLocal() as db:
            db.add(TaskPrompt(
                task_id="smoke_test_task_1",
                workflow_id="1-images.json",
                segment_index=1,
                prompt_generation_output_id=generated["outputId"],
                positive_prompt=generated["positivePrompt"],
                negative_prompt=generated["negativePrompt"],
            ))
            db.commit()

        job_prompts_response = client.get("/api/jobs/smoke_test_task_1/prompts")
        assert job_prompts_response.status_code == 200, job_prompts_response.text
        job_prompt_items = job_prompts_response.json()["items"]
        assert len(job_prompt_items) == 1
        assert job_prompt_items[0]["promptFeedback"]["rating"] == 5
        assert job_prompt_items[0]["promptFeedback"]["notes"] == "smoke test"
        assert job_prompt_items[0]["qualityRating"] is None

    print("OK prompt db smoke check passed")


if __name__ == "__main__":
    main()
