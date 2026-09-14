import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiClient, DashboardRange, DashboardRecentTask, DashboardSummary } from "../api/client";
import { User, canUse } from "../auth";
import { AppShell } from "../components/AppShell";
import { shellNavigate, shellNavigateAdmin } from "../helpers/navigation";
import { StudioRoute } from "../router";

// 2026-09-13: 로그인 랜딩 대시보드 (spec docs/superpowers/specs/2026-09-13-dashboard-landing-design.md,
// 목업 A "데이터 우선"). 전역 정책 — 로그인한 모든 사용자에게 표시. 데이터는
// GET /api/dashboard/summary 한 번으로 받고, 실패 시 마지막 성공 값을 유지한다.

// area="admin"이면 관리자 콘솔 쉘(ADMIN 사이드바) 안에서 같은 대시보드를 그린다
// (route admin.dashboard) — 스튜디오↔관리자 콘솔 전환의 기본 도착지.
type Props = { user: User; onGoTo: (route: StudioRoute) => void; area?: "generate" | "admin" };

const RANGE_STORAGE_KEY = "dobedub.dashboard.range";
const REFRESH_INTERVAL_MS = 60_000;
const RANGE_OPTIONS: Array<{ value: DashboardRange; label: string }> = [
  { value: "today", label: "오늘" },
  { value: "7d", label: "7일" },
  { value: "30d", label: "30일" }
];

function readStoredRange(): DashboardRange {
  try {
    const stored = localStorage.getItem(RANGE_STORAGE_KEY);
    if (stored === "today" || stored === "7d" || stored === "30d") return stored;
  } catch {
    // localStorage unavailable — fall through to the default
  }
  return "7d";
}

