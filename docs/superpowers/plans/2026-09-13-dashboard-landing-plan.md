# 로그인 랜딩 대시보드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인 직후 `HOME > 대시보드`(`home.dashboard`)에서 시스템 상태 타일(ComfyUI·Qwen·Sandbox Pod·Runpod Worker·Workflows/DB), 작업 KPI(오늘/7일/30일), 최근 작업 테이블, 작업자별·워크플로별 집계, 주의 필요 카드를 한 화면에 보여준다. 사이드바는 유지하고 최상단에 HOME 그룹을 추가한다. 목업 A(데이터 우선) 확정.

**Architecture:** 단일 엔드포인트 `GET /api/dashboard/summary?range=`(인증만)가 `system`(설정 검사)·`sandbox`(파드 목록 30초 캐시)·KPI·최근 작업·집계·worker·db·alerts를 한 번에 돌려주고, 프론트는 이 한 호출로 모든 블록을 그린다. 집계 로직은 순수 함수(`_classify_status`, `_range_bounds`, `_evaluate_alerts`)로 분리해 단위 테스트한다. 화면은 `AppShell` 골격 + 신규 `DashboardScreen`, 상태는 마지막 성공 값 유지·60초 폴링.

**Tech Stack:** FastAPI + SQLAlchemy 집계 쿼리, alembic 런타임 조회, React/TypeScript(Vite), pytest(`api_client` fixture, SQLite), Python 소스 컨트랙트 테스트(프론트), vitest 없음(webtoon-cut 전용).

**Spec:** `docs/superpowers/specs/2026-09-13-dashboard-landing-design.md`
**Mockup:** `docs/superpowers/mockups/2026-09-13-dashboard-landing/dobedub-dashboard-landing.html` (1페이지 A 확정)
**Branch:** `feat/enhance` (base: `main` 835a1be 이후, 로컬 미커밋 2묶음 — 메뉴 정리·Sandbox 성능/2단계 로딩 — 먼저 커밋)

## Global Constraints

- 대시보드 API의 외부 호출은 Sandbox 파드 목록 1회(30초 서버 캐시, 실패 격리)뿐. 응답 시간 목표 < 500 ms(캐시 히트 시).
- 집계 기준: `workflow_tasks.deleted_at IS NULL`, 기간은 `created_at`(UTC naive) ↔ KST 일 경계 변환. 상태 분류는 스펙 §3.3 표를 단일 함수 `_classify_status(status) -> "completed"|"failed"|"active"|"queued"|"other"`로 고정하고 `task_policy_service.ACTIVE_TASK_STATUSES`를 재사용.
- `workflowName`은 `_task_to_history_item()`과 같은 규칙(`Path(workflow_id).stem`)으로 만든다(별도 조인 없음, 스펙 §8 가정 해소).
- 권한: **전역** — 화면·API 모두 로그인만 요구(`current_user_from_headers`). 타일의 관리 화면 링크만 해당 권한으로 제어.
- 기존 응답 시각 필드 규칙 `timestamp_fields("createdAt", …)` 사용.
- 실패 응답에서 마지막 성공 상태를 지우지 않는다(Sandbox 화면과 동일 원칙).
- 기본 라우트 전환(`create.load` → `home.dashboard`)은 **마지막 Task**에서만 수행(스펙 §7 롤아웃 3단계).
- `metadata/*.json` 변경은 커밋에 포함하지 않는다.
- 검증 명령: `python3 -m pytest backend/tests/test_dashboard_service.py backend/tests/test_dashboard_api.py backend/tests/test_frontend_dashboard_contract.py -q` + `cd frontend && npx tsc --noEmit -p tsconfig.json && npx vite build --minify false`.

## 롤아웃 매핑 (스펙 §7)

| 단계 | Task | 사용자 영향 |
|---|---|---|
| 1. API만 | 1, 2, 3 | 없음 |
| 2. 화면 + 메뉴(기본 라우트 유지) | 4, 5, 6, 7 | 메뉴로 진입 가능 |
| 3. 기본 라우트 전환 | 8 | 로그인 후 대시보드 |

---

### Task 1: 대시보드 집계 서비스 — 순수 함수와 KPI

**Files:**
- Create: `backend/app/services/dashboard_service.py`
- Create: `backend/tests/test_dashboard_service.py`
- Reference: `backend/app/services/task_policy_service.py:16` (`ACTIVE_TASK_STATUSES`), `backend/app/services/task_tracking_service.py:1600-1615` (`_task_to_history_item`), `backend/app/core/timezone_utils.py` (`timestamp_fields`, `utc_now`, KST 변환)

