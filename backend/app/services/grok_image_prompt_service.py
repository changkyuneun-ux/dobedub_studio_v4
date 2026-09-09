"""Grok image understanding client for WAN I2V positive prompt drafts.

This client deliberately does not reuse the Qwen/RunPod prompt client. Grok
receives one uploaded image and returns only an editable positive prompt; the
application keeps the workflow's negative prompt as its own separate value.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings


INSTRUCTION_VERSION = "wan-i2v-grok-v1"
LOGGER = logging.getLogger(__name__)
_SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png"}
_SUPPORTED_IMAGE_TYPES = {"background", "indoor_background", "static_character", "dynamic_image"}
GROK_PROMPT_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["positivePrompt", "imageType", "warnings"],
    "properties": {
        "positivePrompt": {
            "type": "string",
            "description": "Concise English WAN image-to-video positive prompt. Empty only for indoor_background.",
            "maxLength": 2048,
        },
        "imageType": {
            "type": "string",
            "enum": ["background", "indoor_background", "static_character", "dynamic_image"],
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string", "maxLength": 256},
            "maxItems": 8,
        },
    },
}

SYSTEM_PROMPT = """You convert one uploaded webtoon or illustration image into a WAN2.2 image-to-video positive prompt.

The image is a source frame, not a text-to-image request. First classify it as exactly one of: background, indoor_background, static_character, dynamic_image. Use background when no person is the main subject. Use indoor_background when that background is primarily an interior. Use static_character when a person is the subject without visible action cues. Use dynamic_image only when an action is already visibly occurring through pose, motion lines, action trails, or similar evidence.

For indoor_background, do not generate a prompt. Return positivePrompt as an empty string and warnings containing manual_input_required. For outdoor background, describe only weather or environmental motion visibly supported by the source. For static_character, use one gentle idle motion and at most one related hair or clothing motion. For dynamic_image, use one already-visible action and one directly related secondary motion. Do not add people, objects, locations, weather, dialogue, transformations, sexual content, facial-mouth movement, camera movement, or actions not shown by the source. Do not re-list clothing, appearance, or background details that are already visible.

Every non-empty prompt must be concise English, use a locked camera, include exactly one compatible animated art-style phrase, and end with: smooth movement. Static and dynamic character prompts should be 50-90 words; outdoor background prompts should be 30-70 words. Keep any visible speech bubbles, sound-effect text, exclamation marks, or hard graphic lines unchanged, but do not animate them.

