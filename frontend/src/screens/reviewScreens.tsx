import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  apiClient,
  BatchJobResponse,
  HealthResponse,
  HistoryItem,
  RunpodHistoryStats,
  AssetItem,
  CollectionSummary,
  TaskPromptReviewFlags,
  TaskPromptItem,
  TaskModelReference,
  GrokImagePromptDraftResponse,
  WorkflowItem
} from "../api/client";
import { StudioRoute } from "../router";
import { canUse, User } from "../auth";
import { AppShell } from "../components/AppShell";
import {
  formatKstTimestamp,
  formatTimestamp,
  isSuccessStatus,
  isTerminalHistoryStatus
} from "../helpers/format";
import { positivePromptEntries, negativePromptEntries } from "../helpers/prompts";
import {
  historyInputImages,
  historyOutputAsset
} from "../helpers/workflow";
import { shellNavigate } from "../helpers/navigation";
import {
  ProtectedImage,
  ProtectedVideoThumb,
  ProtectedAssetPreview
} from "../components/ProtectedAssets";
import { isEditableKeyboardTarget, nextListSelectionId } from "../helpers/listKeyboardNavigation";

function workflowLabel(workflow: WorkflowItem) {
  return workflow.label || workflow.name || workflow.id;
}

function runpodStatusDisplay(status?: string | null, fallback?: string | null) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "PENDING_SUBMIT") return "제출 대기";
  if (normalized === "DISPATCHING") return "제출 중";
  if (normalized === "QUEUED" || normalized === "IN_QUEUE") return "RunPod Queue";
  if (normalized === "IN_PROGRESS" || normalized === "RUNNING") return "진행 중";
  if (normalized === "COMPLETED" || normalized === "SUCCESS") return "Completed";
  if (normalized === "CANCELLED") return "취소됨";
  if (normalized === "TIMED_OUT") return "시간 초과";
  if (normalized === "FAILED") return "Failed";
  return fallback || status || "-";
}

function runpodResultStatusLabel(item: HistoryItem) {
  if (item.lastDispatchError?.includes("동시 활성 Task 한도")) return "한도 대기";
  return runpodStatusDisplay(item.status, item.statusLabel);
}

function isCancelledStatus(status?: string) {
  return String(status || "").toUpperCase() === "CANCELLED";
}

function isFailedRunpodStatus(status?: string) {
  const normalized = String(status || "").toUpperCase();
  return normalized === "FAILED" || normalized === "TIMED_OUT";
}

// 2026-09-13 지침 §6: 상태 3중 인코딩(색+점+텍스트) + 행 좌측 3px 바. 판정 로직(runpodResultStatusTone)은
// 그대로 두고 배지 톤 → 행 바 클래스만 파생한다(완료·취소는 바 없음).
function runpodRowToneClass(tone: string) {
  if (tone === "is-failed") return "is-tone-fail";
  if (tone === "is-running") return "is-tone-run";
  if (tone === "is-pending") return "is-tone-wait";
  return "";
}

function runpodResultStatusTone(status?: string) {
  if (isSuccessStatus(status)) return "is-ready";
  if (isCancelledStatus(status)) return "is-muted";
  if (isFailedRunpodStatus(status)) return "is-failed";
  return "is-pending";
}

const RUNPOD_RESULT_FILTER_LABELS: Record<"all" | "active" | "completed" | "failed" | "cancelled", string> = {
  all: "전체 결과",
  active: "진행 중",
  completed: "완료",
  failed: "실패",
  cancelled: "취소"
};

const EMPTY_RUNPOD_HISTORY_STATS: RunpodHistoryStats = {
  total: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
  pendingSubmit: 0,
  active: 0
};

