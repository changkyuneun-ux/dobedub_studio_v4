from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.services.sandbox_pod_service import _lifecycle_event_timestamp, _present_pod
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

    @patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="READY")
    def test_presents_provider_times_and_lifecycle_event_separately(self, _: object) -> None:
        result = _present_pod(
            object(),
            {
                "id": "pod-123",
                "name": "sandbox",
                "desiredStatus": "RUNNING",
                "ports": ["8188/http"],
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


if __name__ == "__main__":
    unittest.main()
