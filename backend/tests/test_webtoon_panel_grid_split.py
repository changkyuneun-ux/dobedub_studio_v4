from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest


def test_refine_to_border_preserves_nearby_speech_bubble_protrusion():
    from backend.app.services.webtoon_panel_engine.grid_split import _refine_to_border

    image = np.full((360, 520, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (120, 120), (460, 320), (0, 0, 0), 5)
    cv2.ellipse(image, (390, 65), (80, 40), 0, 0, 360, (0, 0, 0), 4)
    cv2.putText(image, "TEXT", (350, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    refined, ok = _refine_to_border(image, (100, 40, 480, 330))

    assert ok is True
    assert refined[1] <= 30


def test_dark_background_split_names_panels_by_visual_reading_order(tmp_path):
    from backend.app.services.webtoon_panel_engine.dark_bg_split import split_panels

    source = tmp_path / "dark-layout.png"
    image = np.full((960, 900, 3), 20, dtype=np.uint8)
    panels = [
        ((500, 470), (850, 900)),
        ((80, 40), (420, 180)),
        ((460, 40), (800, 180)),
        ((70, 220), (820, 380)),
        ((70, 470), (420, 900)),
    ]
    for index, (a, b) in enumerate(panels, start=1):
        cv2.rectangle(image, a, b, (235, 235, 235), -1)
        cv2.putText(image, str(index), (a[0] + 30, a[1] + 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        cv2.rectangle(image, (a[0] + 40, a[1] + 40), (a[0] + 100, a[1] + 100), (0, 0, 0), -1)
    cv2.imwrite(str(source), image)

    saved = split_panels(str(source), str(tmp_path / "out"), debug=True)

    assert [Path(path).name for path in saved] == [
        "panel_01.png",
        "panel_02.png",
        "panel_03.png",
        "panel_04.png",
        "panel_05.png",
    ]


def test_grid_split_rejects_horizontal_gutter_band_between_panel_rows(tmp_path):
    from backend.app.services.webtoon_panel_engine.grid_split import split_panels

    source = tmp_path / "white-grid.png"
    image = np.full((700, 800, 3), 255, dtype=np.uint8)
    panels = [
        ((80, 80), (360, 300)),
        ((440, 80), (720, 300)),
        ((80, 380), (360, 600)),
        ((440, 380), (720, 600)),
    ]
    for index, (a, b) in enumerate(panels, start=1):
        cv2.rectangle(image, a, b, (20, 20, 20), 4)
        cv2.rectangle(image, (a[0] + 48, a[1] + 48), (a[0] + 108, a[1] + 108), (20, 20, 20), -1)
        cv2.putText(image, str(index), (a[0] + 140, a[1] + 120), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (20, 20, 20), 4)
    cv2.imwrite(str(source), image)

    saved = split_panels(str(source), str(tmp_path / "out"), debug=True)

    assert [Path(path).name for path in saved] == ["panel_01.png", "panel_02.png", "panel_03.png", "panel_04.png"]


def test_runtime_routes_panel_detection_through_batch_split_entrypoint(tmp_path, monkeypatch):
    from backend.app.services.webtoon_panel_engine import batch_split
    from backend.app.services.webtoon_panel_engine.runtime import process_image_file

    source = tmp_path / "source.png"
    image = np.full((120, 160, 3), 255, dtype=np.uint8)
    cv2.imwrite(str(source), image)
    called = []

    def fake_split_panels(image_path: str, out_dir: str, debug: bool = False):
        called.append((Path(image_path).name, debug))
        panel = Path(out_dir) / "panel_01.png"
        cv2.imwrite(str(panel), np.full((40, 60, 3), 128, dtype=np.uint8))
        return [str(panel)]

    monkeypatch.setattr(batch_split, "split_panels", fake_split_panels, raising=False)

    result = process_image_file(source, output_dir=tmp_path / "out")

    assert called == [("source.png", True)]
    assert result.mode == "grid"
    assert [(cut.cut_index, cut.width, cut.height) for cut in result.cuts] == [(1, 60, 40)]


def test_runtime_routes_dark_background_mode_through_dark_split_entrypoint(tmp_path, monkeypatch):
    from backend.app.services.webtoon_panel_engine import dark_bg_split
    from backend.app.services.webtoon_panel_engine.runtime import process_image_file

    source = tmp_path / "source.png"
    image = np.full((120, 160, 3), 32, dtype=np.uint8)
    cv2.imwrite(str(source), image)
    called = []

    def fake_split_panels(image_path: str, out_dir: str, debug: bool = False):
        called.append((Path(image_path).name, debug))
        panel = Path(out_dir) / "panel_01.png"
        cv2.imwrite(str(panel), np.full((36, 72, 3), 180, dtype=np.uint8))
        return [str(panel)]

    monkeypatch.setattr(dark_bg_split, "split_panels", fake_split_panels, raising=False)

    result = process_image_file(source, output_dir=tmp_path / "out", split_mode="dark-webtoon")

    assert called == [("source.png", True)]
    assert result.mode == "dark_bg"
    assert [(cut.cut_index, cut.width, cut.height) for cut in result.cuts] == [(1, 72, 36)]


def test_science_book_page_016_matches_reference_batch_split_count(tmp_path):
    source_pdf = Path(
        "/Users/changkyuneun/Downloads/과학사 100 원본/"
        "과학사_2권_내지_인쇄용_수정.pdf"
    )
    if not source_pdf.exists():
        pytest.skip("local science book regression PDF is not available")

    from backend.app.services.webtoon_panel_engine.runtime import process_pdf_page

    result = process_pdf_page(source_pdf, page_number=16, output_dir=tmp_path / "page-016", dpi=300)

    assert result.mode == "grid"
    assert len(result.cuts) == 4
    assert [(cut.cut_index, cut.width, cut.height) for cut in result.cuts] == [
        (1, 942, 1037),
        (2, 1019, 1103),
        (3, 1032, 968),
        (4, 928, 967),
    ]
