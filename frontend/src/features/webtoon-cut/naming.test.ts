import { describe, expect, it } from "vitest";
import type { DiscoveredInput } from "./types";
import { disambiguateSiblingStems, planArchiveEntryPath, planOutputPath, safeOutputName } from "./naming";

function image(relativePath: string): DiscoveredInput {
  return {
    kind: "image",
    relativePath,
    fileName: relativePath.split("/").pop() || relativePath,
    extension: relativePath.split(".").pop()?.toLowerCase() || ""
  };
}

describe("webtoon cut output naming", () => {
  it("places a normal image beside its source under a stem_cuts directory", () => {
    expect(planOutputPath(image("진실의 방_001_006.jpg"), new Set())).toEqual(["진실의 방_001_006_cuts"]);
  });

  it("preserves ZIP parents and adds one source-stem directory", () => {
    expect(planArchiveEntryPath("episode-pack.zip", "scene-a/page-001.jpg", new Set())).toEqual([
      "episode-pack_cuts",
      "scene-a",
      "page-001"
    ]);
  });

  it("disambiguates equal stems with their extensions", () => {
    expect(disambiguateSiblingStems(["page.jpg", "page.png"])).toEqual(["page__jpg", "page__png"]);
  });

  it("normalizes unsafe output name components without changing readable names", () => {
    expect(safeOutputName("  컷:01/.png. ")).toBe("  컷_01_.png");
  });
});
