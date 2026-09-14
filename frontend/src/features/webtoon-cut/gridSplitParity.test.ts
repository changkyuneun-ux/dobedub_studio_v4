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

    // 이 합성 이미지는 두 가지가 겹친 극단적인 케이스다: (1) fourPanelPage의 두 행이 y좌표까지
    // 완전히 일치해 그 사이 거터가 별도 leaf로 분리되고, (2) 장식 다이아몬드 blob이 재귀 분할에서
    // 자기 자신을 관통하는 세로 분할선을 만들어 2조각으로 쪼개진다. 애초에 "장식은 컷으로
    // 오인식되지 않는다"는 것을 이 한 픽셀 구성으로 완벽히 검증하는 fixture가 아니라는 뜻이다
    // (그 검증은 아래 "does not mistake a borderless decorative blob" 테스트와, 실사 페이지
    // page_016 검증에서 이미 이뤄짐). vendored grid_split.py 원본을 이 픽셀과 동일한 구조의
    // 합성 이미지에 직접 실행해 확인한 결과 Python도 동일하게 7개(진짜 4컷 + 거터 밴드 1개 +
    // 장식 조각 2개)를 반환하므로, 이 테스트는 "TS 포팅이 grid_split.py의 결과와 정확히
    // 일치하는지"를 검증하는 parity 테스트로 유지한다.
    expect(cuts).toHaveLength(7);
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
