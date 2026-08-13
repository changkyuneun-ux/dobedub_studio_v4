from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from backend.app.core.security import CurrentUser, require_any_permission, require_permission
from backend.app.services import studio_api_service

router = APIRouter(tags=["assets"])


@router.get("/assets")
def list_assets(
    type: str = "",
    workflowId: str = "",
    from_: str = Query("", alias="from"),
    to: str = "",
    page: int = 1,
    pageSize: int = 20,
    collectionId: int = 0,
    uncategorized: bool = False,
    _: CurrentUser = Depends(require_permission("history:read")),
):
    # A-01: 화면 5a/5c(E-03)가 작업을 거치지 않고 직접 목록을 그릴 수 있도록 함.
    # `from`은 Python 예약어라 쿼리 파라미터 이름은 그대로 두고 함수 인자만 `from_`로 받는다.
    # 2026-08-11: Asset 관리 화면 통합 - collectionId(특정 컬렉션만)/uncategorized
    # (어느 컬렉션에도 없는 자산만) 필터 추가.
    return studio_api_service.paginated_assets(
        page,
        pageSize,
        asset_type=type,
        workflow_id=workflowId,
        date_from=from_,
        date_to=to,
        collection_id=collectionId or None,
        uncategorized=uncategorized,
    )


@router.post("/uploads", status_code=201)
def create_upload(payload: dict, _: CurrentUser = Depends(require_permission("jobs:run"))):
    if not payload.get("fileName") or not payload.get("dataUrl"):
        raise HTTPException(status_code=400, detail="fileName and dataUrl are required")
    try:
        asset = studio_api_service.create_upload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "assetId": asset["assetId"],
        "fileName": asset["fileName"],
        "mimeType": asset["mimeType"],
        "sizeBytes": asset["sizeBytes"],
        "imageWidth": asset.get("imageWidth"),
        "imageHeight": asset.get("imageHeight"),
        "downloadUrl": f"/api/files/{asset['assetId']}",
    }


@router.get("/files/{asset_id}")
def get_file(asset_id: str, request: Request, download: str = "0", _: CurrentUser = Depends(require_any_permission(("jobs:run", "history:read")))):
    try:
        asset, asset_path = studio_api_service.get_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"File not found: {asset_id}") from exc

    content_type = asset.get("mimeType") or mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    file_size = asset_path.stat().st_size
    file_name = str(asset.get("fileName") or asset_path.name).replace('"', "")
    disposition = "attachment" if download == "1" else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{file_name}"',
    }
    range_header = request.headers.get("range", "")
    if range_header.startswith("bytes="):
        start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
        try:
            start = int(start_text) if start_text else 0
            end = int(end_text) if end_text else file_size - 1
            start = max(0, min(start, file_size - 1))
            end = max(start, min(end, file_size - 1))
        except ValueError:
            start, end = 0, file_size - 1
        length = end - start + 1
        with asset_path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(length)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return Response(data, status_code=206, media_type=content_type, headers=headers)

    return FileResponse(asset_path, media_type=content_type, filename=file_name, headers=headers)
