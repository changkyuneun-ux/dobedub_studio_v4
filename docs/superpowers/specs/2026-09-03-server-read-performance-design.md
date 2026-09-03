# 서버 조회 성능 개선 설계 (Server Read Performance)

작성일: 2026-09-03
기준 커밋: `main` @ a26e606
대상: 조회 경로(Task History / 프롬프트 이력 / Assets / 인증), DB 스키마, 서버 실행 구성, 프론트 폴링

## 1. 결론 — 근본 원인은 하나다

느린 조회도, ECS의 메모리 부족(OOM)도 원인이 같다.

> **`workflow_tasks.runpod_status_json`에 결과 영상/이미지의 base64 원본이
> 통째로 저장되어 있고, 거의 모든 조회 경로가 이 컬럼을 함께 읽는다.**

인덱스 문제가 아니다. `backend/app/db/models.py`에 복합 인덱스가 이미 충분히
잡혀 있고, 실행 계획상 병목이 아니다.

**"프롬프트 이력 화면엔 영상이 없는데 왜 느린가"에 대한 답**: 화면이 영상을
보여주지 않을 뿐, ORM이 **영상 base64를 전부 메모리로 끌어온 뒤 버리고 있다.**
프롬프트 이력 응답이 그 task에서 실제로 쓰는 값은 `id`와 `status` 두 개뿐이다.

| 구분 | 측정값 |
| --- | --- |
| `runpod_status_json` 테이블 합계 | **18.30MB = DB 파일 21.3MB의 86%** |
| 행 최대 크기 | 1,598,732 B (1.60MB) — 전부 `output.images[0].data` base64 |
| Task History 1페이지(20행)가 읽는 양 | **6.57MB** (응답은 214KB) |
| `prompt_options()` 1회 호출 | **peak 43.1MB / RSS +58MB** (응답은 텍스트 136건) |

## 2. 근거

### 2.1 컬럼 내용

```
.output.images[0].data     : str 1,598,498 B   ← 결과물 base64 원본
.output.images[0].filename : str        20 B
.status / .id / .workerId  : 수십 B
```

```
runpod_status_json  total = 18,299,869 B  (avg 310KB / max 1,598,732 B)
payload_json        total =    290,751 B  (avg 4.9KB)
```

### 2.2 이 데이터는 완전한 중복본이다

- `backend/app/services/output_service.py:160-198` `save_runpod_outputs()`가
  같은 base64를 디코딩해 **이미 파일로 저장**하고 `assets` 레코드를 만든다.
- API 응답에는 실리지 않는다. `_task_to_history_item()`
  (`task_tracking_service.py:991`)은 `payload_json`으로 응답을 만들고,
  `_runpod_response_summary()`(`:1044`)가 `runpod_status_json`에서
  `filename` / `executionTime` / `delayTime` / `jobId` 4개만 뽑는다.

→ **6.57MB를 읽어 214KB를 만든다. 제거해도 API 계약은 바뀌지 않는다.**

### 2.3 Task History 경로

```
ORM 전체 컬럼 조회 (20행)      : 43.0ms
runpod_status_json 제외        :  2.7ms      → 16배
```

`task_tracking_service.py:85` `select(WorkflowTask)`가 전체 컬럼을 읽는다.
이 화면은 `frontend/src/StudioShell.tsx:1503`에서 **3초마다** 폴링된다.

## 3. 프롬프트 이력이 느리고 OOM이 나는 이유

### 3.1 원인 경로 4곳 (모두 같은 컬럼)

| # | 경로 | 코드 | 실제로 쓰는 값 |
| --- | --- | --- | --- |
| 1 | `GET /history/prompts` | `prompt_batch_service.py:412-416` `_latest_runpod_tasks_by_draft()` → `select(WorkflowTask)` 전체 컬럼 | `task.id`, `task.status` **2개뿐** (`:463-464`) |
| 2 | `GET /prompts/options` | `studio_api_service.py:155` `prompt_options()` → `load_history()`(`:58`) → `task_history_items()` **인자 없이 호출 = LIMIT 없음** | 프롬프트 텍스트 상위 100건 |
| 3 | RunPod 요청 화면(2초 폴링) | `runpod_request_batch_service.py:400` `_item_payload()` → `db.get(WorkflowTask, ...)` **item마다 1회(N+1)** | 상태 필드 몇 개 |
| 4 | 요청 묶음 복구 | `runpod_request_batch_service.py:134` 루프 안 `db.get(WorkflowTask, ...)` (N+1) | `payload_json`, `status` |

