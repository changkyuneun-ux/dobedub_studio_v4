# 로그인 랜딩 대시보드(시스템 상태 · 작업 현황) 설계

- 작성일: 2026-09-13 (v1.2 — 영역 전환 기본 도착지 = 대시보드 추가; v1.1 — 전역 표시 정책 반영: 대시보드는 로그인한 모든 사용자에게 권한 없이 표시)
- 대상 화면: 스튜디오 → **HOME → 대시보드** (`home.dashboard`, 로그인 후 기본 랜딩)
- 대상 코드: `backend/app/services/dashboard_service.py`(신규), `backend/app/api/v1/dashboard.py`(신규), `backend/app/services/permission_service.py`(리소스 카탈로그), `frontend/src/router.ts`, `frontend/src/main.tsx`, `frontend/src/StudioShell.tsx`, `frontend/src/components/AppShell.tsx`, `frontend/src/screens/dashboardScreen.tsx`(신규), `frontend/src/api/client.ts`, `frontend/src/styles.css`
- 목업: `docs/superpowers/mockups/2026-09-13-dashboard-landing/dobedub-dashboard-landing.html` (캔버스 1페이지 = 확정 A, 2페이지 = 대안 B 보류)
- 관련 문서: `docs/superpowers/specs/2026-09-11-sandbox-pod-gpu-fallback-design.md`(Sandbox Pod 상태 API·2단계 로딩)

## 1. 배경

로그인하면 `create.load`(2a 이미지 로드)로 바로 진입해, 운영자가 시스템이 정상인지·누가 무엇을 돌리고 있는지 보려면 작업 이력·System Status·Sandbox Pod·Runpod Worker 설정 화면을 각각 열어야 한다. 장애(2026-09-11 Sandbox Pod 재고 부족, 09-13 webtoon-cut 누락 회귀)도 화면을 돌아다니다 발견됐다. 로그인 직후 한 화면에서 **시스템 상태와 작업 현황(작업자·워크플로·날짜)** 을 보게 한다.

## 2. 목적과 범위

### 2.1 확정 방향 — A "데이터 우선"

사이드바(212px)는 그대로 두고 `HOME` 그룹에 **대시보드** 항목을 추가한다. 본문은 위→아래 3단:

1. **시스템 상태 타일 5개** — ComfyUI Serverless · Qwen Prompt LLM · Sandbox Pod · Runpod Worker · Workflows/DB
2. **작업 현황 KPI 6개**(기간 칩: 오늘 / 7일 / 30일) — 제출 · 완료 · 진행 중 · 실패 · 평균 실행 · 활성 작업자
3. **최근 작업 테이블**(시각 · 작업자 · 워크플로 · 워커 · 상태 · 실행) + 우측 **작업자별 / 워크플로별 집계 바** + **주의 필요 카드**

대안 B(요약 우선·활동 타임라인)는 채택하지 않는다. 목업 캔버스 2페이지에 보류.

### 2.2 범위 밖

- 실시간 푸시(WebSocket) — 60초 폴링으로 충분. 
- 차트 라이브러리 도입 — 집계 바는 CSS 바(`.v3-dash-bar`)로 그린다.
- 작업 이력 화면의 기능 이전 — 대시보드는 요약·진입점이며 상세는 `review.history`로 딥링크.
- 대시보드 위젯 사용자화(순서·표시 여부 저장).

## 3. 화면 요건

### 3.1 라우팅·메뉴

| 항목 | 값 |
|---|---|
| 라우트 | `home.dashboard` → `/studio/home` |
| 로그인 후 기본 라우트 | `create.load` → `home.dashboard`로 변경 (`router.ts` `studio:` 매핑, `main.tsx:111`, `StudioShell.tsx:1952` 랜딩 처리) |
| 레거시 URL(`/studio`, 알 수 없는 세그먼트) | `home.dashboard`로 |
| 관리자 콘솔 안의 대시보드 | `admin.dashboard` → `/studio/admin/home` (같은 `DashboardScreen`, `area="admin"`으로 ADMIN 사이드바 유지) |
| 스튜디오 ↔ 관리자 콘솔 전환 버튼 | "관리자 콘솔 →" = `admin.dashboard`, "← 스튜디오" = `home.dashboard` — **전환 기본 도착지는 항상 대시보드** (이전: admin.roles / create.load) |
| 사이드바 | `AppShell` 모든 area(local/generate/admin)에서 `HOME > 대시보드`를 최상단 그룹으로 표시. **권한 조건 없음**(로그인한 모든 사용자) |
| 헤더 | eyebrow `HOME · DASHBOARD`, 제목 `시스템 상태 · 작업 현황`, 우측 `마지막 확인 HH:MM:SS KST · 60초마다 자동 갱신` + **새로고침** |

