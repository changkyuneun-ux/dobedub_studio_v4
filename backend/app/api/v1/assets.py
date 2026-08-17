from __future__ import annotations

import mimetypes
from email.utils import formatdate
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.core.security import CurrentUser, current_user_from_asset_session, has_permission, require_permission
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
def get_file(
    asset_id: str,
    request: Request,
    download: str = "0",
    current_user: CurrentUser = Depends(current_user_from_asset_session),
):
    if not any(has_permission(current_user.permissions, permission) for permission in ("jobs:run", "history:read")):
        raise HTTPException(status_code=403, detail="One of permissions is required: jobs:run, history:read")
    try:
        asset, asset_path = studio_api_service.get_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"File not found: {asset_id}") from exc

    content_type = asset.get("mimeType") or mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    stat_result = asset_path.stat()
    file_size = stat_result.st_size
    file_name = str(asset.get("fileName") or asset_path.name).replace('"', "")
    disposition = "attachment" if download == "1" else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="{file_name}"',
        # Keep an authenticated browser cache, but require validation before
        # reuse. This avoids serving a previously cached asset after logout
        # while still allowing a cheap 304 response instead of retransferring
        # a large EFS-backed video.
        "Cache-Control": "private, no-cache",
        "ETag": f'W/"{file_size:x}-{stat_result.st_mtime_ns:x}"',
        "Last-Modified": formatdate(stat_result.st_mtime, usegmt=True),
    }
    range_header = request.headers.get("range", "")
    if not range_header and _etag_matches(request.headers.get("if-none-match", ""), headers["ETag"]):
        return Response(status_code=304, headers=headers)
    if range_header.startswith("bytes="):
        if file_size <= 0:
            return Response(status_code=416, headers={**headers, "Content-Range": "bytes */0"})
        start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
        try:
            start = int(start_text) if start_text else 0
            end = int(end_text) if end_text else file_size - 1
            start = max(0, min(start, file_size - 1))
            end = max(start, min(end, file_size - 1))
        except ValueError:
            start, end = 0, file_size - 1
        length = end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(
            _iter_file_range(asset_path, start=start, length=length),
            status_code=206,
            media_type=content_type,
            headers=headers,
        )

    return FileResponse(asset_path, media_type=content_type, filename=file_name, headers=headers, stat_result=stat_result)


def _iter_file_range(path: Path, *, start: int, length: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Stream a byte range without buffering a large EFS-backed video."""
    remaining = length
    with path.open("rb") as stream:
        stream.seek(start)
        while remaining > 0:
            chunk = stream.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """Return whether an If-None-Match header contains this asset ETag."""
    return if_none_match.strip() == "*" or etag in {item.strip() for item in if_none_match.split(",")}
