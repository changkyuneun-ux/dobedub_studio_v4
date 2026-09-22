from __future__ import annotations

from types import SimpleNamespace

from backend.app.core.security import create_access_token
from backend.app.db.models import User, WorkflowDefinition, WorkflowRevision
from backend.app.db.session import SessionLocal


VALID_WORKFLOW = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
    "2": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "output"}},
}


def _headers() -> dict[str, str]:
    token = create_access_token({"id": "workflow-admin", "name": "Workflow Admin", "role": "SUPER_ADMIN"})
    return {"Authorization": f"Bearer {token['accessToken']}"}


def _seed_admin() -> None:
    session = SessionLocal()
    try:
        session.add(User(id="workflow-admin", name="Workflow Admin", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True))
        session.commit()
    finally:
        session.close()


def _settings(tmp_path):
    workflows_dir = tmp_path / "workflows"
    data_dir = tmp_path / "data"
    metadata_dir = tmp_path / "metadata"
    workflows_dir.mkdir()
    data_dir.mkdir()
    metadata_dir.mkdir()
    return SimpleNamespace(workflows_dir=workflows_dir, data_dir=data_dir, metadata_dir=metadata_dir)


def test_registers_arbitrary_workflow_as_inactive(api_client, monkeypatch, tmp_path):
    _seed_admin()
    settings = _settings(tmp_path)
    monkeypatch.setattr("backend.app.services.admin_service.get_settings", lambda: settings)

    response = api_client.post(
        "/api/admin/workflows",
        headers=_headers(),
        json={
            "workflowId": "Pickme_Workflow_v7.json",
            "workflowJson": VALID_WORKFLOW,
            "paramConfigJson": {"workflow": "Pickme_Workflow_v7.json"},
        },
    )

    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["items"] if item["id"] == "Pickme_Workflow_v7.json")
    assert item["status"] == "INACTIVE"
    assert item["active"] is False
    assert item["latestRevision"] == 1
    assert item["currentRevision"] is None
    assert not (settings.workflows_dir / "Pickme_Workflow_v7.json").exists()
    assert (settings.workflows_dir / "releases/Pickme_Workflow_v7/1/workflow.json").exists()


def test_activate_and_deactivate_preserve_release_files(api_client, monkeypatch, tmp_path):
    _seed_admin()
    settings = _settings(tmp_path)
    monkeypatch.setattr("backend.app.services.admin_service.get_settings", lambda: settings)
    synchronized: list[str] = []
    monkeypatch.setattr(
        "backend.app.services.admin_service.sync_workflow_segment_defaults",
        lambda workflow_id: synchronized.append(workflow_id) or {"workflowName": workflow_id, "segments": []},
    )
    payload = {
        "workflowId": "dynamic-v2.json",
        "workflowJson": VALID_WORKFLOW,
        "paramConfigJson": {"workflow": "dynamic-v2.json"},
    }
    assert api_client.post("/api/admin/workflows", headers=_headers(), json=payload).status_code == 200

    activated = api_client.post("/api/admin/workflows/dynamic-v2.json/activate", headers=_headers())
    assert activated.status_code == 200, activated.text
    active_item = next(item for item in activated.json()["items"] if item["id"] == "dynamic-v2.json")
    assert active_item["status"] == "ACTIVE"
    assert active_item["currentRevision"] == 1
    assert (settings.workflows_dir / "dynamic-v2.json").exists()
    assert synchronized == ["dynamic-v2.json"]

    deactivated = api_client.post("/api/admin/workflows/dynamic-v2.json/deactivate", headers=_headers())
    assert deactivated.status_code == 200
    inactive_item = next(item for item in deactivated.json()["items"] if item["id"] == "dynamic-v2.json")
    assert inactive_item["status"] == "INACTIVE"
    assert (settings.workflows_dir / "releases/dynamic-v2/1/workflow.json").exists()
    assert (settings.workflows_dir / "dynamic-v2.json").exists()


def test_changed_content_creates_revision_and_identical_content_deduplicates(api_client, monkeypatch, tmp_path):
    _seed_admin()
    settings = _settings(tmp_path)
    monkeypatch.setattr("backend.app.services.admin_service.get_settings", lambda: settings)
    payload = {"workflowId": "revisioned.json", "workflowJson": VALID_WORKFLOW, "paramConfigJson": {}}

    first = api_client.post("/api/admin/workflows", headers=_headers(), json=payload)
    duplicate = api_client.post("/api/admin/workflows", headers=_headers(), json=payload)
    changed = api_client.post(
        "/api/admin/workflows",
        headers=_headers(),
        json={**payload, "workflowJson": {**VALID_WORKFLOW, "3": {"class_type": "SaveVideo", "inputs": {}}}},
    )

    assert first.status_code == duplicate.status_code == changed.status_code == 200
    session = SessionLocal()
    try:
        definition = session.get(WorkflowDefinition, "revisioned.json")
        revisions = session.query(WorkflowRevision).filter_by(workflow_id=definition.id).order_by(WorkflowRevision.revision).all()
        assert [item.revision for item in revisions] == [1, 2]
    finally:
        session.close()

    revisions = api_client.get("/api/admin/workflows/revisioned.json/revisions", headers=_headers())
    assert revisions.status_code == 200
    assert [item["revision"] for item in revisions.json()["items"]] == [2, 1]


def test_integrity_mismatch_blocks_activation(api_client, monkeypatch, tmp_path):
    _seed_admin()
    settings = _settings(tmp_path)
    monkeypatch.setattr("backend.app.services.admin_service.get_settings", lambda: settings)
    payload = {"workflowId": "corrupt.json", "workflowJson": VALID_WORKFLOW, "paramConfigJson": {}}
    assert api_client.post("/api/admin/workflows", headers=_headers(), json=payload).status_code == 200
    (settings.workflows_dir / "releases/corrupt/1/workflow.json").write_text("{}", encoding="utf-8")

    response = api_client.post("/api/admin/workflows/corrupt.json/activate", headers=_headers())

    assert response.status_code == 400
    assert "integrity" in response.json()["detail"]


def test_archive_requires_deactivation_hides_workflow_and_preserves_revisions(api_client, monkeypatch, tmp_path):
    _seed_admin()
    settings = _settings(tmp_path)
    monkeypatch.setattr("backend.app.services.admin_service.get_settings", lambda: settings)
    payload = {"workflowId": "archive-me.json", "workflowJson": VALID_WORKFLOW, "paramConfigJson": {}}
    assert api_client.post("/api/admin/workflows", headers=_headers(), json=payload).status_code == 200
    assert api_client.post("/api/admin/workflows/archive-me.json/activate", headers=_headers()).status_code == 200
    blocked = api_client.post("/api/admin/workflows/archive-me.json/archive", headers=_headers())
    assert blocked.status_code == 400

    assert api_client.post("/api/admin/workflows/archive-me.json/deactivate", headers=_headers()).status_code == 200
    archived = api_client.post("/api/admin/workflows/archive-me.json/archive", headers=_headers())
    assert archived.status_code == 200
    assert all(item["id"] != "archive-me.json" for item in archived.json()["items"])
    assert (settings.workflows_dir / "releases/archive-me/1/workflow.json").exists()

    revisions = api_client.get("/api/admin/workflows/archive-me.json/revisions", headers=_headers())
    assert revisions.status_code == 200
    assert [item["revision"] for item in revisions.json()["items"]] == [1]
