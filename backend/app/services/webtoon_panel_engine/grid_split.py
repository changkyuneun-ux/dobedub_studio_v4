import cv2
import numpy as np
import os
import sys

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
        blackish = (v < 100) & (s < 60)
        score = float(blackish.mean())
        if score > best_score:
            best_score = score
    return best_score


def find_best_divider(region, h_segs, v_segs, gray_v, sat, min_coverage=0.4,
                       min_ink=0.3, margin_frac=0.05):
    x0, y0, x1, y1 = region
    w, h = x1 - x0, y1 - y0
    best = None  # (score, axis, pos)

    h_res = _cluster_and_coverage(h_segs, pos_tol=max(4, h * 0.003),
                                   region_lo=y0 + h * margin_frac, region_hi=y1 - h * margin_frac,
                                   span_lo=x0, span_hi=x1)
    for pos, coverage in h_res:
        if coverage < min_coverage:
            continue
        ink = _ink_score(gray_v, sat, 'h', pos, x0, x1)
        if ink < min_ink:
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
        score = coverage * ink
        if best is None or score > best[0]:
            best = (score, 'v', pos)

    return best


def recursive_split(region, h_segs, v_segs, gray_v, sat, min_area_ratio, total_area, depth=0):
    x0, y0, x1, y1 = region
    area = (x1 - x0) * (y1 - y0)
    if area < total_area * min_area_ratio or depth > 8:
        return [region]

    best = find_best_divider(region, h_segs, v_segs, gray_v, sat)
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
        result.extend(recursive_split(r, h_segs, v_segs, gray_v, sat, min_area_ratio, total_area, depth + 1))
    return result if result else [region]


def _refine_to_border(img, leaf, pad_frac=0.03, min_keep_ratio=0.55):
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
    return (nx0, ny0, nx1, ny1), True


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

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]

    total_area = (x1 - x0) * (y1 - y0)
    regions = recursive_split((x0, y0, x1, y1), h_segs, v_segs, gray, sat, min_area_ratio, total_area)

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

    # 실제 테두리 사각형에 맞춰 경계 미세 조정 (여백/캡션 포함 방지)
    # 테두리를 찾지 못한 영역(예: 제목/헤더 블록처럼 컷 테두리가 없는 장식 영역)은 컷이 아닌 것으로 보고 제외
    if refine_borders:
        refined = []
        for r in regions:
            new_r, ok = _refine_to_border(img, r)
            if ok:
                refined.append(new_r)
        regions = refined

    # 읽기 순서 정렬
    regions.sort(key=lambda r: r[1])
    rows = []
    for r in regions:
        ry0, ry1 = r[1], r[3]
        rh = ry1 - ry0
        placed = False
        for row in rows:
            base = row[0]
            bh = base[3] - base[1]
            if abs(((r[1]+r[3])/2) - ((base[1]+base[3])/2)) < min(rh, bh) * 0.5:
                row.append(r)
                placed = True
                break
        if not placed:
            rows.append([r])
    ordered = []
    for row in rows:
        row.sort(key=lambda r: r[0])
        ordered.extend(row)

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
