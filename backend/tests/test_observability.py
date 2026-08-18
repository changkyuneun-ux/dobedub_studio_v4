from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import Response
from starlette.requests import Request

from backend.app.core.observability import (
    _request_emf_payload,
    add_timing,
    ensure_request_id,
    observe_response,
    operation_for_path,
    request_timing,
    server_timing_value,
)


def _request(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "headers": headers or [],
            "server": ("127.0.0.1", 8787),
        }
    )


class ObservabilityTests(unittest.TestCase):
    def test_only_target_routes_are_instrumented(self) -> None:
        self.assertEqual(operation_for_path("/api/assets"), "asset_list")
        self.assertEqual(operation_for_path("/api/files/asset_123"), "asset_file")
        self.assertEqual(operation_for_path("/manual"), "manual_html")
        self.assertEqual(operation_for_path("/docs/manual-assets/overview.png"), "manual_asset")
        self.assertIsNone(operation_for_path("/api/health"))

    def test_request_id_is_generated_for_invalid_client_value(self) -> None:
        request = _request("/api/assets", [(b"x-request-id", b"invalid space")])

        request_id = ensure_request_id(request)

        self.assertEqual(len(request_id), 32)
        self.assertEqual(request_id, ensure_request_id(request))

    def test_server_timing_includes_recorded_segments(self) -> None:
        request = _request("/api/assets")
        with request_timing(request, "db"):
            pass

        value = server_timing_value({**request.state.observation_timings, "app": 12.34})

        self.assertIn("db;dur=", value)
        self.assertIn("app;dur=12.3", value)

    def test_emf_dimensions_exclude_request_and_asset_identifiers(self) -> None:
        payload = _request_emf_payload(
            environment="production",
            operation="asset_file",
            request_id="request_12345678",
            status_code=206,
            timings={"auth": 2.5, "db": 4.0, "file_stat": 1.5, "app": 10.0},
            slow_request_ms=500,
            range_request=True,
        )

        metric_definition = payload["_aws"]["CloudWatchMetrics"][0]
        self.assertEqual(metric_definition["Dimensions"], [["Environment", "Operation", "StatusFamily"]])
        self.assertEqual(payload["AssetRangeRequestCount"], 1)
        self.assertEqual(payload["ApiErrorCount"], 0)

    def test_response_gets_server_timing_and_request_id(self) -> None:
        request = _request("/api/assets")
        response = Response()
        add_timing(request, "auth", 1.25)
        add_timing(request, "db", 3.5)

        with patch("backend.app.core.observability.OBSERVABILITY_LOGGER.info") as log_info:
            observe_response(request, response, 12.0)

        self.assertIn("auth;dur=1.2", response.headers["server-timing"])
        self.assertIn("db;dur=3.5", response.headers["server-timing"])
        self.assertIn("app;dur=12.0", response.headers["server-timing"])
        self.assertEqual(len(response.headers["x-request-id"]), 32)
        log_info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
