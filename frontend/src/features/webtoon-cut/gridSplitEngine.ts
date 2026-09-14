import { PAGE_POLICY } from "./constants";
import { edgeInkScore, looksLikePanel } from "./panelBorderCheck";
import { chroma, grayValue, median, pixelOffset } from "./pixels";

export { grayValue };
import type { PixelRegion } from "./types";

/**
 * grid_split.py의 재귀 분할선 탐색 알고리즘 포팅.
 *
 * gridDetector.ts의 원래 접근(findBorderComponents: 잉크 픽셀 연결성분의 바운딩박스를
 * 곧바로 "컷"으로 취급)은, 장식 그림의 잉크가 인접한 실제 컷의 테두리 선에 맞닿아 있으면
 * 둘을 하나의 연결성분으로 묶어버리는 구조적 결함이 있다(page_016류 실사 페이지에서 확인됨).
 *
 * grid_split.py는 이 문제를 다른 방식으로 피한다: 잉크 전체가 아니라 "긴 직선(테두리선) 성분"만
 * 형태학적 opening으로 추출하고, 그 선들을 기준으로 페이지 콘텐츠 영역을 재귀적으로 이분(binary
 * space partition)한다. 장식 그림은 긴 직선을 만들지 않으므로 분할선 후보에 기여하지 않고,
 * 그 결과 장식 영역과 실제 컷은 (실제 컷의 테두리선을 기준으로) 서로 다른 leaf로 분리된다.
 */

type LineSeg = { pos: number; start: number; end: number };

function isInkPixel(r: number, g: number, b: number): boolean {
  // grid_split.py의 _line_thickness가 실제로 쓰는 기준과 동일: gray(BT.601)<100 && chroma<20.
  // (grid_split.py의 split_panels()는 "sat" 인자에 HSV saturation이 아니라 chroma(max-min)를
  // 넘긴다 - 순수 검정 근처에서 HSV saturation이 불안정하게 튀는 문제를 피하기 위함.)
  return grayValue(r, g, b) < 100 && chroma(r, g, b) < 20;
}

export function pageMargin(image: ImageData): PixelRegion {
  const marginX = Math.round(image.width * PAGE_POLICY.outerMarginRatio);
  const marginY = Math.round(image.height * PAGE_POLICY.outerMarginRatio);
  return { x0: marginX, y0: marginY, x1: image.width - marginX, y1: image.height - marginY };
}

function buildDarkMask(image: ImageData, threshold: number): Uint8Array {
  const { width, height, data } = image;
  const mask = new Uint8Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const o = pixelOffset(width, x, y);
      if (grayValue(data[o], data[o + 1], data[o + 2]) < threshold) mask[y * width + x] = 1;
    }
  }
  return mask;
}

/** 가로 방향 형태학적 opening: 각 행에서 길이 >= kernelWidth인 연속 구간만 남긴다. */
function openHorizontal(mask: Uint8Array, width: number, height: number, kernelWidth: number): Uint8Array {
  const out = new Uint8Array(width * height);
  if (kernelWidth < 1) return out;
  for (let y = 0; y < height; y += 1) {
    const rowOffset = y * width;
    let runStart = -1;
    for (let x = 0; x <= width; x += 1) {
      const isDark = x < width && mask[rowOffset + x] === 1;
      if (isDark) {
        if (runStart < 0) runStart = x;
      } else if (runStart >= 0) {
        if (x - runStart >= kernelWidth) {
          for (let k = runStart; k < x; k += 1) out[rowOffset + k] = 1;
        }
        runStart = -1;
      }
    }
  }
  return out;
}

/** 세로 방향 형태학적 opening: 각 열에서 길이 >= kernelHeight인 연속 구간만 남긴다. */
function openVertical(mask: Uint8Array, width: number, height: number, kernelHeight: number): Uint8Array {
  const out = new Uint8Array(width * height);
  if (kernelHeight < 1) return out;
  for (let x = 0; x < width; x += 1) {
    let runStart = -1;
    for (let y = 0; y <= height; y += 1) {
      const isDark = y < height && mask[y * width + x] === 1;
      if (isDark) {
        if (runStart < 0) runStart = y;
      } else if (runStart >= 0) {
        if (y - runStart >= kernelHeight) {
          for (let k = runStart; k < y; k += 1) out[k * width + x] = 1;
        }
        runStart = -1;
      }
    }
  }
  return out;
}

