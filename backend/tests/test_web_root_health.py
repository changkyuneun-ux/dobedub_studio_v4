from __future__ import annotations


def test_root_returns_success_for_load_balancer_health_checks(api_client):
    response = api_client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert 'url=/studio/app' in response.text
