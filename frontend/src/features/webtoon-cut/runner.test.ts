import { describe, expect, it } from "vitest";
import { memoryDirectory, validPng } from "./__fixtures__/memoryDirectory";
import { borderlessInfographic } from "./__fixtures__/synthetic";
import { runWebtoonCutJob } from "./runner";
import type { WebtoonCutManifest } from "./types";
import type { SourceInputCollection, SourceInputItem } from "./inputSources";

describe("webtoon cut runner", () => {
  it("writes no artifacts when the complete source inventory cannot be built", async () => {
    const output = memoryDirectory({});

    await expect(runWebtoonCutJob(jobWithUnreadablePdfCount(), { output }, neverAborted())).rejects.toMatchObject({ code: "inventory_error" });
    expect(output.files()).toEqual([]);
  });

  it("surfaces a fullpage fallback as completed_with_review", async () => {
    const result = await runWebtoonCutJob(singleBorderlessImageJob(), { output: memoryDirectory({}) }, neverAborted());

    expect(result.status).toBe("completed_with_review");
    expect(result.ledger[0].flags).toEqual(expect.arrayContaining(["fullpage", "review_required"]));
    expect(result.ledger[0].outputs[0].flags).toEqual(expect.arrayContaining(["fullpage", "review_required"]));
  });

  it("preserves nested source parents and source stems in output paths", async () => {
    const result = await runWebtoonCutJob(nestedImageJob(), { output: memoryDirectory({}) }, neverAborted());

    expect(result.ledger[0].outputs[0].path).toBe("scene-a/page-001/page-001-01.png");
  });

  it("reports stage-level progress while a source unit is processed", async () => {
    const progress: Array<{ stage: string; completed: number; total: number; generatedCuts: number; unitId?: string }> = [];

    await runWebtoonCutJob(twoImageJob(), {
      output: memoryDirectory({}),
      onProgress: (event) => progress.push(event)
    }, neverAborted());

    expect(progress.map((event) => event.stage)).toEqual([
      "inventory",
      "render",
      "detect",
      "write",
      "unit-complete",
      "render",
      "detect",
      "write",
      "unit-complete",
      "manifest"
    ]);
    expect(progress[progress.length - 1]).toMatchObject({ completed: 2, total: 2, generatedCuts: 2 });
  });

  it("resumes from an existing manifest and skips units whose PNG outputs are already valid", async () => {
    const existingManifest = completedOneOfTwoManifest();
    const output = memoryDirectory({
      "page-001-01.png": validPng(400, 400),
      "manifest.json": new TextEncoder().encode(JSON.stringify(existingManifest))
    });
    const progress: Array<{ stage: string; unitId?: string; completed: number }> = [];

    const result = await runWebtoonCutJob(twoImageJob(), {
      output,
      onProgress: (event) => progress.push(event)
    }, neverAborted());

    expect(progress).toEqual(expect.arrayContaining([
      expect.objectContaining({ stage: "resume-skip", unitId: "image:page-001.jpg", completed: 1 })
    ]));
    expect(result.ledger.map((unit) => unit.unitId)).toEqual(["image:page-001.jpg", "image:page-002.jpg"]);
    expect(output.files()).toEqual(expect.arrayContaining(["page-001-01.png", "page-002-01.png", "manifest.json"]));
  });
});

function jobWithUnreadablePdfCount() {
  return {
    jobId: "job-broken",
    inputKind: "pdf" as const,
    inputName: "broken.pdf",
    inputs: {
      inputs: [
        {
          kind: "pdf",
          relativePath: "broken.pdf",
          fileName: "broken.pdf",
          extension: "pdf",
          testPdfPageCountError: new Error("broken pdf")
        } satisfies SourceInputItem
      ]
    } satisfies SourceInputCollection
  };
}

function singleBorderlessImageJob() {
  return {
    jobId: "job-image",
    inputKind: "image" as const,
    inputName: "page.jpg",
    inputs: {
      inputs: [
        {
          kind: "image",
          relativePath: "page.jpg",
          fileName: "page.jpg",
          extension: "jpg",
          testImage: borderlessInfographic(400, 400)
        } satisfies SourceInputItem
      ]
    } satisfies SourceInputCollection
  };
}

function nestedImageJob() {
  return {
    jobId: "job-nested",
    inputKind: "directory" as const,
    inputName: "episode-001",
    inputs: {
      inputs: [
        {
          kind: "image",
          relativePath: "scene-a/page-001.jpg",
          fileName: "page-001.jpg",
          extension: "jpg",
          testImage: borderlessInfographic(400, 400)
        } satisfies SourceInputItem
      ]
    } satisfies SourceInputCollection
  };
}

function twoImageJob() {
  return {
    jobId: "job-two-images",
    inputKind: "directory" as const,
    inputName: "episode-001",
    inputs: {
      inputs: [
        {
          kind: "image",
          relativePath: "page-001.jpg",
          fileName: "page-001.jpg",
          extension: "jpg",
          testImage: borderlessInfographic(400, 400)
        } satisfies SourceInputItem,
        {
          kind: "image",
          relativePath: "page-002.jpg",
          fileName: "page-002.jpg",
          extension: "jpg",
          testImage: borderlessInfographic(400, 400)
        } satisfies SourceInputItem
      ]
    } satisfies SourceInputCollection
  };
}

function completedOneOfTwoManifest(): WebtoonCutManifest {
  return {
    schemaVersion: 1,
    engineVersion: "webtoon-cut-1",
    jobId: "job-two-images",
    status: "running",
    inputKind: "directory",
    inputName: "episode-001",
    outputRoot: "episode-001_cuts",
    expectedUnitCount: 2,
    createdAt: "",
    updatedAt: "",
    completedAt: null,
    options: {} as WebtoonCutManifest["options"],
    inputs: [],
    inventory: [],
    ledger: [
      {
        unitId: "image:page-001.jpg",
        sourcePath: "page-001.jpg",
        sourceKind: "image",
        page: null,
        status: "completed",
        attempts: 1,
        flags: [],
        outputs: [{ path: "page-001-01.png", width: 400, height: 400 }]
      }
    ],
    generatedFiles: ["page-001-01.png"],
    totals: {
      expectedUnitCount: 2,
      completedUnitCount: 1,
      errorUnitCount: 0,
      reviewRequiredUnitCount: 0,
      generatedCutCount: 1,
      flags: {}
    }
  };
}

function neverAborted() {
  return new AbortController().signal;
}
