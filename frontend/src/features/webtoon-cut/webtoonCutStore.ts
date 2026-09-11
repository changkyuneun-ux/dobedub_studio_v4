import React, { useEffect, useSyncExternalStore } from "react";

export type WebtoonCutUnitStatus = "pending" | "processing" | "completed" | "review_required" | "unsupported" | "failed";
export type WebtoonCutUnitFlag = "ok" | "fullpage" | "continuous_sequence" | "unsupported" | "failed";
export type WebtoonCutReprocessMode = "strong-horizontal-transition";

export type WebtoonCutUnit = {
  id: string;
  fileName: string;
  sourcePath: string;
  outputDirName: string;
  width?: number;
  height?: number;
  status: WebtoonCutUnitStatus;
  flag: WebtoonCutUnitFlag;
  cutCount: number;
  message: string;
};

export type WebtoonCutSnapshot = {
  sessionOwnerId: string;
  jobId: string;
  inputName: string;
  workLocation: string;
  outputLocation: string;
  outputReady: boolean;
  status: "idle" | "ready" | "running" | "completed" | "completed_with_review" | "failed";
  notice: string;
  units: WebtoonCutUnit[];
  totalUnits: number;
  completedUnits: number;
  reviewUnits: number;
  failedUnits: number;
  generatedCuts: number;
  selectedReviewUnitId: string;
};

type SelectedInput = {
  id: string;
  file: File;
  sourcePath: string;
  outputDirName: string;
};

type CutBox = {
  index: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

const IMAGE_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "gif"]);
const SUPPORTED_EXTENSIONS = new Set([...IMAGE_EXTENSIONS, "pdf", "zip"]);
const WHITE_ROW_RATIO = 0.93;
const WHITE_PIXEL_THRESHOLD = 246;
const CONTENT_ROW_RATIO = 0.012;
const MIN_GUTTER_HEIGHT = 24;
const MIN_CUT_HEIGHT = 96;
const STRONG_TRANSITION_DELTA = 34;
const STRONG_COLOR_DELTA = 28;
export const FULL_WIDTH_TRANSITION_RATIO = 0.95;
export const MIN_STRONG_TRANSITION_CUT_HEIGHT = 240;

function createInitialSnapshot(sessionOwnerId = ""): WebtoonCutSnapshot {
  return {
    sessionOwnerId,
    jobId: "",
    inputName: "",
    workLocation: "",
    outputLocation: "",
    outputReady: false,
    status: "idle",
    notice: "",
    units: [],
    totalUnits: 0,
    completedUnits: 0,
    reviewUnits: 0,
    failedUnits: 0,
    generatedCuts: 0,
    selectedReviewUnitId: ""
  };
}

let snapshot = createInitialSnapshot();
let selectedInputs: SelectedInput[] = [];
let outputRootHandle: FileSystemDirectoryHandle | null = null;
let running = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function setSnapshot(update: Partial<WebtoonCutSnapshot>) {
  snapshot = { ...snapshot, ...update };
  emit();
}

function replaceUnit(unitId: string, update: Partial<WebtoonCutUnit>) {
  const units = snapshot.units.map((unit) => unit.id === unitId ? { ...unit, ...update } : unit);
  const completedUnits = units.filter((unit) => unit.status === "completed" || unit.status === "review_required").length;
  const reviewUnits = units.filter((unit) => unit.status === "review_required").length;
  const failedUnits = units.filter((unit) => unit.status === "failed" || unit.status === "unsupported").length;
  const generatedCuts = units.reduce((sum, unit) => sum + unit.cutCount, 0);
  snapshot = {
    ...snapshot,
    units,
    completedUnits,
    reviewUnits,
    failedUnits,
    generatedCuts,
    selectedReviewUnitId: snapshot.selectedReviewUnitId || units.find((unit) => unit.status === "review_required")?.id || ""
  };
  emit();
}

