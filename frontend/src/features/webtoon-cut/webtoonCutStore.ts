import { createElement, Fragment, useEffect, useSyncExternalStore, type ReactNode } from "react";
import { ENGINE_VERSION, MANIFEST_SCHEMA_VERSION, PAGE_POLICY, PDF_RENDER_SCALE, STRIP_POLICY, TRANSITION_POLICY } from "./constants";
import { discoverInputs, type FilePort } from "./filesystem";
import { classifySourceName, sourceUnitId, type SourceInputItem } from "./inputSources";
import { readExistingManifest, runWebtoonCutJob, type RunnerJobRequest, type RunnerPorts } from "./runner";
import { clearPersistedInputs, hasHandlePermission, loadPersistedWebtoonCutSession, persistInputDirectoryHandle, persistInputFileHandles, persistWorkspaceHandle } from "./persistence";
import { serializeSummary } from "./artifacts";
import type { GeneratedOutput, RunnerProgressEvent, SummaryRow, UnitLedgerEntry, WebtoonCutManifest, WorkerEvent } from "./types";

export type WebtoonCutUnitStatus = "pending" | "processing" | "completed" | "review_required" | "unsupported" | "failed";
export type WebtoonCutUnitFlag = "ok" | "fullpage" | "continuous_sequence" | "unsupported" | "failed";
export type WebtoonCutReprocessMode = "strong-horizontal-transition";

export type WebtoonCutUnit = {
  id: string;
  fileName: string;
  sourcePath: string;
  outputDirName: string;
  outputs: WebtoonCutOutput[];
  width?: number;
  height?: number;
  status: WebtoonCutUnitStatus;
  flag: WebtoonCutUnitFlag;
  cutCount: number;
  message: string;
};

export type WebtoonCutOutput = {
  path: string;
  width?: number;
  height?: number;
  x0?: number;
  y0?: number;
  x1?: number;
  y1?: number;
  mode?: string;
  confidence?: number;
  flags?: string[];
  previewUrl?: string;
};

export type WebtoonCutSnapshot = {
  sessionOwnerId: string;
  jobId: string;
  inputName: string;
  /** 화면 표시용 입력 라벨: 폴더명 또는 첫 파일명(확장자 포함) + "외 n개" */
  inputLabel: string;
  /** 현재 처리 중인 원본(상대 경로). 진행 중 작업 카드에 job id 대신 표시 */
  currentSourcePath: string;
  workLocation: string;
  outputLocation: string;
  outputReady: boolean;
  defaultWorkspaceReady: boolean;
  defaultWorkspaceName: string;
  status: "idle" | "ready" | "running" | "paused" | "completed" | "completed_with_review" | "failed";
  notice: string;
  units: WebtoonCutUnit[];
  totalUnits: number;
  completedUnits: number;
  reviewUnits: number;
  failedUnits: number;
  generatedCuts: number;
  selectedReviewUnitId: string;
  selectedReviewOutputPath: string;
};

