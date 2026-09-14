import { chroma, grayValue, pixelOffset } from "./pixels";
import type { PixelRegion } from "./types";

/**
 * grid_split.py의 _ink_score 포팅.
 * axis="h" -> pos行(row)을 lo~hi(x범위)로 스캔, axis="v" -> pos열(col)을 lo~hi(y범위)로 스캔.
 * 후보 분할선/변이 실제 검정 잉크 테두리인지, 그 자리 근방(±search)에서 가장 높은
 * "잉크 픽셀 비율"을 채택한다. 그림 속 색이 섞인 선(옷/그림자)과 순수 검정 테두리를 구분하기 위해 grid_split.py의
 * split_panels()가 실제로 쓰는 기준(gray(BT.601)<100 && chroma(max-min)<20)과 동일하게 맞춘다.
 * (grid_split.py는 인자 이름이 "sat"이지만 실제로는 HSV saturation이 아니라 chroma를 넘긴다 -
 * 순수 검정 근처에서 HSV saturation이 불안정하게 튀는 문제를 피하기 위해 저자가 의도적으로 그렇게 함.)
 */
export function edgeInkScore(
  image: ImageData,
  axis: "h" | "v",
  pos: number,
  lo: number,
  hi: number,
  search: number
): number {
  const { width, height, data } = image;
  const spanLo = Math.max(0, Math.floor(lo));
  const spanHi = Math.min(axis === "h" ? width : height, Math.ceil(hi));
  if (spanHi <= spanLo) return 0;

  let best = 0;
  for (let offset = -search; offset <= search; offset += 1) {
    const p = Math.round(pos) + offset;
    if (axis === "h") {
      if (p < 0 || p >= height) continue;
    } else if (p < 0 || p >= width) {
      continue;
    }

    let inkCount = 0;
    for (let i = spanLo; i < spanHi; i += 1) {
      const offsetPx = axis === "h" ? pixelOffset(width, i, p) : pixelOffset(width, p, i);
      const r = data[offsetPx];
      const g = data[offsetPx + 1];
      const b = data[offsetPx + 2];
      if (grayValue(r, g, b) < 100 && chroma(r, g, b) < 20) inkCount += 1;
    }
    const score = inkCount / (spanHi - spanLo);
    if (score > best) best = score;
  }
  return best;
}

function defaultSearch(image: ImageData): number {
  return Math.max(2, Math.min(12, Math.round(Math.min(image.width, image.height) * 0.004)));
}

/**
 * grid_split.py의 _region_border_score 포팅: region의 네 변(상/하/좌/우) 각각에
 * 실제 검정 잉크 테두리선이 있는지 [top, bottom, left, right] 점수로 반환.
 */
export function regionBorderScore(image: ImageData, region: PixelRegion, search?: number): [number, number, number, number] {
  const s = search ?? defaultSearch(image);
  const { x0, y0, x1, y1 } = region;
  const top = edgeInkScore(image, "h", y0, x0, x1, s);
  const bottom = edgeInkScore(image, "h", y1, x0, x1, s);
  const left = edgeInkScore(image, "v", x0, y0, y1, s);
  const right = edgeInkScore(image, "v", x1, y0, y1, s);
  return [top, bottom, left, right];
}

/**
 * grid_split.py의 _looks_like_panel 포팅.
 * region이 실제 컷(사각 테두리로 닫힌 영역)인지 검증한다. 장식/제목 그림처럼
 * 사각 테두리가 전혀 없는 영역(연결된 잉크 성분의 바운딩박스일 뿐인 경우)을
 * 컷으로 오인식하지 않도록 걸러낸다.
 *
 * 페이지 바깥 여백(pageMargin)과 맞닿은 변은 원래 테두리선이 없을 수 있으므로
 * (트림에 블리드된 컷) 검사에서 제외하되, 검사 대상 변이 2개 미만으로 줄어들면
 * (예: 3면이 모두 페이지 여백인 장식 영역) 그 여유를 악용해 통과하는 것을
 * 막기 위해 무조건 불합격 처리한다.
 */
export function looksLikePanel(
  image: ImageData,
  region: PixelRegion,
  pageMargin: PixelRegion,
  minEdgeScore = 0.5,
  minSides = 3
): boolean {
  const edges = regionBorderScore(image, region);
  const atMargin = [
    region.y0 <= pageMargin.y0 + 2,
    region.y1 >= pageMargin.y1 - 2,
    region.x0 <= pageMargin.x0 + 2,
    region.x1 >= pageMargin.x1 - 2
  ];
  const checked = edges.filter((_, index) => !atMargin[index]);
  if (checked.length < 2) return false;
  const passed = checked.filter((score) => score >= minEdgeScore).length;
  const need = Math.min(minSides, checked.length);
  return passed >= need;
}