### 3.2 시스템 상태 타일 (권한별 표시)

모든 타일은 대시보드 API(§4.1) 한 번으로 채우며 **권한과 무관하게 모두 표시**한다. 민감값(엔드포인트 id, URL)은 대시보드 응답에 넣지 않는다.

| 타일 | 데이터 출처(대시보드 API 블록) | 표시 | 상태 점 |
|---|---|---|---|
| COMFYUI SERVERLESS | `system.comfy` = `{configured, executionMode, dryRun}` (설정 검사만, 외부 호출 없음) | ONLINE / DRY-RUN / NOT CONFIGURED, 실행 모드 | on / warn / off |
| QWEN PROMPT LLM | `system.promptLlm` = `{configured, provider, model, timeoutSeconds}` | ONLINE / MOCK / NOT CONFIGURED, provider · model · timeout | on / muted / off |
| SANDBOX POD | `sandbox` = `{configured, activePodId, activePodName, desiredStatus, gpuTier, podCount, runningCount, conflict, duplicateStoppedPodIds, error}` — 서버가 `sandbox_pod_status(include_live=False)`를 **30초 캐시**로 호출 | 활성 파드 desiredStatus, tier 배지, 이름 · `N pods · M running` | RUNNING=on, EXITED=muted, conflict/error=off |
| RUNPOD WORKER | `worker` = `{active, queued, maxActiveTasksTotal, maxActiveTasksPerUser}` | `활성 / 최대` + 사용률 바, `대기열 n · 정책: 최대 N · 사용자당 M` | <80% on, ≥80% warn, 100% off |
| WORKFLOWS · DB | `system.workflows = {count}`, `db = {alembicCurrent, alembicHead, migrationRequired}` | `N 정의 · 정상`, `alembic <head> · 최신/마이그레이션 필요` | on / warn |

- 타일 클릭 시 관리 화면으로 이동(Sandbox → `admin.sandbox`, Worker → `admin.taskPolicy`, Workflows → `admin.workflows`, 나머지 → `admin.status`)은 **해당 화면 권한이 있을 때만** 링크(없으면 정적 타일).
- Sandbox 블록 조회 실패는 `sandbox.error`로 내려오고 타일만 `FAIL`로 표시, 나머지 블록은 정상 렌더.

### 3.3 작업 현황 KPI

- 기간 칩 `오늘 | 7일(기본) | 30일`. 선택값은 `localStorage`(`dobedub.dashboard.range`)에 기억.
- 6개 수치와 보조 문구:

| KPI | 정의 (`workflow_tasks`, `deleted_at IS NULL`, 기간 = `created_at` 기준 KST) | 보조 |
|---|---|---|
| 제출 | 기간 내 생성 건수 | 직전 동일 기간 대비 증감 % |
| 완료 | `status ∈ {COMPLETED, SUCCESS}` | 성공률 = 완료 / (완료+실패) |
| 진행 중 | `status ∈ ACTIVE_TASK_STATUSES ∪ {PENDING_SUBMIT, DISPATCHING}` (기간 무관, 현재값) | 큐 대기 = `PENDING_SUBMIT, QUEUED, IN_QUEUE` |
| 실패 | `status ∈ {FAILED, TIMED_OUT, CANCELLED}` | dispatch 오류 n(`last_dispatch_error` not null) · 타임아웃 n |
| 평균 실행 | 완료 건 `elapsed_seconds` 평균, `Xm Ys` | 지연 평균 = `started_at - created_at` 평균 |
| 활성 작업자 | 기간 내 제출한 `user_id` distinct | Batch 진행 중 n (`batch_jobs.status = INCOMPLETE`) |

### 3.4 최근 작업 테이블

- 기본 20건, `created_at desc`. 컬럼: 시각(KST `HH:MM`, 다른 날이면 `MM-DD HH:MM`) · 작업자(`user.name`, 없으면 id) · 워크플로(`workflowName` → 없으면 `workflow_id`) · 워커(`worker_name` 축약, mono) · 상태 배지 · 실행(`elapsed_seconds` `Xm Ys`, 실패면 사유 축약).
- 필터 칩: 작업자 / 워크플로 / 상태 — 응답에 포함된 값들로 드롭다운을 채우고 **클라이언트에서** 필터(20~50건이라 재조회 불필요). 기간 변경은 재조회.
- 행 클릭 → `review.history`로 이동하며 `taskId`를 쿼리로 전달(기존 작업 이력 화면이 `?taskId=` 선택을 지원하지 않으면 이동만).
- 상태 배지 클래스는 기존 `.v3-status-badge.is-ready/is-running/is-pending/is-failed/is-muted` 재사용: COMPLETED/SUCCESS→ready, RUNNING/IN_PROGRESS/DISPATCHING→running, QUEUED/IN_QUEUE/PENDING_SUBMIT→running(문구 QUEUED), FAILED/TIMED_OUT/CANCELLED→failed, 그 외→muted.

