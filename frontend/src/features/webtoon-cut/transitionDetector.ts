import { TRANSITION_POLICY } from "./constants";
import { luminance, median, regionWidth } from "./pixels";
import type { PixelRegion } from "./types";

type TransitionCandidate = {
  y: number;
  score: number;
};

export function detectTransitionCuts(image: ImageData, region: PixelRegion): PixelRegion[] {
  const candidates = findTransitionCandidates(image, region);
  const minDistance = Math.max(100, Math.round(regionWidth(region) * 0.15));
  const minSegmentHeight = Math.max(100, Math.round(regionWidth(region) * TRANSITION_POLICY.minSegmentWidthRatio));
  const selected = nonMaximumSuppress(candidates, minDistance)
    .map((candidate) => candidate.y)
    .sort((left, right) => left - right)
    .filter((boundary, index, boundaries) => {
      const previous = index === 0 ? region.y0 : boundaries[index - 1];
      const next = index === boundaries.length - 1 ? region.y1 : boundaries[index + 1];
      return boundary - previous >= minSegmentHeight && next - boundary >= minSegmentHeight;
    });

  if (!selected.length) return [region];

  const cuts: PixelRegion[] = [];
  let y0 = region.y0;
  selected.forEach((boundary) => {
    cuts.push({ x0: region.x0, y0, x1: region.x1, y1: boundary });
    y0 = boundary;
  });
  cuts.push({ x0: region.x0, y0, x1: region.x1, y1: region.y1 });
  return cuts;
}

function findTransitionCandidates(image: ImageData, region: PixelRegion): TransitionCandidate[] {
  const candidates: TransitionCandidate[] = [];
  const step = Math.max(1, Math.floor(regionWidth(region) / TRANSITION_POLICY.analysisWidth));

  for (let y = region.y0 + 1; y < region.y1; y += 1) {
    const jumps: number[] = [];
    let coverageCount = 0;
    for (let x = region.x0; x < region.x1; x += step) {
      const upper = ((y - 1) * image.width + x) * 4;
      const lower = (y * image.width + x) * 4;
      const delta = Math.max(
        Math.abs(image.data[upper] - image.data[lower]),
        Math.abs(image.data[upper + 1] - image.data[lower + 1]),
        Math.abs(image.data[upper + 2] - image.data[lower + 2])
      );
      jumps.push(delta);
      if (delta >= TRANSITION_POLICY.deltaFloor) coverageCount += 1;
    }

    const coverage = coverageCount / jumps.length;
    const medianJump = median(jumps);
    const localContrast = contrastAround(image, region, y, TRANSITION_POLICY.contrastWindow, step);
    if (
      coverage >= TRANSITION_POLICY.minCoverage &&
      medianJump >= TRANSITION_POLICY.minMedianJump &&
      localContrast >= TRANSITION_POLICY.minLocalContrast
    ) {
      candidates.push({
        y,
        score: medianJump * (0.25 + coverage) + 0.35 * localContrast
      });
    }
  }

  return candidates;
}

function contrastAround(image: ImageData, region: PixelRegion, y: number, window: number, step: number) {
  const aboveY0 = Math.max(region.y0, y - window);
  const aboveY1 = y;
  const belowY0 = y;
  const belowY1 = Math.min(region.y1, y + window);
  return Math.abs(averageLuminance(image, region, aboveY0, aboveY1, step) - averageLuminance(image, region, belowY0, belowY1, step));
}

function averageLuminance(image: ImageData, region: PixelRegion, y0: number, y1: number, step: number) {
  let total = 0;
  let count = 0;
  for (let y = y0; y < y1; y += 1) {
    for (let x = region.x0; x < region.x1; x += step) {
      const offset = (y * image.width + x) * 4;
      total += luminance(image.data[offset], image.data[offset + 1], image.data[offset + 2]);
      count += 1;
    }
  }
  return count ? total / count : 0;
}

function nonMaximumSuppress(candidates: TransitionCandidate[], minDistance: number) {
  const selected: TransitionCandidate[] = [];
  [...candidates].sort((left, right) => right.score - left.score).forEach((candidate) => {
    if (selected.every((other) => Math.abs(other.y - candidate.y) >= minDistance)) {
      selected.push(candidate);
    }
  });
  return selected;
}
