from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def test_refine_to_border_keeps_crop_on_panel_border_instead_of_nearby_speech_bubble():
    from backend.app.services.webtoon_panel_engine.grid_split import _refine_to_border

    image = np.full((360, 520, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (120, 120), (460, 320), (0, 0, 0), 5)
    cv2.ellipse(image, (390, 65), (80, 40), 0, 0, 360, (0, 0, 0), 4)
    cv2.putText(image, "TEXT", (350, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    refined, ok = _refine_to_border(image, (100, 40, 480, 330))

    assert ok is True
    assert 100 <= refined[1] <= 130


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
