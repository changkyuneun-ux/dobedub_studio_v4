# Webtoon Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DOBEDUB STUDIO user-facing image-cut tool that prepares PNG source images for future I2V workflows, reads user-selected or dropped images, PDFs, directories, and ZIPs in the browser, derives the work/output location from that input, and writes deterministic cut files back to the local filesystem without uploading or downloading media through the server.

**Architecture:** ECS and the local development server provide login, UI, versioned browser code, and split policies only. The actual cut job always runs inside the user's browser: the React screen obtains file/folder handles from the user's selected or dropped input, derives the working/output location from that input, creates a preflight inventory with one stable unit ID per raster file and PDF page, runs sequential decoding and cut detection in a Web Worker, and reconciles the unit ledger against CSV, manifest, and verified PNG files before completion. FastAPI and ECS never receive source or result bytes, and the product does not expose a Local/ECS execution-environment selector for this feature.

**Tech Stack:** React 18, TypeScript, Vite, Web Workers, File System Access API, Canvas/OffscreenCanvas, `pdfjs-dist`, `fflate`, Vitest, existing FastAPI shell and pytest contract tests.

**Spec:** `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md`

## Global Constraints

- Work on branch `feat/webtoon-cut`.
- Preserve all existing uncommitted and untracked user files.
- Support desktop Chrome and Edge in the first release; show an unsupported-browser state elsewhere.
- Do not add any FastAPI media upload, cut-processing, or download endpoint.
- Do not add a user-facing `Local / ECS` execution selector; ECS is the service shell and policy/code source, not a media-processing target.
- Do not send `File`, `Blob`, `ArrayBuffer`, `ImageBitmap`, local path, file name, or relative path through `fetch`, XHR, WebSocket, or `sendBeacon`.
- Keep source and output media exclusively in the user-approved local input/work location.
- Use the exact output layouts and naming rules in the spec.
- Render PDF pages at `300 / 72` scale.
- Encode every generated cut, overlay, and contact sheet as PNG with MIME `image/png`, regardless of input format.
- Keep crop dimensions and aspect ratio at source resolution; do not resize, upscale, pad, or normalize for a specific I2V model in this feature.
- A zero-detection page becomes one `fullpage` cut with `review_required`.
- A low-confidence continuous scene remains one cut with `review_continuous` and `review_required`.
- Strong full-width horizontal scene transitions are review candidates by default; apply them only through a review-screen reprocess action.
- Build a deterministic source-unit inventory before processing: one unit per raster image and one unit per PDF page, including directory and ZIP contents.
- Never report `completed` until inventory, manifest, summary rows, and verified PNG files reconcile; retry a missing unit once and otherwise report `completed_with_errors`.
- Report `completed_with_review` instead of plain `completed` when every unit is accounted for but any unit has a `review_required` detection-quality flag.
- Do not add a database migration; job recovery is local `manifest.json` state.
- Keep one active browser-local job per authenticated user/browser tab in a Provider above `StudioShell`; route changes must not dispose its directory handle, controller, or Worker.
- On logout or authenticated-user change, safely pause the active job and release its Worker and local handle references.
- Do not commit, push, or deploy unless the user explicitly asks.

## File Structure

### New frontend feature files

- `frontend/src/features/webtoon-cut/types.ts` — shared input, region, progress, summary, manifest, and worker-message types.
- `frontend/src/features/webtoon-cut/constants.ts` — supported extensions, exact thresholds, limits, and engine/schema versions.
- `frontend/src/features/webtoon-cut/naming.ts` — NFC comparison, safe output names, collision resolution, and layout calculation.
- `frontend/src/features/webtoon-cut/filesystem.ts` — directory permission, discovery, directory creation, atomic file writing, and test adapters.
- `frontend/src/features/webtoon-cut/archive.ts` — safe ZIP entry validation and item-by-item extraction with `fflate`.
- `frontend/src/features/webtoon-cut/pdf.ts` — PDF.js page enumeration and 300dpi canvas rendering.
- `frontend/src/features/webtoon-cut/pixels.ts` — image decoding and pure typed-array row/column statistics.
- `frontend/src/features/webtoon-cut/gridDetector.ts` — bordered page/grid recursive splitter.
- `frontend/src/features/webtoon-cut/stripDetector.ts` — white-gutter vertical-webtoon splitter.
- `frontend/src/features/webtoon-cut/transitionDetector.ts` — second-stage full-width scene-transition detector.
- `frontend/src/features/webtoon-cut/detector.ts` — explicit/automatic mode dispatch and fallback policy.
- `frontend/src/features/webtoon-cut/artifacts.ts` — crop encoding, `summary.csv`, overlays, contact sheets, and manifest serialization.
- `frontend/src/features/webtoon-cut/reconcile.ts` — source-unit ledger reconciliation and generated-PNG integrity checks.
- `frontend/src/features/webtoon-cut/runner.ts` — resumable sequential job orchestration and cancellation boundaries.
- `frontend/src/features/webtoon-cut/worker.ts` — worker entry point and message protocol.
- `frontend/src/features/webtoon-cut/controller.ts` — UI-side worker lifecycle and progress subscription.
- `frontend/src/features/webtoon-cut/jobStore.ts` — route-independent active-job state, controller ownership, and screen subscription lifecycle.
- `frontend/src/features/webtoon-cut/WebtoonCutJobContext.tsx` — authenticated-tab Provider and screen hook.
- `frontend/src/screens/webtoonCutScreen.tsx` — input selection/drop target, derived work/output locations, inventory preview, progress, flags, and completion surface.

### New tests and fixtures

- `frontend/src/features/webtoon-cut/naming.test.ts`
- `frontend/src/features/webtoon-cut/archive.test.ts`
- `frontend/src/features/webtoon-cut/stripDetector.test.ts`
- `frontend/src/features/webtoon-cut/transitionDetector.test.ts`
- `frontend/src/features/webtoon-cut/gridDetector.test.ts`
- `frontend/src/features/webtoon-cut/runner.test.ts`
- `frontend/src/features/webtoon-cut/reconcile.test.ts`
- `frontend/src/features/webtoon-cut/jobStore.test.ts`
- `frontend/src/features/webtoon-cut/networkIsolation.test.ts`
- `frontend/src/features/webtoon-cut/__fixtures__/synthetic.ts` — generated pixel arrays; no binary fixture maintenance.
- `backend/tests/test_frontend_webtoon_cut_contract.py` — route/menu/permission/build contract.
- `scripts/webtoon_cut_golden_check.mjs` — opt-in local golden check against user-owned samples outside Git.