/** 8-연결 성분 라벨링. queue.shift() 대신 스택(push/pop)을 써서 O(n) 유지(큰 이미지에서 O(n^2) 회피). */
function labelComponents(
  mask: Uint8Array,
  width: number,
  height: number
): Array<{ x0: number; y0: number; x1: number; y1: number; area: number }> {
  const visited = new Uint8Array(width * height);
  const results: Array<{ x0: number; y0: number; x1: number; y1: number; area: number }> = [];
  const stack: number[] = [];

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const start = y * width + x;
      if (!mask[start] || visited[start]) continue;
      visited[start] = 1;
      stack.length = 0;
      stack.push(start);
      let x0 = x;
      let x1 = x + 1;
      let y0 = y;
      let y1 = y + 1;
      let area = 0;

      while (stack.length) {
        const current = stack.pop()!;
        const cx = current % width;
        const cy = (current - cx) / width;
        area += 1;
        if (cx < x0) x0 = cx;
        if (cx + 1 > x1) x1 = cx + 1;
        if (cy < y0) y0 = cy;
        if (cy + 1 > y1) y1 = cy + 1;

        for (let dy = -1; dy <= 1; dy += 1) {
          for (let dx = -1; dx <= 1; dx += 1) {
            if (dx === 0 && dy === 0) continue;
            const nx = cx + dx;
            const ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
            const ni = ny * width + nx;
            if (mask[ni] && !visited[ni]) {
              visited[ni] = 1;
              stack.push(ni);
            }
          }
        }
      }

      results.push({ x0, y0, x1, y1, area });
    }
  }
  return results;
}

/** grid_split.py의 get_line_components 포팅. */
function getLineComponents(mask: Uint8Array, width: number, height: number, axis: "h" | "v"): LineSeg[] {
  const segs: LineSeg[] = [];
  for (const c of labelComponents(mask, width, height)) {
    if (c.area < 20) continue;
    if (axis === "h") {
      segs.push({ pos: c.y0 + (c.y1 - c.y0) / 2, start: c.x0, end: c.x1 });
    } else {
      segs.push({ pos: c.x0 + (c.x1 - c.x0) / 2, start: c.y0, end: c.y1 });
    }
  }
  return segs;
}

/** grid_split.py의 _cluster_and_coverage 포팅. */
function clusterAndCoverage(
  segs: LineSeg[],
  posTol: number,
  regionLo: number,
  regionHi: number,
  spanLo: number,
  spanHi: number
): Array<{ pos: number; coverage: number }> {
  const cands = segs.filter((s) => s.pos > regionLo && s.pos < regionHi).sort((a, b) => a.pos - b.pos);
  type Cluster = { members: LineSeg[]; posSum: number; n: number };
  const clusters: Cluster[] = [];
  for (const s of cands) {
    const last = clusters[clusters.length - 1];
    if (last && Math.abs(s.pos - last.posSum / last.n) <= posTol) {
      last.members.push(s);
      last.posSum += s.pos;
      last.n += 1;
    } else {
      clusters.push({ members: [s], posSum: s.pos, n: 1 });
    }
  }

  const spanLen = spanHi - spanLo;
  const results: Array<{ pos: number; coverage: number }> = [];
  for (const c of clusters) {
    const longest = c.members.reduce((best, m) => (m.end - m.start > best.end - best.start ? m : best));
    const pos = longest.pos;
    const intervals = c.members
      .map((m): [number, number] => [Math.max(m.start, spanLo), Math.min(m.end, spanHi)])
      .sort((a, b) => a[0] - b[0]);
    const merged: Array<[number, number]> = [];
    for (const [a, b] of intervals) {
      if (b <= a) continue;
      const lastMerged = merged[merged.length - 1];
      if (lastMerged && a <= lastMerged[1] + spanLen * 0.03) {
        lastMerged[1] = Math.max(lastMerged[1], b);
      } else {
        merged.push([a, b]);
      }
    }
    const covered = merged.reduce((sum, [a, b]) => sum + (b - a), 0);
    results.push({ pos, coverage: spanLen > 0 ? covered / spanLen : 0 });
  }
  return results;
}

