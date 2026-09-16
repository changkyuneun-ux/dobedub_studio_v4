from __future__ import annotations


def test_reading_order_sorts_vertical_stack_top_to_bottom():
    from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

    boxes = [
        (30, 420, 230, 520),
        (20, 40, 220, 140),
        (25, 230, 225, 330),
    ]

    assert order_reading_sequence(boxes) == [
        (20, 40, 220, 140),
        (25, 230, 225, 330),
        (30, 420, 230, 520),
    ]


def test_reading_order_sorts_same_row_left_to_right_before_next_row():
    from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

    boxes = [
        (500, 470, 850, 900),
        (80, 40, 420, 180),
        (460, 40, 800, 180),
        (70, 220, 820, 380),
        (70, 470, 420, 900),
    ]

    assert order_reading_sequence(boxes) == [
        (80, 40, 420, 180),
        (460, 40, 800, 180),
        (70, 220, 820, 380),
        (70, 470, 420, 900),
        (500, 470, 850, 900),
    ]


def test_reading_order_groups_slightly_staggered_same_row_by_vertical_overlap():
    from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

    boxes = [
        (260, 70, 470, 240),
        (20, 40, 230, 210),
        (25, 300, 460, 440),
    ]

    assert order_reading_sequence(boxes) == [
        (20, 40, 230, 210),
        (260, 70, 470, 240),
        (25, 300, 460, 440),
    ]
