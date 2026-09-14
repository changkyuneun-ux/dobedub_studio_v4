from __future__ import annotations

from sqlalchemy import select

from backend.app.core.security import create_access_token
from backend.app.db.models import AuditLog, User
from backend.app.db.session import SessionLocal
from backend.app.services.sandbox_pod_service import SandboxPodConflict, SandboxPodUnavailable


ATTEMPTS = [
    {"stage": "start", "podId": "caiuvooekq9qqw", "gpuTypeId": "NVIDIA GeForce RTX 5090", "ok": False,
     "error": "HTTP 500: no instances currently available", "at": "2026-09-11T00:20:31Z"},
]


def _seed_users() -> None:
    session = SessionLocal()
    try:
        session.add_all([
            User(id="sandbox-admin", name="Sandbox Admin", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="sandbox-viewer", name="Sandbox Viewer", role="OPERATOR", permissions_json=["sandbox:read"], is_active=True),
        ])
        session.commit()
    finally:
        session.close()


def _headers(user_id: str, *, role: str) -> dict[str, str]:
    token = create_access_token({"id": user_id, "name": user_id, "role": role})
    return {"Authorization": f"Bearer {token['accessToken']}"}


def _audit_actions() -> list[tuple[str, dict | None]]:
    session = SessionLocal()
    try:
        rows = session.scalars(select(AuditLog).order_by(AuditLog.id)).all()
        return [(row.action, row.after_json) for row in rows]
    finally:
        session.close()


def test_start_maps_unavailable_to_503_with_attempts_and_records_failed_audit(api_client, monkeypatch):
    _seed_users()

    def fail(settings, db, pod_id, *, actor_id):
        raise SandboxPodUnavailable("EU-RO-1에 기동 가능한 파드·GPU가 없습니다.", ATTEMPTS)

    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.start_sandbox_pod", fail)

    response = api_client.post("/api/admin/sandbox-pod/start", json={"podId": "caiuvooekq9qqw"},
                               headers=_headers("sandbox-admin", role="SUPER_ADMIN"))

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"].startswith("EU-RO-1")
    assert detail["attempts"] == ATTEMPTS
    assert detail["retryAfterSeconds"] == 300
    actions = _audit_actions()
    failed = [after for action, after in actions if action == "sandbox_pod.start_failed"]
    assert failed and failed[0]["attempts"] == ATTEMPTS and failed[0]["status"] == 503


def test_start_maps_conflict_to_409(api_client, monkeypatch):
    _seed_users()

    def conflict(settings, db, pod_id, *, actor_id):
        raise SandboxPodConflict("실행 중인 Sandbox Pod가 2개입니다.", [], running_pod_ids=["a", "b"])

    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.start_sandbox_pod", conflict)

    response = api_client.post("/api/admin/sandbox-pod/start", headers=_headers("sandbox-admin", role="SUPER_ADMIN"))

    assert response.status_code == 409
    assert response.json()["detail"]["runningPodIds"] == ["a", "b"]


def test_start_success_audit_includes_multi_pod_fields(api_client, monkeypatch):
    _seed_users()
    result = {
        "configured": True, "podId": "3i50u1x4pyz0vr", "activePodId": "3i50u1x4pyz0vr", "desiredStatus": "RUNNING",
        "runtimeStatus": "INITIALIZING", "gpuTypeId": "NVIDIA RTX PRO 6000 Blackwell Workstation Edition",
        "gpuTier": "fallback", "switched": True, "createdBy": None, "attempts": ATTEMPTS, "httpServices": [], "pods": [],
    }
    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.start_sandbox_pod", lambda settings, db, pod_id, *, actor_id: result)

    response = api_client.post("/api/admin/sandbox-pod/start", json={"podId": "caiuvooekq9qqw"},
                               headers=_headers("sandbox-admin", role="SUPER_ADMIN"))

    assert response.status_code == 200
    started = [after for action, after in _audit_actions() if action == "sandbox_pod.start"]
    assert started[0]["switched"] is True
    assert started[0]["gpuTier"] == "fallback"
    assert started[0]["requestedPodId"] == "caiuvooekq9qqw"
    assert started[0]["attempts"] == ATTEMPTS


