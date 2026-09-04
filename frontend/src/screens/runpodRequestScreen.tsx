import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiClient, HealthResponse, RunpodConnectionResponse, RunpodRequestBatchResponse, RunpodRequestDashboardResponse, RunpodRequestQueueItemResponse, RunpodRequestQueueResponse, WorkflowItem } from "../api/client";
import { canUse, User } from "../auth";
import { AppShell } from "../components/AppShell";
import { ProtectedImage } from "../components/ProtectedAssets";
import { shellNavigate } from "../helpers/navigation";
import { StudioRoute } from "../router";
import { loadRunpodWorkspace, saveRunpodWorkspace } from "../state/durableWorkspace";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; workflows: WorkflowItem[] };
const TERMINAL_RUNPOD_STATES = new Set(["COMPLETED", "PARTIAL_FAILED", "FAILED", "CANCELLED", "TIMED_OUT"]);
const ACTIVE_RUNPOD_STATES = new Set(["IN_PROGRESS", "RUNNING"]);
const QUEUED_RUNPOD_STATES = new Set(["PENDING_SUBMIT", "DISPATCHING", "QUEUED", "IN_QUEUE"]);
const ALL_WORKERS_FILTER = "all";
const ALL_WORKFLOWS_FILTER = "";
const ALL_REQUEST_STATUS_FILTER = "requestable";
const REQUEST_STATUS_FILTERS = [
  { value: "requestable", label: "요청 준비" },
  { value: "submitWaiting", label: "제출 대기" },
  { value: "runpodQueued", label: "RunPod 큐" },
  { value: "inProgress", label: "실행 중" },
  { value: "failed", label: "실패" },
  { value: "all", label: "전체 상태" }
];

function workflowName(workflow: WorkflowItem | undefined, fallback: string) {
  return workflow?.label || workflow?.name || fallback;
}

function requestState(item: RunpodRequestQueueItemResponse) {
  if (item.canSubmit) return "요청 준비";
  const state = String(item.status || "").toUpperCase();
  if (ACTIVE_RUNPOD_STATES.has(state)) return "실행 중";
  if (QUEUED_RUNPOD_STATES.has(state)) return state === "PENDING_SUBMIT" ? "요청 대기" : "RunPod Queued";
  if (state === "FAILED" || state === "CANCELLED" || state === "TIMED_OUT") return "실패";
  return state || "등록됨";
}