type SelectedInput = {
  id: string;
  file: File;
  sourcePath: string;
  outputDirName: string;
  sourceItem: SourceInputItem;
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
const DISALLOWED_WORK_FOLDER_NAMES = new Set([
  "",
  "/",
  "Applications",
  "Library",
  "System",
  "Users",
  "Volumes",
  "bin",
  "dev",
  "etc",
  "opt",
  "private",
  "sbin",
  "tmp",
  "usr",
  "var"
]);

let defaultWorkspaceHandle: FileSystemDirectoryHandle | null = null;

function createInitialSnapshot(sessionOwnerId = ""): WebtoonCutSnapshot {
  return {
    sessionOwnerId,
    jobId: "",
    inputName: "",
    inputLabel: "",
    currentSourcePath: "",
    workLocation: "",
    outputLocation: "",
    outputReady: false,
    defaultWorkspaceReady: Boolean(defaultWorkspaceHandle),
    defaultWorkspaceName: defaultWorkspaceHandle?.name || "",
    status: "idle",
    notice: "",
    units: [],
    totalUnits: 0,
    completedUnits: 0,
    reviewUnits: 0,
    failedUnits: 0,
    generatedCuts: 0,
    selectedReviewUnitId: "",
    selectedReviewOutputPath: ""
  };
}

let snapshot = createInitialSnapshot();
let selectedInputs: SelectedInput[] = [];
let outputRootHandle: FileSystemDirectoryHandle | null = null;
let running = false;
let activeAbortController: AbortController | null = null;
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
    releasePreviewUrls(snapshot.units);
    defaultWorkspaceHandle = null;
    snapshot = createInitialSnapshot(sessionOwnerId);
    selectedInputs = [];
    outputRootHandle = null;
    running = false;
    activeAbortController = null;
    emit();
  },
  disposeForSessionEnd(sessionOwnerId: string) {
    if (snapshot.sessionOwnerId !== sessionOwnerId) return;
    releasePreviewUrls(snapshot.units);
    defaultWorkspaceHandle = null;
    snapshot = createInitialSnapshot();
    selectedInputs = [];
    outputRootHandle = null;
    running = false;
    activeAbortController?.abort(new DOMException("화면 세션 종료", "AbortError"));
    activeAbortController = null;
    emit();
  },
  async selectDirectory(directoryHandle: FileSystemDirectoryHandle) {
    await persistInputDirectoryHandle(directoryHandle);
    const discovered = await discoverInputs(directoryHandle);
    const files = await Promise.all(discovered.map(async (entry) => {
      const handle = entry.handle as FilePort | undefined;
      const file = handle ? await handle.getFile() : new File([], entry.fileName);
      return { entry, file };
    }));
    selectedInputs = files.map(({ entry, file }, index) => ({
      id: `${index + 1}-${entry.relativePath}`,
      file,
      sourcePath: entry.relativePath,
      outputDirName: safeBaseName(entry.fileName),
      sourceItem: { ...entry, file }
    }));
    const outputName = `${safeFileName(directoryHandle.name)}_cuts`;
    const output = await prepareOutputDirectory(outputName);
    buildReadySnapshot({
      inputName: directoryHandle.name,
      inputLabel: inputLabelFor(selectedInputs.map((input) => input.file.name), directoryHandle.name),
      workLocation: directoryHandle.name,
      outputLocation: output.outputLocation,
      outputReady: output.outputReady,
      notice: selectedInputs.length
        ? output.notice
        : `'${directoryHandle.name}' 폴더에 지원 파일(JPG · PNG · WEBP · GIF · PDF · ZIP)이 없습니다.`
    });
  },
  async selectFiles(files: File[]) {
    await selectFilesInternal(files, false);
  },
  async selectFileHandles(fileHandles: FileSystemFileHandle[]) {
    await persistInputFileHandles(fileHandles);
    const files = await Promise.all(fileHandles.map((handle) => handle.getFile()));
    await selectFilesInternal(files, true);
  },
  async connectDefaultWorkspace(directoryHandle: FileSystemDirectoryHandle) {
    if (DISALLOWED_WORK_FOLDER_NAMES.has(directoryHandle.name)) {
      setSnapshot({
        defaultWorkspaceReady: Boolean(defaultWorkspaceHandle),
        defaultWorkspaceName: defaultWorkspaceHandle?.name || "",
        outputReady: Boolean(outputRootHandle),
        notice: "시스템 폴더 또는 상위 기본 폴더는 작업 폴더로 지정할 수 없습니다. 사용자가 만든 별도 작업 폴더를 선택하세요."
      });
      return;
    }

    defaultWorkspaceHandle = directoryHandle;
    await persistWorkspaceHandle(directoryHandle);
    const update: Partial<WebtoonCutSnapshot> = {
      defaultWorkspaceReady: true,
      defaultWorkspaceName: directoryHandle.name,
      notice: ""
    };

    if (selectedInputs.length && snapshot.inputName) {
      const outputName = `${safeFileName(snapshot.inputName)}_cuts`;
      outputRootHandle = await defaultWorkspaceHandle.getDirectoryHandle(outputName, { create: true });
      update.outputReady = true;
      update.outputLocation = `${defaultWorkspaceHandle.name}/${outputName}`;
      update.notice = "";
    }

    setSnapshot(update);
  },
  async restorePersistedSession() {
    const persisted = await loadPersistedWebtoonCutSession();
    if (!persisted?.workspaceHandle) return;
    const workspaceGranted = await hasHandlePermission(persisted.workspaceHandle, "readwrite");
    if (!workspaceGranted) {
      setSnapshot({
        defaultWorkspaceReady: false,
        outputReady: false,
        notice: "저장된 작업 폴더 권한이 만료되었습니다. 작업 폴더를 다시 연결하세요."
      });
      return;
    }
    defaultWorkspaceHandle = persisted.workspaceHandle;
    setSnapshot({
      defaultWorkspaceReady: true,
      defaultWorkspaceName: persisted.workspaceHandle.name,
      notice: "저장된 작업 폴더를 복원했습니다."
    });
    if (persisted.inputMode === "directory" && persisted.inputDirectoryHandle) {
      const inputGranted = await hasHandlePermission(persisted.inputDirectoryHandle, "read");
      if (!inputGranted) {
        setSnapshot({ notice: "이전 입력 폴더 권한이 만료되었습니다. 입력 폴더를 다시 선택하면 manifest 기준으로 재개됩니다." });
        return;
      }
      await this.selectDirectory(persisted.inputDirectoryHandle);
      await finishRestoreOrClearIfNoProgress("이전 폴더 입력을 복원했습니다. 작업 요청을 누르면 manifest 기준으로 이어서 처리합니다.");
      return;
    }
    if (persisted.inputMode === "files" && persisted.fileHandles?.length) {
      const granted = await Promise.all(persisted.fileHandles.map((handle) => hasHandlePermission(handle, "read")));
      if (!granted.every(Boolean)) {
        setSnapshot({ notice: "이전 입력 파일 권한이 만료되었습니다. 입력 파일을 다시 선택하면 manifest 기준으로 재개됩니다." });
        return;
      }
      await this.selectFileHandles(persisted.fileHandles);
      await finishRestoreOrClearIfNoProgress("이전 파일 입력을 복원했습니다. 작업 요청을 누르면 manifest 기준으로 이어서 처리합니다.");
    }
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
  /** 화면의 파일/폴더 선택 핸들러가 삼키던 오류를 사용자에게 알린다 */
  reportInputError(error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    setSnapshot({ notice: `입력 선택에 실패했습니다: ${message}` });
  },
  selectReviewUnit(unitId: string) {
    const unit = snapshot.units.find((entry) => entry.id === unitId);
    setSnapshot({
      selectedReviewUnitId: unitId,
      selectedReviewOutputPath: unit ? reviewTargetOutputs(unit)[0]?.path || "" : ""
    });
  },
  selectReviewOutput(path: string) {
    setSnapshot({ selectedReviewOutputPath: path });
  },
  async processSelectedInputs() {
    if (!selectedInputs.length || running) return;
    running = true;
    const controller = new AbortController();
    activeAbortController = controller;
    try {
      if (!outputRootHandle) {
        setSnapshot({
          status: "ready",
          notice: "작업 폴더가 연결되지 않아 작업을 시작할 수 없습니다. 시스템 폴더가 아닌 별도 작업 폴더를 먼저 연결하세요."
        });
        return;
      }
      setSnapshot({ status: "running", notice: "브라우저 로컬에서 컷 분할 중입니다. 원본은 서버로 전송하지 않습니다." });
      await ensureDirectory(outputRootHandle, "_debug");
      const request: RunnerJobRequest = {
        jobId: snapshot.jobId,
        inputKind: selectedInputs.length === 1 ? selectedInputs[0].sourceItem.kind : "directory",
        inputName: snapshot.inputName || "selected_files",
        inputs: { inputs: selectedInputs.map((input) => input.sourceItem) }
      };
      const manifest = await runJobWithWorkerFallback(request, {
        output: outputRootHandle,
        onProgress: ({ completed, total, generatedCuts, stage, message, sourcePath }) => {
          setSnapshot({
            completedUnits: completed,
            totalUnits: total,
            generatedCuts,
            currentSourcePath: stage === "manifest" ? "" : (sourcePath || snapshot.currentSourcePath),
            notice: message || stageNotice(stage)
          });
        }
      }, controller.signal);
      if (manifest.status === "paused") {
        // 2026-09-13: 사용자 요청 - 중단하면 입력 영역을 초기화한다(이전 폴더/파일 선택과
        // 영속 핸들을 지워 재진입 시 복원되지 않게). 출력 폴더의 manifest는 그대로 남아
        // 같은 입력을 다시 선택해 작업 요청하면 이어서 처리된다.
        await resetInputsAfterCancel();
        return;
      }
      releasePreviewUrls(snapshot.units);
      const units = await unitsFromManifest(manifest);
      snapshot = {
        ...snapshot,
        currentSourcePath: "",
        units,
        completedUnits: units.length,
        reviewUnits: units.filter((unit) => unit.status === "review_required").length,
        failedUnits: 0,
        generatedCuts: units.reduce((sum, unit) => sum + unit.cutCount, 0),
        totalUnits: manifest.expectedUnitCount,
        selectedReviewUnitId: units.find((unit) => unit.status === "review_required")?.id || "",
        selectedReviewOutputPath: firstReviewOutputPath(units)
      };
      const hasReview = units.some((unit) => unit.status === "review_required");
      const hasFailed = false;
      setSnapshot({
        status: hasReview ? "completed_with_review" : hasFailed ? "completed_with_review" : "completed",
        notice: hasReview ? "컷 분할이 끝났습니다. 검수 필요 항목을 선택해 재처리 유형을 적용하세요." : "컷 분할이 끝났습니다."
      });
    } catch (error) {
      setSnapshot({ status: "failed", currentSourcePath: "", notice: error instanceof Error ? error.message : "컷 분할 중 오류가 발생했습니다." });
    } finally {
      running = false;
      if (activeAbortController === controller) {
        activeAbortController = null;
      }
    }
  },
  cancelRunningJob() {
    if (!running || !activeAbortController || activeAbortController.signal.aborted) return;
    activeAbortController.abort(new DOMException("중단 요청", "AbortError"));
    setSnapshot({ notice: "중단 요청을 보냈습니다. 중단 시점까지 완료된 결과를 저장 중입니다." });
  },
  async reprocessReviewUnit(unitId: string, mode: WebtoonCutReprocessMode, outputPath?: string) {
    if (!outputRootHandle || running) return;
    running = true;
    try {
      const unit = snapshot.units.find((entry) => entry.id === unitId);
      const target = unit ? resolveReviewTargetOutput(unit, outputPath || snapshot.selectedReviewOutputPath) : undefined;
      if (!unit || !target) {
        setSnapshot({ notice: "재처리할 컷을 먼저 선택하세요." });
        return;
      }
      if (!target.flags?.includes("review_continuous")) {
        setSnapshot({ notice: "선택한 컷은 수평 장면 전환 재처리 대상이 아닙니다." });
        return;
      }
      setSnapshot({ selectedReviewOutputPath: target.path, notice: "선택한 컷을 재처리 중입니다." });
      replaceUnit(unitId, { status: "processing", message: "선택한 컷을 수평 장면 전환 후보로 재처리 중입니다." });
      await processReviewOutput(unit, target, mode);
      await writeSummaryFiles();
      setSnapshot({ status: "completed_with_review", notice: "선택한 컷을 수평 장면 전환 기준으로 재처리했습니다." });
    } catch (error) {
      replaceUnit(unitId, { status: "failed", flag: "failed", message: error instanceof Error ? error.message : "재처리에 실패했습니다." });
    } finally {
      running = false;
    }
  },
  /**
   * 2026-09-14: 사용자 요청 - 새로고침뿐 아니라 "다른 화면으로 이동했다가 다시 진입"하는
   * 경우에도 "진행 중 작업이 없으면 초기화"가 동일하게 적용되어야 한다. 새로고침과 달리
   * 화면 전환은 모듈 상태(snapshot)를 그대로 유지하므로 disk manifest를 다시 읽을 필요는
   * 없고, 지금 이 세션에서 실제로 실행 중인지(running)와 마지막 작업이 종료 상태인지만
   * 보면 된다:
   *   - running(메인 작업 실행 또는 검수 재처리 진행 중)이면 그대로 둔다 - 화면을 벗어나도
   *     작업은 계속 진행되므로 다시 들어왔을 때 진행 상황을 보여줘야 한다.
   *   - status가 "idle"/"ready"(아직 실행한 적 없는 입력 선택)이면 그대로 둔다 - 이건
   *     "이전 작업 정보"가 아니라 사용자가 방금 선택해 둔, 아직 실행하지 않은 입력이다.
   *   - status가 "completed"/"completed_with_review"/"failed"(이미 끝난 이전 작업)이면
   *     화면 재진입 시점에 조용히 초기 상태로 되돌린다.
   */
  resetIfNoActiveWork() {
    if (running) return;
    if (snapshot.status !== "completed" && snapshot.status !== "completed_with_review" && snapshot.status !== "failed") return;
    void clearSessionToInitial();
  }
};