### Existing files to modify

- `frontend/package.json` and `frontend/package-lock.json` — add `pdfjs-dist`, `fflate`, and Vitest scripts/dependencies.
- `frontend/src/router.ts` — add `webtoonCuts` and `/studio/webtoon-cuts`.
- `frontend/src/components/AppShell.tsx` — add the regular-user top-level `LOCAL` menu item above `GENERATE`.
- `frontend/src/helpers/navigation.ts` — map `webtoonCuts` to the new route.
- `frontend/src/main.tsx` — mount the authenticated `WebtoonCutJobProvider` above `StudioShell`.
- `frontend/src/StudioShell.tsx` — permission, label, import, and render branch.
- `frontend/src/styles.css` — feature styles under `.v3-webtoon-cut-*` selectors.
- `scripts/verify.sh` — run focused frontend unit tests before the frontend build.
- `docs/dobedub-studio-user-manual.md` — document the local-only workflow and supported browser requirement.
- `docs/aws-ecs-deployment.md` — record that ECS only serves code and stores no cut media.

---

### Task 1: Establish the typed contract and frontend test gate

**Files:**
- Create: `frontend/src/features/webtoon-cut/types.ts`
- Create: `frontend/src/features/webtoon-cut/constants.ts`
- Create: `frontend/src/features/webtoon-cut/constants.test.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `scripts/verify.sh`

**Interfaces:**
- Produces: `CutMode`, `InputKind`, `PixelRegion`, `DetectedCut`, `SourceUnitDescriptor`, `SourceUnit`, `UnitLedgerEntry`, `UnitStatus`, `JobStatus`, `SummaryRow`, `WebtoonCutManifest`, `ReconciliationReport`, `WorkerRequest`, and `WorkerEvent`.
- Produces: `ENGINE_VERSION`, `MANIFEST_SCHEMA_VERSION`, `PAGE_POLICY`, `STRIP_POLICY`, and `ARCHIVE_LIMITS`.
- Consumes: none.

- [ ] **Step 1: Install deterministic browser dependencies and the test runner**

Run:

```bash
npm --prefix frontend install pdfjs-dist fflate
npm --prefix frontend install --save-dev vitest
```

Expected: `frontend/package.json` and `frontend/package-lock.json` contain the three packages and no unrelated dependency upgrades.

- [ ] **Step 2: Add a failing constants contract test**

```ts
import { describe, expect, it } from "vitest";
import { ARCHIVE_LIMITS, PAGE_POLICY, STRIP_POLICY } from "./constants";

describe("webtoon cut constants", () => {
  it("locks the approved production thresholds", () => {
    expect(PAGE_POLICY).toMatchObject({ outerMarginRatio: 0.03, minAreaRatio: 0.02, maxDepth: 8 });
    expect(STRIP_POLICY).toMatchObject({ foregroundFloor: 245, chromaFloor: 8, rowRatio: 0.003, minGapPx: 100, gapWidthRatio: 0.06, paddingY: 15 });
    expect(ARCHIVE_LIMITS).toMatchObject({ maxEntries: 10_000, maxInputs: 5_000, maxExpandedBytes: 4 * 1024 ** 3, maxEntryBytes: 500 * 1024 ** 2, maxCompressionRatio: 200 });
  });
});
```

- [ ] **Step 3: Run the test and verify that it fails before the modules exist**

Run: `npm --prefix frontend exec vitest run src/features/webtoon-cut/constants.test.ts`

Expected: FAIL because `./constants` cannot be resolved.

- [ ] **Step 4: Add the shared types and exact constants**

```ts
export type CutMode = "auto" | "page" | "strip";
export type InputKind = "image" | "pdf" | "directory" | "zip";
export type UnitStatus = "pending" | "running" | "completed" | "error";
export type JobStatus = "idle" | "running" | "paused" | "completed" | "completed_with_review" | "completed_with_errors" | "failed";
export type PixelRegion = { x0: number; y0: number; x1: number; y1: number };
export type SourceUnitDescriptor = {
  unitId: string;
  sourcePath: string;
  sourceKind: "image" | "pdf-page";
  page: number | null;
};
export type SourceUnit = SourceUnitDescriptor & {
  image: ImageData;
  width: number;
  height: number;
};
export type UnitLedgerEntry = SourceUnitDescriptor & {
  status: UnitStatus;
  attempts: number;
  flags: string[];
  outputs: Array<{ path: string; width: number; height: number }>;
  errorCode?: string;
};
export type ReconciliationReport = {
  expectedUnitCount: number;
  completedUnitCount: number;
  errorUnitIds: string[];
  reviewUnitIds: string[];
  missingUnitIds: string[];
  invalidOutputUnitIds: string[];
  canComplete: boolean;
};
export type DetectedCut = PixelRegion & {
  index: number;
  mode: "grid" | "gutter" | "transition" | "fullpage" | "end_card";
  confidence: number;
  flags: string[];
};

export const ENGINE_VERSION = "webtoon-cut-1";
export const MANIFEST_SCHEMA_VERSION = 1;
export const PAGE_POLICY = Object.freeze({ outerMarginRatio: 0.03, minAreaRatio: 0.02, maxDepth: 8 });
export const STRIP_POLICY = Object.freeze({ foregroundFloor: 245, chromaFloor: 8, rowRatio: 0.003, minGapPx: 100, gapWidthRatio: 0.06, paddingY: 15 });
export const TRANSITION_POLICY = Object.freeze({ analysisWidth: 300, deltaFloor: 12, minCoverage: 0.95, minMedianJump: 40, minLocalContrast: 80, contrastWindow: 8, minSegmentWidthRatio: 0.30 });
export const ARCHIVE_LIMITS = Object.freeze({ maxEntries: 10_000, maxInputs: 5_000, maxExpandedBytes: 4 * 1024 ** 3, maxEntryBytes: 500 * 1024 ** 2, maxCompressionRatio: 200 });
```

Complete `types.ts` with the manifest and worker discriminated unions listed under **Interfaces**, using camelCase in JSON and the exact CSV column names from the spec.

- [ ] **Step 5: Add the frontend test command to the shared verification gate**

Add to `frontend/package.json`:

```json
"test:webtoon-cut": "vitest run src/features/webtoon-cut/*.test.ts"
```

Insert before the frontend build in `scripts/verify.sh`:

```bash
echo "[3/5] Run webtoon cut frontend tests"
npm --prefix frontend run test:webtoon-cut
```

Renumber the remaining progress labels to `[4/5]` and `[5/5]`.

- [ ] **Step 6: Run the focused test**

Run: `npm --prefix frontend run test:webtoon-cut`

Expected: PASS.

- [ ] **Step 7: Commit this independently reviewable contract**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/features/webtoon-cut/types.ts frontend/src/features/webtoon-cut/constants.ts frontend/src/features/webtoon-cut/constants.test.ts scripts/verify.sh
git commit -m "test: define webtoon cut engine contract"
```

