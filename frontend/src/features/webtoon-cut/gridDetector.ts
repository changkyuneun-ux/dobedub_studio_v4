import { detectGridRegions, orderReadingSequence, pageMargin } from "./gridSplitEngine";
import type { DetectedCut } from "./types";

export function detectGridCuts(image: ImageData): DetectedCut[] {
  // grid_split.py의 split_panels(재귀 분할선 탐색 -> 빈 영역 제거 -> 테두리 보정 ->
  // _looks_like_panel 검증)를 포팅한 detectGridRegions가 최종 leaf들을 돌려준다.
  const regions = detectGridRegions(image);
  if (!regions.length) return [fullpageCut(image)];

  return orderReadingSequence(regions).map((region, index) => ({
    ...region,
    index: index + 1,
    mode: "grid",
    confidence: 0.85,
    flags: []
  }));
}

function fullpageCut(image: ImageData): DetectedCut {
  const margin = pageMargin(image);
  return {
    ...margin,
    index: 1,
    mode: "fullpage",
    confidence: 0.1,
    flags: ["fullpage"]
  };
}