**Interfaces:**
- `RANGE_KEYS = ("today", "7d", "30d")`
- `_range_bounds(range_key: str, now_utc: datetime) -> tuple[datetime, datetime, datetime]` — `(since_utc, until_utc, previous_since_utc)`; KST 자정 경계, 7d/30d는 `until - N일`의 KST 자정.
- `_classify_status(status: str | None) -> str` — `completed` (COMPLETED, SUCCESS) / `failed` (FAILED, TIMED_OUT, CANCELLED) / `queued` (PENDING_SUBMIT, QUEUED, IN_QUEUE) / `active` (IN_PROGRESS, RUNNING, DISPATCHING) / `other`.
- `_kpi(session, since, until, previous_since) -> dict` — 스펙 §4.1 `kpi` 블록. 진행 중·큐는 기간 무관 현재값.
- `dashboard_summary(session, *, range_key: str, limit: int = 20, now: datetime | None = None) -> dict` — 스펙 §4.1 전체(Task 2에서 recent/byUser/byWorkflow/worker/db/alerts 채움; 이 Task는 `kpi`·`range`·`since/until`·`checkedAt*`).

**Steps:**
- [ ] `_range_bounds`·`_classify_status` 작성. 테스트: today는 KST 자정~now, 7d는 6일 전 자정, 30d는 29일 전 자정, previous_since = since - (until-since).
- [ ] `_kpi` 작성: `func.count`, `func.sum(case(...))`, `func.avg(elapsed_seconds)`(completed만), 지연 평균 = `avg(started_at - created_at)`(SQLite는 `julianday` 차, Postgres는 `extract(epoch)` — dialect 분기 helper `_seconds_between(col_a, col_b)`), `count(distinct user_id)`, `batch_jobs` INCOMPLETE 수, `submittedDeltaPercent`(이전 기간 0이면 null).
- [ ] 테스트 픽스처: SQLite 세션에 `WorkflowTask` 12건(상태 혼합, 일부 `deleted_at`, 일부 이전 기간, 일부 `last_dispatch_error`) + `BatchJob` 1건. `dashboard_summary(range_key="7d", now=고정)` 결과 KPI 수치 단언, deleted_at 제외, `range="1y"`는 `ValueError`.
- [ ] `python3 -m pytest backend/tests/test_dashboard_service.py -q` 통과.

### Task 2: 최근 작업·집계·worker·db·alerts

**Files:**
- Modify: `backend/app/services/dashboard_service.py`
- Modify: `backend/tests/test_dashboard_service.py`
- Create: `backend/app/services/migration_status_service.py` (alembic head/current 조회 — `scripts/upgrade_database.py:44-49` 로직 추출)
- Reference: `backend/app/services/task_policy_service.py:23-40` (`task_execution_policy`, 활성 수 조회 `:70-76`)

**Interfaces:**
- `_recent(session, since, until, limit) -> list[dict]` — 스펙 §4.1 `recent` 항목, `users` 조인, `workflowName = Path(workflow_id).stem`.
- `_by_user(session, since, until, top=5) -> list[dict]`, `_by_workflow(session, since, until, top=5) -> list[dict]`.
- `_worker(session) -> dict` — `active`(ACTIVE_TASK_STATUSES 현재 수), `queued`(PENDING_SUBMIT/QUEUED/IN_QUEUE), `maxActiveTasksTotal`, `maxActiveTasksPerUser`.
- `migration_status(engine_or_session) -> dict` — `{"alembicCurrent": str|None, "alembicHead": str, "migrationRequired": bool}`; 조회 실패 시 `{"error": "..."}` 포함하고 예외를 삼킨다(대시보드가 죽지 않게).
- `_evaluate_alerts(*, recent_hour: dict, worker: dict, db: dict) -> list[dict]` — 순수 함수. 규칙 `failure_spike`(1시간 실패 ≥3 또는 실패율 ≥30% & 표본 ≥5), `worker_saturated`, `migration_pending`. 각 `{id, level, message, route}`.

**Steps:**
- [ ] `_recent`: `limit` 1~50 clamp, `created_at desc`. 테스트: 정렬·limit·user name fallback(id)·workflowName stem.
- [ ] `_by_user`/`_by_workflow`: `GROUP BY` + `ORDER BY submitted desc` + `LIMIT top`. 테스트: 상위 5, failed/avgElapsed 계산.
- [ ] `_worker`: 정책 행이 없으면 기본값(`task_policy_service` 상수). 테스트.
- [ ] `migration_status_service.py`: `ScriptDirectory.from_config` + `MigrationContext` (upgrade_database.py 재사용). 테스트는 monkeypatch로 head/current 고정.
- [ ] `_evaluate_alerts` 테스트: 임계 경계(2건→없음, 3건→있음; 실패율 29%/30%; 표본 4→없음), saturated, migration.
- [ ] `dashboard_summary` 조립 완료. 전체 응답 키 계약 테스트(스펙 §4.1의 최상위 키 집합 동일).

