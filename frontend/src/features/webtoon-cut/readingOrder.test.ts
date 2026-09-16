import { describe, expect, it } from "vitest";
import { orderReadingSequence } from "./readingOrder";
import type { PixelRegion } from "./types";

describe("webtoon cut reading order", () => {
  it("sorts vertical stack top-to-bottom", () => {
    const boxes: PixelRegion[] = [
      { x0: 30, y0: 420, x1: 230, y1: 520 },
      { x0: 20, y0: 40, x1: 220, y1: 140 },
      { x0: 25, y0: 230, x1: 225, y1: 330 }
    ];

    expect(orderReadingSequence(boxes)).toEqual([
      { x0: 20, y0: 40, x1: 220, y1: 140 },
      { x0: 25, y0: 230, x1: 225, y1: 330 },
      { x0: 30, y0: 420, x1: 230, y1: 520 }
    ]);
  });

  it("sorts same visual row left-to-right before lower rows", () => {
    const boxes: PixelRegion[] = [
      { x0: 500, y0: 470, x1: 850, y1: 900 },
      { x0: 80, y0: 40, x1: 420, y1: 180 },
      { x0: 460, y0: 40, x1: 800, y1: 180 },
      { x0: 70, y0: 220, x1: 820, y1: 380 },
      { x0: 70, y0: 470, x1: 420, y1: 900 }
    ];

    expect(orderReadingSequence(boxes)).toEqual([
      { x0: 80, y0: 40, x1: 420, y1: 180 },
      { x0: 460, y0: 40, x1: 800, y1: 180 },
      { x0: 70, y0: 220, x1: 820, y1: 380 },
      { x0: 70, y0: 470, x1: 420, y1: 900 },
      { x0: 500, y0: 470, x1: 850, y1: 900 }
    ]);
  });

  it("groups slightly staggered same-row panels by overlap and center tolerance", () => {
    const boxes: PixelRegion[] = [
      { x0: 260, y0: 70, x1: 470, y1: 240 },
      { x0: 20, y0: 40, x1: 230, y1: 210 },
      { x0: 25, y0: 300, x1: 460, y1: 440 }
    ];

    expect(orderReadingSequence(boxes)).toEqual([
      { x0: 20, y0: 40, x1: 230, y1: 210 },
      { x0: 260, y0: 70, x1: 470, y1: 240 },
      { x0: 25, y0: 300, x1: 460, y1: 440 }
    ]);
  });
});
