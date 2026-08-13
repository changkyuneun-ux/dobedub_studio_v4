from __future__ import annotations

import json
import uuid
from datetime import datetime
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - requirements installs jsonschema for runtime.
    Draft202012Validator = None

from backend.app.core.config import get_settings
from backend.app.db.models import (
    ModelProfile,
    PromptFeedback,
    PromptCategoryGroup,
    PromptGenerationOutput,
    PromptGenerationRequest,
    PromptRule,
    PromptScope,
    PromptSubcategory,
    PromptSubcategoryKeyword,
    PromptTemplate,
    PromptTerm,
    PromptTermRelation,
    PromptTermRendering,
    WorkflowTask,
)
from backend.app.services.prompt_llm_client import (
    RUNPOD_TERMINAL_STATES,
    cancel_runpod_vllm_job,
    generate_with_prompt_llm,
    get_runpod_vllm_job_status,
    parse_runpod_vllm_job_result,
    submit_runpod_vllm_job,
    uses_async_runpod_vllm,
)
from backend.app.services.prompt_system_prompt_service import active_prompt_system_prompt_text


SCENE_JSON_V1_SCHEMA_PATH = "schemas/scene-json-v1.schema.json"
FIXED_PROMPT_ROOT_CODES = {"POSITIVE_ROOT", "NEGATIVE_ROOT"}

PROMPT_SCOPE_SEED = {
    "POSITIVE": {"nameKo": "Positive", "nameEn": "Positive", "sortOrder": 1},
    "NEGATIVE": {"nameKo": "Negative", "nameEn": "Negative", "sortOrder": 2},
}

PROMPT_GROUP_LABELS = {
    "positive_work_style": ("작품/스타일", "Work / Style"),
    "positive_subject": ("인물/대상", "Subject"),
    "positive_appearance": ("외형/속성", "Appearance"),
    "positive_action_motion": ("동작/움직임", "Action / Motion"),
    "positive_expression_emotion": ("표정/감정", "Expression / Emotion"),
    "positive_scene_background": ("장면/배경", "Scene / Background"),
    "positive_camera_composition": ("카메라/구도", "Camera / Composition"),
    "positive_light_color": ("조명/색감", "Light / Color"),
    "positive_quality_render": ("품질/렌더링", "Quality / Rendering"),
    "negative_quality": ("품질 저하", "Negative Quality"),
    "negative_distortion": ("왜곡/변형", "Distortion"),
    "negative_identity": ("정체성 훼손", "Identity Drift"),
    "negative_motion": ("움직임 오류", "Motion Error"),
    "negative_text_watermark": ("텍스트/워터마크", "Text / Watermark"),
    "negative_camera": ("카메라 오류", "Camera Error"),
    "negative_exclusion": ("금지/제외 요소", "Exclusion"),
}

PROMPT_GROUP_ORDER = list(PROMPT_GROUP_LABELS.keys())


