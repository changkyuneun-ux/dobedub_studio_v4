import cv2
import numpy as np
import os
import sys

from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

def get_line_components(mask, axis):
    """axis='h' -> horizontal line segments, axis='v' -> vertical line segments.
    Returns list of dicts: {pos, start, end, x0,y0,x1,y1}"""
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    segs = []
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if area < 20:
            continue
        if axis == 'h':
            segs.append({'pos': y + h / 2, 'start': x, 'end': x + w, 'x0': x, 'y0': y, 'x1': x + w, 'y1': y + h})
        else:
            segs.append({'pos': x + w / 2, 'start': y, 'end': y + h, 'x0': x, 'y0': y, 'x1': x + w, 'y1': y + h})
    return segs


def _cluster_and_coverage(segs, pos_tol, region_lo, region_hi, span_lo, span_hi):
    """같은 좌표(±tol) 근처의 여러 선분(분리되어 검출된 조각들)을 하나로 묶어
    합집합 커버리지를 계산. region_lo/hi = 분할 위치가 유효한 범위(margin 제외)
    span_lo/hi = 커버리지를 재는 축(너비 또는 높이) 범위. 반환: [(pos, coverage), ...]"""
    cands = [s for s in segs if region_lo < s['pos'] < region_hi]
    cands.sort(key=lambda s: s['pos'])
    clusters = []
    for s in cands:
        if clusters and abs(s['pos'] - clusters[-1]['pos_sum'] / clusters[-1]['n']) <= pos_tol:
            c = clusters[-1]
            c['members'].append(s)
            c['pos_sum'] += s['pos']
            c['n'] += 1
        else:
            clusters.append({'members': [s], 'pos_sum': s['pos'], 'n': 1})

    span_len = span_hi - span_lo
    results = []
    for c in clusters:
        # 평균 위치 대신, 가장 긴(신뢰도 높은) 개별 조각의 위치를 대표값으로 사용
        # (근접한 두 개의 서로 다른 테두리선이 한 클러스터로 묶여 평균이 그 사이 흰 여백에
        #  떨어지는 것을 방지)
        longest = max(c['members'], key=lambda m: m['end'] - m['start'])
        pos = longest['pos']
        # 합집합 길이 계산 (겹치는 구간 병합)
        intervals = sorted([(max(m['start'], span_lo), min(m['end'], span_hi)) for m in c['members']])
        merged = []
        for a, b in intervals:
            if b <= a:
                continue
            if merged and a <= merged[-1][1] + span_len * 0.03:  # 작은 틈은 이어붙임
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        covered = sum(b - a for a, b in merged)
        coverage = covered / span_len if span_len > 0 else 0
        results.append((pos, coverage))
    return results


def _ink_score(gray_v, sat, axis, pos, lo, hi, search=1):
    """후보 분할선이 실제 '순수 검정 잉크 테두리'인지 검증.
    axis='h' -> 가로선이므로 y=pos 행을 lo~hi(x범위)로 스캔
    axis='v' -> 세로선이므로 x=pos 열을 lo~hi(y범위)로 스캔
    테두리는 채도가 낮고 매우 어두운 순수 검정 잉크인 반면,
    그림 속 옷/그림자 등은 색이 섞여 채도가 높아 구분됨.
    pos가 두 개의 인접한 테두리선 사이(gutter) 평균으로 살짝 어긋날 수 있으므로
    ±search 범위 내에서 가장 높은 점수를 채택한다."""
    lo, hi = int(lo), int(hi)
    best_score = 0.0
    for offset in range(-search, search + 1):
        p = int(round(pos)) + offset
        if axis == 'h':
            if p < 0 or p >= gray_v.shape[0]:
                continue
            v = gray_v[p, lo:hi]
            s = sat[p, lo:hi]
        else:
            if p < 0 or p >= gray_v.shape[1]:
                continue
            v = gray_v[lo:hi, p]
            s = sat[lo:hi, p]
        if len(v) == 0:
            continue
        blackish = (v < 100) & (s < 20)
        score = float(blackish.mean())
        if score > best_score:
            best_score = score
    return best_score


