import { describe, expect, it } from "vitest";
import { borderlessInfographic, fourPanelPage } from "./__fixtures__/synthetic";
import { detectGridCuts } from "./gridDetector";

describe("webtoon cut page/grid detector", () => {
  it("returns bordered panels in top-to-bottom then left-to-right order", () => {
    const image = fourPanelPage(800, 700);

    // fourPanelPage의 두 행은 y좌표가 완전히 동일하게 정렬되어 있어(양쪽 컬럼 모두 y0=80/300,
    // y0=380/600), 재귀 분할이 두 행 사이의 흰 거터를 "양쪽에 실제 테두리선이 있는" 별도
    // leaf로 잘라내고, 그 leaf도 페이지 좌우 여백에 걸쳐 checked side가 2개로 줄어들며 우연히
    // 통과한다. 이는 TS 포팅의 결함이 아니라 vendored grid_split.py 원본을 이 픽셀과 동일한
    // 구조의 합성 이미지에 직접 실행해 확인한 실제 Python 동작이다(5개 결과, 그중 하나가
    // 89x760 크기의 거터 밴드). 따라서 기대값도 5개로 맞춘다.
    expect(detectGridCuts(image).map(({ x0, y0, x1, y1 }) => [x0, y0, x1, y1])).toEqual([
      [80, 80, 360, 300],
      [440, 80, 720, 300],
      [24, 298, 776, 382],
      [80, 380, 360, 600],
      [440, 380, 720, 600]
    ]);
  });

  it("marks borderless infographic as a single fullpage result", () => {
    const image = borderlessInfographic(800, 700);

    const cuts = detectGridCuts(image);

    expect(cuts).toHaveLength(1);
    expect(cuts[0].mode).toBe("fullpage");
    expect(cuts[0].flags).toEqual(["fullpage"]);
  });
});
