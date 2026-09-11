import type { CutMode, DetectedCut } from "./types";
import { detectGridCuts } from "./gridDetector";
import { detectStripCuts } from "./stripDetector";
import { detectTransitionCuts } from "./transitionDetector";

export function detectCuts(image: ImageData, mode: CutMode, sourceKind: "image" | "pdf"): DetectedCut[] {
  const effectiveMode = mode === "auto" ? autoMode(image, sourceKind) : mode;
  const cuts = effectiveMode === "strip" ? detectStripCuts(image) : detectGridCuts(image);
  return cuts.map((cut) => withQualityFlags(cut, image));
}

function autoMode(image: ImageData, sourceKind: "image" | "pdf"): Exclude<CutMode, "auto"> {
  if (sourceKind === "pdf") return "page";
  return image.height / image.width >= 2.5 ? "strip" : "page";
}

function withQualityFlags(cut: DetectedCut, image: ImageData): DetectedCut {
  const flags = new Set(cut.flags);
  const width = cut.x1 - cut.x0;
  const height = cut.y1 - cut.y0;
  if (height > width * 3) {
    const transitionCandidates = detectTransitionCuts(image, cut);
    if (transitionCandidates.length > 1) {
      flags.add("review_continuous");
      flags.add("review_required");
    }
  }
  if (height < Math.max(64, image.width * 0.08)) {
    flags.add("thin");
    flags.add("review_required");
  }
  return {
    ...cut,
    flags: [...flags]
  };
}
