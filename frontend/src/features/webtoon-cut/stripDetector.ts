import { STRIP_POLICY } from "./constants";
import { chroma, minChannel } from "./pixels";
import type { DetectedCut, PixelRegion } from "./types";

export function detectStripCuts(image: ImageData): DetectedCut[] {
  const activeRows = computeActiveRows(image);
  const activeSpans = rowsToActiveSpans(activeRows);
  if (!activeSpans.length) return [fullpageCut(image.width, image.height)];

  const minGap = Math.max(STRIP_POLICY.minGapPx, Math.round(image.width * STRIP_POLICY.gapWidthRatio));
  const regions: PixelRegion[] = [];
  let start = activeSpans[0][0];
  let end = activeSpans[0][1];

  for (let index = 1; index < activeSpans.length; index += 1) {
    const [nextStart, nextEnd] = activeSpans[index];
    if (nextStart - end >= minGap) {
      regions.push(paddedRegion(image.width, image.height, start, end));
      start = nextStart;
      end = nextEnd;
    } else {
      end = nextEnd;
    }
  }
  regions.push(paddedRegion(image.width, image.height, start, end));

  return mergeRegions(regions).map((region, index) => ({
    ...region,
    index: index + 1,
    mode: "gutter",
    confidence: 0.9,
    flags: []
  }));
}

function computeActiveRows(image: ImageData) {
  const rows = new Uint8Array(image.height);
  const { data, width, height } = image;
  for (let y = 0; y < height; y += 1) {
    let foreground = 0;
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      const r = data[offset];
      const g = data[offset + 1];
      const b = data[offset + 2];
      if (minChannel(r, g, b) < STRIP_POLICY.foregroundFloor || chroma(r, g, b) > STRIP_POLICY.chromaFloor) {
        foreground += 1;
      }
    }
    if (foreground / width >= STRIP_POLICY.rowRatio) rows[y] = 1;
  }
  return rows;
}

function rowsToActiveSpans(rows: Uint8Array): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  let y = 0;
  while (y < rows.length) {
    while (y < rows.length && rows[y] === 0) y += 1;
    if (y >= rows.length) break;
    const start = y;
    while (y < rows.length && rows[y] === 1) y += 1;
    spans.push([start, y]);
  }
  return spans;
}

function paddedRegion(width: number, height: number, y0: number, y1: number): PixelRegion {
  return {
    x0: 0,
    y0: Math.max(0, y0 - STRIP_POLICY.paddingY),
    x1: width,
    y1: Math.min(height, y1 + STRIP_POLICY.paddingY)
  };
}

function mergeRegions(regions: PixelRegion[]) {
  const merged: PixelRegion[] = [];
  regions.forEach((region) => {
    const previous = merged[merged.length - 1];
    if (previous && region.y0 <= previous.y1) {
      previous.y1 = Math.max(previous.y1, region.y1);
    } else {
      merged.push({ ...region });
    }
  });
  return merged;
}

function fullpageCut(width: number, height: number): DetectedCut {
  return {
    x0: 0,
    y0: 0,
    x1: width,
    y1: height,
    index: 1,
    mode: "fullpage",
    confidence: 0.1,
    flags: ["fullpage"]
  };
}
