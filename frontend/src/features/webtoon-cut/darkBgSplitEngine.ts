import { grayValue, pixelOffset } from "./pixels";
import type { PixelRegion } from "./types";

export const EDGE_MARGIN = 3;
export const BG_UNIFORM_TOL = 10;
export const BG_UNIFORM_FRAC = 0.998;
export const BG_MAX_VALUE = 90;
export const BG_MIN_ROWS = 20;
export const BG_MARGIN = 12;
export const GUTTER_FRAC = 0.998;
export const MIN_RUN = 4;
export const MIN_GAP_AT_1440 = 48;
export const NOISE_AREA_RATIO = 0.001;
export const BLANK_TOL = 10;
export const BLANK_FRAC = 0.995;
export const INK_MARGIN = 0.03;
export const INK_DARK = 128;
export const INK_MIN = 0.0002;

type Axis = "h" | "v";

type GrayImage = {
  width: number;
  height: number;
  data: Uint8Array;
};

export type DarkBgSplitStats = {
  noise: number;
  blank: number;
  vmax: number;
};

export type DarkBgSplitResult = {
  boxes: PixelRegion[];
  stats: DarkBgSplitStats;
};

export function estimateBgMax(image: ImageData | GrayImage): number {
  const gray = toGrayImage(image);
  const x0 = Math.min(EDGE_MARGIN, gray.width);
  const x1 = Math.max(x0, gray.width - EDGE_MARGIN);
  const counts = new Map<number, number>();

  for (let y = 0; y < gray.height; y += 1) {
    const values = rowValues(gray, y, x0, x1);
    if (!values.length) continue;
    const ref = median(values);
    let same = 0;
    for (const value of values) {
      if (Math.abs(value - ref) <= BG_UNIFORM_TOL) same += 1;
    }
    if (same / values.length >= BG_UNIFORM_FRAC && ref <= BG_MAX_VALUE) {
      const key = Math.floor(ref);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }

  let commonMax = 0;
  for (const [value, count] of counts) {
    if (count >= BG_MIN_ROWS && value > commonMax) commonMax = value;
  }
  return commonMax + BG_MARGIN;
}

export function isGutterLine(line: ArrayLike<number>, vmax: number, frac = GUTTER_FRAC): boolean {
  if (line.length === 0) return false;
  let dark = 0;
  for (let index = 0; index < line.length; index += 1) {
    if (line[index] <= vmax) dark += 1;
  }
  return dark / line.length >= frac;
}

export function contentRuns(
  image: ImageData | GrayImage,
  region: PixelRegion,
  axis: Axis,
  vmax: number,
  minGap: number
): Array<[number, number]> {
  const gray = toGrayImage(image);
  const clipped = clipRegion(region, gray.width, gray.height);
  if (clipped.x1 <= clipped.x0 || clipped.y1 <= clipped.y0) return [];
  const content = gutterProfile(gray, clipped, axis, vmax).map((isGutter) => !isGutter);
  const runs: Array<[number, number]> = [];
  let start = -1;
  for (let index = 0; index <= content.length; index += 1) {
    const isContent = index < content.length && content[index];
    if (isContent) {
      if (start < 0) start = index;
    } else if (start >= 0) {
      if (runs.length && start - runs[runs.length - 1][1] < minGap) {
        runs[runs.length - 1][1] = index;
      } else {
        runs.push([start, index]);
      }
      start = -1;
    }
  }
  const base = axis === "h" ? clipped.y0 : clipped.x0;
  return runs
    .filter(([a, b]) => b - a >= MIN_RUN)
    .map(([a, b]) => [base + a, base + b]);
}

export function xyCut(
  image: ImageData | GrayImage,
  region: PixelRegion,
  axis: Axis,
  vmax: number,
  minGap: number,
  tried = false
): PixelRegion[] {
  const gray = toGrayImage(image);
  const runs = contentRuns(gray, region, axis, vmax, minGap);
  if (!runs.length) return [];
  const clipped = clipRegion(region, gray.width, gray.height);
  const nextAxis: Axis = axis === "h" ? "v" : "h";
  const narrow = ([a, b]: [number, number]): PixelRegion => (
    axis === "h"
      ? { x0: clipped.x0, y0: a, x1: clipped.x1, y1: b }
      : { x0: a, y0: clipped.y0, x1: b, y1: clipped.y1 }
  );

  if (runs.length === 1) {
    const narrowed = narrow(runs[0]);
    if (tried) return [narrowed];
    return xyCut(gray, narrowed, nextAxis, vmax, minGap, true);
  }

  return runs.flatMap((run) => xyCut(gray, narrow(run), nextAxis, vmax, minGap, false));
}

export function filterLeaves(
  image: ImageData | GrayImage,
  boxes: PixelRegion[],
  width: number
): { boxes: PixelRegion[]; stats: Omit<DarkBgSplitStats, "vmax"> } {
  const gray = toGrayImage(image);
  const minArea = NOISE_AREA_RATIO * width * width;
  const stats = { noise: 0, blank: 0 };
  const kept: PixelRegion[] = [];

  for (const raw of boxes) {
    const box = clipRegion(raw, gray.width, gray.height);
    const boxWidth = box.x1 - box.x0;
    const boxHeight = box.y1 - box.y0;
    if (boxWidth <= 0 || boxHeight <= 0 || boxWidth * boxHeight < minArea) {
      stats.noise += 1;
      continue;
    }
    const values = regionValues(gray, box);
    const med = median(values);
    let nearMedian = 0;
    for (const value of values) {
      if (Math.abs(value - med) <= BLANK_TOL) nearMedian += 1;
    }
    if (nearMedian / values.length >= BLANK_FRAC) {
      stats.blank += 1;
      continue;
    }

    const marginX = Math.floor(boxWidth * INK_MARGIN) + 3;
    const marginY = Math.floor(boxHeight * INK_MARGIN) + 3;
    const inner: PixelRegion = {
      x0: box.x0 + marginX,
      y0: box.y0 + marginY,
      x1: box.x1 - marginX,
      y1: box.y1 - marginY
    };
    const innerArea = (inner.x1 - inner.x0) * (inner.y1 - inner.y0);
    if (innerArea > 0) {
      let dark = 0;
      for (let y = inner.y0; y < inner.y1; y += 1) {
        for (let x = inner.x0; x < inner.x1; x += 1) {
          if (gray.data[y * gray.width + x] < INK_DARK) dark += 1;
        }
      }
      if (dark / innerArea < INK_MIN) {
        stats.blank += 1;
        continue;
      }
    }

    kept.push(box);
  }

  return { boxes: kept, stats };
}

export function detectPanels(image: ImageData | GrayImage): DarkBgSplitResult {
  const gray = toGrayImage(image);
  const vmax = estimateBgMax(gray);
  const minGap = Math.max(1, Math.round(MIN_GAP_AT_1440 * gray.width / 1440));
  const boxes = xyCut(
    gray,
    { x0: Math.min(EDGE_MARGIN, gray.width), y0: 0, x1: Math.max(0, gray.width - EDGE_MARGIN), y1: gray.height },
    "h",
    vmax,
    minGap
  );
  const filtered = filterLeaves(gray, boxes, gray.width);
  return {
    boxes: filtered.boxes,
    stats: {
      ...filtered.stats,
      vmax
    }
  };
}

function toGrayImage(image: ImageData | GrayImage): GrayImage {
  if ("data" in image && image.data instanceof Uint8Array && !("colorSpace" in image)) return image;
  const source = image as ImageData;
  const data = new Uint8Array(source.width * source.height);
  for (let y = 0; y < source.height; y += 1) {
    for (let x = 0; x < source.width; x += 1) {
      const offset = pixelOffset(source.width, x, y);
      data[y * source.width + x] = Math.round(grayValue(source.data[offset], source.data[offset + 1], source.data[offset + 2]));
    }
  }
  return { width: source.width, height: source.height, data };
}

function gutterProfile(gray: GrayImage, region: PixelRegion, axis: Axis, vmax: number): boolean[] {
  const profile: boolean[] = [];
  if (axis === "h") {
    const line = new Uint8Array(region.x1 - region.x0);
    for (let y = region.y0; y < region.y1; y += 1) {
      for (let x = region.x0; x < region.x1; x += 1) {
        line[x - region.x0] = gray.data[y * gray.width + x];
      }
      profile.push(isGutterLine(line, vmax));
    }
    return profile;
  }

  const line = new Uint8Array(region.y1 - region.y0);
  for (let x = region.x0; x < region.x1; x += 1) {
    for (let y = region.y0; y < region.y1; y += 1) {
      line[y - region.y0] = gray.data[y * gray.width + x];
    }
    profile.push(isGutterLine(line, vmax));
  }
  return profile;
}

function rowValues(gray: GrayImage, y: number, x0: number, x1: number): number[] {
  const values: number[] = [];
  for (let x = x0; x < x1; x += 1) {
    values.push(gray.data[y * gray.width + x]);
  }
  return values;
}

function regionValues(gray: GrayImage, region: PixelRegion): number[] {
  const values: number[] = [];
  for (let y = region.y0; y < region.y1; y += 1) {
    for (let x = region.x0; x < region.x1; x += 1) {
      values.push(gray.data[y * gray.width + x]);
    }
  }
  return values;
}

function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function clipRegion(region: PixelRegion, width: number, height: number): PixelRegion {
  return {
    x0: Math.max(0, Math.min(width, Math.floor(region.x0))),
    y0: Math.max(0, Math.min(height, Math.floor(region.y0))),
    x1: Math.max(0, Math.min(width, Math.ceil(region.x1))),
    y1: Math.max(0, Math.min(height, Math.ceil(region.y1)))
  };
}