export const webtoonCutJobStore = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return snapshot;
  },
  initialize(sessionOwnerId: string) {
    if (snapshot.sessionOwnerId === sessionOwnerId) return;
    snapshot = createInitialSnapshot(sessionOwnerId);
    selectedInputs = [];
    outputRootHandle = null;
    running = false;
    emit();
  },
  disposeForSessionEnd(sessionOwnerId: string) {
    if (snapshot.sessionOwnerId !== sessionOwnerId) return;
    snapshot = createInitialSnapshot();
    selectedInputs = [];
    outputRootHandle = null;
    running = false;
    emit();
  },
  async selectDirectory(directoryHandle: FileSystemDirectoryHandle) {
    const files = await collectFilesFromDirectoryHandle(directoryHandle);
    selectedInputs = files.map((entry, index) => ({
      id: `${index + 1}-${entry.sourcePath}`,
      file: entry.file,
      sourcePath: entry.sourcePath,
      outputDirName: safeBaseName(entry.file.name)
    }));
    const outputName = `${safeFileName(directoryHandle.name)}_cuts`;
    outputRootHandle = await directoryHandle.getDirectoryHandle(outputName, { create: true });
    buildReadySnapshot({
      inputName: directoryHandle.name,
      workLocation: directoryHandle.name,
      outputLocation: `${directoryHandle.name}/${outputName}`,
      outputReady: true
    });
  },
  async selectFiles(files: File[]) {
    const supported = files.filter((file) => SUPPORTED_EXTENSIONS.has(fileExtension(file.name)));
    selectedInputs = supported.map((file, index) => ({
      id: `${index + 1}-${file.name}`,
      file,
      sourcePath: file.webkitRelativePath || file.name,
      outputDirName: safeBaseName(file.name)
    }));
    outputRootHandle = null;
    const inputName = supported.length === 1 ? safeBaseName(supported[0].name) : "selected_files";
    buildReadySnapshot({
      inputName,
      workLocation: "브라우저 선택 파일",
      outputLocation: `${inputName}_cuts`,
      outputReady: false,
      notice: "개별 파일 선택은 부모 폴더 쓰기 권한을 자동으로 얻을 수 없어, 작업 요청 시 출력 폴더 권한을 한 번 더 요청합니다."
    });
  },
  async selectDroppedItems(items: DataTransferItemList) {
    const handles = await Promise.all([...items].map((item) => item.getAsFileSystemHandle?.() || Promise.resolve(null)));
    const directoryHandle = handles.find((handle): handle is FileSystemDirectoryHandle => handle?.kind === "directory");
    if (directoryHandle) {
      await this.selectDirectory(directoryHandle);
      return;
    }
    const handleFiles = await Promise.all(handles.map((handle) => handleDroppedFileSystemHandle(handle)));
    const files = handleFiles.filter((file): file is File => Boolean(file));
    if (!files.length) {
      files.push(...await collectFilesFromDataTransferItems(items));
    }
    await this.selectFiles(files);
  },
  selectReviewUnit(unitId: string) {
    setSnapshot({ selectedReviewUnitId: unitId });
  },
  async processSelectedInputs() {
    if (!selectedInputs.length || running) return;
    running = true;
    try {
      if (!outputRootHandle) {
        const fallback = await window.showDirectoryPicker?.({ mode: "readwrite" });
        if (!fallback) {
          setSnapshot({ notice: "출력 폴더 권한을 얻을 수 없습니다.", status: "failed" });
          return;
        }
        outputRootHandle = await fallback.getDirectoryHandle(`${safeFileName(snapshot.inputName || "selected_files")}_cuts`, { create: true });
        setSnapshot({ outputReady: true, outputLocation: `${fallback.name}/${safeFileName(snapshot.inputName || "selected_files")}_cuts` });
      }
      setSnapshot({ status: "running", notice: "브라우저 로컬에서 컷 분할 중입니다. 원본은 서버로 전송하지 않습니다." });
      await ensureDirectory(outputRootHandle, "_debug");
      for (const input of selectedInputs) {
        await processInput(input, "default");
      }
      await writeSummaryFiles();
      const hasReview = snapshot.units.some((unit) => unit.status === "review_required");
      const hasFailed = snapshot.units.some((unit) => unit.status === "failed" || unit.status === "unsupported");
      setSnapshot({
        status: hasReview ? "completed_with_review" : hasFailed ? "completed_with_review" : "completed",
        notice: hasReview ? "컷 분할이 끝났습니다. 검수 필요 항목을 선택해 재처리 유형을 적용하세요." : "컷 분할이 끝났습니다."
      });
    } catch (error) {
      setSnapshot({ status: "failed", notice: error instanceof Error ? error.message : "컷 분할 중 오류가 발생했습니다." });
    } finally {
      running = false;
    }
  },
  async reprocessReviewUnit(unitId: string, mode: WebtoonCutReprocessMode) {
    if (!outputRootHandle || running) return;
    const input = selectedInputs.find((entry) => entry.id === unitId);
    if (!input) return;
    running = true;
    try {
      replaceUnit(unitId, { status: "processing", message: "수평 장면 전환 후보로 재처리 중입니다." });
      await processInput(input, mode);
      await writeSummaryFiles();
      setSnapshot({ status: "completed_with_review", notice: "선택 항목을 수평 장면 전환 기준으로 재처리했습니다." });
    } catch (error) {
      replaceUnit(unitId, { status: "failed", flag: "failed", message: error instanceof Error ? error.message : "재처리에 실패했습니다." });
    } finally {
      running = false;
    }
  }
};

