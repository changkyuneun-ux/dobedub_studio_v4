from __future__ import annotations

import cv2
import numpy as np


PANEL_BOXES = [
    (40, 100, 680, 700),
    (50, 1050, 670, 1650),
    (45, 2050, 675, 2750),
]


def _draw_panel(gray: np.ndarray, box: tuple[int, int, int, int], *, fill: int, ink: int) -> None:
    x0, y0, x1, y1 = box
    cv2.rectangle(gray, (x0, y0), (x1 - 1, y1 - 1), fill, -1)
    inset_x = max(2, min(60, (x1 - x0) // 4))
    inset_y = max(2, min(60, (y1 - y0) // 4))
    ink_width = max(2, min(60, (x1 - x0) // 3))
    ink_height = max(2, min(60, (y1 - y0) // 3))
    cv2.rectangle(
        gray,
        (x0 + inset_x, y0 + inset_y),
        (min(x1 - 1, x0 + inset_x + ink_width), min(y1 - 1, y0 + inset_y + ink_height)),
        ink,
        -1,
    )


def _light_fixture(*, with_fragment: bool = False) -> np.ndarray:
    gray = np.full((3000, 720), 255, dtype=np.uint8)
    for box in PANEL_BOXES:
        _draw_panel(gray, box, fill=140, ink=0)
    if with_fragment:
        _draw_panel(gray, (20, 2850, 102, 2893), fill=140, ink=0)
    return gray


def test_detect_panels_splits_three_panels_on_a_light_background() -> None:
    from backend.app.services.webtoon_panel_engine.dark_bg_split import detect_panels

    boxes, stats = detect_panels(_light_fixture())

    assert boxes == PANEL_BOXES
    assert stats["bg_mode"] == "light"


def test_detect_panels_preserves_dark_background_behavior() -> None:
    from backend.app.services.webtoon_panel_engine.dark_bg_split import detect_panels

    gray = np.zeros((3000, 720), dtype=np.uint8)
    for box in PANEL_BOXES:
        _draw_panel(gray, box, fill=235, ink=0)

    boxes, stats = detect_panels(gray)

    assert boxes == PANEL_BOXES
    assert stats["bg_mode"] == "dark"


def test_detect_panels_excludes_an_82_by_43_fragment_without_losing_panels() -> None:
    from backend.app.services.webtoon_panel_engine.dark_bg_split import detect_panels

    boxes, stats = detect_panels(_light_fixture(with_fragment=True))

    assert boxes == PANEL_BOXES
    assert stats["small"] == 1
