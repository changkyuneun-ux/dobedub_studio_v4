from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.security import CurrentUser, require_permission
from backend.app.services import collection_service

# A-02: 자산 컬렉션(화면 5c). 자산과 마찬가지로 history:read로 보호한다(A-01 assets와
# 동일 - 컬렉션은 이미 읽을 수 있는 자산을 조직화하는 계층이라 별도 쓰기 권한을 두지
# 않고 읽기 권한으로 통일. 새 권한 코드는 RBAC 시드 전반을 건드려야 해 P2에는 과함).
router = APIRouter(tags=["collections"])


@router.get("/collections")
def list_collections(_: CurrentUser = Depends(require_permission("history:read"))):
    return {"items": collection_service.list_collections()}


@router.post("/collections", status_code=201)
def create_collection(payload: dict, current_user: CurrentUser = Depends(require_permission("history:read"))):
    try:
        return collection_service.create_collection(payload.get("name", ""), created_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int, _: CurrentUser = Depends(require_permission("history:read"))):
    try:
        collection_service.delete_collection(collection_id)
    except collection_service.CollectionNotEmptyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/collections/{collection_id}")
def get_collection(collection_id: int, _: CurrentUser = Depends(require_permission("history:read"))):
    try:
        return collection_service.get_collection(collection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/collections/{collection_id}/items", status_code=201)
def add_collection_item(collection_id: int, payload: dict, _: CurrentUser = Depends(require_permission("history:read"))):
    try:
        return collection_service.add_collection_item(collection_id, str(payload.get("assetId") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# 2026-08-11: Asset 관리 화면 통합 - 컬렉션 칩에서 자산을 뺄 수 있어야 해서 추가.
@router.delete("/collections/{collection_id}/items/{asset_id}")
def remove_collection_item(collection_id: int, asset_id: str, _: CurrentUser = Depends(require_permission("history:read"))):
    try:
        return collection_service.remove_collection_item(collection_id, asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