export function DashboardScreen({ user, onGoTo, area = "generate" }: Props) {
  const [range, setRangeState] = useState<DashboardRange>(readStoredRange);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const [filters, setFilters] = useState({ user: "", workflow: "", status: "" });
  const rangeRef = useRef(range);
  rangeRef.current = range;
  const pendingRetryRef = useRef<number | null>(null);

  const load = useCallback(async (nextRange?: DashboardRange) => {
    const target = nextRange || rangeRef.current;
    setLoading(true);
    try {
      const response = await apiClient.dashboardSummary(target);
      setSummary(response);
      setError("");
      setLastCheckedAt(new Date());
      // 2026-09-13 성능: 서버가 Sandbox 블록을 백그라운드로 갱신 중(pending)이면 4초 뒤 1회만 재조회한다.
      if (response.sandbox?.pending && pendingRetryRef.current === null) {
        pendingRetryRef.current = window.setTimeout(() => {
          pendingRetryRef.current = null;
          void load();
        }, 4000);
      }
    } catch (cause) {
      // 마지막 성공 값은 유지하고 헤더에만 실패를 표시한다.
      setError(cause instanceof Error ? cause.message : "대시보드를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      void load();
    }, REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      if (pendingRetryRef.current !== null) window.clearTimeout(pendingRetryRef.current);
    };
  }, [load]);

  function setRange(next: DashboardRange) {
    setRangeState(next);
    try {
      localStorage.setItem(RANGE_STORAGE_KEY, next);
    } catch {
      // ignore
    }
    void load(next);
  }

  const go = (route: StudioRoute, permission?: string) => {
    if (permission && !canUse(user, permission)) return undefined;
    return () => onGoTo(route);
  };

  const recentRows = useMemo(() => {
    const rows = summary?.recent || [];
    return rows.filter((row) => (
      (!filters.user || (row.user.name || row.user.id || "") === filters.user)
      && (!filters.workflow || row.workflowName === filters.workflow)
      && (!filters.status || row.statusKind === filters.status)
    ));
  }, [summary, filters]);

  const userOptions = useMemo(() => uniq((summary?.recent || []).map((row) => row.user.name || row.user.id || "")), [summary]);
  const workflowOptions = useMemo(() => uniq((summary?.recent || []).map((row) => row.workflowName)), [summary]);

  const checkedLabel = lastCheckedAt ? formatClock(lastCheckedAt) : "-";
  const rangeLabel = RANGE_OPTIONS.find((option) => option.value === range)?.label || range;

  return (
    <AppShell
      user={user}
      area={area}
      activeItem="dashboard"
      onNavigate={(key) => (area === "admin" ? shellNavigateAdmin(key, onGoTo) : shellNavigate(key, onGoTo))}
      headerEyebrow="HOME · DASHBOARD"
      headerTitle="시스템 상태 · 작업 현황"
      headerActions={(
        <div className="v3-dash-header-actions">
          {error
            ? <span className="v3-status-badge is-failed" title={error}>갱신 실패 {checkedLabel} · 재시도 중</span>
            : <span className="v3-dash-checked">마지막 확인 {checkedLabel} KST · 60초마다 자동 갱신</span>}
          <button className="v3-secondary-button" type="button" disabled={loading} onClick={() => void load()}>새로고침</button>
        </div>
      )}
    >
      {!summary ? (
        <DashboardSkeleton error={error} />
      ) : (
        <>
          <SystemTiles summary={summary} go={go} />

          <div className="v3-card v3-dash-kpi">
            <div className="v3-card-header">
              <div className="v3-card-header-title">
                <span>작업 현황</span>
                <div className="v3-dash-chips" role="tablist" aria-label="기간">
                  {RANGE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      role="tab"
                      aria-selected={option.value === range}
                      className={`v3-dash-chip${option.value === range ? " is-on" : ""}`}
                      onClick={() => setRange(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <span className="v3-card-header-meta">{formatRangeMeta(summary)} · 작업 이력 기준</span>
            </div>
            <KpiStrip summary={summary} />
          </div>

          <div className="v3-dash-columns">
            <div className="v3-card v3-dash-recent">
              <div className="v3-card-header">
                <div className="v3-card-header-title">
                  <span>최근 작업</span>
                  <div className="v3-dash-chips">
                    <select className="v3-dash-filter" value={filters.user} onChange={(event) => setFilters({ ...filters, user: event.target.value })} aria-label="작업자 필터">
                      <option value="">작업자 전체</option>
                      {userOptions.map((name) => <option key={name} value={name}>{name}</option>)}
                    </select>
                    <select className="v3-dash-filter" value={filters.workflow} onChange={(event) => setFilters({ ...filters, workflow: event.target.value })} aria-label="워크플로 필터">
                      <option value="">워크플로 전체</option>
                      {workflowOptions.map((name) => <option key={name} value={name}>{name}</option>)}
                    </select>
                    <select className="v3-dash-filter" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })} aria-label="상태 필터">
                      <option value="">상태 전체</option>
                      <option value="active">진행 중</option>
                      <option value="queued">대기</option>
                      <option value="completed">완료</option>
                      <option value="failed">실패</option>
                    </select>
                  </div>
                </div>
                {canUse(user, "history:read")
                  ? <button className="v3-link-button" type="button" onClick={() => onGoTo("review.history")}>작업 이력 전체 보기 →</button>
                  : null}
              </div>
              <RecentTasksTable rows={recentRows} empty={summary.recent.length === 0 ? `${rangeLabel} 내 작업이 없습니다.` : "필터에 맞는 작업이 없습니다."} />
            </div>

            <div className="v3-dash-side">
              <BreakdownBars
                title={`작업자별 · ${rangeLabel}`}
                meta="제출 / 실패"
                rows={summary.byUser.map((row) => ({ key: row.userId || row.name, label: row.name, value: row.submitted, sub: `${row.submitted} / ${row.failed}` }))}
                mono={false}
              />
              <BreakdownBars
                title={`워크플로별 · ${rangeLabel}`}
                meta="제출 · 평균 실행"
                rows={summary.byWorkflow.map((row) => ({ key: row.workflowId, label: row.workflowName, value: row.submitted, sub: `${row.submitted} · ${formatDuration(row.avgElapsedSeconds)}` }))}
                mono
              />
              <AlertsCard summary={summary} onGoTo={onGoTo} user={user} />
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}

// --- blocks ---------------------------------------------------------------------

function SystemTiles({ summary, go }: { summary: DashboardSummary; go: (route: StudioRoute, permission?: string) => (() => void) | undefined }) {
  const { system, sandbox, worker, db } = summary;
  const comfyState = !system.comfy.configured && !system.comfy.dryRun ? "off" : system.comfy.dryRun ? "warn" : "on";
  const comfyLabel = system.comfy.dryRun ? "DRY-RUN" : system.comfy.configured ? "ONLINE" : "NOT CONFIGURED";
  const llmMock = (system.promptLlm.provider || "").toLowerCase() === "mock";
  const llmState = !system.promptLlm.configured ? "off" : llmMock ? "muted" : "on";
  const llmLabel = !system.promptLlm.configured ? "NOT CONFIGURED" : llmMock ? "MOCK" : "ONLINE";
  const sandboxStatus = (sandbox.desiredStatus || "").toUpperCase();
  const sandboxState = sandbox.pending ? "muted" : sandbox.error || sandbox.conflict ? "off" : sandboxStatus === "RUNNING" ? "on" : "muted";
  const sandboxLabel = sandbox.pending ? "조회 중…" : sandbox.error ? "FAIL" : sandbox.conflict ? "CONFLICT" : !sandbox.configured ? "NOT CONFIGURED" : sandbox.podCount === 0 ? "NO POD" : sandboxStatus || "-";
  const ratio = worker.maxActiveTasksTotal ? worker.active / worker.maxActiveTasksTotal : 0;
  const workerState = ratio >= 1 ? "off" : ratio >= 0.8 ? "warn" : "on";
  const dbState = db.error ? "warn" : db.migrationRequired ? "warn" : "on";

  return (
    <div className="v3-dash-tiles">
      <Tile label="COMFYUI SERVERLESS" state={comfyState} onClick={go("admin.status", "system:read")}>
        <strong>{comfyLabel}</strong>
        <small>실행 모드 {system.comfy.executionMode}</small>
      </Tile>
      <Tile label="QWEN PROMPT LLM" state={llmState} onClick={go("admin.status", "system:read")}>
        <strong>{llmLabel}</strong>
        <small>{[system.promptLlm.provider, system.promptLlm.model, system.promptLlm.timeoutSeconds ? `timeout ${system.promptLlm.timeoutSeconds}s` : ""].filter(Boolean).join(" · ") || "-"}</small>
      </Tile>
      <Tile label="SANDBOX POD" state={sandboxState} onClick={go("admin.sandbox", "sandbox:read")}>
        <span className="v3-dash-tile-row">
          <strong>{sandboxLabel}</strong>
          {sandbox.gpuTier === "primary" ? <span className="v3-status-badge is-ready">primary</span> : null}
          {sandbox.gpuTier === "fallback" ? <span className="v3-status-badge is-pending">fallback</span> : null}
        </span>
        <small title={sandbox.error || undefined}>
          {sandbox.pending
            ? "RunPod 파드 목록을 가져오는 중입니다"
            : sandbox.error
            ? sandbox.error
            : sandbox.configured
              ? `${sandbox.activePodName || sandbox.activePodId || "활성 파드 없음"} · ${sandbox.podCount} pods · ${sandbox.runningCount} running`
              : "RUNPOD_SANDBOX_* 미설정"}
        </small>
      </Tile>
      <Tile label="RUNPOD WORKER" state={workerState} onClick={go("admin.taskPolicy", "roles:read")}>
        <span className="v3-dash-tile-row"><strong>{worker.active} / {worker.maxActiveTasksTotal}</strong><small>동시 실행</small></span>
        <span className="v3-dash-bar"><i style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }} /></span>
        <small>대기열 {worker.queued} · 정책: 최대 {worker.maxActiveTasksTotal} · 사용자당 {worker.maxActiveTasksPerUser}</small>
      </Tile>
      <Tile label="WORKFLOWS · DB" state={dbState} onClick={go("admin.workflows", "workflows:read")}>
        <strong>{system.workflows.count ?? "-"} 정의 · {db.migrationRequired ? "마이그레이션 필요" : db.error ? "확인 불가" : "정상"}</strong>
        <small title={db.error || undefined}>{db.error ? db.error : `alembic ${db.alembicCurrent || "-"}${db.migrationRequired ? ` → ${db.alembicHead}` : " · 최신"}`}</small>
      </Tile>
    </div>
  );
}

function Tile({ label, state, onClick, children }: { label: string; state: "on" | "warn" | "off" | "muted"; onClick?: () => void; children: React.ReactNode }) {
  const body = (
    <>
      <div className="v3-dash-tile-head"><span>{label}</span><i className={`v3-dash-dot is-${state}`} aria-hidden="true" /></div>
      {children}
    </>
  );
  // 2026-09-13 지침 §6: 타일 좌측 4px 바 = 상태 색(점과 동일). 색만 추가, 판정 로직 불변.
  return onClick
    ? <button type="button" className={`v3-card v3-dash-tile is-link is-state-${state}`} onClick={onClick}>{body}</button>
    : <div className={`v3-card v3-dash-tile is-state-${state}`}>{body}</div>;
}

function KpiStrip({ summary }: { summary: DashboardSummary }) {
  const { kpi } = summary;
  const delta = kpi.submittedDeltaPercent;
  return (
    <div className="v3-dash-kpi-grid">
      <Kpi label="제출" value={kpi.submitted} sub={delta == null ? "직전 기간 데이터 없음" : `직전 기간 대비 ${delta > 0 ? "+" : ""}${delta}%`} />
      <Kpi label="완료" value={kpi.completed} tone="ok" sub={kpi.successRate == null ? "완료/실패 없음" : `성공률 ${(kpi.successRate * 100).toFixed(1)}%`} />
      <Kpi label="진행 중" value={kpi.active} tone="running" sub={`큐 대기 ${kpi.queued} 포함`} />
      <Kpi label="실패" value={kpi.failed} tone="fail" sub={`dispatch 오류 ${kpi.failedDispatch} · 타임아웃 ${kpi.failedTimeout}`} />
      <Kpi label="평균 실행" value={formatDuration(kpi.avgElapsedSeconds)} sub={`지연 평균 ${formatDuration(kpi.avgDelaySeconds)}`} />
      <Kpi label="활성 작업자" value={kpi.activeUsers} sub={`Batch ${kpi.batchJobsInProgress}건 진행 중`} />
    </div>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub: string; tone?: "ok" | "running" | "fail" }) {
  return (
    <div className="v3-dash-kpi-cell">
      <span>{label}</span>
      <strong className={tone ? `is-${tone}` : undefined}>{value}</strong>
      <small>{sub}</small>
    </div>
  );
}

function RecentTasksTable({ rows, empty }: { rows: DashboardRecentTask[]; empty: string }) {
  if (!rows.length) return <div className="v3-empty-panel">{empty}</div>;
  return (
    <div className="v3-dash-table-wrap">
      <table className="v3-dash-table">
        <thead>
          <tr><th>시각</th><th>작업자</th><th>워크플로</th><th>워커</th><th>상태</th><th className="is-right">실행</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.taskId} title={row.taskId}>
              <td className="is-mono is-muted">{formatTaskTime(row.createdAtKst || row.createdAt)}</td>
              <td>{row.user.name || row.user.id || "-"}</td>
              <td className="is-mono">{row.workflowName}</td>
              <td className="is-mono is-muted">{row.workerName || "-"}</td>
              <td><span className={`v3-status-badge ${statusBadgeClass(row.statusKind)}`}>{statusLabel(row)}</span></td>
              <td className="is-mono is-right">{row.statusKind === "failed" ? shortError(row) : row.statusKind === "queued" ? "—" : formatDuration(row.elapsedSeconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakdownBars({ title, meta, rows, mono }: { title: string; meta: string; rows: Array<{ key: string; label: string; value: number; sub: string }>; mono: boolean }) {
  const max = rows.reduce((top, row) => Math.max(top, row.value), 0);
  return (
    <div className="v3-card">
      <div className="v3-card-header"><div className="v3-card-header-title">{title}</div><span className="v3-card-header-meta">{meta}</span></div>
      {rows.length ? (
        <div className="v3-dash-bars">
          {rows.map((row) => (
            <div key={row.key} className={`v3-dash-bar-row${mono ? " is-mono" : ""}`}>
              <span title={row.label}>{row.label}</span>
              <span className="v3-dash-bar"><i style={{ width: `${max ? Math.round((row.value / max) * 100) : 0}%` }} /></span>
              <small>{row.sub}</small>
            </div>
          ))}
        </div>
      ) : <div className="v3-empty-panel">기간 내 작업이 없습니다.</div>}
    </div>
  );
}

function AlertsCard({ summary, onGoTo, user }: { summary: DashboardSummary; onGoTo: (route: StudioRoute) => void; user: User }) {
  if (!summary.alerts.length) return null;
  const danger = summary.alerts.some((alert) => alert.level === "danger");
  return (
    <div className={`v3-card v3-dash-alerts${danger ? " is-danger" : ""}`}>
      <span className="v3-dash-alerts-label">주의 필요 · {summary.alerts.length}</span>
      {summary.alerts.map((alert) => {
        const route = alert.route as StudioRoute | undefined;
        const permission = route ? ALERT_ROUTE_PERMISSION[route] : undefined;
        const clickable = route && (!permission || canUse(user, permission));
        return clickable
          ? <button key={alert.id} type="button" className="v3-dash-alert is-link" onClick={() => onGoTo(route)}>{alert.message}</button>
          : <div key={alert.id} className="v3-dash-alert">{alert.message}</div>;
      })}
    </div>
  );
}

const ALERT_ROUTE_PERMISSION: Partial<Record<string, string>> = {
  "admin.sandbox": "sandbox:read",
  "admin.taskPolicy": "roles:read",
  "admin.status": "system:read",
  "review.history": "history:read"
};

function DashboardSkeleton({ error }: { error: string }) {
  return (
    <div className="v3-dash-skeleton" aria-busy="true">
      {error ? <p className="v3-inline-notice">{error}</p> : null}
      <div className="v3-dash-tiles">{[0, 1, 2, 3, 4].map((index) => <div key={index} className="v3-card v3-dash-tile is-skeleton" />)}</div>
      <div className="v3-card v3-dash-kpi is-skeleton" />
      <div className="v3-dash-columns"><div className="v3-card v3-dash-recent is-skeleton" /><div className="v3-card is-skeleton" /></div>
    </div>
  );
}

// --- helpers --------------------------------------------------------------------

function uniq(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((left, right) => left.localeCompare(right, "ko"));
}

function formatClock(value: Date): string {
  return value.toLocaleTimeString("ko-KR", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Asia/Seoul" });
}

function formatRangeMeta(summary: DashboardSummary): string {
  const since = (summary.sinceKst || summary.since || "").slice(0, 10);
  const until = (summary.untilKst || summary.until || "").slice(5, 10);
  return since && until ? `${since} → ${until}` : "";
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return "-";
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function formatTaskTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(11, 16) || value;
  const today = new Date();
  const sameDay = date.toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" }) === today.toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" });
  const time = date.toLocaleTimeString("ko-KR", { hour12: false, hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul" });
  if (sameDay) return time;
  const day = date.toLocaleDateString("en-CA", { month: "2-digit", day: "2-digit", timeZone: "Asia/Seoul" });
  return `${day} ${time}`;
}

function statusBadgeClass(kind: DashboardRecentTask["statusKind"]): string {
  if (kind === "completed") return "is-ready";
  if (kind === "failed") return "is-failed";
  if (kind === "active" || kind === "queued") return "is-running";
  return "is-muted";
}

function statusLabel(row: DashboardRecentTask): string {
  if (row.statusKind === "queued") return "QUEUED";
  return row.status || "-";
}

function shortError(row: DashboardRecentTask): string {
  if (row.status === "TIMED_OUT") return "timeout";
  if (row.status === "CANCELLED") return "cancelled";
  if (row.lastDispatchError) return "dispatch";
  return "failed";
}
