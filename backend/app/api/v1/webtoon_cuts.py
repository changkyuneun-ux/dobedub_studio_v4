from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core.security import ADMIN_ROLES, CurrentUser, require_permission
from backend.app.core.config import get_settings
from backend.app.db.models import Asset
from backend.app.db.session import SessionLocal
from backend.app.services.studio_api_service import s3_asset_storage
from backend.app.services import webtoon_cut_service
from backend.app.services.webtoon_cut_naming import make_source_identity
from backend.app.core.timezone_utils import utc_now
import uuid


router = APIRouter(prefix="/webtoon-cuts", tags=["webtoon-cuts"])


@router.post("/uploads/presign", status_code=201)
def create_webtoon_source_presign(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    settings = get_settings()
    if settings.storage_backend != "s3":
        raise HTTPException(status_code=409, detail="STORAGE_BACKEND=s3 설정이 필요합니다.")
    try:
        identity = make_source_identity(str(payload.get("fileName") or "source.bin"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asset_id = str(payload.get("assetId") or f"asset_{uuid.uuid4().hex[:12]}")
    mime_type = str(payload.get("mimeType") or "application/octet-stream")
    key = f"webtoon-cut/users/{current_user.id}/sources/{asset_id}/{identity.safe_stem}{identity.suffix}"
    storage = s3_asset_storage()
    storage_key = storage._key(key)
    return {
        "assetId": asset_id,
        "fileName": identity.display_name,
        "mimeType": mime_type,
        "storageBackend": "s3",
        "storageKey": storage_key,
        "uploadUrl": storage.presigned_put(key, content_type=mime_type, expires_in=900),
        "headers": {"Content-Type": mime_type},
    }


@router.post("/uploads/complete", status_code=201)
def complete_webtoon_source_upload(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    settings = get_settings()
    if settings.storage_backend != "s3":
        raise HTTPException(status_code=409, detail="STORAGE_BACKEND=s3 설정이 필요합니다.")
    asset_id = str(payload.get("assetId") or "").strip()
    storage_key = str(payload.get("storageKey") or "").strip().lstrip("/")
    if not asset_id or not storage_key:
        raise HTTPException(status_code=400, detail="assetId and storageKey are required")
    try:
        identity = make_source_identity(str(payload.get("fileName") or "source.bin"))
        stored = s3_asset_storage().stat(storage_key)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="업로드 원본을 찾을 수 없습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with SessionLocal() as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            asset = Asset(id=asset_id, created_at=utc_now().replace(tzinfo=None))
            session.add(asset)
        asset.asset_type = "webtoon_source_original"
        asset.file_name = identity.display_name
        asset.mime_type = str(payload.get("mimeType") or stored.mime_type or "application/octet-stream")
        asset.size_bytes = stored.size_bytes
        asset.storage_backend = "s3"
        asset.storage_key = storage_key
        asset.public_url = f"s3://{settings.s3_bucket}/{storage_key}"
        asset.metadata_json = {
            "createdBy": current_user.id,
            "displayStem": identity.display_stem,
            "safeStem": identity.safe_stem,
            "webtoonCutSource": True,
        }
        session.commit()
        return {
            "assetId": asset.id,
            "type": asset.asset_type,
            "fileName": asset.file_name,
            "mimeType": asset.mime_type,
            "sizeBytes": asset.size_bytes,
            "storageBackend": asset.storage_backend,
            "storageKey": asset.storage_key,
            "downloadUrl": f"/api/files/{asset.id}",
        }


@router.post("/jobs", status_code=201)
def create_webtoon_cut_job(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    try:
        with SessionLocal() as session:
            return webtoon_cut_service.create_job(
                session,
                source_asset_id=str(payload.get("assetId") or payload.get("sourceAssetId") or ""),
                input_kind=str(payload.get("inputKind") or ""),
                created_by=current_user.id,
                metadata=dict(payload.get("metadata") or {}),
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="원본 asset을 찾을 수 없습니다.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs")
def list_webtoon_cut_jobs(
    status: str = "",
    inputKind: str = Query("", alias="inputKind"),
    query: str = "",
    createdBy: str = Query("", alias="createdBy"),
    page: int = 1,
    pageSize: int = 20,
    current_user: CurrentUser = Depends(require_permission("history:read")),
):
    created_by_filter = str(createdBy or "").strip()
    if current_user.role not in ADMIN_ROLES:
        created_by_filter = current_user.id
    elif not created_by_filter:
        created_by_filter = None
    with SessionLocal() as session:
        return webtoon_cut_service.list_jobs(
            session,
            created_by=created_by_filter,
            status=status,
            input_kind=inputKind,
            query=query,
            page=page,
            page_size=pageSize,
        )


@router.get("/jobs/{job_id}")
def get_webtoon_cut_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_permission("history:read")),
):
    try:
        with SessionLocal() as session:
            return webtoon_cut_service.get_job(session, job_id, created_by=current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="컷 분할 작업을 찾을 수 없습니다.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_webtoon_cut_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    try:
        with SessionLocal() as session:
            return webtoon_cut_service.cancel_job(session, job_id, created_by=current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="컷 분할 작업을 찾을 수 없습니다.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/jobs/{job_id}")
def delete_webtoon_cut_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    try:
        with SessionLocal() as session:
            return webtoon_cut_service.delete_job(session, job_id, created_by=current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="컷 분할 작업을 찾을 수 없습니다.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/outputs")
def list_webtoon_cut_outputs(
    job_id: str,
    usedState: str = Query("", alias="usedState"),
    flags: str = "",
    query: str = "",
    page: int = 1,
    pageSize: int = 50,
    current_user: CurrentUser = Depends(require_permission("history:read")),
):
    try:
        created_by_filter = None if current_user.role in ADMIN_ROLES else current_user.id
        with SessionLocal() as session:
            return webtoon_cut_service.list_outputs(
                session,
                job_id=job_id,
                created_by=created_by_filter,
                used_state=usedState,
                flags=flags,
                query=query,
                page=page,
                page_size=pageSize,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="컷 분할 작업을 찾을 수 없습니다.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/handoff/grok")
def handoff_to_grok_prompt(
    job_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    try:
        with SessionLocal() as session:
            return webtoon_cut_service.create_grok_prompt_input_from_outputs(
                session,
                job_id=job_id,
                output_ids=list(payload.get("outputIds") or []),
                created_by=current_user.id,
            )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/handoff/batch")
def handoff_to_batch(
    job_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("jobs:run")),
):
    try:
        with SessionLocal() as session:
            return webtoon_cut_service.create_batch_input_from_outputs(
                session,
                job_id=job_id,
                output_ids=list(payload.get("outputIds") or []),
                created_by=current_user.id,
            )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