export function WebtoonCutJobProvider({ sessionOwnerId, children }: { sessionOwnerId: string; children: React.ReactNode }) {
  useEffect(() => {
    webtoonCutJobStore.initialize(sessionOwnerId);
    return () => webtoonCutJobStore.disposeForSessionEnd(sessionOwnerId);
  }, [sessionOwnerId]);
  return React.createElement(React.Fragment, null, children);
}

export function useWebtoonCutJob() {
  return useSyncExternalStore(webtoonCutJobStore.subscribe, webtoonCutJobStore.getSnapshot, webtoonCutJobStore.getSnapshot);
}

function buildReadySnapshot({
  inputName,
  workLocation,
  outputLocation,
  outputReady,
  notice = ""
}: {
  inputName: string;
  workLocation: string;
  outputLocation: string;
  outputReady: boolean;
  notice?: string;
}) {
  const units: WebtoonCutUnit[] = selectedInputs.map((input) => ({
    id: input.id,
    fileName: input.file.name,
    sourcePath: input.sourcePath,
    outputDirName: input.outputDirName,
    status: IMAGE_EXTENSIONS.has(fileExtension(input.file.name)) ? "pending" : "unsupported",
    flag: IMAGE_EXTENSIONS.has(fileExtension(input.file.name)) ? "ok" : "unsupported",
    cutCount: 0,
    message: IMAGE_EXTENSIONS.has(fileExtension(input.file.name))
      ? "처리 대기"
      : "PDF/ZIP 렌더러는 후속 구현 대상입니다. 누락 방지를 위해 검수 필요 항목으로 기록합니다."
  }));
  snapshot = {
    ...createInitialSnapshot(snapshot.sessionOwnerId),
    jobId: `CUT-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${String(Date.now()).slice(-4)}`,
    inputName,
    workLocation,
    outputLocation,
    outputReady,
    status: selectedInputs.length ? "ready" : "idle",
    notice,
    units,
    totalUnits: units.length,
    reviewUnits: units.filter((unit) => unit.status === "unsupported").length,
    failedUnits: units.filter((unit) => unit.status === "unsupported").length,
    selectedReviewUnitId: units.find((unit) => unit.status === "unsupported")?.id || ""
  };
  emit();
}

async function processInput(input: SelectedInput, mode: "default" | WebtoonCutReprocessMode) {
  const extension = fileExtension(input.file.name);
  if (!IMAGE_EXTENSIONS.has(extension)) {
    replaceUnit(input.id, {
      status: "unsupported",
      flag: "unsupported",
      cutCount: 0,
      message: "현재 브라우저 로컬 엔진은 이미지 파일을 먼저 처리합니다. PDF/ZIP은 누락 항목으로 남겨 후속 처리합니다."
    });
    return;
  }

  replaceUnit(input.id, { status: "processing", message: "이미지를 분석 중입니다." });
  const bitmap = await createImageBitmap(input.file);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("Canvas 컨텍스트를 만들 수 없습니다.");
    context.drawImage(bitmap, 0, 0);
    const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
    const boxes = mode === "strong-horizontal-transition" && canvas.height > canvas.width * 3
      ? splitByStrongHorizontalTransitions(imageData, canvas.width, canvas.height)
      : splitByWhitespaceGutters(imageData, canvas.width, canvas.height);
    const finalBoxes = boxes.length ? boxes : [{ index: 1, x: 0, y: 0, width: canvas.width, height: canvas.height }];
    const unitDir = await ensureDirectory(outputRootHandle!, input.outputDirName);
    for (const box of finalBoxes) {
      const blob = await cropPng(canvas, box);
      await writeBlob(unitDir, `${input.outputDirName}-${String(box.index).padStart(2, "0")}.png`, blob);
    }
    await writeDebugOverlay(input, canvas, finalBoxes);
    const flag: WebtoonCutUnitFlag = finalBoxes.length === 1 && canvas.height > canvas.width * 3 ? "continuous_sequence" : finalBoxes.length === 1 ? "fullpage" : "ok";
    replaceUnit(input.id, {
      width: canvas.width,
      height: canvas.height,
      status: flag === "ok" ? "completed" : "review_required",
      flag,
      cutCount: finalBoxes.length,
      message: flag === "continuous_sequence"
        ? "긴 단일 결과입니다. 검수 화면에서 수평 장면 전환 재처리를 선택할 수 있습니다."
        : flag === "fullpage"
          ? "구분선을 찾지 못해 페이지 전체를 1컷 PNG로 저장했습니다."
          : `${finalBoxes.length}개 컷을 PNG로 저장했습니다.`
    });
  } finally {
    bitmap.close();
  }
}