### Task 3: API 라우트 (전역 · 인증만)

**Files:**
- Create: `backend/app/api/v1/dashboard.py`
- Modify: `backend/app/api/v1/__init__.py` (라우터 등록 — 기존 `sandbox_pod` 등록 방식 따라)
- Create: `backend/tests/test_dashboard_api.py`

**Interfaces:**
- `GET /api/dashboard/summary?range=7d&limit=20` → 200 JSON(스펙 §4.1); `range` 오류 400 `{"detail": "range must be one of today, 7d, 30d"}`; 예외 → 500 with `LOGGER.exception` (sandbox_pod.py 패턴).

**Steps:**
- [ ] 라우트 작성, `Depends(current_user_from_headers)`(권한 없음).
- [ ] 테스트: 401(무토큰), 권한 없는 OPERATOR도 200, 200 키 계약, 400 range, `limit=500`→50으로 clamp.

### Task 4: 프론트 API 클라이언트·타입

**Files:**
- Modify: `frontend/src/api/client.ts`
- Reference: `client.ts:1675` (`sandboxPodStatus`), `SandboxPodStatus` 타입, `SystemStatusResponse`

**Interfaces:**
- `export type DashboardRange = "today" | "7d" | "30d"`
- `export type DashboardSummary = { range; since; until; kpi: {...}; recent: DashboardRecentTask[]; byUser: ...; byWorkflow: ...; worker: ...; db: ...; alerts: DashboardAlert[]; checkedAt*; }` (스펙 §4.1 그대로)
- `dashboardSummary: (range: DashboardRange, limit?: number) => Promise<DashboardSummary>`
- `runpodConnection: () => Promise<RunpodConnectionResponse>` (없으면 추가 — `GET /api/system/runpod/connection` 응답 형식은 `system_status_service.runpod_connection()` 확인 후 타입 작성)

**Steps:**
- [ ] 타입·엔드포인트 추가. `npx tsc --noEmit` 통과.

### Task 5: 라우팅·AppShell HOME 그룹 (기본 라우트는 유지)

**Files:**
- Modify: `frontend/src/router.ts` (`StudioRoute`에 `"home.dashboard"`, 경로 `/studio/home`, 레거시 매핑은 아직 변경 없음)
- Modify: `frontend/src/components/AppShell.tsx` (`HOME_NAV_ITEMS = [{ key: "dashboard", label: "대시보드" }]` — permission 없음 = 항상 노출; 모든 area에서 최상단 그룹으로 렌더)
- Modify: `frontend/src/helpers/navigation.ts` (`shellNavigate`/`shellNavigateAdmin`에 `dashboard` → `home.dashboard`)
- Modify: `frontend/src/StudioShell.tsx` (라우트 타이틀 맵 `"home.dashboard": "대시보드"`, 화면 분기)
- Create: `backend/tests/test_frontend_dashboard_contract.py`

**Steps:**
- [ ] HOME 그룹은 `area === "admin"`에서도 표시(관리자 콘솔에서 바로 대시보드로).
- [ ] 컨트랙트 테스트: `router.ts`에 `"home.dashboard"`와 `/studio/home`, `AppShell.tsx`에 `HOME_NAV_ITEMS`·`label: "대시보드"`, `navigation.ts` 매핑, `StudioShell.tsx` 타이틀.
- [ ] `tsc` 통과.

### Task 6: DashboardScreen — 데이터 훅·시스템 타일·KPI

**Files:**
- Create: `frontend/src/screens/dashboardScreen.tsx`
- Modify: `frontend/src/styles.css` (`.v3-dash-*` — 목업 A의 인라인 값 그대로: 타일 `padding 12px 14px; gap 8px`, KPI 셀 `padding 14px 16px`, 수치 24px, 바 8px `#e9f5ef/#12a06a`)
- Modify: `frontend/src/StudioShell.tsx` (`home.dashboard` → `<DashboardScreen user health onGoTo />`)

**Interfaces:**
- `useDashboardData(user): { summary, system, runpod, sandbox, errors: Partial<Record<"summary"|"system"|"runpod"|"sandbox", string>>, loading, lastCheckedAt, range, setRange, refresh }` — 4개 호출을 `Promise.allSettled`; 권한 없는 호출은 시도하지 않음; 성공한 블록만 갱신; 60초 폴링(`document.hidden`이면 skip); `range`는 `localStorage("dobedub.dashboard.range")`.
- `SystemTiles`, `KpiStrip` 컴포넌트(같은 파일 내부).

