"""Dark-background vertical webtoon panel splitter.

Ported from ``/Users/changkyuneun/webtoon Pannel/files/dark_bg_split.py``.
This splitter is intentionally separate from ``grid_split.py``: grid handles
printed comics with black panel borders on white paper, while this module
handles borderless image blocks on black/dark-gray scroll backgrounds.
"""

from __future__ import annotations

import collections
import os

import cv2
import numpy as np

EDGE_MARGIN = 3
BG_UNIFORM_TOL = 10
BG_UNIFORM_FRAC = 0.998
BG_MAX_VALUE = 90
BG_MIN_ROWS = 20
BG_MARGIN = 12
GUTTER_FRAC = 0.998
MIN_RUN = 4
MIN_GAP_AT_1440 = 48
NOISE_AREA_RATIO = 0.001
BLANK_TOL = 10
BLANK_FRAC = 0.995
INK_MARGIN = 0.03
INK_DARK = 128
INK_MIN = 0.0002


def estimate_bg_max(gray):
    a = gray[:, EDGE_MARGIN:-EDGE_MARGIN].astype(np.int16)
    ref = np.median(a, axis=1, keepdims=True)
    flat = (np.abs(a - ref) <= BG_UNIFORM_TOL).mean(axis=1) >= BG_UNIFORM_FRAC
    counts = collections.Counter(int(v) for v in ref[:, 0][flat].tolist() if v <= BG_MAX_VALUE)
    common = [v for v, count in counts.items() if count >= BG_MIN_ROWS]
    return (max(common) if common else 0) + BG_MARGIN


def is_gutter_line(line, vmax, frac=GUTTER_FRAC):
    if len(line) == 0:
        return False
    return bool(float((line <= vmax).mean()) >= frac)


def _gutter_profile(sub, axis, vmax):
    dark = sub <= vmax
    return dark.mean(axis=1 if axis == "h" else 0) >= GUTTER_FRAC


def content_runs(gray, region, axis, vmax, min_gap):
    x0, y0, x1, y1 = region
    sub = gray[y0:y1, x0:x1]
    if sub.size == 0:
        return []
    content = ~_gutter_profile(sub, axis, vmax)
    d = np.diff(np.concatenate([[0], content.astype(np.int8), [0]]))
    runs = []
    for a, b in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
        if runs and a - runs[-1][1] < min_gap:
            runs[-1] = (runs[-1][0], b)
        else:
            runs.append((int(a), int(b)))
    base = y0 if axis == "h" else x0
    return [(base + a, base + b) for a, b in runs if b - a >= MIN_RUN]


def xy_cut(gray, region, axis, vmax, min_gap, tried=False):
    runs = content_runs(gray, region, axis, vmax, min_gap)
    if not runs:
        return []
    x0, y0, x1, y1 = region
    nxt = "v" if axis == "h" else "h"

    def narrowed(a, b):
        return (x0, a, x1, b) if axis == "h" else (a, y0, b, y1)

    if len(runs) == 1:
        region2 = narrowed(*runs[0])
        if tried:
            return [region2]
        return xy_cut(gray, region2, nxt, vmax, min_gap, True)

    out = []
    for a, b in runs:
        out.extend(xy_cut(gray, narrowed(a, b), nxt, vmax, min_gap, False))
    return out


def filter_leaves(gray, boxes, width):
    kept = []
    stats = {"noise": 0, "blank": 0}
    min_area = NOISE_AREA_RATIO * width * width
    for box in boxes:
        x0, y0, x1, y1 = box
        if (x1 - x0) * (y1 - y0) < min_area:
            stats["noise"] += 1
            continue
        patch = gray[y0:y1, x0:x1].astype(np.int16)
        if (np.abs(patch - np.median(patch)) <= BLANK_TOL).mean() >= BLANK_FRAC:
            stats["blank"] += 1
            continue
        mx = int((x1 - x0) * INK_MARGIN) + 3
        my = int((y1 - y0) * INK_MARGIN) + 3
        inner = gray[y0 + my:y1 - my, x0 + mx:x1 - mx]
        if inner.size and float((inner < INK_DARK).mean()) < INK_MIN:
            stats["blank"] += 1
            continue
        kept.append(box)
    return kept, stats


def detect_panels(gray):
    h, w = gray.shape
    vmax = estimate_bg_max(gray)
    min_gap = max(1, round(MIN_GAP_AT_1440 * w / 1440))
    boxes = xy_cut(gray, (EDGE_MARGIN, 0, w - EDGE_MARGIN, h), "h", vmax, min_gap)
    boxes, stats = filter_leaves(gray, boxes, w)
    stats["vmax"] = vmax
    return boxes, stats


def split_panels(image_path, out_dir, debug=False, resize_to=None, resize_scale=None):
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    boxes, _ = detect_panels(gray)

    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for index, (x0, y0, x1, y1) in enumerate(boxes, start=1):
        crop = img[y0:y1, x0:x1]
        if resize_to is not None:
            crop = cv2.resize(crop, resize_to, interpolation=cv2.INTER_AREA)
        elif resize_scale is not None:
            nw = max(1, int(crop.shape[1] * resize_scale))
            nh = max(1, int(crop.shape[0] * resize_scale))
            crop = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
        out_path = os.path.join(out_dir, f"panel_{index:02d}.png")
        cv2.imwrite(out_path, crop)
        saved.append(out_path)

    if debug:
        dbg = img.copy()
        for index, (x0, y0, x1, y1) in enumerate(boxes, start=1):
            cv2.rectangle(dbg, (x0, y0), (x1, y1), (0, 0, 255), 8)
            cv2.putText(dbg, str(index), (x0 + 15, y0 + 70), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 0, 255), 6)
        cv2.imwrite(os.path.join(out_dir, "_debug_overlay.png"), dbg)

    return saved