### Task 2: Implement safe local discovery and output naming

**Files:**
- Create: `frontend/src/features/webtoon-cut/naming.ts`
- Create: `frontend/src/features/webtoon-cut/naming.test.ts`
- Create: `frontend/src/features/webtoon-cut/filesystem.ts`
- Create: `frontend/src/features/webtoon-cut/filesystem.test.ts`

**Interfaces:**
- Consumes: `InputKind`, `ARCHIVE_LIMITS`.
- Produces: `normalizeForComparison(name: string): string`.
- Produces: `safeOutputName(name: string): string`.
- Produces: `planOutputPath(input: DiscoveredInput, collisions: Set<string>): string[]`.
- Produces: `requestWorkingDirectory(): Promise<FileSystemDirectoryHandle>`.
- Produces: `discoverInputs(root: FileSystemDirectoryHandle): Promise<DiscoveredInput[]>`.
- Produces: `writeAtomically(parent, name, bytes): Promise<void>`.

- [ ] **Step 1: Write failing path-policy tests**

```ts
it("places a normal image beside its source under a stem_cuts directory", () => {
  expect(planOutputPath(image("진실의 방_001_006.jpg"), new Set())).toEqual(["진실의 방_001_006_cuts"]);
});

it("preserves ZIP parents and adds one source-stem directory", () => {
  expect(planArchiveEntryPath("episode-pack.zip", "scene-a/page-001.jpg", new Set())).toEqual(["episode-pack_cuts", "scene-a", "page-001"]);
});

it("disambiguates equal stems with their extensions", () => {
  const names = disambiguateSiblingStems(["page.jpg", "page.png"]);
  expect(names).toEqual(["page__jpg", "page__png"]);
});
```

- [ ] **Step 2: Run the naming tests and confirm failure**

Run: `npm --prefix frontend exec vitest run src/features/webtoon-cut/naming.test.ts`

Expected: FAIL because the naming module does not exist.

- [ ] **Step 3: Implement normalization, safe names, and deterministic collision handling**

Use `name.normalize("NFC")` for comparisons, replace `/\\:\0` and control characters with `_`, strip trailing dots/spaces, and append `__2`, `__3` only after normalized collision detection. Preserve original source names and paths in memory; only derived output components are sanitized.

```ts
export function safeOutputName(raw: string): string {
  const normalized = raw.normalize("NFC").replace(/[\\/:\u0000-\u001f\u007f]/g, "_").replace(/[. ]+$/g, "");
  return normalized || "unnamed";
}
```

- [ ] **Step 4: Write failing discovery and atomic-write tests using an in-memory directory adapter**

The test adapter must expose the same feature-owned `DirectoryPort` interface used by production code, so tests do not require a native picker.

```ts
it("excludes hidden metadata and generated output trees", async () => {
  const root = memoryDirectory({ "page.jpg": bytes(1), ".DS_Store": bytes(1), "._page.jpg": bytes(1), "page_cuts": { "page-01.png": bytes(1) } });
  expect((await discoverInputs(root)).map((item) => item.relativePath)).toEqual(["page.jpg"]);
});

it("renames a complete partial write and leaves no partial file", async () => {
  const root = memoryDirectory({});
  await writeAtomically(root, "page-01.png", bytes(3));
  expect(root.files()).toEqual(["page-01.png"]);
});
```

- [ ] **Step 5: Implement the production File System Access adapter**

Feature-detect `window.showDirectoryPicker`, request `mode: "readwrite"`, verify `queryPermission`/`requestPermission`, recursively enumerate sorted NFC names, and skip hidden names, symlinks where exposed, and `*_cuts` directories. Write `<name>.partial`, close the writable stream, create the final file, copy the completed bytes, and remove the partial file only after the final write succeeds.

- [ ] **Step 6: Run path and filesystem tests**

Run: `npm --prefix frontend exec vitest run src/features/webtoon-cut/naming.test.ts src/features/webtoon-cut/filesystem.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit the filesystem boundary**

```bash
git add frontend/src/features/webtoon-cut/naming.ts frontend/src/features/webtoon-cut/naming.test.ts frontend/src/features/webtoon-cut/filesystem.ts frontend/src/features/webtoon-cut/filesystem.test.ts
git commit -m "feat: add local webtoon cut input workspace"
```

### Task 3: Build the complete source inventory and safe input adapters

**Files:**
- Create: `frontend/src/features/webtoon-cut/archive.ts`
- Create: `frontend/src/features/webtoon-cut/archive.test.ts`
- Create: `frontend/src/features/webtoon-cut/pdf.ts`
- Create: `frontend/src/features/webtoon-cut/inputSources.ts`
- Create: `frontend/src/features/webtoon-cut/inputSources.test.ts`

**Interfaces:**
- Consumes: `ARCHIVE_LIMITS`, `DiscoveredInput`, `DirectoryPort`.
- Produces: `validateArchiveEntry(entry: ZipEntryMeta): string[] | null`.
- Produces: `iterateArchive(file: File, signal: AbortSignal): AsyncIterable<SourceUnit>`.
- Produces: `iteratePdf(file: File, signal: AbortSignal): AsyncIterable<SourceUnit>`.
- Produces: `iterateSource(input, signal): AsyncIterable<SourceUnit>`.
- Produces: `buildSourceInventory(input, signal): Promise<SourceUnitDescriptor[]>`.
- Produces: `sourceUnitId(sourceKind, normalizedRelativePath, page): string`.

- [ ] **Step 1: Write failing ZIP safety tests**

```ts
it.each(["../escape.jpg", "/absolute.jpg", "C:/escape.jpg", "ok/../../escape.png"])("rejects unsafe ZIP path %s", (name) => {
  expect(() => validateArchiveEntry(entry(name, 10, 10))).toThrow(/안전하지 않은 ZIP 경로/);
});

it("ignores metadata and unsupported files", () => {
  expect(validateArchiveEntry(entry("__MACOSX/._page.jpg", 10, 10))).toBeNull();
  expect(validateArchiveEntry(entry("notes.txt", 10, 10))).toBeNull();
});