/**
 * 2026-09-14: 사용자 요청 - "진행 중 작업"이 실제로 없으면 새로고침 후 복원하지 않고
 * 입력 대기 상태로 되돌린다. 새로고침이 일어나는 순간 실행 중이던 워커/네트워크 상태는
 * 전부 사라지므로, F5 직후에는 진짜 "실행 중" 작업이 존재할 수 없다 — 유일하게 재개할
 * 가치가 있는 경우는 이전 실행이 중간에 중단되어 아직 끝나지 않은 경우뿐이다.
 *
 * 2026-09-14 수정: 최초 구현은 "ledger에 completed 단위가 하나라도 있으면 재개 대상"으로
 * 판정했는데, 이는 정상적으로 끝까지 완료된 작업의 manifest도 그대로 만족시켜 버그를
 * 재현시켰다(수영복.zip 6/6 완료 후 새로고침해도 "0/1 · 0%" 카드가 다시 나타남).
 * runner.ts의 finalizeManifest()를 보면 manifest.status는 다음 세 값 중 하나로만 기록된다:
 *   - "paused": 취소 시그널 등으로 루프가 끝까지 돌지 못하고 중간에 끊긴 경우(=진짜 미완료)
 *   - "completed" / "completed_with_review": 루프가 끝까지 정상적으로 돌아 작업이 끝난 경우
 * 따라서 "재개할 가치가 있는 진행 중 작업"인지는 ledger의 completed 개수가 아니라
 * manifest.status가 "paused"인지로만 판단해야 한다. completed/completed_with_review는
 * 이미 끝난 작업이므로 복원 대상이 아니며, 새로고침 시 조용히 초기화되어야 한다.
 */
