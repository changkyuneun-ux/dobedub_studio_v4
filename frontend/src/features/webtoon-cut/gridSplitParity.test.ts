import { describe, expect, it } from "vitest";
import { blankImage, decorativeBlob, fourPanelPageWithDecoration } from "./__fixtures__/synthetic";
import { detectGridCuts } from "./gridDetector";
import type { PixelRegion } from "./types";

describe("grid_split.py parity — fullpage fallback", () => {
  it("returns fullpage fallback when no bordered panels exist", () => {
    const image = blankImage(1000, 1400, [255, 255, 255]);

    const cuts = detectGridCuts(image);

    expect(cuts).toHaveLength(1);
    expect(cuts[0].mode).toBe("fullpage");
    expect(cuts[0].flags).toContain("fullpage");
    expect(cuts[0].flags).not.toContain("review_required");
  });

  it("fullpage fallback removes the 3 percent print margin", () => {
    const image = blankImage(1000, 2000, [255, 255, 255]);

    const [cut] = detectGridCuts(image);

    expect(cut.x0).toBe(30);
    expect(cut.y0).toBe(60);
    expect(cut.x1).toBe(970);
    expect(cut.y1).toBe(1940);
  });
});

describe("grid_split.py parity — decorative artwork rejection (_looks_like_panel)", () => {
  it("does not mistake a borderless decorative blob for a panel", () => {
    const image = decorativeBlob(800, 900, 400, 750, 90);

    const cuts = detectGridCuts(image);

    expect(cuts).toHaveLength(1);
    expect(cuts[0].mode).toBe("fullpage");
  });

  it("keeps the 4 real bordered panels alongside a decorative blob (matches grid_split.py exactly)", () => {
    const image = fourPanelPageWithDecoration(800, 900);

    const cuts = detectGridCuts(image);

    // 이 합성 이미지는 장식 다이아몬드 blob이 재귀 분할에서 별도 leaf로 남는 극단적인
    // 케이스다. 내부 잉크가 없는 전체 폭 얇은 거터 밴드는 제거되고, edge 후보 복원 후에는
    // 진짜 4컷 + 장식 조각 1개, 총 5개가 parity 기준이다.
    expect(cuts).toHaveLength(5);
    expect(cuts.every((cut) => cut.mode === "grid")).toBe(true);
    const real = cuts.filter(({ x0, y0, x1, y1 }) =>
      [
        [80, 80, 360, 300],
        [440, 80, 720, 300],
        [80, 380, 360, 600],
        [440, 380, 720, 600]
      ].some(([rx0, ry0, rx1, ry1]) => rx0 === x0 && ry0 === y0 && rx1 === x1 && ry1 === y1)
    );
    expect(real).toHaveLength(4);
  });
});

describe("grid_split.py parity — thick merged border components", () => {
  it("uses the component edge instead of the center when artwork touches a panel border", () => {
    const image = blankImage(800, 500);
    drawBorder(image, { x0: 80, y0: 80, x1: 406, y1: 300 }, 4);
    drawBorder(image, { x0: 430, y0: 80, x1: 720, y1: 300 }, 4);
    fillRect(image, { x0: 376, y0: 80, x1: 406, y1: 300 }, [20, 20, 20]);
    fillRect(image, { x0: 500, y0: 150, x1: 560, y1: 210 }, [20, 20, 20]);

    const cuts = detectGridCuts(image);

    const leftPanel = cuts.find((cut) => cut.x0 <= 90 && cut.y0 <= 90 && cut.y1 >= 290);
    expect(leftPanel).toBeTruthy();
    expect(leftPanel!.x1).toBeGreaterThanOrEqual(398);
    expect(leftPanel!.x1).toBeLessThanOrEqual(414);
    expect(cuts.some((cut) => cut.x0 <= 90 && cut.x1 > 360 && cut.x1 < 395)).toBe(false);
  });
});

function drawBorder(image: ImageData, region: PixelRegion, thickness: number) {
  fillRect(image, { x0: region.x0, y0: region.y0, x1: region.x1, y1: region.y0 + thickness }, [20, 20, 20]);
  fillRect(image, { x0: region.x0, y0: region.y1 - thickness, x1: region.x1, y1: region.y1 }, [20, 20, 20]);
  fillRect(image, { x0: region.x0, y0: region.y0, x1: region.x0 + thickness, y1: region.y1 }, [20, 20, 20]);
  fillRect(image, { x0: region.x1 - thickness, y0: region.y0, x1: region.x1, y1: region.y1 }, [20, 20, 20]);
}

function fillRect(image: ImageData, region: PixelRegion, color: [number, number, number]) {
  const [r, g, b] = color;
  for (let y = region.y0; y < region.y1; y += 1) {
    for (let x = region.x0; x < region.x1; x += 1) {
      const offset = (y * image.width + x) * 4;
      image.data[offset] = r;
      image.data[offset + 1] = g;
      image.data[offset + 2] = b;
      image.data[offset + 3] = 255;
    }
  }
}
