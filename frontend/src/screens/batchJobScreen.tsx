import React, { ChangeEvent, useEffect, useRef, useState } from "react";
import { apiClient, BatchJobResponse, HealthResponse, UploadResponse, WorkflowItem } from "../api/client";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { batchFolderName, batchImageFiles } from "../helpers/batchFolder";
import { shellNavigate } from "../helpers/navigation";
import { fileToDataUrl } from "../helpers/workflow";
import { StudioRoute } from "../router";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; workflows: WorkflowItem[] };
type UploadRow = UploadResponse & { file: File };

const FRAME_OPTIONS = [49, 81, 161];
const PAGE_SIZE = 10;
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

function imageTypeSummary(files: File[]) {
  const jpg = files.filter((file) => /\.(jpe?g)$/i.test(file.name)).length;
  const png = files.filter((file) => /\.png$/i.test(file.name)).length;
  const extra = files.length - jpg - png;
  return [
    `대상 이미지 ${files.length}건`,
    jpg ? `JPG ${jpg}` : "",
    png ? `PNG ${png}` : "",
    extra ? `기타 ${extra}` : ""
  ].filter(Boolean).join(" · ");
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

export function BatchJobScreen({ user, health: _health, onGoTo, workflows }: Props) {
  const [workflowId, setWorkflowId] = useState(workflows[0]?.id || "");
  const [requestedFrames, setRequestedFrames] = useState(DEFAULT_REQUESTED_FRAMES);
  const [folderName, setFolderName] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadedRows, setUploadedRows] = useState<UploadRow[]>([]);
  const [activeJobs, setActiveJobs] = useState<BatchJobResponse[]>([]);
  const [history, setHistory] = useState<BatchJobResponse[]>([]);
  const [workers, setWorkers] = useState<Array<{ workerId: string; workerName: string }>>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [workerFilter, setWorkerFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [confirmingBatch, setConfirmingBatch] = useState(false);
  const folderInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!workflowId && workflows[0]?.id) {
      setWorkflowId(workflows[0].id);
    }
  }, [workflowId, workflows]);

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
        dateFrom,
        dateTo,
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

  function chooseFolder(event: ChangeEvent<HTMLInputElement>) {
    const files = batchImageFiles(event.target.files || []);
    setSelectedFiles(files);
    setFolderName(batchFolderName(files));
    setUploadedRows([]);
    setNotice(files.length ? "" : "처리할 이미지가 없습니다.");
  }

  function resetBatchCreation() {
    setSelectedFiles([]);
    setFolderName("");
    setUploadedRows([]);
    setRequestedFrames(DEFAULT_REQUESTED_FRAMES);
    setNotice("");
    if (folderInput.current) {
      folderInput.current.value = "";
    }
  }

  function requestBatchConfirmation() {
    if (!workflowId || !selectedFiles.length) {
      setNotice("워크플로우와 이미지 폴더를 먼저 선택하세요.");
      return;
    }
    setNotice("");
    setConfirmingBatch(true);
  }

  async function startBatch() {
    if (!workflowId || !selectedFiles.length) {
      setNotice("워크플로우와 이미지 폴더를 먼저 선택하세요.");
      return;
    }
    setBusy(true);
    setNotice("");
    const uploaded: UploadRow[] = [];
    try {
      for (const file of selectedFiles) {
        const upload = await apiClient.upload({
          fileName: file.name,
          mimeType: file.type || "image/png",
          dataUrl: await fileToDataUrl(file)
        });
        uploaded.push({ ...upload, file });
        setUploadedRows([...uploaded]);
      }
      const created = await apiClient.createBatchJob({
        workflowId,
        sourceDirName: folderName,
        requestedFrames,
        items: uploaded.map((row) => ({ assetId: row.assetId, fileName: row.file.name }))
      });
      setSelectedFiles([]);
      setUploadedRows([]);
      if (folderInput.current) {
        folderInput.current.value = "";
      }
      setNotice(`배치 작업 ${created.id}을 등록했습니다.`);
      await refreshActive();
      await loadHistory(1);
    } catch (error) {
      await Promise.all(uploaded.map((row) => apiClient.deleteUnsubmittedUpload(row.assetId).catch(() => undefined)));
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

  const selectedImageSummary = selectedFiles.length ? imageTypeSummary(selectedFiles) : "대상 이미지 0건";
  const firstItemIndex = history.length ? (page - 1) * PAGE_SIZE + 1 : 0;
  const lastItemIndex = history.length ? Math.min(total, page * PAGE_SIZE) : 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const selectedWorkflow = workflows.find((workflow) => workflow.id === workflowId);
  const selectedWorkflowLabel = workflowName(selectedWorkflow, workflowId || "-");

  return (
    <>
      <AppShell
        user={user}
        area="generate"
        activeItem="batchJobs"
        onNavigate={(key) => shellNavigate(key, onGoTo)}
        headerEyebrow="GENERATE · BATCH JOB MANAGEMENT"
        headerTitle="Batch 작업 요청 관리"
        headerActions={<span className="v3-status-chip is-ok">GROK CONFIGURED</span>}
      >
        <section className="v3-screen-section v3-batch-management-section">
        <div className="v3-batch-section-title"><span>1</span><strong>Batch 생성</strong></div>
        <div className="v3-batch-layout-grid">
          <div className="v3-batch-field-card">
            <label>Prompt Workflow</label>
            <select value={workflowId} onChange={(event) => setWorkflowId(event.target.value)}>
              {workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflowName(workflow)}</option>)}
            </select>
            <div className="v3-batch-linked-state">지시문 연결됨</div>
          </div>
          <button className="v3-batch-folder-card" type="button" onClick={() => folderInput.current?.click()}>
            <span>작업 폴더</span>
            <strong>{folderName || "폴더 선택"}</strong>
            <small>{selectedImageSummary}</small>
          </button>
          <input
            className="v3-batch-hidden-input"
            ref={(node) => {
              folderInput.current = node;
              if (node) {
                node.setAttribute("webkitdirectory", "");
                node.setAttribute("directory", "");
              }
            }}
            type="file"
            multiple
            onChange={chooseFolder}
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
            <button className="v3-primary-button" type="button" disabled={busy || !selectedFiles.length} onClick={requestBatchConfirmation}>
              작업 요청
            </button>
            <small>{uploadedRows.length ? `업로드 ${uploadedRows.length} / ${selectedFiles.length}` : formatFrameDuration(requestedFrames)}</small>
          </div>
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
          <label>시작일<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
          <label>종료일<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
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
                <th>이미지 디렉토리</th>
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
                  <td>{job.sourceDirName || "-"}</td>
                  <td><button className="v3-secondary-button" type="button" onClick={() => downloadBatch(job.id)}>ZIP 다운로드</button></td>
                  <td>{job.failedCount}</td>
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
      {confirmingBatch ? (
        <div className="v3-modal-overlay" role="presentation">
          <div className="v3-modal-panel v3-batch-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="batch-confirm-title">
            <h2 className="v3-modal-title" id="batch-confirm-title">작업 요청 내역 확인</h2>
            <div className="v3-batch-confirm-summary">
              <div><span>워크플로우</span><strong>{selectedWorkflowLabel}</strong></div>
              <div><span>폴더명</span><strong>{folderName || "-"}</strong></div>
              <div><span>이미지수</span><strong>{selectedFiles.length}개</strong></div>
              <div><span>길이</span><strong>{formatFrameDuration(requestedFrames)}</strong></div>
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
