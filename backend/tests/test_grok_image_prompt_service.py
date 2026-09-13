from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.services.grok_image_prompt_service import (
    GrokPromptError,
    GrokPromptInputError,
    generate_image_prompt,
)


class GrokImagePromptServiceTests(unittest.TestCase):
    def _settings(self) -> Settings:
        return Settings(
            grok_enabled=True,
            grok_api_key="test-key",
            grok_model="grok-test",
            grok_max_retries=0,
        )

    @patch("backend.app.services.grok_image_prompt_service._json_request_with_retry")
    def test_image_request_disables_server_history_and_requires_structured_json(self, request_mock):
        request_mock.return_value = {
            "output_text": '{"positivePrompt":"A character breathes calmly, smooth movement.","imageType":"static_character","warnings":[]}'
        }
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"png-data")
            generate_image_prompt(
                self._settings(),
                asset_path=image_path,
                mime_type="image/png",
                file_name=image_path.name,
            )

        payload = request_mock.call_args.args[2]
        self.assertIs(payload["store"], False)
        text_format = payload["text"]["format"]
        self.assertEqual(text_format["type"], "json_schema")
        self.assertTrue(text_format["strict"])
        self.assertEqual(text_format["schema"]["required"], ["positivePrompt", "imageType", "warnings"])
        self.assertFalse(text_format["schema"]["additionalProperties"])
        image_input = payload["input"][1]["content"][1]
        self.assertEqual(image_input["detail"], "high")

    @patch("backend.app.services.grok_image_prompt_service.time.sleep")
    @patch("backend.app.services.grok_image_prompt_service._json_request")
    def test_retries_non_json_model_output(self, request_mock, sleep_mock):
        request_mock.side_effect = [
            {"output_text": "I cannot determine a prompt from this image."},
            {"output_text": '{"positivePrompt":"A character breathes calmly, smooth movement.","imageType":"static_character","warnings":[]}'},
        ]
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"png-data")
            result = generate_image_prompt(
                Settings(
                    grok_enabled=True,
                    grok_api_key="test-key",
                    grok_model="grok-test",
                    grok_max_retries=1,
                    grok_retry_backoff_seconds=2.0,
                ),
                asset_path=image_path,
                mime_type="image/png",
                file_name=image_path.name,
            )

        self.assertTrue(result.positive_prompt)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2.0)

    @patch("backend.app.services.grok_image_prompt_service.time.sleep")
    @patch("backend.app.services.grok_image_prompt_service._json_request")
    def test_retries_json_missing_positive_prompt(self, request_mock, sleep_mock):
        request_mock.side_effect = [
            {"output_text": '{"imageType":"static_character","warnings":[]}'},
            {"output_text": '{"positivePrompt":"A character breathes calmly, smooth movement.","imageType":"static_character","warnings":[]}'},
        ]
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"png-data")
            result = generate_image_prompt(
                Settings(
                    grok_enabled=True,
                    grok_api_key="test-key",
                    grok_model="grok-test",
                    grok_max_retries=1,
                    grok_retry_backoff_seconds=2.0,
                ),
                asset_path=image_path,
                mime_type="image/png",
                file_name=image_path.name,
            )

        self.assertTrue(result.positive_prompt)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2.0)

    def test_rejects_unsupported_image_format_before_network_request(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.webp"
            image_path.write_bytes(b"webp-data")
            with self.assertRaises(GrokPromptInputError):
                generate_image_prompt(
                    self._settings(),
                    asset_path=image_path,
                    mime_type="image/webp",
                    file_name=image_path.name,
                )

    @patch("backend.app.services.grok_image_prompt_service.time.sleep")
    @patch("backend.app.services.grok_image_prompt_service._json_request")
    def test_retries_temporary_upstream_failure(self, request_mock, sleep_mock):
        request_mock.side_effect = [
            GrokPromptError("temporarily unavailable", status_code=503, retryable=True),
            {"output_text": '{"positivePrompt":"A character breathes calmly, smooth movement.","imageType":"static_character","warnings":[]}'},
        ]
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"png-data")
            result = generate_image_prompt(
                Settings(
                    grok_enabled=True,
                    grok_api_key="test-key",
                    grok_model="grok-test",
                    grok_max_retries=1,
                    grok_retry_backoff_seconds=2.0,
                ),
                asset_path=image_path,
                mime_type="image/png",
                file_name=image_path.name,
            )

        self.assertTrue(result.positive_prompt)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2.0)


if __name__ == "__main__":
    unittest.main()
