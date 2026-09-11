import { describe, expect, it } from "vitest";
import { memoryDirectory, validPng } from "./__fixtures__/memoryDirectory";
import { reconcileJob, resumeDecision } from "./reconcile";
import type { UnitLedgerEntry, WebtoonCutManifest } from "./types";

describe("webtoon cut reconciliation", () => {
  it("refuses completion when any inventoried PDF page lacks a verified PNG", async () => {
    const inventory = [1, 2, 3].map((page) => ({
      unitId: `pdf:book.pdf#page=${String(page).padStart(3, "0")}`,
      sourcePath: "book.pdf",
      sourceKind: "pdf-page" as const,
      page
    }));
    const output = memoryDirectory({
      "001-01.png": validPng(100, 100),
      "003-01.png": validPng(100, 100)
    });

    const report = await reconcileJob(inventory, completedPdfManifest(3), output);

    expect(report.missingUnitIds).toEqual(["pdf:book.pdf#page=002"]);
    expect(report.canComplete).toBe(false);
  });

  it("reprocesses a completed unit whose recorded PNG was deleted", async () => {
    const decision = await resumeDecision(completedImageUnit("image:page.jpg", "page-01.png"), memoryDirectory({}));

    expect(decision).toEqual({ action: "reprocess", reason: "missing_output" });
  });
});

function completedPdfManifest(pageCount: number): WebtoonCutManifest {
  const ledger = Array.from({ length: pageCount }, (_, index) => {
    const page = index + 1;
    return {
      unitId: `pdf:book.pdf#page=${String(page).padStart(3, "0")}`,
      sourcePath: "book.pdf",
      sourceKind: "pdf-page" as const,
      page,
      status: "completed" as const,
      attempts: 1,
      flags: [],
      outputs: [{ path: `${String(page).padStart(3, "0")}-01.png`, width: 100, height: 100 }]
    };
  });
  return {
    schemaVersion: 1,
    engineVersion: "webtoon-cut-3",
    jobId: "job",
    status: "completed",
    inputKind: "pdf",
    inputName: "book.pdf",
    outputRoot: "book_cuts",
    expectedUnitCount: pageCount,
    createdAt: "",
    updatedAt: "",
    completedAt: "",
    options: {} as WebtoonCutManifest["options"],
    inputs: [],
    inventory: [],
    ledger,
    generatedFiles: ledger.flatMap((unit) => unit.outputs.map((output) => output.path)),
    totals: {
      expectedUnitCount: pageCount,
      completedUnitCount: pageCount,
      errorUnitCount: 0,
      reviewRequiredUnitCount: 0,
      generatedCutCount: pageCount,
      flags: {}
    }
  };
}

function completedImageUnit(unitId: string, path: string): UnitLedgerEntry {
  return {
    unitId,
    sourcePath: "page.jpg",
    sourceKind: "image",
    page: null,
    status: "completed",
    attempts: 1,
    flags: [],
    outputs: [{ path, width: 100, height: 100 }]
  };
}
