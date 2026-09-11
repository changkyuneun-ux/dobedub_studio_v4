import { PAGE_POLICY } from "./constants";
import { chroma, minChannel } from "./pixels";
import type { DetectedCut, PixelRegion } from "./types";

export function detectGridCuts(image: ImageData): DetectedCut[] {
  const regions = findBorderComponents(image);
  if (!regions.length) return [fullpageCut(image)];

  return regions
    .sort((left, right) => left.y0 - right.y0 || left.x0 - right.x0)
    .map((region, index) => ({
      ...region,
      index: index + 1,
      mode: "grid",
      confidence: 0.85,
      flags: []
    }));
}

function findBorderComponents(image: ImageData): PixelRegion[] {
  const width = image.width;
  const height = image.height;
  const mask = new Uint8Array(width * height);
  const visited = new Uint8Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      const r = image.data[offset];
      const g = image.data[offset + 1];
      const b = image.data[offset + 2];
      if (minChannel(r, g, b) < 80 && chroma(r, g, b) < 40) {
        mask[y * width + x] = 1;
      }
    }
  }

  const minArea = width * height * PAGE_POLICY.minAreaRatio;
  const regions: PixelRegion[] = [];
  const queue: number[] = [];
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const start = y * width + x;
      if (!mask[start] || visited[start]) continue;
      visited[start] = 1;
      queue.push(start);
      let x0 = x;
      let x1 = x + 1;
      let y0 = y;
      let y1 = y + 1;
      let pixels = 0;
      while (queue.length) {
        const current = queue.shift()!;
        const cx = current % width;
        const cy = Math.floor(current / width);
        pixels += 1;
        x0 = Math.min(x0, cx);
        x1 = Math.max(x1, cx + 1);
        y0 = Math.min(y0, cy);
        y1 = Math.max(y1, cy + 1);
        visit(cx + 1, cy);
        visit(cx - 1, cy);
        visit(cx, cy + 1);
        visit(cx, cy - 1);
      }

      const boxArea = (x1 - x0) * (y1 - y0);
      if (boxArea >= minArea && pixels >= Math.max(8, Math.round(Math.sqrt(boxArea)))) {
        regions.push({ x0, y0, x1, y1 });
      }
    }
  }

  return regions;

  function visit(x: number, y: number) {
    if (x < 0 || y < 0 || x >= width || y >= height) return;
    const index = y * width + x;
    if (!mask[index] || visited[index]) return;
    visited[index] = 1;
    queue.push(index);
  }
}

function fullpageCut(image: ImageData): DetectedCut {
  const marginX = Math.round(image.width * PAGE_POLICY.outerMarginRatio);
  const marginY = Math.round(image.height * PAGE_POLICY.outerMarginRatio);
  return {
    x0: marginX,
    y0: marginY,
    x1: image.width - marginX,
    y1: image.height - marginY,
    index: 1,
    mode: "fullpage",
    confidence: 0.1,
    flags: ["fullpage"]
  };
}