### 3.2 측정값

```
[경로 1] _latest_runpod_tasks_by_draft(draft 20건)
  현재 코드 (전체 컬럼)   :  6.7ms   peak  2.78MB
  필요 컬럼만 (id,status) :  1.9ms   peak  0.06MB
  → 시간 4배, 메모리 45배
  ※ 로컬은 연결 task가 5건뿐이다. 운영은 task 수에 비례해 선형 증가한다.

[경로 2] prompt_options()   ← OOM 주범
  소요 172ms / peak 할당 43.1MB / 프로세스 RSS +58MB
  응답은 텍스트 옵션 136건인데,
    workflow_tasks 61행 전체(runpod_status_json 18.30MB)
    + assets 253행 전체를 매 호출마다 로드
```

### 3.3 OOM 증폭 4단계

1. **무페이지네이션 전체 로드** — 경로 2에는 `LIMIT`이 없다. task가 쌓일수록
   1요청 메모리가 **무한히 증가**한다. 로컬 61건에 43MB이므로 운영 600건이면
   단일 요청이 약 400MB를 잡는다. `task_history_items()`의 인자 기본값이
   `None`이라 **호출부가 실수하기 쉬운 시그니처**인 것이 구조적 원인이다.
2. **pymysql 버퍼링** — 운영 드라이버 `mysql+pymysql`
   (`.env.example` `DATABASE_URL`)은 순수 파이썬이고 기본 커서가 결과셋
   전체를 버퍼링한다. `raw bytes → str 디코딩 → json 파싱 dict`로 **같은
   데이터가 힙에 약 3벌** 동시 존재한다.
3. **스레드풀 40 동시 실행** — 라우트가 전부 sync `def`라 Starlette가 anyio
   기본 한도 40스레드로 병렬 실행한다. 단일 프로세스 안에서 위 할당이 **최대
   40겹**으로 쌓인다. 프롬프트 화면 2초 폴링
   (`promptManagementScreen.tsx:100`), RunPod 화면 2초 폴링
   (`runpodRequestScreen.tsx:86`)이 이를 상시 유발한다.
4. **단일 프로세스** — uvicorn 워커 1개(`scripts/run_server.py`)라 ECS task
   메모리 한도를 이 프로세스 하나가 전부 소진한다.

> **워커 증설·인스턴스 스케일업으로 먼저 대응하면 안 된다.** 워커를 늘리면
> 프로세스마다 같은 할당이 반복되어 OOM이 오히려 빨라진다.

## 4. 그 외 확인된 항목

| 순위 | 항목 | 위치 |
| --- | --- | --- |
| P1 | `_assets_by_id()`가 `assets` 전체 테이블을 매 조회마다 로드 (호출 5곳: 92, 342, 492, 538, 606) | `task_tracking_service.py:1085` |
| P1 | 인증 의존성이 요청마다 권한 3쿼리 | `core/security.py:_current_user_from_claims` → `permission_service.py:204,218,232` |
| P1 | 응답 gzip 미적용 — History 응답 214KB 비압축 | `backend/app/main.py:create_app()` |
| P2 | 요청 1건이 DB 세션 3개를 개별 오픈 | `task_history_items()`/`task_history_total()`이 각자 `SessionLocal()` |
| P2 | 커넥션 풀 크기 미지정 | `db/session.py:engine_kwargs()` |
| P2 | EFS 위 workflow 파일 21개를 metadata 조회마다 sha256 재해싱 | `metadata_loader.py:81-96, 370-384` |

## 5. 개선 계획

### P0-1. base64 본문 제거 (효과 최대 — 이것 하나로 3절 경로 1~4가 전부 해결)