/** grid_split.py의 _has_gutter 포팅: 후보선 옆에 흰 여백(거터)이 있는지 검사. */
function hasGutter(
  image: ImageData,
  axis: "h" | "v",
  pos: number,
  lo: number,
  hi: number,
  minOff = 3,
  maxOff = 70,
  whiteThr = 200,
  minFrac = 0.75
): boolean {
  const { width, height, data } = image;
  const spanLo = Math.max(0, Math.floor(lo));
  const spanHi = Math.min(axis === "h" ? width : height, Math.ceil(hi));
  if (spanHi <= spanLo) return false;
  const p0 = Math.round(pos);

  for (const sign of [-1, 1]) {
    for (let off = minOff; off <= maxOff; off += 1) {
      const p = p0 + sign * off;
      if (axis === "h") {
        if (p < 0 || p >= height) break;
      } else if (p < 0 || p >= width) {
        break;
      }
      let whiteCount = 0;
      for (let i = spanLo; i < spanHi; i += 1) {
        const o = axis === "h" ? pixelOffset(width, i, p) : pixelOffset(width, p, i);
        if (grayValue(data[o], data[o + 1], data[o + 2]) > whiteThr) whiteCount += 1;
      }
      if (whiteCount / (spanHi - spanLo) >= minFrac) return true;
    }
  }
  return false;
}

/** grid_split.py의 _line_thickness 포팅: 후보선의 잉크 두께(px) 중앙값. */
function lineThickness(image: ImageData, axis: "h" | "v", pos: number, lo: number, hi: number, step = 5, reach = 15): number {
  const { width, height, data } = image;
  const p0 = Math.round(pos);
  const spanLo = Math.floor(lo);
  const spanHi = Math.ceil(hi);
  const thicknesses: number[] = [];

  for (let i = spanLo; i < spanHi; i += step) {
    const a0 = axis === "h" ? Math.max(0, p0 - reach) : Math.max(0, p0 - reach);
    const a1 = axis === "h" ? Math.min(height, p0 + reach + 1) : Math.min(width, p0 + reach + 1);
    const colInk: boolean[] = [];
    for (let p = a0; p < a1; p += 1) {
      const o = axis === "h" ? pixelOffset(width, i, p) : pixelOffset(width, p, i);
      colInk.push(isInkPixel(data[o], data[o + 1], data[o + 2]));
    }
    const center = p0 - a0;
    let bestIdx = -1;
    let bestDist = Infinity;
    for (let k = 0; k < colInk.length; k += 1) {
      if (colInk[k]) {
        const d = Math.abs(k - center);
        if (d < bestDist) {
          bestDist = d;
          bestIdx = k;
        }
      }
    }
    if (bestIdx < 0) continue;
    let a = bestIdx;
    let b = bestIdx;
    while (a > 0 && colInk[a - 1]) a -= 1;
    while (b < colInk.length - 1 && colInk[b + 1]) b += 1;
    thicknesses.push(b - a + 1);
  }
  return median(thicknesses);
}

/** grid_split.py의 estimate_border_thickness 포팅. */
function estimateBorderThickness(hSegs: LineSeg[], vSegs: LineSeg[], image: ImageData, region: PixelRegion): number | null {
  const { x0, y0, x1, y1 } = region;
  const w = x1 - x0;
  const h = y1 - y0;
  const thicknesses: number[] = [];

  const configs: Array<[axis: "h" | "v", segs: LineSeg[], lo: number, hi: number, slo: number, shi: number, span: number]> = [
    ["h", hSegs, y0, y1, x0, x1, h],
    ["v", vSegs, x0, x1, y0, y1, w]
  ];

  for (const [axis, segs, lo, hi, slo, shi, span] of configs) {
    for (const { pos, coverage } of clusterAndCoverage(segs, Math.max(4, span * 0.003), lo, hi, slo, shi)) {
      if (coverage < 0.6) continue;
      if (edgeInkScore(image, axis, pos, slo, shi, 1) < 0.6) continue;
      const t = lineThickness(image, axis, pos, slo, shi);
      if (t > 0) thicknesses.push(t);
    }
  }
  return thicknesses.length ? median(thicknesses) : null;
}

