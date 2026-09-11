import { describe, expect, it } from "vitest";
import { borderlessInfographic, fourPanelPage } from "./__fixtures__/synthetic";
import { detectGridCuts } from "./gridDetector";

describe("webtoon cut page/grid detector", () => {
  it("returns bordered panels in top-to-bottom then left-to-right order", () => {
    const image = fourPanelPage(800, 700);

    expect(detectGridCuts(image).map(({ x0, y0, x1, y1 }) => [x0, y0, x1, y1])).toEqual([
      [80, 80, 360, 300],
      [440, 80, 720, 300],
      [80, 380, 360, 600],
      [440, 380, 720, 600]
    ]);
  });

  it("marks borderless infographic as a single fullpage result", () => {
    const image = borderlessInfographic(800, 700);

    const cuts = detectGridCuts(image);

    expect(cuts).toHaveLength(1);
    expect(cuts[0].mode).toBe("fullpage");
    expect(cuts[0].flags).toEqual(expect.arrayContaining(["fullpage", "review_required"]));
  });
});
