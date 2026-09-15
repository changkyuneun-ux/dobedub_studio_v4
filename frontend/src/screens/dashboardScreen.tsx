import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient, DashboardDailyVolume, DashboardFilterOption, DashboardRange, DashboardSummary } from "../api/client";
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
  // 2026-09-14: 필터는 더 이상 "최근 작업" 테이블을 클라이언트에서 자르지 않고,
  // 서버의 일자별 작업량 집계(dailyVolume)를 다시 요청하는 조건으로 쓰인다.
  const [filters, setFiltersState] = useState({ user: "", workflow: "", status: "" });
  const rangeRef = useRef(range);
  rangeRef.current = range;
  const filtersRef = useRef(filters);
  filtersRef.current = filters;
  const pendingRetryRef = useRef<number | null>(null);

  const load = useCallback(async (nextRange?: DashboardRange, nextFilters?: typeof filters) => {
    const target = nextRange || rangeRef.current;
    const targetFilters = nextFilters || filtersRef.current;
    setLoading(true);
    try {
      const response = await apiClient.dashboardSummary(target, 20, {
        user: targetFilters.user || undefined,
        workflow: targetFilters.workflow || undefined,
        status: targetFilters.status || undefined,
      });
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

  function setFilters(next: typeof filters) {
    setFiltersState(next);
    void load(undefined, next);
  }

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

  const userOptions = summary?.filterOptions.users || [];
  const workflowOptions = summary?.filterOptions.workflows || [];

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

          <DurationCostCard summary={summary} />

          <div className="v3-dash-columns">
            <div className="v3-card v3-dash-recent">
              <div className="v3-card-header">
                <div className="v3-card-header-title">
                  <span>작업량 추이</span>
                  <div className="v3-dash-chips">
                    <select className="v3-dash-filter" value={filters.user} onChange={(event) => setFilters({ ...filters, user: event.target.value })} aria-label="작업자 필터">
                      <option value="">작업자 전체</option>
                      {userOptions.map((option) => <option key={option.id || option.name} value={option.id || ""}>{option.name}</option>)}
                    </select>
                    <select className="v3-dash-filter" value={filters.workflow} onChange={(event) => setFilters({ ...filters, workflow: event.target.value })} aria-label="워크플로 필터">
                      <option value="">워크플로 전체</option>
                      {workflowOptions.map((option) => <option key={option.id || option.name} value={option.id || ""}>{option.name}</option>)}
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
              <DailyVolumeChart days={summary.dailyVolume} rangeLabel={rangeLabel} />
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
  const grokState = !system.grok.enabled ? "muted" : !system.grok.configured ? "off" : "on";
  const grokLabel = !system.grok.enabled ? "DISABLED" : !system.grok.configured ? "NOT CONFIGURED" : "ONLINE";
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
      <Tile label="GROK IMAGE PROMPT" state={grokState} onClick={go("admin.status", "system:read")}>
        <strong>{grokLabel}</strong>
        <small>{[system.grok.model, system.grok.timeoutSeconds ? `timeout ${system.grok.timeoutSeconds}s` : ""].filter(Boolean).join(" · ") || "-"}</small>
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
        <span className="v3-dash-tile-row"><strong>{formatNumber(worker.active)} / {formatNumber(worker.maxActiveTasksTotal)}</strong><small>동시 실행</small></span>
        <span className="v3-dash-bar"><i style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }} /></span>
        <small>대기열 {formatNumber(worker.queued)} · 정책: 최대 {formatNumber(worker.maxActiveTasksTotal)} · 사용자당 {formatNumber(worker.maxActiveTasksPerUser)}</small>
      </Tile>
      <Tile label="WORKFLOWS · DB" state={dbState} onClick={go("admin.workflows", "workflows:read")}>
        <strong>active {formatNumber(system.workflows.activeCount)}개 · {db.migrationRequired ? "마이그레이션 필요" : db.error ? "확인 불가" : "정상"}</strong>
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
      <Kpi label="제출" value={formatNumber(kpi.submitted)} sub={delta == null ? "직전 기간 데이터 없음" : `직전 기간 대비 ${delta > 0 ? "+" : ""}${delta}%`} />
      <Kpi label="완료" value={formatNumber(kpi.completed)} tone="ok" sub={kpi.successRate == null ? "완료/실패 없음" : `성공률 ${(kpi.successRate * 100).toFixed(1)}%`} />
      <Kpi label="진행 중" value={formatNumber(kpi.active)} tone="running" sub={`큐 대기 ${formatNumber(kpi.queued)} 포함`} />
      <Kpi label="실패" value={formatNumber(kpi.failed)} tone="fail" sub={`dispatch 오류 ${formatNumber(kpi.failedDispatch)} · 타임아웃 ${formatNumber(kpi.failedTimeout)}`} />
      <Kpi label="평균 실행" value={formatDuration(kpi.avgElapsedSeconds)} sub={`지연 평균 ${formatDuration(kpi.avgDelaySeconds)}`} />
      <Kpi label="활성 작업자" value={formatNumber(kpi.activeUsers)} sub={`Batch ${formatNumber(kpi.batchJobsInProgress)}건 진행 중`} />
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

// 2026-09-15: 컷 길이별(5초/10초) 서버리스 비용 배분 카드
// (spec: 대시보드 수정 설계 - 두비덥 스튜디오 v3 카드/테이블 스타일 재사용,
// 2026-09-15 목업 UI 기준). durationCostBreakdown은 UTC 캘린더일 기준이라
// 아래 "작업량 추이"(KST)와 자정 전후로 최대 하루 어긋날 수 있음 - 각주에 명시.
//
// 통화 표기: RunPod 청구 원본 통화(USD)를 그대로 표시한다. 목업 초안은 KRW를
// 우선 노출했으나, 이 카드의 핵심 요구사항이 "총액이 RunPod 청구와 정확히
// 일치"이므로 날짜별로 달라지는 환율을 끼워 넣으면 그 정합성 보장이 깨진다 -
// 실제 회계 환산 시점의 환율과 어긋날 수 있어 KRW 환산은 의도적으로 넣지 않음.
function DurationCostCard({ summary }: { summary: DashboardSummary }) {
  const breakdown = summary.durationCostBreakdown;
  const days = Object.keys(breakdown.byDay).sort();
  const s = breakdown.summary;
  const ratio =
    s && s.fiveSec.costPerJobUsd && s.tenSec.costPerJobUsd
      ? s.tenSec.costPerJobUsd / s.fiveSec.costPerJobUsd
      : null;

  return (
    <div className="v3-card v3-dash-duration">
      <div className="v3-card-header">
        <div className="v3-card-header-title">
          <span>컷 길이별 비용</span>
          <span className="v3-status-badge is-pending">2026-09-10 UTC부터 적용</span>
        </div>
        <span className="v3-card-header-meta">RunPod 서버리스 청구 · 실행시간 가중 배분</span>
      </div>

      {s ? (
        <div className="v3-dash-duration-strip">
          <div className="v3-dash-duration-cell">
            <span className="v3-dash-duration-label"><i className="v3-dash-duration-swatch is-5s" />5초컷 건당비용</span>
            <span className="v3-dash-duration-cost">{formatUsdPerJob(s.fiveSec.costPerJobUsd)}</span>
            <span className="v3-dash-duration-sub">{formatNumber(s.fiveSec.count)}건 · 누적 {formatUsd(s.fiveSec.costUsd)}</span>
          </div>
          <div className="v3-dash-duration-cell">
            <span className="v3-dash-duration-label"><i className="v3-dash-duration-swatch is-10s" />10초컷 건당비용</span>
            <span className="v3-dash-duration-cost">{formatUsdPerJob(s.tenSec.costPerJobUsd)}</span>
            <span className="v3-dash-duration-sub">{formatNumber(s.tenSec.count)}건 · 누적 {formatUsd(s.tenSec.costUsd)}</span>
          </div>
          <div className="v3-dash-duration-ratio">
            <span className="v3-dash-duration-ratio-value">{ratio ? `× ${ratio.toFixed(2)}` : "-"}</span>
            <span className="v3-dash-duration-ratio-label">
              {ratio ? `10초컷이 5초컷보다 건당 약 ${ratio.toFixed(2)}배 비용이 높음` : "표본이 부족해 비교할 수 없습니다"}
            </span>
          </div>
        </div>
      ) : (
        <div className="v3-empty-panel">2026-09-10 UTC 이후 구간에 RunPod 서버리스 작업이 아직 없습니다.</div>
      )}

      {days.length ? (
        <div className="v3-dash-table-wrap">
          <table className="v3-dash-table v3-dash-duration-table">
            <thead>
              <tr>
                <th>날짜(UTC)</th>
                <th className="is-right">제출</th>
                <th className="is-right">완료</th>
                <th className="is-right">실패</th>
                <th className="is-right">전체비용</th>
                <th className="is-right is-group-5s">5초컷 건수</th>
                <th className="is-right is-group-5s">5초컷 비용</th>
                <th className="is-right is-group-10s">10초컷 건수</th>
                <th className="is-right is-group-10s">10초컷 비용</th>
              </tr>
            </thead>
            <tbody>
              {days.map((day) => {
                const row = breakdown.byDay[day];
                return (
                  <tr key={day} className={row.split ? undefined : "is-before"}>
                    <td className="is-mono">{formatDayLabel(day)}</td>
                    <td className="is-right is-mono">{formatNumber(row.submitted)}</td>
                    <td className="is-right is-mono">{formatNumber(row.completed)}</td>
                    <td className="is-right is-mono">{formatNumber(row.failed)}</td>
                    <td className="is-right is-mono">{formatUsd(row.totalCostUsd)}</td>
                    {row.split ? (
                      <>
                        <td className="is-right is-mono">{formatNumber(row.split.fiveSec.count)}</td>
                        <td className="is-right is-mono">{formatUsd(row.split.fiveSec.costUsd)}</td>
                        <td className="is-right is-mono">{formatNumber(row.split.tenSec.count)}</td>
                        <td className="is-right is-mono">{formatUsd(row.split.tenSec.costUsd)}</td>
                      </>
                    ) : (
                      <>
                        <td className="is-right is-mono is-muted">—</td>
                        <td className="is-right is-mono is-muted">—</td>
                        <td className="is-right is-mono is-muted">—</td>
                        <td className="is-right is-mono is-muted">—</td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="v3-empty-panel">기간 내 RunPod 서버리스 작업이 없습니다.</div>
      )}

      <div className="v3-dash-duration-footnote">
        <b>2026-09-09 이전(UTC)</b>은 10초컷 워크플로 데이터가 없어(0건, 실 프로덕션 확인) 5초컷/10초컷으로 나누지 않고 전체 제출·완료·실패 건수와 전체비용만 표기합니다.{" "}
        <b>2026-09-10부터</b>는 워크플로 종류로 구분하고, 그 날 RunPod 청구 총액을 각 그룹의 실측 GPU 실행시간(executionTime) 비율로 배분합니다 — 두 값의 합은 항상 그 날 전체비용과 일치합니다.
        날짜는 RunPod 청구 기준(UTC 캘린더일)이라 위 "작업량 추이" 그래프의 날짜(KST)와 자정 전후로 최대 하루 어긋날 수 있습니다.
      </div>
    </div>
  );
}

function formatUsd(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `$${value.toFixed(2)}`;
}

function formatUsdPerJob(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `$${value.toFixed(4)}`;
}

function DailyVolumeChart({ days, rangeLabel }: { days: DashboardDailyVolume[]; rangeLabel: string }) {
  const total = days.reduce((sum, day) => sum + day.submitted, 0);
  if (!days.length || total === 0) {
    return <div className="v3-empty-panel">{`${rangeLabel} 내 작업이 없습니다.`}</div>;
  }
  const max = days.reduce((top, day) => Math.max(top, day.submitted), 1);
  const showEveryLabel = days.length <= 8;
  return (
    <div className="v3-dash-volume-wrap">
      <div className="v3-dash-volume-legend">
        <span className="is-completed">완료</span>
        <span className="is-active">진행 중</span>
        <span className="is-queued">대기</span>
        <span className="is-failed">실패</span>
      </div>
      <div className="v3-dash-volume-chart">
        {days.map((day, index) => {
          const showLabel = showEveryLabel || index === 0 || index === days.length - 1 || index % 5 === 0;
          const title = `${day.date} · 제출 ${day.submitted} (완료 ${day.completed} · 진행 중 ${day.active} · 대기 ${day.queued} · 실패 ${day.failed})`;
          return (
            <div key={day.date} className="v3-dash-volume-col" title={title}>
              <div className="v3-dash-volume-bar" style={{ height: `${Math.max(2, Math.round((day.submitted / max) * 100))}%` }}>
                {day.completed > 0 && <i className="is-completed" style={{ flexGrow: day.completed }} />}
                {day.active > 0 && <i className="is-active" style={{ flexGrow: day.active }} />}
                {day.queued > 0 && <i className="is-queued" style={{ flexGrow: day.queued }} />}
                {day.failed > 0 && <i className="is-failed" style={{ flexGrow: day.failed }} />}
                {day.other > 0 && <i className="is-other" style={{ flexGrow: day.other }} />}
              </div>
              <span className="v3-dash-volume-value">{day.submitted > 0 ? formatNumber(day.submitted) : ""}</span>
              <small className="v3-dash-volume-label">{showLabel ? formatDayLabel(day.date) : ""}</small>
            </div>
          );
        })}
      </div>
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

export function formatNumber(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("ko-KR").format(value);
}

function formatDayLabel(dateIso: string): string {
  const [, month, day] = dateIso.split("-");
  return month && day ? `${month}/${day}` : dateIso;
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

