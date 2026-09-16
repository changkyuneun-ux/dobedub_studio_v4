"""ZIP filename normalization helpers."""
from __future__ import annotations

import unicodedata


def normalize_zip_path(value: str | None) -> str:
    """Return an NFC path, repairing common ZIP filename mojibake.

    ZIP tools disagree on whether entry names are UTF-8, CP437, CP949/EUC-KR,
    or raw bytes surfaced as Latin-1. Score multiple byte-decoding candidates
    instead of returning the first one so Korean names are preferred over
    accidental valid non-Korean Unicode such as ``ȭ``.
    """
    raw = str(value or "")
    candidates = {raw}
    candidates.update(_decode_mojibake_candidates(raw, "cp437"))
    candidates.update(_decode_mojibake_candidates(raw, "latin-1"))
    repaired = max(candidates, key=_readability_score)
    return unicodedata.normalize("NFC", repaired)


def _decode_mojibake_candidates(value: str, byte_encoding: str) -> set[str]:
    try:
        original_bytes = value.encode(byte_encoding)
    except UnicodeEncodeError:
        return set()
    decoded_values: set[str] = set()
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            decoded = original_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded != value:
            decoded_values.add(decoded)
    return decoded_values


def _readability_score(value: str) -> int:
    hangul = sum(1 for char in value if "\uac00" <= char <= "\ud7a3")
    ascii_printable = sum(1 for char in value if " " <= char <= "~")
    controls = sum(1 for char in value if ord(char) < 32 or 0x80 <= ord(char) <= 0x9F)
    replacement = value.count("\ufffd")
    mojibake_markers = sum(1 for char in value if char in _MOJIBAKE_MARKERS)
    # Keep ordinary ASCII paths stable, but strongly prefer readable Korean
    # when a mojibake path can be repaired.
    return hangul * 20 + ascii_printable - controls * 20 - replacement * 50 - mojibake_markers * 4


_MOJIBAKE_MARKERS = set(
    "°±²³´µ¶·¸¹º»¼½¾¿"
    "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞß"
    "àáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ"
    "ÃÂÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ"
)


__all__ = ["normalize_zip_path"]
