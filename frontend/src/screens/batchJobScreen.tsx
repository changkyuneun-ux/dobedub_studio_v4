import React, { ChangeEvent, useEffect, useRef, useState } from "react";
import { apiClient, BatchJobDetailItemResponse, BatchJobDetailResponse, BatchJobResponse, HealthResponse, WorkflowItem } from "../api/client";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { ProtectedImage } from "../components/ProtectedAssets";
import { shellNavigate } from "../helpers/navigation";
import { StudioRoute } from "../router";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; workflows: WorkflowItem[] };

const FRAME_OPTIONS = [49, 81, 161];
const PAGE_SIZE = 5;
const RECOVERY_PAGE_SIZE = 10;
const DEFAULT_REQUESTED_FRAMES = 161;
const DEFAULT_FRAME_DURATION_LABEL = "161f · 10초";
const PAGE_COUNT_FORMAT_LABEL = "1 / 4 페이지";

const workflowName = (workflow: WorkflowItem | undefined, fallback = "") => workflow?.label || workflow?.name || workflow?.id || fallback;

function frameSeconds(frames: number) {
  return Math.max(1, Math.round(frames / 16));
}

function formatFrameDuration(frames: number) {
  if (frames === DEFAULT_REQUESTED_FRAMES) return DEFAULT_FRAME_DURATION_LABEL;
  return `${frames}f · ${frameSeconds(frames)}초`;
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function fileSizeLabel(file: File | null) {
  if (!file) return "선택된 ZIP 파일 없음";
  const mb = file.size / (1024 * 1024);
  return `${file.name} · ${mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`}`;
}

function statusLabel(status: string) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "COMPLETE" || normalized === "COMPLETED" || normalized === "SUCCESS") return "완료";
  if (normalized === "INCOMPLETE" || normalized === "IN_PROGRESS" || normalized === "QUEUED") return "진행 중";
  if (normalized === "FAILED" || normalized === "PARTIAL_FAILED") return "실패";
  return normalized || "-";
}

function metricPill(value: number, tone: "gray" | "blue" | "green" | "yellow" | "red" = "gray") {
  return <span className={`v3-batch-metric-pill is-${tone}`}>{value}</span>;
}

function retryStatusTone(status: string) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "READY" || normalized === "COMPLETED" || normalized === "SUCCESS") return "is-ready";
  if (normalized === "FAILED" || normalized === "CANCELLED" || normalized === "TIMED_OUT") return "is-failed";
  if (normalized === "PENDING_SUBMIT" || normalized === "DISPATCHING" || normalized === "QUEUED" || normalized === "IN_QUEUE") return "is-pending";
  if (normalized === "IN_PROGRESS" || normalized === "RUNNING" || normalized === "GENERATING") return "is-running";
  return "is-muted";
}

function retryItemKey(item: BatchJobDetailItemResponse) {
  return item.id || `${item.promptDraftId || ""}:${item.taskId || ""}`;
}

function isRecoveryErrorItem(item: BatchJobDetailItemResponse) {
  if (item.retryKind === "prompt" || item.retryKind === "runpod") return true;
  if (String(item.error || "").trim()) return true;
  const promptStatus = String(item.promptStatus || "").toUpperCase();
  const runpodStatus = String(item.runpodStatus || "").toUpperCase();
  if (["FAILED", "MANUAL_REQUIRED"].includes(promptStatus)) return true;
  if (["FAILED", "CANCELLED", "TIMED_OUT"].includes(runpodStatus)) return true;
  return false;
}

export function BatchJobScreen({ user, health: _health, onGoTo, workflows }: Props) {
  const [workflowId, setWorkflowId] = useState(workflows[0]?.id || "");
  const [requestedFrames, setRequestedFrames] = useState(DEFAULT_REQUESTED_FRAMES);
  const [workflowDefaultNegativePrompt, setWorkflowDefaultNegativePrompt] = useState("");
  const [batchNegativePrompt, setBatchNegativePrompt] = useState("");
  const [instructionStatus, setInstructionStatus] = useState<{ configured: boolean; count: number } | null>(null);
  const [selectedZipFile, setSelectedZipFile] = useState<File | null>(null);
  const [activeJobs, setActiveJobs] = useState<BatchJobResponse[]>([]);
  const [history, setHistory] = useState<BatchJobResponse[]>([]);
  const [workers, setWorkers] = useState<Array<{ workerId: string; workerName: string }>>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [workerFilter, setWorkerFilter] = useState("");
  const [historyDate, setHistoryDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [confirmingBatch, setConfirmingBatch] = useState(false);
  const [recoveryDetail, setRecoveryDetail] = useState<BatchJobDetailResponse | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [selectedRecoveryKeys, setSelectedRecoveryKeys] = useState<string[]>([]);
  const [recoveryPage, setRecoveryPage] = useState(1);
  const [recoveryPreview, setRecoveryPreview] = useState<{ src: string; alt: string } | null>(null);
  const zipInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!workflowId && workflows[0]?.id) {
      setWorkflowId(workflows[0].id);
    }
  }, [workflowId, workflows]);

  useEffect(() => {
    if (!workflowId) {
      setWorkflowDefaultNegativePrompt("");
      setBatchNegativePrompt("");
      setInstructionStatus(null);
      return;
    }
    let cancelled = false;
    void Promise.all([apiClient.workflowSchema(workflowId), apiClient.grokInstructionStatus(workflowId)])
      .then(([nextSchema, nextInstructionStatus]) => {
        if (cancelled) return;
        const defaultNegativePrompt = nextSchema.segments?.[0]?.defaultNegativePrompt || "";
        setWorkflowDefaultNegativePrompt(defaultNegativePrompt);
        setBatchNegativePrompt(defaultNegativePrompt);
        setInstructionStatus(nextInstructionStatus);
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setWorkflowDefaultNegativePrompt("");
        setBatchNegativePrompt("");
        setInstructionStatus(null);
        setNotice(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, [workflowId]);

  useEffect(() => {
    void refreshActive();
    void loadHistory(1);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshActive().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, []);

  async function refreshActive() {
    const response = await apiClient.activeBatchJobs();
    setActiveJobs(response.items || []);
  }

  async function loadHistory(nextPage = page) {
    setBusy(true);
    setNotice("");
    try {
      const response = await apiClient.batchJobs({
        page: nextPage,
        dateFrom: historyDate,
        dateTo: historyDate,
        workerId: workerFilter,
        status: statusFilter
      });
      setHistory(response.items || []);
      setWorkers(response.workers || []);
      setPage(response.page || nextPage);
      setTotal(response.total || 0);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "배치 이력을 불러오지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function loadRecoveryDetail(batchId: string) {
    setRecoveryBusy(true);
    setNotice("");
    try {
      const detail = await apiClient.batchJobDetail(batchId);
      const errorItems = (detail.items || []).filter(isRecoveryErrorItem);
      setRecoveryDetail(detail);
      setSelectedRecoveryKeys(errorItems.filter((item) => item.selectable).map(retryItemKey));
      setRecoveryPage(1);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "재처리 정보를 불러오지 못했습니다.");
    } finally {
      setRecoveryBusy(false);
    }
  }

  function openRecoveryModal(job: BatchJobResponse) {
    if (job.failedCount <= 0) return;
    void loadRecoveryDetail(job.id);
  }

  function closeRecoveryModal() {
    setRecoveryDetail(null);
    setSelectedRecoveryKeys([]);
    setRecoveryPage(1);
    setRecoveryPreview(null);
  }

  function toggleRecoveryItem(item: BatchJobDetailItemResponse) {
    if (!item.selectable) return;
    const key = retryItemKey(item);
    setSelectedRecoveryKeys((current) => current.includes(key) ? current.filter((value) => value !== key) : [...current, key]);
  }

  async function refreshRecoveryDetail() {
    if (!recoveryDetail) return;
    await loadRecoveryDetail(recoveryDetail.batch.id);
    await refreshActive();
    await loadHistory(page);
  }

  async function retrySelectedRecoveryItems() {
    if (!recoveryDetail || !selectedRecoveryKeys.length) return;
    const selectedItems = recoveryDetail.items.filter((item) => selectedRecoveryKeys.includes(retryItemKey(item)) && item.selectable);
    await retryRecoveryItems(selectedItems, "선택 항목 재처리에 실패했습니다.");
  }

  async function retrySingleRecoveryItem(item: BatchJobDetailItemResponse) {
    if (!item.selectable) return;
    await retryRecoveryItems([item], "항목 재처리에 실패했습니다.");
  }

  async function retryRecoveryItems(selectedItems: BatchJobDetailItemResponse[], fallbackMessage: string) {
    if (!recoveryDetail || !selectedItems.length) return;
    const draftIds = selectedItems.filter((item) => item.retryKind === "prompt" && item.promptDraftId).map((item) => item.promptDraftId!);
    const taskIds = selectedItems.filter((item) => item.retryKind === "runpod" && item.taskId).map((item) => item.taskId!);
    if (!draftIds.length && !taskIds.length) return;
    setRecoveryBusy(true);
    setNotice("");
    try {
      await apiClient.retrySelectedBatchItems(recoveryDetail.batch.id, { draftIds, taskIds });
      await refreshRecoveryDetail();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : fallbackMessage);
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function retryAllFailedRecoveryItems() {
    if (!recoveryDetail) return;
    setRecoveryBusy(true);
    setNotice("");
    try {
      await apiClient.retryFailedBatchItems(recoveryDetail.batch.id);
      await refreshRecoveryDetail();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "전체 실패 재처리에 실패했습니다.");
    } finally {
      setRecoveryBusy(false);
    }
  }

  function chooseZipFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] || null;
    if (file && !/\.zip$/i.test(file.name)) {
      setSelectedZipFile(null);
      setNotice("ZIP 파일만 선택할 수 있습니다.");
      if (zipInput.current) {
        zipInput.current.value = "";
      }
      return;
    }
    setSelectedZipFile(file);
    setNotice(file ? "" : "선택된 ZIP 파일이 없습니다.");
  }

  function resetBatchCreation() {
    setSelectedZipFile(null);
    setRequestedFrames(DEFAULT_REQUESTED_FRAMES);
    setBatchNegativePrompt(workflowDefaultNegativePrompt);
    setNotice("");
    if (zipInput.current) {
      zipInput.current.value = "";
    }
  }

  function requestBatchConfirmation() {
    if (!workflowId || !selectedZipFile) {
      setNotice("워크플로우와 ZIP 파일을 먼저 선택하세요.");
      return;
    }
    if (!instructionStatus?.configured) {
      setNotice("선택한 워크플로우에 활성 프롬프트 지시문이 없습니다. 관리자 > 프롬프트 생성 지시 관리에서 먼저 지시문을 설정하세요.");
      return;
    }
    setNotice("");
    setConfirmingBatch(true);
  }

  async function startBatch() {
    if (!workflowId || !selectedZipFile) {
      setNotice("워크플로우와 ZIP 파일을 먼저 선택하세요.");
      return;
    }
    if (!instructionStatus?.configured) {
      setNotice("선택한 워크플로우에 활성 프롬프트 지시문이 없습니다. 관리자 > 프롬프트 생성 지시 관리에서 먼저 지시문을 설정하세요.");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const created = await apiClient.createBatchJobFromZip({
        workflowId,
        requestedFrames,
        negativePrompt: batchNegativePrompt,
        file: selectedZipFile
      });
      setSelectedZipFile(null);
      if (zipInput.current) {
        zipInput.current.value = "";
      }
      setNotice(`배치 작업 ${created.id}을 등록했습니다. 이미지 ${created.totalImages}개를 처리합니다.`);
      await refreshActive();
      await loadHistory(1);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "배치 작업 등록에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function downloadBatch(batchId: string) {
    setBusy(true);
    setNotice("");
    try {
      const blob = await apiClient.batchJobZip(batchId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${batchId}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "ZIP 다운로드에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  const selectedZipSummary = fileSizeLabel(selectedZipFile);
  const firstItemIndex = history.length ? (page - 1) * PAGE_SIZE + 1 : 0;
  const lastItemIndex = history.length ? Math.min(total, page * PAGE_SIZE) : 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const selectedWorkflow = workflows.find((workflow) => workflow.id === workflowId);
  const selectedWorkflowLabel = workflowName(selectedWorkflow, workflowId || "-");
  const instructionConfigured = Boolean(instructionStatus?.configured);
  const instructionMissing = Boolean(instructionStatus && !instructionStatus.configured);
  const recoveryItems = recoveryDetail?.items || [];
  const recoveryErrorItems = recoveryItems.filter(isRecoveryErrorItem);
  const recoveryRetryableCount = recoveryItems.filter((item) => item.retryable).length;
  const recoveryPromptFailedCount = recoveryItems.filter((item) => item.retryKind === "prompt").length;
  const recoveryRunpodFailedCount = recoveryItems.filter((item) => item.retryKind === "runpod").length;
  const recoveryActiveCount = recoveryItems.filter((item) => ["PENDING_SUBMIT", "DISPATCHING", "QUEUED", "IN_QUEUE", "IN_PROGRESS", "RUNNING", "GENERATING"].includes(String(item.runpodStatus || item.promptStatus || "").toUpperCase())).length;
  const recoveryCompletedCount = recoveryItems.filter((item) => ["COMPLETED", "SUCCESS"].includes(String(item.runpodStatus || "").toUpperCase())).length;
  const recoveryTotalPages = Math.max(1, Math.ceil(recoveryErrorItems.length / RECOVERY_PAGE_SIZE));
  const recoveryCurrentPage = Math.min(recoveryPage, recoveryTotalPages);
  const recoveryFirstItemIndex = recoveryErrorItems.length ? (recoveryCurrentPage - 1) * RECOVERY_PAGE_SIZE + 1 : 0;
  const recoveryLastItemIndex = recoveryErrorItems.length ? Math.min(recoveryErrorItems.length, recoveryCurrentPage * RECOVERY_PAGE_SIZE) : 0;
  const paginatedRecoveryItems = recoveryErrorItems.slice((recoveryCurrentPage - 1) * RECOVERY_PAGE_SIZE, recoveryCurrentPage * RECOVERY_PAGE_SIZE);

  return (
    <>
      <AppShell
        user={user}
        area="generate"
        activeItem="batchJobs"
        onNavigate={(key) => shellNavigate(key, onGoTo)}
        headerEyebrow="GENERATE · BATCH JOB MANAGEMENT"
        headerTitle="Batch 처리"
        headerActions={<span className={`v3-status-chip ${instructionConfigured ? "is-ok" : "is-warning"}`}>{instructionConfigured ? "GROK CONFIGURED" : "GROK INSTRUCTION REQUIRED"}</span>}
      >
        <section className="v3-screen-section v3-batch-management-section">
        <div className="v3-batch-section-title"><span>1</span><strong>Batch 생성</strong></div>
        <div className="v3-batch-layout-grid">
          <div className="v3-batch-field-card">
            <label>Prompt Workflow</label>
            <select value={workflowId} onChange={(event) => { setWorkflowId(event.target.value); setInstructionStatus(null); setNotice(""); }}>
              {workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflowName(workflow)}</option>)}
            </select>
            <div className={`v3-batch-linked-state${instructionMissing ? " is-error" : ""}`}>{instructionConfigured ? `지시문 연결됨 (${instructionStatus?.count || 0})` : "지시문 없음"}</div>
          </div>
          <button className="v3-batch-folder-card" type="button" onClick={() => zipInput.current?.click()}>
            <span>작업 ZIP</span>
            <strong>{selectedZipFile?.name || "ZIP 파일 선택"}</strong>
            <small>{selectedZipSummary}</small>
          </button>
          <input
            className="v3-batch-hidden-input"
            ref={zipInput}
            type="file"
            accept=".zip,application/zip,application/x-zip-compressed"
            onChange={chooseZipFile}
          />
          <div className="v3-batch-field-card">
            <label>길이 (프레임 수)</label>
            <div className="v3-batch-length-segmented" role="group" aria-label="길이 (프레임 수)">
              {FRAME_OPTIONS.map((frames) => (
                <button
                  key={frames}
                  className={requestedFrames === frames ? "is-selected" : ""}
                  type="button"
                  onClick={() => setRequestedFrames(frames)}
                >
                  {frames}
                </button>
              ))}
            </div>
            <small>{formatFrameDuration(requestedFrames)}</small>
          </div>
          <div className="v3-batch-create-action">
            <button className="v3-primary-button" type="button" disabled={busy || !selectedZipFile || !instructionStatus?.configured} onClick={requestBatchConfirmation}>
              작업 요청
            </button>
            <small>{selectedZipFile ? selectedZipFile.name : formatFrameDuration(requestedFrames)}</small>
          </div>
          <label className="v3-batch-negative-card">
            <span>Built-in Negative Prompt</span>
            <textarea
              value={batchNegativePrompt}
              onChange={(event) => setBatchNegativePrompt(event.target.value)}
              placeholder="워크플로우 기본 negative prompt"
            />
            <small>선택한 워크플로우의 내장값을 기본으로 사용합니다. 수정한 값은 이번 Batch의 모든 이미지 요청에 적용됩니다.</small>
          </label>
          {instructionMissing ? (
            <p className="v3-batch-workflow-callout is-error">
              {selectedWorkflowLabel}에 활성 프롬프트 지시문이 없습니다. 관리자 &gt; 프롬프트 생성 지시 관리에서 새 지시문을 생성하거나 다른 워크플로우의 문서를 복사하세요.
            </p>
          ) : null}
        </div>
        {notice ? <p className="v3-inline-notice">{notice}</p> : null}
        </section>

        <section className="v3-screen-section v3-batch-management-section">
        <div className="v3-batch-section-title"><span>2</span><strong>진행 중 Batch</strong></div>
        <div className="v3-batch-running-grid">
          <div className="v3-batch-mini-table">
            <h3>프롬프트 생성</h3>
            <div className="v3-batch-mini-head is-prompt"><span>Batch ID</span><span>작업자</span><span>대기</span><span>생성 중</span><span>완료</span><span>실패</span></div>
            {activeJobs.map((job) => (
              <button className="v3-batch-mini-row is-prompt" type="button" key={`prompt-${job.id}`} onClick={() => onGoTo("review.history")}>
                <span>{job.id}</span>
                <span>{job.createdByName || job.createdBy || "-"}</span>
                {metricPill(job.promptWaiting)}
                {metricPill(job.promptGenerating, "blue")}
                {metricPill(job.promptCompletedCount, "green")}
                {metricPill(job.promptFailedCount, "red")}
              </button>
            ))}
            {!activeJobs.length ? <div className="v3-empty-panel">진행 중인 프롬프트 배치가 없습니다.</div> : null}
          </div>

          <div className="v3-batch-mini-table">
            <h3>RunPod 영상 생성</h3>
            <div className="v3-batch-mini-head is-runpod"><span>Batch ID</span><span>Pending Submit</span><span>Queue</span><span>진행</span><span>완료</span><span>실패</span></div>
            {activeJobs.map((job) => (
              <button className="v3-batch-mini-row is-runpod" type="button" key={`runpod-${job.id}`} onClick={() => onGoTo("review.history")}>
                <span>{job.id}</span>
                {metricPill(job.runpodPendingSubmit)}
                {metricPill(job.runpodQueued, "yellow")}
                {metricPill(job.runpodInProgress, "blue")}
                {metricPill(job.videoCompletedCount, "green")}
                {metricPill(job.videoFailedCount, "red")}
              </button>
            ))}
            {!activeJobs.length ? <div className="v3-empty-panel">진행 중인 RunPod 배치가 없습니다.</div> : null}
          </div>
        </div>
        </section>

        <section className="v3-screen-section v3-batch-management-section">
        <div className="v3-batch-section-title"><span>3</span><strong>Batch 작업 이력</strong></div>
        <div className="v3-batch-history-toolbar">
          <label>실행일<input type="date" value={historyDate} onChange={(event) => setHistoryDate(event.target.value)} /></label>
          <label>작업자<select value={workerFilter} onChange={(event) => setWorkerFilter(event.target.value)}>
            <option value="">전체 작업자</option>
            {workers.map((worker) => <option key={worker.workerId} value={worker.workerId}>{worker.workerName}</option>)}
          </select></label>
          <label>상태<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">전체 상태</option>
            <option value="INCOMPLETE">진행 중</option>
            <option value="COMPLETE">완료</option>
          </select></label>
          <button className="v3-secondary-button" type="button" disabled={busy} onClick={() => loadHistory(1)}>조회</button>
        </div>
        <div className="v3-table-scroll">
          <table className="v3-table v3-batch-history-table">
            <thead>
              <tr>
                <th>Batch ID</th>
                <th>Date</th>
                <th>작업자</th>
                <th>상태</th>
                <th>영상길이</th>
                <th>이미지 완료</th>
                <th>영상 완료</th>
                <th>zip 파일명</th>
                <th>다운로드</th>
                <th>실패</th>
              </tr>
            </thead>
            <tbody>
              {history.map((job) => (
                <tr key={job.id}>
                  <td>{job.id}</td>
                  <td>{formatDateTime(job.createdAt)}</td>
                  <td>{job.createdByName || job.createdBy || "-"}</td>
                  <td><span className={`v3-batch-status-chip is-${job.status.toLowerCase()}`}>{statusLabel(job.status)}</span></td>
                  <td>{formatFrameDuration(job.requestedFrames)}</td>
                  <td>{job.promptCompletedCount} / {job.totalImages}</td>
                  <td>{job.videoCompletedCount} / {job.totalImages}</td>
                  <td>{job.sourceZipFileName || job.sourceDirName || "-"}</td>
                  <td><button className="v3-secondary-button" type="button" onClick={() => downloadBatch(job.id)}>ZIP 다운로드</button></td>
                  <td>
                    {job.failedCount > 0 ? (
                      <button className="v3-batch-failure-trigger" type="button" disabled={busy} onClick={() => openRecoveryModal(job)}>
                        {job.failedCount}
                      </button>
                    ) : (
                      <span className="v3-batch-failure-static">0</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!history.length ? <div className="v3-empty-panel">표시할 배치 이력이 없습니다.</div> : null}
        </div>
        <div className="v3-batch-history-pagination">
          <span>{firstItemIndex}-{lastItemIndex} / {total}건</span>
          <div>
            <button type="button" disabled={page <= 1 || busy} onClick={() => loadHistory(1)}>≪</button>
            <button type="button" disabled={page <= 1 || busy} onClick={() => loadHistory(page - 1)}>‹</button>
            <strong aria-label={PAGE_COUNT_FORMAT_LABEL}>{page} / {totalPages} 페이지</strong>
            <button type="button" disabled={page >= totalPages || busy} onClick={() => loadHistory(page + 1)}>›</button>
            <button type="button" disabled={page >= totalPages || busy} onClick={() => loadHistory(totalPages)}>≫</button>
          </div>
        </div>
        </section>
      </AppShell>
      {recoveryDetail ? (
        <div className="v3-modal-overlay" role="presentation">
          <div className="v3-modal-panel v3-batch-recovery-modal" role="dialog" aria-modal="true" aria-labelledby="batch-recovery-title">
            <div className="v3-batch-recovery-title">
              <div>
                <h2 id="batch-recovery-title">재처리 관리</h2>
                <span>실패 건수 1 이상인 Batch에서만 열림</span>
              </div>
              <button className="v3-icon-button" type="button" aria-label="재처리 관리 닫기" onClick={closeRecoveryModal}>×</button>
            </div>
            <div className="v3-batch-recovery-header">
              <div className="v3-batch-recovery-summary">
                <strong>{recoveryDetail.batch.id}</strong>
                <span>{recoveryDetail.batch.sourceZipFileName || recoveryDetail.batch.sourceDirName || "-"} · {recoveryDetail.batch.totalImages}개 항목 · {recoveryDetail.batch.workflowId} · {formatFrameDuration(recoveryDetail.batch.requestedFrames)}</span>
                <span>재처리는 기존 Prompt ID와 RunPod Task ID를 유지합니다. 새 ZIP 업로드가 없으면 새 작업 이력을 생성하지 않습니다.</span>
              </div>
              <div className="v3-batch-recovery-actions">
                <button className="v3-secondary-button" type="button" disabled={recoveryBusy} onClick={refreshRecoveryDetail}>상태 새로고침</button>
                <button className="v3-danger-outline-button" type="button" disabled={recoveryBusy || !selectedRecoveryKeys.length} onClick={retrySelectedRecoveryItems}>선택 항목 재처리</button>
                <button className="v3-primary-button" type="button" disabled={recoveryBusy || recoveryRetryableCount === 0} onClick={retryAllFailedRecoveryItems}>전체 실패 재처리</button>
              </div>
            </div>
            <div className="v3-batch-recovery-metrics">
              <div className="is-total"><small>ALL ITEMS</small><strong>{recoveryDetail.batch.totalImages}</strong></div>
              <div><small>PROMPT FAILED</small><strong>{recoveryPromptFailedCount}</strong></div>
              <div><small>RUNPOD FAILED</small><strong>{recoveryRunpodFailedCount}</strong></div>
              <div><small>RETRYABLE</small><strong>{recoveryRetryableCount}</strong></div>
              <div><small>ACTIVE</small><strong>{recoveryActiveCount}</strong></div>
              <div><small>COMPLETED</small><strong>{recoveryCompletedCount}</strong></div>
            </div>
            <p className="v3-batch-recovery-notice">상태 새로고침은 실행 작업을 만들지 않습니다. 재처리는 기존 Prompt ID와 RunPod Task ID를 유지하며, 새 Batch나 새 작업 이력을 생성하지 않습니다.</p>
            {recoveryDetail.warnings.length ? (
              <div className="v3-batch-recovery-warning">
                {recoveryDetail.warnings.length}개의 연결/중복 진단 항목이 있습니다. 중복 또는 연결 누락 항목은 재처리 대상에서 제외됩니다.
              </div>
            ) : null}
            <div className="v3-batch-recovery-list-title">
              <strong>오류건 내역</strong>
              <span>{recoveryFirstItemIndex}-{recoveryLastItemIndex} / {recoveryErrorItems.length}건</span>
            </div>
            <div className="v3-batch-recovery-table">
              <div className="v3-batch-recovery-head">
                <span></span><span>원본 파일</span><span>프롬프트 상태</span><span>RunPod 상태</span><span>오류</span><span>재처리</span><span>다음 처리</span><span>작업</span>
              </div>
              {paginatedRecoveryItems.map((item) => {
                const key = retryItemKey(item);
                const selected = selectedRecoveryKeys.includes(key);
                return (
                  <div className="v3-batch-recovery-row" key={key}>
                    <input type="checkbox" checked={selected} disabled={!item.selectable || recoveryBusy} onChange={() => toggleRecoveryItem(item)} />
                    <div className="v3-batch-recovery-file">
                      {item.assetId ? (
                        <button
                          className="v3-batch-recovery-file-preview"
                          type="button"
                          title="원본 이미지 미리보기"
                          onClick={() => setRecoveryPreview({ src: `/api/files/${item.assetId}`, alt: item.sourceRelativePath || item.sourceFileName })}
                        >
                          {item.sourceRelativePath || item.sourceFileName}
                        </button>
                      ) : (
                        <strong>{item.sourceRelativePath || item.sourceFileName}</strong>
                      )}
                      <small>{item.promptDraftId || item.taskId || "-"}</small>
                    </div>
                    <span className={`v3-status-badge ${retryStatusTone(item.promptStatus)}`}>{item.promptStatus || "-"}</span>
                    <span className={`v3-status-badge ${retryStatusTone(item.runpodStatus)}`}>{item.runpodStatus || "-"}</span>
                    <span className="v3-batch-recovery-error">{item.error || "-"}</span>
                    <span className="v3-batch-metric-pill is-yellow">{item.retryCount}회</span>
                    <span className="v3-batch-recovery-next">{item.nextRetryAt ? formatDateTime(item.nextRetryAt) : "-"}</span>
                    <button className="v3-text-button" type="button" disabled={!item.selectable || recoveryBusy} onClick={() => void retrySingleRecoveryItem(item)}>{item.actionLabel}</button>
                  </div>
                );
              })}
              {!recoveryErrorItems.length ? <div className="v3-empty-panel">재처리할 오류 항목이 없습니다.</div> : null}
            </div>
            {recoveryErrorItems.length > RECOVERY_PAGE_SIZE ? (
              <div className="v3-batch-recovery-pagination">
                <button type="button" disabled={recoveryCurrentPage <= 1 || recoveryBusy} onClick={() => setRecoveryPage((current) => Math.max(1, current - 1))}>이전</button>
                <strong>{recoveryCurrentPage} / {recoveryTotalPages} 페이지</strong>
                <button type="button" disabled={recoveryCurrentPage >= recoveryTotalPages || recoveryBusy} onClick={() => setRecoveryPage((current) => Math.min(recoveryTotalPages, current + 1))}>다음</button>
              </div>
            ) : null}
            {recoveryPreview ? (
              <div className="v3-batch-recovery-preview-backdrop" role="dialog" aria-modal="true" aria-label="원본 이미지 미리보기" onClick={() => setRecoveryPreview(null)}>
                <div className="v3-batch-recovery-preview-modal" onClick={(event) => event.stopPropagation()}>
                  <div className="v3-panel-title-row">
                    <div className="v3-panel-title">{recoveryPreview.alt}</div>
                    <button className="v3-secondary-button" type="button" onClick={() => setRecoveryPreview(null)}>닫기</button>
                  </div>
                  <ProtectedImage src={recoveryPreview.src} alt={recoveryPreview.alt} />
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
      {confirmingBatch ? (
        <div className="v3-modal-overlay" role="presentation">
          <div className="v3-modal-panel v3-batch-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="batch-confirm-title">
            <h2 className="v3-modal-title" id="batch-confirm-title">작업 요청 내역 확인</h2>
            <div className="v3-batch-confirm-summary">
              <div><span>워크플로우</span><strong>{selectedWorkflowLabel}</strong></div>
              <div><span>ZIP 파일명</span><strong>{selectedZipFile?.name || "-"}</strong></div>
              <div><span>길이</span><strong>{formatFrameDuration(requestedFrames)}</strong></div>
              <div><span>Negative Prompt</span><strong>{batchNegativePrompt.trim() || workflowDefaultNegativePrompt || "-"}</strong></div>
            </div>
            <p className="v3-modal-body-text">진행하시겠습니까?</p>
            <div className="v3-modal-actions">
              <button className="v3-secondary-button" type="button" disabled={busy} onClick={() => { setConfirmingBatch(false); resetBatchCreation(); }}>취소</button>
              <button className="v3-primary-button" type="button" disabled={busy} onClick={() => { setConfirmingBatch(false); void startBatch(); }}>진행</button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