export async function hasResumableProgress(root: FileSystemDirectoryHandle): Promise<boolean> {
  const manifest = await readExistingManifest(root);
  return manifest?.status === "paused";
}

async function finishRestoreOrClearIfNoProgress(resumeNotice: string) {
  const resumable = outputRootHandle ? await hasResumableProgress(outputRootHandle) : false;
  if (resumable) {
    setSnapshot({ notice: resumeNotice });
    return;
  }
  await clearSessionToInitial();
}

/**
 * finishRestoreOrClearIfNoProgress()(새로고침 직후 복원 여부 판단)와
 * resetIfNoActiveWork()(화면 재진입 시 종료된 이전 작업 정리)가 공유하는 초기화 로직.
 * 영속 저장된 입력 핸들(IndexedDB)까지 함께 지운다 - 이미 끝난 작업으로 판정된 뒤에는
 * 그 입력을 다시 이어서 처리할 이유가 없기 때문이다.
 */
async function clearSessionToInitial() {
  await clearPersistedInputs();
  releasePreviewUrls(snapshot.units);
  selectedInputs = [];
  outputRootHandle = null;
  // createInitialSnapshot()는 defaultWorkspaceHandle 모듈 변수를 그대로 반영하므로
  // 위에서 복원해둔 작업 폴더 연결(defaultWorkspaceReady/Name)은 그대로 유지된다.
  snapshot = { ...createInitialSnapshot(snapshot.sessionOwnerId), notice: "" };
  emit();
}

async function resetInputsAfterCancel() {
  await clearPersistedInputs();
  releasePreviewUrls(snapshot.units);
  selectedInputs = [];
  outputRootHandle = null;
  snapshot = {
    ...createInitialSnapshot(snapshot.sessionOwnerId),
    notice: "작업을 중단했습니다. 중단 시점까지 저장된 결과는 출력 폴더에 남아 있습니다. 입력을 다시 선택하면 manifest 기준으로 이어서 처리합니다."
  };
  emit();
}

function inputLabelFor(fileNames: string[], directoryName: string): string {
  const [first, ...rest] = fileNames;
  if (!first) return directoryName;
  return rest.length ? `${first} 외 ${rest.length}개` : first;
}

