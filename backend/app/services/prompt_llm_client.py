from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from backend.app.core.config import Settings
from backend.app.services.runpod_client import is_real_secret, mask_secret


@dataclass(frozen=True)
class PromptLLMResult:
    positive_prompt: str
    negative_prompt: str
    warnings: list[dict]
    raw_response: dict


class PromptLLMResponseError(RuntimeError):
    """A completed LLM job did not contain a valid prompt JSON payload."""


def prompt_llm_status(settings: Settings) -> dict:
    provider = (settings.prompt_llm_provider or "mock").strip().lower()
    api_key = _prompt_llm_api_key(settings)
    endpoint_id = _prompt_llm_endpoint_id(settings)
    endpoint_url = _prompt_llm_endpoint_url(settings)
    return {
        "provider": provider,
        "configured": provider == "mock" or bool(endpoint_url or endpoint_id),
        "endpointId": mask_secret(endpoint_id),
        "endpointUrl": _mask_endpoint_url(endpoint_url),
        "model": settings.prompt_llm_model,
        "runpodInputMode": settings.prompt_llm_runpod_input_mode,
        "timeout": settings.prompt_llm_timeout,
        "coldStartRetryDelaysSeconds": list(settings.prompt_llm_cold_start_retry_delays_seconds),
        "apiKeyConfigured": provider == "mock" or is_real_secret(api_key, "your_prompt_llm_api_key"),
    }


def generate_with_prompt_llm(
    settings: Settings,
    *,
    scene: dict,
    constraints: dict,
    language: str,
    system_prompt: str | None = None,
) -> PromptLLMResult:
    provider = (settings.prompt_llm_provider or "mock").strip().lower()
    if provider == "runpod_vllm":
        return _runpod_vllm_generate(settings, scene=scene, constraints=constraints, language=language, system_prompt=system_prompt)
    if provider in {"openai_compatible", "vllm_openai"}:
        return _openai_compatible_generate(settings, scene=scene, constraints=constraints, language=language, system_prompt=system_prompt)
    raise ValueError(f"Prompt LLM provider '{provider}' is not supported. Use mock, runpod_vllm, or openai_compatible.")


def _runpod_vllm_generate(
    settings: Settings,
    *,
    scene: dict,
    constraints: dict,
    language: str,
    system_prompt: str | None,
) -> PromptLLMResult:
    endpoint_url = _prompt_llm_endpoint_url(settings)
    if "/openai/" in endpoint_url:
        return _openai_compatible_generate(settings, scene=scene, constraints=constraints, language=language, system_prompt=system_prompt)

    url = _runpod_runsync_url(settings)
    payload = {"input": _runpod_vllm_input(settings, scene=scene, constraints=constraints, language=language, system_prompt=system_prompt)}
    headers = _auth_headers(_prompt_llm_api_key(settings))
    timeout = settings.prompt_llm_timeout

    def perform_request() -> dict:
        response = _json_request(
            url,
            headers,
            payload,
            timeout,
            retry_delays=settings.prompt_llm_cold_start_retry_delays_seconds,
        )
        status = str(response.get("status") or "").upper()
        if status and status not in {"COMPLETED", "SUCCEEDED", "SUCCESS"}:
            raise RuntimeError(f"RunPod vLLM prompt job did not complete: {status}")
        return response

    return _generate_with_parse_retry(
        perform_request=perform_request,
        extract_output=lambda response: response.get("output", response),
        scene=scene,
    )


