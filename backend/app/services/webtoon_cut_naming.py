from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath


_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_SUPPORTED_SOURCE_SUFFIXES = {
    ".pdf",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}


@dataclass(frozen=True)
class SourceIdentity:
    display_name: str
    display_stem: str
    suffix: str
    safe_stem: str


def make_source_identity(file_name: str, *, fallback: str = "source") -> SourceIdentity:
    display_name = _normalize_display_name(file_name or fallback)
    path = PurePosixPath(display_name)
    suffix = path.suffix.lower()
    if suffix and suffix not in _SUPPORTED_SOURCE_SUFFIXES:
        raise ValueError(f"지원하지 않는 원본 파일 형식입니다: {suffix}")
    display_stem = path.stem or fallback
    safe_stem = safe_storage_segment(display_stem, fallback=fallback)
    return SourceIdentity(
        display_name=display_name,
        display_stem=display_stem,
        suffix=suffix,
        safe_stem=safe_stem,
    )


def safe_storage_segment(value: str, *, fallback: str = "item") -> str:
    normalized = unicodedata.normalize("NFKD", str(value or fallback))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE_SEGMENT_CHARS.sub("_", ascii_text).strip("._-")
    return cleaned[:120] or fallback


def output_relative_path(
    *,
    input_kind: str,
    source_stem: str,
    cut_index: int,
    page_number: int | None = None,
    zip_stem: str | None = None,
    zip_internal_relative_dir: str | None = None,
) -> str:
    if cut_index < 1:
        raise ValueError("cut_index must be >= 1")
    display_stem = _normalize_display_segment(source_stem or "source")
    kind = str(input_kind or "").strip().lower()
    if kind in {"pdf", "zip_pdf"}:
        if page_number is None or page_number < 1:
            raise ValueError("page_number must be >= 1 for PDF outputs")
        if kind == "zip_pdf":
            zip_display_stem = _normalize_display_segment(zip_stem or "archive")
            internal_dir = _normalize_internal_dir(zip_internal_relative_dir or "")
            parts = [f"{zip_display_stem}_cuts"]
            if internal_dir:
                parts.append(internal_dir)
            parts.extend([display_stem, f"{page_number:03d}-{cut_index:02d}.png"])
            return "/".join(parts)
        return f"{display_stem}/{page_number:03d}-{cut_index:02d}.png"
    if kind in {"image", "zip_image"}:
        file_name = f"{display_stem}-{cut_index:02d}.png"
        if kind == "zip_image":
            zip_display_stem = _normalize_display_segment(zip_stem or "archive")
            internal_dir = _normalize_internal_dir(zip_internal_relative_dir or "")
            parts = [f"{zip_display_stem}_cuts"]
            if internal_dir:
                parts.append(internal_dir)
            parts.extend([display_stem, file_name])
            return "/".join(parts)
        return f"{display_stem}/{file_name}"
    raise ValueError(f"unsupported input_kind: {input_kind}")


def validate_zip_entry_path(entry_name: str) -> str:
    raw = str(entry_name or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError("ZIP entry path is empty")
    if raw.startswith("/"):
        raise ValueError("ZIP entry absolute paths are not allowed")
    path = PurePosixPath(raw)
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        raise ValueError("ZIP entry path is empty")
    if any(part == ".." for part in parts):
        raise ValueError("ZIP entry path traversal is not allowed")
    if parts[0] == "__MACOSX":
        raise ValueError("ZIP macOS metadata entries are ignored")
    if any(part in {".DS_Store"} or part.startswith("._") for part in parts):
        raise ValueError("ZIP macOS metadata entries are ignored")
    return "/".join(_normalize_display_segment(part) for part in parts)


def _normalize_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value or "").replace("\\", "/"))
    name = PurePosixPath(normalized).name.strip()
    if not name:
        raise ValueError("file name is required")
    return name


def _normalize_display_segment(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value or "")).strip()
    normalized = normalized.replace("/", "_").replace("\\", "_").strip()
    if normalized in {"", ".", ".."}:
        raise ValueError("invalid path segment")
    return normalized


def _normalize_internal_dir(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    validated = validate_zip_entry_path(f"{raw}/placeholder.png")
    parts = validated.split("/")[:-1]
    return "/".join(parts)
