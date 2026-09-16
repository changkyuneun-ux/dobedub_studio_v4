import { describe, expect, it } from "vitest";
import { blankImage, decorativeBlob, fourPanelPageWithDecoration } from "./__fixtures__/synthetic";
import { detectGridCuts } from "./gridDetector";

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

    // 이 합성 이미지는 장식 다이아몬드 blob이 재귀 분할에서 자기 자신을 관통하는 세로
    // 분할선을 만들어 2조각으로 쪼개지는 극단적인 케이스다. 과거에는 두 행 사이 흰 거터도
    // 별도 leaf로 통과해 7개가 나왔지만, 현재는 내부 잉크가 없는 전체 폭 얇은 거터 밴드를
    // 컷 후보에서 제거하므로 진짜 4컷 + 장식 조각 2개, 총 6개가 parity 기준이다.
    expect(cuts).toHaveLength(6);
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
