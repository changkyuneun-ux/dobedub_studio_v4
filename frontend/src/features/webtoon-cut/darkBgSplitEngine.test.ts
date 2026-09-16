import { describe, expect, it } from "vitest";
import { blankImage } from "./__fixtures__/synthetic";
import {
  detectPanels,
  EDGE_MARGIN,
  estimateBgMax
} from "./darkBgSplitEngine";
import { detectCuts } from "./detector";
import type { PixelRegion } from "./types";

describe("darkBgSplitEngine", () => {
  it("detects three vertically stacked panels on a black webtoon background", () => {
    const image = blankImage(240, 720, [0, 0, 0]);
    drawPanel(image, { x0: 20, y0: 30, x1: 220, y1: 180 });
    drawPanel(image, { x0: 30, y0: 250, x1: 210, y1: 400 });
    drawPanel(image, { x0: 25, y0: 470, x1: 215, y1: 650 });

    const { boxes, stats } = detectPanels(image);

    expect(stats.vmax).toBe(12);
    expect(boxes).toEqual([
      { x0: 20, y0: 30, x1: 220, y1: 180 },
      { x0: 30, y0: 250, x1: 210, y1: 400 },
      { x0: 25, y0: 470, x1: 215, y1: 650 }
    ]);
  });

  it("treats a dark gray 51 background as gutter", () => {
    const image = blankImage(240, 360, [51, 51, 51]);
    drawPanel(image, { x0: 40, y0: 40, x1: 200, y1: 180 });

    const { boxes, stats } = detectPanels(image);

    expect(estimateBgMax(image)).toBe(63);
    expect(stats.vmax).toBe(63);
    expect(boxes).toEqual([{ x0: 40, y0: 40, x1: 200, y1: 180 }]);
  });

  it("clips panels touching the left and right image edges inward by the edge margin", () => {
    const image = blankImage(200, 180, [0, 0, 0]);
    drawPanel(image, { x0: 0, y0: 30, x1: 200, y1: 150 });

    const { boxes } = detectPanels(image);

    expect(boxes).toEqual([{ x0: EDGE_MARGIN, y0: 30, x1: 200 - EDGE_MARGIN, y1: 150 }]);
  });

  it("splits two staggered panels that overlap vertically", () => {
    const image = blankImage(300, 280, [0, 0, 0]);
    drawPanel(image, { x0: 20, y0: 30, x1: 135, y1: 220 });
    drawPanel(image, { x0: 165, y0: 80, x1: 280, y1: 250 });

    const { boxes } = detectPanels(image);

    expect(boxes).toEqual([
      { x0: 20, y0: 30, x1: 135, y1: 220 },
      { x0: 165, y0: 80, x1: 280, y1: 250 }
    ]);
  });

  it("excludes contentless white boxes while keeping panels with ink", () => {
    const image = blankImage(240, 420, [0, 0, 0]);
    fillRect(image, { x0: 30, y0: 30, x1: 210, y1: 170 }, [255, 255, 255]);
    drawPanel(image, { x0: 30, y0: 240, x1: 210, y1: 380 });

    const { boxes, stats } = detectPanels(image);

    expect(stats.blank).toBe(1);
    expect(boxes).toEqual([{ x0: 30, y0: 240, x1: 210, y1: 380 }]);
  });

  it("returns no panels for a solid image", () => {
    const image = blankImage(240, 360, [0, 0, 0]);

    const { boxes, stats } = detectPanels(image);

    expect(boxes).toEqual([]);
    expect(stats.blank + stats.noise).toBe(0);
  });

  it("falls back to a single fullpage cut when dark webtoon mode finds no panel", () => {
    const image = blankImage(240, 360, [0, 0, 0]);

    const cuts = detectCuts(image, "auto", "image", "dark-webtoon");

    expect(cuts).toEqual([
      expect.objectContaining({
        x0: 0,
        y0: 0,
        x1: 240,
        y1: 360,
        mode: "fullpage",
        flags: ["fullpage"]
      })
    ]);
  });

  it("orders mixed dark webtoon layout top-to-bottom and left-to-right within each row", () => {
    const image = blankImage(900, 960, [20, 20, 20]);
    drawPanel(image, { x0: 500, y0: 470, x1: 850, y1: 900 });
    drawPanel(image, { x0: 80, y0: 40, x1: 420, y1: 180 });
    drawPanel(image, { x0: 460, y0: 40, x1: 800, y1: 180 });
    drawPanel(image, { x0: 70, y0: 220, x1: 820, y1: 380 });
    drawPanel(image, { x0: 70, y0: 470, x1: 420, y1: 900 });

    const cuts = detectCuts(image, "auto", "image", "dark-webtoon");

    expect(cuts.map(({ index, x0, y0, x1, y1 }) => [index, x0, y0, x1, y1])).toEqual([
      [1, 80, 40, 420, 180],
      [2, 460, 40, 800, 180],
      [3, 70, 220, 820, 380],
      [4, 70, 470, 420, 900],
      [5, 500, 470, 850, 900]
    ]);
  });
});

function drawPanel(image: ImageData, region: PixelRegion) {
  fillRect(image, region, [255, 255, 255]);
  fillRect(image, {
    x0: region.x0 + Math.max(12, Math.floor((region.x1 - region.x0) * 0.35)),
    y0: region.y0 + Math.max(12, Math.floor((region.y1 - region.y0) * 0.35)),
    x1: region.x0 + Math.max(42, Math.floor((region.x1 - region.x0) * 0.35) + 30),
    y1: region.y0 + Math.max(42, Math.floor((region.y1 - region.y0) * 0.35) + 30)
  }, [240, 170, 120]);
  const ink: PixelRegion = {
    x0: region.x0 + Math.max(12, Math.floor((region.x1 - region.x0) * 0.2)),
    y0: region.y0 + Math.max(12, Math.floor((region.y1 - region.y0) * 0.2)),
    x1: region.x0 + Math.max(32, Math.floor((region.x1 - region.x0) * 0.2) + 20),
    y1: region.y0 + Math.max(32, Math.floor((region.y1 - region.y0) * 0.2) + 20)
  };
  fillRect(image, ink, [0, 0, 0]);
}

function fillRect(image: ImageData, region: PixelRegion, color: [number, number, number]) {
  const [r, g, b] = color;
  const x0 = Math.max(0, Math.floor(region.x0));
  const y0 = Math.max(0, Math.floor(region.y0));
  const x1 = Math.min(image.width, Math.ceil(region.x1));
  const y1 = Math.min(image.height, Math.ceil(region.y1));
  for (let y = y0; y < y1; y += 1) {
    for (let x = x0; x < x1; x += 1) {
      const offset = (y * image.width + x) * 4;
      image.data[offset] = r;
      image.data[offset + 1] = g;
      image.data[offset + 2] = b;
      image.data[offset + 3] = 255;
    }
  }
}
