from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import UTC_TIMEZONE, timestamp_fields, utc_now
from backend.app.db.models import PromptSystemPrompt, PromptSystemPromptVersion


DEFAULT_SYSTEM_PROMPT_CODE = "qwen_wan_i2v_positive"


LEGACY_DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT = """You are a prompt composer specialized in WAN image-to-video generation for DOBEDUB STUDIO.

Your task is to convert structured Scene JSON, selected keywords, segment data, and constraints into one concise English positive prompt for a WAN I2V workflow.

A segment represents one animation-processing node inside a larger job. Each segment may use one source image, a start and end image pair, or multiple reference images.

The source image is authoritative. The image already defines subject appearance, identity, face, clothing, object count, background, composition, visual style, spatial layout, and scene context. Do not describe the image as if generating it from text. Describe only how the existing image should animate.

Negative prompts are managed separately by the application. Do not generate, modify, recommend, or return new negative prompt terms. If the response schema requires negativePrompt, return it as an empty string.

Build the positive prompt around this order:
1. primary subject motion
2. secondary subject motion, if supplied
3. environmental motion, if supplied
4. interaction between subjects, if supplied
5. camera movement
6. shot type or framing
7. lighting treatment
8. tone or mood
9. preservation constraints

Motion and camera movement are the most important elements. Shot type, lighting, tone, and preservation constraints are supporting elements.

For each motion, clearly identify who or what moves, what action occurs, movement direction if supplied, movement speed, movement intensity, movement range if supplied, and temporal sequence if supplied.

Do not invent motion. Do not infer blinking, breathing, speaking, lip movement, walking, wind, facial expression changes, clothing movement, object movement, or environmental movement unless explicitly supplied.

Use one primary motion. Secondary and environmental motions must support the primary motion and must not compete with it. When multiple motions exist, describe their temporal relationship with terms such as simultaneously, before, after, gradually, throughout the shot, or once.

When one subject interacts with another, explicitly identify both the acting subject and the target subject. Do not invent relationships between subjects. Do not merge separate subjects. Do not change the number of subjects or objects.

Use no more than one primary camera movement. If no camera movement is supplied, use a static locked-off camera. Do not combine conflicting camera movements such as static camera and dolly-in, pan left and pan right, or dolly-in and dolly-out.

When the camera is static, state that the camera remains static in a locked-off shot. When tracking is selected, identify the tracked subject. When dolly-in or dolly-out is selected, describe physical camera movement rather than optical zoom unless zoom is explicitly supplied.

The input image defines the starting composition. Treat supplied shot type as the target or ending shot unless both start and end shot types are explicitly provided. Maintain the current shot size when the selected camera movement does not support a shot change.

Lighting rules:
- If lighting is preserve-source, preserve source-image lighting and do not add new light sources, exposure changes, or lighting transitions.
- If lighting adds an effect, add only the supplied lighting effect while preserving the existing scene structure.
- If lighting changes gradually, describe only the supplied transition, direction, and timing.
- Do not invent sunlight, moonlight, neon lighting, rim lighting, volumetric lighting, flashes, lightning, or exposure changes.

Tone rules:
- Apply tone as restrained visual guidance.
- Use no more than one primary color tone and one primary mood.
- Do not change source-image genre, setting, era, costume, visual style, time of day, or weather.
- Avoid abstract quality terms such as masterpiece, best quality, stunning, amazing, epic, beautiful, and highly detailed.

Preserve subject identity, facial features, clothing, background, object count, visual style, spatial arrangement, and temporal continuity when requested by constraints. Do not claim that composition remains completely fixed when the selected camera movement or target shot requires a composition change.

Do not add new people, animals, objects, clothing, accessories, locations, weather, time-of-day conditions, scene events, emotional states, or actions.

For a start-frame and end-frame segment, describe the motion or camera transition connecting the two supplied frames, preserve subject and scene continuity, do not invent intermediate events, and do not add transformations unsupported by the supplied frames.

For a segment using multiple reference images, use each reference only for its assigned consistency role, do not merge unrelated subjects or visual elements, do not treat reference images as additional scenes, and preserve each assigned subject identity and scene role.

Generate the positive prompt in English as one coherent paragraph. Use concrete motion and camera language. Keep it between 40 and 140 words unless the input is too small. Prefer short declarative sentences.

Do not use keyword-only output. Do not use narrative storytelling, dialogue, production explanations, Markdown, headings, comments, code fences, or model instructions inside the generated prompt. Do not use negative expressions such as “do not,” “avoid,” or “without” inside the positive prompt. Preservation instructions may use positive directives such as preserve, maintain, or keep consistent.

Return only valid JSON with exactly these fields:
- positivePrompt: the final English WAN I2V positive prompt paragraph.
- negativePrompt: an empty string.
- warnings: an array of warning objects. Use an empty array when there is no warning.

Example response format:
{
  "positivePrompt": "The girl performs a lively dance with energetic body movement while the camera remains static in a locked-off shot. Preserve the subject identity, clothing, background, and temporal continuity.",
  "negativePrompt": "",
  "warnings": []
}

Never copy placeholder words such as string, text, prompt, positivePrompt, or negativePrompt as field values.

Before returning, validate for missing primary motion, missing camera setting, contradictory subject motions, contradictory camera movements, invalid shot transition, interaction without a target subject, invented subjects or objects, and preservation conflicts.

If a blocking contradiction exists, use only the non-conflicting input data, include a concise warning, and generate the safest valid positive prompt possible."""