**원칙**: `runpod_status_json`은 provider 응답 **요약**만 저장한다. 결과물
바이트는 `assets` + 파일 저장소가 유일한 원본이다.

1. `_prune_provider_payload(payload)` 추가 — `output.images[*].data` 등
   길이 임계값(4KB) 초과 문자열을 제거하고 `dataBytes`(길이)와
   `dataStripped: true`만 남긴다. 응답 스키마가 바뀌어도 방어적으로 동작한다.
2. 저장 지점 두 곳에 적용: `task_tracking_service.py:735`,
   `repositories/db_adapter.py:98`.
3. **순서 주의**: `save_runpod_outputs()`가 파일을 저장한 *뒤에* pruning이
   적용되어야 한다. `job_service.py:176`의 `job["runpodStatus"]`는 원본을
   유지하고, **DB 영속화 시점에만** pruning한다.
4. Alembic 데이터 마이그레이션으로 기존 행 정리 → 18.3MB → 약 20KB 예상.

**검증**: 마이그레이션 전후 `/api/v1/history?page=1&pageSize=20` 응답 JSON이
**바이트 단위로 동일**함을 확인한다(계약 불변 증명).

### P0-2. 대용량 컬럼 지연 로딩 (재발 방지)

`models.py`의 `payload_json` / `runpod_status_json` / `runpod_submit_json`에
`deferred=True` 적용. 목록 경로는 `load_only`로 필요한 컬럼만 명시하고,
상세 복원 경로(`restore_job_from_task`)만 전체 로드한다.

### P0-3. 무제한 조회 시그니처 제거

- `task_history_items(page=None, page_size=None)`의 "인자 없으면 전체" 동작을
  없애고 **상한(기본 200건)을 강제**한다.
- `prompt_options()`는 전체 이력을 읽지 않는다. 응답이 상위 100건으로
  잘리므로 최근 N건만 읽으면 충분하다. 더 나은 방식은 `task_prompts`를 직접
  `DISTINCT` 조회하는 것이다(`ix_task_prompts_workflow_segment` 활용).

### P0-4. 필요 컬럼 조회 / N+1 제거

- 경로 1: `select(WorkflowTask.prompt_draft_id, .id, .status)`로 교체.
- 경로 3·4: item마다 `db.get()` 하는 대신 `IN` 배치 조회 1회로 통합.

### P0-5. 폴링 정리

- `StudioShell.tsx:1503` 3초 → 5초 (서버 모니터 `TASK_MONITOR_INTERVAL_SECONDS=5`와 정렬).
- `promptManagementScreen.tsx:100`, `runpodRequestScreen.tsx:86` 2초 → 3초.
- 폴링 전용 경량 엔드포인트 `GET /history/status?ids=` 검토
  (`taskId/status/progress/completedAt`만, 응답 수 KB).

### P1. gzip / assets 전체 로드 / 권한 캐시

- `main.py`에 `GZipMiddleware(minimum_size=1024)` → 214KB → 20~30KB.
- `_assets_by_id()` 호출 5곳을 기존 `_assets_by_ids(session, ids)`(`:1089`)로 교체.
- `role_permission_code_map()`은 사용자 무관 전역 데이터 → TTL 캐시(60초).
  `user_extra_permission_codes()`는 사용자 단위 단기 캐시. 권한 변경 API에서
  무효화 훅 호출. 인증 API 1건당 쿼리 3 → 1.

### P2. 인프라·구성 (P0/P1 완료 후)

- `engine_kwargs()`에 `pool_size=10, max_overflow=5` 명시. 워커 수 × pool_size가
  RDS `max_connections`를 넘지 않도록 산정.
- `SessionLocal()` 개별 오픈을 `Depends(get_db)` 세션 재사용으로 통일.
- metadata fingerprint에 `(경로, st_mtime_ns, st_size)` 기반 프로세스 캐시.
  관리자 등록/수정 경로는 이미 `force=True`라 정합성 영향 없음.
