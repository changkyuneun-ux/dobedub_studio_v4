from __future__ import annotations

from starlette.responses import Response

from backend.app.api.v1.assets import _content_disposition


def test_content_disposition_supports_korean_file_names():
    header = _content_disposition("inline", "제목 없음-45.jpg")

    response = Response(headers={"Content-Disposition": header})

    assert "filename*=utf-8''" in response.headers["content-disposition"]
    assert response.raw_headers
