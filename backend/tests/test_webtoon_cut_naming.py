from __future__ import annotations

import pytest


def test_display_name_preserves_korean_and_safe_segment_is_ascii():
    from backend.app.services.webtoon_cut_naming import make_source_identity

    identity = make_source_identity("과학사_3권_내지_인쇄용_수정.pdf")

    assert identity.display_name == "과학사_3권_내지_인쇄용_수정.pdf"
    assert identity.display_stem == "과학사_3권_내지_인쇄용_수정"
    assert identity.safe_stem
    assert identity.safe_stem.isascii()
    assert "ú" not in identity.display_name


def test_pdf_cut_relative_path_uses_page_and_cut_sequence():
    from backend.app.services.webtoon_cut_naming import output_relative_path

    path = output_relative_path(
        input_kind="pdf",
        source_stem="과학사_2권_내지_인쇄용_수정",
        page_number=17,
        cut_index=5,
    )

    assert path == "과학사_2권_내지_인쇄용_수정/017-05.png"


def test_zip_internal_relative_path_is_preserved_and_sanitized_for_output():
    from backend.app.services.webtoon_cut_naming import output_relative_path

    path = output_relative_path(
        input_kind="zip_image",
        source_stem="page_001",
        page_number=None,
        cut_index=2,
        zip_stem="episode_pack",
        zip_internal_relative_dir="chapter 01/sub dir",
    )

    assert path == "episode_pack_cuts/chapter 01/sub dir/page_001/page_001-02.png"


def test_zip_pdf_relative_path_uses_pdf_page_cut_sequence_under_archive_root():
    from backend.app.services.webtoon_cut_naming import output_relative_path

    path = output_relative_path(
        input_kind="zip_pdf",
        source_stem="book_a",
        page_number=17,
        cut_index=5,
        zip_stem="episode_pack",
        zip_internal_relative_dir="pdfs",
    )

    assert path == "episode_pack_cuts/pdfs/book_a/017-05.png"


def test_zip_entry_validation_rejects_path_traversal_and_mac_noise():
    from backend.app.services.webtoon_cut_naming import validate_zip_entry_path

    with pytest.raises(ValueError):
        validate_zip_entry_path("../evil.jpg")
    with pytest.raises(ValueError):
        validate_zip_entry_path("/absolute.jpg")
    with pytest.raises(ValueError):
        validate_zip_entry_path("__MACOSX/._page.jpg")
    with pytest.raises(ValueError):
        validate_zip_entry_path("chapter/.DS_Store")

    assert validate_zip_entry_path("chapter/page 001.jpg") == "chapter/page 001.jpg"
