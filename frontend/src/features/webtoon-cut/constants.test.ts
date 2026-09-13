import { describe, expect, it } from "vitest";
import { ARCHIVE_LIMITS, PAGE_POLICY, STRIP_POLICY } from "./constants";

describe("webtoon cut constants", () => {
  it("locks the approved production thresholds", () => {
    expect(PAGE_POLICY).toMatchObject({
      outerMarginRatio: 0.03,
      minAreaRatio: 0.02,
      maxDepth: 8
    });
    expect(STRIP_POLICY).toMatchObject({
      foregroundFloor: 245,
      chromaFloor: 8,
      rowRatio: 0.003,
      minGapPx: 100,
      gapWidthRatio: 0.06,
      paddingY: 15
    });
    expect(ARCHIVE_LIMITS).toMatchObject({
      maxEntries: 10_000,
      maxInputs: 5_000,
      maxExpandedBytes: 4 * 1024 ** 3,
      maxEntryBytes: 500 * 1024 ** 2,
      maxCompressionRatio: 200
    });
  });
});
