from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, has_permission, require_any_permission, require_permission
from backend.app.core.config import get_settings
from backend.app.db.models import ImagePromptDraft, PromptCategoryGroup, PromptSubcategory, PromptSystemPrompt, PromptTerm
from backend.app.db.session import get_db
from backend.app.services import studio_api_service
from backend.app.services.audit_log_service import record_audit_log
from backend.app.services.prompt_builder_service import (
    build_scene_json,
    deactivate_prompt_category_group,
    deactivate_prompt_category,
    deactivate_prompt_term,
    generate_prompt,
    get_prompt_generation_status,
    prompt_catalog,
    save_prompt_feedback,
    scene_json_v1_schema,
    upsert_prompt_category_group,
    upsert_prompt_category,
    upsert_prompt_keyword,
)
from backend.app.services.prompt_system_prompt_service import (
    DEFAULT_SYSTEM_PROMPT_CODE,
    get_prompt_system_prompt,
    list_prompt_system_prompt_versions,
    save_prompt_system_prompt,
)
from backend.app.services.grok_image_prompt_service import (
    GrokPromptError,
    GrokPromptInputError,
    generate_image_prompt,
)
from backend.app.services.grok_instruction_service import active_instruction_text, list_instruction_documents
from backend.app.services.prompt_batch_service import (
    create_prompt_generation_batch,
    list_active_prompt_generation_batches,
    latest_active_prompt_generation_batch,
    list_prompt_drafts,
    prompt_generation_batch_payload,
    retry_prompt_draft,
    update_prompt_draft,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# A-04: 감사 로그 대상 스냅샷 헬퍼 - upsert 서비스 함수는 카탈로그 전체(prompt_catalog(session))를
# 반환하므로 개별 엔티티의 before/after는 라우트에서 직접 모델을 조회해 만든다.
def _category_group_snapshot(group: PromptCategoryGroup) -> dict:
    return {
        "id": group.id,
        "code": group.code,
        "nameKo": group.name_ko,
        "nameEn": group.name_en,
        "sortOrder": group.sort_order,
        "isActive": group.is_active,
    }


def _category_snapshot(category: PromptSubcategory) -> dict:
    return {
        "id": category.id,
        "code": category.code,
        "nameKo": category.name_ko,
        "nameEn": category.name_en,
        "scopeType": category.scope_type,
        "selectionType": category.selection_type,
        "sortOrder": category.sort_order,
        "isActive": category.is_active,
    }


def _term_snapshot(term: PromptTerm) -> dict:
    return {
        "id": term.id,
        "code": term.code,
        "labelKo": term.label_ko,
        "labelEn": term.label_en,
        "riskLevel": term.risk_level,
        "sortOrder": term.sort_order,
        "isActive": term.is_active,
    }


def _system_prompt_snapshot(prompt: PromptSystemPrompt) -> dict:
    return {
        "id": prompt.id,
        "code": prompt.code,
        "name": prompt.name,
        "provider": prompt.provider,
        "modelFamily": prompt.model_family,
        "promptText": prompt.prompt_text,
        "isActive": prompt.is_active,
    }


@router.get("")
def prompts(_: CurrentUser = Depends(require_any_permission(("prompts:build", "prompts:reuse")))):
    return studio_api_service.prompt_options()


@router.get("/reusable")
def reusable_prompts(
    keyword: str = "",
    workflowId: str = "",
    minRating: int | None = None,
    reviewedOnly: bool = False,
    reuseEligible: bool | None = None,
    page: int = 1,
    pageSize: int = 20,
    _: CurrentUser = Depends(require_permission("prompts:reuse")),
):
    try:
        return studio_api_service.reusable_prompts(
            keyword=keyword,
            workflow_id=workflowId,
            min_rating=minRating,
            reviewed_only=reviewedOnly,
            reuse_eligible=reuseEligible,
            page=page,
            page_size=pageSize,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Reusable prompt query failed: {exc}") from exc


@router.get("/catalog")
def catalog(_: CurrentUser = Depends(require_any_permission(("prompts:build", "prompts:reuse", "prompt-catalog:read", "prompt-catalog:write"))), db: Session = Depends(get_db)):
    try:
        return prompt_catalog(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt DB is not ready: {exc}") from exc


@router.get("/scene-schema")
def scene_schema(_: CurrentUser = Depends(require_any_permission(("prompts:build", "prompts:reuse")))):
    return scene_json_v1_schema()


@router.get("/system-prompt")
def system_prompt(_: CurrentUser = Depends(require_permission("prompts:build")), db: Session = Depends(get_db)):
    try:
        return get_prompt_system_prompt(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt system prompt load failed: {exc}") from exc


@router.get("/system-prompt/versions")
# B-08: 시스템 지시문 버전 이력(7a 되돌리기용). 조회는 편집 화면과 같은 prompts:build.
def system_prompt_versions(code: str = DEFAULT_SYSTEM_PROMPT_CODE, _: CurrentUser = Depends(require_permission("prompts:build")), db: Session = Depends(get_db)):
    try:
        return {"items": list_prompt_system_prompt_versions(db, str(code or DEFAULT_SYSTEM_PROMPT_CODE))}
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt system prompt versions load failed: {exc}") from exc


@router.put("/system-prompt")
def update_system_prompt(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    code = str(payload.get("code") or DEFAULT_SYSTEM_PROMPT_CODE).strip() or DEFAULT_SYSTEM_PROMPT_CODE
    existing = db.scalar(select(PromptSystemPrompt).where(PromptSystemPrompt.code == code))
    before = _system_prompt_snapshot(existing) if existing else None
    try:
        result = save_prompt_system_prompt(db, payload, created_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt system prompt save failed: {exc}") from exc
    after = db.scalar(select(PromptSystemPrompt).where(PromptSystemPrompt.code == code))
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="prompt_catalog.system_prompt.update",
        target_type="prompt_system_prompt",
        target_id=code,
        before=before,
        after=_system_prompt_snapshot(after) if after else None,
        ip=_client_ip(request),
    )
    return result


@router.post("/category-groups")
def create_category_group(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        result = upsert_prompt_category_group(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt category save failed: {exc}") from exc
    group = db.scalar(select(PromptCategoryGroup).where(PromptCategoryGroup.code == str(payload.get("code") or "").strip().lower()))
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="prompt_catalog.category_group.create",
        target_type="prompt_category_group",
        target_id=str(group.id) if group else None,
        before=None,
        after=_category_group_snapshot(group) if group else None,
        ip=_client_ip(request),
    )
    return result


@router.put("/category-groups/{group_id}")
def update_category_group(group_id: int, payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    existing = db.get(PromptCategoryGroup, group_id)
    before = _category_group_snapshot(existing) if existing else None
    try:
        result = upsert_prompt_category_group(db, payload, group_id=group_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt category save failed: {exc}") from exc
    after = db.get(PromptCategoryGroup, group_id)
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="prompt_catalog.category_group.update",
        target_type="prompt_category_group",
        target_id=str(group_id),
        before=before,
        after=_category_group_snapshot(after) if after else None,
        ip=_client_ip(request),
    )
    return result


@router.post("/category-groups/{group_id}/deactivate")
def deactivate_category_group(group_id: int, _: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        return deactivate_prompt_category_group(db, group_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt category deactivate failed: {exc}") from exc


@router.post("/categories")
def create_category(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        result = upsert_prompt_category(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt category save failed: {exc}") from exc
    category = db.scalar(select(PromptSubcategory).where(PromptSubcategory.code == str(payload.get("code") or "").strip().upper()))
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="prompt_catalog.category.create",
        target_type="prompt_category",
        target_id=str(category.id) if category else None,
        before=None,
        after=_category_snapshot(category) if category else None,
        ip=_client_ip(request),
    )
    return result


@router.put("/categories/{category_id}")
def update_category(category_id: int, payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    existing = db.get(PromptSubcategory, category_id)
    before = _category_snapshot(existing) if existing else None
    try:
        result = upsert_prompt_category(db, payload, category_id=category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt category save failed: {exc}") from exc
    after = db.get(PromptSubcategory, category_id)
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="prompt_catalog.category.update",
        target_type="prompt_category",
        target_id=str(category_id),
        before=before,
        after=_category_snapshot(after) if after else None,
        ip=_client_ip(request),
    )
    return result


@router.post("/categories/{category_id}/deactivate")
def deactivate_category(category_id: int, _: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        return deactivate_prompt_category(db, category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt category deactivate failed: {exc}") from exc


@router.post("/terms")
def create_term(payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        result = upsert_prompt_keyword(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt term save failed: {exc}") from exc
    term = db.scalar(select(PromptTerm).where(PromptTerm.code == str(payload.get("code") or "").strip()))
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="prompt_catalog.term.create",
        target_type="prompt_term",
        target_id=str(term.id) if term else None,
        before=None,
        after=_term_snapshot(term) if term else None,
        ip=_client_ip(request),
    )
    return result


@router.put("/terms/{term_id}")
def update_term(term_id: int, payload: dict, request: Request, current_user: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    existing = db.get(PromptTerm, term_id)
    before = _term_snapshot(existing) if existing else None
    try:
        result = upsert_prompt_keyword(db, payload, term_id=term_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt term save failed: {exc}") from exc
    after = db.get(PromptTerm, term_id)
    record_audit_log(
        db,
        actor_id=current_user.id,
        action="prompt_catalog.term.update",
        target_type="prompt_term",
        target_id=str(term_id),
        before=before,
        after=_term_snapshot(after) if after else None,
        ip=_client_ip(request),
    )
    return result


@router.post("/terms/{term_id}/deactivate")
def deactivate_term(term_id: int, _: CurrentUser = Depends(require_permission("prompt-catalog:write")), db: Session = Depends(get_db)):
    try:
        return deactivate_prompt_term(db, term_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt term deactivate failed: {exc}") from exc


@router.post("/scene")
def scene(payload: dict, _: CurrentUser = Depends(require_permission("prompts:build")), db: Session = Depends(get_db)):
    try:
        return build_scene_json(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt scene build failed: {exc}") from exc


@router.post("/generate")
def generate(payload: dict, current_user: CurrentUser = Depends(require_permission("prompts:build")), db: Session = Depends(get_db)):
    try:
        result = generate_prompt(db, payload, created_by=current_user.id)
        if str(result.get("status") or "").upper() not in {"", "COMPLETED", "SUCCEEDED", "SUCCESS"}:
            return JSONResponse(status_code=202, content=result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt generation failed: {exc}") from exc


def _image_prompt_draft_payload(draft: ImagePromptDraft, *, cached: bool = False) -> dict:
    return {
        "draftId": draft.id,
        "assetId": draft.asset_id,
        "workflowId": draft.workflow_id,
        "slotIndex": draft.slot_index,
        "status": draft.status,
        "provider": draft.provider,
        "model": draft.model,
        "instructionVersion": draft.instruction_version,
        "positivePrompt": draft.positive_prompt or "",
        "imageType": str((draft.raw_json or {}).get("imageType") or "mixed"),
        "warnings": draft.warnings_json or [],
        "error": draft.failure_message,
        "cached": cached,
    }


@router.post("/image-drafts/generate")
def generate_image_draft(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    """Generate (or return) the positive prompt paired with one source asset."""
    asset_id = str(payload.get("assetId") or "").strip()
    workflow_id = str(payload.get("workflowId") or "").strip()
    try:
        slot_index = int(payload.get("slotIndex") or 0)
    except (TypeError, ValueError):
        slot_index = 0
    if not asset_id or not workflow_id or slot_index < 1:
        raise HTTPException(status_code=400, detail="assetId, workflowId, and slotIndex are required")

    settings = get_settings()
    if not settings.grok_enabled:
        raise HTTPException(status_code=409, detail="Grok image prompt generation is disabled. Set GROK_ENABLED=1.")
    try:
        instruction_text, instruction_version = active_instruction_text(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    existing = db.scalar(
        select(ImagePromptDraft)
        .where(
            ImagePromptDraft.asset_id == asset_id,
            ImagePromptDraft.workflow_id == workflow_id,
            ImagePromptDraft.slot_index == slot_index,
            ImagePromptDraft.created_by == current_user.id,
            ImagePromptDraft.status.in_(["READY", "MANUAL_REQUIRED"]),
            ImagePromptDraft.model == settings.grok_model,
            ImagePromptDraft.instruction_version == instruction_version,
        )
        .order_by(ImagePromptDraft.updated_at.desc())
    )
    if existing and not bool(payload.get("regenerate")):
        return _image_prompt_draft_payload(existing, cached=True)

    try:
        asset, asset_path = studio_api_service.get_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Input image asset was not found.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Input image file is unavailable.") from exc

    draft = ImagePromptDraft(
        id=f"grok_draft_{uuid.uuid4().hex[:16]}",
        asset_id=asset_id,
        workflow_id=workflow_id,
        slot_index=slot_index,
        status="GENERATING",
        provider="grok",
        model=settings.grok_model,
        instruction_version=instruction_version,
        warnings_json=[],
        raw_json={},
        created_by=current_user.id,
    )
    db.add(draft)
    db.flush()
    try:
        result = generate_image_prompt(
            settings,
            asset_path=asset_path,
            mime_type=str(asset.get("mimeType") or ""),
            file_name=str(asset.get("fileName") or asset_path.name),
            image_width=asset.get("imageWidth"),
            image_height=asset.get("imageHeight"),
            instruction_text=instruction_text,
        )
        draft.status = "MANUAL_REQUIRED" if not result.positive_prompt else "READY"
        draft.positive_prompt = result.positive_prompt
        draft.warnings_json = result.warnings
        draft.raw_json = {"imageType": result.image_type, "response": result.raw_response}
        db.commit()
        db.refresh(draft)
        return _image_prompt_draft_payload(draft)
    except GrokPromptInputError as exc:
        draft.status = "FAILED"
        draft.failure_message = str(exc)
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GrokPromptError as exc:
        draft.status = "FAILED"
        draft.failure_message = str(exc)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        draft.status = "FAILED"
        draft.failure_message = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail="Grok image prompt generation failed.") from exc


@router.post("/image-drafts/batches")
def create_image_prompt_batch(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    """Persist one Grok request batch; the monitor processes its drafts sequentially."""
    settings = get_settings()
    if not settings.grok_enabled:
        raise HTTPException(status_code=409, detail="Grok image prompt generation is disabled. Set GROK_ENABLED=1.")
    try:
        return create_prompt_generation_batch(db, payload, created_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt generation batch save failed: {exc}") from exc


@router.get("/image-drafts/batches/active")
def active_image_prompt_batch(
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    return {"item": latest_active_prompt_generation_batch(db, created_by=current_user.id)}


@router.get("/image-drafts/batches/active-list")
def active_image_prompt_batches(
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    created_by = None if has_permission(current_user.permissions, "jobs:manage") else current_user.id
    return {"items": list_active_prompt_generation_batches(db, created_by=created_by)}


@router.get("/image-drafts/batches/{batch_id}")
def image_prompt_batch_status(
    batch_id: str,
    _: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    try:
        return prompt_generation_batch_payload(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/image-drafts")
def image_prompt_drafts(
    workerId: str = "",
    workflowId: str = "",
    status: str = "",
    page: int = 1,
    pageSize: int = 50,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    selected_worker = workerId.strip() or current_user.id
    if selected_worker in {"*", "all"}:
        if not has_permission(current_user.permissions, "jobs:manage"):
            raise HTTPException(status_code=403, detail="전체 작업자 조회에는 jobs:manage 권한이 필요합니다.")
        selected_worker = None
    elif selected_worker != current_user.id and not has_permission(current_user.permissions, "jobs:manage"):
        raise HTTPException(status_code=403, detail="다른 작업자 조회에는 jobs:manage 권한이 필요합니다.")
    return list_prompt_drafts(
        db,
        created_by=selected_worker,
        workflow_id=workflowId,
        status=status,
        page=page,
        page_size=pageSize,
    )


@router.get("/image-drafts/instruction-status")
def image_prompt_instruction_status(workflowId: str, _: CurrentUser = Depends(require_permission("prompts:build"))):
    try:
        result = list_instruction_documents(workflowId)
        active_items = [item for item in result.get("items") or [] if item.get("isActive")]
        return {"workflowId": workflowId, "configured": bool(active_items), "count": len(active_items)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/image-drafts/{draft_id}")
def update_image_prompt_draft(
    draft_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    try:
        return update_prompt_draft(
            db,
            draft_id,
            created_by=current_user.id,
            positive_prompt=payload.get("positivePrompt"),
            negative_prompt=payload.get("negativePrompt"),
            requested_frames=payload.get("requestedFrames"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/image-drafts/{draft_id}/retry")
def retry_image_prompt_draft(
    draft_id: str,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    try:
        return retry_prompt_draft(db, draft_id, created_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/generate/{request_id}")
def prompt_generation_status(request_id: str, _: CurrentUser = Depends(require_permission("prompts:build")), db: Session = Depends(get_db)):
    try:
        return get_prompt_generation_status(db, request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt generation status failed: {exc}") from exc


@router.post("/feedback", status_code=201)
# B-03: 평가는 검수 행위다 - 생성 권한(prompts:build)이 아니라 리뷰 권한(prompts:review)을
# 요구한다. ADMIN 역할은 review는 있지만 build는 없어 이전에는 이 엔드포인트를 호출할 수
# 없었다(B-02가 새로 연결한 3f의 "프롬프트 생성 품질" 평가 UI가 정작 ADMIN에게는 403이었음).
def feedback(payload: dict, _: CurrentUser = Depends(require_permission("prompts:review")), db: Session = Depends(get_db)):
    try:
        return save_prompt_feedback(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Prompt feedback failed: {exc}") from exc
