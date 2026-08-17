from __future__ import annotations

import unittest

from fastapi import Response
from starlette.requests import Request

from backend.app.api.v1.auth import _set_asset_session_cookie


def _request(host: str, scheme: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": scheme,
            "path": "/api/auth/login",
            "headers": [(b"host", host.encode("ascii"))],
            "server": (host.split(":", 1)[0], 443 if scheme == "https" else 80),
        }
    )


class AssetSessionCookieTests(unittest.TestCase):
    def test_local_cookie_is_http_only_and_scoped_to_files(self) -> None:
        response = Response()

        _set_asset_session_cookie(response, "token", _request("127.0.0.1:8787", "http"))

        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Path=/api/files", cookie)
        self.assertNotIn("Secure", cookie)

    def test_public_cookie_requires_https(self) -> None:
        response = Response()

        _set_asset_session_cookie(response, "token", _request("studio.example.com", "https"))

        self.assertIn("Secure", response.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()
