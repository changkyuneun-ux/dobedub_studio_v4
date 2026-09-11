import { describe, expect, it } from "vitest";
import { verticalBands } from "./__fixtures__/synthetic";
import { detectStripCuts } from "./stripDetector";

describe("webtoon cut strip detector", () => {
  it("splits foreground bands separated by at least the approved white gap", () => {
    const image = verticalBands(1500, 2200, [[100, 500], [800, 1200], [1500, 1900]]);

    expect(detectStripCuts(image).map(({ y0, y1 }) => [y0, y1])).toEqual([[85, 515], [785, 1215], [1485, 1915]]);
  });

  it("does not split a 99px gap at 1500px width", () => {
    const image = verticalBands(1500, 1000, [[0, 400], [499, 900]]);

    expect(detectStripCuts(image)).toHaveLength(1);
  });
});