it("rejects an excessive compression ratio", () => {
  expect(() => validateArchiveEntry(entry("page.jpg", 201_000, 1_000))).toThrow(/압축비/);
});
```

- [ ] **Step 2: Run ZIP tests and confirm failure**

Run: `npm --prefix frontend exec vitest run src/features/webtoon-cut/archive.test.ts`

Expected: FAIL because `archive.ts` does not exist.

- [ ] **Step 3: Implement ZIP validation and ordered entry iteration**

Use `fflate` to read supported entries, normalize `\\` to `/`, reject absolute/drive/parent traversal, apply every limit before processing, and yield one entry at a time in normalized relative-path order. Never write extracted source files to the derived work/output location.

- [ ] **Step 4: Write failing PDF scale and source-dispatch tests**

```ts
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
    "image:cover.jpg",
  ]);
});

it("rejects a partial inventory before any output write", async () => {
  const input = fakeInputTree({ "good.jpg": raster(), "broken.pdf": unreadablePdfPageCount() });
  await expect(buildSourceInventory(input, neverAborted())).rejects.toMatchObject({ code: "inventory_error" });
});
```

- [ ] **Step 5: Implement PDF.js and raster adapters**

Configure a bundled PDF.js worker URL through Vite, disable network range loading for local `File` input, read `numPages` before rendering, render one page at a time at `300 / 72`, emit one-based page numbers, and destroy page/document resources after each page. Decode raster files with `createImageBitmap` and convert them to `ImageData` through `OffscreenCanvas`.

Before any cut output is written, recursively enumerate normal, directory, and ZIP inputs into a stable NFC-sorted inventory. Record one `SourceUnitDescriptor` per raster file and one per PDF page, with PDF page IDs covering `1..numPages` without gaps. ZIP entry paths remain relative to the ZIP root. Reject duplicate `unitId` values before starting the job. If a PDF page count or complete ZIP entry list cannot be read, return `inventory_error` and perform no output writes; do not start with a partial inventory.

- [ ] **Step 6: Run all input-adapter tests and build TypeScript**

Run:

```bash
npm --prefix frontend exec vitest run src/features/webtoon-cut/archive.test.ts src/features/webtoon-cut/inputSources.test.ts
npm --prefix frontend run build
```

Expected: both commands PASS.

- [ ] **Step 7: Commit the input adapters**

```bash
git add frontend/src/features/webtoon-cut/archive.ts frontend/src/features/webtoon-cut/archive.test.ts frontend/src/features/webtoon-cut/pdf.ts frontend/src/features/webtoon-cut/inputSources.ts frontend/src/features/webtoon-cut/inputSources.test.ts frontend/package.json frontend/package-lock.json
git commit -m "feat: read local webtoon cut inputs"
```

### Task 4: Port the two-stage cut detection engine

**Files:**
- Create: `frontend/src/features/webtoon-cut/pixels.ts`
- Create: `frontend/src/features/webtoon-cut/__fixtures__/synthetic.ts`
- Create: `frontend/src/features/webtoon-cut/gridDetector.ts`
- Create: `frontend/src/features/webtoon-cut/gridDetector.test.ts`
- Create: `frontend/src/features/webtoon-cut/stripDetector.ts`
- Create: `frontend/src/features/webtoon-cut/stripDetector.test.ts`
- Create: `frontend/src/features/webtoon-cut/transitionDetector.ts`
- Create: `frontend/src/features/webtoon-cut/transitionDetector.test.ts`
- Create: `frontend/src/features/webtoon-cut/detector.ts`

**Interfaces:**
- Consumes: `PixelRegion`, `DetectedCut`, `PAGE_POLICY`, `STRIP_POLICY`, `TRANSITION_POLICY`.
- Produces: `detectGridCuts(image: ImageData): DetectedCut[]`.
- Produces: `detectStripCuts(image: ImageData): DetectedCut[]`.
- Produces: `detectTransitionCuts(image: ImageData, region: PixelRegion): PixelRegion[]`.
- Produces: `detectCuts(image: ImageData, mode: CutMode, sourceKind: "image" | "pdf"): DetectedCut[]`.

- [ ] **Step 1: Add synthetic image generators and failing strip tests**

```ts
it("splits foreground bands separated by at least the approved white gap", () => {
  const image = verticalBands(1500, 2200, [[100, 500], [800, 1200], [1500, 1900]]);
  expect(detectStripCuts(image).map(({ y0, y1 }) => [y0, y1])).toEqual([[85, 515], [785, 1215], [1485, 1915]]);
});

it("does not split a 99px gap at 1500px width", () => {
  const image = verticalBands(1500, 1000, [[0, 400], [499, 900]]);
  expect(detectStripCuts(image)).toHaveLength(1);
});
```

- [ ] **Step 2: Add failing full-width-transition tests**

```ts
it("accepts two near-full-width transitions and creates three cuts", () => {
  const image = threeSceneStrip(1500, 8521, [2843, 3754]);
  expect(detectTransitionCuts(image, { x0: 0, y0: 0, x1: 1500, y1: 8521 }).map(({ y0, y1 }) => [y0, y1])).toEqual([[0, 2843], [2843, 3754], [3754, 8521]]);
});

it("rejects an 84 percent inset frame edge", () => {
  const image = insetFrameEdge(1500, 1200, 329, 0.84);
  expect(detectTransitionCuts(image, { x0: 0, y0: 0, x1: 1500, y1: 1200 })).toEqual([{ x0: 0, y0: 0, x1: 1500, y1: 1200 }]);
});

