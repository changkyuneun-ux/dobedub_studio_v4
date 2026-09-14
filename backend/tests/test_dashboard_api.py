from __future__ import annotations

from backend.app.core.security import create_access_token
from backend.app.db.models import User
from backend.app.db.session import SessionLocal


def _seed_users() -> None:
    session = SessionLocal()
    try:
        session.add_all([
            User(id="dash-admin", name="Dash Admin", role="SUPER_ADMIN", permissions_json=["admin:*"], is_active=True),
            User(id="dash-nobody", name="No Permission", role="OPERATOR", permissions_json=[], is_active=True),
        ])
        session.commit()
    finally:
        session.close()


def _headers(user_id: str, *, role: str) -> dict[str, str]:
    token = create_access_token({"id": user_id, "name": user_id, "role": role})
    return {"Authorization": f"Bearer {token['accessToken']}"}


def _fake_summary(db, *, range_key="7d", limit=20, **_):
    return {"range": range_key, "limit": limit, "kpi": {}, "recent": [], "alerts": []}


def test_dashboard_requires_login_but_no_permission(api_client, monkeypatch):
    _seed_users()
    monkeypatch.setattr("backend.app.api.v1.dashboard.dashboard_summary", _fake_summary)

    assert api_client.get("/api/dashboard/summary").status_code == 401
    # 2026-09-13 정책: 전역 표시 — 권한이 하나도 없는 사용자도 200
    response = api_client.get("/api/dashboard/summary", headers=_headers("dash-nobody", role="OPERATOR"))
    assert response.status_code == 200
    assert response.json()["range"] == "7d"
    assert api_client.get("/api/dashboard/summary?range=today", headers=_headers("dash-admin", role="SUPER_ADMIN")).json()["range"] == "today"


def test_dashboard_validates_range_and_clamps_limit(api_client, monkeypatch):
    _seed_users()
    monkeypatch.setattr("backend.app.api.v1.dashboard.dashboard_summary", _fake_summary)
    headers = _headers("dash-admin", role="SUPER_ADMIN")

    bad = api_client.get("/api/dashboard/summary?range=1y", headers=headers)
    assert bad.status_code == 400 and "today, 7d, 30d" in bad.json()["detail"]
    assert api_client.get("/api/dashboard/summary?limit=500", headers=headers).json()["limit"] == 50
    assert api_client.get("/api/dashboard/summary?limit=0", headers=headers).status_code == 422


def test_dashboard_maps_service_errors_to_500(api_client, monkeypatch):
    _seed_users()

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("backend.app.api.v1.dashboard.dashboard_summary", boom)
    response = api_client.get("/api/dashboard/summary", headers=_headers("dash-admin", role="SUPER_ADMIN"))
    assert response.status_code == 500 and "db down" in response.json()["detail"]


def test_dashboard_summary_end_to_end_with_real_service(api_client):
    _seed_users()
    response = api_client.get("/api/dashboard/summary?range=30d", headers=_headers("dash-nobody", role="OPERATOR"))
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"kpi", "recent", "byUser", "byWorkflow", "system", "sandbox", "worker", "db", "alerts"}
    assert body["kpi"]["submitted"] == 0
    assert body["sandbox"]["configured"] in (True, False)