function formatRunpodHistoryTime(totalSeconds?: number | string | null) {
  if (totalSeconds === undefined || totalSeconds === null) return "-";
  const value = Number(totalSeconds);
  if (!Number.isFinite(value) || value < 0) return "-";
  const total = Math.round(value);
  const minutes = String(Math.floor(total / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function formatKstDateOnly(value?: string | null) {
  const formatted = formatKstTimestamp(value);
  return formatted === "-" ? formatted : formatted.slice(0, 10);
}

function batchZipDownloadName(batch: BatchJobResponse) {
  const source = String(batch.sourceZipFileName || batch.sourceDirName || batch.id || "batch").trim();
  const base = source.replace(/\.zip$/i, "") || "batch";
  return `${base}_output.zip`;
}

const RUNPOD_HISTORY_GRID = "32px 36px minmax(44px, .28fr) minmax(76px, .4fr) minmax(110px, .9fr) minmax(96px, .75fr) minmax(96px, .75fr) minmax(96px, .75fr) minmax(110px, .85fr) minmax(72px, .5fr) 72px minmax(170px, 1.25fr) minmax(62px, .45fr) minmax(62px, .45fr) minmax(88px, .55fr) 52px";

// E-03 · 3a "작업 이력" — design_handoff_dobedub_v3/3 Review.dc.html의 첫 화면.
// 목록·페이지네이션·삭제는 B-01/C-03에서 이미 완성된 로직(loadHistoryPage,
// changeHistoryPageSize, deleteHistoryItem)을 그대로 재사용한다.
//
// 설계 원본과 다르게 뺀 것:
// - run id·프롬프트 검색, 날짜 범위, 워크플로 필터 칩, CSV 내보내기 — `GET
//   /api/history`가 page/pageSize만 받고 검색·필터·내보내기 파라미터가 없다.
// - 상태 필터(전체/완료/실패/진행 중/내 작업만)는 서버 필터가 아니라 **현재
//   불러온 페이지 안에서만** 클라이언트 필터링한다 - 128건 전체가 아니라 화면에
//   이미 있는 20/50건 중에서만 걸러진다는 뜻이라 이 화면에서만 유의미하다.
// - "소요" 컬럼 — HistoryItem에 소요 시간 필드가 없다.
// - 상세 패널의 "평가 4 · 재사용 등록됨" 같은 평가 요약 수치 — 이력 목록
//   응답에 평가 집계가 없어 RunPod 통계 패널에는 포함하지 않는다.
//
// 2026-09-08: RunPod 우측 패널은 개별 Run 상세 대신 현재 필터 결과의 통계
// 대시보드로 사용한다. 개별 다운로드/재실행은 표 행과 상단 액션에서 처리한다.
export function Create3aScreen({
  user,
  health,
  onGoTo,
  history,
  page,
  pageCount,
  pageSize,
  total,
  loading,
  selectedTaskId,
  deleteTargets,
  deleteError,
  promptReviewItems,
  promptReviewLoading,
  promptReviewNotice,
  onSelect,
  onPageChange,
  onPageSizeChange,
  onDownload,
  onRework,
  onSavePromptReview,
  onSavePromptFeedback,
  onRequestDelete,
  onRequestBulkDelete,
  onCancelDelete,
  onConfirmDelete,
  onCancelTask,
  canRework,
  canDelete,
  canCancel,
  canReview,
  canGiveFeedback,
  workflows
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  history: HistoryItem[];
  page: number;
  pageCount: number;
  pageSize: 20 | 50;
  total: number;
  loading: boolean;
  selectedTaskId: string;
  deleteTargets: HistoryItem[];
  // #4 오류 위치 규칙: 삭제(동작) 실패는 본문 상단이 아니라 삭제 모달의 버튼 근처에
  // 표시한다. modalNotice(StudioShell)를 그대로 받는다 - 이전엔 어디에도 렌더되지
  // 않아 삭제 실패가 사용자에게 전혀 보이지 않았다.
  deleteError: string;
  // 2026-08-11: 폐지된 Run 상세(3f/3c) 화면의 평가 데이터를 우측 패널
  // Prompt Review 아코디언이 그대로 흡수한다 - 저장 로직(B-02)은 동일.
  promptReviewItems: TaskPromptItem[];
  promptReviewLoading: boolean;
  promptReviewNotice: string;
  onSelect: (item: HistoryItem) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: 20 | 50) => void;
  onDownload: (item: HistoryItem) => void;
  onRework: (item: HistoryItem) => void;
  onSavePromptReview: (segmentIndex: number, payload: Record<string, unknown>) => void;
  onSavePromptFeedback: (outputId: string, payload: { rating?: number; notes?: string }) => void;
  onRequestDelete: (item: HistoryItem) => void;
  onRequestBulkDelete: (items: HistoryItem[]) => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  onCancelTask: (item: HistoryItem) => void;
  canRework: boolean;
  canDelete: boolean;
  canCancel: boolean;
  canReview: boolean;
  canGiveFeedback: boolean;
  workflows: WorkflowItem[];
}) {
  const [historyTab, setHistoryTab] = useState<"prompt" | "runpod">("runpod");
  const [runpodPage, setRunpodPage] = useState(1);
  const [runpodHistoryItems, setRunpodHistoryItems] = useState<HistoryItem[]>([]);
  const [runpodHistoryTotal, setRunpodHistoryTotal] = useState(0);
  const [runpodHistoryStats, setRunpodHistoryStats] = useState<RunpodHistoryStats>(EMPTY_RUNPOD_HISTORY_STATS);
  const [runpodHistoryLoading, setRunpodHistoryLoading] = useState(false);
  const [runpodHistoryNotice, setRunpodHistoryNotice] = useState("");
  const [runpodHistoryNoticeKind, setRunpodHistoryNoticeKind] = useState<"error" | "success">("error");
  const [selectedRunpodTaskIds, setSelectedRunpodTaskIds] = useState<string[]>([]);
  const [selectedRunpodPromptItem, setSelectedRunpodPromptItem] = useState<HistoryItem | null>(null);
  const [reworkingRunpodTaskIds, setReworkingRunpodTaskIds] = useState<string[]>([]);
  const [runpodBulkReworking, setRunpodBulkReworking] = useState(false);
  const [assetPreview, setAssetPreview] = useState<{ src: string; isVideo: boolean; alt: string } | null>(null);
  const [runpodResultFilter, setRunpodResultFilter] = useState<"all" | "active" | "completed" | "failed" | "cancelled">("all");
  const [runpodWorkflowFilter, setRunpodWorkflowFilter] = useState("");
  const [batchSearchText, setBatchSearchText] = useState("");
  const [selectedBatchJob, setSelectedBatchJob] = useState<BatchJobResponse | null>(null);
  const [batchCandidates, setBatchCandidates] = useState<BatchJobResponse[]>([]);
  const [batchSearchLoading, setBatchSearchLoading] = useState(false);
  const [batchCandidateOpen, setBatchCandidateOpen] = useState(false);
  const [runpodWorkerFilter, setRunpodWorkerFilter] = useState("");
  const [runpodRunDate, setRunpodRunDate] = useState("");
  const [runpodJobSearch, setRunpodJobSearch] = useState("");
  const [runpodSelectionLoading, setRunpodSelectionLoading] = useState(false);
  const [selectedPromptHistoryItem, setSelectedPromptHistoryItem] = useState<GrokImagePromptDraftResponse | null>(null);
  const runpodHistoryListRef = useRef<HTMLDivElement | null>(null);
  const selectedBatchJobId = selectedBatchJob?.id || "";
  useEffect(() => {
    if (historyTab !== "runpod") return;
    let active = true;
    setRunpodHistoryLoading(true);
    setRunpodHistoryNotice("");
    setRunpodHistoryNoticeKind("error");
    apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId, jobId: runpodJobSearch.trim() })
      .then((response) => {
        if (!active) return;
        setRunpodHistoryItems(response.items);
        setRunpodHistoryTotal(response.total);
        setRunpodHistoryStats(response.stats || EMPTY_RUNPOD_HISTORY_STATS);
      })
      .catch((error: Error) => {
        if (!active) return;
        setRunpodHistoryItems([]);
        setRunpodHistoryTotal(0);
        setRunpodHistoryStats(EMPTY_RUNPOD_HISTORY_STATS);
        setRunpodHistoryNoticeKind("error");
        setRunpodHistoryNotice(error.message || "RunPod 이력을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setRunpodHistoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [historyTab, runpodPage, runpodWorkflowFilter, runpodResultFilter, runpodWorkerFilter, runpodRunDate, selectedBatchJobId, runpodJobSearch]);

  useEffect(() => {
    if (historyTab !== "runpod") return;
    const query = batchSearchText.trim();
    if (!query || (selectedBatchJob && query === selectedBatchJob.id)) {
      setBatchCandidates([]);
      setBatchCandidateOpen(false);
      setBatchSearchLoading(false);
      return;
    }
    let active = true;
    setBatchSearchLoading(true);
    const timer = window.setTimeout(() => {
      apiClient.batchJobCandidates({ query, limit: 10 })
        .then((response) => {
          if (!active) return;
          setBatchCandidates(response.items || []);
          setBatchCandidateOpen(true);
        })
        .catch(() => {
          if (!active) return;
          setBatchCandidates([]);
          setBatchCandidateOpen(true);
        })
        .finally(() => {
          if (active) setBatchSearchLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [historyTab, batchSearchText, selectedBatchJob]);

  useEffect(() => {
    if (historyTab !== "runpod") return;
    if (!reworkingRunpodTaskIds.length) return;
    let active = true;
    const refreshReworkedTasks = async () => {
      const response = await apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId, jobId: runpodJobSearch.trim() });
      if (!active) return;
      setRunpodHistoryItems(response.items);
      setRunpodHistoryTotal(response.total);
      setRunpodHistoryStats(response.stats || EMPTY_RUNPOD_HISTORY_STATS);
      const visibleById = new Map(response.items.map((item) => [item.taskId, item]));
      setReworkingRunpodTaskIds((current) => current.filter((taskId) => {
        const refreshed = visibleById.get(taskId);
        return Boolean(refreshed && !isTerminalHistoryStatus(refreshed.status));
      }));
    };
    const timer = window.setInterval(() => {
      void refreshReworkedTasks();
    }, 5000);
    void refreshReworkedTasks();
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [historyTab, reworkingRunpodTaskIds, runpodPage, runpodWorkflowFilter, runpodResultFilter, runpodWorkerFilter, runpodRunDate, selectedBatchJobId, runpodJobSearch]);

  const filteredHistory = runpodHistoryItems;
  const runpodPageSize = 10;
  const runpodPageCount = Math.max(1, Math.ceil(runpodHistoryTotal / runpodPageSize));
  const pageStart = runpodHistoryTotal ? (runpodPage - 1) * runpodPageSize + 1 : 0;
  const pageEnd = Math.min(runpodHistoryTotal, runpodPage * runpodPageSize);
  const pageOffset = (runpodPage - 1) * runpodPageSize;
  const terminalRunpodItems = filteredHistory.filter((item) => isTerminalHistoryStatus(item.status));
  const selectedRunpodItems = terminalRunpodItems.filter((item) => selectedRunpodTaskIds.includes(item.taskId));
  const selectedDownloadItems = selectedRunpodItems.filter((item) => {
    const result = historyOutputAsset(item);
    return Boolean(result?.downloadUrl || result?.url || item.outputUrl);
  });
  const canReworkFilteredRunpodItems = Boolean(selectedBatchJobId)
    && !runpodJobSearch.trim()
    && runpodResultFilter !== "active"
    && runpodResultFilter !== "completed";
  const selectedWorkflow = workflows.find((workflow) => workflow.id === runpodWorkflowFilter);
  const runpodAppliedFilters = [
    { label: "Batch ID", value: selectedBatchJobId || "전체 Batch" },
    { label: "작업 ID", value: runpodJobSearch.trim() || "전체 작업" },
    { label: "워크플로우", value: selectedWorkflow ? workflowLabel(selectedWorkflow) : "전체 워크플로우" },
    { label: "결과", value: RUNPOD_RESULT_FILTER_LABELS[runpodResultFilter] },
    { label: "작업자", value: runpodWorkerFilter.trim() || "전체 작업자" },
    { label: "실행일", value: runpodRunDate || "전체 실행일" }
  ];
  const runpodReplayCandidateCount = runpodHistoryStats.failed + runpodHistoryStats.cancelled;
  const runpodStatSegments = [
    { key: "completed", label: "완료", value: runpodHistoryStats.completed, tone: "is-ready" },
    { key: "failed", label: "실패", value: runpodHistoryStats.failed, tone: "is-failed" },
    { key: "cancelled", label: "취소", value: runpodHistoryStats.cancelled, tone: "is-muted" },
    { key: "pendingSubmit", label: "제출대기", value: runpodHistoryStats.pendingSubmit, tone: "is-pending" },
    { key: "active", label: "진행", value: runpodHistoryStats.active, tone: "is-running" }
  ] as const;
  const allTerminalItemsSelected = terminalRunpodItems.length > 0
    && terminalRunpodItems.every((item) => selectedRunpodTaskIds.includes(item.taskId));
  const handleRunpodHistoryListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isEditableKeyboardTarget(event.target)) return;
    const nextTaskId = nextListSelectionId(filteredHistory, selectedTaskId, event.key, (item) => item.taskId);
    if (nextTaskId === selectedTaskId) return;
    const nextItem = filteredHistory.find((item) => item.taskId === nextTaskId);
    if (!nextItem) return;
    event.preventDefault();
    onSelect(nextItem);
  };
  const selectRunpodHistoryRow = (item: HistoryItem) => {
    onSelect(item);
    runpodHistoryListRef.current?.focus();
  };
  const toggleRunpodSelection = (taskId: string) => {
    setSelectedRunpodTaskIds((current) => current.includes(taskId)
      ? current.filter((candidate) => candidate !== taskId)
      : [...current, taskId]);
  };
  const toggleAllRunpodSelection = () => {
    setSelectedRunpodTaskIds((current) => {
      if (allTerminalItemsSelected) {
        const visibleTaskIds = new Set(terminalRunpodItems.map((item) => item.taskId));
        return current.filter((taskId) => !visibleTaskIds.has(taskId));
      }
      return Array.from(new Set([...current, ...terminalRunpodItems.map((item) => item.taskId)]));
    });
  };
  async function selectAllFilteredRunpodTasks() {
    setRunpodHistoryNotice("");
    setRunpodHistoryNoticeKind("error");
    setRunpodSelectionLoading(true);
    try {
      const selection = await apiClient.runpodHistorySelection({
        workflowId: runpodWorkflowFilter,
        resultStatus: runpodResultFilter,
        workerId: runpodWorkerFilter,
        runDate: runpodRunDate,
        batchId: selectedBatchJobId,
        jobId: runpodJobSearch.trim()
      });
      setSelectedRunpodTaskIds(selection.taskIds);
      setRunpodHistoryNoticeKind("success");
      setRunpodHistoryNotice(selection.truncated
        ? `종료 작업 ${selection.taskIds.length}건을 선택했습니다. 선택 가능 한도까지만 포함되었습니다.`
        : `종료 작업 ${selection.taskIds.length}건을 선택했습니다.`);
    } catch (error) {
      setRunpodHistoryNoticeKind("error");
      setRunpodHistoryNotice(error instanceof Error ? error.message : "조회 결과를 선택하지 못했습니다.");
    } finally {
      setRunpodSelectionLoading(false);
    }
  }
  async function downloadFilteredBatchZip() {
    if (!selectedBatchJob) return;
    setRunpodHistoryNotice("");
    setRunpodHistoryNoticeKind("error");
    try {
      const blob = await apiClient.batchJobZip(selectedBatchJob.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = batchZipDownloadName(selectedBatchJob);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setRunpodHistoryNoticeKind("error");
      setRunpodHistoryNotice(error instanceof Error ? error.message : "배치 ZIP 다운로드에 실패했습니다.");
    }
  }
  async function downloadSelectedBatchZip() {
    if (!selectedBatchJob || !selectedRunpodTaskIds.length) return;
    setRunpodHistoryNotice("");
    setRunpodHistoryNoticeKind("error");
    try {
      const blob = await apiClient.batchJobZip(selectedBatchJob.id, selectedRunpodTaskIds);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${batchZipDownloadName(selectedBatchJob).replace(/\\.zip$/, "")}_selected.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setRunpodHistoryNoticeKind("error");
      setRunpodHistoryNotice(error instanceof Error ? error.message : "선택 ZIP 다운로드에 실패했습니다.");
    }
  }
  async function reworkRunpodHistoryItem(item: HistoryItem) {
    if (reworkingRunpodTaskIds.includes(item.taskId)) return;
    setRunpodHistoryNotice("");
    setRunpodHistoryNoticeKind("error");
    setReworkingRunpodTaskIds((current) => current.includes(item.taskId) ? current : [...current, item.taskId]);
    try {
      const job = await apiClient.reworkHistoryItem(item.taskId);
      const response = await apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId, jobId: runpodJobSearch.trim() });
      setRunpodHistoryItems(response.items.map((historyItem) => historyItem.taskId === item.taskId ? { ...historyItem, status: job.status, runpodJobId: job.runpodJobId || historyItem.runpodJobId, lastDispatchError: job.lastDispatchError || undefined } : historyItem));
      setRunpodHistoryTotal(response.total);
      setRunpodHistoryStats(response.stats || EMPTY_RUNPOD_HISTORY_STATS);
      setRunpodHistoryNoticeKind("success");
      setRunpodHistoryNotice("재작업 요청이 등록되었습니다. 기존 작업 상태가 갱신됩니다.");
    } catch (error) {
      setReworkingRunpodTaskIds((current) => current.filter((taskId) => taskId !== item.taskId));
      setRunpodHistoryNoticeKind("error");
      setRunpodHistoryNotice(error instanceof Error ? error.message : "RunPod 재작업 요청에 실패했습니다.");
    }
  }
  async function reworkSelectedRunpodItems() {
    if (!selectedRunpodItems.length || runpodBulkReworking) return;
    const taskIds = selectedRunpodItems.map((item) => item.taskId);
    setRunpodHistoryNotice("");
    setRunpodHistoryNoticeKind("error");
    setRunpodBulkReworking(true);
    setReworkingRunpodTaskIds((current) => Array.from(new Set([...current, ...taskIds])));
    try {
      const result = await apiClient.reworkRunpodHistoryItems({ scope: "selected", taskIds });
      const response = await apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId, jobId: runpodJobSearch.trim() });
      setRunpodHistoryItems(response.items);
      setRunpodHistoryTotal(response.total);
      setRunpodHistoryStats(response.stats || EMPTY_RUNPOD_HISTORY_STATS);
      setSelectedRunpodTaskIds((current) => current.filter((taskId) => !result.taskIds.includes(taskId)));
      setRunpodHistoryNoticeKind("success");
      setRunpodHistoryNotice(`${result.reworked}건의 재실행 요청이 등록되었습니다.${result.skipped.length ? ` 제외 ${result.skipped.length}건` : ""}`);
    } catch (error) {
      setReworkingRunpodTaskIds((current) => current.filter((taskId) => !taskIds.includes(taskId)));
      setRunpodHistoryNoticeKind("error");
      setRunpodHistoryNotice(error instanceof Error ? error.message : "선택 RunPod 재실행 요청에 실패했습니다.");
    } finally {
      setRunpodBulkReworking(false);
    }
  }
  async function reworkFilteredRunpodItems() {
    if (!canReworkFilteredRunpodItems || runpodBulkReworking) return;
    setRunpodHistoryNotice("");
    setRunpodHistoryNoticeKind("error");
    setRunpodBulkReworking(true);
    try {
      const result = await apiClient.reworkRunpodHistoryItems({
        scope: "query",
        batchId: selectedBatchJobId,
        workflowId: runpodWorkflowFilter,
        resultStatus: runpodResultFilter,
        workerId: runpodWorkerFilter,
        runDate: runpodRunDate
      });
      const response = await apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId, jobId: runpodJobSearch.trim() });
      setRunpodHistoryItems(response.items);
      setRunpodHistoryTotal(response.total);
      setRunpodHistoryStats(response.stats || EMPTY_RUNPOD_HISTORY_STATS);
      setSelectedRunpodTaskIds((current) => current.filter((taskId) => !result.taskIds.includes(taskId)));
      setReworkingRunpodTaskIds((current) => Array.from(new Set([...current, ...result.taskIds])));
      setRunpodHistoryNoticeKind("success");
      setRunpodHistoryNotice(`${result.reworked}건의 조회 결과 재실행 요청이 등록되었습니다.${result.skipped.length ? ` 제외 ${result.skipped.length}건` : ""}`);
    } catch (error) {
      setRunpodHistoryNoticeKind("error");
      setRunpodHistoryNotice(error instanceof Error ? error.message : "조회 결과 RunPod 재실행 요청에 실패했습니다.");
    } finally {
      setRunpodBulkReworking(false);
    }
  }
  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="taskHistory"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="TASK HISTORY"
      headerTitle="작업 이력"
      bodyClassName="v3-task-history-body"
      headerActions={historyTab === "runpod" ? <span className="v3-header-meta">{runpodHistoryTotal}건 · KST</span> : null}
      sidebarFooter={<p className="v3-muted-text">보관 기한 90일 · RunPod 이력 10건 / 페이지 · 이후 Assets만 유지</p>}
      rightPanel={
        historyTab === "prompt" ? (
          <PromptGrokResponseDetail item={selectedPromptHistoryItem} />
        ) : (
          <>
            {/* 지침 §4: 우측 패널은 무엇에 대한 것인지 헤더로 선언한다(전체 요약 vs 행 상세). */}
            <div className="v3-panel-context">← 왼쪽 조회 결과 요약</div>
            <div className="v3-panel-title-row">
              <div>
                <div className="v3-panel-title">RunPod 조회 통계</div>
                <p className="v3-muted-text" style={{ margin: "4px 0 0" }}>현재 필터({runpodAppliedFilters.filter((filter) => !filter.value.startsWith("전체")).map((filter) => filter.label).join(" · ") || "없음"}) 기준 {runpodHistoryStats.total}건</p>
              </div>
              <span className="v3-status-badge is-ready">{pageStart}-{pageEnd} / {runpodHistoryTotal}</span>
            </div>

            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>총건</span><strong>{runpodHistoryStats.total}</strong></div>
              {runpodStatSegments.map((segment) => (
                <div className="v3-summary-row" key={segment.key}>
                  <span>{segment.label}</span>
                  <strong>{segment.value}</strong>
                </div>
              ))}
            </div>

            <div className="v3-card v3-runpod-stat-card">
              <div className="v3-card-header">
                <div className="v3-card-header-title">결과 구성</div>
              </div>
              <div className="v3-runpod-stat-list">
                {runpodStatSegments.map((segment) => {
                  const percent = runpodHistoryStats.total ? Math.round((segment.value / runpodHistoryStats.total) * 1000) / 10 : 0;
                  return (
                    <div className="v3-runpod-stat-row" key={segment.key}>
                      <div className="v3-runpod-stat-line">
                        <span>{segment.label}</span>
                        <strong>{percent}%</strong>
                      </div>
                      <div className="v3-runpod-stat-bar">
                        <i className={segment.tone} style={{ width: `${percent}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="v3-card">
              <div className="v3-card-header">
                <div className="v3-card-header-title">적용된 필터</div>
              </div>
              <div className="v3-filter-chip-list">
                {runpodAppliedFilters.map((filter) => (
                  <div className="v3-filter-chip" key={filter.label}>
                    <span>{filter.label}</span>
                    <strong>{filter.value}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div className="v3-card">
              <div className="v3-card-header">
                <div className="v3-card-header-title">재실행 기준</div>
              </div>
              <div className="v3-summary-row"><span>조회 오류 재실행 대상</span><strong>{runpodReplayCandidateCount}</strong></div>
              <div className="v3-summary-row"><span>선택 재실행 가능</span><strong>{selectedRunpodItems.length}</strong></div>
              <p className="v3-muted-text" style={{ margin: "8px 12px 12px" }}>진행/제출대기 자동 제외</p>
            </div>
          </>
        )
      }
    >
      <div className="v3-scope-tabs" role="tablist" aria-label="작업 이력 종류">
        <button
          type="button"
          role="tab"
          aria-selected={historyTab === "runpod"}
          className={`v3-scope-tab ${historyTab === "runpod" ? "is-active" : ""}`}
          onClick={() => setHistoryTab("runpod")}
        >
          RunPod 이력
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={historyTab === "prompt"}
          className={`v3-scope-tab ${historyTab === "prompt" ? "is-active" : ""}`}
          onClick={() => setHistoryTab("prompt")}
        >
          프롬프트 이력
        </button>
      </div>

      {historyTab === "prompt" ? (
        <PromptGenerationHistory user={user} onSelectGrokItem={setSelectedPromptHistoryItem} />
      ) : (
        <>
      {/* 2026-09-13 지침 §4·§5: ①조회 조건 → ②선택 작업 → ③조회 결과 번호 섹션. 필터 카드는 Batch ID
          후보 드롭다운(.v3-batch-candidate-list, position:absolute)이 카드 밖으로 나가야 하므로
          overflow:visible(is-overflow-visible)을 유지한다 — 카드 기본 overflow:hidden에 잘리면 안 된다. */}
      <div className="v3-card v3-history-step-card is-overflow-visible">
        <div className="v3-history-step-head">
          <span className="v3-step-badge">1</span>
          <strong>조회 조건</strong>
          <small>필터를 바꾸면 아래 표와 우측 요약이 함께 갱신됩니다</small>
        </div>
        <div className="v3-runpod-history-toolbar">
        <div className="v3-runpod-filter-bar v3-runpod-history-filters">
          <label>작업자<input value={runpodWorkerFilter} onChange={(event) => { setRunpodWorkerFilter(event.target.value); setRunpodPage(1); setSelectedRunpodTaskIds([]); }} placeholder="전체 작업자" /></label>
          <label>실행일<input type="date" value={runpodRunDate} onChange={(event) => { setRunpodRunDate(event.target.value); setRunpodPage(1); setSelectedRunpodTaskIds([]); }} /></label>
          <label>작업 ID<input value={runpodJobSearch} onChange={(event) => { setRunpodJobSearch(event.target.value); setRunpodPage(1); setSelectedRunpodTaskIds([]); }} placeholder="Studio Task / RunPod Job ID" /></label>
          <label className="v3-batch-search-field">Batch ID
            <input
              value={batchSearchText}
              onBlur={() => window.setTimeout(() => setBatchCandidateOpen(false), 160)}
              onChange={(event) => {
                setBatchSearchText(event.target.value);
                setSelectedBatchJob(null);
                setRunpodPage(1);
                setSelectedRunpodTaskIds([]);
              }}
              onFocus={() => {
                if (batchSearchText.trim()) setBatchCandidateOpen(true);
              }}
              placeholder="Batch ID / 작업자명 검색"
            />
            {selectedBatchJob ? <span className="v3-batch-selected-label">선택됨 · {selectedBatchJob.id}</span> : null}
            {batchCandidateOpen && batchSearchText.trim() && !selectedBatchJob ? (
              <div className="v3-batch-candidate-list" role="listbox" aria-label="Batch ID 검색 결과">
                {batchSearchLoading ? <div className="v3-batch-candidate-empty">검색 중...</div> : null}
                {!batchSearchLoading && !batchCandidates.length ? <div className="v3-batch-candidate-empty">검색 결과 없음</div> : null}
                {!batchSearchLoading && batchCandidates.map((candidate) => (
                  <button
                    key={candidate.id}
                    type="button"
                    role="option"
                    className="v3-batch-candidate-option"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setSelectedBatchJob(candidate);
                      setBatchSearchText(candidate.id);
                      setBatchCandidateOpen(false);
                      setRunpodPage(1);
                      setSelectedRunpodTaskIds([]);
                    }}
                  >
                    <strong>{candidate.id}</strong>
                    <span>{candidate.createdByName || candidate.createdBy || "-"} · {candidate.totalImages}건 · 완료 {candidate.videoCompletedCount}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </label>
          <label>워크플로우<select value={runpodWorkflowFilter} onChange={(event) => { setRunpodWorkflowFilter(event.target.value); setRunpodPage(1); setSelectedRunpodTaskIds([]); }}><option value="">전체 워크플로우</option>{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflowLabel(workflow)}</option>)}</select></label>
          <label>결과<select value={runpodResultFilter} onChange={(event) => { setRunpodResultFilter(event.target.value as "all" | "active" | "completed" | "failed" | "cancelled"); setRunpodPage(1); setSelectedRunpodTaskIds([]); }}><option value="all">전체 결과</option><option value="active">진행</option><option value="completed">완료</option><option value="failed">실패</option><option value="cancelled">취소</option></select></label>
        </div>
        </div>
      </div>

      {/* ②선택 작업 바. 개수 바인딩은 각 액션이 실제로 처리하는 집합을 그대로 쓴다(지침 §5 "선택 대상이 필요한 버튼은
          개수를 라벨에 포함"): 재실행·삭제 = selectedRunpodItems(이 페이지의 종료 상태 선택분), 다운로드 =
          selectedDownloadItems(결과물 URL 있는 선택분), ZIP = selectedRunpodTaskIds(현재 필터 전체 선택 포함 ID 전체).
          헤더의 "선택 N건"은 선택 ID 전체 수이며, 페이지 밖 선택이 있으면 괄호로 이 페이지 분을 병기한다. */}
      <div className="v3-selection-bar">
        <div className="v3-selection-bar-head">
          <span className="v3-step-badge is-accent">2</span>
          <span className="v3-selection-bar-title">선택 {selectedRunpodTaskIds.length}건에 대한 작업{selectedRunpodTaskIds.length !== selectedRunpodItems.length ? ` (이 페이지 ${selectedRunpodItems.length}건)` : ""}</span>
          <div className="v3-selection-bar-actions v3-runpod-history-actions">
            <button
              className="v3-primary-button"
              type="button"
              disabled={runpodBulkReworking || !selectedRunpodItems.length}
              onClick={reworkSelectedRunpodItems}
            >
              <svg width="13" height="13" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true"><path d="M3.4 2.2 11.4 7l-8 4.8z" /></svg>
              선택 재실행 ({selectedRunpodItems.length})
            </button>
            <button
              className="v3-secondary-button"
              type="button"
              disabled={!selectedDownloadItems.length}
              onClick={() => selectedDownloadItems.forEach((item) => onDownload(item))}
            >
              <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><line x1="7" y1="2" x2="7" y2="9" /><path d="M4.2 6.4 7 9.2l2.8-2.8" /><line x1="2.6" y1="11.6" x2="11.4" y2="11.6" /></svg>
              선택 다운로드 ({selectedDownloadItems.length})
            </button>
            <button
              className="v3-secondary-button"
              type="button"
              disabled={!selectedBatchJob || !selectedRunpodTaskIds.length}
              onClick={() => void downloadSelectedBatchZip()}
            >
              선택 ZIP ({selectedRunpodTaskIds.length})
            </button>
            {canDelete ? (
              <>
                <span className="v3-selection-bar-divider" aria-hidden="true" />
                <button
                  className="v3-danger-button"
                  type="button"
                  disabled={!selectedRunpodItems.length}
                  onClick={() => onRequestBulkDelete(selectedRunpodItems)}
                >
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><rect x="3.4" y="4.2" width="7.2" height="7.6" rx="1.4" /><line x1="2.2" y1="4.2" x2="11.8" y2="4.2" /><line x1="5.6" y1="2.2" x2="8.4" y2="2.2" /></svg>
                  선택 삭제 ({selectedRunpodItems.length})
                </button>
              </>
            ) : null}
          </div>
        </div>
        <div className="v3-selection-bar-quiet">
          <button
            className="v3-secondary-button is-quiet"
            type="button"
            disabled={!selectedBatchJob || runpodSelectionLoading}
            onClick={() => void selectAllFilteredRunpodTasks()}
          >
            {runpodSelectionLoading ? "선택 중..." : "현재 필터 전체 선택"}
          </button>
          <button
            className="v3-secondary-button is-quiet"
            type="button"
            disabled={runpodBulkReworking || !canReworkFilteredRunpodItems}
            onClick={reworkFilteredRunpodItems}
          >
            조회 오류 재실행{runpodReplayCandidateCount ? ` (${runpodReplayCandidateCount})` : ""}
          </button>
          <button
            className="v3-secondary-button is-quiet"
            type="button"
            disabled={!selectedBatchJob}
            onClick={downloadFilteredBatchZip}
          >
            배치 ZIP
          </button>
        </div>
      </div>
      <div
        ref={runpodHistoryListRef}
        className="v3-card v3-runpod-history-table"
        role="listbox"
        aria-label="RunPod 작업 이력"
        tabIndex={0}
        onKeyDown={handleRunpodHistoryListKeyDown}
      >
        <div className="v3-history-step-head">
          <span className="v3-step-badge">3</span>
          <strong>조회 결과</strong>
          <span className="v3-history-count-chip">{runpodHistoryTotal}건 중 {pageStart}–{pageEnd}</span>
        </div>
        {/* 16컬럼 그리드 정합성: head와 row가 같은 RUNPOD_HISTORY_GRID를 쓰고, 행 좌측 3px 상태 바는
            border-left로 그려 컬럼 수·폭을 바꾸지 않는다. head에도 같은 폭의 투명 border-left를 둔다(.v3-history-head). */}
        <div className="v3-review-table-head v3-history-head" style={{ gridTemplateColumns: RUNPOD_HISTORY_GRID }}>
          <span><input type="checkbox" aria-label="현재 페이지 종료 작업 전체 선택" checked={allTerminalItemsSelected} disabled={!terminalRunpodItems.length} onChange={toggleAllRunpodSelection} /></span><span>No</span><span>작업자</span><span>실행일</span><span>워크플로우</span><span>Batch ID</span><span>Prompt ID</span><span>Studio Task</span><span>RunPod Job ID</span><span>결과</span><span>입력 이미지</span><span>생성 영상</span><span>영상길이</span><span>생성시간</span><span>다운로드</span><span className="v3-history-delete-column">삭제</span>
        </div>
        {runpodHistoryLoading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {runpodHistoryNotice ? <p className={runpodHistoryNoticeKind === "success" ? "v3-inline-success" : "v3-inline-error"} style={{ margin: 16 }} role="alert">{runpodHistoryNotice}</p> : null}
        {!runpodHistoryLoading && !runpodHistoryNotice && !filteredHistory.length ? <p className="v3-muted-text" style={{ padding: 16 }}>표시할 작업이 없습니다.</p> : null}
        {filteredHistory.map((item) => {
          const isSelected = item.taskId === selectedTaskId;
          const rowNo = pageOffset + runpodHistoryItems.findIndex((candidate) => candidate.taskId === item.taskId) + 1;
          const input = historyInputImages(item)[0];
          const result = historyOutputAsset(item);
          const resultUrl = result?.downloadUrl || result?.url || item.outputUrl || "";
          const inputFileName = input?.fileName || "입력 이미지";
          const outputFileName = result?.fileName || item.outputFile || item.runpodResponse?.filename || "생성 영상";
          const canReworkTask = canRework && isTerminalHistoryStatus(item.status) && !isSuccessStatus(item.status);
          const resultStatusLabel = runpodResultStatusLabel(item);
          const resultStatusTone = runpodResultStatusTone(item.status);
          const reworkInFlight = reworkingRunpodTaskIds.includes(item.taskId);
          const displayBatchId = item.batchJobId || item.promptBatchId || "";
          const runpodJobId = item.runpodJobId || item.runpodResponse?.jobId || "";
          return (
            <div
              key={item.taskId}
              role="option"
              aria-selected={isSelected}
              className={`v3-review-table-row v3-history-row ${runpodRowToneClass(resultStatusTone)} ${isSelected ? "is-selected" : ""}`}
              style={{ gridTemplateColumns: RUNPOD_HISTORY_GRID, cursor: "pointer" }}
              onClick={() => selectRunpodHistoryRow(item)}
            >
              <span>
                {isTerminalHistoryStatus(item.status) ? (
                  <input
                    type="checkbox"
                    aria-label={`${item.taskId} 선택`}
                    checked={selectedRunpodTaskIds.includes(item.taskId)}
                    onClick={(event) => event.stopPropagation()}
                    onChange={() => toggleRunpodSelection(item.taskId)}
                  />
                ) : null}
              </span>
              <span className="v3-review-seg-name">{rowNo}</span>
              <span style={{ fontSize: 12 }}>{item.workerName || item.user?.name || "-"}</span>
              <span className="v3-history-date-cell">{formatKstDateOnly(item.timestampUtc || item.timestamp)}</span>
              <span className="v3-review-prompt" title={item.workflowName || item.workflow || item.workflowId || ""}>{item.workflowName || item.workflow || item.workflowId || "-"}</span>
              <span className="v3-review-prompt" title={displayBatchId}>{displayBatchId || "-"}</span>
              <span className="v3-review-prompt" title={item.promptDraftId || ""}>
                {item.promptDraftId ? (
                  <button
                    className="v3-text-link-button v3-runpod-prompt-id-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedRunpodPromptItem(item);
                    }}
                  >
                    {item.promptDraftId}
                  </button>
                ) : "-"}
              </span>
              <span className="v3-review-prompt" title={item.taskId}>{item.taskId || "-"}</span>
              <span className="v3-review-prompt" title={runpodJobId}>{runpodJobId || "-"}</span>
              <span>
                <span className={`v3-status-badge ${resultStatusTone}`}>{resultStatusLabel}</span>
              </span>
              <span>
                {input?.assetId ? (
                  <button className="v3-runpod-input-thumb-button" type="button" title={inputFileName} onClick={(event) => { event.stopPropagation(); setAssetPreview({ src: `/api/files/${input.assetId}`, isVideo: false, alt: inputFileName }); }}>
                    <ProtectedImage src={`/api/files/${input.assetId}`} alt={inputFileName} />
                  </button>
                ) : "-"}
              </span>
              <span>
                {resultUrl ? <button className="v3-text-link-button v3-runpod-output-link" type="button" title={`${inputFileName} -> ${outputFileName}`} onClick={(event) => { event.stopPropagation(); setAssetPreview({ src: resultUrl, isVideo: true, alt: outputFileName }); }}>{`${inputFileName} -> ${outputFileName}`}</button> : "-"}
              </span>
              <span>{formatRunpodHistoryTime(item.durationSeconds)}</span>
              <span>{formatRunpodHistoryTime(item.runpodResponse?.executionSeconds ?? item.elapsedSeconds)}</span>
              <span>
                {canReworkTask ? (
                  <button
                    className="v3-text-link-button"
                    type="button"
                    disabled={reworkInFlight}
                    onClick={(event) => {
                      event.stopPropagation();
                      void reworkRunpodHistoryItem(item);
                    }}
                  >
                    {reworkInFlight ? "요청 중" : "재작업"}
                  </button>
                ) : resultUrl ? <button className="v3-text-link-button" type="button" onClick={(event) => { event.stopPropagation(); onDownload(item); }}>Download</button> : "-"}
              </span>
              <span className="v3-history-delete-column">
                {canDelete && isTerminalHistoryStatus(item.status) ? (
                  <button
                    className="v3-text-link-button"
                    style={{ color: "var(--v3-danger)" }}
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onRequestDelete(item);
                    }}
                  >
                    삭제
                  </button>
                ) : null}
              </span>
            </div>
          );
        })}
        <div className="v3-pagination">
          <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {runpodHistoryTotal}</span>
          <div className="v3-pagination-controls">
            <button className="v3-page-button" type="button" disabled={runpodPage <= 1} onClick={() => setRunpodPage((value) => value - 1)}>이전</button>
            <span className="v3-page-button is-current">{runpodPage}</span>
            <button className="v3-page-button" type="button" disabled={runpodPage >= runpodPageCount} onClick={() => setRunpodPage((value) => value + 1)}>다음</button>
            <span className="v3-pagination-meta">10건 / 페이지 · 표는 가로 스크롤로 16컬럼 전체 확인</span>
          </div>
        </div>
      </div>

      {selectedRunpodPromptItem ? (
        <RunpodHistoryPromptDetail item={selectedRunpodPromptItem} onClose={() => setSelectedRunpodPromptItem(null)} />
      ) : null}

      {assetPreview ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-label="자산 미리보기" onClick={() => setAssetPreview(null)}>
          <div className="v3-modal-panel v3-asset-preview-modal" onClick={(event) => event.stopPropagation()}>
            <div className="v3-panel-title-row"><div className="v3-panel-title">{assetPreview.alt}</div><button className="v3-secondary-button" type="button" onClick={() => setAssetPreview(null)}>닫기</button></div>
            <ProtectedAssetPreview src={assetPreview.src} isVideo={assetPreview.isVideo} alt={assetPreview.alt} />
          </div>
        </div>
      ) : null}

      {deleteTargets.length ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="v3DeleteHistoryTitle">
          <div className="v3-modal-panel">
            <div className="v3-label" style={{ color: "var(--v3-danger)" }}>HISTORY:DELETE</div>
            <h2 id="v3DeleteHistoryTitle" className="v3-modal-title">작업 내역 삭제</h2>
            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>대상 작업</span><strong>{deleteTargets.length}건</strong></div>
              {deleteTargets.length === 1 ? <><div className="v3-summary-row"><span>작업</span><strong>#{deleteTargets[0].taskId.slice(0, 8)} · {deleteTargets[0].workflowName || deleteTargets[0].workflow || deleteTargets[0].workflowId || "-"}</strong></div><div className="v3-summary-row"><span>실행</span><strong>{formatTimestamp(deleteTargets[0].timestampKst || deleteTargets[0].timestamp, deleteTargets[0].timestampUtc).replace(/\n/g, " ")} · {deleteTargets[0].workerName || deleteTargets[0].user?.name || "-"}</strong></div></> : null}
              <div className="v3-summary-row"><span>결과물</span><strong>{deleteTargets.reduce((count, item) => count + ((item.outputAssets || []).length || (item.outputUrl ? 1 : 0)), 0)}건</strong></div>
            </div>
            <p className="v3-modal-body-text">이력에서 제거되면 이 작업의 프롬프트 평가와 재사용 등록도 함께 사라집니다. 결과물 파일은 Assets에 남습니다.</p>
            <div className="v3-warning-strip" style={{ background: "var(--v3-danger-bg)", margin: 0 }}>
              <span className="v3-warning-dot" style={{ background: "var(--v3-danger)" }} />
              <span style={{ color: "var(--v3-danger)" }}>되돌릴 수 없습니다</span>
            </div>
            {deleteError ? <p className="v3-inline-error" role="alert">{deleteError}</p> : null}
            <div className="v3-inline-actions">
              <button className="v3-secondary-button v3-flex-button" type="button" onClick={onCancelDelete}>취소</button>
              <button
                className="v3-danger-button v3-flex-button"
                style={{ background: "var(--v3-danger)", color: "#fff", borderColor: "var(--v3-danger)" }}
                type="button"
                onClick={onConfirmDelete}
              >
                삭제
              </button>
            </div>
            <p className="v3-muted-text">진행 중인 작업은 삭제할 수 없습니다 · 권한이 없으면 버튼이 보이지 않습니다</p>
          </div>
        </div>
      ) : null}
        </>
      )}
    </AppShell>
  );
}

function RunpodHistoryPromptDetail({ item, onClose }: { item: HistoryItem; onClose: () => void }) {
  const positivePrompts = positivePromptEntries(item);
  const negativePrompts = negativePromptEntries(item);
  const displayBatchId = item.batchJobId || item.promptBatchId || "";
  return (
    <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="v3RunpodPromptTitle" onClick={onClose}>
      <div className="v3-modal-panel v3-runpod-prompt-modal" onClick={(event) => event.stopPropagation()}>
        <div className="v3-panel-title-row">
          <div>
            <div className="v3-label">PROMPT DETAIL</div>
            <h2 id="v3RunpodPromptTitle" className="v3-modal-title">프롬프트 내용</h2>
          </div>
          <button className="v3-secondary-button" type="button" onClick={onClose}>닫기</button>
        </div>
        <div className="v3-summary-card">
          <div className="v3-summary-row"><span>Prompt ID</span><strong>{item.promptDraftId || "-"}</strong></div>
          <div className="v3-summary-row"><span>Batch ID</span><strong>{displayBatchId || "-"}</strong></div>
          <div className="v3-summary-row"><span>Workflow</span><strong>{item.workflowName || item.workflow || item.workflowId || "-"}</strong></div>
        </div>
        <RunpodPromptTextBlock title="Positive Prompt" entries={positivePrompts} emptyText="저장된 positive prompt가 없습니다." />
        <RunpodPromptTextBlock title="Negative Prompt" entries={negativePrompts} emptyText="저장된 negative prompt가 없습니다." />
      </div>
    </div>
  );
}

function RunpodPromptTextBlock({ title, entries, emptyText }: { title: string; entries: Array<{ index?: number; text?: string }>; emptyText: string }) {
  return (
    <section className="v3-runpod-prompt-section">
      <h3>{title}</h3>
      {entries.length ? (
        <div className="v3-runpod-prompt-list">
          {entries.map((entry, index) => (
            <p key={`${title}-${entry.index || index + 1}`}><strong>SEG {String(entry.index || index + 1).padStart(2, "0")}</strong>{entry.text}</p>
          ))}
        </div>
      ) : (
        <p className="v3-muted-text">{emptyText}</p>
      )}
    </section>
  );
}

function PromptGenerationHistory({
  user,
  onSelectGrokItem
}: {
  user: User | null;
  onSelectGrokItem: (item: GrokImagePromptDraftResponse | null) => void;
}) {
  const [items, setItems] = useState<GrokImagePromptDraftResponse[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [generationFilter, setGenerationFilter] = useState("");
  const [runpodFilter, setRunpodFilter] = useState("");
  const [promptBatchSearchText, setPromptBatchSearchText] = useState("");
  const [selectedPromptBatchJob, setSelectedPromptBatchJob] = useState<BatchJobResponse | null>(null);
  const [promptBatchCandidates, setPromptBatchCandidates] = useState<BatchJobResponse[]>([]);
  const [promptBatchSearchLoading, setPromptBatchSearchLoading] = useState(false);
  const [promptBatchCandidateOpen, setPromptBatchCandidateOpen] = useState(false);
  const [selectedPromptHistoryDraftId, setSelectedPromptHistoryDraftId] = useState("");
  const [retryingDraftId, setRetryingDraftId] = useState("");
  const [previewItem, setPreviewItem] = useState<GrokImagePromptDraftResponse | null>(null);
  const [editingItem, setEditingItem] = useState<GrokImagePromptDraftResponse | null>(null);
  const [pendingRequeueItem, setPendingRequeueItem] = useState<GrokImagePromptDraftResponse | null>(null);
  const [editingPrompt, setEditingPrompt] = useState("");
  const [savingPrompt, setSavingPrompt] = useState(false);
  const promptHistoryListRef = useRef<HTMLDivElement | null>(null);
  const pageSize = 10;
  const selectedPromptBatchJobId = selectedPromptBatchJob?.id || "";

  function selectPromptHistoryItem(item: GrokImagePromptDraftResponse | null) {
    setSelectedPromptHistoryDraftId(item?.draftId || "");
    onSelectGrokItem(item);
  }
  function selectPromptHistoryRow(item: GrokImagePromptDraftResponse) {
    selectPromptHistoryItem(item);
    promptHistoryListRef.current?.focus();
  }

  async function loadPromptHistory(targetPage = page) {
    const response = await apiClient.promptHistory({ page: targetPage, generationStatus: generationFilter, runpodStatus: runpodFilter, batchId: selectedPromptBatchJobId });
    setItems(response.items);
    setTotal(response.total);
    return response;
  }

  useEffect(() => {
    const query = promptBatchSearchText.trim();
    if (!query || (selectedPromptBatchJob && query === selectedPromptBatchJob.id)) {
      setPromptBatchCandidates([]);
      setPromptBatchSearchLoading(false);
      return;
    }
    let active = true;
    setPromptBatchSearchLoading(true);
    const timer = window.setTimeout(() => {
      apiClient.batchJobCandidates({ query, limit: 10 })
        .then((response) => {
          if (!active) return;
          setPromptBatchCandidates(response.items);
          setPromptBatchCandidateOpen(true);
        })
        .catch(() => {
          if (active) setPromptBatchCandidates([]);
        })
        .finally(() => {
          if (active) setPromptBatchSearchLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [promptBatchSearchText, selectedPromptBatchJob]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setNotice("");
    apiClient.promptHistory({ page, generationStatus: generationFilter, runpodStatus: runpodFilter, batchId: selectedPromptBatchJobId })
      .then((response) => {
        if (!active) return;
        setItems(response.items);
        setTotal(response.total);
      })
      .catch((error: Error) => {
        if (!active) return;
        setItems([]);
        setTotal(0);
        setNotice(error.message || "프롬프트 이력을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, generationFilter, runpodFilter, selectedPromptBatchJobId]);

  useEffect(() => {
    selectPromptHistoryItem(items[0] || null);
  }, [items]);

  useEffect(() => {
    if (!previewItem && !editingItem && !pendingRequeueItem) return;
    const closeModal = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || savingPrompt) return;
      setPreviewItem(null);
      setEditingItem(null);
      if (!retryingDraftId) setPendingRequeueItem(null);
    };
    window.addEventListener("keydown", closeModal);
    return () => window.removeEventListener("keydown", closeModal);
  }, [previewItem, editingItem, pendingRequeueItem, savingPrompt, retryingDraftId]);

  async function retryPromptHistoryItem(item: GrokImagePromptDraftResponse) {
    setRetryingDraftId(item.draftId);
    setNotice("");
    try {
      await apiClient.retryImagePromptDraft(item.draftId);
      const response = await loadPromptHistory(page);
      const updatedItem = response.items.find((candidate) => candidate.draftId === item.draftId) || item;
      selectPromptHistoryItem(updatedItem);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "프롬프트 재생성 요청에 실패했습니다.");
    } finally {
      setRetryingDraftId("");
    }
  }

  async function requeueRunpodForPrompt(item: GrokImagePromptDraftResponse) {
    setRetryingDraftId(item.draftId);
    setNotice("");
    try {
      await apiClient.requeueRunpodForPromptDraft(item.draftId);
      const response = await loadPromptHistory(page);
      selectPromptHistoryItem(response.items.find((candidate) => candidate.draftId === item.draftId) || item);
      setPendingRequeueItem(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "RunPod 재요청에 실패했습니다.");
    } finally {
      setRetryingDraftId("");
    }
  }

  async function savePromptEdit() {
    if (!editingItem) return;
    const normalized = editingPrompt.trim();
    if (!normalized) {
      setNotice("Positive Prompt를 입력하세요.");
      return;
    }
    setSavingPrompt(true);
    setNotice("");
    try {
      const failed = ["FAILED", "MANUAL_REQUIRED"].includes(String(editingItem.status || "").toUpperCase());
      let updated: GrokImagePromptDraftResponse;
      if (failed) {
        updated = await apiClient.repairImagePromptDraft(editingItem.draftId, normalized);
      } else {
        updated = await apiClient.updateImagePromptDraft(editingItem.draftId, { positivePrompt: normalized });
      }
      setItems((current) => current.map((item) => item.draftId === updated.draftId ? updated : item));
      selectPromptHistoryItem(updated);
      setEditingItem(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "프롬프트 저장에 실패했습니다.");
    } finally {
      setSavingPrompt(false);
    }
  }

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  const handlePromptHistoryListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isEditableKeyboardTarget(event.target)) return;
    const nextDraftId = nextListSelectionId(items, selectedPromptHistoryDraftId, event.key, (item) => item.draftId);
    if (nextDraftId === selectedPromptHistoryDraftId) return;
    const nextItem = items.find((item) => item.draftId === nextDraftId);
    if (!nextItem) return;
    event.preventDefault();
    selectPromptHistoryItem(nextItem);
  };

  return (
    <div className="v3-prompt-history-layout">
      <div
        ref={promptHistoryListRef}
        className="v3-card v3-prompt-history-card"
        role="listbox"
        aria-label="프롬프트 생성 이력"
        tabIndex={0}
        onKeyDown={handlePromptHistoryListKeyDown}
      >
      <div className="v3-card-header">
        <div className="v3-card-header-title">프롬프트 생성 이력</div>
        <span className="v3-card-header-meta">{total}건 · 10건 / 페이지</span>
      </div>
      <div className="v3-runpod-filter-bar">
        <label>프롬프트 생성<select value={generationFilter} onChange={(event) => { setGenerationFilter(event.target.value); setPage(1); }}><option value="">전체 결과</option><option value="SUCCESS">성공</option><option value="FAILED">실패</option></select></label>
        <label>RunPod<select value={runpodFilter} onChange={(event) => { setRunpodFilter(event.target.value); setPage(1); }}><option value="">전체 상태</option><option value="UNREQUESTED">미요청</option><option value="PENDING">대기/큐</option><option value="IN_PROGRESS">진행</option><option value="SUCCESS">완료</option><option value="FAILED">실패</option><option value="CANCELLED">취소</option></select></label>
        <label className="v3-batch-search-field">Batch ID
          <input
            value={promptBatchSearchText}
            onBlur={() => window.setTimeout(() => setPromptBatchCandidateOpen(false), 160)}
            onChange={(event) => {
              setPromptBatchSearchText(event.target.value);
              setSelectedPromptBatchJob(null);
              setPage(1);
            }}
            onFocus={() => {
              if (promptBatchSearchText.trim()) setPromptBatchCandidateOpen(true);
            }}
            placeholder="Batch ID / 작업자명 검색"
          />
          {selectedPromptBatchJob ? <span className="v3-batch-selected-label">선택됨 · {selectedPromptBatchJob.id}</span> : null}
          {promptBatchCandidateOpen && promptBatchSearchText.trim() && !selectedPromptBatchJob ? (
            <div className="v3-batch-candidate-list" role="listbox" aria-label="Batch ID 검색 결과">
              {promptBatchSearchLoading ? <div className="v3-batch-candidate-empty">검색 중...</div> : null}
              {!promptBatchSearchLoading && !promptBatchCandidates.length ? <div className="v3-batch-candidate-empty">검색 결과가 없습니다.</div> : null}
              {!promptBatchSearchLoading && promptBatchCandidates.map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  role="option"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    setSelectedPromptBatchJob(candidate);
                    setPromptBatchSearchText(candidate.id);
                    setPromptBatchCandidateOpen(false);
                    setPage(1);
                  }}
                >
                  <strong>{candidate.id}</strong>
                  <span>{candidate.createdByName || candidate.createdBy || "-"} · {candidate.sourceZipFileName || candidate.sourceDirName || "-"} · {candidate.workflowId}</span>
                </button>
              ))}
            </div>
          ) : null}
        </label>
      </div>
      <div className="v3-prompt-history-head">
        <span>No</span><span>작업자</span><span>KST 생성일</span><span>워크플로우</span><span>Batch ID</span><span>이미지</span><span>Positive Prompt</span><span>프롬프트 생성</span><span>RunPod</span><span>프롬프트 재생성</span>
      </div>
      {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>프롬프트 이력을 불러오는 중입니다...</p> : null}
      {notice ? <p className="v3-inline-error" style={{ margin: 16 }} role="alert">{notice}</p> : null}
      {!loading && !notice && !items.length ? <p className="v3-muted-text" style={{ padding: 16 }}>생성된 프롬프트 이력이 없습니다.</p> : null}
      {!loading && items.map((item, index) => {
        const generated = item.status === "READY";
        const normalizedStatus = String(item.status || "").toUpperCase();
        const generationLabel = normalizedStatus === "FAILED" || normalizedStatus === "MANUAL_REQUIRED" ? "FAILED" : generated ? "SUCCESS" : item.status || "-";
        const generationTone = normalizedStatus === "FAILED" || normalizedStatus === "MANUAL_REQUIRED" ? "is-failed" : generated ? "is-ready" : "is-pending";
        const promptTone = normalizedStatus === "FAILED" || normalizedStatus === "MANUAL_REQUIRED" ? "is-failed" : generated ? "is-success" : "";
        const displayBatchId = item.batchJobId || item.promptBatchId || "";
        const canRetry = Boolean(user?.id && item.createdBy === user.id);
        const canEditPrompt = ["READY", "FAILED", "MANUAL_REQUIRED"].includes(normalizedStatus) && Boolean(user?.id && (item.createdBy === user.id || canUse(user, "jobs:manage")));
        return (
          <div
            className={`v3-prompt-history-row ${selectedPromptHistoryDraftId === item.draftId ? "is-selected" : ""}`}
            key={item.draftId}
            role="option"
            aria-selected={selectedPromptHistoryDraftId === item.draftId}
            onClick={() => {
              selectPromptHistoryRow(item);
            }}
          >
            <span className="v3-review-seg-name">{(page - 1) * pageSize + index + 1}</span>
            <span className="v3-prompt-history-worker">{item.createdByName || item.createdBy || "-"}</span>
            <span className="v3-prompt-history-date">{formatKstDateOnly(item.createdAt)}</span>
            <span className="v3-prompt-history-workflow">{item.workflowId || "-"}</span>
            <span className="v3-prompt-history-batch-id" title={displayBatchId}>{displayBatchId || "-"}</span>
            <button className="v3-prompt-history-image v3-prompt-history-cell-button" type="button" title="이미지 미리보기" onClick={(event) => { event.stopPropagation(); setPreviewItem(item); }}>
              {item.assetId ? <ProtectedImage src={`/api/files/${item.assetId}`} alt={item.asset?.fileName || item.assetId} /> : <span>-</span>}
              <small>{item.assetId}</small>
            </button>
            <button className={`v3-review-prompt v3-prompt-history-cell-button ${canEditPrompt ? "is-editable" : ""} ${promptTone}`} type="button" disabled={!canEditPrompt} title={canEditPrompt ? "Positive Prompt 수정" : item.positivePrompt || item.error || ""} onClick={(event) => { event.stopPropagation(); if (canEditPrompt) { setEditingItem(item); setEditingPrompt(item.positivePrompt || ""); } }}>{generated ? item.positivePrompt || "-" : canEditPrompt ? "클릭하여 Positive Prompt 입력" : item.error || "-"}</button>
            <span className={`v3-status-badge ${generationTone}`}>{generationLabel}</span>
            {item.requeueRequired ? <button className="v3-text-link-button" type="button" disabled={retryingDraftId === item.draftId} onClick={(event) => { event.stopPropagation(); setPendingRequeueItem(item); }}>{retryingDraftId === item.draftId ? "요청 중" : "재요청"}</button> : <span className={`v3-status-badge ${runpodResultStatusTone(item.runpodStatus ?? undefined)}`}>{runpodStatusDisplay(item.runpodStatus, "미요청")}</span>}
            <button className="v3-text-link-button" type="button" disabled={!canRetry || retryingDraftId === item.draftId} onClick={(event) => { event.stopPropagation(); void retryPromptHistoryItem(item); }}>{retryingDraftId === item.draftId ? "요청 중" : "재생성"}</button>
          </div>
        );
      })}
      <div className="v3-pagination">
        <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {total}</span>
        <div className="v3-pagination-controls">
          <button className="v3-page-button" type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>이전</button>
          <span className="v3-page-button is-current">{page}</span>
          <button className="v3-page-button" type="button" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>다음</button>
        </div>
      </div>
      </div>
      {previewItem ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-label="프롬프트 원본 이미지 미리보기" onClick={() => setPreviewItem(null)}>
          <div className="v3-modal-panel v3-asset-preview-modal" onClick={(event) => event.stopPropagation()}>
            <div className="v3-panel-title-row"><div className="v3-panel-title">{previewItem.asset?.fileName || previewItem.assetId}</div><button className="v3-secondary-button" type="button" onClick={() => setPreviewItem(null)}>닫기</button></div>
            <ProtectedAssetPreview src={`/api/files/${previewItem.assetId}`} isVideo={false} alt={previewItem.asset?.fileName || previewItem.assetId} />
          </div>
        </div>
      ) : null}
      {editingItem ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="promptRecoveryTitle">
          <div className="v3-modal-panel v3-prompt-edit-modal">
            <div className="v3-panel-title-row"><div id="promptRecoveryTitle" className="v3-panel-title">{["FAILED", "MANUAL_REQUIRED"].includes(String(editingItem.status || "").toUpperCase()) ? "실패 프롬프트 수동 입력" : "Positive Prompt 수정"}</div><button className="v3-secondary-button" type="button" disabled={savingPrompt} onClick={() => setEditingItem(null)}>닫기</button></div>
            <p className="v3-muted-text">{["FAILED", "MANUAL_REQUIRED"].includes(String(editingItem.status || "").toUpperCase()) ? "저장한 프롬프트는 RunPod ComfyUI 요청 목록에 표시됩니다. 영상 요청은 해당 화면에서 사용자가 직접 처리합니다." : "수정한 Positive Prompt를 저장합니다. 기존 RunPod 작업은 다시 제출하지 않습니다."}</p>
            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>작업자</span><strong>{editingItem.createdByName || editingItem.createdBy || "-"}</strong></div>
              <div className="v3-summary-row"><span>파일</span><strong>{editingItem.asset?.fileName || editingItem.assetId}</strong></div>
              {["FAILED", "MANUAL_REQUIRED"].includes(String(editingItem.status || "").toUpperCase()) ? <div className="v3-summary-row"><span>실패 사유</span><strong>{editingItem.error || "Positive Prompt 없음"}</strong></div> : null}
              {user?.id !== editingItem.createdBy ? <div className="v3-summary-row"><span>수정 권한</span><strong>관리자 수정</strong></div> : null}
            </div>
            <textarea className="v3-prompt-edit-textarea" aria-label="Positive Prompt" value={editingPrompt} onChange={(event) => setEditingPrompt(event.target.value)} autoFocus />
            <div className="v3-modal-actions"><button className="v3-secondary-button" type="button" disabled={savingPrompt} onClick={() => setEditingItem(null)}>취소</button><button className="v3-primary-button" type="button" disabled={savingPrompt || !editingPrompt.trim()} onClick={() => void savePromptEdit()}>{savingPrompt ? "저장 중" : "저장"}</button></div>
          </div>
        </div>
      ) : null}
      {pendingRequeueItem ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-label="RunPod 영상 재요청 확인" onClick={() => { if (!retryingDraftId) setPendingRequeueItem(null); }}>
          <div className="v3-modal-panel v3-batch-confirm-modal v3-runpod-requeue-confirm-modal" onClick={(event) => event.stopPropagation()}>
            <div className="v3-panel-title-row">
              <div className="v3-panel-title">RunPod 영상 재요청</div>
              <button className="v3-secondary-button" type="button" disabled={Boolean(retryingDraftId)} onClick={() => setPendingRequeueItem(null)}>닫기</button>
            </div>
            <p className="v3-modal-confirm-message">기존 영상이 있는 경우 덮어쓰기가 됩니다. 진행하시겠습니까?</p>
            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>작업자</span><strong>{pendingRequeueItem.createdByName || pendingRequeueItem.createdBy || "-"}</strong></div>
              <div className="v3-summary-row"><span>파일</span><strong>{pendingRequeueItem.asset?.fileName || pendingRequeueItem.assetId}</strong></div>
            </div>
            <div className="v3-modal-actions">
              <button className="v3-secondary-button" type="button" disabled={Boolean(retryingDraftId)} onClick={() => setPendingRequeueItem(null)}>취소</button>
              <button className="v3-primary-button" type="button" disabled={Boolean(retryingDraftId)} onClick={() => void requeueRunpodForPrompt(pendingRequeueItem)}>{retryingDraftId ? "요청 중" : "확인"}</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PromptGrokResponseDetail({ item }: { item: GrokImagePromptDraftResponse | null }) {
  if (!item) {
    return <p className="v3-muted-text">왼쪽 목록에서 작업을 선택하세요.</p>;
  }

  return (
    <>
      <div className="v3-panel-title-row">
        <div className="v3-panel-title">Grok API 응답</div>
        <span className="v3-card-header-meta">{item.draftId}</span>
      </div>
      <div className="v3-prompt-api-detail">
        <div><span>Model</span><strong>{item.grokResponse?.model || item.model || "-"}</strong></div>
        <div><span>Endpoint</span><strong>{compactEndpoint(item.grokResponse?.endpoint)}</strong></div>
        <div><span>Usage</span><strong>{formatGrokUsage(item.grokResponse)}</strong></div>
        <div><span>Image Type</span><strong>{item.imageType || "-"}</strong></div>
        <div><span>Warnings</span><strong>{item.warnings?.length ? item.warnings.join(" · ") : "-"}</strong></div>
        <div><span>Error</span><strong>{item.error || "-"}</strong></div>
      </div>
    </>
  );
}

function formatRunpodSeconds(value?: number | string | null) {
  if (value === undefined || value === null || value === "") return "-";
  const seconds = Number(value);
  return Number.isFinite(seconds) ? `${seconds.toFixed(seconds % 1 ? 1 : 0)}s` : String(value);
}

function compactEndpoint(value?: string | null) {
  if (!value) return "endpoint -";
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

function formatGrokUsage(response: GrokImagePromptDraftResponse["grokResponse"]) {
  if (!response) return "응답 메타데이터 없음";
  const latency = response.latencyMs == null ? "-" : `${(response.latencyMs / 1000).toFixed(1)}s`;
  return `${latency} · in ${response.inputTokens ?? "-"} · out ${response.outputTokens ?? "-"}`;
}

function uniqueModelReferences(references: TaskModelReference[]): TaskModelReference[] {
  const seen = new Set<string>();
  return references.filter((reference) => {
    const key = [reference.bucket, reference.nodeId, reference.field, reference.value].join("\u0000");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function modelBucketLabel(bucket: string): string {
  const labels: Record<string, string> = {
    checkpoints: "CHECKPOINT",
    vae: "VAE",
    loras: "LORA",
    text_encoders: "CLIP",
    unet: "UNET",
    video_models: "VIDEO MODEL",
    models: "MODEL"
  };
  return labels[bucket] || bucket.toUpperCase();
}

export const PROMPT_REVIEW_FLAGS: Array<[keyof TaskPromptReviewFlags, string]> = [
  ["originalPreserved", "원본 유지"],
  ["naturalMotion", "자연스런 동작"],
  ["noDistortion", "왜곡 없음"],
  ["backgroundStable", "배경 안정"],
  ["colorStable", "색감 안정"]
];

function normalizeReviewFlags(flags: TaskPromptReviewFlags | undefined): TaskPromptReviewFlags {
  return {
    originalPreserved: Boolean(flags?.originalPreserved || flags?.intentMatched || flags?.identityPreserved),
    naturalMotion: Boolean(flags?.naturalMotion),
    noDistortion: Boolean(flags?.noDistortion),
    backgroundStable: Boolean(flags?.backgroundStable),
    colorStable: Boolean(flags?.colorStable)
  };
}

// 3f 전용 v3 평가 카드. 구버전 PromptReviewCard/PromptFeedbackCard(E-06에서 제거)와
// 저장 로직은 동일(B-02: task_prompts ↔ prompt_feedback 역할 분리)하되 v3 토큰으로
// 다시 그렸다. PROMPT_REVIEW_FLAGS는 원래 그 구버전 카드들 사이에 정의돼 있었지만
// 이 v3 카드도 함께 쓰는 공유 상수라 E-06에서 살아남아 이 근처로 옮겨왔다.
export function V3PromptReviewGroup({
  prompt,
  loading,
  canReview,
  canGiveFeedback,
  onSave,
  onSaveFeedback
}: {
  prompt: TaskPromptItem;
  loading: boolean;
  canReview: boolean;
  canGiveFeedback: boolean;
  onSave: (segmentIndex: number, payload: Record<string, unknown>) => void;
  onSaveFeedback: (outputId: string, payload: { rating?: number; notes?: string }) => void;
}) {
  const [rating, setRating] = useState(String(prompt.qualityRating || ""));
  const [reuseEligible, setReuseEligible] = useState(Boolean(prompt.reuseEligible));
  const [flags, setFlags] = useState<TaskPromptReviewFlags>(() => normalizeReviewFlags(prompt.reviewFlags));
  const [comment, setComment] = useState(prompt.qualityComment || "");
  const existingFeedback = prompt.promptFeedback || null;
  const [feedbackRating, setFeedbackRating] = useState(String(existingFeedback?.rating || ""));
  const [feedbackNotes, setFeedbackNotes] = useState(existingFeedback?.notes || "");

  useEffect(() => {
    setRating(String(prompt.qualityRating || ""));
    setReuseEligible(Boolean(prompt.reuseEligible));
    setFlags(normalizeReviewFlags(prompt.reviewFlags));
    setComment(prompt.qualityComment || "");
    setFeedbackRating(String(existingFeedback?.rating || ""));
    setFeedbackNotes(existingFeedback?.notes || "");
  }, [prompt.id]);

  const hasReviewReason = PROMPT_REVIEW_FLAGS.some(([key]) => Boolean(flags[key]));
  const hasComment = Boolean(comment.trim());
  const saveDisabled = loading || !canReview || !rating || (!hasReviewReason && !hasComment);

  return (
    <div className="v3-review-card">
      <div className="v3-card-header">
        <span className="v3-label">SEG {prompt.segmentIndex}</span>
        <span className="v3-card-header-meta">{rating ? "reviewed" : "unreviewed"}</span>
      </div>
      <div className="v3-prompt-text-block">{prompt.positivePrompt || "-"}</div>
      <div className="v3-label">평가 등급 · 필수</div>
      <div className="v3-rating-row">
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            className={`v3-rating-pill ${String(value) === rating ? "is-selected" : ""}`}
            onClick={() => setRating(String(value))}
          >
            {value}
          </button>
        ))}
      </div>
      {!rating ? <p className="v3-inline-notice">평가 등급을 선택하세요.</p> : null}
      <div className="v3-label">평가 사유</div>
      <div className="v3-term-chip-row">
        {PROMPT_REVIEW_FLAGS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`v3-term-chip ${flags[key] ? "is-selected" : ""}`}
            onClick={() => setFlags((current) => ({ ...current, [key]: !current[key] }))}
          >
            {label}
          </button>
        ))}
      </div>
      <label className="v3-checklist-item is-done" style={{ cursor: "pointer" }}>
        <input type="checkbox" checked={reuseEligible} onChange={(event) => setReuseEligible(event.target.checked)} style={{ marginRight: 4 }} />
        재사용 가능 — Prompt Library에 등록
      </label>
      {!hasReviewReason && !hasComment ? <p className="v3-inline-notice">평가 사유를 하나 이상 선택하거나 코멘트를 입력하세요.</p> : null}
      <textarea className="v3-scene-textarea" rows={2} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="품질 판단, 재사용 조건, 보완점" />
      <button
        className="v3-primary-button"
        type="button"
        disabled={saveDisabled}
        onClick={() => onSave(prompt.segmentIndex, { qualityRating: rating, qualityComment: comment, reuseEligible, reviewFlags: flags })}
      >
        평가 저장 · 재사용 등록
      </button>

      {prompt.promptGenerationOutputId ? (
        <div className="v3-feedback-block">
          <div className="v3-label">프롬프트 생성 품질 · {prompt.modelName || "Qwen"}</div>
          <div className="v3-rating-row">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                className={`v3-rating-pill ${String(value) === feedbackRating ? "is-selected" : ""}`}
                disabled={!canGiveFeedback}
                onClick={() => setFeedbackRating(String(value))}
              >
                {value}
              </button>
            ))}
          </div>
          <textarea className="v3-scene-textarea" rows={2} disabled={!canGiveFeedback} value={feedbackNotes} onChange={(event) => setFeedbackNotes(event.target.value)} placeholder="생성된 프롬프트 자체의 품질 메모" />
          <button
            className="v3-secondary-button"
            type="button"
            disabled={loading || !canGiveFeedback}
            onClick={() => onSaveFeedback(prompt.promptGenerationOutputId as string, { rating: feedbackRating ? Number(feedbackRating) : undefined, notes: feedbackNotes.trim() || undefined })}
          >
            프롬프트 품질 평가 저장
          </button>
        </div>
      ) : null}
    </div>
  );
}

// E-03 · 4c "프롬프트 재사용" — design_handoff_dobedub_v3/3 Review.dc.html의
// 세 번째 화면. 검색·목록·적용 로직은 기존 searchPromptReuse/applyReusablePrompt를
// 그대로 재사용하고(`GET /api/prompts/reusable`), 화면만 새로 짰다.
// 2026-08-11: 카드 그리드 → 리스트로 전환 + 서버사이드 페이지네이션(고정
// 20건/페이지) 추가. 3a 작업 이력(Create3aScreen)이 쓰는
// `.v3-review-table-head/-row` + `.v3-pagination` 패턴을 그대로 재사용한다 -
// 카드 하나가 담던 정보(워크플로·세그먼트, Rating, 프롬프트 본문, 사유 칩,
// Task ID, Model, 적용 버튼)를 한 줄로 압축했다. 프롬프트 본문은 한 줄
// 말줄임(`title` 속성으로 전체 텍스트는 hover 시 노출)으로 바꿨다 - 여러 줄
// 카드 본문을 표 행에 그대로 넣으면 행 높이가 들쭉날쭉해진다.
export function Create4cScreen({
  user,
  health,
  onGoTo,
  keyword,
  items,
  loading,
  notice,
  page,
  pageSize,
  total,
  workflowName,
  targetSegmentName,
  onKeywordChange,
  onSearch,
  onPageChange,
  onApply
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  keyword: string;
  items: TaskPromptItem[];
  loading: boolean;
  notice: string;
  page: number;
  pageSize: number;
  total: number;
  workflowName: string;
  targetSegmentName: string;
  onKeywordChange: (value: string) => void;
  onSearch: () => void;
  onPageChange: (page: number) => void;
  onApply: (prompt: TaskPromptItem) => void;
}) {
  const [expandedModelPromptIds, setExpandedModelPromptIds] = useState<Record<number, boolean>>({});

  function reviewReasons(prompt: TaskPromptItem) {
    const flags = normalizeReviewFlags(prompt.reviewFlags);
    return PROMPT_REVIEW_FLAGS.filter(([key]) => Boolean(flags[key])).map(([, label]) => label);
  }

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  // 2026-08-11: 사용자 요청 - 정보 항목을 워크플로/시작·다음 이미지/포지티브·
  // 네거티브 프롬프트/사유/코멘트/레이팅/생성자/모델명 9개로 재구성. "적용"은
  // 한 번 컬럼을 없애고 행 클릭으로 대체했다가, 사용자 요청으로 다시 버튼
  // 컬럼으로 복구했다.
  const gridColumns = "108px 172px minmax(0,1.3fr) minmax(0,1fr) 140px 130px 54px 88px minmax(160px,0.7fr) 72px";

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="promptLibrary"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`대상 워크플로 · ${workflowName || "-"} · 적용 대상 ${targetSegmentName}`}
      headerTitle="프롬프트 재사용"
      headerActions={
        <>
          <input
            className="v3-search-input"
            value={keyword}
            onChange={(event) => onKeywordChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSearch();
            }}
            placeholder="프롬프트, 코멘트, 재사용 사유, task 검색"
          />
          <button className="v3-primary-button" type="button" disabled={loading} onClick={onSearch}>
            {loading ? "Searching..." : "Search"}
          </button>
        </>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-card" style={{ overflowX: "auto" }}>
        <div className="v3-review-table-head" style={{ gridTemplateColumns: gridColumns, minWidth: 980 }}>
          <span>워크플로</span><span>시작 → 다음 이미지</span><span>프롬프트 (Positive)</span><span>프롬프트 (Negative)</span><span>평가 사유</span><span>코멘트</span><span>레이팅</span><span>생성자</span><span>모델 정보</span><span style={{ textAlign: "center" }}>재사용</span>
        </div>
        {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {!loading && !items.length ? (
          <p className="v3-muted-text" style={{ padding: 16 }}>재사용 가능으로 등록된 프롬프트가 없습니다. Task History에서 작업을 선택해 Prompt Review 아코디언에서 평가·재사용 등록을 먼저 진행하세요.</p>
        ) : null}
        {!loading && items.map((prompt) => {
          const reasons = reviewReasons(prompt);
          const startAsset = (prompt.inputAssets || [])[0];
          const endAsset = (prompt.inputAssets || [])[1];
          const selectedModelReferences = uniqueModelReferences(prompt.modelReferences || []);
          const modelReferences = selectedModelReferences.length
            ? selectedModelReferences
            : prompt.modelName || prompt.modelProfileId
            ? [{ bucket: "models", value: prompt.modelName || prompt.modelProfileId || "-" }]
            : [];
          const isModelInfoExpanded = Boolean(expandedModelPromptIds[prompt.id]);
          return (
            <div
              className="v3-review-table-row"
              style={{ gridTemplateColumns: gridColumns, minWidth: 980 }}
              key={prompt.id}
            >
              <span className="v3-review-seg-name">{prompt.workflowId}<br /><span className="v3-muted-text">Segment {prompt.segmentIndex}</span></span>
              <span className="v3-kf-pair v3-kf-pair-sm">
                <span className="v3-kf-thumb v3-kf-thumb-sm">
                  {startAsset?.assetId ? <ProtectedImage src={`/api/files/${startAsset.assetId}`} alt="시작 이미지" /> : <span>-</span>}
                </span>
                <span className="v3-kf-arrow">→</span>
                <span className="v3-kf-thumb v3-kf-thumb-sm">
                  {endAsset?.assetId ? <ProtectedImage src={`/api/files/${endAsset.assetId}`} alt="다음 이미지" /> : <span>-</span>}
                </span>
              </span>
              <span className="v3-reuse-prompt-cell">
                {prompt.positivePrompt || "-"}
              </span>
              <span className="v3-reuse-prompt-cell">
                {prompt.negativePrompt || "-"}
              </span>
              <span>
                {reasons.length ? (
                  <ol className="v3-reuse-reason-list">
                    {reasons.map((reason) => <li key={reason}>{reason}</li>)}
                  </ol>
                ) : (
                  <span className="v3-muted-text">사유 없음</span>
                )}
              </span>
              <span
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={prompt.qualityComment || "-"}
              >
                {prompt.qualityComment || "-"}
              </span>
              <span>
                <span className="v3-status-badge is-ready">{prompt.qualityRating || "-"}</span>
              </span>
              <span style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={prompt.createdBy || "-"}>
                {prompt.createdBy || "-"}
              </span>
              <span className="v3-reuse-model-info">
                {modelReferences.length ? (
                  <>
                    <button
                      className="v3-reuse-model-toggle"
                      type="button"
                      aria-expanded={isModelInfoExpanded}
                      onClick={() => setExpandedModelPromptIds((current) => ({ ...current, [prompt.id]: !current[prompt.id] }))}
                    >
                      <span>모델 {modelReferences.length}개</span>
                      <span aria-hidden="true">{isModelInfoExpanded ? "−" : "+"}</span>
                    </button>
                    {isModelInfoExpanded ? (
                      <span className="v3-reuse-model-list">
                        {modelReferences.map((reference) => (
                          <span key={`${reference.bucket}-${reference.nodeId}-${reference.field}-${reference.value}`} title={`${modelBucketLabel(reference.bucket)}: ${reference.value}`}>
                            <b>{modelBucketLabel(reference.bucket)}</b> {reference.value}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </>
                ) : <span className="v3-muted-text">-</span>}
              </span>
              <span style={{ textAlign: "center" }}>
                <button className="v3-text-link-button" type="button" onClick={() => onApply(prompt)}>재사용</button>
              </span>
            </div>
          );
        })}
        {total > pageSize ? (
          <div className="v3-pagination">
            <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {total}</span>
            <div className="v3-pagination-controls">
              <button className="v3-page-button" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>이전</button>
              <span className="v3-page-button is-current">{page}</span>
              <button className="v3-page-button" type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>다음</button>
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}

// E-03 · 5a "Asset 관리" — design_handoff_dobedub_v3/3 Review.dc.html의 자산
// 그리드(5a)와 컬렉션(5c) 두 화면이었던 것을 2026-08-11 사용자 요청으로 하나로
// 합쳤다: "asset을 output 기준으로 관리, asset은 output에 input 이미지가
// 종속되는 구조로 변경, asset과 collection을 Asset 관리로 통합, Asset 하위
// 카테고리에 collection(미분류 포함)을 가지며 각 하위 카테고리는 목록기반
// 정보구조로 구성"(첨부 목업 참조). 백엔드도 함께 바뀌었다 - `GET /api/assets`가
// 이제 `assets` 테이블 전체가 아니라 `task_output_assets`에 연결된 출력 자산만
// 최상위로 내려주고(`list_assets`, task_tracking_service.py), 같은 작업의
// 입력 이미지는 각 출력 행 안에 `inputAssets`로 종속되어 함께 온다. 한 번도
// 출력으로 이어지지 못한 입력 전용 업로드(중단된 작업의 키프레임 등)는 사용자
// 결정에 따라 이 화면에서 제외한다(출력 자산 목록이 원래 대상이 아님).
//
// 설계 원본과 다르게 뺀 것 — 전부 대응 백엔드가 없어서 뺐다(가짜 데이터 금지 원칙):
// - 태그(#가을 #야외 등), 공개 범위(PRIVATE/SHARED 토글) — `assets` 테이블에 대응
//   컬럼이 없음.
// - 저장 용량 진행 바("184/500 GB") — 총 한도 값을 내려주는 API가 없음.
// - "업로드" 버튼 — 업로드는 `2a` 키프레임 슬롯에서만 발생하는 것이 현재 흐름.
// - 정렬 드롭다운 — API가 `created_at desc` 고정 정렬만 지원.
// 컬렉션 소속은 다대다로 유지(사용자 선택 - 자산 하나가 여러 컬렉션에 동시에 속할
// 수 있음) — 그래서 "Collection" 열은 단일 선택 대신 칩 목록 + 추가/제거로 구현.
export function Create5aScreen({
  user,
  health,
  onGoTo,
  items,
  page,
  pageCount,
  pageSize,
  total,
  allTotal,
  loading,
  notice,
  collections,
  uncategorizedTotal,
  collectionFilter,
  createName,
  onCollectionFilterChange,
  onCreateNameChange,
  onCreateCollection,
  onDeleteCollection,
  onAddToCollection,
  onRemoveFromCollection,
  onPageChange,
  onPageSizeChange,
  onDownload
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  items: AssetItem[];
  page: number;
  pageCount: number;
  pageSize: 20 | 50;
  total: number;
  allTotal: number;
  loading: boolean;
  notice: string;
  collections: CollectionSummary[];
  uncategorizedTotal: number;
  collectionFilter: number | "uncategorized" | "";
  createName: string;
  onCollectionFilterChange: (value: number | "uncategorized" | "") => void;
  onCreateNameChange: (value: string) => void;
  onCreateCollection: () => void;
  onDeleteCollection: (collection: CollectionSummary) => void;
  onAddToCollection: (assetId: string, collectionId: number) => void;
  onRemoveFromCollection: (assetId: string, collectionId: number) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: 20 | 50) => void;
  onDownload: (item: AssetItem) => void;
}) {
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  // 2026-08-12: "미리보기" 버튼이 기능 없이 정적 썸네일/배지만 보여주고 있었다는
  // 지적 + 위치를 앞으로 옮겨달라는 요청 - Asset ID 바로 다음(Collection·Asset
  // 이름·생성일·생성자보다 앞)으로 옮기고, 클릭하면 큰 미리보기 모달을 연다
  // (이미지는 확대 이미지, 영상 출력은 controls 있는 <video>로 재생 - 목록
  // 썸네일에서는 <img>가 영상을 못 그려 배지만 보이던 문제도 여기서 해소됨).
  // Asset 이름은 한 줄 말줄임으로 충분하므로 폭을 제한하고, KST/UTC를 모두
  // 표시하는 생성일 열에 공간을 우선 배분한다. 입력 썸네일도 셀 안에서 유지된다.
  const gridColumns = "148px 104px 62px minmax(140px, 0.55fr) 198px 82px 148px 68px";
  const [previewItem, setPreviewItem] = useState<AssetItem | null>(null);
  const previewIsImage = previewItem ? (previewItem.mimeType || "").startsWith("image/") : false;

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="assets"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="ASSETS"
      headerTitle={`컬렉션 관리 · 전체 ${total}개`}
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <section className="v3-collection-management" aria-label="컬렉션 관리">
        <div className="v3-collection-management-heading">
          <div>
            <span className="v3-label">COLLECTION MANAGEMENT</span>
            <h2>컬렉션 관리</h2>
          </div>
          <span className="v3-collection-management-count">{collections.length}개 컬렉션</span>
        </div>
        <div className="v3-collection-management-form">
          <label htmlFor="new-collection-name">새 컬렉션 이름</label>
          <input
            id="new-collection-name"
            className="v3-search-input"
            value={createName}
            placeholder="예: 광고 시안, 검수 완료"
            onChange={(event) => onCreateNameChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && createName.trim()) {
                onCreateCollection();
              }
            }}
          />
          <button className="v3-primary-button" type="button" disabled={!createName.trim()} onClick={onCreateCollection}>컬렉션 만들기</button>
        </div>
        <div className="v3-collection-management-list" aria-label="컬렉션 목록 필터">
          <button
            type="button"
            className={`v3-collection-management-item v3-collection-filter-row ${collectionFilter === "" ? "is-active" : ""}`}
            onClick={() => onCollectionFilterChange("")}
          >
            <span>전체 목록</span>
            <small>{allTotal}개 자산</small>
          </button>
          <button
            type="button"
            className={`v3-collection-management-item v3-collection-filter-row ${collectionFilter === "uncategorized" ? "is-active" : ""}`}
            onClick={() => onCollectionFilterChange("uncategorized")}
          >
            <span>미분류</span>
            <small>{uncategorizedTotal}개 자산</small>
          </button>
          {collections.map((collection) => (
            <div
              role="button"
              tabIndex={0}
              className={`v3-collection-management-item v3-collection-filter-row ${collectionFilter === collection.id ? "is-active" : ""}`}
              key={collection.id}
              onClick={() => onCollectionFilterChange(collection.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onCollectionFilterChange(collection.id);
                }
              }}
            >
              <span>{collection.name}</span>
              <small>{collection.itemCount}개 자산</small>
              <button
                type="button"
                className="v3-collection-delete-button"
                onClick={(event) => { event.stopPropagation(); onDeleteCollection(collection); }}
              >
                삭제
              </button>
            </div>
          ))}
        </div>
      </section>
      <div className="v3-card" style={{ overflowX: "auto" }}>
        <div className="v3-review-table-head" style={{ gridTemplateColumns: gridColumns, minWidth: 1080 }}>
          <span>Collection</span><span>Asset ID</span><span>미리보기</span><span>Asset 이름</span><span>생성일</span><span>생성자</span><span>입력 이미지</span><span style={{ textAlign: "right" }}>다운로드</span>
        </div>
        {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {!loading && !items.length ? <p className="v3-muted-text" style={{ padding: 16 }}>표시할 자산이 없습니다.</p> : null}
        {!loading && items.map((item) => {
          const itemCollectionIds = new Set((item.collections || []).map((c) => c.id));
          const availableToAdd = collections.filter((c) => !itemCollectionIds.has(c.id));
          const isImage = (item.mimeType || "").startsWith("image/");
          const isVideo = (item.mimeType || "").startsWith("video/");
          return (
            <div className="v3-review-table-row" style={{ gridTemplateColumns: gridColumns, minWidth: 1080 }} key={item.assetId}>
              <span>
                <div className="v3-asset-collection-chips">
                  {(item.collections || []).length ? (item.collections || []).map((c) => (
                    <span className="v3-asset-collection-chip" key={c.id}>
                      {c.name}
                      <button
                        type="button"
                        className="v3-asset-collection-chip-remove"
                        title={`${c.name}에서 빼기`}
                        onClick={() => onRemoveFromCollection(item.assetId, c.id)}
                      >
                        ×
                      </button>
                    </span>
                  )) : <span className="v3-muted-text">미분류</span>}
                </div>
                {availableToAdd.length ? (
                  <select
                    className="v3-asset-collection-add"
                    value=""
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      if (value) onAddToCollection(item.assetId, value);
                      event.target.value = "";
                    }}
                  >
                    <option value="">+ 컬렉션에 담기</option>
                    {availableToAdd.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                ) : null}
              </span>
              <span className="v3-review-seg-name" title={item.assetId}>{item.assetId.slice(0, 12)}</span>
              <span className="v3-asset-preview-cell">
                <button
                  type="button"
                  className="v3-kf-thumb v3-kf-thumb-xs v3-asset-preview-trigger"
                  title="미리보기"
                  onClick={() => setPreviewItem(item)}
                >
                  {isImage ? (
                    <ProtectedImage src={`/api/files/${item.assetId}`} alt={item.fileName} />
                  ) : isVideo ? (
                    <ProtectedVideoThumb src={`/api/files/${item.assetId}`} alt={item.fileName} />
                  ) : (
                    <span>{(item.type || item.mimeType || "FILE").toUpperCase().slice(0, 4)}</span>
                  )}
                </button>
              </span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.fileName}>
                {item.fileName}
              </span>
              <span className="v3-timestamp-cell">{formatTimestamp(item.createdAtKst || item.createdAt, item.createdAtUtc)}</span>
              <span style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.createdBy || "-"}>
                {item.createdBy || "-"}
              </span>
              <span className="v3-asset-input-row">
                {(item.inputAssets || []).length ? (item.inputAssets || []).map((input) => (
                  <span className="v3-kf-thumb v3-kf-thumb-sm" key={input.assetId} title={input.fileName}>
                    <ProtectedImage src={`/api/files/${input.assetId}`} alt={input.fileName} />
                  </span>
                )) : <span className="v3-muted-text">-</span>}
              </span>
              <span style={{ textAlign: "right" }}>
                <button className="v3-text-link-button" type="button" onClick={() => onDownload(item)}>다운로드</button>
              </span>
            </div>
          );
        })}
      </div>
      <div className="v3-pagination">
        <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {total}</span>
        <div className="v3-pagination-controls">
          <button className="v3-page-button" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>이전</button>
          <span className="v3-page-button is-current">{page}</span>
          <button className="v3-page-button" type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>다음</button>
          <select className="v3-page-size-select" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value) as 20 | 50)}>
            <option value={20}>20건 / 페이지</option>
            <option value={50}>50건 / 페이지</option>
          </select>
        </div>
      </div>
      {previewItem ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="v3AssetPreviewTitle" onClick={() => setPreviewItem(null)}>
          <div className="v3-modal-panel v3-modal-panel-media" onClick={(event) => event.stopPropagation()}>
            <div className="v3-modal-media-head">
              <h2 id="v3AssetPreviewTitle" className="v3-modal-title" title={previewItem.assetId}>{previewItem.fileName}</h2>
              <button className="v3-icon-button" type="button" onClick={() => setPreviewItem(null)} aria-label="닫기">×</button>
            </div>
            <div className="v3-modal-media-body">
              <ProtectedAssetPreview src={`/api/files/${previewItem.assetId}`} isVideo={!previewIsImage} alt={previewItem.fileName} />
            </div>
            <div className="v3-modal-media-actions">
              <button className="v3-secondary-button" type="button" onClick={() => onDownload(previewItem)}>다운로드</button>
            </div>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