**Steps:**
- [ ] 헤더: eyebrow/제목/마지막 확인·새로고침(스펙 §3.1).
- [ ] 시스템 타일 5개(스펙 §3.2 표), 권한별 숨김, `auto-fit` 그리드, 타일 클릭 → 라우트(권한 있을 때만 `button`).
- [ ] KPI 스트립 + 기간 칩(오늘/7일/30일), 보조 문구 포맷 헬퍼(`formatDuration(sec) → "4m 12s"`, 퍼센트).
- [ ] 스켈레톤(첫 로드), 실패 시 마지막 값 유지 + 헤더 배지 `갱신 실패 HH:MM:SS`.
- [ ] `tsc` + `vite build` 통과.

### Task 7: 최근 작업 테이블·집계 바·주의 필요 카드

**Files:**
- Modify: `frontend/src/screens/dashboardScreen.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `backend/tests/test_frontend_dashboard_contract.py`

**Interfaces:**
- `RecentTasksTable({ rows, onOpenHistory })` — 클라이언트 필터 3종(작업자/워크플로/상태, `<select>`), 상태 배지 매핑(스펙 §3.4), 행 클릭 → `onGoTo("review.history")`.
- `BreakdownBars({ title, meta, rows: {label, value, sub, ratio}[] })` — 작업자별/워크플로별 공용.
- `AlertsCard({ alerts })` — 서버 alerts + 프론트 계산 Sandbox alerts(`sandbox_duplicate_pod`, `sandbox_conflict` — `sandbox.pods`에서 같은 `gpuTypeId`의 EXITED ≥2, `sandbox.conflict`). 0건이면 렌더 안 함.

**Steps:**
- [ ] 테이블·필터·빈 상태(`기간 내 작업이 없습니다.`) 구현.
- [ ] 집계 바 2개, 상위 5.
- [ ] 주의 필요 카드(warning 톤 `#fdf3e7/#f0d7b0`), 항목 클릭 → `route`.
- [ ] 컨트랙트 테스트에 `v3-dash-tiles`, `v3-dash-kpi`, `v3-dash-recent`, `v3-dash-alerts` 클래스 존재, `sandbox_duplicate_pod` 문자열 존재 단언.
- [ ] `tsc` + `vite build` 통과. 로컬 서버(`python3 scripts/run_local.py`)에서 SUPER_ADMIN / history:read만 / system:read만 계정으로 블록 표시 확인(수동).

### Task 8: 기본 라우트 전환 (롤아웃 3단계)

**Files:**
- Modify: `frontend/src/router.ts` (`studio: "create.load"` → `"home.dashboard"`, `:186` fallback)
- Modify: `frontend/src/main.tsx:111` (`navigate("create.load")` → `home.dashboard`)
- Modify: `frontend/src/StudioShell.tsx:1952` (로그인 랜딩 처리)
- Modify: `backend/tests/test_frontend_dashboard_contract.py`

**Steps:**
- [ ] 세 지점 변경(권한 가드 없음).
- [ ] 컨트랙트 테스트 갱신(`studio: "home.dashboard"`).
- [ ] 기존 프론트 컨트랙트 테스트 전체 실행(`python3 -m pytest backend/tests/test_frontend_*.py -q`)으로 `create.load` 가정이 깨진 곳 확인.
- [ ] 로컬에서 로그인 → 대시보드 진입, 사이드바 다른 메뉴 이동 후 복귀 확인.

### Task 9: 문서·배포

**Files:**
- Modify: `docs/superpowers/specs/2026-09-13-dashboard-landing-design.md` §8 (구현 중 확정된 가정 반영)
- Modify: `docs/aws-ecs-deployment.md` (변경 없음 확인 — env·마이그레이션 없음)

**Steps:**
- [ ] 커밋 분리: `feat(dashboard): summary API`(Task 1–3) / `feat(dashboard): landing screen`(Task 4–7) / `feat(dashboard): make dashboard the default route`(Task 8).
- [ ] 배포: `./scripts/ecs_release.sh build` → 태스크 정의 복제 → `--check`(마이그레이션 없음 기대) → update-service → 롤아웃·RollbackAlarm 확인.
- [ ] 프로덕션에서 권한별 계정으로 §6 수동 검증.

## 리스크·메모

- 30일 집계가 느리면 `(deleted_at, created_at)` 복합 인덱스 마이그레이션 추가(별도 커밋).
- `GET /api/system/runpod/connection`이 실제로 RunPod를 호출하므로 대시보드 폴링 60초마다 외부 호출 1회 발생 — 부담되면 타일에서 제외하고 `system/status`만 사용.
- 대안 B의 활동 타임라인은 audit log + tasks 결합이 필요해 별도 API가 되므로 이번 범위에서 제외(캔버스 2페이지 보류).
