from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.services import admin_service, workflow_service
from backend.app.services.workflow_visibility import SUPPORTED_WORKFLOW_IDS, assert_workflow_selectable


REMOVED_WORKFLOW_IDS = {
    "1-images.json",
    "1-images_10s_chain.json",
    "Blowbang1.json",
    "Pickme_Workflow.json",
    "video_wan2_2_14B_flf2v_2-images-1.json",
    "video_minimax_h3_r2v.json",
}


def test_retired_workflows_are_hidden_from_studio_and_admin_lists(monkeypatch, tmp_path):
    items = [{"id": workflow_id, "name": Path(workflow_id).stem} for workflow_id in sorted(REMOVED_WORKFLOW_IDS | SUPPORTED_WORKFLOW_IDS)]
    settings = SimpleNamespace(workflows_dir=tmp_path, metadata_dir=tmp_path)

    monkeypatch.setattr(workflow_service, "get_settings", lambda: settings)
    monkeypatch.setattr(workflow_service, "parse_workflow_list", lambda _directory: items)
    monkeypatch.setattr(admin_service, "get_settings", lambda: settings)
    monkeypatch.setattr(admin_service, "parse_workflow_list", lambda _directory: items)
    monkeypatch.setattr(admin_service, "load_workflow_registry", lambda: {"items": {}})
    monkeypatch.setattr(admin_service, "read_json_if_exists", lambda _path, default: default)
    monkeypatch.setattr(admin_service, "workflow_registry_path", lambda: tmp_path / "workflow-registry.json")

    assert {item["id"] for item in workflow_service.list_workflows()} == SUPPORTED_WORKFLOW_IDS
    assert {item["id"] for item in admin_service.list_admin_workflows()["items"]} == SUPPORTED_WORKFLOW_IDS


def test_unapproved_workflow_cannot_be_reactivated_or_registered_again():
    with pytest.raises(ValueError, match="not approved"):
        admin_service.set_admin_workflow_active("1-images.json", True)

    with pytest.raises(ValueError, match="not approved"):
        admin_service.register_admin_workflow({"workflowId": "1-images.json"})


def test_unapproved_workflow_cannot_be_used_by_a_direct_request():
    with pytest.raises(ValueError, match="not approved"):
        assert_workflow_selectable("Pickme_Workflow.json")


@pytest.mark.parametrize("workflow_id", sorted(SUPPORTED_WORKFLOW_IDS))
def test_approved_workflow_can_be_used_by_a_direct_request(workflow_id):
    assert_workflow_selectable(workflow_id)
