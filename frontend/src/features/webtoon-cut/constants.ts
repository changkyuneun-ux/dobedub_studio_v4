export const ENGINE_VERSION = "webtoon-cut-3";

export const MANIFEST_SCHEMA_VERSION = 1;

export const PDF_RENDER_SCALE = 300 / 72;

export const SUPPORTED_IMAGE_EXTENSIONS = Object.freeze(["jpg", "jpeg", "png", "webp", "gif"] as const);

export const SUPPORTED_DOCUMENT_EXTENSIONS = Object.freeze(["pdf"] as const);

export const SUPPORTED_ARCHIVE_EXTENSIONS = Object.freeze(["zip"] as const);

export const SUPPORTED_INPUT_EXTENSIONS = Object.freeze([
  ...SUPPORTED_IMAGE_EXTENSIONS,
  ...SUPPORTED_DOCUMENT_EXTENSIONS,
  ...SUPPORTED_ARCHIVE_EXTENSIONS
] as const);

export const PAGE_POLICY = Object.freeze({
  outerMarginRatio: 0.03,
  minAreaRatio: 0.02,
  maxDepth: 8
});

export const STRIP_POLICY = Object.freeze({
  foregroundFloor: 245,
  chromaFloor: 8,
  rowRatio: 0.003,
  minGapPx: 100,
  gapWidthRatio: 0.06,
  paddingY: 15
});

export const TRANSITION_POLICY = Object.freeze({
  analysisWidth: 300,
  deltaFloor: 12,
  minCoverage: 0.95,
  minMedianJump: 40,
  minLocalContrast: 80,
  contrastWindow: 8,
  minSegmentWidthRatio: 0.30
});

export const ARCHIVE_LIMITS = Object.freeze({
  maxEntries: 10_000,
  maxInputs: 5_000,
  maxExpandedBytes: 4 * 1024 ** 3,
  maxEntryBytes: 500 * 1024 ** 2,
  maxCompressionRatio: 200
});

export const SUMMARY_COLUMNS = Object.freeze([
  "unit_id",
  "source_path",
  "page",
  "cut",
  "filename",
  "mode",
  "x0",
  "y0",
  "x1",
  "y1",
  "width",
  "height",
  "confidence",
  "flag",
  "elapsed_ms",
  "status",
  "error"
] as const);