EXAMPLE_PROMPT_CATALOG = {
    "categories": [
        {"code": "POSITIVE_ROOT", "groupCode": "prompt_scope", "nameKo": "Positive", "nameEn": "Positive", "scopeType": "GLOBAL", "selectionType": "MULTIPLE", "maxSelectCount": None, "sortOrder": 1},
        {"code": "NEGATIVE_ROOT", "groupCode": "prompt_scope", "nameKo": "Negative", "nameEn": "Negative", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": None, "sortOrder": 2},
        {"code": "GENRE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_work_style", "nameKo": "장르", "nameEn": "Genre", "scopeType": "GLOBAL", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 10},
        {"code": "CONTENT_RATING", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_work_style", "nameKo": "콘텐츠 등급", "nameEn": "Content Rating", "scopeType": "GLOBAL", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 20},
        {"code": "SUBJECT_TYPE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_subject", "nameKo": "대상 유형", "nameEn": "Subject Type", "scopeType": "SCENE", "selectionType": "SINGLE", "required": True, "maxSelectCount": 1, "sortOrder": 30},
        {"code": "CHARACTER_APPEARANCE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_appearance", "nameKo": "인물/대상 외형", "nameEn": "Appearance", "scopeType": "ENTITY", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 40},
        {"code": "CHARACTER_ACTION", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_action_motion", "nameKo": "인물/대상 동작", "nameEn": "Character Action", "scopeType": "ENTITY", "selectionType": "MULTIPLE", "maxSelectCount": 6, "sortOrder": 50},
        {"code": "CAMERA_MOVEMENT", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_camera_composition", "nameKo": "카메라 움직임", "nameEn": "Camera Movement", "scopeType": "SCENE", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 60},
        {"code": "CAMERA_FRAMING", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_camera_composition", "nameKo": "프레이밍", "nameEn": "Camera Framing", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 70},
        {"code": "BACKGROUND", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_scene_background", "nameKo": "배경", "nameEn": "Background", "scopeType": "SCENE", "selectionType": "MULTIPLE", "maxSelectCount": 4, "sortOrder": 80},
        {"code": "TIME_OF_DAY", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_scene_background", "nameKo": "시간대", "nameEn": "Time of Day", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 90},
        {"code": "WEATHER", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_scene_background", "nameKo": "날씨/환경", "nameEn": "Weather", "scopeType": "SCENE", "selectionType": "MULTIPLE", "maxSelectCount": 2, "sortOrder": 100},
        {"code": "LIGHTING", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_light_color", "nameKo": "조명", "nameEn": "Lighting", "scopeType": "SCENE", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 110},
        {"code": "COLOR_PALETTE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_light_color", "nameKo": "색감", "nameEn": "Color Palette", "scopeType": "SCENE", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 120},
        {"code": "VIDEO_MOOD", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_light_color", "nameKo": "분위기", "nameEn": "Mood", "scopeType": "SCENE", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 130},
        {"code": "QUALITY_TAG", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_quality_render", "nameKo": "품질", "nameEn": "Quality", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 4, "sortOrder": 140},
        {"code": "NEGATIVE_ANATOMY", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_distortion", "nameKo": "인체/형태 제한", "nameEn": "Negative Anatomy", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 150},
        {"code": "NEGATIVE_ARTIFACT", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_text_watermark", "nameKo": "아티팩트 제한", "nameEn": "Negative Artifact", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 160},
        {"code": "NEGATIVE_TEMPORAL", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_motion", "nameKo": "시간/움직임 제한", "nameEn": "Negative Temporal", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 170},
        {"code": "OBJECT_ACTION", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_action_motion", "nameKo": "객체 동작", "nameEn": "Object Action", "scopeType": "ENTITY", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 180},
        {"code": "MOTION_SPEED", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_action_motion", "nameKo": "움직임 속도", "nameEn": "Motion Speed", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 190},
        {"code": "MOTION_INTENSITY", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_action_motion", "nameKo": "움직임 강도", "nameEn": "Motion Intensity", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 200},
        {"code": "CAMERA_ANGLE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_camera_composition", "nameKo": "카메라 각도", "nameEn": "Camera Angle", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 210},
        {"code": "LENS_TYPE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_camera_composition", "nameKo": "렌즈", "nameEn": "Lens Type", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 220},
        {"code": "FOCUS_STYLE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_camera_composition", "nameKo": "초점", "nameEn": "Focus Style", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 230},
        {"code": "CLOTHING", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_appearance", "nameKo": "의상", "nameEn": "Clothing", "scopeType": "ENTITY", "selectionType": "MULTIPLE", "maxSelectCount": 4, "sortOrder": 240},
        {"code": "POSE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_appearance", "nameKo": "포즈", "nameEn": "Pose", "scopeType": "ENTITY", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 250},
        {"code": "GAZE_DIRECTION", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_appearance", "nameKo": "시선", "nameEn": "Gaze Direction", "scopeType": "ENTITY", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 260},
        {"code": "FACIAL_EXPRESSION", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_expression_emotion", "nameKo": "표정", "nameEn": "Facial Expression", "scopeType": "ENTITY", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 270},
        {"code": "EMOTION", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_expression_emotion", "nameKo": "감정", "nameEn": "Emotion", "scopeType": "ENTITY", "selectionType": "MULTIPLE", "maxSelectCount": 3, "sortOrder": 280},
        {"code": "ANIMATION_STYLE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_work_style", "nameKo": "애니메이션 스타일", "nameEn": "Animation Style", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 290},
        {"code": "RENDERING_STYLE", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_quality_render", "nameKo": "렌더링 스타일", "nameEn": "Rendering Style", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 300},
        {"code": "SCENE_TRANSITION", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_work_style", "nameKo": "장면 전환", "nameEn": "Scene Transition", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 310},
        {"code": "SHOT_DURATION", "parentCode": "POSITIVE_ROOT", "groupCode": "positive_action_motion", "nameKo": "샷 길이", "nameEn": "Shot Duration", "scopeType": "SCENE", "selectionType": "SINGLE", "maxSelectCount": 1, "sortOrder": 320},
        {"code": "NEGATIVE_QUALITY", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_quality", "nameKo": "품질 제한", "nameEn": "Negative Quality", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 330},
        {"code": "NEGATIVE_CAMERA", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_camera", "nameKo": "카메라 제한", "nameEn": "Negative Camera", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 340},
        {"code": "NEGATIVE_TEXT", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_text_watermark", "nameKo": "문자/자막 제한", "nameEn": "Negative Text", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 350},
        {"code": "NEGATIVE_IDENTITY", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_identity", "nameKo": "정체성 제한", "nameEn": "Negative Identity", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 360},
        {"code": "NEGATIVE_EXCLUSION", "parentCode": "NEGATIVE_ROOT", "groupCode": "negative_exclusion", "nameKo": "금지/제외 요소", "nameEn": "Negative Exclusion", "scopeType": "OUTPUT", "selectionType": "MULTIPLE", "maxSelectCount": 5, "sortOrder": 370},
    ],
    "terms": [
        {"category": "GENRE", "code": "genre_cinematic", "canonicalKey": "genre.cinematic", "labelKo": "시네마틱", "labelEn": "cinematic", "promptText": "cinematic image-to-video shot", "renderText": "cinematic WAN image-to-video shot", "sortOrder": 10},
        {"category": "GENRE", "code": "genre_documentary", "canonicalKey": "genre.documentary", "labelKo": "다큐멘터리", "labelEn": "documentary", "promptText": "natural documentary style", "sortOrder": 20},
        {"category": "CONTENT_RATING", "code": "rating_brand_safe", "canonicalKey": "rating.brand_safe", "labelKo": "브랜드 세이프", "labelEn": "brand-safe", "promptText": "brand-safe visual tone", "sortOrder": 10},
        {"category": "SUBJECT_TYPE", "code": "subject_person", "canonicalKey": "subject.person", "labelKo": "인물", "labelEn": "person", "promptText": "the person from the input image", "sortOrder": 10},
        {"category": "SUBJECT_TYPE", "code": "subject_product", "canonicalKey": "subject.product", "labelKo": "제품", "labelEn": "product", "promptText": "the product from the input image", "sortOrder": 20},
        {"category": "CHARACTER_APPEARANCE", "code": "appearance_preserve_identity", "canonicalKey": "appearance.preserve_identity", "labelKo": "동일성 유지", "labelEn": "preserve identity", "promptText": "preserve the same identity, outfit, and proportions from the input image", "sortOrder": 10},
        {"category": "CHARACTER_ACTION", "code": "action_gentle_walk", "canonicalKey": "action.gentle_walk", "labelKo": "천천히 걷기", "labelEn": "gentle walking", "promptText": "gentle walking motion", "renderText": "gentle, natural walking motion", "sortOrder": 10},
        {"category": "CHARACTER_ACTION", "code": "action_subtle_expression", "canonicalKey": "action.subtle_expression", "labelKo": "미세한 표정 변화", "labelEn": "subtle expression", "promptText": "subtle natural expression change", "sortOrder": 20},
        {"category": "CAMERA_MOVEMENT", "code": "camera_slow_tracking", "canonicalKey": "camera.movement.slow_tracking", "labelKo": "느린 트래킹", "labelEn": "slow tracking", "promptText": "slow tracking camera movement", "sortOrder": 10},
        {"category": "CAMERA_MOVEMENT", "code": "camera_static", "canonicalKey": "camera.movement.static", "labelKo": "고정 카메라", "labelEn": "static camera", "promptText": "stable static camera", "sortOrder": 20},
        {"category": "CAMERA_FRAMING", "code": "shot_medium", "canonicalKey": "camera.framing.medium", "labelKo": "미디엄 샷", "labelEn": "medium shot", "promptText": "medium shot composition", "sortOrder": 10},
        {"category": "BACKGROUND", "code": "background_original", "canonicalKey": "environment.background.original", "labelKo": "원본 배경 유지", "labelEn": "preserve original background", "promptText": "preserve the original background layout", "sortOrder": 10},
        {"category": "TIME_OF_DAY", "code": "time_original", "canonicalKey": "environment.time.original", "labelKo": "원본 시간대 유지", "labelEn": "preserve original time of day", "promptText": "preserve the original time of day", "sortOrder": 10},
        {"category": "WEATHER", "code": "weather_original", "canonicalKey": "environment.weather.original", "labelKo": "원본 날씨 유지", "labelEn": "preserve original weather", "promptText": "preserve the original weather and atmosphere", "sortOrder": 10},
        {"category": "LIGHTING", "code": "lighting_soft", "canonicalKey": "style.lighting.soft", "labelKo": "부드러운 조명", "labelEn": "soft light", "promptText": "soft natural light", "sortOrder": 10},
        {"category": "COLOR_PALETTE", "code": "color_balanced", "canonicalKey": "style.color.balanced", "labelKo": "균형 잡힌 색감", "labelEn": "balanced color", "promptText": "balanced natural color grading", "sortOrder": 10},
        {"category": "VIDEO_MOOD", "code": "mood_calm", "canonicalKey": "style.mood.calm", "labelKo": "차분한 분위기", "labelEn": "calm", "promptText": "calm and believable atmosphere", "sortOrder": 10},
        {"category": "QUALITY_TAG", "code": "quality_stable_motion", "canonicalKey": "quality.stable_motion", "labelKo": "안정적인 움직임", "labelEn": "stable motion", "promptText": "stable motion, coherent frames", "sortOrder": 10},
        {"category": "NEGATIVE_ANATOMY", "code": "negative_distortion", "canonicalKey": "negative.anatomy.distortion", "labelKo": "왜곡 방지", "labelEn": "avoid distortion", "promptText": "", "negativeText": "distorted anatomy, warped body, deformed face, extra limbs", "riskLevel": "HIGH", "sortOrder": 10},
        {"category": "NEGATIVE_ARTIFACT", "code": "negative_artifacts", "canonicalKey": "negative.artifact.general", "labelKo": "아티팩트 방지", "labelEn": "avoid artifacts", "promptText": "", "negativeText": "blur, flicker, watermark, subtitles, text artifacts", "riskLevel": "MEDIUM", "sortOrder": 20},
        {"category": "NEGATIVE_TEMPORAL", "code": "negative_unstable_motion", "canonicalKey": "negative.temporal.unstable_motion", "labelKo": "불안정 움직임 방지", "labelEn": "avoid unstable motion", "promptText": "", "negativeText": "jitter, temporal inconsistency, unstable motion, morphing", "riskLevel": "MEDIUM", "sortOrder": 30},
        {"category": "OBJECT_ACTION", "code": "object_remain_stable", "canonicalKey": "object.action.remain_stable", "labelKo": "안정 유지", "labelEn": "remain stable", "promptText": "the object remains stable and keeps its original shape", "sortOrder": 10},
        {"category": "OBJECT_ACTION", "code": "object_subtle_motion", "canonicalKey": "object.action.subtle_motion", "labelKo": "미세한 움직임", "labelEn": "subtle object motion", "promptText": "subtle object motion without shape deformation", "sortOrder": 20},
        {"category": "MOTION_SPEED", "code": "motion_speed_slow", "canonicalKey": "motion.speed.slow", "labelKo": "느리게", "labelEn": "slow motion pace", "promptText": "slow, controlled motion pace", "sortOrder": 10},
        {"category": "MOTION_SPEED", "code": "motion_speed_natural", "canonicalKey": "motion.speed.natural", "labelKo": "자연스럽게", "labelEn": "natural motion pace", "promptText": "natural motion pace", "sortOrder": 20},
        {"category": "MOTION_INTENSITY", "code": "motion_intensity_subtle", "canonicalKey": "motion.intensity.subtle", "labelKo": "약하게", "labelEn": "subtle motion intensity", "promptText": "subtle motion intensity", "sortOrder": 10},
        {"category": "MOTION_INTENSITY", "code": "motion_intensity_moderate", "canonicalKey": "motion.intensity.moderate", "labelKo": "중간", "labelEn": "moderate motion intensity", "promptText": "moderate motion intensity", "sortOrder": 20},
        {"category": "CAMERA_ANGLE", "code": "camera_angle_eye_level", "canonicalKey": "camera.angle.eye_level", "labelKo": "눈높이", "labelEn": "eye-level angle", "promptText": "eye-level camera angle", "sortOrder": 10},
        {"category": "CAMERA_ANGLE", "code": "camera_angle_low", "canonicalKey": "camera.angle.low", "labelKo": "로우 앵글", "labelEn": "low angle", "promptText": "low-angle camera view", "sortOrder": 20},
        {"category": "LENS_TYPE", "code": "lens_standard", "canonicalKey": "camera.lens.standard", "labelKo": "표준 렌즈", "labelEn": "standard lens", "promptText": "standard lens perspective", "sortOrder": 10},
        {"category": "LENS_TYPE", "code": "lens_telephoto", "canonicalKey": "camera.lens.telephoto", "labelKo": "망원 렌즈", "labelEn": "telephoto lens", "promptText": "compressed telephoto lens perspective", "sortOrder": 20},
        {"category": "FOCUS_STYLE", "code": "focus_subject_locked", "canonicalKey": "camera.focus.subject_locked", "labelKo": "대상 고정 초점", "labelEn": "subject-locked focus", "promptText": "subject-locked focus", "sortOrder": 10},
        {"category": "FOCUS_STYLE", "code": "focus_shallow_depth", "canonicalKey": "camera.focus.shallow_depth", "labelKo": "얕은 심도", "labelEn": "shallow depth of field", "promptText": "shallow depth of field", "sortOrder": 20},
        {"category": "CLOTHING", "code": "clothing_preserve", "canonicalKey": "subject.clothing.preserve", "labelKo": "의상 유지", "labelEn": "preserve clothing", "promptText": "preserve the original clothing", "sortOrder": 10},
        {"category": "POSE", "code": "pose_preserve", "canonicalKey": "subject.pose.preserve", "labelKo": "포즈 유지", "labelEn": "preserve pose", "promptText": "preserve the original pose structure", "sortOrder": 10},
        {"category": "GAZE_DIRECTION", "code": "gaze_camera", "canonicalKey": "subject.gaze.camera", "labelKo": "카메라 응시", "labelEn": "looking at camera", "promptText": "looking toward the camera", "sortOrder": 10},
        {"category": "FACIAL_EXPRESSION", "code": "expression_soft_smile", "canonicalKey": "subject.expression.soft_smile", "labelKo": "부드러운 미소", "labelEn": "soft smile", "promptText": "soft natural smile", "sortOrder": 10},
        {"category": "EMOTION", "code": "emotion_calm", "canonicalKey": "subject.emotion.calm", "labelKo": "차분함", "labelEn": "calm emotion", "promptText": "calm emotional tone", "sortOrder": 10},
        {"category": "ANIMATION_STYLE", "code": "animation_realistic_i2v", "canonicalKey": "style.animation.realistic_i2v", "labelKo": "사실적 I2V", "labelEn": "realistic image-to-video", "promptText": "realistic image-to-video animation style", "sortOrder": 10},
        {"category": "RENDERING_STYLE", "code": "rendering_photoreal", "canonicalKey": "style.rendering.photoreal", "labelKo": "포토리얼", "labelEn": "photorealistic rendering", "promptText": "photorealistic rendering", "sortOrder": 10},
        {"category": "SCENE_TRANSITION", "code": "transition_none", "canonicalKey": "style.transition.none", "labelKo": "전환 없음", "labelEn": "no scene transition", "promptText": "no scene transition", "sortOrder": 10},
        {"category": "SHOT_DURATION", "code": "duration_short_3s", "canonicalKey": "edit.duration.short_3s", "labelKo": "짧은 3초", "labelEn": "short 3-second shot", "promptText": "short 3-second shot duration", "sortOrder": 10},
        {"category": "NEGATIVE_QUALITY", "code": "negative_low_quality", "canonicalKey": "negative.quality.low_quality", "labelKo": "저품질 방지", "labelEn": "avoid low quality", "promptText": "", "negativeText": "low quality, noisy frames, compression artifacts", "riskLevel": "MEDIUM", "sortOrder": 10},
        {"category": "NEGATIVE_CAMERA", "code": "negative_camera_shake", "canonicalKey": "negative.camera.shake", "labelKo": "카메라 흔들림 방지", "labelEn": "avoid camera shake", "promptText": "", "negativeText": "excessive camera shake, sudden zoom, rolling shutter distortion", "riskLevel": "MEDIUM", "sortOrder": 10},
        {"category": "NEGATIVE_TEXT", "code": "negative_text_overlay", "canonicalKey": "negative.text.overlay", "labelKo": "문자/자막 방지", "labelEn": "avoid text overlays", "promptText": "", "negativeText": "text overlay, captions, subtitles, logos, watermarks", "riskLevel": "MEDIUM", "sortOrder": 10},
        {"category": "NEGATIVE_IDENTITY", "code": "negative_identity_drift", "canonicalKey": "negative.identity.drift", "labelKo": "정체성 변화 방지", "labelEn": "avoid identity drift", "promptText": "", "negativeText": "identity drift, changed face, changed outfit, changed body proportions", "riskLevel": "HIGH", "sortOrder": 10},
        {"category": "NEGATIVE_EXCLUSION", "code": "negative_new_objects", "canonicalKey": "negative.exclusion.new_objects", "labelKo": "불필요한 객체 방지", "labelEn": "avoid new objects", "promptText": "", "negativeText": "new objects, unrelated people, unrelated background changes", "riskLevel": "MEDIUM", "sortOrder": 10},
    ],
    "rules": [
        {
            "code": "i2v_preserve_identity",
            "name": "Preserve input identity",
            "ruleType": "constraint",
            "condition": {"i2v_mode": True},
            "action": {"positive_append": ["preserve identity from the input image"], "negative_append": ["identity drift"]},
            "severity": "info",
        },
        {
            "code": "avoid_unrequested_objects",
            "name": "Avoid unrequested objects",
            "ruleType": "constraint",
            "condition": {"avoid_new_objects": True},
            "action": {"negative_append": ["new objects, unrelated background changes"]},
            "severity": "warning",
        },
    ],
    "relations": [
        {
            "source": "subject_person",
            "target": "appearance_preserve_identity",
            "relationType": "IMPLY",
            "weight": 1.0,
            "metadata": {"message": "Person subjects imply identity preservation for image-to-video generation."},
        },
        {
            "source": "camera_static",
            "target": "camera_slow_tracking",
            "relationType": "EXCLUDE",
            "weight": 1.0,
            "metadata": {"message": "Static camera and slow tracking camera should not be selected together."},
        },
        {
            "source": "action_gentle_walk",
            "target": "quality_stable_motion",
            "relationType": "RECOMMEND",
            "weight": 0.7,
            "metadata": {"message": "Gentle walking usually benefits from stable motion quality."},
        },
    ],
    "templates": [
        {
            "code": "i2v_positive_default",
            "name": "I2V positive default",
            "promptType": "positive",
            "templateText": "{genre}, {subject}, {action}, {camera}, {style}, {quality}",
            "schema": {"output": "positive_prompt"},
        },
        {
            "code": "i2v_negative_default",
            "name": "I2V negative default",
            "promptType": "negative",
            "templateText": "{negative}, identity drift, unstable motion",
            "schema": {"output": "negative_prompt"},
        },
    ],
    "modelProfiles": [
        {
            "modelFamily": "WAN",
            "modelName": "Wan Image-to-Video",
            "modelVersion": "2.1/2.2",
            "taskType": "image_to_video",
            "promptLanguage": "en",
            "supportsNegativePrompt": True,
            "supportsPromptWeight": False,
            "capabilities": {"sceneJsonVersion": "1.0", "supportsMultiImage": True},
            "defaultParameters": {"fps": 16, "steps": 4, "cfgScale": 1, "motionShift": 5},
        }
    ],
}


def apply_example_prompt_catalog(session: Session, *, force: bool = False) -> dict:
    """B-06 4단계: 이 시드 함수는 더 이상 구형 prompt_categories/prompt_category_terms를
    거치지 않고, 신형 계층(prompt_scopes -> prompt_category_groups -> prompt_subcategories
    -> prompt_subcategory_keywords)에 직접 쓴다. 예전에는 여기서 PromptCategory/
    PromptCategoryTerm을 만들고 sync_prompt_catalog_hierarchy()의 lazy backfill에 기대
    신형 계층을 채웠지만, 그 backfill 함수 자체가 이 단계에서 제거되었다(더 이상 구형
    테이블에 쓰는 코드가 없으므로 브릿지가 필요 없음). EXAMPLE_PROMPT_CATALOG의 원본
    데이터 구조(categories/terms 키, groupCode/parentCode 등)는 그대로 두되(콘텐츠
    자체는 이 정리 작업의 대상이 아님), 여기서 신형 테이블 행으로 직접 변환한다.
    """
    if force:
        for model in (
            PromptTermRendering,
            ModelProfile,
            PromptSubcategoryKeyword,
            PromptSubcategory,
            PromptCategoryGroup,
            PromptScope,
            PromptTermRelation,
            PromptTemplate,
            PromptRule,
            PromptTerm,
        ):
            session.query(model).delete()
        session.flush()

    now = datetime.utcnow()

    # 1) scopes (POSITIVE/NEGATIVE) - 신형 계층의 최상위.
    scope_by_code: dict[str, PromptScope] = {}
    for code, item in PROMPT_SCOPE_SEED.items():
        scope = session.scalar(select(PromptScope).where(PromptScope.code == code))
        if not scope:
            scope = PromptScope(code=code, created_at=now)
            session.add(scope)
        scope.name_ko = item["nameKo"]
        scope.name_en = item["nameEn"]
        scope.sort_order = item["sortOrder"]
        scope.is_active = True
        scope.updated_at = now
        scope_by_code[code] = scope
    session.flush()

    # 2) category groups - ROOT(POSITIVE_ROOT/NEGATIVE_ROOT)를 제외한 모든 예시
    # 카테고리의 groupCode에서 도출한다(구형 sync_prompt_catalog_hierarchy가 활성
    # 카테고리에서 하던 것과 동일한 규칙).
    group_codes = sorted({
        item["groupCode"] for item in EXAMPLE_PROMPT_CATALOG["categories"]
        if item["code"] not in FIXED_PROMPT_ROOT_CODES
    })
    group_by_code: dict[str, PromptCategoryGroup] = {}
    for group_code in group_codes:
        scope = scope_by_code[_scope_code_for_group(group_code)]
        group = session.scalar(select(PromptCategoryGroup).where(PromptCategoryGroup.code == group_code))
        if not group:
            group = PromptCategoryGroup(code=group_code, scope_id=scope.id, created_at=now)
            session.add(group)
        group.scope_id = scope.id
        label_ko, label_en = PROMPT_GROUP_LABELS.get(group_code, (_title_from_code(group_code), _title_from_code(group_code)))
        group.name_ko = label_ko
        group.name_en = label_en
        group.sort_order = _prompt_group_sort_order(group_code)
        group.is_active = True
        group.updated_at = now
        group_by_code[group_code] = group
    session.flush()

    # 3) subcategories - ROOT를 제외한 예시 카테고리 1건당 1개. legacy_category_id는
    # 더 이상 컬럼 자체가 없다(20260810_0013 마이그레이션 참조).
    subcategory_by_code: dict[str, PromptSubcategory] = {}
    for item in EXAMPLE_PROMPT_CATALOG["categories"]:
        if item["code"] in FIXED_PROMPT_ROOT_CODES:
            continue
        group = group_by_code[item["groupCode"]]
        subcategory = session.scalar(select(PromptSubcategory).where(PromptSubcategory.code == item["code"]))
        if not subcategory:
            subcategory = PromptSubcategory(code=item["code"], category_group_id=group.id, created_at=now)
            session.add(subcategory)
        subcategory.category_group_id = group.id
        subcategory.scope_type = item.get("scopeType", "SCENE")
        subcategory.selection_type = item.get("selectionType", "MULTIPLE")
        subcategory.required_yn = bool(item.get("required", False))
        subcategory.max_select_count = item.get("maxSelectCount")
        subcategory.name_ko = item["nameKo"]
        subcategory.name_en = item["nameEn"]
        subcategory.description = item.get("description")
        subcategory.sort_order = item.get("sortOrder", 100)
        subcategory.is_active = True
        subcategory.updated_at = now
        subcategory_by_code[subcategory.code] = subcategory
    session.flush()

    # 4) terms - 콘텐츠(label/prompt text 등)는 여전히 prompt_terms에만 저장 가능하다
    # (upsert_prompt_keyword의 docstring 참조). category_id는 이제 nullable이며 항상
    # None으로 남긴다 - 귀속은 아래 5)의 prompt_subcategory_keywords 링크가 전담한다.
    term_by_code: dict[str, PromptTerm] = {}
    for item in EXAMPLE_PROMPT_CATALOG["terms"]:
        term = session.scalar(select(PromptTerm).where(PromptTerm.code == item["code"]))
        if not term:
            term = PromptTerm(code=item["code"])
            session.add(term)
        term.canonical_key = item.get("canonicalKey") or item["code"]
        term.label_ko = item["labelKo"]
        term.label_en = item["labelEn"]
        term.description = item.get("description")
        term.prompt_text = item.get("promptText", "")
        term.negative_text = item.get("negativeText")
        term.risk_level = item.get("riskLevel", "NONE")
        term.metadata_json = item.get("metadata", {})
        term.sort_order = item.get("sortOrder", 100)
        term.is_active = True
        term.updated_at = now
        term_by_code[term.code] = term
    session.flush()

    # 5) subcategory <-> keyword 링크 - 구형 prompt_category_terms를 완전히 대체한다.
    for item in EXAMPLE_PROMPT_CATALOG["terms"]:
        subcategory = subcategory_by_code[item["category"]]
        term = term_by_code[item["code"]]
        link = session.get(PromptSubcategoryKeyword, {"subcategory_id": subcategory.id, "keyword_id": term.id})
        if not link:
            link = PromptSubcategoryKeyword(subcategory_id=subcategory.id, keyword_id=term.id)
            session.add(link)
        link.default_polarity = "NEGATIVE" if item.get("negativeText") else "POSITIVE"
        link.sort_order = item.get("sortOrder", 100)
        link.active_yn = True

    session.flush()
    for item in EXAMPLE_PROMPT_CATALOG.get("relations", []):
        source_term = session.scalar(select(PromptTerm).where(PromptTerm.code == item["source"]))
        target_term = session.scalar(select(PromptTerm).where(PromptTerm.code == item["target"]))
        if not source_term or not target_term:
            continue
        relation = session.scalar(
            select(PromptTermRelation).where(
                PromptTermRelation.source_term_id == source_term.id,
                PromptTermRelation.target_term_id == target_term.id,
                PromptTermRelation.relation_type == item["relationType"],
            )
        )
        if not relation:
            relation = PromptTermRelation(
                source_term_id=source_term.id,
                target_term_id=target_term.id,
                relation_type=item["relationType"],
            )
            session.add(relation)
        relation.weight = float(item.get("weight", 1.0))
        relation.metadata_json = item.get("metadata", {})

    session.flush()
    profile_by_name: dict[str, ModelProfile] = {}
    for item in EXAMPLE_PROMPT_CATALOG.get("modelProfiles", []):
        profile = session.scalar(
            select(ModelProfile).where(
                ModelProfile.model_family == item["modelFamily"],
                ModelProfile.model_name == item["modelName"],
                ModelProfile.model_version == item.get("modelVersion"),
            )
        )
        if not profile:
            profile = ModelProfile(model_family=item["modelFamily"], model_name=item["modelName"])
            session.add(profile)
        profile.model_version = item.get("modelVersion")
        profile.task_type = item.get("taskType", "image_to_video")
        profile.prompt_language = item.get("promptLanguage", "en")
        profile.supports_negative_prompt = bool(item.get("supportsNegativePrompt", True))
        profile.supports_prompt_weight = bool(item.get("supportsPromptWeight", False))
        profile.capabilities_json = item.get("capabilities", {})
        profile.default_parameters_json = item.get("defaultParameters", {})
        profile.active_yn = True
        profile_by_name[profile.model_name] = profile
    session.flush()

    model_profile = next(iter(profile_by_name.values()), None)
    if model_profile:
        for item in EXAMPLE_PROMPT_CATALOG["terms"]:
            term = session.scalar(select(PromptTerm).where(PromptTerm.code == item["code"]))
            if not term:
                continue
            render_items = []
            if item.get("promptText"):
                render_items.append(("POSITIVE", item.get("renderText") or item["promptText"]))
            if item.get("negativeText"):
                render_items.append(("NEGATIVE", item.get("negativeRenderText") or item["negativeText"]))
            for polarity, render_text in render_items:
                rendering = session.scalar(
                    select(PromptTermRendering).where(
                        PromptTermRendering.term_id == term.id,
                        PromptTermRendering.model_profile_id == model_profile.id,
                        PromptTermRendering.polarity == polarity,
                    )
                )
                if not rendering:
                    rendering = PromptTermRendering(
                        term_id=term.id,
                        model_profile_id=model_profile.id,
                        polarity=polarity,
                    )
                    session.add(rendering)
                rendering.language_code = "en"
                rendering.render_text = render_text
                rendering.render_version = "v1"
                rendering.active_yn = True

    for item in EXAMPLE_PROMPT_CATALOG["rules"]:
        rule = session.scalar(select(PromptRule).where(PromptRule.code == item["code"]))
        if not rule:
            rule = PromptRule(code=item["code"])
            session.add(rule)
        rule.name = item["name"]
        rule.rule_type = item.get("ruleType", "constraint")
        rule.condition_json = item.get("condition", {})
        rule.action_json = item.get("action", {})
        rule.severity = item.get("severity", "info")
        rule.is_active = True
        rule.updated_at = datetime.utcnow()

    for item in EXAMPLE_PROMPT_CATALOG["templates"]:
        template = session.scalar(select(PromptTemplate).where(PromptTemplate.code == item["code"]))
        if not template:
            template = PromptTemplate(code=item["code"])
            session.add(template)
        template.name = item["name"]
        template.prompt_type = item["promptType"]
        template.template_text = item["templateText"]
        template.schema_json = item.get("schema", {})
        template.is_active = True
        template.updated_at = datetime.utcnow()

    session.commit()
    return prompt_catalog(session)


# B-06 4단계: sync_prompt_catalog_hierarchy()(구형<->신형 계층 lazy 브릿지)는 이 단계에서
# 완전히 제거했다. TASKS.md 0번 항목이 "전환 후에는 이 동기화 호출도 제거 대상입니다"라고
# 명시했고, 3단계까지 admin CRUD가, 이번 4단계에서 apply_example_prompt_catalog()까지
# 신형 계층에만 직접 쓰도록 바뀌면서 이 브릿지의 유일한 존재 이유(구형 쓰기를 신형에 반영)가
# 사라졌다. 남아있던 호출부(prompt_catalog/build_scene_json/upsert_prompt_category_group/
# upsert_prompt_category)에서도 모두 제거했다.


def _scope_code_for_group(group_code: str) -> str:
    return "NEGATIVE" if group_code.lower().startswith("negative") else "POSITIVE"


def _prompt_group_sort_order(group_code: str) -> int:
    try:
        return (PROMPT_GROUP_ORDER.index(group_code) + 1) * 10
    except ValueError:
        return 1000


def _title_from_code(code: str) -> str:
    return code.replace("_", " ").strip().title()


def prompt_catalog(session: Session) -> dict:
    rules = session.scalars(
        select(PromptRule).where(PromptRule.is_active.is_(True)).order_by(PromptRule.code)
    ).all()
    templates = session.scalars(
        select(PromptTemplate).where(PromptTemplate.is_active.is_(True)).order_by(PromptTemplate.prompt_type, PromptTemplate.code)
    ).all()
    relations = session.scalars(
        select(PromptTermRelation)
        .options(selectinload(PromptTermRelation.source_term), selectinload(PromptTermRelation.target_term))
        .order_by(PromptTermRelation.relation_type, PromptTermRelation.weight.desc())
    ).all()
    groups = session.scalars(
        select(PromptCategoryGroup)
        .options(
            selectinload(PromptCategoryGroup.scope),
            selectinload(PromptCategoryGroup.subcategories)
            .selectinload(PromptSubcategory.keyword_links)
            .selectinload(PromptSubcategoryKeyword.keyword),
        )
        .where(PromptCategoryGroup.is_active.is_(True))
        .order_by(PromptCategoryGroup.sort_order, PromptCategoryGroup.code)
    ).all()
    return {
        "groups": [
            {
                "id": group.id,
                "code": group.code,
                "scopeId": group.scope_id,
                "scopeCode": group.scope.code if group.scope else None,
                "scopeType": group.scope.code if group.scope else None,
                "nameKo": group.name_ko,
                "nameEn": group.name_en,
                "description": group.description,
                "sortOrder": group.sort_order,
                "subcategories": [
                    {
                        "id": subcategory.id,
                        "code": subcategory.code,
                        "groupId": subcategory.category_group_id,
                        "scopeType": subcategory.scope_type,
                        "nameKo": subcategory.name_ko,
                        "nameEn": subcategory.name_en,
                        "description": subcategory.description,
                        "selectionMode": "single" if subcategory.selection_type.upper() == "SINGLE" else "multi",
                        "required": subcategory.required_yn,
                        "maxSelectCount": subcategory.max_select_count,
                        "sortOrder": subcategory.sort_order,
                        "terms": [
                            _prompt_term_payload(link.keyword, link.sort_order)
                            for link in sorted(subcategory.keyword_links, key=lambda link: (link.sort_order, link.keyword.code if link.keyword else ""))
                            if link.active_yn and link.keyword and link.keyword.is_active
                        ],
                    }
                    for subcategory in sorted(group.subcategories, key=lambda item: (item.sort_order, item.code))
                    if subcategory.is_active
                ],
            }
            for group in groups
        ],
        # B-06 3단계에서 discrepancy를 해소하며 구형 "categories" 배열을 완전히
        # 제거했다(2단계 커밋에서는 admin CRUD가 여전히 구형 테이블에 쓰고 있어
        # smoke test 호환을 위해 남겨두고 DEPRECATED로만 표시했었다). 이제
        # upsert_prompt_category/upsert_prompt_keyword이 신형 계층에만 쓰므로, 구형
        # categories를 계속 내려주면 오히려 이 시점부터는 최신화되지 않는 stale
        # 데이터를 보여주게 된다 - "groups"가 유일한 canonical 응답이다.
        "rules": [
            {
                "id": rule.id,
                "code": rule.code,
                "name": rule.name,
                "ruleType": rule.rule_type,
                "condition": rule.condition_json,
                "action": rule.action_json,
                "severity": rule.severity,
            }
            for rule in rules
        ],
        "templates": [
            {
                "id": template.id,
                "code": template.code,
                "name": template.name,
                "promptType": template.prompt_type,
                "templateText": template.template_text,
                "schema": template.schema_json,
            }
            for template in templates
        ],
        "relations": [
            {
                "id": relation.id,
                "sourceTermId": relation.source_term_id,
                "sourceTermCode": relation.source_term.code if relation.source_term else None,
                "targetTermId": relation.target_term_id,
                "targetTermCode": relation.target_term.code if relation.target_term else None,
                "relationType": relation.relation_type,
                "weight": relation.weight,
                "metadata": relation.metadata_json,
            }
            for relation in relations
        ],
    }


def _prompt_term_payload(term: PromptTerm, sort_order: int | None = None) -> dict:
    return {
        "id": term.id,
        "code": term.code,
        "canonicalKey": term.canonical_key,
        "labelKo": term.label_ko,
        "labelEn": term.label_en,
        "description": term.description,
        "promptText": term.prompt_text,
        "negativeText": term.negative_text,
        "riskLevel": term.risk_level,
        "metadata": term.metadata_json,
        "sortOrder": sort_order if sort_order is not None else term.sort_order,
    }


def upsert_prompt_category_group(session: Session, payload: dict, group_id: int | None = None) -> dict:
    # B-06: 이 함수는 원래부터 신형 PromptCategoryGroup에만 쓴다 - 구형
    # prompt_categories/prompt_terms는 이 함수에서 애초에 건드리지 않았다.
    code = _required_admin_string(payload, "code").lower()
    scope_code = _required_admin_string(payload, "scopeType").upper()
    if scope_code not in PROMPT_SCOPE_SEED:
        raise ValueError("scopeType must be POSITIVE or NEGATIVE")
    scope = session.scalar(select(PromptScope).where(PromptScope.code == scope_code))
    if not scope:
        raise ValueError("Prompt scope is not ready")
    group = session.get(PromptCategoryGroup, group_id) if group_id else None
    existing = session.scalar(select(PromptCategoryGroup).where(PromptCategoryGroup.code == code))
    if existing and (not group or existing.id != group.id):
        raise ValueError(f"Prompt category code already exists: {code}")
    if not group:
        group = PromptCategoryGroup(code=code, scope_id=scope.id)
        session.add(group)
    group.scope_id = scope.id
    group.code = code
    group.name_ko = _required_admin_string(payload, "nameKo")
    group.name_en = _required_admin_string(payload, "nameEn")
    group.description = _optional_admin_string(payload.get("description"))
    group.sort_order = _optional_admin_int(payload.get("sortOrder")) or 100
    group.is_active = True
    group.updated_at = datetime.utcnow()
    session.commit()
    return prompt_catalog(session)


def deactivate_prompt_category_group(session: Session, group_id: int) -> dict:
    # B-06 4단계: legacy_category_id/legacy_category 관계가 제거되어 구형 카테고리로의
    # cascade도 함께 제거했다 - prompt_categories는 이제 어떤 서비스 코드에서도
    # 읽거나 쓰지 않는, 순수 과거 데이터다.
    group = session.get(PromptCategoryGroup, group_id)
    if not group:
        raise ValueError("Prompt category not found")
    group.is_active = False
    group.updated_at = datetime.utcnow()
    for subcategory in group.subcategories:
        subcategory.is_active = False
        subcategory.updated_at = datetime.utcnow()
        for link in subcategory.keyword_links:
            link.active_yn = False
    session.commit()
    return prompt_catalog(session)


def upsert_prompt_category(session: Session, payload: dict, category_id: int | None = None) -> dict:
    """B-06: 이름/엔드포인트(/prompts/categories)는 프론트 계약을 지키기 위해 그대로
    두지만, 실제로는 신형 PromptSubcategory에만 쓴다. 구형 prompt_categories는 이
    함수에서 생성/수정하지 않는다("이관 후 읽기 전용" 원칙 - 4단계에서는 아예 참조도
    하지 않음). category_id 인자와 반환되는 catalog의 subcategory "id"는
    PromptSubcategory.id다. 3단계에서 보고했던 discrepancy(legacy_category_id가 없는
    서브카테고리 아래 신규 용어를 만들 수 없던 제약)는 4단계에서
    prompt_terms.category_id를 nullable로 완화하며 완전히 해소했다 -
    upsert_prompt_keyword() 참조.
    """
    code = _required_admin_string(payload, "code").upper()
    if code in FIXED_PROMPT_ROOT_CODES:
        raise ValueError("Positive/Negative root categories are fixed system classifications.")
    subcategory = session.get(PromptSubcategory, category_id) if category_id else None
    existing = session.scalar(select(PromptSubcategory).where(PromptSubcategory.code == code))
    if existing and (not subcategory or existing.id != subcategory.id):
        raise ValueError(f"Prompt category code already exists: {code}")
    group = _prompt_group_from_payload(session, payload)
    if not group:
        raise ValueError("groupId or groupCode is required")
    now = datetime.utcnow()
    if not subcategory:
        subcategory = PromptSubcategory(code=code, category_group_id=group.id, created_at=now)
        session.add(subcategory)
    subcategory.category_group_id = group.id
    subcategory.code = code
    subcategory.scope_type = _required_admin_string(payload, "scopeType").upper()
    selection_mode = _required_admin_string(payload, "selectionMode").upper()
    subcategory.selection_type = "SINGLE" if selection_mode in {"SINGLE", "SINGLE_SELECT"} else "MULTIPLE"
    subcategory.required_yn = bool(payload.get("required", False))
    subcategory.max_select_count = _optional_admin_int(payload.get("maxSelectCount"))
    subcategory.name_ko = _required_admin_string(payload, "nameKo")
    subcategory.name_en = _required_admin_string(payload, "nameEn")
    subcategory.description = _optional_admin_string(payload.get("description"))
    subcategory.sort_order = _optional_admin_int(payload.get("sortOrder")) or 100
    subcategory.is_active = True
    subcategory.updated_at = now
    session.commit()
    return prompt_catalog(session)


def deactivate_prompt_category(session: Session, category_id: int) -> dict:
    # B-06 4단계: category_id는 PromptSubcategory.id. legacy_category cascade는
    # legacy_category_id 컬럼과 함께 제거했다.
    subcategory = session.get(PromptSubcategory, category_id)
    if not subcategory:
        raise ValueError("Prompt category not found")
    if subcategory.code in FIXED_PROMPT_ROOT_CODES:
        raise ValueError("Positive/Negative root categories cannot be deactivated.")
    now = datetime.utcnow()
    subcategory.is_active = False
    subcategory.updated_at = now
    for link in subcategory.keyword_links:
        link.active_yn = False
        if link.keyword:
            link.keyword.is_active = False
            link.keyword.updated_at = now
    session.commit()
    return prompt_catalog(session)


def upsert_prompt_keyword(session: Session, payload: dict, term_id: int | None = None) -> dict:
    """B-06: "categoryId" 페이로드 키는 이름을 그대로 유지하되(프론트 계약 불변), 이제
    PromptSubcategory.id를 가리키는 것으로 의미가 바뀐다 - main.tsx의
    promptCatalogCategories()가 groups[].subcategories[]를 펼쳐 만드는 "category" 객체의
    id가 이미 subcategory.id이므로, 프론트는 코드 변경 없이 자연스럽게 맞는 값을 보낸다.

    3단계에서 보고했던 discrepancy(해소됨): prompt_subcategory_keywords는 용어
    콘텐츠 컬럼이 전혀 없어(subcategory_id, keyword_id, default_polarity, sort_order,
    active_yn뿐) 새 용어의 실제 콘텐츠(label_ko 등)는 여전히 prompt_terms에 저장한다
    (keyword_id는 prompt_terms.id를 가리키는 FK). 3단계 당시엔 prompt_terms.category_id가
    NOT NULL FK(→prompt_categories.id)라서 legacy_category_id가 없는(=이관되지 않은)
    서브카테고리 아래에는 신규 용어를 만들 수 없었다. 4단계 마이그레이션
    (20260810_0013)이 category_id를 nullable로 완화하면서 이 제약이 완전히 사라졌다 -
    이제 어떤 서브카테고리(신규로 만든 것이든 이관된 것이든) 아래에도 신규 용어를 자유롭게
    추가할 수 있다. 더 이상 prompt_category_terms(구형 조인 테이블)에는 쓰지 않고,
    prompt_subcategory_keywords 링크를 이 함수가 직접, 명시적으로 만든다.
    """
    code = _required_admin_string(payload, "code")
    subcategory_id = _optional_admin_int(payload.get("categoryId") or payload.get("subcategoryId"))
    if not subcategory_id:
        raise ValueError("categoryId is required")
    subcategory = session.get(PromptSubcategory, subcategory_id)
    if not subcategory or not subcategory.is_active:
        raise ValueError("Active prompt category not found")
    term = session.get(PromptTerm, term_id) if term_id else None
    existing = session.scalar(select(PromptTerm).where(PromptTerm.code == code))
    if existing and (not term or existing.id != term.id):
        raise ValueError(f"Prompt term code already exists: {code}")
    if not term:
        # B-06 4단계: category_id는 더 이상 설정하지 않는다(nullable, 구형 카테고리와
        # 무관하게 항상 None으로 생성) - 귀속은 아래 _link_keyword_from_admin이 만드는
        # prompt_subcategory_keywords 링크가 전담한다.
        term = PromptTerm(code=code)
        session.add(term)
    term.code = code
    term.canonical_key = _optional_admin_string(payload.get("canonicalKey")) or code
    term.label_ko = _required_admin_string(payload, "labelKo")
    term.label_en = _required_admin_string(payload, "labelEn")
    term.description = _optional_admin_string(payload.get("description"))
    term.prompt_text = _optional_admin_string(payload.get("promptText")) or ""
    term.negative_text = _optional_admin_string(payload.get("negativeText"))
    term.risk_level = (_optional_admin_string(payload.get("riskLevel")) or "NONE").upper()
    term.metadata_json = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    term.sort_order = _optional_admin_int(payload.get("sortOrder")) or 100
    term.is_active = True
    term.updated_at = datetime.utcnow()
    session.flush()
    _link_keyword_from_admin(session, subcategory.id, term)
    session.commit()
    return prompt_catalog(session)


def deactivate_prompt_term(session: Session, term_id: int) -> dict:
    term = session.get(PromptTerm, term_id)
    if not term:
        raise ValueError("Prompt term not found")
    term.is_active = False
    term.updated_at = datetime.utcnow()
    # B-06 3단계: 구형 prompt_category_terms 대신 신형 prompt_subcategory_keywords가
    # 권한 있는 카테고리화 관계다.
    links = session.scalars(
        select(PromptSubcategoryKeyword).where(PromptSubcategoryKeyword.keyword_id == term.id)
    ).all()
    for link in links:
        link.active_yn = False
    session.commit()
    return prompt_catalog(session)


def _link_keyword_from_admin(session: Session, subcategory_id: int, term: PromptTerm) -> None:
    """B-06 3단계: 관리자 용어 생성/수정 시 prompt_subcategory_keywords 링크를
    lazy sync에 기대지 않고 이 함수가 직접, 명시적으로 만든다."""
    default_polarity = "NEGATIVE" if term.negative_text and not term.prompt_text else "POSITIVE"
    link = session.get(PromptSubcategoryKeyword, {"subcategory_id": subcategory_id, "keyword_id": term.id})
    if not link:
        link = PromptSubcategoryKeyword(subcategory_id=subcategory_id, keyword_id=term.id)
        session.add(link)
    link.default_polarity = default_polarity
    link.sort_order = term.sort_order
    link.active_yn = True


def _prompt_group_from_payload(session: Session, payload: dict) -> PromptCategoryGroup | None:
    group_id = _optional_admin_int(payload.get("groupId"))
    if group_id:
        group = session.get(PromptCategoryGroup, group_id)
        if not group or not group.is_active:
            raise ValueError("Active prompt category group not found")
        return group
    group_code = _optional_admin_string(payload.get("groupCode"))
    if not group_code:
        return None
    return session.scalar(select(PromptCategoryGroup).where(PromptCategoryGroup.code == group_code, PromptCategoryGroup.is_active.is_(True)))


def _required_admin_string(payload: dict, key: str) -> str:
    value = _optional_admin_string(payload.get(key))
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_admin_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_admin_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def scene_json_v1_schema() -> dict:
    schema_path = get_settings().project_root / SCENE_JSON_V1_SCHEMA_PATH
    with schema_path.open("r", encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def scene_json_v1_validator():
    if Draft202012Validator is None:
        return None
    schema = scene_json_v1_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def scene_json_v1_schema_validation_available() -> bool:
    return scene_json_v1_validator() is not None


def _subcategory_map_for_terms(session: Session, term_ids: list[int]) -> dict[int, PromptSubcategory]:
    """B-06 2단계: term.id(=keyword_id)로 신형 계층의 PromptSubcategory를 찾는다.

    PromptSubcategoryKeyword.keyword_id는 prompt_terms.id를 가리키는 FK이므로
    (models.py 참조) "keyword id"와 "term id"는 동일한 값 공간이다. 즉
    build_scene_json()/generate_prompt() 전 구간에서 다루는 termIds/usedTermIds는
    전부 PromptTerm.id 값이며, 이 값을 그대로 keyword_id로 사용해 신형 계층을
    조회할 수 있다.
    """
    if not term_ids:
        return {}
    links = session.scalars(
        select(PromptSubcategoryKeyword)
        .options(selectinload(PromptSubcategoryKeyword.subcategory))
        .where(PromptSubcategoryKeyword.keyword_id.in_(term_ids), PromptSubcategoryKeyword.active_yn.is_(True))
    ).all()
    mapping: dict[int, PromptSubcategory] = {}
    for link in links:
        if link.subcategory and link.subcategory.is_active:
            mapping.setdefault(link.keyword_id, link.subcategory)
    return mapping


def _term_group_key(term: PromptTerm, subcategory: PromptSubcategory | None) -> str:
    """B-06 4단계: 서브카테고리 링크가 있으면 그 code를 그룹 키로 쓴다. 링크가 없는
    경우(관리자 생성/시드 경로 양쪽 다 항상 링크를 만들므로 정상 상태라면 발생하지
    않음)는 term.category로 폴백할 수 없다 - category_id가 nullable로 바뀌어(4단계
    마이그레이션) term.category가 None일 수 있기 때문이다. 대신 term 자신의 code로
    만든 고유 키를 써서 크래시 없이 안전하게 처리한다."""
    return subcategory.code if subcategory else f"_unlinked_{term.code}"


def build_scene_json(session: Session, payload: dict) -> dict:
    # B-06 4단계: 카테고리/서브카테고리 귀속 판단은 신형 계층
    # (prompt_subcategories/prompt_subcategory_keywords)만 사용한다. 구형<->신형
    # lazy 브릿지(sync_prompt_catalog_hierarchy)는 admin CRUD와 시드 함수 양쪽 다 신형
    # 계층에 직접 쓰게 되면서 더 이상 필요 없어 제거했다.
    term_ids = [int(value) for value in payload.get("termIds") or [] if str(value).isdigit()]
    terms = session.scalars(
        select(PromptTerm)
        .where(PromptTerm.id.in_(term_ids), PromptTerm.is_active.is_(True))
        .order_by(PromptTerm.sort_order, PromptTerm.code)
    ).all() if term_ids else []
    constraints = {
        "preserve_identity": True,
        "avoid_new_objects": True,
        "i2v_mode": True,
        **(payload.get("constraints") or {}),
    }
    terms, validation_warnings = _validate_and_normalize_terms(session, terms)
    terms, relation_warnings = _apply_term_relations(session, terms)
    terms, relation_validation_warnings = _validate_and_normalize_terms(session, terms)
    model_profile = _resolve_model_profile(session, payload)
    renderings = _term_rendering_map(session, terms, model_profile)
    grouped: dict[str, list[str]] = {}
    positive_parts = []
    negative_parts = []
    subcategory_by_term_id = _subcategory_map_for_terms(session, [term.id for term in terms])
    for term in terms:
        subcategory = subcategory_by_term_id.get(term.id)
        group_key = _term_group_key(term, subcategory).lower()
        grouped.setdefault(group_key, []).append(term.label_en)
        positive_text = _render_term_text(term, renderings, "POSITIVE")
        negative_text = _render_term_text(term, renderings, "NEGATIVE")
        if positive_text:
            positive_parts.append(positive_text)
        if negative_text:
            negative_parts.append(negative_text)

    # 2026-08-12: 중복 경고 제거 - 아래 _dedupe_warnings 정의부 주석 참조.
    warnings = _dedupe_warnings([*validation_warnings, *relation_warnings, *relation_validation_warnings])
    for rule in session.scalars(select(PromptRule).where(PromptRule.is_active.is_(True))).all():
        if not _rule_applies(rule.condition_json, constraints):
            continue
        action = rule.action_json or {}
        positive_parts.extend(action.get("positive_append") or [])
        negative_parts.extend(action.get("negative_append") or [])
        if rule.severity in {"warning", "error"}:
            warnings.append({"code": rule.code, "message": rule.name, "severity": rule.severity})

    scene, scene_warnings = _build_scene_v1(payload, grouped, constraints)
    warnings.extend(scene_warnings)
    _raise_for_scene_schema_errors(scene)
    # B-06 확정 사항: used_term_ids/selected_term_ids는 PromptTerm.id다. 신형 계층의
    # PromptSubcategoryKeyword.keyword_id는 prompt_terms.id를 가리키는 FK라 별도
    # entity가 아니며(models.py), 값 공간이 term id와 완전히 같다. 따라서 프론트가
    # 카탈로그(구형 categories든 신형 groups[].subcategories[].terms든)에서 얻어
    # 제출하는 termIds/usedTermIds를 그대로 keyword_id로 사용해 신형 계층을 조회해도
    # 된다 — 실제로 _subcategory_map_for_terms()가 이렇게 한다.
    used_term_ids = [term.id for term in terms]
    request = PromptGenerationRequest(
        id=f"prompt_req_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        workflow_id=payload.get("workflowId"),
        segment_index=payload.get("segmentIndex"),
        language=payload.get("language") or "ko",
        scene_json=scene,
        constraints_json=constraints,
        selected_term_ids=used_term_ids,
        status="draft",
        created_by=None,
    )
    session.add(request)
    output = PromptGenerationOutput(
        id=f"prompt_out_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        request_id=request.id,
        provider="builder",
        positive_prompt=", ".join(_dedupe(positive_parts)),
        negative_prompt=", ".join(_dedupe(negative_parts)),
        used_term_ids=used_term_ids,
        added_term_ids=[],
        warnings_json=warnings,
        raw_json={"scene": scene, "constraints": constraints, "modelProfile": _model_profile_payload(model_profile)},
    )
    session.add(output)
    session.commit()
    return {
        "requestId": request.id,
        "outputId": output.id,
        "provider": output.provider,
        "workflowId": request.workflow_id,
        "segmentIndex": request.segment_index,
        "language": request.language,
        "scene": scene,
        "constraints": constraints,
        "positivePromptDraft": output.positive_prompt,
        "negativePromptDraft": output.negative_prompt,
        "usedTermIds": used_term_ids,
        "modelProfile": _model_profile_payload(model_profile),
        "warnings": warnings,
    }


def _validate_and_normalize_terms(session: Session, terms: list[PromptTerm]) -> tuple[list[PromptTerm], list[dict]]:
    # B-06 4단계: 선택/필수 검증은 신형 PromptSubcategory만 기준으로 한다. 서브카테고리
    # 링크가 없는 용어(정상 상태라면 발생하지 않음)는 _term_group_key로 안전하게
    # 처리하고, 선택 제한은 두지 않는다(제한을 걸 근거가 되는 서브카테고리 자체가 없음).
    warnings = []
    subcategory_by_term_id = _subcategory_map_for_terms(session, [term.id for term in terms])
    grouped_terms: dict[str, list[PromptTerm]] = {}
    for term in terms:
        subcategory = subcategory_by_term_id.get(term.id)
        grouped_terms.setdefault(_term_group_key(term, subcategory), []).append(term)

    normalized_terms: list[PromptTerm] = []
    for group_key, group_terms in grouped_terms.items():
        subcategory = subcategory_by_term_id.get(group_terms[0].id)
        if subcategory:
            selection_type = subcategory.selection_type
            max_select_count = subcategory.max_select_count
        else:
            selection_type = "MULTIPLE"
            max_select_count = None
        limit = 1 if selection_type.upper() == "SINGLE" else max_select_count
        if limit and len(group_terms) > limit:
            warnings.append({
                "code": "selection_limit_trimmed",
                "message": f"{group_key} accepts up to {limit} term(s); extra terms were ignored.",
                "severity": "warning",
            })
            group_terms = group_terms[:limit]
        normalized_terms.extend(group_terms)

    selected_group_keys = {
        _term_group_key(term, subcategory_by_term_id.get(term.id))
        for term in normalized_terms
    }
    required_subcategories = session.scalars(
        select(PromptSubcategory)
        .where(PromptSubcategory.is_active.is_(True), PromptSubcategory.required_yn.is_(True))
        .order_by(PromptSubcategory.sort_order)
    ).all()
    for subcategory in required_subcategories:
        if subcategory.code not in selected_group_keys:
            warnings.append({
                "code": "required_category_missing",
                "message": f"{subcategory.code} is required for a complete prompt scene.",
                "severity": "warning",
            })

    return normalized_terms, warnings


def _apply_term_relations(session: Session, terms: list[PromptTerm]) -> tuple[list[PromptTerm], list[dict]]:
    selected_by_id = {term.id: term for term in terms}
    if not selected_by_id:
        return terms, []

    warnings = []
    relations = session.scalars(
        select(PromptTermRelation)
        .options(
            selectinload(PromptTermRelation.source_term),
            selectinload(PromptTermRelation.target_term),
        )
        .where(PromptTermRelation.source_term_id.in_(selected_by_id.keys()))
        .order_by(PromptTermRelation.weight.desc(), PromptTermRelation.relation_type)
    ).all()
    for relation in relations:
        source = relation.source_term
        target = relation.target_term
        if not source or not target or not target.is_active:
            continue
        relation_type = relation.relation_type.upper()
        message = (relation.metadata_json or {}).get("message")
        if relation_type == "IMPLY" and target.id not in selected_by_id:
            selected_by_id[target.id] = target
            warnings.append({
                "code": "term_implied",
                "message": message or f"{target.label_en} was added because {source.label_en} implies it.",
                "severity": "info",
                "sourceTermId": source.id,
                "targetTermId": target.id,
                "relationType": relation_type,
            })
        elif relation_type == "RECOMMEND" and target.id not in selected_by_id:
            warnings.append({
                "code": "term_recommended",
                "message": message or f"{target.label_en} is recommended with {source.label_en}.",
                "severity": "info",
                "sourceTermId": source.id,
                "targetTermId": target.id,
                "relationType": relation_type,
            })
        elif relation_type == "EXCLUDE" and target.id in selected_by_id:
            warnings.append({
                "code": "term_relation_conflict",
                "message": message or f"{source.label_en} conflicts with {target.label_en}.",
                "severity": "warning",
                "sourceTermId": source.id,
                "targetTermId": target.id,
                "relationType": relation_type,
            })
    # B-06 4단계: 최종 정렬 기준은 신형 서브카테고리의 sort_order만 사용한다. 서브카테고리
    # 링크가 없는 예외적인 경우(정상 상태라면 발생하지 않음)는 term 자신의 sort_order를
    # 그룹 정렬값으로도 재사용해 안전하게 처리한다(더 이상 term.category로 폴백할 수
    # 없음 - category_id가 nullable이라 None일 수 있다).
    subcategory_by_term_id = _subcategory_map_for_terms(session, list(selected_by_id.keys()))

    def _term_sort_key(term: PromptTerm) -> tuple:
        subcategory = subcategory_by_term_id.get(term.id)
        sort_order = subcategory.sort_order if subcategory else term.sort_order
        return (sort_order, term.sort_order, term.code)

    return sorted(selected_by_id.values(), key=_term_sort_key), warnings


def _resolve_model_profile(session: Session, payload: dict) -> ModelProfile | None:
    model_profile_id = payload.get("modelProfileId")
    if str(model_profile_id or "").isdigit():
        profile = session.get(ModelProfile, int(model_profile_id))
        if profile and profile.active_yn:
            return profile

    model_family = str(payload.get("modelFamily") or "WAN").strip()
    model_name = str(payload.get("modelName") or "").strip()
    filters = [ModelProfile.active_yn.is_(True)]
    if model_family:
        filters.append(ModelProfile.model_family == model_family)
    if model_name:
        filters.append(ModelProfile.model_name == model_name)
    profile = session.scalars(
        select(ModelProfile)
        .where(*filters)
        .order_by(ModelProfile.id)
    ).first()
    if profile:
        return profile
    return session.scalars(
        select(ModelProfile)
        .where(ModelProfile.active_yn.is_(True))
        .order_by(ModelProfile.id)
    ).first()


def _term_rendering_map(
    session: Session,
    terms: list[PromptTerm],
    model_profile: ModelProfile | None,
) -> dict[tuple[int, str], str]:
    if not terms or not model_profile:
        return {}
    term_ids = [term.id for term in terms]
    renderings = session.scalars(
        select(PromptTermRendering)
        .where(
            PromptTermRendering.term_id.in_(term_ids),
            PromptTermRendering.active_yn.is_(True),
            PromptTermRendering.model_profile_id == model_profile.id,
            PromptTermRendering.language_code == model_profile.prompt_language,
        )
        .order_by(PromptTermRendering.term_id, PromptTermRendering.polarity)
    ).all()
    return {
        (rendering.term_id, rendering.polarity.upper()): rendering.render_text
        for rendering in renderings
    }


def _render_term_text(term: PromptTerm, renderings: dict[tuple[int, str], str], polarity: str) -> str:
    rendered = renderings.get((term.id, polarity.upper()))
    if rendered is not None:
        return rendered
    if polarity.upper() == "NEGATIVE":
        return term.negative_text or ""
    return term.prompt_text or ""


def _model_profile_payload(model_profile: ModelProfile | None) -> dict | None:
    if not model_profile:
        return None
    return {
        "id": model_profile.id,
        "modelFamily": model_profile.model_family,
        "modelName": model_profile.model_name,
        "modelVersion": model_profile.model_version,
        "promptLanguage": model_profile.prompt_language,
    }


def _build_scene_v1(payload: dict, grouped: dict[str, list[str]], constraints: dict) -> tuple[dict, list[dict]]:
    subject_values = grouped.get("subject_type", [])
    actions = [
        *grouped.get("character_action", []),
        *grouped.get("object_action", []),
        *grouped.get("action", []),
    ]
    appearance_attributes = _scene_summary_appearance_terms([
        *grouped.get("character_appearance", []),
        *grouped.get("clothing", []),
        *grouped.get("pose", []),
        *grouped.get("gaze_direction", []),
        *grouped.get("facial_expression", []),
        *grouped.get("emotion", []),
    ])
    negative_terms = [
        *grouped.get("negative_anatomy", []),
        *grouped.get("negative_artifact", []),
        *grouped.get("negative_temporal", []),
        *grouped.get("negative_quality", []),
        *grouped.get("negative_camera", []),
        *grouped.get("negative_text", []),
        *grouped.get("negative_identity", []),
        *grouped.get("negative_exclusion", []),
        *grouped.get("negative_tag", []),
    ]
    description = _clean_scene_string(payload.get("description"))
    summary_parts = _dedupe([
        *subject_values,
        *appearance_attributes,
        *actions,
    ])
    scene_item = {
        "sequenceNo": 1,
        "summary": ", ".join(summary_parts),
        "description": description,
        "camera": {
            "framing": [
                *grouped.get("camera_framing", []),
                *grouped.get("shot_type", []),
            ],
            "movement": [
                *grouped.get("camera_movement", []),
                *grouped.get("camera_motion", []),
            ],
            "angle": grouped.get("camera_angle", []),
            "lens": [
                *grouped.get("lens_type", []),
                *grouped.get("camera_lens", []),
            ],
            "focus": [
                *grouped.get("focus_style", []),
                *grouped.get("camera_focus", []),
            ],
        },
        "environment": {
            "background": grouped.get("background", []),
            "location": grouped.get("location", []),
            "timeOfDay": grouped.get("time_of_day", []),
            "weather": grouped.get("weather", []),
        },
        "style": {
            "lighting": grouped.get("lighting", []),
            "colorPalette": [
                *grouped.get("color_palette", []),
                *grouped.get("color_style", []),
            ],
            "mood": [
                *grouped.get("video_mood", []),
                *grouped.get("mood", []),
            ],
            "animationStyle": [
                *grouped.get("animation_style", []),
                *grouped.get("scene_transition", []),
            ],
            "renderingStyle": grouped.get("rendering_style", []),
        },
        "motion": {
            "speed": [
                *grouped.get("motion_speed", []),
                *grouped.get("shot_duration", []),
            ],
            "intensity": grouped.get("motion_intensity", []),
        },
        "quality": grouped.get("quality_tag", []),
        "negativeTerms": negative_terms,
    }
    return {
        "version": "1.0",
        "workflowId": payload.get("workflowId"),
        "segmentIndex": payload.get("segmentIndex"),
        "language": payload.get("language") or "ko",
        "genres": grouped.get("genre", []),
        "contentRating": grouped.get("content_rating", []),
        "scenes": [scene_item],
        "constraints": constraints,
    }, []


def _scene_summary_appearance_terms(values: list[str]) -> list[str]:
    preservation_terms = {
        "preserve identity",
        "preserve the same identity",
        "preserve the same identity, outfit, and proportions from the input image",
        "preserve identity from the input image",
    }
    return [
        value
        for value in values
        if _clean_scene_string(value).lower() not in preservation_terms
    ]


def _clean_scene_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _looks_like_scene_v1(scene: dict) -> bool:
    return scene.get("version") == "1.0" or isinstance(scene.get("scenes"), list)


def _raise_for_scene_schema_errors(scene: dict) -> None:
    errors = validate_scene_json_v1_with_schema(scene)
    if errors:
        details = "; ".join(error["message"] for error in errors)
        raise ValueError(f"Scene JSON v1 validation failed: {details}")


def validate_scene_json_v1_with_schema(scene: dict) -> list[dict]:
    validator = scene_json_v1_validator()
    if validator is None:
        return validate_scene_json_v1(scene)
    schema_errors = [
        _schema_error(_format_jsonschema_error(error))
        for error in sorted(validator.iter_errors(scene), key=_jsonschema_error_sort_key)
    ]
    if schema_errors:
        return schema_errors
    return validate_scene_json_v1(scene)


def _jsonschema_error_sort_key(error) -> tuple:
    return tuple(str(path_part) for path_part in error.absolute_path)


def _format_jsonschema_error(error) -> str:
    path = "scene"
    for path_part in error.absolute_path:
        if isinstance(path_part, int):
            path = f"{path}[{path_part}]"
        else:
            path = f"{path}.{path_part}"
    return f"{path}: {error.message}"


def validate_scene_json_v1(scene: dict) -> list[dict]:
    errors = []
    _require_value(errors, scene, "version", "1.0", "scene.version")
    _require_optional_string(errors, scene, "workflowId", "scene.workflowId")
    _require_optional_int(errors, scene, "segmentIndex", "scene.segmentIndex")
    _require_string(errors, scene, "language", "scene.language")
    _require_string_list(errors, scene, "genres", "scene.genres")
    _require_string_list(errors, scene, "contentRating", "scene.contentRating")
    _require_dict(errors, scene, "constraints", "scene.constraints")

    scenes = scene.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errors.append(_schema_error("scene.scenes must be a non-empty array"))
        return errors
    for scene_index, scene_item in enumerate(scenes):
        path = f"scene.scenes[{scene_index}]"
        if not isinstance(scene_item, dict):
            errors.append(_schema_error(f"{path} must be an object"))
            continue
        _require_int(errors, scene_item, "sequenceNo", f"{path}.sequenceNo")
        _require_string(errors, scene_item, "summary", f"{path}.summary")
        _require_string(errors, scene_item, "description", f"{path}.description")
        _validate_named_string_list_section(errors, scene_item, "camera", ["framing", "movement", "angle", "lens", "focus"], path)
        _validate_named_string_list_section(errors, scene_item, "environment", ["background", "location", "timeOfDay", "weather"], path)
        _validate_named_string_list_section(errors, scene_item, "style", ["lighting", "colorPalette", "mood", "animationStyle", "renderingStyle"], path)
        _validate_named_string_list_section(errors, scene_item, "motion", ["speed", "intensity"], path)
        _require_string_list(errors, scene_item, "quality", f"{path}.quality")
        _require_string_list(errors, scene_item, "negativeTerms", f"{path}.negativeTerms")
    return errors


def _validate_named_string_list_section(errors: list[dict], source: dict, key: str, child_keys: list[str], parent_path: str) -> None:
    section = source.get(key)
    path = f"{parent_path}.{key}"
    if not isinstance(section, dict):
        errors.append(_schema_error(f"{path} must be an object"))
        return
    for child_key in child_keys:
        _require_string_list(errors, section, child_key, f"{path}.{child_key}")


def _require_value(errors: list[dict], source: dict, key: str, expected: object, path: str) -> None:
    if source.get(key) != expected:
        errors.append(_schema_error(f"{path} must be {expected!r}"))


def _require_dict(errors: list[dict], source: dict, key: str, path: str) -> None:
    if not isinstance(source.get(key), dict):
        errors.append(_schema_error(f"{path} must be an object"))


def _require_string(errors: list[dict], source: dict, key: str, path: str) -> None:
    if not isinstance(source.get(key), str):
        errors.append(_schema_error(f"{path} must be a string"))


def _require_optional_string(errors: list[dict], source: dict, key: str, path: str) -> None:
    value = source.get(key)
    if value is not None and not isinstance(value, str):
        errors.append(_schema_error(f"{path} must be a string or null"))


def _require_int(errors: list[dict], source: dict, key: str, path: str) -> None:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(_schema_error(f"{path} must be an integer"))


def _require_optional_int(errors: list[dict], source: dict, key: str, path: str) -> None:
    value = source.get(key)
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        errors.append(_schema_error(f"{path} must be an integer or null"))


def _require_string_list(errors: list[dict], source: dict, key: str, path: str) -> None:
    value = source.get(key)
    if not isinstance(value, list):
        errors.append(_schema_error(f"{path} must be an array"))
        return
    if any(not isinstance(item, str) for item in value):
        errors.append(_schema_error(f"{path} must contain only strings"))


def _schema_error(message: str) -> dict:
    return {"code": "scene_schema_invalid", "message": message, "severity": "error"}


def generate_prompt(session: Session, payload: dict, *, created_by: str | None = None) -> dict:
    settings = get_settings()
    provider = (payload.get("provider") or settings.prompt_llm_provider or "mock").strip().lower()
    scene = payload.get("scene")
    if not isinstance(scene, dict):
        raise ValueError("scene must be a JSON object")
    if _looks_like_scene_v1(scene):
        _raise_for_scene_schema_errors(scene)
    constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
    # B-06 확정 사항: 이 함수는 신형/구형 어느 계층도 직접 조회하지 않는다 - 프론트가
    # scene JSON을 만들 때(build_scene_json) 이미 확정한 termIds/usedTermIds를 그대로
    # 감사 기록용으로 저장할 뿐이다. 그 값은 PromptTerm.id이며(위 build_scene_json의
    # used_term_ids 주석 참조), keyword_id와 동일한 값 공간이라 신형 계층에도 그대로
    # 대응된다.
    selected_term_ids = [int(value) for value in payload.get("termIds") or payload.get("usedTermIds") or [] if str(value).isdigit()]
    language = payload.get("language") or "ko"

    if uses_async_runpod_vllm(settings, provider):
        return _submit_async_runpod_prompt_generation(
            session,
            payload=payload,
            scene=scene,
            constraints=constraints,
            selected_term_ids=selected_term_ids,
            language=language,
            provider=provider,
            created_by=created_by,
        )

    raw_generation = {"scene": scene, "constraints": constraints, "provider": provider}
    if provider == "mock":
        generated = _mock_llm_prompt(scene, constraints)
        positive_prompt = generated["positivePrompt"]
        negative_prompt = generated["negativePrompt"]
        warnings = generated["warnings"]
    else:
        system_prompt = active_prompt_system_prompt_text(session)
        llm_result = generate_with_prompt_llm(
            settings,
            scene=scene,
            constraints=constraints,
            language=language,
            system_prompt=system_prompt,
        )
        positive_prompt = llm_result.positive_prompt
        negative_prompt = llm_result.negative_prompt
        warnings = llm_result.warnings
        raw_generation["llmResponse"] = llm_result.raw_response
        raw_generation["systemPromptCode"] = "qwen_wan_i2v_positive"

    request = PromptGenerationRequest(
        id=f"prompt_req_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        workflow_id=payload.get("workflowId"),
        segment_index=payload.get("segmentIndex"),
        language=language,
        scene_json=scene,
        constraints_json=constraints,
        selected_term_ids=selected_term_ids,
        status="generated",
        created_by=created_by,
    )
    session.add(request)
    output = PromptGenerationOutput(
        id=f"prompt_out_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        request_id=request.id,
        provider=provider,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        used_term_ids=selected_term_ids,
        added_term_ids=[],
        warnings_json=warnings,
        raw_json=raw_generation,
    )
    session.add(output)
    session.commit()
    return {
        "requestId": request.id,
        "outputId": output.id,
        "provider": provider,
        "workflowId": request.workflow_id,
        "segmentIndex": request.segment_index,
        "language": language,
        "scene": scene,
        "constraints": constraints,
        "positivePrompt": output.positive_prompt,
        "negativePrompt": output.negative_prompt,
        "usedTermIds": selected_term_ids,
        "warnings": output.warnings_json,
    }


def get_prompt_generation_status(session: Session, request_id: str) -> dict:
    request = session.get(PromptGenerationRequest, request_id)
    if not request:
        raise ValueError("Prompt generation request was not found.")
    output = session.scalar(
        select(PromptGenerationOutput)
        .where(PromptGenerationOutput.request_id == request.id)
        .order_by(PromptGenerationOutput.created_at.desc())
    )
    return _prompt_generation_payload(request, output)


def monitor_active_prompt_generations() -> dict:
    """Refresh queued Qwen jobs independently of browser/API request lifetime."""
    from backend.app.db.session import SessionLocal

    settings = get_settings()
    # RunPod endpoint / worker implementations can report the same waiting
    # period as IN_QUEUE, QUEUED, or SUBMITTED. Keep every non-terminal form
    # eligible for the background monitor instead of leaving a request stale.
    active_statuses = {"SUBMITTING", "SUBMITTED", "IN_QUEUE", "QUEUED", "IN_PROGRESS", "RUNNING"}
    refreshed = 0
    failures: list[str] = []
    with SessionLocal() as session:
        requests = session.scalars(
            select(PromptGenerationRequest).where(
                PromptGenerationRequest.external_job_id.is_not(None),
                PromptGenerationRequest.status.in_(active_statuses),
            )
        ).all()
        for request in requests:
            try:
                _refresh_async_runpod_prompt_generation(session, request, settings)
                refreshed += 1
            except Exception as exc:
                # A temporary RunPod status failure must not erase a valid queued job.
                failures.append(f"{request.id}: {exc}")
        session.commit()
    return {"checked": len(requests), "refreshed": refreshed, "failures": failures}


def _submit_async_runpod_prompt_generation(
    session: Session,
    *,
    payload: dict,
    scene: dict,
    constraints: dict,
    selected_term_ids: list[int],
    language: str,
    provider: str,
    created_by: str | None,
) -> dict:
    settings = get_settings()
    request = PromptGenerationRequest(
        id=f"prompt_req_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        workflow_id=payload.get("workflowId"),
        segment_index=payload.get("segmentIndex"),
        language=language,
        scene_json=scene,
        constraints_json=constraints,
        selected_term_ids=selected_term_ids,
        status="SUBMITTING",
        created_by=created_by,
    )
    session.add(request)
    session.commit()

    try:
        submission = submit_runpod_vllm_job(
            settings,
            scene=scene,
            constraints=constraints,
            language=language,
            system_prompt=active_prompt_system_prompt_text(session),
        )
        request.external_job_id = str(submission["id"])
        request.status = str(submission.get("status") or "IN_QUEUE").upper()
        request.failure_message = None
        session.commit()
    except Exception as exc:
        request.status = "FAILED"
        request.failure_message = str(exc)
        session.commit()
        raise RuntimeError(f"Qwen prompt request could not be submitted: {exc}") from exc
    return _prompt_generation_payload(request, None, submit_response=submission)


def _refresh_async_runpod_prompt_generation(session: Session, request: PromptGenerationRequest, settings) -> None:
    if not request.external_job_id:
        return
    age_seconds = max(0, (datetime.utcnow() - request.created_at).total_seconds())
    if age_seconds > settings.prompt_llm_cold_start_timeout:
        try:
            cancel_runpod_vllm_job(settings, request.external_job_id)
        except Exception:
            pass
        request.status = "TIMED_OUT"
        request.failure_message = f"Qwen prompt generation exceeded {settings.prompt_llm_cold_start_timeout} seconds."
        return

    status_response = get_runpod_vllm_job_status(settings, request.external_job_id)
    status = str(status_response.get("status") or "UNKNOWN").upper()
    request.status = status
    if status not in RUNPOD_TERMINAL_STATES:
        return
    if status not in {"COMPLETED", "SUCCEEDED", "SUCCESS"}:
        request.failure_message = str(status_response.get("error") or status_response.get("message") or f"RunPod job finished with {status}.")
        return

    existing_output = session.scalar(
        select(PromptGenerationOutput).where(PromptGenerationOutput.request_id == request.id)
    )
    if existing_output:
        request.status = "COMPLETED"
        return
    try:
        result = parse_runpod_vllm_job_result(status_response, scene=request.scene_json or {})
    except Exception as exc:
        request.status = "FAILED"
        request.failure_message = f"Qwen returned an invalid prompt response: {exc}"
        return
    output = PromptGenerationOutput(
        id=f"prompt_out_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        request_id=request.id,
        provider="runpod_vllm",
        positive_prompt=result.positive_prompt,
        negative_prompt=result.negative_prompt,
        used_term_ids=request.selected_term_ids or [],
        added_term_ids=[],
        warnings_json=result.warnings,
        raw_json={
            "scene": request.scene_json,
            "constraints": request.constraints_json,
            "provider": "runpod_vllm",
            "llmResponse": result.raw_response,
            "systemPromptCode": "qwen_wan_i2v_positive",
        },
    )
    session.add(output)
    request.status = "COMPLETED"
    request.failure_message = None


def _prompt_generation_payload(
    request: PromptGenerationRequest,
    output: PromptGenerationOutput | None,
    *,
    submit_response: dict | None = None,
) -> dict:
    status = str(request.status or "UNKNOWN").upper()
    payload = {
        "requestId": request.id,
        "outputId": output.id if output else None,
        "provider": output.provider if output else "runpod_vllm",
        "workflowId": request.workflow_id,
        "segmentIndex": request.segment_index,
        "language": request.language,
        "scene": request.scene_json or {},
        "constraints": request.constraints_json or {},
        "usedTermIds": request.selected_term_ids or [],
        "status": status,
        "externalJobId": request.external_job_id,
        "failureMessage": request.failure_message,
        "pollIntervalSeconds": get_settings().prompt_llm_poll_interval,
    }
    if submit_response:
        payload["runpodSubmit"] = submit_response
    if output:
        payload.update(
            {
                "positivePrompt": output.positive_prompt,
                "negativePrompt": output.negative_prompt,
                "warnings": output.warnings_json or [],
            }
        )
    return payload


def save_prompt_feedback(session: Session, payload: dict) -> dict:
    """B-02: 프롬프트 평가 이중 저장 정리. `task_prompts.quality_rating`(영상 결과 평가,
    `/api/jobs/{id}/prompts/{n}/review`가 담당)과 이 함수가 쓰는 `prompt_feedback.rating`
    (프롬프트 생성 품질 평가)은 역할이 고정되어 있다 - 이 함수는 후자만 담당하며 전자의
    컬럼은 절대 건드리지 않는다. 화면도 `3f` Run 상세 한 곳에서만 이 API를 호출하도록
    구현되어 있다(세그먼트 편집 화면인 PromptBuilderModal에는 평가 UI가 없다).

    `taskId`를 필수로 받는 이유: prompt_feedback.task_id가 채워져 있어야 두 저장소의
    기록이 연결된다(TASKS.md B-02 완료 기준). output_id만으로는 어떤 task_prompts 행과
    짝인지 결정할 수 없다 - PromptGenerationOutput/Request는 workflow_task 생성 이전에도
    만들어질 수 있고 workflow_id+segment_index만으로는 재실행 시 여러 workflow_tasks 행과
    겹칠 수 있어 신뢰할 수 있는 join 키가 아니다. 그래서 taskId는 프론트(3f 화면에서 이미
    알고 있는 selectedHistoryTaskId)가 명시적으로 보내야 한다.
    """
    output_id = str(payload.get("outputId") or "").strip()
    if not output_id:
        raise ValueError("outputId is required")
    output = session.get(PromptGenerationOutput, output_id)
    if not output:
        raise ValueError(f"Prompt output not found: {output_id}")
    task_id = str(payload.get("taskId") or "").strip()
    if not task_id:
        raise ValueError("taskId is required")
    if not session.get(WorkflowTask, task_id):
        raise ValueError(f"Task not found: {task_id}")
    rating = payload.get("rating")
    feedback = PromptFeedback(
        id=f"prompt_fb_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        output_id=output_id,
        task_id=task_id,
        rating=int(rating) if rating not in {None, ""} else None,
        edited_positive_prompt=payload.get("editedPositivePrompt"),
        edited_negative_prompt=payload.get("editedNegativePrompt"),
        notes=payload.get("notes"),
        created_by=None,
    )
    session.add(feedback)
    session.commit()
    return {"id": feedback.id, "outputId": feedback.output_id, "taskId": feedback.task_id, "rating": feedback.rating}


def _rule_applies(condition: dict, constraints: dict) -> bool:
    return all(constraints.get(key) == value for key, value in (condition or {}).items())


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


# 2026-08-12: 사용자 신고 - 2b 화면에 "SUBJECT_TYPE is required for a complete
# prompt scene." 같은 경고가 두 번씩 겹쳐 표시됨. 원인: build_scene_json이
# _validate_and_normalize_terms를 관계(rule) 적용 전/후 두 번 호출하는데(관계가
# 필수 서브카테고리를 채워줄 수도 있어 재검증이 필요함), 관계로도 채워지지 않는
# 누락은 두 번의 호출 모두에서 독립적으로 같은 "required_category_missing" 경고를
# 만들어 최종 warnings 리스트에 그대로 중복 누적됐다. 경고 자체를 한 번만 만들도록
# 호출 구조를 바꾸는 대신(재검증 로직이 얽혀 있어 위험도가 높음), 최종 합산 단계에서
# (code, message) 기준으로 중복만 제거한다 - 순서는 유지되고 서로 다른 경고는
# 그대로 보존된다.
def _dedupe_warnings(warnings: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for warning in warnings:
        key = (warning.get("code"), warning.get("message"))
        if key in seen:
            continue
        seen.add(key)
        result.append(warning)
    return result


def _mock_llm_prompt(scene: dict, constraints: dict) -> dict:
    scene_item = _first_scene_item(scene)
    genre = _join_scene_values(scene.get("genres") or scene.get("genre")) or "cinematic image-to-video shot"
    subject = _scene_subject(scene) or "the subject from the input image"
    scene_detail = _join_scene_values([scene_item.get("description"), scene_item.get("summary")])
    action = scene_detail or _join_scene_values(scene.get("action")) or "subtle natural motion"
    camera_section = scene_item.get("camera") if isinstance(scene_item.get("camera"), dict) else scene.get("camera") or {}
    camera = _join_scene_values(camera_section.get("movement") or camera_section.get("motion")) or "stable camera movement"
    shot_type = _join_scene_values(camera_section.get("framing") or camera_section.get("shotType"))
    style_section = scene_item.get("style") if isinstance(scene_item.get("style"), dict) else scene.get("style") or {}
    style = _join_scene_values([
        *(_listify(style_section.get("lighting"))),
        *(_listify(style_section.get("colorPalette") or style_section.get("color"))),
        *(_listify(style_section.get("mood"))),
    ])
    quality = _join_scene_values(scene_item.get("quality") or scene.get("quality")) or "stable motion, coherent frames"
    positive_parts = [genre, subject, action, camera, shot_type, style, quality]
    negative_parts = [
        "distorted anatomy",
        "warped body",
        "deformed face",
        "extra limbs",
        "blur",
        "flicker",
        "watermark",
        "subtitles",
        "text artifacts",
        *_listify(scene_item.get("negativeTerms")),
    ]
    warnings = []
    if constraints.get("avoid_new_objects", True):
        negative_parts.append("new objects, unrelated background changes")
    if constraints.get("preserve_identity", True):
        positive_parts.append("preserve identity from the input image")
        negative_parts.append("identity drift")
    if not scene_detail and not _join_scene_values(scene.get("action")):
        warnings.append({"code": "missing_scene_detail", "message": "Scene detail is empty; mock provider used subtle motion fallback.", "severity": "warning"})
    return {
        "positivePrompt": ", ".join(_dedupe(positive_parts)),
        "negativePrompt": ", ".join(_dedupe(negative_parts)),
        "warnings": warnings,
    }


def _scene_subject(scene: dict) -> str:
    subject = scene.get("subject") if isinstance(scene.get("subject"), dict) else {}
    values = [
        *_listify(subject.get("type")),
        *_listify(subject.get("appearance")),
    ]
    return _join_scene_values(values)


def _first_scene_item(scene: dict) -> dict:
    scenes = scene.get("scenes")
    if isinstance(scenes, list) and scenes and isinstance(scenes[0], dict):
        return scenes[0]
    return {}


def _join_scene_values(value: object) -> str:
    return ", ".join(_dedupe([str(item) for item in _listify(value)]))


def _listify(value: object) -> list:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    return [value]
