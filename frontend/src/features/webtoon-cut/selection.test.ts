import { describe, expect, it } from "vitest";
import { toggleSelection } from "./selection";

describe("toggleSelection", () => {
  it("adds a current page without discarding selections from another page", () => {
    expect([...toggleSelection(new Set(["other-page"]), ["page-1", "page-2"])]).toEqual([
      "other-page", "page-1", "page-2"
    ]);
  });

  it("removes only the target page when every target item is already selected", () => {
    expect([...toggleSelection(new Set(["other-page", "page-1", "page-2"]), ["page-1", "page-2"])]).toEqual([
      "other-page"
    ]);
  });
});