### 3.5 집계 바

- **작업자별 · 기간**: 상위 5명, `제출 / 실패`, 바 폭 = 제출 / 최대 제출.
- **워크플로별 · 기간**: 상위 5개, `제출 · 평균 실행`, 바 폭 동일 규칙.
- 상위 밖은 표시하지 않는다(더보기 없음). 데이터 0건이면 `기간 내 작업이 없습니다.`

### 3.6 주의 필요 카드

서버가 규칙을 평가해 목록으로 내려주고 화면은 그대로 나열한다(0건이면 카드 숨김, 1건 이상이면 warning 톤).

| 규칙 id | 조건 | 문구 예 |
|---|---|---|
| `sandbox_duplicate_pod` | Sandbox 파드 목록에 같은 `gpuTypeId`의 EXITED 파드가 2개 이상 | 중복 Sandbox Pod 1개 정지 상태(caiuvooekq9qqw) · 삭제 권장 |
| `sandbox_conflict` | `conflict = true` | 실행 중인 Sandbox Pod 2개 · 하나만 남기고 정지 |
| `failure_spike` | 최근 1시간 실패 ≥ 3 또는 실패율 ≥ 30% (완료+실패 ≥ 5일 때) | 최근 1시간 타임아웃 3건 · character_ref_i2v (wk-7be1) |
| `worker_saturated` | 활성 작업 = `max_active_tasks_total` | Runpod Worker 상한 도달 5/5 · 대기열 2 |
| `migration_pending` | alembic current ≠ head | DB 마이그레이션 필요 (`<current>` → `<head>`) |

Sandbox 규칙은 서버가 `sandbox` 블록으로 평가한다(권한 무관).

### 3.7 갱신·오류·빈 상태

- 60초 `setInterval` 자동 갱신(탭 비활성 시 `document.hidden`이면 건너뜀). 새로고침 버튼은 즉시 재조회.
- 조회 실패 시 **마지막 성공 값을 유지**하고 헤더에 `갱신 실패 HH:MM:SS · 재시도 중` 배지(Sandbox 화면과 같은 원칙).
- 첫 로드 스켈레톤: 타일·KPI는 회색 박스, 테이블은 5행.
- 권한 가드 없음 — 로그인만 되어 있으면 진입.

## 4. API 설계

### 4.1 `GET /api/dashboard/summary?range=today|7d|30d`

- 권한: **인증만**(`current_user_from_headers`), 별도 permission 없음. 리소스 카탈로그에는 등록하지 않는다(전역 API).
- 단일 호출로 `system`·`sandbox`·KPI·최근 작업·집계·`worker`·`db`·`alerts`(Sandbox 규칙 포함)를 반환. 외부 호출은 Sandbox 파드 목록(RunPod REST 1회)뿐이며 서버 30초 캐시(`_SANDBOX_CACHE_TTL_SECONDS`)로 폴링 부하를 제한하고, 실패는 `sandbox.error`로 격리한다.

```json
{
  "range": "7d",
  "since": "2026-09-07T00:00:00+09:00", "until": "2026-09-13T09:41:12+09:00",
  "kpi": {
    "submitted": 184, "submittedDeltaPercent": 12.0,
    "completed": 161, "successRate": 0.875,
    "active": 5, "queued": 2,
    "failed": 18, "failedDispatch": 7, "failedTimeout": 11,
    "avgElapsedSeconds": 252, "avgDelaySeconds": 38,
    "activeUsers": 6, "batchJobsInProgress": 3
  },
  "recent": [
    {"taskId": "…", "createdAt": "…", "createdAtKst": "…", "user": {"id": "…", "name": "김민지"},
     "workflowId": "wan22_i2v_720p", "workflowName": "…", "workerName": "wk-3f2a",
     "status": "RUNNING", "elapsedSeconds": 80, "lastDispatchError": null}
  ],
  "byUser": [{"userId": "…", "name": "김민지", "submitted": 58, "failed": 4}],
  "byWorkflow": [{"workflowId": "wan22_i2v_720p", "workflowName": "…", "submitted": 92, "avgElapsedSeconds": 241}],
  "system": {"comfy": {"configured": true, "executionMode": "runpod", "dryRun": false},
             "promptLlm": {"configured": true, "provider": "runpod", "model": "Qwen2.5-7B", "timeoutSeconds": 60},
             "workflows": {"count": 12}},
  "sandbox": {"configured": true, "activePodId": "…", "activePodName": "dobedub_comfyUI_Sandbox_RTX 5090", "desiredStatus": "RUNNING",
              "gpuTier": "primary", "podCount": 2, "runningCount": 1, "conflict": false, "duplicateStoppedPodIds": [], "error": null},
  "worker": {"active": 3, "queued": 2, "maxActiveTasksTotal": 5, "maxActiveTasksPerUser": 3},
  "db": {"alembicCurrent": "20260912_0038", "alembicHead": "20260912_0038", "migrationRequired": false},
  "alerts": [{"id": "failure_spike", "level": "warning", "message": "최근 1시간 타임아웃 3건 · character_ref_i2v (wk-7be1)", "route": "review.history"}],
  "checkedAt": "…", "checkedAtUtc": "…", "checkedAtKst": "…"
}
```