it("splits a no-gutter raster shorter than three widths at a strong full-width transition", () => {
  const image = twoSceneNoGutter(1500, 3600, 1800);
  expect(detectCuts(image, "auto", "image").map(({ y0, y1 }) => [y0, y1])).toEqual([[0, 1800], [1800, 3600]]);
});
```

- [ ] **Step 3: Run strip and transition tests and confirm failure**

Run: `npm --prefix frontend exec vitest run src/features/webtoon-cut/stripDetector.test.ts src/features/webtoon-cut/transitionDetector.test.ts`

Expected: FAIL because the detectors do not exist.

- [ ] **Step 4: Implement row statistics and white-gutter segmentation**

For every pixel compute `minChannel` and `chroma`; mark foreground when `minChannel < 245 || chroma > 8`. Mark a row active at ratio `>= 0.003`, find inactive runs with height `>= max(100, width * 0.06)`, derive content runs, add 15px top/bottom padding, merge overlapping padded regions, and preserve full width.

- [ ] **Step 5: Implement second-stage transition scoring**

Downsample analysis width to 300 with box averaging, apply a five-sample horizontal/vertical separable blur, compute adjacent-row absolute deltas, and use:

```ts
const transitionScore = medianJump * (0.25 + coverage12) + 0.35 * localContrast;
const accepted = coverage12 >= 0.95 && medianJump >= 40 && localContrast >= 80;
```

Apply non-maximum suppression with `max(100, width * 0.15)` minimum distance and reject candidates creating a segment shorter than `max(100, width * 0.30)`. Invoke this detector only for long results flagged as `continuous_sequence` (`height > width * 3`). The detector records only candidates whose intensity/color jump covers at least 95% of the full width, and it must not change the default cut outputs until the user selects the `수평 장면 전환` reprocess type in the review screen.

- [ ] **Step 6: Add failing grid-recursion tests**

Generate a white page with a 3% outer margin and four black, low-chroma bordered rectangles separated by white gutters. Assert four regions in top-to-bottom and left-to-right order. Add a borderless infographic fixture and assert one `fullpage` result.

- [ ] **Step 7: Implement the page/grid splitter**

Port the approved `grid_split.py` behavior with typed-array scans: derive black/low-chroma horizontal and vertical runs, cluster candidate positions within `max(4, dimension * 0.003)`, merge span gaps up to 3%, require gutter evidence, estimate border thickness from high-coverage candidates, recurse to depth 8, and filter by the spec's area/dimension/content ratios. Return fullpage after cropping the outer 3% when no valid panel remains.

- [ ] **Step 8: Implement automatic dispatch and flags**

Use page mode for PDFs, strip mode for raster `height / width >= 2.5`, and page mode otherwise. Mark short results `end_card`; mark unchanged regions taller than `width * 3` as `continuous_sequence` and `review_continuous`. For those long results only, record strong full-width transition candidates as metadata instead of applying them automatically. Add `thin` and `many` according to the spec. Add `review_required` whenever a unit has `fullpage`, `review_continuous`, `thin`, or `many`, so potentially incomplete splitting is listed by source image or PDF page.

- [ ] **Step 9: Run every detector test**

Run: `npm --prefix frontend exec vitest run src/features/webtoon-cut/gridDetector.test.ts src/features/webtoon-cut/stripDetector.test.ts src/features/webtoon-cut/transitionDetector.test.ts`

Expected: PASS.

- [ ] **Step 10: Commit the detector engine**

```bash
git add frontend/src/features/webtoon-cut/pixels.ts frontend/src/features/webtoon-cut/__fixtures__/synthetic.ts frontend/src/features/webtoon-cut/gridDetector.ts frontend/src/features/webtoon-cut/gridDetector.test.ts frontend/src/features/webtoon-cut/stripDetector.ts frontend/src/features/webtoon-cut/stripDetector.test.ts frontend/src/features/webtoon-cut/transitionDetector.ts frontend/src/features/webtoon-cut/transitionDetector.test.ts frontend/src/features/webtoon-cut/detector.ts
git commit -m "feat: add browser-local cut detection engine"
```

### Task 5: Write verified cut artifacts and reconcile every source unit

**Files:**
- Create: `frontend/src/features/webtoon-cut/artifacts.ts`
- Create: `frontend/src/features/webtoon-cut/artifacts.test.ts`
- Create: `frontend/src/features/webtoon-cut/reconcile.ts`
- Create: `frontend/src/features/webtoon-cut/reconcile.test.ts`
- Create: `frontend/src/features/webtoon-cut/runner.ts`
- Create: `frontend/src/features/webtoon-cut/runner.test.ts`
- Create: `frontend/src/features/webtoon-cut/worker.ts`
- Create: `frontend/src/features/webtoon-cut/controller.ts`
- Create: `frontend/src/features/webtoon-cut/jobStore.ts`
- Create: `frontend/src/features/webtoon-cut/jobStore.test.ts`

**Interfaces:**
- Consumes: `buildSourceInventory`, `iterateSource`, `detectCuts`, `DirectoryPort`, `DetectedCut`, `SourceUnitDescriptor`, `UnitLedgerEntry`, `WebtoonCutManifest`, `WorkerRequest`, `WorkerEvent`.
- Produces: `encodeCut(image, region): Promise<Blob>` with MIME `image/png`.
- Produces: `serializeSummary(rows: SummaryRow[]): Uint8Array`.
- Produces: `verifyPngOutput(file, expectedSize): Promise<boolean>`.
- Produces: `reconcileJob(inventory, manifest, outputRoot): Promise<ReconciliationReport>`.
- Produces: `runWebtoonCutJob(request, ports, signal): Promise<WebtoonCutManifest>`.
- Produces: `WebtoonCutController.start()`, `.pause()`, `.subscribe()` and `.dispose()`.
- Produces: `createWebtoonCutJobStore(controller)` with `.getSnapshot()`, `.subscribe()`, `.start()`, `.pause()`, and `.disposeForSessionEnd()`.

- [ ] **Step 1: Write failing CSV, filename, and manifest-resume tests**

```ts
it("writes UTF-8 BOM and exact summary columns", () => {
  const csv = new TextDecoder().decode(serializeSummary([summaryRow()]));
  expect(csv.startsWith("\uFEFFunit_id,source_path,page,cut,filename,mode,x0,y0,x1,y1,width,height,confidence,flag,elapsed_ms,status,error\r\n")).toBe(true);
});

it("skips a completed unit only when fingerprint, engine, and options match", () => {
  expect(canResume(completedManifest(), matchingRequest())).toBe(true);
  expect(canResume(completedManifest(), changedThresholdRequest())).toBe(false);
});

it("encodes every generated image as PNG without changing crop dimensions", async () => {
  const blob = await encodeCut(sourceCanvas(640, 480), { x0: 10, y0: 20, x1: 610, y1: 420 });
  expect(blob.type).toBe("image/png");
  await expect(decodedSize(blob)).resolves.toEqual({ width: 600, height: 400 });
});

it("keeps an active job when its screen subscriber detaches", async () => {
  const controller = fakeController();
  const store = createWebtoonCutJobStore(controller);
  const unsubscribe = store.subscribe(() => undefined);
  await store.start(jobRequest());
  unsubscribe();
  expect(store.getSnapshot().status).toBe("running");
  expect(controller.dispose).not.toHaveBeenCalled();
});

