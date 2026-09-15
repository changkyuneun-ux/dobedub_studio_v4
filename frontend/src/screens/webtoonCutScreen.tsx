import React, { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  apiClient,
  HealthResponse,
  WebtoonCutJobResponse,
  WebtoonCutOutputItem
} from "../api/client";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { shellNavigate } from "../helpers/navigation";
import { StudioRoute } from "../router";
import { saveWebtoonCutHandoff } from "../state/durableWorkspace";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; mode: "split" | "history" };
type ViewMode = "list" | "grid";

const POLL_INTERVAL_MS = 2500;

export function WebtoonCutScreen({ user, health: _health, onGoTo, mode }: Props) {
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [activeJob, setActiveJob] = useState<WebtoonCutJobResponse | null>(null);
  const [jobs, setJobs] = useState<WebtoonCutJobResponse[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [outputs, setOutputs] = useState<WebtoonCutOutputItem[]>([]);
  const [selectedOutputIds, setSelectedOutputIds] = useState<Set<string>>(new Set());
  const [previewOutputId, setPreviewOutputId] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [jobStatusFilter, setJobStatusFilter] = useState("");
  const [usedState, setUsedState] = useState("");
  const [flagFilter, setFlagFilter] = useState("");
  const [workerFilter, setWorkerFilter] = useState("");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const isHistoryMode = mode === "history";

  const selectedJob = useMemo(
    () => jobs.find((job) => job.jobId === selectedJobId) || (!isHistoryMode ? activeJob : null) || jobs[0] || null,
    [activeJob, isHistoryMode, jobs, selectedJobId]
  );
  const previewOutput = outputs.find((item) => item.outputId === previewOutputId) || outputs[0] || null;
  const isRunning = activeJob ? !["completed", "failed", "cancelled"].includes(activeJob.status) : false;
  const sameFileHistoryCount = selectedFile ? jobs.filter((job) => job.displayName === selectedFile.name).length : 0;

  useEffect(() => {
    void refreshJobs();
  }, []);

  useEffect(() => {
    if (!isHistoryMode) return;
    void refreshJobs();
  }, [isHistoryMode, jobStatusFilter]);

  useEffect(() => {
    if (!selectedJob?.jobId) return;
    void refreshOutputs(selectedJob.jobId);
  }, [selectedJob?.jobId, usedState, flagFilter, query]);

  useEffect(() => {
    if (!isRunning || !activeJob?.jobId) return;
    const timer = window.setInterval(() => void refreshJobs(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [isRunning, activeJob?.jobId]);

  async function refreshJobs() {
    try {
      const response = await apiClient.webtoonCutJobs({ status: jobStatusFilter, pageSize: 20 });
      setJobs(response.items);
      const running = response.items.find((job) => !["completed", "failed", "cancelled"].includes(job.status)) || null;
      setActiveJob(running);
      if (response.items[0] && !response.items.some((job) => job.jobId === selectedJobId)) setSelectedJobId(response.items[0].jobId);
      if (!response.items.length) setSelectedJobId("");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "컷 분할 이력을 불러오지 못했습니다.");
    }
  }

  async function refreshOutputs(jobId: string) {
    try {
      const response = await apiClient.webtoonCutOutputs(jobId, {
        usedState,
        flags: flagFilter,
        query,
        pageSize: 50
      });
      const items = workerFilter ? response.items.filter((item) => item.createdBy === workerFilter) : response.items;
      setOutputs(items);
      setPreviewOutputId((current) => items.some((item) => item.outputId === current) ? current : items[0]?.outputId || "");
      setSelectedOutputIds((current) => new Set([...current].filter((id) => items.some((item) => item.outputId === id))));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "컷 목록을 불러오지 못했습니다.");
    }
  }

  async function chooseFiles(files: FileList | null) {
    const file = files?.[0] || null;
    if (!file) return;
    setSelectedFile(file);
    setNotice("");
  }

  async function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0] || null;
    if (file) {
      setSelectedFile(file);
      setNotice("");
    }
  }

  async function requestJob() {
    if (isRunning && activeJob) {
      await cancelActiveJob();
      return;
    }
    if (!selectedFile) {
      setNotice("업로드할 PDF, ZIP 또는 이미지 파일을 선택해주세요.");
      return;
    }
    setLoading(true);
    setNotice("업로드 준비 중입니다.");
    try {
      const presigned = await apiClient.presignWebtoonCutUpload({
        fileName: selectedFile.name,
        mimeType: selectedFile.type || "application/octet-stream",
        sizeBytes: selectedFile.size
      });
      const putResponse = await fetch(presigned.uploadUrl, {
        method: "PUT",
        headers: presigned.headers,
        body: selectedFile
      });
      if (!putResponse.ok) {
        throw new Error(`S3 업로드 실패: ${putResponse.status}`);
      }
      const uploaded = await apiClient.completeWebtoonCutUpload({
        assetId: presigned.assetId,
        fileName: presigned.fileName,
        mimeType: presigned.mimeType,
        storageKey: presigned.storageKey,
        sizeBytes: selectedFile.size
      });
      const job = await apiClient.createWebtoonCutJob({
        assetId: uploaded.assetId,
        inputKind: inputKindFromFile(selectedFile),
        metadata: { originalFileName: selectedFile.name }
      });
      setActiveJob(job);
      setSelectedJobId(job.jobId);
      setNotice("컷 분할 작업을 요청했습니다.");
      await refreshJobs();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "작업 요청에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function cancelActiveJob() {
    if (!activeJob) return;
    setLoading(true);
    try {
      const job = await apiClient.cancelWebtoonCutJob(activeJob.jobId);
      setActiveJob(job);
      setNotice("작업 취소 요청을 보냈습니다. 현재 처리 단위 완료 후 중단됩니다.");
      await refreshJobs();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "작업 취소 요청에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  function toggleOutput(outputId: string) {
    setSelectedOutputIds((current) => {
      const next = new Set(current);
      if (next.has(outputId)) next.delete(outputId);
      else next.add(outputId);
      return next;
    });
  }

  function selectCurrentPage() {
    const page = previewOutput?.pageNumber;
    if (!page) return;
    setSelectedOutputIds(new Set(outputs.filter((item) => item.pageNumber === page).map((item) => item.outputId)));
  }

  function selectFilteredAll() {
    setSelectedOutputIds(new Set(outputs.map((item) => item.outputId)));
  }

  async function handoff(target: "grok" | "batch") {
    if (!selectedJob || !selectedOutputIds.size) {
      setNotice("후속 작업에 보낼 컷을 선택해주세요.");
      return;
    }
    try {
      if (target === "grok") {
        const handoffPayload = await apiClient.handoffWebtoonCutsToGrok(selectedJob.jobId, [...selectedOutputIds]);
        saveWebtoonCutHandoff(user.id, { ...handoffPayload, createdAt: new Date().toISOString() });
        setNotice("선택 컷을 Grok 프롬프트 화면 입력으로 연결했습니다. 프롬프트 옵션은 해당 화면에서 선택합니다.");
        onGoTo("create.promptManagement");
      } else {
        const handoffPayload = await apiClient.handoffWebtoonCutsToBatch(selectedJob.jobId, [...selectedOutputIds]);
        saveWebtoonCutHandoff(user.id, { ...handoffPayload, createdAt: new Date().toISOString() });
        setNotice("선택 컷을 Batch 처리 화면 입력으로 연결했습니다. 워크플로우는 Batch 화면에서 선택합니다.");
        onGoTo("create.batchJobs");
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "후속 작업 연결에 실패했습니다.");
    }
  }

  return (
    <AppShell
      user={user}
      area="local"
      activeItem={isHistoryMode ? "webtoonCutHistory" : "webtoonCutSplit"}
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`IMAGE CUT · SERVER PIPELINE · ${isHistoryMode ? "컷 분할 이력" : "컷 분할 처리"}`}
      headerTitle="이미지 컷 관리"
      headerActions={<span className="v3-status-chip is-ok">S3 업로드 · 서버 컷 분리 · I2V 입력 연결</span>}
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}

      {!isHistoryMode ? (
        <>
          <section className="v3-screen-section v3-webtoon-cut-section">
            <div className="v3-batch-section-title"><span>1</span><strong>컷 분할 작업 생성</strong></div>
            <div className="v3-webtoon-cut-create">
              <div className="v3-webtoon-cut-card">
                <label>처리 구조</label>
                <strong>서버 업로드 처리</strong>
                <small>원본과 분리 컷은 S3에 보관됩니다.</small>
                <small>동일 파일명도 기존 결과를 덮어쓰지 않고 새 작업으로 생성됩니다.</small>
                <span className="v3-webtoon-cut-good">✓ 기존 Batch/Grok/RunPod 작업과 분리된 webtoon-cut 전용 API</span>
                <span className="v3-webtoon-cut-good">✓ 기존 취소/실패 작업과 S3 산출물은 이력에 보존됩니다.</span>
              </div>

              <div
                className={`v3-webtoon-cut-dropzone${dragging ? " is-dragging" : ""}`}
                onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => void handleDrop(event)}
              >
                <label>원본 업로드</label>
                <strong>{selectedFile ? selectedFile.name : "PDF · ZIP · JPG · PNG · WEBP · GIF"}</strong>
                <small>파일을 선택하거나 끌어놓으면 S3 업로드 후 서버 worker가 컷을 분리합니다.</small>
                <div className="v3-webtoon-cut-input-actions">
                  <button className="v3-secondary-button" type="button" onClick={() => fileInput.current?.click()}>파일 선택</button>
                </div>
                <input
                  ref={fileInput}
                  className="v3-batch-hidden-input"
                  type="file"
                  accept=".jpg,.jpeg,.png,.webp,.gif,.pdf,.zip,image/jpeg,image/png,image/webp,image/gif,application/pdf,application/zip,application/x-zip-compressed"
                  onChange={(event) => void chooseFiles(event.target.files)}
                />
              </div>

              <div className={`v3-webtoon-cut-action${isRunning ? " is-running" : ""}`}>
                <button
                  className={isRunning ? "v3-danger-button" : "v3-primary-button"}
                  type="button"
                  disabled={loading || (!selectedFile && !isRunning)}
                  onClick={() => void requestJob()}
                >
                  {isRunning ? "작업 취소" : "작업 요청"}
                </button>
                <small>{isRunning ? "취소 요청 시점까지 생성된 컷과 summary는 보존됩니다." : selectedFile ? `${formatBytes(selectedFile.size)} · ${inputKindFromFile(selectedFile).toUpperCase()}${sameFileHistoryCount ? ` · 동일 파일명 이력 ${sameFileHistoryCount}건 · 새 작업 생성` : ""}` : "입력 선택 후 처리정보 표시"}</small>
              </div>
            </div>
          </section>

          <section className="v3-screen-section v3-webtoon-cut-section">
            <div className="v3-batch-section-title"><span>2</span><strong>진행 중 작업</strong><em>화면 이동 후 재진입해도 서버 job 상태를 다시 조회</em></div>
            <div className="v3-webtoon-cut-running">
              <div className="v3-webtoon-cut-progress">
                <strong>{activeJob?.jobId || "CUT-대기"}</strong>
                <span>{activeJob ? `${activeJob.displayName} · ${activeJob.currentUnitLabel || activeJob.status}` : "진행 중인 작업 없음"}</span>
                <div className="v3-webtoon-cut-progressbar"><i style={{ width: `${progressPercent(activeJob)}%` }} /></div>
                <small>{activeJob ? `${activeJob.completedUnits} / ${activeJob.totalUnits || "-"} · ${progressPercent(activeJob)}%` : "0 / 0 · 0%"}</small>
              </div>
              <div className="v3-webtoon-cut-metrics">
                <div><small>완료 단위</small><strong>{activeJob?.completedUnits || 0}</strong></div>
                <div><small>생성 컷</small><strong>{activeJob?.generatedCutCount || 0}</strong></div>
                <div><small>검수 필요</small><strong>{activeJob?.reviewRequiredCount || 0}</strong></div>
                <div><small>오류/누락</small><strong>{activeJob?.failedUnits || 0}</strong></div>
              </div>
            </div>
          </section>
        </>
      ) : (
        <section className="v3-screen-section v3-webtoon-cut-section">
          <div className="v3-batch-section-title"><span>1</span><strong>컷 분할 이력</strong></div>
          <div className="v3-webtoon-cut-filters">
            <label>작업 상태<select value={jobStatusFilter} onChange={(event) => setJobStatusFilter(event.target.value)}><option value="">전체</option><option value="pending">대기</option><option value="running">진행</option><option value="completed">완료</option><option value="cancelled">취소</option><option value="failed">실패</option></select></label>
            <label>사용 여부<select value={usedState} onChange={(event) => setUsedState(event.target.value)}><option value="">전체</option><option value="unused">미사용 컷</option><option value="grok">Grok 사용</option><option value="batch">Batch 사용</option><option value="i2v">I2V 결과 있음</option></select></label>
            <label>플래그<select value={flagFilter} onChange={(event) => setFlagFilter(event.target.value)}><option value="">전체</option><option value="thin">thin</option><option value="many">many</option><option value="review_continuous">review_continuous</option><option value="fullpage">fullpage</option></select></label>
            <label>작업자<input value={workerFilter} onChange={(event) => setWorkerFilter(event.target.value)} placeholder="createdBy" /></label>
            <label>검색<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="파일명 또는 경로" /></label>
            <button className="v3-secondary-button" type="button" onClick={() => void refreshJobs()}>새로고침</button>
          </div>

          <div className="v3-webtoon-cut-history">
            <div className="v3-webtoon-cut-job-list">
              {jobs.map((job) => (
                <button key={job.jobId} className={`v3-webtoon-cut-job-row${selectedJob?.jobId === job.jobId ? " is-selected" : ""}`} type="button" onClick={() => { setSelectedJobId(job.jobId); void refreshOutputs(job.jobId); }}>
                  <strong>{job.displayName}</strong>
                  <span>{job.status} · {job.generatedCutCount}컷 · 검수 {job.reviewRequiredCount}</span>
                </button>
              ))}
              {!jobs.length ? <div className="v3-empty-panel">컷 분할 이력이 없습니다.</div> : null}
            </div>

            <div className="v3-webtoon-cut-output-panel">
              <div className="v3-webtoon-cut-toolbar">
                <strong>{selectedJob?.displayName || "작업 선택"}</strong>
                <div className="v3-webtoon-cut-input-actions">
                  <button className={`v3-secondary-button${viewMode === "list" ? " is-active" : ""}`} type="button" onClick={() => setViewMode("list")}>리스트</button>
                  <button className={`v3-secondary-button${viewMode === "grid" ? " is-active" : ""}`} type="button" onClick={() => setViewMode("grid")}>그리드</button>
                  <button className="v3-secondary-button" type="button" onClick={selectCurrentPage}>현재 페이지 선택</button>
                  <button className="v3-secondary-button" type="button" onClick={selectFilteredAll}>필터 결과 전체 선택</button>
                </div>
              </div>

              <div className={`v3-webtoon-cut-output-layout is-${viewMode}`}>
                <div className="v3-webtoon-cut-output-list">
                  {outputs.map((output) => (
                    <button key={output.outputId} className={`v3-webtoon-cut-output-row${previewOutputId === output.outputId ? " is-preview" : ""}${selectedOutputIds.has(output.outputId) ? " is-selected" : ""}`} type="button" onClick={() => setPreviewOutputId(output.outputId)}>
                      <input type="checkbox" checked={selectedOutputIds.has(output.outputId)} onChange={() => toggleOutput(output.outputId)} onClick={(event) => event.stopPropagation()} />
                      <img src={output.viewUrl} alt={output.displayPath} loading="lazy" />
                      <span><b>{output.displayPath}</b><small>page {output.pageNumber || "-"} · cut {output.cutIndex} · {output.width || "-"}×{output.height || "-"}</small></span>
                      <em>{usageLabel(output)}</em>
                    </button>
                  ))}
                </div>
                <aside className="v3-webtoon-cut-preview">
                  {previewOutput ? (
                    <>
                      <img src={previewOutput.viewUrl} alt={previewOutput.displayPath} />
                      <strong>{previewOutput.displayPath}</strong>
                      <small>{previewOutput.flags.join(", ") || "normal"}</small>
                    </>
                  ) : <div className="v3-empty-panel">프리뷰할 컷이 없습니다.</div>}
                </aside>
              </div>

              <div className="v3-webtoon-cut-pipelines">
                <strong>선택 컷 {selectedOutputIds.size}개</strong>
                <button className="v3-primary-button" type="button" onClick={() => void handoff("grok")}>Grok 프롬프트 화면으로 보내기</button>
                <button className="v3-secondary-button" type="button" onClick={() => void handoff("batch")}>Batch 처리 화면으로 보내기</button>
              </div>
            </div>
          </div>
        </section>
      )}
    </AppShell>
  );
}

function inputKindFromFile(file: File): string {
  const name = file.name.toLowerCase();
  if (name.endsWith(".zip")) return "zip";
  if (name.endsWith(".pdf")) return "pdf";
  return "image";
}

function progressPercent(job: WebtoonCutJobResponse | null): number {
  if (!job?.totalUnits) return 0;
  return Math.min(100, Math.round((job.completedUnits / job.totalUnits) * 100));
}

function usageLabel(output: WebtoonCutOutputItem): string {
  if (output.i2vResultCount > 0) return "I2V 결과 있음";
  if (output.usedInBatchCount > 0) return "Batch 사용";
  if (output.usedInPromptCount > 0) return "Grok 사용";
  return "미사용";
}

function formatBytes(bytes: number): string {
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  if (bytes > 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}