- uvicorn 다중 워커. **선행 조건**: `main.py:_lifecycle`의 `monitor_loop()`이
  워커마다 중복 실행되므로 모니터를 별도 ECS service로 분리하거나
  (`claim_next_pending_submission()`처럼) DB 조건부 UPDATE 기반 리더 선출을
  적용해야 한다. 그 전까지는 단일 워커를 유지한다.

## 6. 실행 순서

| 단계 | 작업 | 선행 | 예상 효과 |
| --- | --- | --- | --- |
| 1 | P0-1 base64 pruning + 마이그레이션 | 없음 | 조회 I/O **-99%**, OOM 해소 |
| 2 | P0-3 무제한 조회 제거 | 없음 | 1요청 메모리 상한 확보 |
| 3 | P0-2 deferred 컬럼 | 1 | 재발 방지 |
| 4 | P1 gzip | 없음 | 전송량 -85% |
| 5 | P0-4 필요 컬럼 / N+1 | 없음 | 프롬프트·RunPod 화면 개선 |
| 6 | P1 `_assets_by_id` 제거 | 없음 | 자산 증가 선형 열화 제거 |
| 7 | P0-5 폴링 조정 | 1 | 요청 수 -40% |
| 8 | P1 권한 캐시 | 없음 | 쿼리 -66%/요청 |
| 9 | P2 인프라·구성 | 모니터 분리 | 동시성 확보 |

1~3단계만으로 OOM과 체감 지연의 대부분이 해소될 것으로 본다.

## 7. 검증 기준

- **계약 불변**: 변경 전후 `/api/v1/history`, `/api/v1/history/prompts`,
  `/api/v1/assets` 응답 JSON이 동일해야 한다. 기존
  `backend/tests/test_history_tab_api.py`, `test_prompt_batch_service.py`,
  `test_asset_streaming.py`, `test_frontend_submission_flow.py` 통과 필수.
- **회귀 테스트 추가**:
  - `runpod_status_json`에 4KB 초과 문자열이 저장되지 않음을 검증.
  - `task_history_items()`가 상한 없이 호출될 수 없음을 검증.
  - 프롬프트 이력 조회가 `assets`/`workflow_tasks` 전체를 읽지 않음
    (쿼리 카운트 assertion).
- **성능 측정**: `Server-Timing` 헤더와 EMF 로그가 이미 있다
  (`core/observability.py`). `operation_for_path()`에 `history`,
  `history/prompts`, `prompts/options` 경로를 추가해 CloudWatch
  `DOBEDUB/Studio`에서 전후를 비교한다.
- **목표치**: RDS 기준 `/history/prompts` p95 **< 300ms**,
  요청당 peak 할당 **< 5MB**.

## 8. 하지 않는 것

- **인덱스 추가**. 실행 계획상 병목이 아니다. 근거 없이 늘리면 쓰기 비용만 증가한다.
- **RDS/ECS 스케일업, 워커 증설**. 애플리케이션이 불필요한 수십 MB를 요청하는
  상태에서의 증설은 원인을 가리고 OOM을 앞당긴다. 1~3단계 후 재측정하고 판단한다.
- **S3 스토리지 전환**. 별도 과제이며 본 설계의 전제가 아니다.

## 9. 리스크

- **P0-1 마이그레이션은 되돌릴 수 없다.** 제거 대상 base64는 `assets` 파일과
  중복본이라 실질 손실이 없다. 실행 전 RDS 스냅샷을 남기고, 스크립트는
  `output.images[*].data`만 지우고 나머지 provider 필드는 보존한다.
- 파일이 유실되고 DB base64만 남은 과거 작업이 있다면 그 작업의 결과물 복구
  경로가 사라진다. **파일이 없는 행은 pruning 대상에서 제외**한다.

  로컬 DB 사전 점검 결과:

  ```
  base64 보유 task: 20건 / 파일 정상: 20건 / 문제: 0건 (출력링크 없음 0건)
  ```

  로컬 기준으로는 전부 안전하다. **같은 점검을 운영 RDS + EFS에서 반드시 다시
  실행한 뒤** 마이그레이션한다(EFS 경로는 컨테이너 기준
  `/data/outputs/dobedub-studio`).

## 10. 구현 결과 (2026-09-03)