it("refuses completion when any inventoried PDF page lacks a verified PNG", async () => {
  const inventory = pdfInventory("book.pdf", 3);
  const output = memoryDirectory({ "001-01.png": validPng(100, 100), "003-01.png": validPng(100, 100) });
  const report = await reconcileJob(inventory, completedPdfManifest(3), output);
  expect(report.missingUnitIds).toEqual(["pdf:book.pdf#page=002"]);
  expect(report.canComplete).toBe(false);
});

it("reprocesses a completed unit whose recorded PNG was deleted", async () => {
  const decision = await resumeDecision(completedImageUnit("image:page.jpg", "page-01.png"), memoryDirectory({}));
  expect(decision).toEqual({ action: "reprocess", reason: "missing_output" });
});

it("writes no artifacts when the complete source inventory cannot be built", async () => {
  const output = memoryDirectory({});
  await expect(runWebtoonCutJob(jobWithUnreadablePdfCount(), ports({ output }), neverAborted())).rejects.toMatchObject({ code: "inventory_error" });
  expect(output.files()).toEqual([]);
});

it("surfaces a fullpage fallback as completed_with_review", async () => {
  const result = await runWebtoonCutJob(singleBorderlessImageJob(), memoryPorts(), neverAborted());
  expect(result.status).toBe("completed_with_review");
  expect(result.units[0].flags).toEqual(expect.arrayContaining(["fullpage", "review_required"]));
});
```

- [ ] **Step 2: Run artifact and runner tests and confirm failure**

Run: `npm --prefix frontend exec vitest run src/features/webtoon-cut/artifacts.test.ts src/features/webtoon-cut/reconcile.test.ts src/features/webtoon-cut/runner.test.ts src/features/webtoon-cut/jobStore.test.ts`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement lossless-coordinate crop encoding and debug artifacts**

Crop with `drawImage` using integer source coordinates and an output canvas exactly `x1 - x0` by `y1 - y0`. Encode every crop, overlay, and contact sheet with `convertToBlob({ type: "image/png" })` and a `.png` filename, regardless of whether the input was JPG, PNG, WebP, or a rendered PDF page. Preserve source alpha where present. Produce scaled overlay/contact-sheet files without reusing their dimensions for source crops, and do not resize, upscale, pad, or apply model-specific I2V normalization to cut files.

- [ ] **Step 4: Implement summary and manifest serialization**

Escape CSV quotes, CR, and LF; prefix BOM; use CRLF rows. Serialize manifest with stable key ordering and two-space indentation. Store only relative paths and `name/size/lastModified` fingerprints. Write the complete ordered inventory and `expectedUnitCount` before processing. Update the ledger and manifest after a source image or one PDF page completes atomically; each successful source unit contributes at least one CSV row with its deterministic `unit_id`.

- [ ] **Step 5: Implement sequential orchestration and pause boundaries**

For every source unit: mark it `running`, decode, detect, replace an empty result with one `fullpage` cut, write cuts, read each file back, verify its PNG signature/decodability/dimensions, write debug data, append summary rows, then mark the unit `completed` and write manifest. On an input error, append one `status=error` row, mark that exact unit `error`, and continue. Observe `AbortSignal` between atomic units and record `paused` before returning.

Before emitting a terminal event, call `reconcileJob` to compare inventory, ledger, CSV coverage, and actual output files. Reset missing or invalid completed units to `pending` and retry those units once without repeating valid units. Reconcile again; emit `completed` only when `expectedUnitCount === completedUnitCount`, no ledger unit is pending/running/error, every unit has at least one verified PNG, and `reviewUnitIds` is empty. Emit `completed_with_review` when output reconciliation passes but `reviewUnitIds` is non-empty. Otherwise mark unresolved units `missing_output` and emit `completed_with_errors` with their IDs.

- [ ] **Step 6: Implement worker messages, UI controller, and route-independent job store**

Use a discriminated protocol:

```ts
type WorkerRequest =
  | { type: "start"; request: CutJobRequest }
  | { type: "pause"; jobId: string };

type WorkerEvent =
  | { type: "progress"; jobId: string; completed: number; total: number; cutCount: number; elapsedMs: number }
  | { type: "completed"; jobId: string; outcome: "completed" | "completed_with_review" | "completed_with_errors"; manifest: WebtoonCutManifest; reviewUnitIds: string[]; unresolvedUnitIds: string[] }
  | { type: "paused"; jobId: string; manifest: WebtoonCutManifest }
  | { type: "failed"; jobId: string; code: string; message: string };
```

Throttle progress delivery to once per 500ms. Transfer `ArrayBuffer` objects to the Worker rather than cloning them, and release decoded resources after each unit.

Make `jobStore.ts` the owner of the active request, directory/output handles, options, current snapshot, controller, and Worker-backed lifecycle. Screen subscription cleanup must remove only the listener; it must not pause, dispose, or clear the job. Limit the store to one active job. `disposeForSessionEnd()` must request a safe pause, wait for the current atomic unit to finish, clear local handle references, and then dispose the controller.

- [ ] **Step 7: Run runner tests and frontend build**

Run:

```bash
npm --prefix frontend exec vitest run src/features/webtoon-cut/artifacts.test.ts src/features/webtoon-cut/reconcile.test.ts src/features/webtoon-cut/runner.test.ts src/features/webtoon-cut/jobStore.test.ts
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 8: Commit artifact generation and recovery**

```bash
git add frontend/src/features/webtoon-cut/artifacts.ts frontend/src/features/webtoon-cut/artifacts.test.ts frontend/src/features/webtoon-cut/reconcile.ts frontend/src/features/webtoon-cut/reconcile.test.ts frontend/src/features/webtoon-cut/runner.ts frontend/src/features/webtoon-cut/runner.test.ts frontend/src/features/webtoon-cut/worker.ts frontend/src/features/webtoon-cut/controller.ts frontend/src/features/webtoon-cut/jobStore.ts frontend/src/features/webtoon-cut/jobStore.test.ts
git commit -m "feat: write resumable local cut artifacts"
```

### Task 6: Integrate the user menu, route, permissions, and screen

**Files:**
- Create: `frontend/src/features/webtoon-cut/WebtoonCutJobContext.tsx`
- Create: `frontend/src/screens/webtoonCutScreen.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/helpers/navigation.ts`
- Modify: `frontend/src/StudioShell.tsx`
- Modify: `frontend/src/styles.css`
- Create: `backend/tests/test_frontend_webtoon_cut_contract.py`

