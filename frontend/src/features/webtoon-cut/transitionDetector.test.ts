import { describe, expect, it } from "vitest";
import { insetFrameEdge, threeSceneStrip } from "./__fixtures__/synthetic";
import { detectCuts } from "./detector";
import { detectTransitionCuts } from "./transitionDetector";

describe("webtoon cut full-width transition detector", () => {
  it("accepts two near-full-width transitions and creates three cuts", () => {
    const image = threeSceneStrip(1500, 8521, [2843, 3754]);

    expect(detectTransitionCuts(image, { x0: 0, y0: 0, x1: 1500, y1: 8521 }).map(({ y0, y1 }) => [y0, y1])).toEqual([
      [0, 2843],
      [2843, 3754],
      [3754, 8521]
    ]);
  });

  it("rejects an 84 percent inset frame edge", () => {
    const image = insetFrameEdge(1500, 1200, 329, 0.84);

    expect(detectTransitionCuts(image, { x0: 0, y0: 0, x1: 1500, y1: 1200 })).toEqual([
      { x0: 0, y0: 0, x1: 1500, y1: 1200 }
    ]);
  });

  it("keeps full-width transitions as review metadata in the default pass", () => {
    const image = threeSceneStrip(1500, 8521, [2843, 3754]);

    const cuts = detectCuts(image, "auto", "image");

    expect(cuts).toHaveLength(1);
    expect(cuts[0].flags).toEqual(expect.arrayContaining(["review_continuous", "review_required"]));
  });
});
