import React, { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { apiClient, GrokImagePromptDraftResponse, HealthResponse, PromptGenerationBatchResponse, UploadResponse, WorkflowItem, WorkflowSchema } from "../api/client";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import { ProtectedImage } from "../components/ProtectedAssets";
import { shellNavigate } from "../helpers/navigation";
import { fileToDataUrl, formatImageDimensions, formatUploadSize } from "../helpers/workflow";
import { StudioRoute } from "../router";
import { loadPromptWorkspace, PromptUploadItem, savePromptWorkspace } from "../state/durableWorkspace";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; workflows: WorkflowItem[] };
type UploadItem = PromptUploadItem;
type PromptMappingRow = { upload: UploadItem; draft?: GrokImagePromptDraftResponse; batchId?: string };

const workflowName = (workflow: WorkflowItem) => workflow.label || workflow.name || workflow.id;
const PROMPT_BATCH_PROGRESS_PAGE_SIZE = 10;
const promptDisplayStatus = (status: string) => {
  const normalized = status.toUpperCase();
  if (normalized === "READY" || normalized === "MANUAL_REQUIRED") return "COMPLETED";
  if (normalized === "PENDING") return "WAITING";
  return normalized || "WAITING";
};

export function PromptManagementScreen({ user, health: _health, onGoTo, workflows }: Props) {
  const [initialWorkspace] = useState(() => loadPromptWorkspace(user.id));
  const [workflowId, setWorkflowId] = useState(initialWorkspace.workflowId);
  const [schema, setSchema] = useState<WorkflowSchema | null>(null);
  const [uploads, setUploads] = useState<UploadItem[]>(initialWorkspace.uploads);
  const [drafts, setDrafts] = useState<Record<string, GrokImagePromptDraftResponse>>(initialWorkspace.drafts);
  const [negativePrompt, setNegativePrompt] = useState(initialWorkspace.negativePrompt);
  const [activePromptGenerationBatches, setActivePromptGenerationBatches] = useState<PromptGenerationBatchResponse[]>([]);
  const [instructionStatus, setInstructionStatus] = useState<{ configured: boolean; count: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [isDragActive, setIsDragActive] = useState(false);
  const [notice, setNotice] = useState("");
  const [activeBatchPage, setActiveBatchPage] = useState(1);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const selectedWorkflow = workflows.find((workflow) => workflow.id === workflowId);
  const generating = activePromptGenerationBatches.length > 0;
  const dashboard = useMemo(() => {
    const items = Object.values(drafts);
    return {
      total: uploads.length,
      waiting: Math.max(0, uploads.length - items.length),
      generating: items.filter((draft) => draft.status === "GENERATING").length,
      completed: items.filter((draft) => draft.status === "READY").length,
      failed: items.filter((draft) => draft.status === "FAILED").length
    };
  }, [uploads.length, drafts]);
  const activePromptMappingRows = useMemo<PromptMappingRow[]>(() => activePromptGenerationBatches.flatMap((batch) => batch.items.map((draft) => ({
    batchId: batch.id,
    draft,
    upload: {
      assetId: draft.assetId,
      downloadUrl: `/api/files/${draft.assetId}`,
      fileName: draft.asset?.fileName || draft.assetId,
      imageHeight: draft.asset?.imageHeight,
      imageWidth: draft.asset?.imageWidth,
      mimeType: draft.asset?.mimeType || "image/png",
      requestedFrames: draft.requestedFrames || 81,
      sizeBytes: draft.asset?.sizeBytes || 0
    }
  }))), [activePromptGenerationBatches]);
  const promptMappingRows = useMemo<PromptMappingRow[]>(() => [
    ...activePromptMappingRows,
    ...uploads.map((upload) => ({ upload, draft: drafts[upload.assetId] }))
  ], [activePromptMappingRows, drafts, uploads]);
  const activeBatchDashboard = useMemo(() => {
    const items = activePromptGenerationBatches.flatMap((batch) => batch.items);
    const total = items.length;
    const waiting = items.filter((item) => item.status === "PENDING").length;
    const generatingCount = items.filter((item) => item.status === "GENERATING").length;
    const readyCount = items.filter((item) => item.status === "READY" || item.status === "MANUAL_REQUIRED").length;
    const failedCount = items.filter((item) => item.status === "FAILED").length;
    return { total, waiting, generatingCount, readyCount, failedCount };
  }, [activePromptGenerationBatches]);
  const activeBatchPageCount = Math.max(1, Math.ceil(activePromptGenerationBatches.length / PROMPT_BATCH_PROGRESS_PAGE_SIZE));
  const safeActiveBatchPage = Math.min(activeBatchPage, activeBatchPageCount);
  const activeBatchStart = activePromptGenerationBatches.length ? (safeActiveBatchPage - 1) * PROMPT_BATCH_PROGRESS_PAGE_SIZE + 1 : 0;
  const activeBatchEnd = Math.min(activePromptGenerationBatches.length, safeActiveBatchPage * PROMPT_BATCH_PROGRESS_PAGE_SIZE);
  const paginatedActivePromptGenerationBatches = activePromptGenerationBatches.slice(
    (safeActiveBatchPage - 1) * PROMPT_BATCH_PROGRESS_PAGE_SIZE,
    safeActiveBatchPage * PROMPT_BATCH_PROGRESS_PAGE_SIZE
  );

  useEffect(() => {
    if (!workflowId) {
      setSchema(null);
      setInstructionStatus(null);
      return;
    }
    void Promise.all([apiClient.workflowSchema(workflowId), apiClient.grokInstructionStatus(workflowId)])
      .then(([nextSchema, nextInstructionStatus]) => {
        setSchema(nextSchema);
        setInstructionStatus(nextInstructionStatus);
        setNegativePrompt((current) => current || nextSchema.segments?.[0]?.defaultNegativePrompt || "");
      })
      .catch((error: Error) => {
        setInstructionStatus(null);
        setNotice(error.message);
      });
  }, [workflowId]);

  useEffect(() => {
    void refreshActivePromptGenerationBatches()
      .catch(() => { /* A stale dashboard must not block a new composition. */ });
  }, []);

  useEffect(() => {
    savePromptWorkspace(user.id, {
      workflowId,
      uploads,
      drafts,
      negativePrompt,
      batchId: undefined
    });
  }, [drafts, negativePrompt, uploads, user.id, workflowId]);

  useEffect(() => {
    if (!activePromptGenerationBatches.length) return;
    const timer = window.setInterval(() => {
      void refreshActivePromptGenerationBatches().catch((error: Error) => setNotice(error.message));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activePromptGenerationBatches.length]);

  useEffect(() => {
    setActiveBatchPage((current) => Math.min(current, activeBatchPageCount));
  }, [activeBatchPageCount]);

  function selectWorkflow(id: string) {
    setWorkflowId(id);
    setDrafts({});
    setInstructionStatus(null);
    setNotice("");
  }

  async function refreshActivePromptGenerationBatches() {
    const response = await apiClient.activePromptGenerationBatches();
    setActivePromptGenerationBatches(response.items);
  }

  async function uploadFiles(files: FileList | File[] | null) {
    if (!files?.length) return;
    setBusy(true);
    setNotice("");
    try {
      const next = await Promise.all(Array.from(files).map(async (file) => apiClient.upload({
        fileName: file.name,
        mimeType: file.type || "image/png",
        dataUrl: await fileToDataUrl(file)
      })));
      setUploads((current) => [...current, ...next.map((item) => ({ ...item, requestedFrames: 81 }))]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "이미지 업로드에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  function handleDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    setIsDragActive(false);
    void uploadFiles(event.dataTransfer.files);
  }

  async function generateAll() {
    if (!workflowId || !uploads.length) return;
    if (!instructionStatus?.configured) {
      setNotice("선택한 워크플로우에 활성 프롬프트 지시문이 없습니다. 관리자 > 프롬프트 생성 지시 관리에서 먼저 지시문을 설정하세요.");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const next = await apiClient.createImagePromptBatch({
        workflowId,
        items: uploads.map((upload, index) => ({
          assetId: upload.assetId,
          slotIndex: index + 1,
          requestedFrames: upload.requestedFrames,
          negativePrompt
        }))
      });
      setActivePromptGenerationBatches((current) => [next, ...current.filter((batch) => batch.id !== next.id)]);
      setActiveBatchPage(1);
      setUploads([]);
      setDrafts({});
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "일괄 프롬프트 생성 요청에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  function updateVisibleDraft(nextDraft: GrokImagePromptDraftResponse) {
    setDrafts((current) => ({ ...current, [nextDraft.assetId]: nextDraft }));
    setActivePromptGenerationBatches((current) => current.map((batch) => ({
      ...batch,
      items: batch.items.map((item) => item.draftId === nextDraft.draftId ? nextDraft : item)
    })));
  }

  async function saveDraft(draft: GrokImagePromptDraftResponse, changes: { positivePrompt?: string; requestedFrames?: number }) {
    try {
      const next = await apiClient.updateImagePromptDraft(draft.draftId, changes);
      updateVisibleDraft(next);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "프롬프트 저장에 실패했습니다.");
    }
  }

  async function retry(draft: GrokImagePromptDraftResponse, fileName: string) {
    try {
      const next = await apiClient.retryImagePromptDraft(draft.draftId);
      updateVisibleDraft(next);
      void refreshActivePromptGenerationBatches();
      setNotice(`${fileName} 프롬프트를 다시 생성합니다.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "재생성 요청에 실패했습니다.");
    }
  }

  async function deletePromptRow(draft: GrokImagePromptDraftResponse) {
    if (busy || draft.status === "GENERATING") return;
    setBusy(true);
    setNotice("");
    try {
      await apiClient.deleteImagePromptDraft(draft.draftId);
      setUploads((current) => current.filter((item) => item.assetId !== draft.assetId));
      setDrafts((current) => {
        const next = { ...current };
        delete next[draft.assetId];
        return next;
      });
      await refreshActivePromptGenerationBatches();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "프롬프트 항목을 삭제하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteUpload(upload: UploadItem) {
    if (busy || drafts[upload.assetId]) return;
    setBusy(true);
    setNotice("");
    try {
      await apiClient.deleteUnsubmittedUpload(upload.assetId);
      setUploads((current) => current.filter((item) => item.assetId !== upload.assetId));
      setDrafts((current) => {
        const next = { ...current };
        delete next[upload.assetId];
        return next;
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "업로드 이미지를 삭제하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell user={user} area="generate" activeItem="promptManagement" onNavigate={(key) => shellNavigate(key, onGoTo)} headerEyebrow="GENERATE · PROMPT MANAGEMENT" headerTitle="Grok 프롬프트 생성" headerActions={<span className="v3-status-chip is-ok">{generating ? "GROK GENERATING" : "GROK CONFIGURED"}</span>}>
      <section className="v3-card v3-prompt-workflow-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Prompt Workflow</div><span className="v3-muted-text">프롬프트 생성 전에 워크플로우 지시문을 선택합니다.</span></div>
        <div className="v3-prompt-workflow-list">{workflows.map((workflow) => <button key={workflow.id} type="button" className={`v3-prompt-workflow-option ${workflow.id === workflowId ? "is-selected" : ""}`} onClick={() => selectWorkflow(workflow.id)}><b>{workflowName(workflow)}</b><small>{workflow.keyframeCount || 1} kf · {workflow.id === workflowId ? "SELECTED" : "ACTIVE"}</small></button>)}</div>
        <p className={`v3-prompt-workflow-callout${!selectedWorkflow || (instructionStatus && !instructionStatus.configured) ? " is-error" : ""}`}>{selectedWorkflow ? instructionStatus?.configured ? `${workflowName(selectedWorkflow)}의 활성 프롬프트 지시문 ${instructionStatus.count}개를 사용해 업로드 이미지별 Positive Prompt를 생성합니다.` : `${workflowName(selectedWorkflow)}에 활성 프롬프트 지시문이 없습니다. 관리자 > 프롬프트 생성 지시 관리에서 새 지시문을 생성하거나 다른 워크플로우의 문서를 복사하세요.` : "워크플로우를 선택하세요. 연결된 지시문이 없으면 프롬프트 생성 요청을 시작할 수 없습니다."}</p>
      </section>

      <section className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Image Upload</div><span className="v3-muted-text">제한 없이 추가 · 이미지별 프롬프트 매핑</span></div>
        <div className="v3-prompt-upload-layout">
          <button className={`v3-prompt-drop-zone ${isDragActive ? "is-dragging" : ""}`} type="button" disabled={busy} onClick={() => fileInput.current?.click()} onDrop={handleDrop} onDragOver={(event) => { event.preventDefault(); setIsDragActive(true); }} onDragLeave={() => setIsDragActive(false)}><strong>＋</strong><b>이미지 업로드</b><small>파일 선택 또는 끌어놓기</small></button>
          <input ref={fileInput} hidden type="file" accept="image/*" multiple onChange={(event) => void uploadFiles(event.target.files)} />
          <div className="v3-prompt-upload-summary"><b>업로드 이미지 · {uploads.length}건</b><span>프롬프트 생성 요청 전에는 이미지별로 삭제할 수 있습니다.</span><div className="v3-prompt-upload-preview-list">{uploads.slice(0, 6).map((upload) => <div className="v3-prompt-upload-preview" key={upload.assetId}><ProtectedImage src={upload.downloadUrl} alt={upload.fileName} /><button type="button" disabled={busy || Boolean(drafts[upload.assetId])} aria-label="업로드 이미지 삭제" onClick={() => void deleteUpload(upload)}>삭제</button></div>)}{uploads.length > 6 ? <em>+{uploads.length - 6}</em> : null}</div></div>
          <div className="v3-prompt-batch-action"><small>BATCH PROMPT GENERATION</small><strong>{uploads.length} Images</strong><span>현재 입력 대기 {dashboard.waiting} · 진행 중 배치 {activePromptGenerationBatches.length}</span><button className="v3-primary-button" type="button" disabled={!workflowId || !instructionStatus?.configured || !uploads.length || busy} onClick={() => void generateAll()}>{busy ? "요청 중..." : `Generate Prompts for ${uploads.length} Images`}</button></div>
        </div>
      </section>

      <section className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Prompt Generation Dashboard</div><span className="v3-muted-text">Grok 요청 진행 상태</span></div>
        {!activePromptGenerationBatches.length ? <div className="v3-empty-panel">진행 중인 프롬프트 생성 배치가 없습니다. 새 이미지를 업로드해 요청을 시작하세요.</div> : <div className="v3-prompt-batch-dashboard-list"><div className="v3-prompt-batch-dashboard"><div className="v3-prompt-batch-dashboard-title"><b>통합 진행 현황</b><span>{activePromptGenerationBatches.length}개 배치</span></div><div className="v3-prompt-dashboard"><div className="is-total"><small>ALL IMAGES</small><strong>{activeBatchDashboard.total}</strong><i><b style={{ width: `${activeBatchDashboard.total ? (activeBatchDashboard.waiting / activeBatchDashboard.total) * 100 : 0}%` }} /><b style={{ width: `${activeBatchDashboard.total ? (activeBatchDashboard.generatingCount / activeBatchDashboard.total) * 100 : 0}%` }} /><b style={{ width: `${activeBatchDashboard.total ? (activeBatchDashboard.readyCount / activeBatchDashboard.total) * 100 : 0}%` }} /><b style={{ width: `${activeBatchDashboard.total ? (activeBatchDashboard.failedCount / activeBatchDashboard.total) * 100 : 0}%` }} /></i></div><div><small>WAITING</small><strong>{activeBatchDashboard.waiting}</strong></div><div><small>GENERATING</small><strong>{activeBatchDashboard.generatingCount}</strong></div><div><small>COMPLETED</small><strong>{activeBatchDashboard.readyCount}</strong></div><div><small>FAILED</small><strong>{activeBatchDashboard.failedCount}</strong></div></div></div><div className="v3-prompt-batch-progress-list"><div className="v3-prompt-batch-progress-head"><b>진행 내역</b><span>{activeBatchStart}–{activeBatchEnd} / {activePromptGenerationBatches.length}건</span></div>{paginatedActivePromptGenerationBatches.map((activeBatch) => { const activeItems = activeBatch.items; const waitingCount = activeItems.filter((item) => item.status === "PENDING").length; const generatingCount = activeItems.filter((item) => item.status === "GENERATING").length; const readyCount = activeItems.filter((item) => item.status === "READY" || item.status === "MANUAL_REQUIRED").length; const failedCount = activeItems.filter((item) => item.status === "FAILED").length; return <div className="v3-prompt-batch-progress-row" key={activeBatch.id}><b>{activeBatch.id}</b><span>{workflowName(workflows.find((workflow) => workflow.id === activeBatch.workflowId) || { id: activeBatch.workflowId } as WorkflowItem)}</span><small>전체 {activeBatch.totalCount} · 대기 {waitingCount} · 생성 {generatingCount} · 완료 {readyCount} · 실패 {failedCount}</small></div>; })}<div className="v3-pagination"><span className="v3-pagination-meta">{activeBatchStart}–{activeBatchEnd} / {activePromptGenerationBatches.length}</span><div className="v3-pagination-controls"><button className="v3-page-button" type="button" disabled={safeActiveBatchPage <= 1} onClick={() => setActiveBatchPage((value) => Math.max(1, value - 1))}>이전</button><span className="v3-page-button is-current">{safeActiveBatchPage}</span><button className="v3-page-button" type="button" disabled={safeActiveBatchPage >= activeBatchPageCount} onClick={() => setActiveBatchPage((value) => Math.min(activeBatchPageCount, value + 1))}>다음</button></div></div></div></div>}
        <p className="v3-prompt-dashboard-note">배치별 항목이 모두 완료 또는 실패하면 이 목록에서 빠지고 Prompt History에 남습니다. 새 업로드와 새 요청은 진행 중 배치와 독립적으로 계속할 수 있습니다.</p>
      </section>

      <section className="v3-card v3-prompt-mapping-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Image Prompt Mapping</div><span className="v3-muted-text">이미지별 Positive Prompt</span></div>
        {!promptMappingRows.length ? <div className="v3-empty-panel">상단에서 이미지 파일을 한 장 이상 추가하세요.</div> : <div className="v3-prompt-mapping-table"><div className="v3-prompt-mapping-head"><span>이미지</span><span>입력 파일</span><span>프롬프트 배치</span><span>Positive Prompt</span><span>생성 상태</span><span>후속 처리</span><span>작업</span></div>{promptMappingRows.map(({ upload, draft, batchId }, index) => {
          const status = promptDisplayStatus(draft?.status || "WAITING");
          return <article className="v3-prompt-mapping-row" key={draft?.draftId || upload.assetId}><ProtectedImage src={upload.downloadUrl} alt={upload.fileName} /><div className="v3-prompt-file-meta"><b>IMG {String(index + 1).padStart(2, "0")}</b><strong>{upload.fileName}</strong><small>{formatImageDimensions(upload.imageHeight, upload.imageWidth)} · {formatUploadSize(upload.sizeBytes)}</small></div><span className="v3-prompt-batch-id">{batchId || "작성 중"}</span><div className="v3-prompt-positive"><textarea value={draft?.positivePrompt || ""} disabled={!draft || draft.status === "GENERATING"} onChange={(event) => draft && updateVisibleDraft({ ...draft, positivePrompt: event.target.value })} onBlur={(event) => draft && void saveDraft(draft, { positivePrompt: event.target.value })} placeholder="일괄 생성 후 결과가 표시됩니다." />{draft?.error ? <small className="v3-error-text">{draft.error}</small> : null}</div><span className={`v3-draft-status is-${status.toLowerCase()}`}>{status}</span><span className="v3-prompt-followup">{draft?.status === "READY" || draft?.status === "MANUAL_REQUIRED" ? "RunPod 요청 가능" : draft?.status === "FAILED" ? "재생성 후 요청 가능" : "완료 후 요청 가능"}</span><div className="v3-prompt-row-actions"><button className="v3-text-button" type="button" disabled={!draft || draft.status === "GENERATING"} onClick={() => draft && void retry(draft, upload.fileName)}>재생성</button><button className="v3-text-button is-delete" type="button" disabled={busy || draft?.status === "GENERATING"} aria-label={draft ? "프롬프트 항목 삭제" : "업로드 이미지 삭제"} onClick={() => draft ? void deletePromptRow(draft) : void deleteUpload(upload)}>삭제</button></div></article>;
        })}</div>}
      </section>

      <section className="v3-card"><div className="v3-card-header"><div className="v3-card-header-title">Built-in Negative Prompt</div><span className="v3-muted-text">모든 이미지 요청에 workflow 기본값으로 적용 · 수정 가능</span></div><label className="v3-prompt-negative"><b>Negative Prompt</b><textarea value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} placeholder="워크플로우 기본 negative prompt" /><small>수정한 값은 이후 RunPod 요청에 적용됩니다. Positive Prompt는 이미지별 생성 결과를 그대로 유지합니다.</small></label></section>
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
    </AppShell>
  );
}
