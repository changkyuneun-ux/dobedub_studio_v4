import { describe, expect, it } from "vitest";
import { memoryDirectory, validPng } from "./__fixtures__/memoryDirectory";
import { blankImage, borderlessInfographic } from "./__fixtures__/synthetic";
import { ENGINE_VERSION } from "./constants";
import { outputFileName, runWebtoonCutJob } from "./runner";
import type { PixelRegion, WebtoonCutManifest } from "./types";
import type { SourceInputCollection, SourceInputItem } from "./inputSources";

describe("webtoon cut runner", () => {
  it("writes no artifacts when the complete source inventory cannot be built", async () => {
    const output = memoryDirectory({});

    await expect(runWebtoonCutJob(jobWithUnreadablePdfCount(), { output }, neverAborted())).rejects.toMatchObject({ code: "inventory_error" });
    expect(output.files()).toEqual([]);
  });

  it("stores a fullpage fallback as a completed output without review", async () => {
    const result = await runWebtoonCutJob(singleBorderlessImageJob(), { output: memoryDirectory({}) }, neverAborted());

    expect(result.status).toBe("completed");
    expect(result.ledger[0].flags).toEqual(["fullpage"]);
    expect(result.ledger[0].outputs[0].flags).toEqual(["fullpage"]);
    expect(result.totals.reviewRequiredUnitCount).toBe(0);
  });

  it("uses the dark webtoon split mode when requested and records it in the manifest", async () => {
    const result = await runWebtoonCutJob(singleDarkWebtoonImageJob(), { output: memoryDirectory({}) }, neverAborted());

    expect(result.options.splitMode).toBe("dark-webtoon");
    expect(result.ledger[0].outputs).toHaveLength(2);
    expect(result.ledger[0].outputs.map((output) => output.mode)).toEqual(["dark_bg", "dark_bg"]);
    expect(result.ledger[0].outputs.map((output) => [output.x0, output.y0, output.x1, output.y1])).toEqual([
      [20, 30, 220, 180],
      [30, 250, 210, 400]
    ]);
  });

  it("places a root image source under its filename directory", async () => {
    const result = await runWebtoonCutJob(singleBorderlessImageJob(), { output: memoryDirectory({}) }, neverAborted());

    expect(result.ledger[0].outputs[0].path).toBe("page/page-01.png");
  });

  it("preserves nested source parents and source stems in output paths", async () => {
    const result = await runWebtoonCutJob(nestedImageJob(), { output: memoryDirectory({}) }, neverAborted());

    expect(result.ledger[0].outputs[0].path).toBe("scene-a/page-001/page-001-01.png");
  });

  it("places pdf page cut sequences under the pdf filename directory", () => {
    expect(outputFileName("book.pdf", 1, 2)).toBe("book/001-02.png");
    expect(outputFileName("scene-b/page-002.pdf", 12, 3)).toBe("scene-b/page-002/012-03.png");
  });

  it("normalizes decomposed Korean source names before writing output paths", () => {
    const decomposed = "과학사 100 원본".normalize("NFD");

    expect(outputFileName(`${decomposed}.jpg`, null, 1)).toBe("과학사 100 원본/과학사 100 원본-01.png");
    expect(outputFileName(`묶음/${decomposed}.pdf`, 3, 2)).toBe("묶음/과학사 100 원본/003-02.png");
  });

  it("keeps numbered image source stems as the local cut sequence prefix", () => {
    expect(outputFileName("episode/001.jpg", null, 1)).toBe("episode/001/001-01.png");
    expect(outputFileName("episode/001.jpg", null, 4)).toBe("episode/001/001-04.png");
    expect(outputFileName("episode/002.jpg", null, 1)).toBe("episode/002/002-01.png");
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
      "page-001": {
        "page-001-01.png": validPng(400, 400)
      },
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
    expect(output.files()).toEqual(expect.arrayContaining(["page-001", "page-002", "manifest.json"]));
  });

  it("returns a paused manifest with completed outputs when aborted after a unit completes", async () => {
    const controller = new AbortController();
    const output = memoryDirectory({});

    const result = await runWebtoonCutJob(twoImageJob(), {
      output,
      onProgress: (event) => {
        if (event.stage === "unit-complete" && event.completed === 1) {
          controller.abort(new DOMException("중단 요청", "AbortError"));
        }
      }
    }, controller.signal);

    expect(result.status).toBe("paused");
    expect(result.ledger.map((unit) => unit.unitId)).toEqual(["image:page-001.jpg"]);
    expect(result.totals).toMatchObject({
      expectedUnitCount: 2,
      completedUnitCount: 1,
      generatedCutCount: 1
    });
    expect(output.files()).toEqual(expect.arrayContaining(["page-001", "manifest.json", "summary.csv"]));
    await expect(readJsonFile<WebtoonCutManifest>(output, "manifest.json")).resolves.toMatchObject({
      status: "paused",
      totals: {
        expectedUnitCount: 2,
        completedUnitCount: 1,
        generatedCutCount: 1
      }
    });
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

function singleDarkWebtoonImageJob() {
  return {
    jobId: "job-dark-webtoon",
    inputKind: "image" as const,
    inputName: "dark-strip.png",
    splitMode: "dark-webtoon" as const,
    inputs: {
      inputs: [
        {
          kind: "image",
          relativePath: "dark-strip.png",
          fileName: "dark-strip.png",
          extension: "png",
          testImage: darkWebtoonImage()
        } satisfies SourceInputItem
      ]
    } satisfies SourceInputCollection
  };
}

function darkWebtoonImage() {
  const image = blankImage(240, 460, [0, 0, 0]);
  drawPanel(image, { x0: 20, y0: 30, x1: 220, y1: 180 });
  drawPanel(image, { x0: 30, y0: 250, x1: 210, y1: 400 });
  return image;
}

function drawPanel(image: ImageData, region: PixelRegion) {
  fillRect(image, region, [255, 255, 255]);
  fillRect(image, { x0: region.x0 + 70, y0: region.y0 + 60, x1: region.x0 + 100, y1: region.y0 + 90 }, [240, 170, 120]);
  fillRect(image, { x0: region.x0 + 40, y0: region.y0 + 40, x1: region.x0 + 60, y1: region.y0 + 60 }, [0, 0, 0]);
}

function fillRect(image: ImageData, region: PixelRegion, color: [number, number, number]) {
  const [r, g, b] = color;
  for (let y = Math.max(0, region.y0); y < Math.min(image.height, region.y1); y += 1) {
    for (let x = Math.max(0, region.x0); x < Math.min(image.width, region.x1); x += 1) {
      const offset = (y * image.width + x) * 4;
      image.data[offset] = r;
      image.data[offset + 1] = g;
      image.data[offset + 2] = b;
      image.data[offset + 3] = 255;
    }
  }
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
    engineVersion: ENGINE_VERSION,
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
        outputs: [{ path: "page-001/page-001-01.png", width: 400, height: 400 }]
      }
    ],
    generatedFiles: ["page-001/page-001-01.png"],
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

async function readJsonFile<T>(directory: { getFileHandle(name: string): Promise<{ getFile(): Promise<File> }> }, name: string): Promise<T> {
  const handle = await directory.getFileHandle(name);
  return JSON.parse(await (await handle.getFile()).text()) as T;
}