- 시각 필드는 기존 `timestamp_fields()` 규칙(`*`, `*Utc`, `*Kst`)을 따른다.
- `range` 외 값은 400. `recent` 건수는 `limit`(기본 20, 최대 50) 쿼리로 조정.
- 집계는 SQL `GROUP BY`(작업자·워크플로)와 `count(case …)`로 한 트랜잭션·3~4 쿼리 내에서 끝낸다. 30일 기준 수만 건에서도 수백 ms 이내가 목표(`created_at`·`status`·`user_id` 인덱스 존재, 필요 시 `(deleted_at, created_at)` 복합 인덱스는 후속).
- alembic head/current는 `scripts/upgrade_database.py --check`와 같은 방식(`alembic.script.ScriptDirectory` + `MigrationContext`)을 서비스 함수로 추출해 재사용.

### 4.2 프론트 호출

프론트는 대시보드 API **한 번**만 호출한다(기존 system/sandbox API 미사용). 블록 단위 오류는 응답 안의 `sandbox.error`·`db.error`로 표현된다.

## 5. 데이터·권한·성능 원칙

- 대시보드 API는 DB 집계 + 설정 검사 + Sandbox 파드 목록(30초 캐시, 실패 격리)만 수행한다. LLM·RunPod 실측 호출(연결 테스트, LIVE 지표)은 하지 않는다.
- KPI의 기간은 KST 일 경계(`Asia/Seoul`), DB 저장은 UTC naive → 비교 시 UTC로 변환.
- `deleted_at IS NULL`만 집계(작업 이력 화면과 동일 기준).
- 사용자 이름은 `users.name`을 조인, 삭제/비활성 사용자는 id 표시.
- 권한: **전역** — 화면·API 모두 로그인만 요구. 타일에서 관리 화면으로의 링크만 해당 화면 권한으로 제어.

## 6. 테스트

- `backend/tests/test_dashboard_service.py`: 기간 경계(오늘/7d/30d, KST 자정), 상태 분류(완료·실패·진행·큐), 성공률·평균·지연 계산, byUser/byWorkflow 정렬·상위 5, alerts 규칙(failure_spike 임계, worker_saturated, migration_pending), deleted_at 제외.
- `backend/tests/test_dashboard_api.py`: 인증(401) / 권한 없는 사용자도 200, `range` 검증(400), `limit` 상한, 응답 키 계약.
- `backend/tests/test_frontend_dashboard_contract.py`: `router.ts`에 `home.dashboard`와 기본 라우트, `AppShell.tsx` HOME 그룹, `client.ts`에 `dashboardSummary`, `dashboardScreen.tsx`에 4개 블록 클래스(`v3-dash-tiles`, `v3-dash-kpi`, `v3-dash-recent`, `v3-dash-alerts`).
- 수동: SUPER_ADMIN과 권한 없는 일반 사용자로 로그인해 모든 타일·블록이 표시되고 관리 링크만 차이 나는지 확인, 60초 자동 갱신, 조회 실패 시 마지막 값 유지.

## 7. 롤아웃

1. 백엔드 API + 테스트 배포(화면 없음, 무해).
2. 프론트 화면 + 사이드바 항목 추가, **기본 라우트는 아직 `create.load`** (사용자가 메뉴로 진입).
3. 기본 라우트를 `home.dashboard`로 전환.

마이그레이션 없음. 신규 환경변수 없음.

## 8. 미결·가정

- 목업의 "ComfyUI 마지막 응답 2.4s"는 외부 호출을 피하기 위해 제외하고 실행 모드(runpod/dry-run)만 표시한다.
- Qwen 타일의 `MOCK`은 `promptLlm.provider == "mock"`(`prompt_llm_status()` 확인됨).
- `workflowName`은 `_task_to_history_item()`과 같은 규칙 `Path(workflow_id).stem`.
- 작업 이력 화면의 `?taskId=` 딥링크 지원 여부 확인 필요(없으면 이동만).
