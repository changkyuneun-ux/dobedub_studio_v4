"""ZIP filename normalization helpers."""
from __future__ import annotations

import unicodedata


def normalize_zip_path(value: str | None) -> str:
    """Return an NFC path, repairing UTF-8 bytes that were decoded as CP437."""
    raw = str(value or "")
    repaired = _decode_cp437_mojibake(raw)
    return unicodedata.normalize("NFC", repaired)


def _decode_cp437_mojibake(value: str) -> str:
    try:
        original_bytes = value.encode("cp437")
    except UnicodeEncodeError:
        return value
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            decoded = original_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded != value:
            return decoded
    return value


__all__ = ["normalize_zip_path"]
