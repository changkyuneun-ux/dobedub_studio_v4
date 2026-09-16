import type { SUMMARY_COLUMNS } from "./constants";

export type CutMode = "auto" | "page" | "strip";

export type WebtoonCutSplitMode = "print" | "dark-webtoon";

export type DetectorMode = "grid" | "gutter" | "transition" | "dark_bg" | "fullpage" | "end_card";

export type InputKind = "image" | "pdf" | "directory" | "zip";

export type SourceKind = "image" | "pdf-page";

export type UnitStatus = "pending" | "running" | "completed" | "error";

export type JobStatus =
  | "idle"
  | "running"
  | "paused"
  | "completed"
  | "completed_with_review"
  | "completed_with_errors"
  | "failed";

export type ReviewFlag =
  | "review_required"
  | "fullpage"
  | "review_continuous"
  | "thin"
  | "many"
  | "missing_output"
  | "debug_error"
  | "error";

export type PixelRegion = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type DetectedCut = PixelRegion & {
  index: number;
  mode: DetectorMode;
  confidence: number;
  flags: string[];
};

export type SourceFingerprint = {
  name: string;
  size: number;
  lastModified: number;
};

export type SourceUnitDescriptor = {
  unitId: string;
  sourcePath: string;
  sourceKind: SourceKind;
  page: number | null;
};

export type SourceUnit = SourceUnitDescriptor & {
  image: ImageData;
  width: number;
  height: number;
};

export type GeneratedOutput = {
  path: string;
  width: number;
  height: number;
  x0?: number;
  y0?: number;
  x1?: number;
  y1?: number;
  mode?: DetectorMode;
  confidence?: number;
  flags?: string[];
};

export type RunnerProgressStage =
  | "inventory"
  | "resume-skip"
  | "render"
  | "detect"
  | "write"
  | "unit-complete"
  | "manifest";

export type RunnerProgressEvent = {
  stage: RunnerProgressStage;
  unitId?: string;
  sourcePath?: string;
  completed: number;
  total: number;
  generatedCuts: number;
  message?: string;
};

export type UnitLedgerEntry = SourceUnitDescriptor & {
  status: UnitStatus;
  attempts: number;
  flags: string[];
  outputs: GeneratedOutput[];
  errorCode?: string;
  error?: string;
};

export type SummaryColumn = (typeof SUMMARY_COLUMNS)[number];

export type SummaryRow = Record<SummaryColumn, string | number | null>;

export type CutJobOptions = {
  mode: CutMode;
  splitMode: WebtoonCutSplitMode;
  pdfScale: number;
  outputFormat: "png";
  pagePolicy: Readonly<{
    outerMarginRatio: number;
    minAreaRatio: number;
    maxDepth: number;
  }>;
  stripPolicy: Readonly<{
    foregroundFloor: number;
    chromaFloor: number;
    rowRatio: number;
    minGapPx: number;
    gapWidthRatio: number;
    paddingY: number;
  }>;
  transitionPolicy: Readonly<{
    analysisWidth: number;
    deltaFloor: number;
    minCoverage: number;
    minMedianJump: number;
    minLocalContrast: number;
    contrastWindow: number;
    minSegmentWidthRatio: number;
  }>;
};

export type SourceInputDescriptor = {
  inputId: string;
  kind: InputKind;
  relativePath: string;
  fingerprint: SourceFingerprint | null;
};

export type DiscoveredInput = {
  kind: Exclude<InputKind, "directory">;
  relativePath: string;
  fileName: string;
  extension: string;
  fingerprint?: SourceFingerprint;
  handle?: unknown;
};

export type ManifestTotals = {
  expectedUnitCount: number;
  completedUnitCount: number;
  errorUnitCount: number;
  reviewRequiredUnitCount: number;
  generatedCutCount: number;
  flags: Record<string, number>;
};

export type WebtoonCutManifest = {
  schemaVersion: number;
  engineVersion: string;
  jobId: string;
  status: JobStatus;
  inputKind: InputKind;
  inputName: string;
  outputRoot: string;
  expectedUnitCount: number;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  options: CutJobOptions;
  inputs: SourceInputDescriptor[];
  inventory: SourceUnitDescriptor[];
  ledger: UnitLedgerEntry[];
  generatedFiles: string[];
  totals: ManifestTotals;
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

export type CutJobRequest = {
  jobId: string;
  inputKind: InputKind;
  inputName: string;
  outputRoot: FileSystemDirectoryHandle;
  options: CutJobOptions;
};

export type WorkerRequest =
  | {
      type: "start";
      request: {
        jobId: string;
        inputKind: InputKind;
        inputName: string;
        splitMode?: WebtoonCutSplitMode;
        inputs: unknown;
        outputRoot: FileSystemDirectoryHandle;
      };
    }
  | { type: "pause"; jobId: string };

export type WorkerEvent =
  | ({ type: "progress"; jobId: string } & RunnerProgressEvent)
  | {
      type: "completed";
      jobId: string;
      outcome: "completed" | "completed_with_review" | "completed_with_errors";
      manifest: WebtoonCutManifest;
      reviewUnitIds: string[];
      unresolvedUnitIds: string[];
    }
  | { type: "paused"; jobId: string; manifest: WebtoonCutManifest }
  | { type: "failed"; jobId: string; code: string; message: string };