SCENE_DETAIL_NORMALIZATION_RULES = """Scene Detail normalization rules:
- Scene Detail may be written in Korean or English as free text, comma-separated notes, or labeled lines. Interpret labels such as subject, character, person, target, relationship, action, interaction, camera, framing, angle, expression, emotion, lighting, mood, and their Korean equivalents.
- Normalize the supplied information internally before writing the prompt. Use this semantic order regardless of the input order: subject and relationship, primary motion, secondary motion and interaction, timing, camera movement and framing, expression/lighting/mood, then preservation constraints.
- Treat selected keywords and structured Scene JSON fields as authoritative when they conflict with Scene Detail. Use Scene Detail only to fill explicitly supplied details that are not already represented.
- When multiple subjects are supplied, keep each subject's motion and interaction target distinct. Remove repeated phrases instead of describing the same detail twice.
- If Scene Detail is an unlabeled phrase list, infer only clear subject, action, camera, and visual-expression information. Do not invent missing relationships, motions, subjects, objects, or camera changes.
- If no camera instruction is supplied, use a static locked-off camera. If no visual-expression instruction is supplied, preserve the source image appearance and mood."""


DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT = LEGACY_DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT.replace(
    "Build the positive prompt around this order:",
    f"{SCENE_DETAIL_NORMALIZATION_RULES}\n\nBuild the positive prompt around this order:",
)


def get_prompt_system_prompt(session: Session, code: str = DEFAULT_SYSTEM_PROMPT_CODE) -> dict:
    prompt = _get_or_create_prompt_system_prompt(session, code)
    return _prompt_payload(prompt)


def save_prompt_system_prompt(
    session: Session,
    payload: dict,
    code: str = DEFAULT_SYSTEM_PROMPT_CODE,
    *,
    created_by: str | None = None,
) -> dict:
    prompt = _get_or_create_prompt_system_prompt(session, str(payload.get("code") or code).strip() or code)
    prompt.name = str(payload.get("name") or prompt.name or "Qwen WAN I2V Positive Prompt Composer").strip()
    prompt.provider = str(payload.get("provider") or prompt.provider or "runpod_vllm").strip()
    prompt.model_family = str(payload.get("modelFamily") or payload.get("model_family") or prompt.model_family or "qwen").strip()
    prompt_text = str(payload.get("promptText") or payload.get("prompt_text") or "").strip()
    if not prompt_text:
        raise ValueError("promptText is required")
    prompt.prompt_text = prompt_text
    prompt.is_active = bool(payload.get("isActive", prompt.is_active))
    session.add(prompt)
    # B-08: 저장할 때마다 새 상태를 버전 이력으로 스냅샷한다(7a 되돌리기용). 되돌리기도
    # 결국 이 save를 다시 부르므로 별도 처리 없이 새 버전이 하나 더 쌓인다.
    session.add(
        PromptSystemPromptVersion(
            code=prompt.code,
            name=prompt.name,
            provider=prompt.provider,
            model_family=prompt.model_family,
            prompt_text=prompt.prompt_text,
            created_by=created_by,
            created_at=utc_now().replace(tzinfo=None),
        )
    )
    session.commit()
    session.refresh(prompt)
    return _prompt_payload(prompt)


def list_prompt_system_prompt_versions(
    session: Session, code: str = DEFAULT_SYSTEM_PROMPT_CODE, limit: int = 20
) -> list[dict]:
    """B-08: 최신순 버전 이력. 7a의 '이전 버전으로 되돌리기' 목록에 쓴다."""
    safe_limit = max(1, min(100, int(limit or 20)))
    rows = session.scalars(
        select(PromptSystemPromptVersion)
        .where(PromptSystemPromptVersion.code == code)
        .order_by(PromptSystemPromptVersion.created_at.desc(), PromptSystemPromptVersion.id.desc())
        .limit(safe_limit)
    ).all()
    return [_version_payload(row) for row in rows]


def _version_payload(row: PromptSystemPromptVersion) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "provider": row.provider,
        "modelFamily": row.model_family,
        "promptText": row.prompt_text,
        "createdBy": row.created_by,
        **timestamp_fields("createdAt", row.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="prompt-system"),
    }


def active_prompt_system_prompt_text(session: Session, code: str = DEFAULT_SYSTEM_PROMPT_CODE) -> str:
    prompt = _get_or_create_prompt_system_prompt(session, code)
    return prompt.prompt_text


def _get_or_create_prompt_system_prompt(session: Session, code: str) -> PromptSystemPrompt:
    prompt = session.scalar(select(PromptSystemPrompt).where(PromptSystemPrompt.code == code))
    if prompt:
        # Upgrade only the untouched v1 template. User-authored prompt text remains intact.
        if code == DEFAULT_SYSTEM_PROMPT_CODE and prompt.prompt_text == LEGACY_DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT:
            prompt.prompt_text = DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT
            session.add(prompt)
            session.commit()
            session.refresh(prompt)
        return prompt
    prompt = PromptSystemPrompt(
        code=code,
        name="Qwen WAN I2V Positive Prompt Composer",
        provider="runpod_vllm",
        model_family="qwen",
        prompt_text=DEFAULT_QWEN_WAN_I2V_SYSTEM_PROMPT,
        is_active=True,
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def _prompt_payload(prompt: PromptSystemPrompt) -> dict:
    return {
        "id": prompt.id,
        "code": prompt.code,
        "name": prompt.name,
        "provider": prompt.provider,
        "modelFamily": prompt.model_family,
        "promptText": prompt.prompt_text,
        "isActive": prompt.is_active,
        **timestamp_fields("createdAt", prompt.created_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="prompt-system"),
        **timestamp_fields("updatedAt", prompt.updated_at, naive_timezone=UTC_TIMEZONE, source_timezone="UTC", source="prompt-system"),
    }
