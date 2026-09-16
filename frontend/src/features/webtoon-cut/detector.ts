import { detectPanels } from "./darkBgSplitEngine";
import type { CutMode, DetectedCut, WebtoonCutSplitMode } from "./types";
import { detectGridCuts } from "./gridDetector";
import { detectStripCuts } from "./stripDetector";
import { detectTransitionCuts } from "./transitionDetector";

export function detectCuts(
  image: ImageData,
  mode: CutMode,
  sourceKind: "image" | "pdf",
  splitMode: WebtoonCutSplitMode = "print"
): DetectedCut[] {
  if (splitMode === "dark-webtoon") {
    const { boxes } = detectPanels(image);
    const cuts = boxes.length
      ? boxes.map((region, index): DetectedCut => ({
          ...region,
          index: index + 1,
          mode: "dark_bg",
          confidence: 0.88,
          flags: []
        }))
      : [darkFullpageCut(image)];
    return cuts.map((cut) => withQualityFlags(cut, image));
  }

  const effectiveMode = mode === "auto" ? autoMode(image, sourceKind) : mode;
  const cuts = effectiveMode === "strip" ? detectStripCuts(image) : detectGridCuts(image);
  return cuts.map((cut) => withQualityFlags(cut, image));
}

function autoMode(image: ImageData, sourceKind: "image" | "pdf"): Exclude<CutMode, "auto"> {
  if (sourceKind === "pdf") return "page";
  return image.height / image.width >= 2.5 ? "strip" : "page";
}

function darkFullpageCut(image: ImageData): DetectedCut {
  return {
    x0: 0,
    y0: 0,
    x1: image.width,
    y1: image.height,
    index: 1,
    mode: "fullpage",
    confidence: 0.1,
    flags: ["fullpage"]
  };
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
