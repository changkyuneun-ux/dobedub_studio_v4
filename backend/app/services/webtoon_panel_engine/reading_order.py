from __future__ import annotations

from typing import Iterable, TypeAlias

Box: TypeAlias = tuple[int, int, int, int]


def order_reading_sequence(boxes: Iterable[Box]) -> list[Box]:
    """Return boxes in visual reading order: top-to-bottom, then left-to-right."""
    sorted_boxes = sorted(list(boxes), key=lambda box: (box[1], box[0], box[3], box[2]))
    rows: list[list[Box]] = []

    for box in sorted_boxes:
        for row in rows:
            if _same_visual_row(box, row):
                row.append(box)
                break
        else:
            rows.append([box])

    ordered: list[Box] = []
    for row in sorted(rows, key=lambda items: min(item[1] for item in items)):
        ordered.extend(sorted(row, key=lambda item: (item[0], item[1], item[2], item[3])))
    return ordered


def _same_visual_row(box: Box, row: list[Box]) -> bool:
    row_y0 = min(item[1] for item in row)
    row_y1 = max(item[3] for item in row)
    box_y0, box_y1 = box[1], box[3]
    overlap = max(0, min(box_y1, row_y1) - max(box_y0, row_y0))
    box_height = max(1, box_y1 - box_y0)
    row_height = max(1, row_y1 - row_y0)
    center_delta = abs(((box_y0 + box_y1) / 2) - ((row_y0 + row_y1) / 2))
    row_tolerance = min(box_height, row_height)
    return overlap >= row_tolerance * 0.35 or center_delta < row_tolerance * 0.5