def _has_gutter(gray_v, axis, pos, lo, hi, min_off=3, max_off=70, white_thr=200, min_frac=0.75):
    """후보 테두리선 바로 옆에 흰 거터가 있는지 검사해 그림 속 선 오검출을 줄인다."""
    lo, hi = int(lo), int(hi)
    p0 = int(round(pos))
    height, width = gray_v.shape
    for sign in (-1, 1):
        for off in range(min_off, max_off + 1):
            p = p0 + sign * off
            if axis == 'h':
                if p < 0 or p >= height:
                    break
                v = gray_v[p, lo:hi]
            else:
                if p < 0 or p >= width:
                    break
                v = gray_v[lo:hi, p]
            if len(v) and (v > white_thr).mean() >= min_frac:
                return True
    return False


def _line_thickness(gray_v, sat, axis, pos, lo, hi, step=5, reach=15):
    """후보선의 잉크 두께 중앙값. 실제 인쇄 컷 테두리와 그림 속 가는 선을 구분한다."""
    ink = (gray_v < 100) & (sat < 20)
    height, width = gray_v.shape
    p0 = int(round(pos))
    thicknesses = []
    for i in range(int(lo), int(hi), step):
        if axis == 'h':
            a0, a1 = max(0, p0 - reach), min(height, p0 + reach + 1)
            col = ink[a0:a1, i]
        else:
            a0, a1 = max(0, p0 - reach), min(width, p0 + reach + 1)
            col = ink[i, a0:a1]
        idx = np.where(col)[0]
        if len(idx) == 0:
            continue
        center = idx[np.argmin(np.abs(idx - (p0 - a0)))]
        a = center
        while a > 0 and col[a - 1]:
            a -= 1
        b = center
        while b < len(col) - 1 and col[b + 1]:
            b += 1
        thicknesses.append(b - a + 1)
    if not thicknesses:
        return 0.0
    return float(np.median(thicknesses))


def estimate_border_thickness(h_segs, v_segs, gray_v, sat, region):
    """페이지별 실제 컷 테두리 굵기를 추정한다."""
    x0, y0, x1, y1 = region
    w, h = x1 - x0, y1 - y0
    thicknesses = []
    for axis, segs, lo, hi, span_lo, span_hi, length in (
        ('h', h_segs, y0, y1, x0, x1, h),
        ('v', v_segs, x0, x1, y0, y1, w),
    ):
        for pos, coverage in _cluster_and_coverage(segs, max(4, length * 0.003), lo, hi, span_lo, span_hi):
            if coverage < 0.6:
                continue
            if _ink_score(gray_v, sat, axis, pos, span_lo, span_hi) < 0.6:
                continue
            thickness = _line_thickness(gray_v, sat, axis, pos, span_lo, span_hi)
            if thickness > 0:
                thicknesses.append(thickness)
    if not thicknesses:
        return None
    return float(np.median(thicknesses))


def find_best_divider(region, h_segs, v_segs, gray_v, sat, min_coverage=0.4,
                       min_ink=0.3, margin_frac=0.05, require_gutter=True, min_thick=None):
    x0, y0, x1, y1 = region
    w, h = x1 - x0, y1 - y0
    best = None  # (score, axis, pos)
    if min_thick is None:
        min_thick = max(3.0, gray_v.shape[0] * 0.00135)

    h_res = _cluster_and_coverage(h_segs, pos_tol=max(4, h * 0.003),
                                   region_lo=y0 + h * margin_frac, region_hi=y1 - h * margin_frac,
                                   span_lo=x0, span_hi=x1)
    for pos, coverage in h_res:
        if coverage < min_coverage:
            continue
        ink = _ink_score(gray_v, sat, 'h', pos, x0, x1)
        if ink < min_ink:
            continue
        if require_gutter and not _has_gutter(gray_v, 'h', pos, x0, x1):
            continue
        if min_thick and _line_thickness(gray_v, sat, 'h', pos, x0, x1) < min_thick:
            continue
        score = coverage * ink
        if best is None or score > best[0]:
            best = (score, 'h', pos)

    v_res = _cluster_and_coverage(v_segs, pos_tol=max(4, w * 0.003),
                                   region_lo=x0 + w * margin_frac, region_hi=x1 - w * margin_frac,
                                   span_lo=y0, span_hi=y1)
    for pos, coverage in v_res:
        if coverage < min_coverage:
            continue
        ink = _ink_score(gray_v, sat, 'v', pos, y0, y1)
        if ink < min_ink:
            continue
        if require_gutter and not _has_gutter(gray_v, 'v', pos, y0, y1):
            continue
        if min_thick and _line_thickness(gray_v, sat, 'v', pos, y0, y1) < min_thick:
            continue
        score = coverage * ink
        if best is None or score > best[0]:
            best = (score, 'v', pos)

    return best


