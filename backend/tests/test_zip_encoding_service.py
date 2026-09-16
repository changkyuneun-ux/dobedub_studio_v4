from __future__ import annotations

from backend.app.services.zip_encoding_service import normalize_zip_path


def _utf8_latin1_mojibake(value: str) -> str:
    return value.encode("utf-8").decode("latin-1")


def _utf8_cp437_mojibake(value: str) -> str:
    return value.encode("utf-8").decode("cp437")


def _cp949_latin1_mojibake(value: str) -> str:
    return value.encode("cp949").decode("latin-1")


def test_normalize_zip_path_repairs_utf8_latin1_mojibake():
    assert normalize_zip_path(_utf8_latin1_mojibake("OTT_6화/24화_001.png")) == "OTT_6화/24화_001.png"


def test_normalize_zip_path_repairs_utf8_cp437_mojibake():
    assert normalize_zip_path(_utf8_cp437_mojibake("OTT_6화/24화_001.png")) == "OTT_6화/24화_001.png"


def test_normalize_zip_path_repairs_cp949_latin1_mojibake():
    assert normalize_zip_path(_cp949_latin1_mojibake("과학사_3권_내지_인쇄용_수정.pdf")) == "과학사_3권_내지_인쇄용_수정.pdf"


def test_normalize_zip_path_prefers_composed_hangul_over_mixed_cjk_candidate():
    broken = "source_cuts/OTT_6ßäÆßà¬/24ßäÆßà¬_001/24ßäÆßà¬_001-01.png"

    assert normalize_zip_path(broken) == "source_cuts/OTT_6화/24화_001/24화_001-01.png"