async function selectFilesInternal(files: File[], preservePersistedInput: boolean) {
  if (!preservePersistedInput) {
    await clearPersistedInputs();
  }
  const supported = files.filter((file) => SUPPORTED_EXTENSIONS.has(fileExtension(file.name)));
  selectedInputs = supported.map((file, index) => ({
    id: `${index + 1}-${file.name}`,
    file,
    sourcePath: file.webkitRelativePath || file.name,
    outputDirName: safeBaseName(file.name),
    sourceItem: {
      kind: classifySourceName(file.name) || "image",
      relativePath: file.webkitRelativePath || file.name,
      fileName: file.name,
      extension: fileExtension(file.name),
      fingerprint: {
        name: file.name,
        size: file.size,
        lastModified: file.lastModified
      },
      file
    }
  }));
  const inputName = supported.length === 1 ? safeBaseName(supported[0].name) : "selected_files";
  const outputName = `${inputName}_cuts`;
  const output = await prepareOutputDirectory(outputName);
  buildReadySnapshot({
    inputName,
    inputLabel: inputLabelFor(supported.map((file) => file.name), ""),
    workLocation: "브라우저 선택 파일",
    outputLocation: output.outputLocation,
    outputReady: output.outputReady,
    notice: supported.length
      ? output.notice
      : `선택한 ${files.length}개 파일 중 지원 형식(JPG · PNG · WEBP · GIF · PDF · ZIP)이 없습니다.`
  });
}

export function WebtoonCutJobProvider({ sessionOwnerId, children }: { sessionOwnerId: string; children: ReactNode }) {
  useEffect(() => {
    webtoonCutJobStore.initialize(sessionOwnerId);
    void webtoonCutJobStore.restorePersistedSession();
    return () => webtoonCutJobStore.disposeForSessionEnd(sessionOwnerId);
  }, [sessionOwnerId]);
  return createElement(Fragment, null, children);
}

export function useWebtoonCutJob() {
  return useSyncExternalStore(webtoonCutJobStore.subscribe, webtoonCutJobStore.getSnapshot, webtoonCutJobStore.getSnapshot);
}

async function prepareOutputDirectory(outputName: string): Promise<{ outputLocation: string; outputReady: boolean; notice: string }> {
  const safeOutputName = safeFileName(outputName);
  if (!defaultWorkspaceHandle) {
      outputRootHandle = null;
    return {
      outputLocation: `작업 폴더/${safeOutputName}`,
      outputReady: false,
      notice: "시스템 폴더가 아닌 별도 작업 폴더를 연결해야 작업 요청을 시작할 수 있습니다."
    };
  }

  outputRootHandle = await defaultWorkspaceHandle.getDirectoryHandle(safeOutputName, { create: true });
  return {
    outputLocation: `${defaultWorkspaceHandle.name}/${safeOutputName}`,
    outputReady: true,
    notice: ""
  };
}

function buildReadySnapshot({
  inputName,
  inputLabel,
  workLocation,
  outputLocation,
  outputReady,
  notice = ""
}: {
  inputName: string;
  inputLabel: string;
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
    outputs: [],
    status: "pending",
    flag: "ok",
    cutCount: 0,
    message: "처리 대기"
  }));
  releasePreviewUrls(snapshot.units);
  snapshot = {
    ...createInitialSnapshot(snapshot.sessionOwnerId),
    jobId: `CUT-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${String(Date.now()).slice(-4)}`,
    inputName,
    inputLabel,
    workLocation,
    outputLocation,
    outputReady,
    status: selectedInputs.length ? "ready" : "idle",
    notice,
    units,
    totalUnits: units.length,
    reviewUnits: 0,
    failedUnits: 0,
    selectedReviewUnitId: "",
    selectedReviewOutputPath: ""
  };
  emit();
}

async function unitsFromManifest(manifest: WebtoonCutManifest): Promise<WebtoonCutUnit[]> {
  return Promise.all(manifest.ledger.map(async (unit) => ({
    id: unit.unitId,
    fileName: unit.sourcePath.split("/").pop() || unit.sourcePath,
    sourcePath: unit.page ? `${unit.sourcePath}#${String(unit.page).padStart(3, "0")}` : unit.sourcePath,
    outputDirName: safeBaseName(unit.sourcePath),
    outputs: await loadOutputPreviews(unit.outputs),
    width: unit.outputs[0]?.width,
    height: unit.outputs[0]?.height,
    status: unit.flags.includes("review_required") ? "review_required" as const : "completed" as const,
    flag: unit.flags.includes("review_continuous") ? "continuous_sequence" as const : unit.flags.includes("fullpage") ? "fullpage" as const : "ok" as const,
    cutCount: unit.outputs.length,
    message: unit.flags.includes("review_required") ? "검수 필요 플래그가 있는 결과입니다." : `${unit.outputs.length}개 컷을 PNG로 저장했습니다.`
  })));
}

