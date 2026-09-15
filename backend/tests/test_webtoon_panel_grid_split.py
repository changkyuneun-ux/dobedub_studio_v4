from __future__ import annotations

import cv2
import numpy as np


def test_refine_to_border_preserves_nearby_speech_bubble_protrusion():
    from backend.app.services.webtoon_panel_engine.grid_split import _refine_to_border

    image = np.full((360, 520, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (120, 120), (460, 320), (0, 0, 0), 5)
    cv2.ellipse(image, (390, 65), (80, 40), 0, 0, 360, (0, 0, 0), 4)
    cv2.putText(image, "TEXT", (350, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    refined, ok = _refine_to_border(image, (100, 40, 480, 330))

    assert ok is True
    assert refined[1] <= 30