export function RunpodRequestScreen({ user, health: _health, onGoTo, workflows }: Props) {
  const canManageRequests = canUse(user, "jobs:manage");
  const [initialWorkspace] = useState(() => loadRunpodWorkspace(user.id));
  const [queue, setQueue] = useState<RunpodRequestQueueResponse | null>(null);
  const [selected, setSelected] = useState<string[]>(initialWorkspace.selectedDraftIds);
  const [workflowOverrides, setWorkflowOverrides] = useState<Record<string, string>>(initialWorkspace.workflowOverrides);
  const [requestBatch, setRequestBatch] = useState<RunpodRequestBatchResponse | null>(null);
  const [requestDashboard, setRequestDashboard] = useState<RunpodRequestDashboardResponse | null>(null);
  const [workerStats, setWorkerStats] = useState<Array<{ workerId?: string | null; workerName?: string | null }>>([]);
  const [workerFilter, setWorkerFilter] = useState(() => canManageRequests ? ALL_WORKERS_FILTER : user.id);
  const [workflowFilter, setWorkflowFilter] = useState(ALL_WORKFLOWS_FILTER);
  const [statusFilter, setStatusFilter] = useState(ALL_REQUEST_STATUS_FILTER);
  const [requestPage, setRequestPage] = useState(1);
  const filterInitialized = useRef(false);
  const latestLoadRequestRef = useRef(0);
  const [connection, setConnection] = useState<RunpodConnectionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  async function load(restoreWorkspace = true, page = requestPage) {
    const loadRequestId = ++latestLoadRequestRef.current;
    try {
      const selectedWorkerId = canManageRequests ? workerFilter : user.id;
      const requestedBatch = restoreWorkspace && initialWorkspace.requestBatchId
        ? apiClient.runpodRequestBatch(initialWorkspace.requestBatchId).catch(() => null)
        : selectedWorkerId === ALL_WORKERS_FILTER
          ? Promise.resolve(null)
          : apiClient.activeRunpodRequestBatch(selectedWorkerId).then((response) => response.item);
      const [requestQueue, list, status, restoredBatch, dashboard] = await Promise.all([
        apiClient.runpodRequestQueue({ workerId: selectedWorkerId === ALL_WORKERS_FILTER ? ALL_WORKERS_FILTER : selectedWorkerId, workflowId: workflowFilter, statusFilter, page, pageSize: 10 }),
        apiClient.imagePromptDrafts({ workerId: selectedWorkerId === ALL_WORKERS_FILTER ? ALL_WORKERS_FILTER : selectedWorkerId, workflowId: workflowFilter, pageSize: 1 }),
        apiClient.runpodConnection(),
        requestedBatch,
        apiClient.runpodRequestDashboard()
      ]);
      if (loadRequestId !== latestLoadRequestRef.current) return;
      setQueue(requestQueue);
      setConnection(status);
      setRequestBatch(restoredBatch);
      setRequestDashboard(dashboard);
      setWorkerStats(list.workerStats);
    } catch (error) {
      if (loadRequestId !== latestLoadRequestRef.current) return;
      setNotice(error instanceof Error ? error.message : "RunPod 요청 정보를 불러오지 못했습니다.");
    }
  }
  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (!filterInitialized.current) {
      filterInitialized.current = true;
      return;
    }
    setSelected([]);
    setRequestBatch(null);
    setRequestPage(1);
    void load(false, 1);
  }, [workerFilter, workflowFilter, statusFilter]);

  useEffect(() => {
    if (!requestDashboard || !requestDashboard.totals.incomplete) return;
    const timer = window.setInterval(() => {
      void load(false);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [requestDashboard?.totals.incomplete, requestPage, workerFilter, workflowFilter, statusFilter]);

  useEffect(() => {
    saveRunpodWorkspace(user.id, {
      selectedDraftIds: selected,
      workflowOverrides,
      requestBatchId: requestBatch?.id
    });
  }, [requestBatch?.id, selected, user.id, workflowOverrides]);

  const rows = queue?.items || [];
  const selectable = useMemo(() => rows.filter((item) => {
    const workflow = workflows.find((workflow) => workflow.id === item.workflowId);
    return item.canSubmit && Boolean(item.promptDraftId) && (workflow?.keyframeCount || 1) === 1;
  }), [rows, workflows]);
  const dashboard = requestDashboard?.totals || {
    incomplete: 0,
    requestWaiting: 0,
    runpodQueued: 0,
    inProgress: 0,
    failed: 0
  };

  const visibleWorkers = useMemo(() => {
    const indexed = new Map<string, { workerId: string; workerName: string }>();
    [...workerStats, ...(requestDashboard?.workers || [])].forEach((worker) => {
      const id = String(worker.workerId || "").trim();
      if (id) indexed.set(id, { workerId: id, workerName: String(worker.workerName || id) });
    });
    if (!indexed.has(user.id)) indexed.set(user.id, { workerId: user.id, workerName: user.name || user.id });
    return [...indexed.values()].sort((left, right) => left.workerName.localeCompare(right.workerName));
  }, [requestDashboard?.workers, user.id, user.name, workerStats]);

  async function submit() {
    if (!selected.length) return;
    setBusy(true);
    setNotice("");
    try {
      const groupedByWorker = new Map<string, RunpodRequestQueueItemResponse[]>();
      selected.forEach((draftId) => {
        const draft = rows.find((item) => item.promptDraftId === draftId);
        if (!draft?.canSubmit || !draft.promptDraftId) return;
        const ownerId = String(draft.workerId || user.id).trim() || user.id;
        const entries = groupedByWorker.get(ownerId) || [];
        entries.push(draft);
        groupedByWorker.set(ownerId, entries);
      });
      if (!groupedByWorker.size) {
        setNotice("요청 가능한 프롬프트 생성 결과를 선택하세요.");
        return;
      }
      const batches = await Promise.all([...groupedByWorker.entries()].map(([workerId, drafts]) => apiClient.createRunpodRequestBatch({
        workerId,
        items: drafts.map((draft) => ({
          promptDraftId: draft.promptDraftId!,
          workflowId: workflowOverrides[draft.promptDraftId!] || draft.workflowId,
          requestedFrames: draft.requestedFrames || 81
        }))
      })));
      setRequestBatch(batches.length === 1 ? batches[0] : null);
      setNotice(`${selected.length}건을 ${groupedByWorker.size}개 작업자별 요청 묶음으로 등록했습니다. 서버가 유휴 RunPod worker를 확인한 뒤 순차 전송합니다.`);
      setSelected([]);
      await load(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "RunPod 요청 등록에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function updateLength(draft: RunpodRequestQueueItemResponse, requestedFrames: number) {
    if (!draft.canSubmit || !draft.promptDraftId) return;
    try {
      const updated = await apiClient.updateImagePromptDraft(draft.promptDraftId, { requestedFrames });
      setQueue((current) => current ? {
        ...current,
        items: current.items.map((item) => item.promptDraftId === updated.draftId ? { ...item, requestedFrames: updated.requestedFrames || requestedFrames } : item)
      } : current);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Length 저장에 실패했습니다.");
    }
  }

  return (
    <AppShell user={user} area="generate" activeItem="runpodRequests" onNavigate={(key) => shellNavigate(key, onGoTo)} headerEyebrow="GENERATE · RUNPOD REQUEST MANAGEMENT" headerTitle="RunPod 요청 관리" headerActions={<><span className="v3-status-chip is-ok">GROK CONFIGURED</span><button className="v3-secondary-button" type="button" onClick={() => void load()}>상태 새로고침</button></>}>
      <section className="v3-card"><div className="v3-card-header"><div className="v3-card-header-title">RunPod Progress Dashboard</div><span className="v3-muted-text">미완료 작업만 표시 · 완료 결과는 Task History에서 조회</span></div>
        <div className="v3-runpod-progress-grid"><div className="is-total"><small>INCOMPLETE REQUESTS</small><strong>{dashboard.incomplete}</strong><i><b style={{ width: `${dashboard.incomplete ? (dashboard.requestWaiting / dashboard.incomplete) * 100 : 0}%` }} /><b style={{ width: `${dashboard.incomplete ? (dashboard.runpodQueued / dashboard.incomplete) * 100 : 0}%` }} /><b style={{ width: `${dashboard.incomplete ? (dashboard.inProgress / dashboard.incomplete) * 100 : 0}%` }} /><b style={{ width: `${dashboard.incomplete ? (dashboard.failed / dashboard.incomplete) * 100 : 0}%` }} /></i></div><div><small>REQUEST WAITING</small><strong>{dashboard.requestWaiting}</strong></div><div><small>RUNPOD QUEUED</small><strong>{dashboard.runpodQueued}</strong></div><div><small>IN PROGRESS</small><strong>{dashboard.inProgress}</strong></div><div><small>FAILED</small><strong>{dashboard.failed}</strong></div></div>
        <p className="v3-runpod-dashboard-note">유휴 worker {connection?.workers?.idle ?? "-"} · RunPod queue {connection?.jobs?.inQueue ?? "-"} · 선택 요청은 서버 작업 모니터가 유휴 worker를 확인해 하나씩 전송합니다.</p>
        {canManageRequests ? <div className="v3-runpod-worker-summary">{(requestDashboard?.workers || []).map((worker) => <div key={worker.workerId || "unknown"}><b>{worker.workerName || worker.workerId}</b><span>대기 {worker.requestWaiting} · 큐 {worker.runpodQueued} · 실행 {worker.inProgress} · 실패 {worker.failed}</span></div>)}{!(requestDashboard?.workers || []).length ? <span className="v3-muted-text">미완료 요청이 있는 작업자가 없습니다.</span> : null}</div> : null}
      </section>

      <section className="v3-card v3-runpod-request-card"><div className="v3-card-header"><div><div className="v3-card-header-title">Incomplete RunPod Requests</div><span className="v3-muted-text">생성 완료 이미지만 선택 · Workflow와 Length는 이미지별로 연결</span></div><button className="v3-primary-button" type="button" disabled={!selected.length || busy} onClick={() => void submit()}>{busy ? "등록 중..." : `선택 ${selected.length}건 RunPod 요청`}</button></div>
        <div className="v3-runpod-filter-bar">{canManageRequests ? <label>작업자<select value={workerFilter} onChange={(event) => setWorkerFilter(event.target.value)}><option value={ALL_WORKERS_FILTER}>전체 작업자</option>{visibleWorkers.map((worker) => <option key={worker.workerId} value={worker.workerId}>{worker.workerName}</option>)}</select></label> : null}<label>워크플로우<select value={workflowFilter} onChange={(event) => setWorkflowFilter(event.target.value)}><option value={ALL_WORKFLOWS_FILTER}>전체 워크플로우</option>{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflowName(workflow, workflow.id)}</option>)}</select></label><label>상태<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>{REQUEST_STATUS_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}</select></label></div>
        {!rows.length ? <div className="v3-empty-panel">표시할 미완료 RunPod 요청이 없습니다.</div> : <div className="v3-runpod-request-table"><div className="v3-runpod-request-head"><input type="checkbox" checked={selectable.length > 0 && selected.length === selectable.length} onChange={(event) => setSelected(event.target.checked ? selectable.flatMap((item) => item.promptDraftId ? [item.promptDraftId] : []) : [])} /><span>이미지</span><span>입력 파일</span><span>작업자</span><span>Prompt Batch ID</span><span>Item No.</span><span>Positive Prompt</span><span>Workflow</span><span>Length</span><span>상태</span></div>{rows.map((draft) => {
          const workflow = workflows.find((item) => item.id === draft.workflowId);
          const supported = (workflow?.keyframeCount || 1) === 1;
          const frames = draft.requestedFrames || 81;
          const draftId = draft.promptDraftId || "";
          const selectedWorkflowId = workflowOverrides[draftId] || draft.workflowId;
          const editable = draft.canSubmit && Boolean(draftId);
          return <article className={`v3-runpod-request-row${supported && editable ? "" : " is-disabled"}`} key={draft.id}><input type="checkbox" disabled={!supported || !editable} checked={Boolean(draftId) && selected.includes(draftId)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, draftId] : current.filter((id) => id !== draftId))} /><ProtectedImage src={`/api/files/${draft.assetId}`} alt={draft.asset?.fileName || draft.assetId} /><span className="v3-runpod-file-name">{draft.asset?.fileName || draft.assetId}</span><span className="v3-runpod-worker-name">{draft.workerName || draft.workerId || "-"}</span><span className="v3-runpod-batch-id">{draft.promptBatchId || "-"}</span><span className="v3-runpod-item-no">{draft.sequenceNo}</span><span className="v3-runpod-prompt-cell">{draft.positivePrompt}</span><select aria-label="워크플로우" disabled={!editable} value={selectedWorkflowId} onChange={(event) => setWorkflowOverrides((current) => ({ ...current, [draftId]: event.target.value }))}>{workflows.filter((item) => (item.keyframeCount || 1) === 1).map((item) => <option key={item.id} value={item.id}>{workflowName(item, item.id)}</option>)}</select><div className="v3-runpod-length-buttons">{[49, 81, 161].map((length) => <button key={length} type="button" disabled={!editable} className={frames === length ? "is-selected" : ""} onClick={() => void updateLength(draft, length)}>{length}</button>)}</div><span className={`v3-draft-status is-${requestState(draft).replace(/\s+/g, "-").toLowerCase()}`}>{supported ? requestState(draft) : "다중 keyframe 다음 단계"}</span></article>;
        })}</div>}
        <div className="v3-pagination"><span className="v3-pagination-meta">{queue?.total ? `${(requestPage - 1) * 10 + 1}-${Math.min(requestPage * 10, queue.total)} / ${queue.total}건` : "0건"} · 페이지당 10건</span><div className="v3-pagination-controls"><button className="v3-page-button" type="button" disabled={requestPage <= 1 || busy} onClick={() => { const next = requestPage - 1; setRequestPage(next); void load(false, next); }}>이전</button><span className="v3-pagination-meta">{requestPage} / {Math.max(1, Math.ceil((queue?.total || 0) / 10))}</span><button className="v3-page-button" type="button" disabled={busy || requestPage >= Math.max(1, Math.ceil((queue?.total || 0) / 10))} onClick={() => { const next = requestPage + 1; setRequestPage(next); void load(false, next); }}>다음</button></div></div>
      </section>
      <section className="v3-card"><div className="v3-card-header"><div className="v3-card-header-title">Request Handling</div><span className="v3-muted-text">선택한 미완료 작업의 일괄 처리</span></div><p className="v3-runpod-dashboard-note">선택 항목은 요청 전까지 Length를 변경할 수 있습니다. 등록 후 실행 중인 작업은 Task History에서 상태와 결과를 조회합니다.</p></section>
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
    </AppShell>
  );
}