/** grid_split.py의 find_best_divider 포팅. */
function findBestDivider(
  region: PixelRegion,
  hSegs: LineSeg[],
  vSegs: LineSeg[],
  image: ImageData,
  minThick: number
): { axis: "h" | "v"; pos: number; score: number } | null {
  const { x0, y0, x1, y1 } = region;
  const w = x1 - x0;
  const h = y1 - y0;
  const minCoverage = 0.4;
  const minInk = 0.3;
  const marginFrac = 0.05;

  let best: { axis: "h" | "v"; pos: number; score: number } | null = null;

  const hRes = clusterAndCoverage(hSegs, Math.max(4, h * 0.003), y0 + h * marginFrac, y1 - h * marginFrac, x0, x1);
  for (const { pos, coverage } of hRes) {
    if (coverage < minCoverage) continue;
    const ink = edgeInkScore(image, "h", pos, x0, x1, 1);
    if (ink < minInk) continue;
    if (!hasGutter(image, "h", pos, x0, x1)) continue;
    if (lineThickness(image, "h", pos, x0, x1) < minThick) continue;
    const score = coverage * ink;
    if (!best || score > best.score) best = { axis: "h", pos, score };
  }

  const vRes = clusterAndCoverage(vSegs, Math.max(4, w * 0.003), x0 + w * marginFrac, x1 - w * marginFrac, y0, y1);
  for (const { pos, coverage } of vRes) {
    if (coverage < minCoverage) continue;
    const ink = edgeInkScore(image, "v", pos, y0, y1, 1);
    if (ink < minInk) continue;
    if (!hasGutter(image, "v", pos, y0, y1)) continue;
    if (lineThickness(image, "v", pos, y0, y1) < minThick) continue;
    const score = coverage * ink;
    if (!best || score > best.score) best = { axis: "v", pos, score };
  }

  return best;
}

/** grid_split.py의 recursive_split 포팅. */
function recursiveSplit(
  region: PixelRegion,
  hSegs: LineSeg[],
  vSegs: LineSeg[],
  image: ImageData,
  minAreaRatio: number,
  totalArea: number,
  minThick: number,
  depth = 0
): PixelRegion[] {
  const { x0, y0, x1, y1 } = region;
  const area = (x1 - x0) * (y1 - y0);
  if (area < totalArea * minAreaRatio || depth > PAGE_POLICY.maxDepth) return [region];

  const best = findBestDivider(region, hSegs, vSegs, image, minThick);
  if (!best) return [region];

  const p = Math.round(best.pos);
  const [r1, r2]: [PixelRegion, PixelRegion] =
    best.axis === "h"
      ? [{ x0, y0, x1, y1: p }, { x0, y0: p, x1, y1 }]
      : [{ x0, y0, x1: p, y1 }, { x0: p, y0, x1, y1 }];

  const result: PixelRegion[] = [];
  for (const r of [r1, r2]) {
    if (r.x1 - r.x0 < 5 || r.y1 - r.y0 < 5) continue;
    result.push(...recursiveSplit(r, hSegs, vSegs, image, minAreaRatio, totalArea, minThick, depth + 1));
  }
  return result.length ? result : [region];
}

function darkRatio(dark: Uint8Array, width: number, region: PixelRegion): number {
  const { x0, y0, x1, y1 } = region;
  let count = 0;
  let total = 0;
  for (let y = y0; y < y1; y += 1) {
    for (let x = x0; x < x1; x += 1) {
      total += 1;
      if (dark[y * width + x]) count += 1;
    }
  }
  return total > 0 ? count / total : 0;
}

/**
 * grid_split.py의 _refine_to_border 포팅: 재귀 분할로 얻은 leaf 영역을 실제 인쇄된
 * 테두리 사각형(그 지점 주변에서 가장 큰 어두운 연결 성분의 바운딩박스)에 맞춰 미세 조정한다.
 * (분할선은 테두리 굵기의 중앙에서 잘리므로, 보정 없이는 leaf 경계가 실제 테두리보다
 * 반 굵기만큼 안쪽으로 들어가 있다.)
 */
function refineToBorder(
  image: ImageData,
  leaf: PixelRegion,
  padFrac = 0.03,
  minKeepRatio = 0.55
): { region: PixelRegion; ok: boolean } {
  const { width: wImg, height: hImg, data } = image;
  const { x0, y0, x1, y1 } = leaf;
  const lw = x1 - x0;
  const lh = y1 - y0;
  const padX = Math.floor(lw * padFrac) + 10;
  const padY = Math.floor(lh * padFrac) + 10;
  const ex0 = Math.max(0, x0 - padX);
  const ey0 = Math.max(0, y0 - padY);
  const ex1 = Math.min(wImg, x1 + padX);
  const ey1 = Math.min(hImg, y1 + padY);
  const cropW = ex1 - ex0;
  const cropH = ey1 - ey0;
  if (cropW <= 0 || cropH <= 0) return { region: leaf, ok: false };

  const mask = new Uint8Array(cropW * cropH);
  for (let y = 0; y < cropH; y += 1) {
    for (let x = 0; x < cropW; x += 1) {
      const o = pixelOffset(wImg, ex0 + x, ey0 + y);
      if (grayValue(data[o], data[o + 1], data[o + 2]) < 150) mask[y * cropW + x] = 1;
    }
  }
  const comps = labelComponents(mask, cropW, cropH);
  if (!comps.length) return { region: leaf, ok: false };
  const best = comps.reduce((a, b) => (b.area > a.area ? b : a));
  const nx0 = ex0 + best.x0;
  const ny0 = ey0 + best.y0;
  const nx1 = ex0 + best.x1;
  const ny1 = ey0 + best.y1;

  const ix0 = Math.max(x0, nx0);
  const iy0 = Math.max(y0, ny0);
  const ix1 = Math.min(x1, nx1);
  const iy1 = Math.min(y1, ny1);
  const inter = Math.max(0, ix1 - ix0) * Math.max(0, iy1 - iy0);
  const leafArea = lw * lh;
  const newArea = (nx1 - nx0) * (ny1 - ny0);
  if (leafArea === 0 || newArea === 0) return { region: leaf, ok: false };
  if (inter / leafArea < minKeepRatio || newArea / leafArea < minKeepRatio) return { region: leaf, ok: false };
  return { region: { x0: nx0, y0: ny0, x1: nx1, y1: ny1 }, ok: true };
}

