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
import { downloadProtectedAsset } from "../helpers/workflow";
import { StudioRoute } from "../router";
import { saveWebtoonCutHandoff } from "../state/durableWorkspace";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; mode: "split" | "history" };
type ViewMode = "list" | "grid";
type SelectedFileStructure = {
  inputRelativePath: string;
  sourceCountLabel: string;
  fileSizeLabel: string;
  imageSizeLabel: string;
  outputPolicyLabel: string;
  s3RelativePath: string;
};

const POLL_INTERVAL_MS = 2500;
const JOBS_PAGE_SIZE = 20;
const OUTPUTS_PAGE_SIZE = 50;

export function WebtoonCutScreen({ user, health: _health, onGoTo, mode }: Props) {
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadedStorageKey, setUploadedStorageKey] = useState("");
  const [imageSizeLabel, setImageSizeLabel] = useState("서버 분석 후 확정");
  const [dragging, setDragging] = useState(false);
  const [activeJob, setActiveJob] = useState<WebtoonCutJobResponse | null>(null);
  const [jobs, setJobs] = useState<WebtoonCutJobResponse[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [outputs, setOutputs] = useState<WebtoonCutOutputItem[]>([]);
  const [selectedOutputIds, setSelectedOutputIds] = useState<Set<string>>(new Set());
  const [previewOutputId, setPreviewOutputId] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [jobStatusFilter, setJobStatusFilter] = useState("");
  const [jobsPage, setJobsPage] = useState(1);
  const [outputsPage, setOutputsPage] = useState(1);
  const [usedState, setUsedState] = useState("");
  const [flagFilter, setFlagFilter] = useState("");
  const [workerFilter, setWorkerFilter] = useState("");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingDeleteJob, setPendingDeleteJob] = useState<WebtoonCutJobResponse | null>(null);
  const isHistoryMode = mode === "history";

  const selectedJob = useMemo(
    () => jobs.find((job) => job.jobId === selectedJobId) || (!isHistoryMode ? activeJob : null) || jobs[0] || null,
    [activeJob, isHistoryMode, jobs, selectedJobId]
  );
  const previewOutput = outputs.find((item) => item.outputId === previewOutputId) || outputs[0] || null;
  const isRunning = activeJob ? !["completed", "failed", "cancelled"].includes(activeJob.status) : false;
  const sameFileHistoryCount = selectedFile ? jobs.filter((job) => job.displayName === selectedFile.name).length : 0;
  const selectedFileStructure = useMemo(
    () => describeSelectedFileStructure(selectedFile, { imageSizeLabel, uploadedStorageKey }),
    [imageSizeLabel, selectedFile, uploadedStorageKey]
  );

  useEffect(() => {
    void refreshJobs();
  }, []);

  useEffect(() => {
    if (!isHistoryMode) return;
    void refreshJobs();
  }, [isHistoryMode, jobStatusFilter, workerFilter, query, jobsPage]);

  useEffect(() => {
    if (!selectedJob?.jobId) return;
    void refreshOutputs(selectedJob.jobId);
  }, [selectedJob?.jobId, usedState, flagFilter, query, outputsPage]);

  useEffect(() => {
    setJobsPage(1);
  }, [jobStatusFilter, workerFilter, query]);

  useEffect(() => {
    setOutputsPage(1);
  }, [selectedJobId, usedState, flagFilter, query]);

  useEffect(() => {
    if (!isRunning || !activeJob?.jobId) return;
    const timer = window.setInterval(() => void refreshJobs(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [isRunning, activeJob?.jobId]);

  useEffect(() => {
    if (!selectedFile || inputKindFromFile(selectedFile) !== "image") {
      setImageSizeLabel("서버 분석 후 확정");
      return;
    }
    const url = window.URL.createObjectURL(selectedFile);
    const image = new Image();
    image.onload = () => {
      setImageSizeLabel(`${image.naturalWidth}×${image.naturalHeight}`);
      window.URL.revokeObjectURL(url);
    };
    image.onerror = () => {
      setImageSizeLabel("이미지 크기 확인 실패");
      window.URL.revokeObjectURL(url);
    };
    image.src = url;
  }, [selectedFile]);

  async function refreshJobs() {
    try {
      const response = await apiClient.webtoonCutJobs({
        status: jobStatusFilter,
        query,
        createdBy: isHistoryMode ? workerFilter.trim() : user.id,
        page: jobsPage,
        pageSize: JOBS_PAGE_SIZE
      });
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
        page: outputsPage,
        pageSize: OUTPUTS_PAGE_SIZE
      });
      const items = response.items;
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
    setUploadedStorageKey("");
    setNotice("");
  }

  async function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0] || null;
    if (file) {
      setSelectedFile(file);
      setUploadedStorageKey("");
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
      setUploadedStorageKey(uploaded.storageKey);
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

  async function deleteHistoryJob(job: WebtoonCutJobResponse) {
    if (!canDeleteJob(job)) {
      setNotice("진행 중인 작업은 삭제할 수 없습니다. 먼저 취소 또는 완료 후 삭제하세요.");
      return;
    }
    setPendingDeleteJob(job);
  }

  async function confirmDeleteHistoryJob() {
    const job = pendingDeleteJob;
    if (!job) return;
    setLoading(true);
    try {
      await apiClient.deleteWebtoonCutJob(job.jobId);
      setNotice("컷 분할 이력을 삭제했습니다. 원본과 컷 파일은 S3에 보존됩니다.");
      setPendingDeleteJob(null);
      setOutputs([]);
      setSelectedOutputIds(new Set());
      setPreviewOutputId("");
      if (selectedJobId === job.jobId) setSelectedJobId("");
      await refreshJobs();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "컷 분할 이력을 삭제하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function downloadSelectedOutputs() {
    if (!selectedJob || !selectedOutputIds.size) {
      setNotice("다운로드할 컷을 선택해주세요.");
      return;
    }
    setLoading(true);
    try {
      const selectedIds = [...selectedOutputIds];
      if (selectedIds.length === 1) {
        const output = outputs.find((item) => item.outputId === selectedIds[0]);
        if (!output) throw new Error("선택한 컷을 현재 목록에서 찾을 수 없습니다.");
        await downloadProtectedAsset(output.downloadUrl, output.displayPath.split("/").pop() || "webtoon-cut.png");
      } else {
        const blob = await apiClient.downloadWebtoonCutOutputsZip(selectedJob.jobId, selectedIds);
        downloadBlob(blob, `${stripExtension(selectedJob.displayName)}_cuts_selected.zip`);
      }
      setNotice(`선택 컷 ${selectedIds.length}개 다운로드를 시작했습니다.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "선택 컷 다운로드에 실패했습니다.");
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

              <div className="v3-webtoon-cut-source-panel">
                <label>입력 구조 정보</label>
                <strong>{selectedFile ? selectedFile.name : "파일 선택 후 자동 표시"}</strong>
                <div className="v3-webtoon-cut-source-grid">
                  <span>상대경로</span><b>{selectedFileStructure.inputRelativePath}</b>
                  <span>원본 이미지 수</span><b>{selectedFileStructure.sourceCountLabel}</b>
                  <span>파일 크기</span><b>{selectedFileStructure.fileSizeLabel}</b>
                  <span>원본 크기</span><b>{selectedFileStructure.imageSizeLabel}</b>
                  <span>출력 구조</span><b>{selectedFileStructure.outputPolicyLabel}</b>
                  <span>S3 상대경로</span><b>{selectedFileStructure.s3RelativePath}</b>
                </div>
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
                <div key={job.jobId} className={`v3-webtoon-cut-job-row${selectedJob?.jobId === job.jobId ? " is-selected" : ""}`}>
                  <button className="v3-webtoon-cut-job-row-main" type="button" onClick={() => { setSelectedJobId(job.jobId); void refreshOutputs(job.jobId); }}>
                    <strong>{job.displayName}</strong>
                    <span>{job.status} · {job.generatedCutCount}컷 · 검수 {job.reviewRequiredCount}</span>
                  </button>
                  <span className="v3-webtoon-cut-job-actions">
                    <button
                      className="v3-danger-button"
                      type="button"
                      disabled={loading || !canDeleteJob(job)}
                      onClick={() => void deleteHistoryJob(job)}
                    >
                      이력 삭제
                    </button>
                  </span>
                </div>
              ))}
              {!jobs.length ? <div className="v3-empty-panel">컷 분할 이력이 없습니다.</div> : null}
              <div className="v3-webtoon-cut-pagination">
                <button className="v3-secondary-button" type="button" disabled={jobsPage <= 1} onClick={() => setJobsPage((page) => Math.max(1, page - 1))}>이전</button>
                <span>{jobsPage} 페이지</span>
                <button className="v3-secondary-button" type="button" disabled={jobs.length < JOBS_PAGE_SIZE} onClick={() => setJobsPage((page) => page + 1)}>다음</button>
              </div>
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
                      <RetryingCutThumbnail src={output.viewUrl} alt={output.displayPath} />
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
              <div className="v3-webtoon-cut-pagination">
                <button className="v3-secondary-button" type="button" disabled={outputsPage <= 1} onClick={() => setOutputsPage((page) => Math.max(1, page - 1))}>이전</button>
                <span>{outputsPage} 페이지</span>
                <button className="v3-secondary-button" type="button" disabled={outputs.length < OUTPUTS_PAGE_SIZE} onClick={() => setOutputsPage((page) => page + 1)}>다음</button>
              </div>

              <div className="v3-webtoon-cut-pipelines">
                <strong>선택 컷 {selectedOutputIds.size}개</strong>
                <button className="v3-secondary-button" type="button" disabled={!selectedOutputIds.size || loading} onClick={() => void downloadSelectedOutputs()}>선택 컷 다운로드</button>
                <button className="v3-primary-button" type="button" onClick={() => void handoff("grok")}>Grok 프롬프트 화면으로 보내기</button>
                <button className="v3-secondary-button v3-webtoon-cut-batch-button" type="button" onClick={() => void handoff("batch")}>Batch 처리 화면으로 보내기</button>
              </div>
            </div>
          </div>
        </section>
      )}
      {pendingDeleteJob ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="v3WebtoonCutDeleteTitle" onClick={() => !loading && setPendingDeleteJob(null)}>
          <div className="v3-modal-panel v3-webtoon-cut-delete-modal" onClick={(event) => event.stopPropagation()}>
            <h2 id="v3WebtoonCutDeleteTitle" className="v3-modal-title">컷 분할 이력 삭제</h2>
            <p className="v3-modal-body-text">
              <strong>{pendingDeleteJob.displayName}</strong> 컷 분할 이력을 삭제할까요?
              S3 원본과 컷 파일은 보존되고 이력 목록에서만 숨겨집니다.
            </p>
            <div className="v3-modal-actions">
              <button className="v3-secondary-button" type="button" disabled={loading} onClick={() => setPendingDeleteJob(null)}>취소</button>
              <button className="v3-danger-button" type="button" disabled={loading} onClick={() => void confirmDeleteHistoryJob()}>삭제</button>
            </div>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}

function inputKindFromFile(file: File): string {
  const name = file.name.toLowerCase();
  if (name.endsWith(".zip")) return "zip";
  if (name.endsWith(".pdf")) return "pdf";
  return "image";
}

function describeSelectedFileStructure(
  file: File | null,
  options: { imageSizeLabel: string; uploadedStorageKey: string }
): SelectedFileStructure {
  if (!file) {
    return {
      inputRelativePath: "-",
      sourceCountLabel: "-",
      fileSizeLabel: "-",
      imageSizeLabel: "-",
      outputPolicyLabel: "파일 선택 후 표시",
      s3RelativePath: "업로드 후 표시"
    };
  }
  const kind = inputKindFromFile(file);
  const inputRelativePath = String((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name);
  const sourceCountLabel = kind === "image" ? "1개" : kind === "pdf" ? "PDF 페이지 기준" : "ZIP 내부 파일 기준";
  return {
    inputRelativePath,
    sourceCountLabel,
    fileSizeLabel: formatBytes(file.size),
    imageSizeLabel: kind === "image" ? options.imageSizeLabel : "서버 분석 후 확정",
    outputPolicyLabel: `${stripExtension(file.name)}_cuts / source_cuts / 원본별 하위 경로`,
    s3RelativePath: options.uploadedStorageKey || "작업 요청 시 S3 업로드 후 표시"
  };
}

function stripExtension(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, "");
}

function downloadBlob(blob: Blob, fileName: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName || "webtoon-cut-selected.zip";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
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

function RetryingCutThumbnail({ src, alt }: { src: string; alt: string }) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setAttempt(0);
    setFailed(false);
  }, [src]);

  if (failed) {
    return <span className="v3-webtoon-cut-thumb-fallback">썸네일<br />재시도 실패</span>;
  }

  return (
    <img
      src={attempt > 0 ? withRetryQuery(src, attempt) : src}
      alt={alt}
      loading="lazy"
      onError={() => {
        if (attempt < 2) {
          setAttempt((value) => value + 1);
        } else {
          setFailed(true);
        }
      }}
    />
  );
}

function withRetryQuery(src: string, attempt: number): string {
  try {
    const url = new URL(src, window.location.origin);
    url.searchParams.set("thumbRetry", String(attempt));
    return url.toString();
  } catch {
    const separator = src.includes("?") ? "&" : "?";
    return `${src}${separator}thumbRetry=${attempt}`;
  }
}

function canDeleteJob(job: WebtoonCutJobResponse): boolean {
  return ["completed", "failed", "cancelled"].includes(job.status);
}

function formatBytes(bytes: number): string {
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  if (bytes > 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}
