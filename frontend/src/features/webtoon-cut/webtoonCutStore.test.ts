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

  it("keeps the selected split mode in the job snapshot", () => {
    webtoonCutJobStore.initialize("split-mode-test");

    expect(webtoonCutJobStore.getSnapshot().splitMode).toBe("print");

    webtoonCutJobStore.setSplitMode("dark-webtoon");

    expect(webtoonCutJobStore.getSnapshot().splitMode).toBe("dark-webtoon");
  });

  it("treats a manifest paused before any unit finished as still resumable (job was interrupted, not merely unrun)", async () => {
    // status가 "paused"라는 것 자체가 실행 도중 취소되었다는 의미이므로, 완료된 단위가
    // 0개라도 "진행 중이던 작업"은 맞다 — 한 번도 실행하지 않은 경우(=manifest.json 자체가
    // 없는 경우)와는 다르다. 그 구분은 아래 "missing manifest" 테스트가 커버한다.
    const outputDir = new MemoryDirectory("sample_cuts", {
      "manifest.json": new TextEncoder().encode(JSON.stringify({ status: "paused", ledger: [{ unitId: "a", status: "pending" }] }))
    });

    expect(await hasResumableProgress(outputDir as unknown as FileSystemDirectoryHandle)).toBe(true);
  });

  it("treats a manifest paused mid-run (some completed units, job not finished) as resumable", async () => {
    // 탭이 중간에 닫히는 등 정상 중단 경로를 타지 못해 일부 단위가 이미 완료된 채
    // manifest.json이 남아있는 경우에만 "이어서 처리" 복원이 의미가 있다. runner.ts의
    // finalizeManifest()는 이 경우 manifest.status를 "paused"로 기록한다.
    const outputDir = new MemoryDirectory("sample_cuts", {
      "manifest.json": new TextEncoder().encode(JSON.stringify({
        status: "paused",
        ledger: [{ unitId: "a", status: "completed" }, { unitId: "b", status: "pending" }]
      }))
    });

    expect(await hasResumableProgress(outputDir as unknown as FileSystemDirectoryHandle)).toBe(true);
  });

  it("treats a fully completed manifest as nothing to resume even though every unit is completed", async () => {
    // 2026-09-14 회귀 수정: 작업이 끝까지 정상적으로 완료된 경우 ledger의 모든 단위가
    // "completed"이지만, 이는 "재개할 진행 중 작업"이 아니라 이미 끝난 작업이다.
    // finalizeManifest()는 이 경우 manifest.status를 "completed"(또는 검수 필요 시
    // "completed_with_review")로 기록하므로, ledger 단위 상태가 아니라 manifest 레벨의
    // status로 판정해야 한다. (수영복.zip 6/6 완료 후 새로고침해도 이전 진행 카드가
    // 다시 뜨던 버그의 재발 방지 테스트)
    const outputDir = new MemoryDirectory("sample_cuts", {
      "manifest.json": new TextEncoder().encode(JSON.stringify({
        status: "completed",
        ledger: [{ unitId: "a", status: "completed" }, { unitId: "b", status: "completed" }]
      }))
    });

    expect(await hasResumableProgress(outputDir as unknown as FileSystemDirectoryHandle)).toBe(false);
  });

  it("treats a manifest completed with review flags as nothing to resume", async () => {
    const outputDir = new MemoryDirectory("sample_cuts", {
      "manifest.json": new TextEncoder().encode(JSON.stringify({
        status: "completed_with_review",
        ledger: [{ unitId: "a", status: "completed" }]
      }))
    });

    expect(await hasResumableProgress(outputDir as unknown as FileSystemDirectoryHandle)).toBe(false);
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
