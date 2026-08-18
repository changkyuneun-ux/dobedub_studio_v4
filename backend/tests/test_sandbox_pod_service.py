from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.services.sandbox_pod_service import _lifecycle_event_timestamp, _present_pod, _runtime_metrics
from backend.app.core.timezone_utils import UTC_TIMEZONE


class SandboxPodLifecycleTimestampTests(unittest.TestCase):
    def test_extracts_runpod_lifecycle_event_timestamp(self) -> None:
        value = "Rented by User: Fri Aug 07 2026 07:51:24 GMT+0000 (Coordinated Universal Time)"

        parsed = _lifecycle_event_timestamp(value)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, UTC_TIMEZONE)
        self.assertEqual(parsed.strftime("%Y-%m-%dT%H:%M:%SZ"), "2026-08-07T07:51:24Z")

    def test_keeps_unparseable_event_without_inventing_a_time(self) -> None:
        self.assertIsNone(_lifecycle_event_timestamp("Provisioning requested by provider"))

    @patch("backend.app.services.sandbox_pod_service._graphql_request")
    def test_returns_runtime_metrics_without_exposing_provider_response_shape(self, graphql_request: object) -> None:
        graphql_request.return_value = {
            "pod": {
                "runtime": {
                    "uptimeInSeconds": 3661,
                    "container": {"cpuPercent": 12.8, "memoryPercent": 34.2},
                    "gpus": [{"id": "gpu-0", "gpuUtilPercent": 45.5, "memoryUtilPercent": 67.1}],
                }
            }
        }

        result = _runtime_metrics(
            Settings(sandbox_pod_api_key="test-key"),
            "pod-123",
            {"containerDiskInGb": 150, "volumeInGb": 1000, "networkVolumeId": "volume-1"},
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["uptimeSeconds"], 3661)
        self.assertEqual(result["cpuPercent"], 12.8)
        self.assertEqual(result["gpus"][0]["memoryUtilPercent"], 67.1)
        self.assertEqual(result["storage"]["networkVolumeId"], "volume-1")

    @patch("backend.app.services.sandbox_pod_service._runtime_metrics", return_value={"available": True, "gpus": []})
    @patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="READY")
    def test_presents_provider_times_and_lifecycle_event_separately(self, _: object, __: object) -> None:
        result = _present_pod(
            object(),
            {
                "id": "pod-123",
                "name": "sandbox",
                "desiredStatus": "RUNNING",
                "ports": ["8188/http", "8080/http", "8888/http", "22/tcp"],
                "lastStartedAt": "2026-08-07T07:51:24Z",
                "lastStatusChange": "Rented by User: Fri Aug 07 2026 07:51:24 GMT+0000 (Coordinated Universal Time)",
            },
            "template-id",
        )

        self.assertEqual(result["lastStartedAtUtc"], "2026-08-07T07:51:24Z")
        self.assertEqual(result["lastStartedAtKst"], "2026-08-07 16:51:24 KST")
        self.assertEqual(result["lastStatusChangeUtc"], "2026-08-07T07:51:24Z")
        self.assertEqual(result["lastLifecycleEvent"], "Rented by User: Fri Aug 07 2026 07:51:24 GMT+0000 (Coordinated Universal Time)")
        self.assertIsNotNone(result["checkedAtUtc"])
        self.assertEqual(result["httpServices"], [
            {"internalPort": 8188, "url": "https://pod-123-8188.proxy.runpod.net", "label": "ComfyUI"},
            {"internalPort": 8080, "url": "https://pod-123-8080.proxy.runpod.net", "label": "FileBrowser"},
            {"internalPort": 8888, "url": "https://pod-123-8888.proxy.runpod.net", "label": "JupyterLab"},
        ])


if __name__ == "__main__":
    unittest.main()