**Interfaces:**
- Consumes: `WebtoonCutJobStore`, `discoverInputs`, `requestWorkingDirectory`, `CutMode`, existing `AppShell`, `shellNavigate`, authenticated `user.id`, and `jobs:run` permission checks.
- Produces: `WebtoonCutJobProvider`, `useWebtoonCutJob()`, route `webtoonCuts`, path `/studio/webtoon-cuts`, menu key `webtoonCuts`, and `WebtoonCutScreen`.

- [ ] **Step 1: Write a failing frontend integration contract**

```python
from pathlib import Path


def test_webtoon_cut_is_a_jobs_run_user_route_without_server_media_api() -> None:
    router = Path("frontend/src/router.ts").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    studio = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    main = Path("frontend/src/main.tsx").read_text(encoding="utf-8")
    backend = "\n".join(path.read_text(encoding="utf-8") for path in Path("backend/app/api/v1").glob("*.py"))

    assert '"webtoonCuts"' in router
    assert '"webtoonCuts": "/studio/webtoon-cuts"' in router
    assert '{ key: "webtoonCuts", label: "이미지 컷 분할", permission: "jobs:run" }' in shell
    assert '"webtoonCuts": "jobs:run"' in studio
    assert shell.index('label: "LOCAL"') < shell.index('label: "GENERATE"')
    assert "WebtoonCutScreen" in studio
    assert '<WebtoonCutJobProvider key={user.id}' in main
    assert main.index('<WebtoonCutJobProvider key={user.id}') < main.index('<StudioShell')
    assert "</WebtoonCutJobProvider>" in main
    assert "/webtoon-cuts/upload" not in backend
    assert "/webtoon-cuts/download" not in backend
```

- [ ] **Step 2: Run the contract and confirm failure**

Run: `python3 -m pytest backend/tests/test_frontend_webtoon_cut_contract.py -q`

Expected: FAIL because the route and screen are absent.

- [ ] **Step 3: Add the route and navigation entry**

Add `webtoonCuts` to `StudioRoute`, map it to `/studio/webtoon-cuts`, add it to `ROUTE_REQUIRED_PERMISSION` and `ROUTE_LABEL`, map `webtoonCuts` in `shellNavigate`, and insert a top-level `LOCAL` menu section above `GENERATE`. Put only `이미지 컷 분할` in that `LOCAL` section so users do not confuse the browser-local cut workflow with ECS/server generation jobs.

- [ ] **Step 4: Mount the persistent authenticated-tab job Provider**

Implement `WebtoonCutJobProvider` with `useSyncExternalStore` over the route-independent job store. In the authenticated branch of `frontend/src/main.tsx`, wrap `StudioShell` with `<WebtoonCutJobProvider key={user.id} sessionOwnerId={user.id}>`. Do not place the Provider inside `WebtoonCutScreen` or a route render branch: navigating away must unsubscribe only that screen while the Provider, directory handle, controller, and Worker keep running.

On Provider cleanup caused by logout or authenticated-user change, call `disposeForSessionEnd()` so the active atomic unit safely pauses before the Worker and local handle references are released. A page reload or tab close is still recovered by reselecting the directory and reading `manifest.json`; browser background execution after tab close is not promised.

- [ ] **Step 5: Build the screen states**

Implement these explicit states in `WebtoonCutScreen`: unsupported browser, no input, permission lost, input selected, output-location-required, inventory preview, output conflict, running, paused, completed, completed-with-review, completed-with-errors, and failed. The screen reads and commands the Provider through `useWebtoonCutJob()`; it must not create or dispose the controller. The first viewport must show one primary input selection/drop target, inventory-derived processing information, derived working location, derived output location, policy version, I2V-input purpose, and disabled Start button until at least one supported input is selected. Do not expose separate working-directory, input-range, output-policy, or cut-mode selectors in the general user flow. If a file/ZIP selection cannot grant parent-directory write permission, request an output folder only as a fallback state.

Use an in-app modal for existing-output choice. `재개` is enabled only when the manifest matches; `새 출력 폴더` selects the next collision-free suffix; `취소` performs no writes.

- [ ] **Step 6: Add progress, route-return restoration, and completion details**

Display expected, completed, review-required, error, and missing source-unit counts, source/page progress, generated cuts, elapsed time, and counts for `review_required`, `fullpage`, `review_continuous`, `thin`, `many`, `missing_output`, and `error`. A `completed_with_review` job must list the exact relative image/PDF-page identifiers with links to their debug overlays. For `review_continuous`, let the user select the file/page, choose reprocess type `수평 장면 전환`, inspect the three acceptance rules (`continuous_sequence` only, full-width 95% jump, minimum cut height and boundary distance), and run `선택 유형으로 재처리` for only that selected unit. A `completed_with_errors` job must show the exact relative file/PDF-page list and a `실패/누락 재시도` action that queues only unresolved units. When the user leaves and re-enters the route, initialize the screen from the existing Provider snapshot so the selected input, derived work/output locations, policy-derived processing info, status, progress, and results reappear without another picker prompt when permission is still valid. `중지` requests a safe pause. `결과 위치 확인` opens `showDirectoryPicker({ startIn: outputHandle, mode: "read" })` when supported; otherwise it shows the working-location-relative output path for the user to open in Finder/Explorer.

- [ ] **Step 7: Add scoped styles**

Add `.v3-webtoon-cut-*` rules that reuse existing color, typography, button, card, table, status-chip, and modal tokens. Keep the input tree keyboard navigable, use visible focus rings, and stack the settings/progress columns below 960px.

- [ ] **Step 8: Run persistence test, route contract, and frontend build**

Run:

```bash
python3 -m pytest backend/tests/test_frontend_webtoon_cut_contract.py -q
npm --prefix frontend exec vitest run src/features/webtoon-cut/jobStore.test.ts
npm run build
```

Expected: PASS.

- [ ] **Step 9: Commit the product surface**

```bash
git add frontend/src/features/webtoon-cut/WebtoonCutJobContext.tsx frontend/src/screens/webtoonCutScreen.tsx frontend/src/main.tsx frontend/src/router.ts frontend/src/components/AppShell.tsx frontend/src/helpers/navigation.ts frontend/src/StudioShell.tsx frontend/src/styles.css backend/tests/test_frontend_webtoon_cut_contract.py
git commit -m "feat: add webtoon cut user screen"
```

### Task 7: Lock network isolation and golden sample behavior

**Files:**
- Create: `frontend/src/features/webtoon-cut/networkIsolation.test.ts`
- Create: `scripts/webtoon_cut_golden_check.mjs`
- Modify: `.gitignore`
- Modify: `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md` only if measured golden coordinates require a documented correction.

