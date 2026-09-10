from __future__ import annotations

import mimetypes
from time import perf_counter
from email.utils import formatdate
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.core.security import CurrentUser, current_user_from_asset_session, has_permission, require_permission
from backend.app.core.observability import observe_asset_stream, request_timing
from backend.app.db.session import SessionLocal
from backend.app.services import studio_api_service
from backend.app.services.upload_cleanup_service import delete_unsubmitted_upload

router = APIRouter(tags=["assets"])


@router.get("/assets")
def list_assets(
    request: Request,
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
    with request_timing(request, "db"):
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
def create_upload(payload: dict, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    if not payload.get("fileName") or not payload.get("dataUrl"):
        raise HTTPException(status_code=400, detail="fileName and dataUrl are required")
    try:
        asset = studio_api_service.create_upload({**payload, "createdBy": current_user.id})
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


@router.post("/uploads/presign", status_code=201)
def create_s3_upload_presign(payload: dict, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    if not payload.get("fileName") or not payload.get("mimeType"):
        raise HTTPException(status_code=400, detail="fileName and mimeType are required")
    try:
        return studio_api_service.create_s3_upload_presign(payload, created_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/uploads/complete", status_code=201)
def complete_s3_upload(payload: dict, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    try:
        return studio_api_service.complete_s3_upload(payload, created_by=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Uploaded object was not found.") from exc


@router.delete("/uploads/{asset_id}")
def delete_upload(asset_id: str, current_user: CurrentUser = Depends(require_permission("jobs:run"))):
    session = SessionLocal()
    try:
        return delete_unsubmitted_upload(session, asset_id, created_by=current_user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="업로드 이미지를 찾을 수 없습니다.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        session.close()


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
        with request_timing(request, "db"):
            s3_asset = studio_api_service.s3_asset_download(asset_id, include_url=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}") from exc
    if s3_asset is not None:
        metadata = s3_asset.get("metadata") or {}
        created_by = str(metadata.get("createdBy") or "")
        if created_by and created_by != current_user.id and not has_permission(current_user.permissions, "history:read"):
            raise HTTPException(status_code=403, detail="Asset access denied")
        file_name = str(s3_asset.get("fileName") or asset_id).replace('"', "")
        disposition = "attachment" if download == "1" else "inline"
        storage_key = str(s3_asset.get("storageKey") or "").strip()
        if not storage_key:
            raise HTTPException(status_code=404, detail=f"File not found: {asset_id}")
        try:
            stored = studio_api_service.s3_asset_storage().stat(storage_key)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=f"File not found: {asset_id}") from exc
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": _content_disposition(disposition, file_name),
            "Cache-Control": "private, no-cache",
            "Content-Length": str(stored.size_bytes),
        }
        if stored.etag:
            headers["ETag"] = str(stored.etag)
        range_header = request.headers.get("range", "")
        if range_header.startswith("bytes="):
            if stored.size_bytes <= 0:
                return Response(status_code=416, headers={**headers, "Content-Range": "bytes */0"})
            start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
            try:
                start = int(start_text) if start_text else 0
                end = int(end_text) if end_text else stored.size_bytes - 1
                start = max(0, min(start, stored.size_bytes - 1))
                end = max(start, min(end, stored.size_bytes - 1))
            except ValueError:
                start, end = 0, stored.size_bytes - 1
            length = end - start + 1
            headers["Content-Range"] = f"bytes {start}-{end}/{stored.size_bytes}"
            headers["Content-Length"] = str(length)
            return StreamingResponse(
                _iter_s3_object_range(
                    storage_key,
                    start=start,
                    end=end,
                    on_complete=lambda duration_ms, bytes_sent: observe_asset_stream(
                        request,
                        duration_ms=duration_ms,
                        bytes_sent=bytes_sent,
                        status_code=206,
                    ),
                ),
                status_code=206,
                media_type=str(s3_asset.get("mimeType") or stored.mime_type or "application/octet-stream"),
                headers=headers,
            )
        return StreamingResponse(
            _iter_s3_object(
                storage_key,
                on_complete=lambda duration_ms, bytes_sent: observe_asset_stream(
                    request,
                    duration_ms=duration_ms,
                    bytes_sent=bytes_sent,
                    status_code=200,
                ),
            ),
            media_type=str(s3_asset.get("mimeType") or stored.mime_type or "application/octet-stream"),
            headers=headers,
        )
    try:
        with request_timing(request, "db"):
            asset, asset_path = studio_api_service.get_asset(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"File not found: {asset_id}") from exc

    content_type = asset.get("mimeType") or mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    with request_timing(request, "file_stat"):
        stat_result = asset_path.stat()
    file_size = stat_result.st_size
    file_name = str(asset.get("fileName") or asset_path.name).replace('"', "")
    disposition = "attachment" if download == "1" else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": _content_disposition(disposition, file_name),
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
            _iter_file_range(
                asset_path,
                start=start,
                length=length,
                on_complete=lambda duration_ms, bytes_sent: observe_asset_stream(
                    request,
                    duration_ms=duration_ms,
                    bytes_sent=bytes_sent,
                    status_code=206,
                ),
            ),
            status_code=206,
            media_type=content_type,
            headers=headers,
        )

    return FileResponse(asset_path, media_type=content_type, filename=file_name, headers=headers, stat_result=stat_result)


def _iter_s3_object(storage_key: str, *, on_complete: Callable[[float, int], None] | None = None, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    started = perf_counter()
    bytes_sent = 0
    try:
        with studio_api_service.s3_asset_storage().open_read(storage_key) as stream:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                bytes_sent += len(chunk)
                yield chunk
    finally:
        if on_complete:
            on_complete((perf_counter() - started) * 1000, bytes_sent)


def _iter_s3_object_range(
    storage_key: str,
    *,
    start: int,
    end: int,
    on_complete: Callable[[float, int], None] | None = None,
    chunk_size: int = 1024 * 1024,
) -> Iterator[bytes]:
    started = perf_counter()
    bytes_sent = 0
    try:
        with studio_api_service.s3_asset_storage().open_read_range(storage_key, start=start, end=end) as stream:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                bytes_sent += len(chunk)
                yield chunk
    finally:
        if on_complete:
            on_complete((perf_counter() - started) * 1000, bytes_sent)


def _content_disposition(disposition: str, file_name: str) -> str:
    try:
        file_name.encode("ascii")
    except UnicodeEncodeError:
        return f"{disposition}; filename*=utf-8''{quote(file_name)}"
    return f'{disposition}; filename="{file_name}"'


def _iter_file_range(
    path: Path,
    *,
    start: int,
    length: int,
    chunk_size: int = 1024 * 1024,
    on_complete: Callable[[float, int], None] | None = None,
) -> Iterator[bytes]:
    """Stream a byte range without buffering a large EFS-backed video."""
    started_at = perf_counter()
    bytes_sent = 0
    remaining = length
    try:
        with path.open("rb") as stream:
            stream.seek(start)
            while remaining > 0:
                chunk = stream.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                bytes_sent += len(chunk)
                yield chunk
    finally:
        if on_complete:
            on_complete((perf_counter() - started_at) * 1000, bytes_sent)


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """Return whether an If-None-Match header contains this asset ETag."""
    return if_none_match.strip() == "*" or etag in {item.strip() for item in if_none_match.split(",")}