function splitByWhitespaceGutters(imageData: ImageData, width: number, height: number): CutBox[] {
  const whiteRows = new Uint8Array(height);
  const contentRows = new Uint8Array(height);
  const data = imageData.data;
  const xStep = Math.max(1, Math.floor(width / 420));
  const samples = Math.ceil(width / xStep);
  for (let y = 0; y < height; y += 1) {
    let white = 0;
    let content = 0;
    const rowOffset = y * width * 4;
    for (let x = 0; x < width; x += xStep) {
      const offset = rowOffset + x * 4;
      const r = data[offset];
      const g = data[offset + 1];
      const b = data[offset + 2];
      if (r > WHITE_PIXEL_THRESHOLD && g > WHITE_PIXEL_THRESHOLD && b > WHITE_PIXEL_THRESHOLD) white += 1;
      if (r < 242 || g < 242 || b < 242) content += 1;
    }
    if (white / samples >= WHITE_ROW_RATIO) whiteRows[y] = 1;
    if (content / samples >= CONTENT_ROW_RATIO) contentRows[y] = 1;
  }
  const contentTop = firstRow(contentRows, 1);
  const contentBottom = lastRow(contentRows, 1);
  if (contentTop < 0 || contentBottom < 0) {
    return [{ index: 1, x: 0, y: 0, width, height }];
  }
  const boundaries: number[] = [];
  let y = contentTop;
  while (y <= contentBottom) {
    if (!whiteRows[y]) {
      y += 1;
      continue;
    }
    const start = y;
    while (y <= contentBottom && whiteRows[y]) y += 1;
    const end = y - 1;
    if (end - start + 1 >= MIN_GUTTER_HEIGHT) {
      const boundary = Math.floor((start + end) / 2);
      if (boundary - contentTop >= MIN_CUT_HEIGHT && contentBottom - boundary >= MIN_CUT_HEIGHT) {
        boundaries.push(boundary);
      }
    }
  }
  return boxesFromBoundaries(width, contentTop, contentBottom + 1, boundaries, MIN_CUT_HEIGHT);
}

function splitByStrongHorizontalTransitions(imageData: ImageData, width: number, height: number): CutBox[] {
  const data = imageData.data;
  const xStep = Math.max(1, Math.floor(width / 500));
  const samples = Math.ceil(width / xStep);
  const rawCandidates: number[] = [];
  for (let y = 1; y < height - 1; y += 1) {
    let changed = 0;
    for (let x = 0; x < width; x += xStep) {
      const upper = ((y - 1) * width + x) * 4;
      const lower = (y * width + x) * 4;
      const upperLum = luminance(data[upper], data[upper + 1], data[upper + 2]);
      const lowerLum = luminance(data[lower], data[lower + 1], data[lower + 2]);
      const colorDelta = Math.max(
        Math.abs(data[upper] - data[lower]),
        Math.abs(data[upper + 1] - data[lower + 1]),
        Math.abs(data[upper + 2] - data[lower + 2])
      );
      if (Math.abs(upperLum - lowerLum) >= STRONG_TRANSITION_DELTA || colorDelta >= STRONG_COLOR_DELTA) {
        changed += 1;
      }
    }
    if (changed / samples >= FULL_WIDTH_TRANSITION_RATIO) {
      rawCandidates.push(y);
    }
  }
  const compacted: number[] = [];
  for (const candidate of rawCandidates) {
    const previous = compacted[compacted.length - 1];
    if (previous === undefined || candidate - previous >= MIN_STRONG_TRANSITION_CUT_HEIGHT) {
      compacted.push(candidate);
    }
  }
  return boxesFromBoundaries(width, 0, height, compacted, MIN_STRONG_TRANSITION_CUT_HEIGHT);
}

function boxesFromBoundaries(width: number, top: number, bottom: number, boundaries: number[], minHeight: number): CutBox[] {
  const boxes: CutBox[] = [];
  let y = top;
  [...boundaries, bottom].forEach((boundary) => {
    const height = boundary - y;
    if (height >= minHeight) {
      boxes.push({ index: boxes.length + 1, x: 0, y, width, height });
      y = boundary;
    }
  });
  if (boxes.length && bottom - y >= minHeight) {
    boxes.push({ index: boxes.length + 1, x: 0, y, width, height: bottom - y });
  }
  return boxes;
}

