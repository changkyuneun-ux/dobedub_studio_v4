export const ENGINE_VERSION = "webtoon-cut-3";

export const MANIFEST_SCHEMA_VERSION = 1;

export const PDF_RENDER_SCALE = 300 / 72;

// pdf.js가 CID/Type0 폰트(예: 임베드된 한글 폰트)를 렌더링하려면 CMap과 표준 폰트 데이터가 필요하다.
// 이 값들이 없으면 해당 폰트 로딩이 조용히 실패하며(예외를 던지지 않음), 말풍선 텍스트만 빈 화면으로 렌더링된다.
// (public/pdfjs/{cmaps,standard_fonts}는 node_modules/pdfjs-dist에서 복사한 정적 리소스)
export const PDF_CMAP_URL = `${import.meta.env.BASE_URL}pdfjs/cmaps/`;
export const PDF_STANDARD_FONT_DATA_URL = `${import.meta.env.BASE_URL}pdfjs/standard_fonts/`;

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
