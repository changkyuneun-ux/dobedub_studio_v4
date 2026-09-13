import type { PixelRegion } from "./types";

export function luminance(r: number, g: number, b: number) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function chroma(r: number, g: number, b: number) {
  return Math.max(r, g, b) - Math.min(r, g, b);
}

export function minChannel(r: number, g: number, b: number) {
  return Math.min(r, g, b);
}

export function pixelOffset(width: number, x: number, y: number) {
  return (y * width + x) * 4;
}

export function median(values: number[]) {
  if (!values.length) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function regionWidth(region: PixelRegion) {
  return region.x1 - region.x0;
}

export function regionHeight(region: PixelRegion) {
  return region.y1 - region.y0;
}

export function clampRegion(region: PixelRegion, width: number, height: number): PixelRegion {
  return {
    x0: Math.max(0, Math.min(width, Math.floor(region.x0))),
    y0: Math.max(0, Math.min(height, Math.floor(region.y0))),
    x1: Math.max(0, Math.min(width, Math.ceil(region.x1))),
    y1: Math.max(0, Math.min(height, Math.ceil(region.y1)))
  };
}

export function fullRegion(image: ImageData): PixelRegion {
  return { x0: 0, y0: 0, x1: image.width, y1: image.height };
}