def test_select_persists_and_returns_status(api_client, monkeypatch):
    _seed_users()
    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.sandbox_pod_status",
                        lambda settings, db: {"configured": True, "selectedPodId": "caiuvooekq9qqw", "pods": [], "httpServices": []})

    response = api_client.post("/api/admin/sandbox-pod/select", json={"podId": "caiuvooekq9qqw"},
                               headers=_headers("sandbox-admin", role="SUPER_ADMIN"))

    assert response.status_code == 200
    settings = api_client.put("/api/admin/sandbox-pod/settings", json={"autoSwitchOnStartFailure": False, "podPriority": ["a", "b"], "replaceSameGpuPods": False},
                              headers=_headers("sandbox-admin", role="SUPER_ADMIN"))
    assert settings.status_code == 200
    assert settings.json()["replaceSameGpuPods"] is False
    assert settings.json()["selectedPodId"] == "caiuvooekq9qqw"
    assert settings.json()["autoSwitchOnStartFailure"] is False
    assert settings.json()["podPriority"] == ["a", "b"]
    actions = [action for action, _ in _audit_actions()]
    assert "sandbox_pod.select" in actions and "sandbox_pod.settings_update" in actions


def test_terminate_endpoint_records_audit(api_client, monkeypatch):
    _seed_users()
    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.terminate_sandbox_pod",
                        lambda settings, db, pod_id, *, actor_id: {"terminatedPodId": pod_id, "terminatedPodName": "dobedub_comfyUI_Sandbox_RTX 5090",
                                                                   "attempts": [{"stage": "terminate", "podId": pod_id, "ok": True}], "selectedPodId": None, "pods": [], "httpServices": []})
    response = api_client.post("/api/admin/sandbox-pod/terminate", json={"podId": "caiuvooekq9qqw"}, headers=_headers("sandbox-admin", role="SUPER_ADMIN"))
    assert response.status_code == 200
    rows = [(action, after) for action, after in _audit_actions() if action == "sandbox_pod.terminate"]
    assert rows and rows[0][1]["attempts"][0]["stage"] == "terminate"
    assert api_client.post("/api/admin/sandbox-pod/terminate", json={}, headers=_headers("sandbox-admin", role="SUPER_ADMIN")).status_code == 400


def test_control_endpoints_require_sandbox_control(api_client):
    _seed_users()
    headers = _headers("sandbox-viewer", role="OPERATOR")
    assert api_client.post("/api/admin/sandbox-pod/select", json={"podId": "x"}, headers=headers).status_code == 403
    assert api_client.post("/api/admin/sandbox-pod/start", headers=headers).status_code == 403
    assert api_client.put("/api/admin/sandbox-pod/settings", json={}, headers=headers).status_code == 403
    assert api_client.post("/api/admin/sandbox-pod/terminate", json={"podId": "x"}, headers=headers).status_code == 403


def test_status_live_flag_and_live_endpoint(api_client, monkeypatch):
    # 2026-09-13 2단계 로딩: ?live=false는 include_live=False로 전달, /live는 sandbox_pod_live 호출.
    _seed_users()
    seen: dict[str, object] = {}

    def fake_status(settings, db, *, include_live=True):
        seen["include_live"] = include_live
        return {"configured": True, "pods": [], "attempts": []}

    def fake_live(settings, db):
        seen["live"] = True
        return {"configured": True, "podId": "p1", "runtimeStatus": "READY", "systemStatus": None, "pods": []}

    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.sandbox_pod_status", fake_status)
    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.sandbox_pod_live", fake_live)
    headers = _headers("sandbox-admin", role="SUPER_ADMIN")

    assert api_client.get("/api/admin/sandbox-pod?live=false", headers=headers).status_code == 200
    assert seen["include_live"] is False
    assert api_client.get("/api/admin/sandbox-pod", headers=headers).status_code == 200
    assert seen["include_live"] is True
    response = api_client.get("/api/admin/sandbox-pod/live", headers=headers)
    assert response.status_code == 200
    assert response.json()["runtimeStatus"] == "READY"
    assert seen.get("live") is True