Return JSON only with exactly these keys: positivePrompt (string), imageType (one of background, indoor_background, static_character, dynamic_image), warnings (array of short strings). negativePrompt is managed by the application and must not be included."""


class GrokPromptError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class GrokPromptInputError(GrokPromptError):
    """A request that cannot be accepted without changing the input asset."""


@dataclass(frozen=True)
class GrokImagePromptResult:
    positive_prompt: str
    image_type: str
    warnings: list[str]
    raw_response: dict[str, Any]


def generate_image_prompt(
    settings: Settings,
    *,
    asset_path: Path | None = None,
    asset_bytes: bytes | None = None,
    mime_type: str,
    file_name: str,
    image_width: int | None = None,
    image_height: int | None = None,
    instruction_text: str = SYSTEM_PROMPT,
) -> GrokImagePromptResult:
    if not settings.grok_enabled:
        raise GrokPromptError("Grok image prompt generation is disabled. Set GROK_ENABLED=1.")
    if not settings.grok_api_key or settings.grok_api_key.startswith("your_"):
        raise GrokPromptError("GROK_API_KEY is not configured.")

    if asset_bytes is None:
        if asset_path is None or not asset_path.exists() or not asset_path.is_file():
            raise GrokPromptError("Uploaded image file is not available for Grok analysis.")
        raw = asset_path.read_bytes()
    else:
        raw = asset_bytes
    if len(raw) > settings.grok_max_image_bytes:
        raise GrokPromptError(
            f"Image is too large for Grok prompt generation ({len(raw)} bytes; limit {settings.grok_max_image_bytes} bytes)."
        )
    if not raw:
        raise GrokPromptError("Uploaded image file is empty.")

    resolved_mime = (mime_type or mimetypes.guess_type(file_name)[0] or "image/png").lower()
    if resolved_mime == "image/jpg":
        resolved_mime = "image/jpeg"
    if resolved_mime not in _SUPPORTED_IMAGE_MIME_TYPES:
        raise GrokPromptInputError(
            "Grok 이미지 분석은 PNG 또는 JPEG 입력만 지원합니다. 해당 형식으로 다시 업로드하세요."
        )
    data_url = f"data:{resolved_mime};base64,{base64.b64encode(raw).decode('ascii')}"
    dimensions = "unknown"
    if image_width and image_height:
        dimensions = f"W {image_width} x H {image_height}"
    user_text = (
        f"Analyze the attached source image for a WAN2.2 I2V draft. "
        f"Asset: {file_name}. Original dimensions: {dimensions}. "
        "Return the JSON object only."
    )
    payload = {
        "model": settings.grok_model,
        # xAI recommends disabling server-side history when the request contains
        # an image. Keeping image payload history can make a later request fail.
        "store": False,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": instruction_text or SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_text},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            },
        ],
        "temperature": settings.grok_temperature,
        "max_output_tokens": settings.grok_max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "wan_i2v_prompt_draft",
                "strict": True,
                "schema": GROK_PROMPT_RESPONSE_SCHEMA,
            },
        },
    }
    response = _json_request_with_retry(
        f"{settings.grok_base_url.rstrip('/')}/responses",
        settings.grok_api_key,
        payload,
        settings.grok_request_timeout_seconds,
        max_retries=settings.grok_max_retries,
        retry_backoff_seconds=settings.grok_retry_backoff_seconds,
    )
    parsed = _parse_output(response)
    image_type = str(parsed.get("imageType") or "").strip().lower()
    positive_prompt = str(parsed.get("positivePrompt") or "").strip()
    warnings = [str(item).strip() for item in parsed.get("warnings") or [] if str(item).strip()]
    return GrokImagePromptResult(
        positive_prompt=positive_prompt,
        image_type=image_type,
        warnings=warnings,
        raw_response=response,
    )


def _json_request_with_retry(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: int,
    *,
    max_retries: int,
    retry_backoff_seconds: float,
) -> dict[str, Any]:
    for attempt in range(max_retries + 1):
        try:
            response = _json_request(url, api_key, payload, timeout)
            _parse_output(response)
            return response
        except GrokPromptError as exc:
            if not exc.retryable or attempt >= max_retries:
                raise
            delay = retry_backoff_seconds * (2**attempt)
            LOGGER.warning(
                "Retrying Grok image prompt request after upstream failure: attempt=%s/%s status=%s delay_seconds=%.2f",
                attempt + 1,
                max_retries,
                exc.status_code,
                delay,
            )
            time.sleep(delay)
    raise AssertionError("Grok retry loop must return or raise")


def _json_request(url: str, api_key: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = response.read().decode("utf-8")
            value = json.loads(decoded)
            if not isinstance(value, dict):
                raise GrokPromptError("Grok API did not return a JSON object.")
            return value
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        request_id = str(exc.headers.get("x-request-id") or exc.headers.get("request-id") or "").strip()
        retryable = exc.code == 429 or exc.code >= 500
        LOGGER.warning(
            "Grok API rejected image prompt request: status=%s request_id=%s retryable=%s detail=%s",
            exc.code,
            request_id or "-",
            retryable,
            detail[:500],
        )
        request_suffix = f" (request id: {request_id})" if request_id else ""
        raise GrokPromptError(
            f"Grok API HTTP {exc.code}{request_suffix}: {detail[:500]}",
            status_code=exc.code,
            retryable=retryable,
        ) from exc
    except urllib.error.URLError as exc:
        LOGGER.warning("Grok image prompt request failed before a response: %s", exc.reason)
        raise GrokPromptError(f"Grok API request failed: {exc.reason}", retryable=True) from exc
    except TimeoutError as exc:
        LOGGER.warning("Grok image prompt request timed out after %s seconds", timeout)
        raise GrokPromptError("Grok API request timed out.", retryable=True) from exc
    except json.JSONDecodeError as exc:
        raise GrokPromptError("Grok API did not return valid JSON.") from exc


def _parse_output(response: dict[str, Any]) -> dict[str, Any]:
    text = str(response.get("output_text") or "").strip()
    if not text:
        text_parts: list[str] = []
        for output in response.get("output") or []:
            for content in output.get("content") or []:
                if content.get("type") in {"output_text", "text"}:
                    text_parts.append(str(content.get("text") or ""))
        text = "\n".join(part for part in text_parts if part).strip()
    if not text:
        raise GrokPromptError("Grok response did not contain text output.", retryable=True)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        matched = re.search(r"\{[\s\S]*\}", text)
        if not matched:
            raise GrokPromptError("Grok response did not contain a JSON object.", retryable=True)
        try:
            value = json.loads(matched.group(0))
        except json.JSONDecodeError as exc:
            raise GrokPromptError("Grok response JSON could not be parsed.", retryable=True) from exc
    if not isinstance(value, dict):
        raise GrokPromptError("Grok response JSON must be an object.", retryable=True)
    for key in ("positivePrompt", "imageType", "warnings"):
        if key not in value:
            raise GrokPromptError(f"Grok response did not contain {key}.", retryable=True)
    image_type = str(value.get("imageType") or "").strip().lower()
    if image_type not in _SUPPORTED_IMAGE_TYPES:
        raise GrokPromptError("Grok response did not contain a supported imageType.", retryable=True)
    if not isinstance(value.get("warnings"), list):
        raise GrokPromptError("Grok response warnings must be an array.", retryable=True)
    if not str(value.get("positivePrompt") or "").strip() and image_type != "indoor_background":
        raise GrokPromptError("Grok response did not contain positivePrompt.", retryable=True)
    return value
