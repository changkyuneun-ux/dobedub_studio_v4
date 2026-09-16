from __future__ import annotations


def test_root_returns_success_for_load_balancer_health_checks(api_client):
    response = api_client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert 'url=/studio/app' in response.text


def test_studio_pdfjs_cmaps_are_served_as_static_assets(api_client):
    response = api_client.get("/studio/pdfjs/cmaps/Adobe-Korea1-UCS2.bcmap")

    assert response.status_code == 200
    assert "text/html" not in response.headers.get("content-type", "")
    assert not response.content.startswith(b"<!doctype html")