async function runJobWithWorkerFallback(request: RunnerJobRequest, ports: RunnerPorts, signal: AbortSignal): Promise<WebtoonCutManifest> {
  if (typeof Worker === "undefined" || typeof window === "undefined" || !canRunWebtoonCutInWorker(request)) {
    return runWebtoonCutJob(request, ports, signal);
  }

  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    let settled = false;

    function finish(callback: () => void) {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", abort);
      worker.terminate();
      callback();
    }

    function abort() {
      worker.postMessage({ type: "pause", jobId: request.jobId });
    }

    signal.addEventListener("abort", abort, { once: true });
    worker.onmessage = (event: MessageEvent<WorkerEvent>) => {
      const message = event.data;
      if (message.type === "progress") {
        ports.onProgress?.(message as RunnerProgressEvent);
        return;
      }
      if (message.type === "completed") {
        finish(() => resolve(message.manifest));
        return;
      }
      if (message.type === "paused") {
        finish(() => resolve(message.manifest));
        return;
      }
      if (message.type === "failed") {
        finish(() => reject(new Error(message.message)));
      }
    };
    worker.onerror = (event) => {
      finish(() => reject(new Error(event.message || "컷 분할 Worker 오류가 발생했습니다.")));
    };
    worker.postMessage({
      type: "start",
      request: {
        ...request,
        outputRoot: ports.output
      }
    });
    if (signal.aborted) abort();
  });
}

export function canRunWebtoonCutInWorker(request: Pick<RunnerJobRequest, "inputs">): boolean {
  const inputs = Array.isArray(request.inputs) ? request.inputs : request.inputs.inputs;
  return inputs.every((input) => sourceInputCanRunInWorker(input));
}

function sourceInputCanRunInWorker(input: SourceInputItem): boolean {
  const kind = classifySourceName(input.relativePath) || input.kind;
  if (kind === "image") return true;
  if (kind === "zip" && input.archiveEntries) {
    return input.archiveEntries.every((entry) => sourceInputCanRunInWorker(entry));
  }
  return false;
}