def recursive_split(region, h_segs, v_segs, gray_v, sat, min_area_ratio, total_area, depth=0, min_thick=None):
    x0, y0, x1, y1 = region
    area = (x1 - x0) * (y1 - y0)
    if area < total_area * min_area_ratio or depth > 8:
        return [region]

    best = find_best_divider(region, h_segs, v_segs, gray_v, sat, min_thick=min_thick)
    if best is None:
        return [region]

    _, axis, pos = best
    if axis == 'h':
        r1 = (x0, y0, x1, int(pos))
        r2 = (x0, int(pos), x1, y1)
    else:
        r1 = (x0, y0, int(pos), y1)
        r2 = (int(pos), y0, x1, y1)

    result = []
    for r in (r1, r2):
        rx0, ry0, rx1, ry1 = r
        if rx1 - rx0 < 5 or ry1 - ry0 < 5:
            continue
        result.extend(recursive_split(r, h_segs, v_segs, gray_v, sat, min_area_ratio, total_area, depth + 1, min_thick))
    return result if result else [region]


def _region_border_score(gray_v, sat, region, search=12):
    x0, y0, x1, y1 = region
    top = _ink_score(gray_v, sat, 'h', y0, x0, x1, search=search)
    bottom = _ink_score(gray_v, sat, 'h', y1, x0, x1, search=search)
    left = _ink_score(gray_v, sat, 'v', x0, y0, y1, search=search)
    right = _ink_score(gray_v, sat, 'v', x1, y0, y1, search=search)
    return [top, bottom, left, right]


def _looks_like_panel(gray_v, sat, region, page_margin, min_edge_score=0.5, min_sides=3):
    x0, y0, x1, y1 = region
    mx0, my0, mx1, my1 = page_margin
    page_w, page_h = mx1 - mx0, my1 - my0
    region_w, region_h = x1 - x0, y1 - y0
    full_width_band = x0 <= mx0 + 2 and x1 >= mx1 - 2 and region_h <= page_h * 0.2
    full_height_band = y0 <= my0 + 2 and y1 >= my1 - 2 and region_w <= page_w * 0.2
    if (full_width_band or full_height_band) and _inner_ink_ratio(gray_v, sat, region) < 0.0005:
        return False
    edges = _region_border_score(gray_v, sat, region)
    at_margin = [y0 <= my0 + 2, y1 >= my1 - 2, x0 <= mx0 + 2, x1 >= mx1 - 2]
    checked = [score for score, margin in zip(edges, at_margin) if not margin]
    if len(checked) < 2:
        return False
    passed = sum(1 for score in checked if score >= min_edge_score)
    return passed >= min(min_sides, len(checked))


def _inner_ink_ratio(gray_v, sat, region):
    x0, y0, x1, y1 = region
    w, h = x1 - x0, y1 - y0
    inset = max(8, int(min(w, h) * 0.08))
    ix0, iy0, ix1, iy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inner = (gray_v[iy0:iy1, ix0:ix1] < 100) & (sat[iy0:iy1, ix0:ix1] < 20)
    if inner.size == 0:
        return 0.0
    return float(inner.mean())


