import { describe, expect, it } from "vitest";
import { blankImage, fourPanelPage } from "./__fixtures__/synthetic";
import { looksLikePanel, regionBorderScore } from "./panelBorderCheck";

describe("panelBorderCheck (_looks_like_panel / _region_border_score parity)", () => {
  it("scores all 4 edges high for a real bordered panel", () => {
    const image = fourPanelPage(800, 700);
    const [top, bottom, left, right] = regionBorderScore(image, { x0: 80, y0: 80, x1: 360, y1: 300 });

    expect(top).toBeGreaterThanOrEqual(0.5);
    expect(bottom).toBeGreaterThanOrEqual(0.5);
    expect(left).toBeGreaterThanOrEqual(0.5);
    expect(right).toBeGreaterThanOrEqual(0.5);
  });

  it("accepts a real bordered panel as looksLikePanel", () => {
    const image = fourPanelPage(800, 700);
    const margin = { x0: 24, y0: 21, x1: 776, y1: 679 };

    expect(looksLikePanel(image, { x0: 80, y0: 80, x1: 360, y1: 300 }, margin)).toBe(true);
  });

  it("rejects an arbitrary blank-page region with no ink border", () => {
    const image = blankImage(800, 700);
    const margin = { x0: 24, y0: 21, x1: 776, y1: 679 };

    expect(looksLikePanel(image, { x0: 200, y0: 200, x1: 500, y1: 500 }, margin)).toBe(false);
  });
});
