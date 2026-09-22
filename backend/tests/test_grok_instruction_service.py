from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.services import grok_instruction_service as svc


ACTIVE_WORKFLOW_IDS = frozenset({
    "1-images_81.json",
    "1-images_10s_chain_81.json",
    "wan22_10s_chain.json",
    "wan22_default_81.json",
})


@pytest.fixture(autouse=True)
def _dynamic_active_workflows(monkeypatch):
    monkeypatch.setattr(svc, "_active_workflow_ids", lambda: sorted(ACTIVE_WORKFLOW_IDS))


def _write_set(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_resolve_workflow_instruction_set_returns_only_selected_workflow(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {
        "schemaVersion": "2.0",
        "workflowInstructionSets": [
            {"workflowId": "1-images.json", "version": 1, "documents": [
                {"id": "core", "code": "core", "title": "core", "role": "CORE", "isActive": True, "contentMarkdown": "핵심 규칙"},
                {"id": "router", "code": "router", "title": "router", "role": "ROUTER", "isActive": True, "contentMarkdown": "분기 규칙"},
            ]},
            {"workflowId": "3-images.json", "version": 1, "documents": [
                {"id": "core3", "code": "core3", "title": "core3", "role": "CORE", "isActive": True, "contentMarkdown": "다른 워크플로우"},
            ]},
        ],
    })
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    result = svc.resolve_workflow_instruction_set(svc.DEFAULT_WAN_WORKFLOW_ID)

    assert result["workflowId"] == svc.DEFAULT_WAN_WORKFLOW_ID
    assert "[CORE]" in result["compiledMarkdown"]
    assert "핵심 규칙" in result["compiledMarkdown"]
    assert "다른 워크플로우" not in result["compiledMarkdown"]


def test_resolve_unknown_workflow_raises(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {"schemaVersion": "2.0", "workflowInstructionSets": []})
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    with pytest.raises(ValueError, match="활성 프롬프트 지시문이 없습니다"):
        svc.resolve_workflow_instruction_set("1-images.json")


def test_duplicate_core_is_rejected():
    with pytest.raises(ValueError, match="CORE 역할은 워크플로우당 1개만"):
        svc.validate_instruction_set({"workflowId": "1-images.json", "documents": [{"role": "CORE"}, {"role": "CORE"}]})


def test_multiple_guides_are_allowed():
    svc.validate_instruction_set({"workflowId": "1-images.json", "documents": [{"role": "CORE"}, {"role": "GUIDE"}, {"role": "GUIDE"}]})


def test_legacy_v1_file_is_promoted_to_default_workflow(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {"schemaVersion": "1.0", "version": 7, "documents": [
        {"id": "legacy-core", "code": "legacy_core", "title": "legacy", "role": "CORE", "isActive": True, "contentMarkdown": "기존 관리자 편집본"},
    ]})
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    result = svc.resolve_workflow_instruction_set(svc.DEFAULT_WAN_WORKFLOW_ID)

    assert result["version"] == 7
    assert "기존 관리자 편집본" in result["compiledMarkdown"]
    promoted = json.loads(target.read_text(encoding="utf-8"))
    assert promoted["schemaVersion"] == "2.0"
    migrated = {item["workflowId"]: item for item in promoted["workflowInstructionSets"]}
    assert migrated[svc.DEFAULT_WAN_WORKFLOW_ID]["version"] == 7
    assert migrated[svc.LEGACY_DEFAULT_WORKFLOW_ID]["documents"] == []


def test_legacy_default_instruction_is_copied_to_every_approved_workflow(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {"schemaVersion": "1.0", "version": 1, "documents": [
        {"id": "legacy-core", "code": "legacy_core", "title": "legacy", "role": "CORE", "isActive": True, "contentMarkdown": "1-images only"},
    ]})
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    for workflow_id in ACTIVE_WORKFLOW_IDS:
        assert "1-images only" in svc.resolve_workflow_instruction_set(workflow_id)["compiledMarkdown"]

    with pytest.raises(ValueError, match="활성 프롬프트 지시문이 없습니다"):
        svc.resolve_workflow_instruction_set(svc.LEGACY_DEFAULT_WORKFLOW_ID)


def test_save_requires_workflow_id(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {"schemaVersion": "2.0", "workflowInstructionSets": []})
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    with pytest.raises(ValueError, match="워크플로우를 먼저 선택"):
        svc.save_instruction_document({"role": "GUIDE", "contentMarkdown": "x"}, document_id=None)


def test_delete_instruction_removes_only_the_selected_workflow_document(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {
        "schemaVersion": "2.0",
        "workflowInstructionSets": [
            {"workflowId": "1-images.json", "version": 1, "documents": [
                {"id": "core-1", "code": "core", "title": "Core", "role": "CORE", "isActive": True, "contentMarkdown": "core"},
                {"id": "guide-1", "code": "guide", "title": "Guide", "role": "GUIDE", "isActive": True, "contentMarkdown": "guide"},
            ]},
            {"workflowId": "3-images.json", "version": 1, "documents": [
                {"id": "guide-3", "code": "guide", "title": "Other guide", "role": "GUIDE", "isActive": True, "contentMarkdown": "other"},
            ]},
        ],
    })
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    migrated = svc.list_instruction_documents(svc.DEFAULT_WAN_WORKFLOW_ID)
    guide_id = next(item["id"] for item in migrated["items"] if item["code"] == "guide")
    result = svc.delete_instruction_document(svc.DEFAULT_WAN_WORKFLOW_ID, guide_id)

    assert [item["code"] for item in result["items"]] == ["core"]
    assert [item["id"] for item in svc.list_instruction_documents("3-images.json")["items"]] == ["guide-3"]


def test_copy_instruction_documents_creates_independent_target_workflow_set(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {
        "schemaVersion": "2.0",
        "workflowInstructionSets": [{"workflowId": "1-images.json", "version": 2, "documents": [
            {"id": "core-1", "code": "core", "title": "Core", "role": "CORE", "isActive": True, "contentMarkdown": "source core"},
            {"id": "guide-1", "code": "guide", "title": "Guide", "role": "GUIDE", "isActive": True, "contentMarkdown": "source guide"},
        ]}],
    })
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    copied = svc.copy_instruction_documents(svc.DEFAULT_WAN_WORKFLOW_ID, "other-workflow.json")

    assert copied["instructionSet"]["workflowId"] == "other-workflow.json"
    assert [item["contentMarkdown"] for item in copied["items"]] == ["source core", "source guide"]
    assert {item["id"] for item in copied["items"]}.isdisjoint({"core-1", "guide-1"})
    svc.save_instruction_document(
        {"workflowId": "other-workflow.json", "id": copied["items"][0]["id"], "role": "CORE", "contentMarkdown": "target core"},
        document_id=copied["items"][0]["id"],
    )
    assert "source core" in svc.resolve_workflow_instruction_set(svc.DEFAULT_WAN_WORKFLOW_ID)["compiledMarkdown"]
    assert "target core" in svc.resolve_workflow_instruction_set("other-workflow.json")["compiledMarkdown"]


def test_instruction_source_workflows_only_lists_workflows_with_documents(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {
        "schemaVersion": "2.0",
        "workflowInstructionSets": [
            {"workflowId": "1-images.json", "version": 2, "documents": [
                {"id": "core-1", "code": "core", "title": "Core", "role": "CORE", "isActive": True, "contentMarkdown": "core"},
            ]},
            {"workflowId": "empty-workflow.json", "version": 1, "documents": []},
            {"workflowId": "inactive-only.json", "version": 1, "documents": [
                {"id": "guide-1", "code": "guide", "title": "Guide", "role": "GUIDE", "isActive": False, "contentMarkdown": "guide"},
            ]},
        ],
    })
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    assert set(svc.list_instruction_source_workflows()) == ACTIVE_WORKFLOW_IDS


def test_existing_legacy_documents_move_to_flat_wan_without_overwriting_target(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {
        "schemaVersion": "2.0",
        "workflowInstructionSets": [
            {"workflowId": "1-images.json", "version": 4, "documents": [
                {"id": "core-1", "code": "core", "title": "Core", "role": "CORE", "isActive": True, "contentMarkdown": "legacy core"},
            ]},
            {"workflowId": svc.DEFAULT_WAN_WORKFLOW_ID, "version": 2, "documents": []},
        ],
    })
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    resolved = svc.resolve_workflow_instruction_set(svc.DEFAULT_WAN_WORKFLOW_ID)

    assert "legacy core" in resolved["compiledMarkdown"]
    stored = json.loads(target.read_text(encoding="utf-8"))
    stored_sets = {item["workflowId"]: item for item in stored["workflowInstructionSets"]}
    assert stored_sets["1-images.json"]["documents"] == []
    for workflow_id in ACTIVE_WORKFLOW_IDS:
        assert stored_sets[workflow_id]["documents"]