### 적용된 변경

| 단계 | 내용 | 파일 |
| --- | --- | --- |
| P0-1 | `prune_provider_payload()` — 영속화 직전 4KB 초과 문자열 제거, 봉투(상태·ID·타이밍·파일명) 보존 | `task_tracking_service.py`, `db_adapter.py` |
| P0-1 | 기존 데이터 정리 마이그레이션. 출력 파일이 없는 행은 제외 | `migrations/versions/20260903_0032_prune_runpod_status_media.py` |
| P0-3 | `task_history_items(page=1, page_size=200)` — 무제한 시그니처 제거, 상한 강제 | `task_tracking_service.py` |
| P0-3 | `load_history(limit=200)` — `prompt_options()`의 전체 이력 로드 제거 | `studio_api_service.py` |
| P0-4 | `_latest_runpod_tasks_by_draft()` → 필요 컬럼(`id`,`status`)만 조회 | `prompt_batch_service.py` |
| P0-4 | `_item_relations()` 배치 조회로 `db.get()` N+1 제거 (2곳) | `runpod_request_batch_service.py` |
| P0-4 | `_reconcile_task_links_from_snapshot()` 필요 컬럼 배치 조회 + 변경분만 UPDATE | `runpod_request_batch_service.py` |
| P0-5 | 폴링 3초→5초, 2초→3초 (3곳) | `StudioShell.tsx`, `promptManagementScreen.tsx`, `runpodRequestScreen.tsx` |
| P1 | `GZipMiddleware(minimum_size=1024)` | `main.py` |
| P1 | `_assets_by_id()`(전체 테이블) 전 호출부 제거, `_assets_by_ids()`로 교체 후 헬퍼 삭제 | `task_tracking_service.py`, `db_adapter.py` |

### 측정 결과

```
데이터 정리 (실 DB 사본)
  runpod_status_json 합계  18.300MB → 0.006MB   (최대 행 1,598,732B → 284B)
  출력 파일 없어 건너뛴 행  0건

조회 성능 (SQLite 로컬)
  task_history_items(1,20)   43.0ms          →  16.8ms   peak 1.58MB
  prompt_options()          172.0ms/43.10MB  →  48.2ms   peak 4.00MB   (메모리 11배 감소)

API 계약
  /history, /history(runpod), /prompts/options 응답 632,643 bytes 바이트 단위 동일
```

운영 RDS에서는 페이지당 6.57MB 네트워크 전송이 사라지므로 개선 폭이 로컬보다 훨씬 크다.

### 계획에서 변경한 판단

- **P0-2(대용량 컬럼 `deferred=True`)는 적용하지 않았다.** `_task_to_history_item()`이
  `payload_json`/`runpod_status_json`/`runpod_submit_json`을 모두 읽으므로 이력
  경로에서는 전부 `undefer`해야 해 이득이 없고, 한 곳이라도 빠뜨리면 행마다 지연
  로딩 쿼리가 발생하는 **새로운 N+1**이 된다. 재발 방지는 더 강한 불변식으로 대체했다:
  쓰기 경계에서의 pruning + `backend/tests/test_provider_payload_pruning.py`의
  회귀 테스트(4KB 초과 문자열이 provider 컬럼에 저장되지 않음, 이력 조회에 LIMIT이
  항상 걸림, assets 전체 스캔이 없음).
- **P1(권한 캐시)은 보류했다.** 다른 세션이 같은 시점에 RBAC/역할 권한을 수정 중이고
  (`20260903_0031_restore_operator_role_permissions.py`), 요청 간 공유되는 권한
  캐시를 지금 넣으면 그 작업과 충돌해 진단하기 어려운 권한 staleness를 만든다.
  실행 순서에서도 8/9번으로 효과가 가장 작다.

### 남은 작업

- P1 권한 캐시 (위 사유로 보류)
- P2 커넥션 풀·세션 통합, EFS fingerprint 캐시, uvicorn 다중 워커(모니터 분리 선행)
- 운영 RDS+EFS에서 출력 파일 존재 여부 사전 점검 후 마이그레이션 실행