def _openai_compatible_generate(
    settings: Settings,
    *,
    scene: dict,
    constraints: dict,
    language: str,
    system_prompt: str | None,
) -> PromptLLMResult:
    url = _openai_chat_completions_url(settings)
    payload = {
        "model": settings.prompt_llm_model or "default",
        "messages": _prompt_messages(scene, constraints, language, system_prompt),
        "temperature": settings.prompt_llm_temperature,
        "max_tokens": settings.prompt_llm_max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = _auth_headers(_prompt_llm_api_key(settings))
    timeout = settings.prompt_llm_timeout

    def perform_request() -> dict:
        return _json_request(
            url,
            headers,
            payload,
            timeout,
            retry_delays=settings.prompt_llm_cold_start_retry_delays_seconds,
        )

    # 2026-08-11: openai_compatible/vllm_openai 경로에 재시도가 없어 vLLM
    # 콜드스타트 직후 첫 응답이 placeholder/빈 값이면 즉시 502로 실패하고,
    # 사용자가 재요청(모델 워밍업 완료 후)해야 성공하는 것처럼 보이던 문제.
    # runpod_vllm 경로와 동일하게 파싱 실패 1회 재시도로 통일.
    return _generate_with_parse_retry(
        perform_request=perform_request,
        extract_output=lambda response: response,
        scene=scene,
    )


def _generate_with_parse_retry(
    *,
    perform_request: Callable[[], dict],
    extract_output: Callable[[dict], Any],
    scene: dict,
) -> PromptLLMResult:
    """Shared retry-on-parse-failure logic for all Prompt LLM providers.

    2026-08-11: 이전엔 runpod_vllm과 openai_compatible이 각자 재시도 로직을
    따로 구현해 openai_compatible만 재시도가 빠져 있는 비일관성이 생겼다
    (사용자 신고: 첫 generate_prompt 요청은 실패, 두 번째는 성공). 공통
    헬퍼로 합쳐 앞으로도 같은 방식으로 어긋나지 않게 한다.
    """
    responses: list[dict] = []
    parse_error: PromptLLMResponseError | None = None
    for attempt in range(2):
        response = perform_request()
        responses.append(response)
        try:
            result = _parse_prompt_llm_output(extract_output(response), raw_response=response, scene=scene)
        except PromptLLMResponseError as exc:
            parse_error = exc
            continue
        if attempt == 0:
            return result
        return PromptLLMResult(
            positive_prompt=result.positive_prompt,
            negative_prompt=result.negative_prompt,
            warnings=[
                *result.warnings,
                {
                    "code": "llm_response_retry_succeeded",
                    "message": "The initial Prompt LLM response was not valid JSON, so the request was retried once successfully.",
                    "severity": "warning",
                },
            ],
            raw_response={"attempts": responses, "selectedAttempt": attempt + 1},
        )
    raise RuntimeError(f"Prompt LLM returned an invalid response after one retry: {parse_error}")


def _prompt_messages(scene: dict, constraints: dict, language: str, system_prompt: str | None = None) -> list[dict]:
    return [
        {
            "role": "system",
            "content": system_prompt or (
                "You generate concise WAN image-to-video prompts. "
                "Return only valid JSON with keys positivePrompt, negativePrompt, warnings. "
                "positivePrompt must be one complete natural English sentence describing the video motion, subject, style, and camera. "
                "negativePrompt must be concise English comma-separated negative terms. "
                "warnings must be an array of objects with code, message, severity. "
                "Preserve subject identity and avoid adding unrequested objects."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Generate positive and negative prompts for WAN image-to-video.",
                    "language": language,
                    "scene": scene,
                    "constraints": constraints,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def _runpod_vllm_input(
    settings: Settings,
    *,
    scene: dict,
    constraints: dict,
    language: str,
    system_prompt: str | None,
) -> dict:
    mode = settings.prompt_llm_runpod_input_mode
    if mode == "messages":
        return {
            "messages": _prompt_messages(scene, constraints, language, system_prompt),
            "sampling_params": _sampling_params(settings),
            "model": settings.prompt_llm_model or None,
            "response_format": {"type": "json_object"},
        }
    return {
        "prompt": _prompt_text(scene, constraints, language, system_prompt),
        "sampling_params": _sampling_params(settings),
        "model": settings.prompt_llm_model or None,
    }


def _prompt_text(scene: dict, constraints: dict, language: str, system_prompt: str | None = None) -> str:
    system_prompt_text = system_prompt or (
        "Generate concise WAN image-to-video prompts.\n"
        "Return only valid JSON with keys positivePrompt, negativePrompt, warnings.\n"
        "positivePrompt must be one complete natural English sentence describing the video motion, subject, style, and camera.\n"
        "negativePrompt must be concise English comma-separated negative terms.\n"
        "warnings must be an array of objects with code, message, severity.\n"
        "Preserve subject identity and avoid adding unrequested objects."
    )
    return (
        f"{system_prompt_text}\n\n"
        f"Language: {language}\n"
        f"Scene JSON:\n{json.dumps(scene, ensure_ascii=False, sort_keys=True)}\n\n"
        f"Constraints JSON:\n{json.dumps(constraints, ensure_ascii=False, sort_keys=True)}"
    )


def _sampling_params(settings: Settings) -> dict:
    return {
        "temperature": settings.prompt_llm_temperature,
        "max_tokens": settings.prompt_llm_max_tokens,
    }


# 2026-08-11: 사용자 신고 - generate_prompt 첫 요청이 502 Bad Gateway로 실패하고
# 재요청하면 대부분 성공한다(매우 간헐적). 원인 확인: RunPod 서버리스 워커가 0에서
# 스케일업되는 콜드 스타트 구간에는 게이트웨이가 워커를 기다리지 않고 즉시
# 502/503/504를 반환하는 경우가 있고, 몇 초 뒤 같은 요청을 다시 보내면 워커가 이미
# 떠 있어 성공한다. 이전엔 이 계층(urllib HTTPError/URLError)에서 곧장
# RuntimeError를 던졌고, prompts.py가 RuntimeError를 그대로 502로 변환해 사용자에게
# 전달했다(재시도 없음) - _generate_with_parse_retry의 재시도는 "정상 응답을 받았지만
# JSON 파싱에 실패한" 경우에만 동작해 이 상황을 커버하지 못했다. 여기서 502/503/504와
# 연결 계열 오류(URLError)에 한해 짧은 대기 후 재시도한다 - 실제 오류(401/403/400
# 등 설정 문제)는 재시도해도 계속 실패할 뿐이므로 재시도 대상에서 제외.
#
# 2026-08-12: RunPod Serverless Qwen의 첫 요청은 콜드 스타트 동안 502/503/504를
# 반환할 수 있다. 재시도 간격은 환경변수로 관리하며 기본값은 5,10,20,30,30초다.
# 실제 설정 오류(400/401/403)는 즉시 노출한다. TimeoutError는 한 요청이 이미 전체
# timeout을 사용한 경우이므로 한 번만 재시도한다.
_RETRYABLE_HTTP_STATUS = {502, 503, 504}
_TIMEOUT_RETRY_ATTEMPTS = 2


def _json_request(
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout: int,
    *,
    retry_delays: tuple[int, ...],
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    attempts = max(len(retry_delays) + 1, _TIMEOUT_RETRY_ATTEMPTS)
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            if attempt < _TIMEOUT_RETRY_ATTEMPTS - 1 and retry_delays:
                time.sleep(retry_delays[0])
                continue
            raise RuntimeError(f"Prompt LLM request timed out after {timeout} seconds.") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in _RETRYABLE_HTTP_STATUS and attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
                continue
            raise RuntimeError(f"Prompt LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            if attempt < len(retry_delays):
                time.sleep(retry_delays[attempt])
                continue
            raise RuntimeError(f"Prompt LLM request failed: {exc.reason}") from exc
    raise RuntimeError("Prompt LLM request failed after retry.")


def _auth_headers(api_key: str) -> dict[str, str]:
    if not is_real_secret(api_key, "your_prompt_llm_api_key"):
        raise ValueError("PROMPT_LLM_API_KEY or RUNPOD_API_KEY is required for actual prompt LLM generation.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _runpod_runsync_url(settings: Settings) -> str:
    endpoint_url = _prompt_llm_endpoint_url(settings)
    if endpoint_url:
        if endpoint_url.endswith("/runsync"):
            return endpoint_url
        return f"{endpoint_url.rstrip('/')}/runsync"
    endpoint_id = _prompt_llm_endpoint_id(settings)
    if not endpoint_id:
        raise ValueError("PROMPT_LLM_ENDPOINT_ID or PROMPT_LLM_ENDPOINT_URL is required for runpod_vllm provider.")
    return f"{settings.runpod_base_url.rstrip('/')}/{endpoint_id}/runsync"


def _openai_chat_completions_url(settings: Settings) -> str:
    endpoint_url = _prompt_llm_endpoint_url(settings)
    endpoint_id = _prompt_llm_endpoint_id(settings)
    if not endpoint_url and endpoint_id:
        endpoint_url = f"{settings.runpod_base_url.rstrip('/')}/{endpoint_id}/openai/v1"
    if not endpoint_url:
        raise ValueError("PROMPT_LLM_ENDPOINT_URL or PROMPT_LLM_ENDPOINT_ID is required for openai_compatible provider.")
    endpoint_url = endpoint_url.rstrip("/")
    if endpoint_url.endswith("/chat/completions"):
        return endpoint_url
    return f"{endpoint_url}/chat/completions"


def _parse_prompt_llm_output(output: Any, *, raw_response: dict, scene: dict | None = None) -> PromptLLMResult:
    content = _extract_content(output)
    parsed = _load_json_object(content)
    if not _first_text(parsed, "positivePrompt", "positive_prompt", "positive") and isinstance(parsed.get("choices"), list):
        nested_content = _extract_content(parsed)
        if nested_content and nested_content != content:
            content = nested_content
            parsed = _load_json_object(content)
    positive = _first_text(parsed, "positivePrompt", "positive_prompt", "positive")
    negative = _first_text(parsed, "negativePrompt", "negative_prompt", "negative")
    negative_key_present = any(key in parsed for key in ("negativePrompt", "negative_prompt", "negative"))
    positive_placeholder = _is_placeholder_positive_prompt(positive)
    if not positive or positive_placeholder:
        reason = "placeholder positivePrompt" if positive_placeholder else "missing positivePrompt"
        raise PromptLLMResponseError(f"Prompt LLM response has {reason}; a valid JSON prompt payload is required.")
    positive = _normalize_positive_sentence(positive)
    if not negative and not negative_key_present:
        negative = ""
    warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
    warnings = _normalize_warnings(warnings)
    return PromptLLMResult(
        positive_prompt=positive,
        negative_prompt=negative,
        warnings=warnings,
        raw_response=raw_response,
    )


def _extract_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _extract_content(value[0])
    if not isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    choices = value.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        if isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(first.get("text"), str):
            return first["text"]
        tokens = first.get("tokens")
        if isinstance(tokens, list):
            return "".join(str(token) for token in tokens)
    for key in ("content", "text", "response", "generated_text", "output"):
        item = value.get(key)
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return _extract_content(item)
    return json.dumps(value, ensure_ascii=False)


def _load_json_object(text: str) -> dict:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        candidates = _json_object_candidates(cleaned)
        if not candidates:
            return {}
        # The worker may echo input/example JSON before its final completion.
        # The last complete, non-placeholder prompt object is authoritative.
        parsed = next(
            (
                candidate
                for candidate in reversed(candidates)
                if _first_text(candidate, "positivePrompt", "positive_prompt", "positive")
                and not _is_placeholder_positive_prompt(_first_text(candidate, "positivePrompt", "positive_prompt", "positive"))
            ),
            {},
        )
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _json_object_candidates(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    return candidates


def _fallback_positive_prompt(text: str, *, scene: dict | None = None) -> str:
    scene_fallback = _fallback_positive_prompt_from_scene(scene)
    if scene_fallback:
        return scene_fallback
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned[:1200] or "cinematic image-to-video shot, subtle natural motion, stable camera, coherent frames"


def _fallback_positive_prompt_from_scene(scene: dict | None) -> str:
    if not isinstance(scene, dict):
        return ""
    scenes = scene.get("scenes")
    scene_item = scenes[0] if isinstance(scenes, list) and scenes and isinstance(scenes[0], dict) else {}
    summary = str(scene_item.get("summary") or "").strip()
    description = str(scene_item.get("description") or "").strip()
    parts = _dedupe_text_parts(re.split(r"[,;]", description or summary))
    if not parts:
        return ""
    return _normalize_positive_sentence(", ".join(parts))


def _is_placeholder_positive_prompt(value: str) -> bool:
    cleaned = " ".join(str(value or "").split()).strip(" .,:;\"'`").lower()
    return cleaned in {
        "string",
        "positiveprompt",
        "positive prompt",
        "positive prompt string",
        "your positive prompt",
        "generated positive prompt",
        "one coherent paragraph",
    }


def _normalize_warnings(warnings: list[Any]) -> list[dict]:
    normalized: list[dict] = []
    for index, warning in enumerate(warnings):
        if isinstance(warning, dict):
            normalized.append(warning)
        elif str(warning).strip() and str(warning).strip().lower() != "string":
            normalized.append({
                "code": f"llm_warning_{index + 1}",
                "message": str(warning).strip(),
                "severity": "warning",
            })
    return normalized


def _normalize_positive_sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip(" ,;")
    if not cleaned:
        return "A cinematic image-to-video shot shows the subject with subtle natural motion, stable camera movement, and coherent frames."
    if re.search(r"[.!?]$", cleaned) and len(cleaned.split()) >= 6:
        return cleaned
    parts = _dedupe_text_parts(re.split(r"[,;]", cleaned))
    if len(parts) <= 1:
        return cleaned if re.search(r"[.!?]$", cleaned) else f"{cleaned}."
    subject = parts[0]
    details = _join_sentence_parts(parts[1:])
    subject_sentence = _subject_as_sentence_lead(subject)
    if details:
        return f"{subject_sentence} with {details}."
    return f"{subject_sentence}."


def _subject_as_sentence_lead(subject: str) -> str:
    value = subject.strip(" ,.;")
    lower = value.lower()
    match = re.match(r"^(girl|boy|woman|man|person|character|subject|product|object)\b\s*(.*)$", value, flags=re.IGNORECASE)
    if match:
        noun = match.group(1).lower()
        tail = match.group(2).strip()
        article = "an" if noun[0] in "aeiou" else "a"
        if noun in {"person", "character", "subject", "product", "object"}:
            article = "the"
        if tail:
            return f"{article.capitalize()} {noun} is shown {tail}"
        return f"{article.capitalize()} {noun} is shown"
    if lower.startswith(("a ", "an ", "the ")):
        return f"{value[0].upper()}{value[1:]} is shown"
    return f"A {value} is shown"


def _join_sentence_parts(parts: list[str]) -> str:
    cleaned = _dedupe_text_parts(parts)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _dedupe_text_parts(parts: list[str]) -> list[str]:
    seen = set()
    result = []
    for part in parts:
        cleaned = " ".join(str(part or "").split()).strip(" ,.;")
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result[:12]


def _first_text(source: dict, *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
    return ""


def _prompt_llm_api_key(settings: Settings) -> str:
    return settings.prompt_llm_api_key or settings.runpod_api_key


def _prompt_llm_endpoint_id(settings: Settings) -> str:
    return settings.prompt_llm_endpoint_id


def _prompt_llm_endpoint_url(settings: Settings) -> str:
    return settings.prompt_llm_endpoint_url.strip().rstrip("/")


def _mask_endpoint_url(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"/v2/([^/]+)", lambda match: f"/v2/{mask_secret(match.group(1))}", url)
