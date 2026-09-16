import type { PixelRegion } from "./types";

export function orderReadingSequence<T extends PixelRegion>(regions: readonly T[]): T[] {
  const sorted = [...regions].sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0 || a.y1 - b.y1 || a.x1 - b.x1);
  const rows: T[][] = [];

  for (const region of sorted) {
    const row = rows.find((candidate) => sameVisualRow(region, candidate));
    if (row) row.push(region);
    else rows.push([region]);
  }

  return rows
    .sort((a, b) => Math.min(...a.map((item) => item.y0)) - Math.min(...b.map((item) => item.y0)))
    .flatMap((row) => row.sort((a, b) => a.x0 - b.x0 || a.y0 - b.y0 || a.x1 - b.x1 || a.y1 - b.y1));
}

function sameVisualRow(region: PixelRegion, row: readonly PixelRegion[]) {
  const rowY0 = Math.min(...row.map((item) => item.y0));
  const rowY1 = Math.max(...row.map((item) => item.y1));
  const overlap = Math.max(0, Math.min(region.y1, rowY1) - Math.max(region.y0, rowY0));
  const regionHeight = Math.max(1, region.y1 - region.y0);
  const rowHeight = Math.max(1, rowY1 - rowY0);
  const centerDelta = Math.abs((region.y0 + region.y1) / 2 - (rowY0 + rowY1) / 2);
  const tolerance = Math.min(regionHeight, rowHeight);
  return overlap >= tolerance * 0.35 || centerDelta < tolerance * 0.5;
}
