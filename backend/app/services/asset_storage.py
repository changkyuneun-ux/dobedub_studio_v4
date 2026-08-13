from __future__ import annotations

import base64
import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def image_dimensions(raw: bytes, mime_type: str = "") -> tuple[int | None, int | None]:
    """Return image width/height for upload metadata without decoding pixels."""
    try:
        if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
            return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
        if raw[:6] in {b"GIF87a", b"GIF89a"} and len(raw) >= 10:
            return int.from_bytes(raw[6:8], "little"), int.from_bytes(raw[8:10], "little")
        if raw.startswith(b"\xff\xd8"):
            return _jpeg_dimensions(raw)
        if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            return _webp_dimensions(raw)
    except (IndexError, ValueError):
        return None, None
    return None, None


def _jpeg_dimensions(raw: bytes) -> tuple[int | None, int | None]:
    offset = 2
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset + 9 <= len(raw):
        if raw[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        if offset >= len(raw):
            break
        marker = raw[offset]
        offset += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(raw):
            break
        length = int.from_bytes(raw[offset:offset + 2], "big")
        if length < 2 or offset + length > len(raw):
            break
        if marker in sof_markers and length >= 7:
            height = int.from_bytes(raw[offset + 3:offset + 5], "big")
            width = int.from_bytes(raw[offset + 5:offset + 7], "big")
            return width, height
        offset += length
    return None, None


def _webp_dimensions(raw: bytes) -> tuple[int | None, int | None]:
    offset = 12
    while offset + 8 <= len(raw):
        chunk_type = raw[offset:offset + 4]
        chunk_size = int.from_bytes(raw[offset + 4:offset + 8], "little")
        data_start = offset + 8
        data_end = data_start + chunk_size
        if data_end > len(raw):
            break
        chunk = raw[data_start:data_end]
        if chunk_type == b"VP8X" and len(chunk) >= 10:
            width = int.from_bytes(chunk[4:7], "little") + 1
            height = int.from_bytes(chunk[7:10], "little") + 1
            return width, height
        if chunk_type == b"VP8 " and len(chunk) >= 10 and chunk[3:6] == b"\x9d\x01\x2a":
            width = int.from_bytes(chunk[6:8], "little") & 0x3FFF
            height = int.from_bytes(chunk[8:10], "little") & 0x3FFF
            return width, height
        if chunk_type == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
            bits = int.from_bytes(chunk[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        offset = data_end + (chunk_size % 2)
    return None, None


def media_kind(file_name: str, mime_type: str, fallback: str = "output") -> str:
    suffix = Path(file_name or "").suffix.lower()
    mime = str(mime_type or "")
    if mime.startswith("video/") or suffix in VIDEO_SUFFIXES:
        return "videos"
    if mime.startswith("image/") or suffix in IMAGE_SUFFIXES:
        return "images"
    return fallback or "output"


def safe_filename(name: str, fallback: str = "upload.bin") -> str:
    base = Path(name or fallback).name
    stem = Path(base).stem or Path(fallback).stem or "upload"
    suffix = Path(base).suffix[:12]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "upload"
    return f"{stem}{suffix}"


def decode_data_url(value: str) -> tuple[bytes, str]:
    if not isinstance(value, str):
        raise ValueError("dataUrl must be a string")
    if "," not in value or not value.startswith("data:"):
        return base64.b64decode(value), "application/octet-stream"
    header, encoded = value.split(",", 1)
    mime_type = "application/octet-stream"
    if header.startswith("data:") and ";" in header:
        mime_type = header[5:].split(";", 1)[0] or mime_type
    return base64.b64decode(encoded), mime_type


def encode_file_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def asset_record(file_path: Path, asset_type: str, mime_type: str | None = None, file_name: str | None = None) -> dict:
    path = Path(file_path)
    resolved_mime_type = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    item = {
        "assetId": f"asset_{uuid.uuid4().hex[:12]}",
        "type": asset_type,
        "fileName": file_name or path.name,
        "mimeType": resolved_mime_type,
        "path": str(path),
        "sizeBytes": path.stat().st_size if path.exists() else 0,
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if resolved_mime_type.startswith("image/") and path.exists():
        image_width, image_height = image_dimensions(path.read_bytes(), resolved_mime_type)
        if image_width and image_height:
            item["imageWidth"] = image_width
            item["imageHeight"] = image_height
    return item


def path_within_storage(path: str | Path, allowed_roots: list[Path]) -> bool:
    try:
        resolved = Path(path).resolve()
    except (TypeError, OSError):
        return False
    return any(resolved == root.resolve() or root.resolve() in resolved.parents for root in allowed_roots)