/**
 * grid_split.py의 split_panels 전체 흐름(라인 검출 -> 재귀 분할 -> 빈 영역 제거 ->
 * 테두리 보정 -> _looks_like_panel 검증)에 대응. findBorderComponents(잉크 연결성분
 * 바운딩박스)를 대체한다. 반환값은 looksLikePanel 검증을 이미 통과한 최종 leaf들이다.
 */
export function detectGridRegions(image: ImageData): PixelRegion[] {
  const { width, height } = image;
  const dark = buildDarkMask(image, 150);
  const horizMask = openHorizontal(dark, width, height, Math.max(1, Math.floor(width / 8)));
  const vertMask = openVertical(dark, width, height, Math.max(1, Math.floor(height / 10)));
  const hSegs = getLineComponents(horizMask, width, height, "h");
  const vSegs = getLineComponents(vertMask, width, height, "v");

  const margin = pageMargin(image);
  const totalArea = (margin.x1 - margin.x0) * (margin.y1 - margin.y0);
  const refThickness = estimateBorderThickness(hSegs, vSegs, image, margin);
  const minThick = refThickness ? Math.max(2, refThickness * 0.8) : Math.max(3, height * 0.00135);

  const rawRegions = recursiveSplit(margin, hSegs, vSegs, image, PAGE_POLICY.minAreaRatio, totalArea, minThick);

  const contentFiltered = rawRegions.filter((r) => {
    const contentRatio = darkRatio(dark, width, r);
    if (contentRatio < 0.03) return false;
    const rw = r.x1 - r.x0;
    const rh = r.y1 - r.y0;
    if (rw < width * 0.05 || rh < height * 0.05) return false;
    return true;
  });

  const candidates = contentFiltered.map((r) => {
    const { region: refined, ok } = refineToBorder(image, r);
    const finalRegion = ok ? refined : r;
    const checks = ok ? [r, refined] : [r];
    return { finalRegion, checks };
  });

  // refine 전/후 좌표 중 하나라도 _looks_like_panel을 통과하면 인정한다: refine이 컨투어를
  // 잘못 확장해 경계가 실제 선에서 벗어나는 경우에도, 또 refine 전 좌표가 아직 실제 선에
  // 못 맞춰진 경우에도 진짜 컷을 오검출로 놓치지 않기 위함(grid_split.py와 동일한 전략).
  return candidates
    .filter(({ checks }) => checks.some((c) => looksLikePanel(image, c, margin)))
    .map(({ finalRegion }) => finalRegion);
}

/** grid_split.py의 split_panels 마지막 "읽기 순서 정렬" 블록 포팅: 같은 행끼리 묶은 뒤 좌->우, 행은 상->하. */
export function orderReadingSequence(regions: PixelRegion[]): PixelRegion[] {
  const sorted = [...regions].sort((a, b) => a.y0 - b.y0);
  const rows: PixelRegion[][] = [];
  for (const r of sorted) {
    const rh = r.y1 - r.y0;
    let placed = false;
    for (const row of rows) {
      const base = row[0];
      const bh = base.y1 - base.y0;
      if (Math.abs((r.y0 + r.y1) / 2 - (base.y0 + base.y1) / 2) < Math.min(rh, bh) * 0.5) {
        row.push(r);
        placed = true;
        break;
      }
    }
    if (!placed) rows.push([r]);
  }
  const ordered: PixelRegion[] = [];
  for (const row of rows) {
    row.sort((a, b) => a.x0 - b.x0);
    ordered.push(...row);
  }
  return ordered;
}
