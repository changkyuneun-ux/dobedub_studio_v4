import { describe, expect, it } from "vitest";
import { pdfRenderScale } from "./pdf";
import type { SourceInputCollection, SourceInputItem } from "./inputSources";
import { buildSourceInventory, classifySourceName } from "./inputSources";

function raster(): SourceInputItem {
  return {
    kind: "image",
    relativePath: "",
    fileName: "",
    extension: "jpg"
  };
}

function pdfWithPages(pageCount: number): SourceInputItem {
  return {
    kind: "pdf",
    relativePath: "",
    fileName: "",
    extension: "pdf",
    testPdfPageCount: pageCount
  };
}

function unreadablePdfPageCount(): SourceInputItem {
  return {
    kind: "pdf",
    relativePath: "",
    fileName: "",
    extension: "pdf",
    testPdfPageCountError: new Error("broken pdf")
  };
}

function fakeInputTree(tree: Record<string, SourceInputItem>): SourceInputCollection {
  return {
    inputs: Object.entries(tree).map(([relativePath, item]) => ({
      ...item,
      relativePath,
      fileName: relativePath.split("/").pop() || relativePath,
      extension: relativePath.split(".").pop()?.toLowerCase() || item.extension
    }))
  };
}

function neverAborted() {
  return new AbortController().signal;
}

describe("webtoon cut input sources", () => {
  it("uses the approved 300dpi PDF scale", () => {
    expect(pdfRenderScale()).toBeCloseTo(300 / 72, 12);
  });

  it("dispatches extensions case-insensitively", () => {
    expect(classifySourceName("BOOK.PDF")).toBe("pdf");
    expect(classifySourceName("EPISODE.ZIP")).toBe("zip");
    expect(classifySourceName("CUT.JPEG")).toBe("image");
  });

  it("inventories every raster and every PDF page exactly once", async () => {
    const input = fakeInputTree({ "cover.jpg": raster(), "book.pdf": pdfWithPages(3) });

    const inventory = await buildSourceInventory(input, neverAborted());

    expect(inventory.map((unit) => unit.unitId)).toEqual([
      "pdf:book.pdf#page=001",
      "pdf:book.pdf#page=002",
      "pdf:book.pdf#page=003",
      "image:cover.jpg"
    ]);
  });

  it("rejects a partial inventory before any output write", async () => {
    const input = fakeInputTree({ "good.jpg": raster(), "broken.pdf": unreadablePdfPageCount() });

    await expect(buildSourceInventory(input, neverAborted())).rejects.toMatchObject({ code: "inventory_error" });
  });
});