function firstRow(rows: Uint8Array, value: number) {
  for (let index = 0; index < rows.length; index += 1) {
    if (rows[index] === value) return index;
  }
  return -1;
}

function lastRow(rows: Uint8Array, value: number) {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (rows[index] === value) return index;
  }
  return -1;
}

function luminance(r: number, g: number, b: number) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

async function cropPng(source: HTMLCanvasElement, box: CutBox): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = box.width;
  canvas.height = box.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("PNG crop 컨텍스트를 만들 수 없습니다.");
  context.drawImage(source, box.x, box.y, box.width, box.height, 0, 0, box.width, box.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("PNG 파일을 생성하지 못했습니다.");
  return blob;
}

async function writeDebugOverlay(input: SelectedInput, source: HTMLCanvasElement, boxes: CutBox[]) {
  const maxWidth = 420;
  const scale = Math.min(1, maxWidth / source.width);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(source.width * scale);
  canvas.height = Math.round(source.height * scale);
  const context = canvas.getContext("2d");
  if (!context) return;
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  context.strokeStyle = "#15966b";
  context.lineWidth = Math.max(2, Math.round(3 * scale));
  boxes.forEach((box) => {
    context.strokeRect(0, box.y * scale, canvas.width, box.height * scale);
  });
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (blob) {
    const debugDir = await ensureDirectory(outputRootHandle!, "_debug");
    await writeBlob(debugDir, `${input.outputDirName}.png`, blob);
  }
}

async function writeSummaryFiles() {
  if (!outputRootHandle) return;
  const summary = [
    "source_path,file_name,status,flag,width,height,cut_count,message",
    ...snapshot.units.map((unit) => [
      csvCell(unit.sourcePath),
      csvCell(unit.fileName),
      unit.status,
      unit.flag,
      unit.width || "",
      unit.height || "",
      unit.cutCount,
      csvCell(unit.message)
    ].join(","))
  ].join("\n");
  const manifest = {
    jobId: snapshot.jobId,
    inputName: snapshot.inputName,
    outputLocation: snapshot.outputLocation,
    createdAt: new Date().toISOString(),
    purpose: "future_i2v_input",
    outputFormat: "png",
    units: snapshot.units
  };
  await writeBlob(outputRootHandle, "summary.csv", new Blob([summary], { type: "text/csv;charset=utf-8" }));
  await writeBlob(outputRootHandle, "manifest.json", new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }));
}

function csvCell(value: string) {
  return `"${String(value).replace(/"/g, '""')}"`;
}

async function writeBlob(directory: FileSystemDirectoryHandle, name: string, blob: Blob) {
  const handle = await directory.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await writable.write(blob);
  await writable.close();
}

async function ensureDirectory(root: FileSystemDirectoryHandle, name: string) {
  return root.getDirectoryHandle(safeFileName(name), { create: true });
}

async function collectFilesFromDirectoryHandle(directory: FileSystemDirectoryHandle, prefix = directory.name): Promise<Array<{ file: File; sourcePath: string }>> {
  const files: Array<{ file: File; sourcePath: string }> = [];
  for await (const handle of directory.values()) {
    if (handle.kind === "file") {
      const file = await (handle as FileSystemFileHandle).getFile();
      if (SUPPORTED_EXTENSIONS.has(fileExtension(file.name))) {
        files.push({ file, sourcePath: `${prefix}/${file.name}` });
      }
    } else if (handle.kind === "directory") {
      files.push(...await collectFilesFromDirectoryHandle(handle as FileSystemDirectoryHandle, `${prefix}/${handle.name}`));
    }
  }
  return files.sort((left, right) => left.sourcePath.localeCompare(right.sourcePath, "ko"));
}

async function collectFilesFromDataTransferItems(items: DataTransferItemList): Promise<File[]> {
  const files: File[] = [];
  for (const item of [...items]) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (file) files.push(file);
  }
  return files;
}

async function handleDroppedFileSystemHandle(handle: FileSystemHandle | null): Promise<File | null> {
  if (!handle || handle.kind !== "file") return null;
  const file = await (handle as FileSystemFileHandle).getFile();
  return SUPPORTED_EXTENSIONS.has(fileExtension(file.name)) ? file : null;
}

function fileExtension(name: string) {
  return name.split(".").pop()?.toLowerCase() || "";
}

function safeBaseName(name: string) {
  return safeFileName(name.replace(/\.[^.]+$/, "")) || "source";
}

function safeFileName(value: string) {
  return value.trim().replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, " ");
}