def _overlap_len(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def _axis_gap(a0, a1, b0, b1):
    if a1 < b0:
        return b0 - a1
    if b1 < a0:
        return a0 - b1
    return 0


def _is_near_border_protrusion(candidate, core, max_gap):
    cx0, cy0, cx1, cy1 = candidate
    bx0, by0, bx1, by1 = core
    outside_core = cx0 < bx0 or cy0 < by0 or cx1 > bx1 or cy1 > by1
    if not outside_core:
        return False

    x_overlap = _overlap_len(cx0, cx1, bx0, bx1)
    y_overlap = _overlap_len(cy0, cy1, by0, by1)
    x_gap = _axis_gap(cx0, cx1, bx0, bx1)
    y_gap = _axis_gap(cy0, cy1, by0, by1)
    cw, ch = cx1 - cx0, cy1 - cy0
    bw, bh = bx1 - bx0, by1 - by0
    min_x_overlap = max(8, min(cw, bw) * 0.25)
    min_y_overlap = max(8, min(ch, bh) * 0.25)

    return (y_gap <= max_gap and x_overlap >= min_x_overlap) or (
        x_gap <= max_gap and y_overlap >= min_y_overlap
    )


def _expand_to_nearby_ink(img, region, search_region, pad_frac=0.06):
    """컷 테두리 가까이 돌출된 말풍선/텍스트 잉크를 최종 crop에 포함한다."""
    h_img, w_img = img.shape[:2]
    rx0, ry0, rx1, ry1 = region
    sx0, sy0, sx1, sy1 = search_region
    sw, sh = sx1 - sx0, sy1 - sy0
    pad_x, pad_y = int(sw * pad_frac) + 10, int(sh * pad_frac) + 10

    ex0, ey0 = max(0, sx0 - pad_x), max(0, sy0 - pad_y)
    ex1, ey1 = min(w_img, sx1 + pad_x), min(h_img, sy1 + pad_y)
    crop = img[ey0:ey1, ex0:ex1]
    if crop.size == 0:
        return region

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return region

    core = (rx0 - ex0, ry0 - ey0, rx1 - ex0, ry1 - ey0)
    ux0, uy0, ux1, uy1 = core
    max_gap = min(24, max(10, int(min(rx1 - rx0, ry1 - ry0) * 0.03)))
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        candidate = (x, y, x + w, y + h)
        if w * h < 24:
            continue
        if _is_near_border_protrusion(candidate, core, max_gap):
            ux0, uy0 = min(ux0, candidate[0]), min(uy0, candidate[1])
            ux1, uy1 = max(ux1, candidate[2]), max(uy1, candidate[3])

    return (ex0 + ux0, ey0 + uy0, ex0 + ux1, ey0 + uy1)


def _refine_to_border(img, leaf, pad_frac=0.06, min_keep_ratio=0.55, include_nearby_ink=True):
    """재귀 분할로 얻은 leaf 영역을 실제 인쇄된 테두리 사각형에 맞춰 미세 조정.
    (한쪽 변의 구분선을 못 찾아 여백/캡션까지 포함되는 문제를 보정)"""
    h_img, w_img = img.shape[:2]
    x0, y0, x1, y1 = leaf
    lw, lh = x1 - x0, y1 - y0
    pad_x, pad_y = int(lw * pad_frac) + 10, int(lh * pad_frac) + 10

    ex0, ey0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    ex1, ey1 = min(w_img, x1 + pad_x), min(h_img, y1 + pad_y)

    crop = img[ey0:ey1, ex0:ex1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return leaf, False

    best = max(contours, key=cv2.contourArea)
    bx, by, bw, bh = cv2.boundingRect(best)
    nx0, ny0, nx1, ny1 = ex0 + bx, ey0 + by, ex0 + bx + bw, ey0 + by + bh

    ix0, iy0 = max(x0, nx0), max(y0, ny0)
    ix1, iy1 = min(x1, nx1), min(y1, ny1)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    leaf_area = lw * lh
    new_area = bw * bh
    if leaf_area == 0 or new_area == 0:
        return leaf, False
    if inter / leaf_area < min_keep_ratio or new_area / leaf_area < min_keep_ratio:
        return leaf, False
    refined = (nx0, ny0, nx1, ny1)
    if include_nearby_ink:
        refined = _expand_to_nearby_ink(img, refined, leaf, pad_frac=pad_frac)
    return refined, True


def split_panels(image_path, out_dir, inner_margin=None, min_area_ratio=0.02, debug=False,
                  refine_borders=True, resize_to=None, resize_scale=None):
    """
    resize_to: (width, height) 형태로 지정하면 모든 컷을 해당 크기로 강제 리사이즈(비율 무시)
    resize_scale: 0~1 등 배율로 지정하면 각 컷의 원본 비율을 유지한 채 크기만 조정
      (resize_to가 있으면 resize_scale은 무시됨)
    """
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)

    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 8, 1))
    horiz = cv2.morphologyEx(dark, cv2.MORPH_OPEN, hk, iterations=1)
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 10))
    vert = cv2.morphologyEx(dark, cv2.MORPH_OPEN, vk, iterations=1)

    h_segs = get_line_components(horiz, 'h')
    v_segs = get_line_components(vert, 'v')

    if inner_margin is None:
        # 페이지 외곽 여백(재단선/색상바) 자동 추정: 안쪽 컨텐츠 영역만 사용
        x0, y0, x1, y1 = int(w * 0.03), int(h * 0.03), int(w * 0.97), int(h * 0.97)
    else:
        x0, y0, x1, y1 = inner_margin

    sat = (img.max(axis=2).astype(np.int16) - img.min(axis=2).astype(np.int16)).astype(np.uint8)

    total_area = (x1 - x0) * (y1 - y0)
    ref_t = estimate_border_thickness(h_segs, v_segs, gray, sat, (x0, y0, x1, y1))
    min_thick = max(2.0, ref_t * 0.8) if ref_t else max(3.0, h * 0.00135)
    regions = recursive_split((x0, y0, x1, y1), h_segs, v_segs, gray, sat, min_area_ratio, total_area, min_thick=min_thick)

    # 내용이 거의 없는(빈 여백/거터) 영역 제거
    filtered = []
    for (rx0, ry0, rx1, ry1) in regions:
        patch = dark[ry0:ry1, rx0:rx1]
        if patch.size == 0:
            continue
        content_ratio = (patch > 0).mean()
        rw, rh = rx1 - rx0, ry1 - ry0
        if content_ratio < 0.03:
            continue
        if rw < w * 0.05 or rh < h * 0.05:
            continue
        filtered.append((rx0, ry0, rx1, ry1))
    regions = filtered

    page_margin = (x0, y0, x1, y1)
    candidates = []
    for r in regions:
        if refine_borders:
            border_r, ok = _refine_to_border(img, r, include_nearby_ink=False)
        else:
            border_r, ok = r, False
        final_r = _expand_to_nearby_ink(img, border_r, r) if ok else r
        candidates.append((final_r, [r, border_r] if ok else [r]))

    regions = [
        final_r for final_r, checks in candidates
        if any(_looks_like_panel(gray, sat, check, page_margin) for check in checks)
    ]
    ordered = order_reading_sequence(regions)

    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for i, (rx0, ry0, rx1, ry1) in enumerate(ordered, start=1):
        pad = 4
        cx0, cy0 = max(0, rx0 - pad), max(0, ry0 - pad)
        cx1, cy1 = min(w, rx1 + pad), min(h, ry1 + pad)
        crop = img[cy0:cy1, cx0:cx1]

        if resize_to is not None:
            crop = cv2.resize(crop, resize_to, interpolation=cv2.INTER_AREA)
        elif resize_scale is not None:
            nw, nh = max(1, int(crop.shape[1] * resize_scale)), max(1, int(crop.shape[0] * resize_scale))
            crop = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)

        out_path = os.path.join(out_dir, f"panel_{i:02d}.png")
        cv2.imwrite(out_path, crop)
        saved.append(out_path)

    if debug:
        dbg = img.copy()
        for i, (rx0, ry0, rx1, ry1) in enumerate(ordered, start=1):
            cv2.rectangle(dbg, (rx0, ry0), (rx1, ry1), (0, 0, 255), 6)
            cv2.putText(dbg, str(i), (rx0 + 20, ry0 + 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 4)
        cv2.imwrite(os.path.join(out_dir, "_debug_overlay.png"), dbg)

    return saved


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "input.png"
    out = sys.argv[2] if len(sys.argv) > 2 else "panels_grid"

    resize_to = None
    resize_scale = None
    if len(sys.argv) > 3:
        arg = sys.argv[3]
        if "x" in arg.lower():
            wstr, hstr = arg.lower().split("x")
            resize_to = (int(wstr), int(hstr))
        else:
            resize_scale = float(arg)

    result = split_panels(src, out, debug=True, resize_to=resize_to, resize_scale=resize_scale)
    print(f"총 {len(result)}개 컷 분리 완료")
    for p in result:
        print(" -", p)