**Interfaces:**
- Consumes: public detector and runner interfaces.
- Produces: a static source audit and opt-in golden check requiring `WEBTOON_CUT_FIXTURE_ROOT`.

- [ ] **Step 1: Write the failing network-isolation source audit**

```ts
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("webtoon cut network isolation", () => {
  it("contains no network transport in the feature implementation", () => {
    const root = join(process.cwd(), "src/features/webtoon-cut");
    const source = readdirSync(root).filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts")).map((name) => readFileSync(join(root, name), "utf8")).join("\n");
    expect(source).not.toMatch(/\b(fetch|XMLHttpRequest|WebSocket|sendBeacon)\b/);
  });
});
```

- [ ] **Step 2: Add the user-owned golden checker**

The script reads fixtures only when `WEBTOON_CUT_FIXTURE_ROOT` is set, writes all temporary results beneath a `mkdtemp` directory, and checks:

```text
진실의 방_001_009.jpg       => 5 cuts; last flag end_card
진실의 방_001_006.jpg       => 기본 처리에서 review_continuous 후보 기록; 선택 유형으로 재처리 후 기대 컷 수
진실의 방_001_006-07.jpg    => 기본 처리에서 review_continuous 후보 기록; 선택 유형으로 재처리 후 y ranges 0:2843, 2843:3754, 3754:8521
과학사 1.png                => cut count and reading order recorded by the current Python reference run
```

If the optional fixture is absent, print `SKIP: WEBTOON_CUT_FIXTURE_ROOT is not set` and exit 0. Do not copy the copyrighted samples into Git.

- [ ] **Step 3: Run unit isolation and local golden checks**

Run:

```bash
npm --prefix frontend exec vitest run src/features/webtoon-cut/networkIsolation.test.ts
WEBTOON_CUT_FIXTURE_ROOT='/Users/changkyuneun/Documents/New project/webtoon-split-test' node scripts/webtoon_cut_golden_check.mjs
```

Expected: unit test PASS; golden check PASS or an explicit path-specific SKIP for samples not present under the configured root.

- [ ] **Step 4: Manually verify the browser Network boundary in local mode**

Start the app with `npm start`, sign in, open `/studio/webtoon-cuts`, preserve the browser Network log, process one local JPEG, and assert that no request contains the source name, media MIME type, or media-sized request body. Confirm the output was written directly to the selected directory.

- [ ] **Step 5: Repeat the Network boundary against the ECS-hosted UI before release**

Use the deployed canary URL only after explicit deployment approval. Run the same JPEG and verify the ECS task logs, EFS, S3, and RDS contain no source or result artifact. This step is a release gate, not authorization to deploy.

- [ ] **Step 6: Commit regression tooling**

```bash
git add frontend/src/features/webtoon-cut/networkIsolation.test.ts scripts/webtoon_cut_golden_check.mjs .gitignore
git commit -m "test: lock webtoon cut privacy and golden behavior"
```

### Task 8: Update user and ECS documentation, then run the full gate

**Files:**
- Modify: `docs/dobedub-studio-user-manual.md`
- Modify: `docs/aws-ecs-deployment.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: completed feature behavior and exact browser support.
- Produces: user operation instructions and deployment privacy checks.

- [ ] **Step 1: Document the user workflow**

Add `이미지 컷 분할` as a top-level `LOCAL` menu above `GENERATE`, not under `GENERATE`, with: its future-I2V-input purpose, supported Chrome/Edge versions, directory permission, selectable input types, automatic/page/strip mode selection, no-gutter strong-transition handling, PNG-only generated images, output examples for normal/ZIP inputs, expected/completed/error/missing unit counts, unresolved-unit retry, route-change state retention, manifest-based reload recovery, flag meanings, and confirmation that source files are never modified or sent to the server.

- [ ] **Step 2: Document ECS invariants**

Add an `이미지 컷 분할 로컬 처리` section to `docs/aws-ecs-deployment.md` stating that the container serves code only, creates no cut API, receives no media, needs no EFS/S3/RDS capacity for this feature, and must keep all worker/PDF/ZIP assets in the immutable frontend build.

- [ ] **Step 3: Add a concise README capability entry**

State that both local and ECS deployments support browser-local cut processing on desktop Chrome/Edge and that no media transfer occurs.

- [ ] **Step 4: Run the complete repository gate**

Run: `./scripts/verify.sh`

Expected: backend compile PASS, all pytest tests PASS, webtoon cut Vitest suite PASS, frontend build PASS, and `git diff --check` PASS.

- [ ] **Step 5: Inspect the final branch diff and user-file preservation**

Run:

```bash
git status --short --branch
git diff --stat
git diff --check
```

Expected: branch remains `feat/webtoon-cut`; only files listed by this plan are changed by this feature; pre-existing untracked files remain unmodified.

- [ ] **Step 6: Commit documentation after explicit commit approval**

```bash
git add README.md docs/dobedub-studio-user-manual.md docs/aws-ecs-deployment.md
git commit -m "docs: explain local-only webtoon cut workflow"
```

## Self-Review Checklist

- [ ] Every requirement in `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md` maps to Tasks 1–8.
- [ ] Search this plan for unresolved placeholder terms and replace any occurrence before execution.
- [ ] Confirm `CutMode`, `DetectedCut`, `SourceUnit`, `SummaryRow`, `WebtoonCutManifest`, `WorkerRequest`, and `WorkerEvent` names are identical across tasks.
- [ ] Confirm normal file, PDF, directory, and ZIP output examples match the spec exactly.
- [ ] Confirm every generated cut, overlay, and contact sheet uses a `.png` filename and `image/png` encoding while input JPG/JPEG/PNG/WebP support remains intact.
- [ ] Confirm every discovered raster file and every `1..numPages` PDF page has exactly one ledger entry and at least one verified PNG or a visible terminal error.
- [ ] Confirm `completed` is impossible while any unit is pending, running, errored, missing from summary, or linked to a missing/invalid PNG.
- [ ] Confirm any `fullpage`, `review_continuous`, `thin`, or `many` unit receives `review_required` and produces `completed_with_review` rather than a silent plain completion.
- [ ] Confirm no-gutter strong horizontal transitions are evaluated even below `height = width * 3`, while the 84%-coverage inset-frame regression remains unsplit.
- [ ] Confirm screen unmount only removes its subscription, route return restores the active snapshot, and authenticated Provider cleanup safely pauses and releases local handles.
- [ ] Confirm both local and ECS paths use the same Worker and never invoke a media API.
- [ ] Confirm the plan adds no database migration and does not alter existing batch ZIP upload/download behavior.