async function processInput(input: SelectedInput, mode: "default" | WebtoonCutReprocessMode, unitId = input.id) {
  const extension = fileExtension(input.file.name);
  if (!IMAGE_EXTENSIONS.has(extension)) {
    replaceUnit(unitId, {
      status: "unsupported",
      flag: "unsupported",
      cutCount: 0,
      message: "현재 브라우저 로컬 엔진은 이미지 파일을 먼저 처리합니다. PDF/ZIP은 누락 항목으로 남겨 후속 처리합니다."
    });
    return;
  }

  replaceUnit(unitId, { status: "processing", message: "이미지를 분석 중입니다." });
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
    const outputs: WebtoonCutOutput[] = [];
    for (const box of finalBoxes) {
      const blob = await cropPng(canvas, box);
      const fileName = `${input.outputDirName}-${String(box.index).padStart(2, "0")}.png`;
      await writeBlob(unitDir, fileName, blob);
      outputs.push({
        path: `${input.outputDirName}/${fileName}`,
        width: box.width,
        height: box.height
      });
    }
    await writeDebugOverlay(input, canvas, finalBoxes);
    const flag: WebtoonCutUnitFlag = finalBoxes.length === 1 && canvas.height > canvas.width * 3 ? "continuous_sequence" : finalBoxes.length === 1 ? "fullpage" : "ok";
    replaceUnit(unitId, {
      width: canvas.width,
      height: canvas.height,
      outputs: await loadOutputPreviews(outputs),
      status: flag === "continuous_sequence" ? "review_required" : "completed",
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

export function findSelectedInputIndexForUnitId(inputs: Array<Pick<SelectedInput, "sourcePath"> & { sourceItem?: SourceInputItem }>, unitId: string) {
  return inputs.findIndex((input) => {
    const relativePath = input.sourceItem?.relativePath || input.sourcePath;
    return sourceUnitId("image", relativePath, null) === unitId;
  });
}

export function reviewTargetOutputs(unit: WebtoonCutUnit) {
  return unit.outputs.filter((output) => output.flags?.includes("review_required"));
}

export function resolveReviewTargetOutput(unit: WebtoonCutUnit, outputPath?: string) {
  const targets = reviewTargetOutputs(unit);
  if (outputPath) {
    const explicit = targets.find((output) => output.path === outputPath);
    if (explicit) return explicit;
  }
  return targets.find((output) => output.flags?.includes("review_continuous")) || targets[0];
}

function firstReviewOutputPath(units: WebtoonCutUnit[]) {
  for (const unit of units) {
    const target = reviewTargetOutputs(unit)[0];
    if (target) return target.path;
  }
  return "";
}

async function loadOutputPreviews(outputs: GeneratedOutput[] | WebtoonCutOutput[]): Promise<WebtoonCutOutput[]> {
  return Promise.all(outputs.map(async (output) => ({
    ...output,
    previewUrl: await createPreviewUrl(output.path)
  })));
}

async function createPreviewUrl(path: string) {
  if (!outputRootHandle || !URL.createObjectURL) return undefined;
  try {
    const file = await readOutputFile(path);
    return URL.createObjectURL(file);
  } catch {
    return undefined;
  }
}

async function readOutputFile(path: string) {
  if (!outputRootHandle) throw new Error("출력 폴더가 연결되지 않았습니다.");
  const parts = path.split("/").filter(Boolean);
  const fileName = parts.pop();
  if (!fileName) throw new Error("출력 파일명이 비어 있습니다.");
  let directory = outputRootHandle;
  for (const part of parts) {
    directory = await directory.getDirectoryHandle(part);
  }
  const fileHandle = await directory.getFileHandle(fileName);
  return fileHandle.getFile();
}

function releasePreviewUrls(units: WebtoonCutUnit[]) {
  units.forEach((unit) => {
    unit.outputs.forEach((output) => {
      if (output.previewUrl) URL.revokeObjectURL?.(output.previewUrl);
    });
  });
}

async function processReviewOutput(unit: WebtoonCutUnit, target: WebtoonCutOutput, mode: WebtoonCutReprocessMode) {
  if (mode !== "strong-horizontal-transition") return;
  const targetFile = await readOutputFile(target.path);
  const bitmap = await createImageBitmap(targetFile);
  try {
    const region = document.createElement("canvas");
    region.width = bitmap.width;
    region.height = bitmap.height;
    const regionContext = region.getContext("2d", { willReadFrequently: true });
    if (!regionContext) throw new Error("재처리 Canvas 컨텍스트를 만들 수 없습니다.");
    regionContext.drawImage(bitmap, 0, 0);

    const imageData = regionContext.getImageData(0, 0, region.width, region.height);
    const boxes = splitByStrongHorizontalTransitions(imageData, region.width, region.height);
    const finalBoxes = boxes.length ? boxes : [{ index: 1, x: 0, y: 0, width: region.width, height: region.height }];
    const basePath = stripPngExtension(target.path);
    const replacementOutputs: WebtoonCutOutput[] = [];

    for (const box of finalBoxes) {
      const blob = await cropPng(region, box);
      const outputPath = finalBoxes.length === 1 ? target.path : `${basePath}-${String(box.index).padStart(2, "0")}.png`;
      await writeBlobPath(outputRootHandle!, outputPath, blob);
      replacementOutputs.push({
        path: outputPath,
        width: box.width,
        height: box.height,
        x0: (target.x0 || 0) + box.x,
        y0: (target.y0 || 0) + box.y,
        x1: (target.x0 || 0) + box.x + box.width,
        y1: (target.y0 || 0) + box.y + box.height,
        mode: "transition",
        confidence: finalBoxes.length > 1 ? 0.88 : 0.45,
        flags: []
      });
    }

    const replacement = outputsAfterReviewReplacement(unit.outputs, target.path, replacementOutputs);
    for (const deletePath of replacement.deletePaths) {
      await removeOutputPath(outputRootHandle!, deletePath);
    }
    const nextOutputs = replacement.outputs;
    const reviewOutputs = nextOutputs.filter((output) => output.flags?.includes("review_required"));
    const continuousOutputs = nextOutputs.filter((output) => output.flags?.includes("review_continuous"));
    const nextFlag: WebtoonCutUnitFlag = continuousOutputs.length ? "continuous_sequence" : reviewOutputs.length ? unit.flag : "ok";
    replaceUnit(unit.id, {
      outputs: await loadOutputPreviews(nextOutputs),
      status: reviewOutputs.length ? "review_required" : "completed",
      flag: nextFlag,
      cutCount: nextOutputs.length,
      message: reviewOutputs.length
        ? `${reviewOutputs.length}개 컷이 아직 검수 필요입니다.`
        : "선택 컷 재처리가 끝났습니다."
    });
    setSnapshot({ selectedReviewOutputPath: reviewOutputs[0]?.path || "" });
  } finally {
    bitmap.close();
  }
}

export function outputsAfterReviewReplacement(existing: WebtoonCutOutput[], targetPath: string, replacementOutputs: WebtoonCutOutput[]) {
  const shouldDeleteOriginal = replacementOutputs.length > 1 || replacementOutputs[0]?.path !== targetPath;
  return {
    outputs: existing.flatMap((output) => output.path === targetPath ? replacementOutputs : [output]),
    deletePaths: shouldDeleteOriginal ? [targetPath] : []
  };
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
  const ledger = snapshot.units.map(unitToLedgerEntry);
  const summaryRows = ledger.flatMap(unitToSummaryRows);
  const now = new Date().toISOString();
  const manifest: WebtoonCutManifest = {
    schemaVersion: MANIFEST_SCHEMA_VERSION,
    engineVersion: ENGINE_VERSION,
    jobId: snapshot.jobId,
    status: snapshot.reviewUnits ? "completed_with_review" : snapshot.failedUnits ? "completed_with_errors" : "completed",
    inputKind: selectedInputs.length === 1 ? selectedInputs[0].sourceItem.kind : "directory",
    inputName: snapshot.inputName,
    outputRoot: snapshot.outputLocation.split("/").pop() || `${safeFileName(snapshot.inputName)}_cuts`,
    expectedUnitCount: snapshot.totalUnits,
    createdAt: now,
    updatedAt: now,
    completedAt: now,
    options: {
      mode: "auto",
      pdfScale: PDF_RENDER_SCALE,
      outputFormat: "png",
      pagePolicy: PAGE_POLICY,
      stripPolicy: STRIP_POLICY,
      transitionPolicy: TRANSITION_POLICY
    },
    inputs: selectedInputs.map((input) => ({
      inputId: input.id,
      kind: input.sourceItem.kind,
      relativePath: input.sourceItem.relativePath,
      fingerprint: input.sourceItem.fingerprint || null
    })),
    inventory: ledger.map((unit) => ({
      unitId: unit.unitId,
      sourcePath: unit.sourcePath,
      sourceKind: unit.sourceKind,
      page: unit.page
    })),
    ledger,
    generatedFiles: ledger.flatMap((unit) => unit.outputs.map((output) => output.path)),
    totals: {
      expectedUnitCount: snapshot.totalUnits,
      completedUnitCount: ledger.filter((unit) => unit.status === "completed").length,
      errorUnitCount: ledger.filter((unit) => unit.status === "error").length,
      reviewRequiredUnitCount: ledger.filter((unit) => unit.flags.includes("review_required")).length,
      generatedCutCount: ledger.reduce((sum, unit) => sum + unit.outputs.length, 0),
      flags: countUnitFlags(ledger)
    }
  };
  const summaryBytes = serializeSummary(summaryRows);
  const summaryBuffer = new ArrayBuffer(summaryBytes.byteLength);
  new Uint8Array(summaryBuffer).set(summaryBytes);
  await writeBlob(outputRootHandle, "summary.csv", new Blob([summaryBuffer], { type: "text/csv;charset=utf-8" }));
  await writeBlob(outputRootHandle, "manifest.json", new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }));
}

function unitToLedgerEntry(unit: WebtoonCutUnit): UnitLedgerEntry {
  const { sourcePath, page } = splitUnitSourcePath(unit.sourcePath);
  const outputFlags = [...new Set(unit.outputs.flatMap((output) => output.flags || []))];
  const flags = [...new Set([
    ...outputFlags,
    ...(unit.status === "review_required" ? ["review_required"] : []),
    ...(unit.flag === "fullpage" ? ["fullpage"] : []),
    ...(unit.flag === "continuous_sequence" ? ["review_continuous"] : []),
    ...(unit.status === "failed" ? ["error"] : [])
  ])];
  return {
    unitId: unit.id,
    sourcePath,
    sourceKind: unit.id.startsWith("pdf:") ? "pdf-page" : "image",
    page,
    status: unit.status === "failed" ? "error" : "completed",
    attempts: 1,
    flags,
    outputs: unit.outputs.map(({ previewUrl: _previewUrl, ...output }) => output as GeneratedOutput),
    error: unit.status === "failed" ? unit.message : undefined
  };
}

function unitToSummaryRows(unit: UnitLedgerEntry): SummaryRow[] {
  return unit.outputs.map((output, index) => ({
    unit_id: unit.unitId,
    source_path: unit.sourcePath,
    page: unit.page ?? "",
    cut: index + 1,
    filename: output.path,
    mode: output.mode || "",
    x0: output.x0 ?? "",
    y0: output.y0 ?? "",
    x1: output.x1 ?? "",
    y1: output.y1 ?? "",
    width: output.width || "",
    height: output.height || "",
    confidence: output.confidence ?? "",
    flag: output.flags?.join(" ") || unit.flags.join(" "),
    elapsed_ms: "",
    status: unit.status,
    error: unit.error || ""
  }));
}

function splitUnitSourcePath(value: string) {
  const match = value.match(/^(.*)#(\d{3})$/);
  return {
    sourcePath: match ? match[1] : value,
    page: match ? Number(match[2]) : null
  };
}

function countUnitFlags(ledger: UnitLedgerEntry[]) {
  const flags: Record<string, number> = {};
  ledger.forEach((unit) => {
    unit.flags.forEach((flag) => {
      flags[flag] = (flags[flag] || 0) + 1;
    });
  });
  return flags;
}

async function writeBlob(directory: FileSystemDirectoryHandle, name: string, blob: Blob) {
  const handle = await directory.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await writable.write(blob);
  await writable.close();
}

async function writeBlobPath(root: FileSystemDirectoryHandle, path: string, blob: Blob) {
  const parts = path.split("/").filter(Boolean);
  const fileName = parts.pop();
  if (!fileName) throw new Error("출력 파일명이 비어 있습니다.");
  let directory = root;
  for (const part of parts) {
    directory = await directory.getDirectoryHandle(part, { create: true });
  }
  await writeBlob(directory, fileName, blob);
}

async function removeOutputPath(root: FileSystemDirectoryHandle, path: string) {
  const parts = path.split("/").filter(Boolean);
  const fileName = parts.pop();
  if (!fileName) return;
  let directory = root;
  for (const part of parts) {
    directory = await directory.getDirectoryHandle(part);
  }
  await directory.removeEntry(fileName).catch(() => undefined);
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

function stageNotice(stage: string) {
  if (stage === "inventory") return "입력 파일과 PDF 페이지 수를 확인 중입니다.";
  if (stage === "resume-skip") return "manifest 기준으로 완료된 산출물을 건너뛰고 있습니다.";
  if (stage === "render") return "페이지/이미지를 렌더링 중입니다.";
  if (stage === "detect") return "컷 경계를 감지 중입니다.";
  if (stage === "write") return "PNG 컷 파일을 저장 중입니다.";
  if (stage === "manifest") return "summary.csv와 manifest.json을 저장 중입니다.";
  return "브라우저 로컬에서 컷 분할 중입니다.";
}

function safeBaseName(name: string) {
  return safeFileName(name.replace(/\.[^.]+$/, "")) || "source";
}

function stripPngExtension(path: string) {
  return path.replace(/\.png$/i, "");
}

function safeFileName(value: string) {
  return value.normalize("NFC").trim().replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, " ");
}
