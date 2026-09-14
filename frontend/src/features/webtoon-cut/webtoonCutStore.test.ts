import { describe, expect, it } from "vitest";
import { bytes, MemoryDirectory } from "./__fixtures__/memoryDirectory";
import { canRunWebtoonCutInWorker, findSelectedInputIndexForUnitId, hasResumableProgress, outputsAfterReviewReplacement, resolveReviewTargetOutput, reviewTargetOutputs, webtoonCutJobStore, type WebtoonCutOutput, type WebtoonCutUnit } from "./webtoonCutStore";

describe("webtoon cut UI store", () => {
  it("keeps file jobs disabled until a non-system work folder is connected", async () => {
    webtoonCutJobStore.initialize("default-workspace-test");
    await webtoonCutJobStore.selectFiles([new File([bytes(4)], "sample.zip", { type: "application/zip" })]);

    expect(webtoonCutJobStore.getSnapshot()).toMatchObject({
      inputName: "sample",
      outputReady: false,
      defaultWorkspaceReady: false
    });

    await webtoonCutJobStore.connectDefaultWorkspace(new MemoryDirectory("System", {}) as unknown as FileSystemDirectoryHandle);

    expect(webtoonCutJobStore.getSnapshot()).toMatchObject({
      outputReady: false,
      defaultWorkspaceReady: false
    });
    expect(webtoonCutJobStore.getSnapshot().notice).toContain("시스템 폴더");

    const workspace = new MemoryDirectory("my-webtoon-work", {});
    await webtoonCutJobStore.connectDefaultWorkspace(workspace as unknown as FileSystemDirectoryHandle);
    expect(webtoonCutJobStore.getSnapshot().notice).toBe("");

    await webtoonCutJobStore.selectFiles([new File([bytes(4)], "sample.zip", { type: "application/zip" })]);

    expect(webtoonCutJobStore.getSnapshot()).toMatchObject({
      inputName: "sample",
      outputLocation: "my-webtoon-work/sample_cuts",
      outputReady: true,
      defaultWorkspaceReady: true,
      notice: ""
    });
    expect(workspace.files()).toContain("sample_cuts");
  });

  it("treats a manifest with no completed units as nothing to resume", async () => {
    // 2026-09-14: 새로고침 직후엔 진짜 "실행 중" 작업이 있을 수 없다(워커/네트워크
    // 상태가 전부 사라짐) — output 폴더의 manifest에 완료된 단위가 하나도 없다면
    // 이전에 한 번도 실행되지 않은 입력 선택일 뿐이므로 복원 대상이 아니다.
    const outputDir = new MemoryDirectory("sample_cuts", {
      "manifest.json": new TextEncoder().encode(JSON.stringify({ ledger: [{ unitId: "a", status: "pending" }] }))
    });

    expect(await hasResumableProgress(outputDir as unknown as FileSystemDirectoryHandle)).toBe(false);
  });

  it("treats a manifest with at least one completed unit as resumable", async () => {
    // 탭이 중간에 닫히는 등 정상 중단 경로를 타지 못해 일부 단위가 이미 완료된 채
    // manifest.json이 남아있는 경우에만 "이어서 처리" 복원이 의미가 있다.
    const outputDir = new MemoryDirectory("sample_cuts", {
      "manifest.json": new TextEncoder().encode(JSON.stringify({
        ledger: [{ unitId: "a", status: "completed" }, { unitId: "b", status: "pending" }]
      }))
    });

    expect(await hasResumableProgress(outputDir as unknown as FileSystemDirectoryHandle)).toBe(true);
  });

  it("treats a missing manifest as nothing to resume", async () => {
    const outputDir = new MemoryDirectory("sample_cuts", {});

    expect(await hasResumableProgress(outputDir as unknown as FileSystemDirectoryHandle)).toBe(false);
  });

  it("maps review ledger unit ids back to the selected image input for reprocessing", () => {
    const selectedInputs = [
      { sourcePath: "수영복을 입은 형수님_019화_002.jpg" },
      { sourcePath: "수영복을 입은 형수님_019화_003.jpg" }
    ];

    expect(findSelectedInputIndexForUnitId(selectedInputs, "image:수영복을 입은 형수님_019화_002.jpg")).toBe(0);
  });

  it("returns only flagged outputs as review targets", () => {
    const unit = {
      outputs: [
        { path: "page-01.png", flags: [] },
        { path: "page-02.png", flags: ["review_continuous", "review_required"] },
        { path: "page-03.png", flags: [] },
        { path: "page-04.png", flags: ["thin", "review_required"] }
      ]
    } as WebtoonCutUnit;

    expect(reviewTargetOutputs(unit).map((output) => output.path)).toEqual(["page-02.png", "page-04.png"]);
  });

  it("resolves the explicit selected review output for reprocessing", () => {
    const unit = {
      outputs: [
        { path: "page-02.png", flags: ["review_continuous", "review_required"] },
        { path: "page-04.png", flags: ["thin", "review_required"] }
      ]
    } as WebtoonCutUnit;

    expect(resolveReviewTargetOutput(unit, "page-04.png")?.path).toBe("page-04.png");
  });

  it("replaces a selected review output and marks the original long output for deletion", () => {
    const existing: WebtoonCutOutput[] = [
      { path: "page-01.png", flags: [] },
      { path: "page-02.png", flags: ["review_continuous", "review_required"] },
      { path: "page-03.png", flags: [] }
    ];
    const replacement: WebtoonCutOutput[] = [
      { path: "page-02-01.png", flags: [] },
      { path: "page-02-02.png", flags: [] }
    ];

    expect(outputsAfterReviewReplacement(existing, "page-02.png", replacement)).toEqual({
      outputs: [
        { path: "page-01.png", flags: [] },
        { path: "page-02-01.png", flags: [] },
        { path: "page-02-02.png", flags: [] },
        { path: "page-03.png", flags: [] }
      ],
      deletePaths: ["page-02.png"]
    });
  });

  it("keeps pdf and archive inputs on the main browser path because PDF rendering depends on DOM APIs", () => {
    expect(canRunWebtoonCutInWorker({
      inputs: { inputs: [{ kind: "image", relativePath: "page.png", fileName: "page.png", extension: "png" }] }
    })).toBe(true);

    expect(canRunWebtoonCutInWorker({
      inputs: { inputs: [{ kind: "pdf", relativePath: "book.pdf", fileName: "book.pdf", extension: "pdf" }] }
    })).toBe(false);

    expect(canRunWebtoonCutInWorker({
      inputs: { inputs: [{ kind: "zip", relativePath: "episode.zip", fileName: "episode.zip", extension: "zip" }] }
    })).toBe(false);
  });
});
