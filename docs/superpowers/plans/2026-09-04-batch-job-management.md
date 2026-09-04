# Batch 작업 요청 관리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 폴더 하나를 골라 그 안의 이미지 전부를 프롬프트 생성부터 RunPod 영상 생성까지 한 번에 처리하고, 결과를 batch_id로 필터해 ZIP으로 내려받는 화면을 신설한다.

**Architecture:** 신규 `batch_jobs` 테이블을 상위 오케스트레이션 개념으로 두고, 이미 존재하는 `prompt_generation_batches` / `runpod_request_batches` 파이프라인을 그 자식으로 연결한다. 서버 `monitor_loop`이 프롬프트가 READY 되는 대로 기존 `studio_api_service.create_runpod_request_batch()`를 호출해 RunPod 요청으로 승격시킨다. 프롬프트 생성·디스패치·태스크 추적 로직은 새로 만들지 않고 전부 재사용한다.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 (`Mapped`/`mapped_column`) · Alembic · pytest · React 18 + TypeScript + Vite

**Spec:** `docs/superpowers/specs/2026-09-04-batch-job-management-design.md`

---

## Global Constraints

- 새 마이그레이션의 `down_revision = "20260903_0032"` (현재 head). 모든 DDL은 `sa.inspect(bind)`로 존재 확인 후 조건부 실행한다 — 기존 마이그레이션 전부가 이 관례를 따른다.
- `downgrade()`는 해당 리비전이 만든 구조만 제거한다. 기존 이력 데이터는 건드리지 않는다.
- 워크플로 JSON과 `.paramconfig.json` 계약을 바꾸지 않는다.
- RunPod 제출 재현성을 유지한다 — 입력 asset id, 프롬프트 텍스트, 워크플로 설정, 제출 스냅샷을 보존한다.
- 비밀정보를 소스·문서에 넣지 않는다.
- 커밋은 하되 **push·배포하지 않는다** (`AGENTS.md`).
- Length 허용값은 `{49, 81, 161}`, 기본 `81`. 그 외 값은 400.
- `duration_seconds = round(requested_frames / fps)`, `fps`는 워크플로우 `output_fps` 컨트롤의 default, 없으면 `16`. → 49=3초, 81=5초, 161=10초.
- 신규 API 권한은 전부 `prompts:build` **AND** `jobs:run`.
- 한국어 사용자 메시지를 쓴다 (기존 서비스 전부 한국어 예외 메시지).
- 각 태스크 끝에 `python3 -m compileall -q backend/app`가 통과해야 한다.

---

## 현재 상태 및 재작업 범위 (2026-09-04 3차 개정)

**브랜치 `feat/batch-job-management`, main(`1d3eee1`)에서 분기. Task 1~3은 이미 커밋되어 있다.**
이 계획을 처음부터 실행하지 말 것 — 아래 표의 완료분을 다시 수행하면 마이그레이션이 충돌한다.

| 커밋 | 내용 | 리뷰 | 상태 |
|---|---|---|---|
| `076f1f2` | 스펙 + 계획 문서 | — | — |
| `7b1ec62` | **Task 1** 스키마 (`batch_jobs` + 4개 링크 컬럼) | ✅ spec / ✅ quality | 완료. **R-A로 보강 필요** |
| `48a030b` | **Task 2** `create_batch_job` | ✅ spec / ✅ quality | 완료. **R-C로 결함 수정 필요** |
| `c592000` | **Task 3** 승격 | 미실시 | 완료. **R-D로 결함 수정 필요** |
| (작업 트리) | `batchJobId` 인젝션 수정 — 프로덕션 코드만, 테스트 없음 | — | **R-B로 마무리** |

`docs/superpowers/plans/` 의 이 문서가 유일한 기준이다. 세션 원장
(`.superpowers/sdd/progress.md`)은 `.superpowers/sdd/.gitignore`가 `*`로 무시하는
**세션 스크래치**이므로, 다른 사람이나 새 세션은 그것을 볼 수 없다. 진행 상태는 반드시
이 표를 갱신해서 남긴다.

**실행 순서:** R-A → R-B → R-C → R-D → R-E → Task 4 → Task 5 → … → Task 12.
Task 1·2·3 본문은 이미 수행된 기록으로만 남겨 둔다(재수행 금지).

**3차 개정에서 새로 확정된 결함 5건** — 상세와 가드레일은 아래 사이드 이펙트 절의
SE-11 ~ SE-15 참조. 요약:

| 결함 | 영향 | 해소 |
|---|---|---|
| 승격에 원자적 claim 없음 | **ECS Canary 배포마다** 구·신 revision이 동시에 승격 → RunPod 중복 과금 | R-D |
| `create_batch_job`의 트랜잭션이 실제로는 쪼개짐 | 배치가 영구히 `INCOMPLETE`로 고착 | R-C |
| 128건 승격이 monitor_loop 장기 점유 | RunPod 상태 폴링·프롬프트 처리 지연 | R-D |
| 대시보드가 비정규화 카운터를 안 쓰고 매번 재계산 | 3초 폴링 × 활성 배치 수만큼 GROUP BY | R-A + Task 4 |
| 배포 게이트 누락 | 이미지가 마이그레이션보다 먼저 뜨면 **Task History 전면 장애** | Task 12 |
| 고아 request item | task 없는 item 하나가 배치를 **영구 대기**시킴. 대화형 경로에도 있는 기존 결함 | R-E |
| 만료 없는 선점 | 컨테이너가 죽으면 draft가 **영구 선점**되어 다시 승격되지 않음 | R-D |

**main에서 확인된 사실 (계획의 전제):**

| 항목 | main 상태 | 결론 |
|---|---|---|
| Alembic head | `20260903_0032` | `down_revision` 그대로 유효 |
| `process_next_prompt_generation_draft` 정렬 | `created_at.asc(), id.asc()` (`prompt_batch_service.py:89-93`) | SE-1 여전히 존재. G-1 필요 |
| `claim_next_pending_submission` 정렬 | `created_at.asc(), id.asc()` (`task_tracking_service.py:510-519`) | SE-1 여전히 존재. G-1 필요 |
| `create_request_batch` 시그니처 | `(db, *, items, created_by, submitted_by=None)` — 동일 | G-5 그대로 적용 |
| `monitor_loop` | 단일 try/except 3단계 (`main.py:82-94`) | G-3 필요 |
| `GZipMiddleware(minimum_size=1024)` | 동일 | G-2 필요 |
| `NavItem.permission` | 단일 문자열 (`AppShell.tsx:43-50`) | G-9 필요 |
| `reviewScreens` grid 중복 | `:451`과 `:467`에 같은 문자열 2회 | G-6 필요 |
| `storage_backends` 읽기 API | 여전히 없음 | G-4 필요 |
| dispatch가 task policy로 막히는가 | 아니오 (`6d85a9f`가 오히려 큐 적재를 허용) | SE-8 판단 유효 |

## 코드베이스 검증 완료 사실 (2026-09-04 2차 재검토, 전부 실행해서 확인함)

계획의 코드 스니펫 **내부**까지 대조한 결과다. 1차 main 대조는 파일·라인·시그니처만 봤고
스니펫 안의 심볼·상수·CSS 변수는 검증하지 않아, Task 1~3 실행 중 매번 정정이 필요했다.
아래는 그 재발을 막기 위한 확정 사실이며, 각 태스크 본문에도 반영돼 있다.

| 항목 | 확정된 사실 |
|---|---|
| workflow id | **`.json` 확장자를 포함**한다 — `"Blowbang1.json"`, `"1-images.json"`. 빼면 `FileNotFoundError` |
| 워크플로 스키마 조회 | `workflow_service.**get_workflow_schema**(workflow_id)` |
| `output_fps` 컨트롤 | **10개 워크플로 어디에도 없다.** fps는 항상 폴백 16 → 49=3초, 81=5초, 161=10초 (스펙 표와 일치) |
| task 종료 상태 | `{"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"}` (`task_tracking_service.py:29`). **`SUCCESS` 필수**, `PARTIAL_FAILED`는 task가 아닌 batch 상태 |
| 라우터 등록 | `main.py:155-169`의 `api_routers` 리스트에 넣어 `/api/v1`·`/api` **양쪽**에 등록된다 |
| `studio_api_service.get_asset` | `(asset_id) -> tuple[dict, Path]` — 맞음 |
| 테스트 픽스처 | `conftest.py`에는 **`db_session`·`api_client`·`fake_runpod` 3개뿐.** `operator_user`/`seeded_assets`/`other_user`/`ready_draft`는 **없다** — 테스트 파일 안에서 직접 만들 것 |
| 테스트 DB | 테이블은 `db_session`/`api_client` 픽스처 안에서만 생성된다. 픽스처 없이 `SessionLocal()`만 쓰면 테이블이 없다 |
| 지시문 스텁 | `create_prompt_generation_batch`는 `active_instruction_text`를 호출한다. 해피패스 테스트는 per-test monkeypatch 필요 |
| CSS 변수 | `--v3-surface-muted`는 **없다.** 실제는 `--v3-bg-muted`. `--v3-accent`·`--v3-border`·`--v3-text-secondary`·`--v3-danger`는 존재 |
| `_StreamBuffer` | 계획대로 동작한다. `seekable()`/`tell()` 추가 **불필요** (직접 실행 확인) |
| 백엔드 헬퍼 | `require_permission`·`has_permission`·`CurrentUser` 존재 |
| 프론트 헬퍼 | `requestJson`·`fileToDataUrl`·`deleteUnsubmittedUpload`·`grokInstructionStatus`·`canUse` 모두 존재 |
| pytest | `pytest-randomly` 설치됨 → 순서가 매번 다름. `-q`만으로는 요약 줄이 안 나온다(`-rf` 사용) |

> **테스트 시그니처에 관한 전역 주의.** 아래 태스크들의 테스트 코드는
> `def test_x(db_session, operator_user, seeded_assets, ...)` 형태로 쓰여 있지만
> **`operator_user`·`seeded_assets`·`other_user`·`ready_draft`는 픽스처가 아니다 — 존재하지 않는다.**
> Task 2가 `backend/tests/test_batch_job_service.py`에 모듈 레벨 헬퍼 함수를 이미 만들어 뒀다:
> `_asset(asset_id)` · `_user(user_id="operator_1")` · `_asset_items(count)` · `_seed_assets(db_session, count)`.
> 같은 파일에 이어 쓰는 태스크(3·4)는 이 헬퍼를 재사용하고 시그니처를 그에 맞게 고쳐 쓸 것.
> 새 테스트 파일을 만드는 태스크(5·6·7·8)는 같은 패턴을 그 파일 안에 정의할 것.

**철회된 결정 (2026-09-04 3차 개정):** 2차 개정에서 "단일 인스턴스 운영을 전제로 중복 승격
위험을 수용한다"고 적었던 문구는 **틀렸으므로 철회한다.** 배포 전략이 ECS Express Canary이고
(`docs/ecs-express-deployment-runbook.md:18`) Canary 구간에는 구·신 revision이 동시에 살아
각자 monitor_loop을 돌린다. 정상 운영이 단일 인스턴스여도 **배포할 때마다** 중복 승격 창이 열린다.
SE-11 / G-10(R-D)이 유일한 방어 수단이며 선택 사항이 아니다.

**처리량 기대치 (명시하지 않으면 오해를 부르는 값):**

이 기능의 판매 포인트는 "무인 대량 처리"지만, 실제 소요 시간은 기존 파이프라인의 직렬 구조가 정한다.
128장 배치 기준:

| 단계 | 제약 | 소요 |
|---|---|---|
| 프롬프트 생성 | `process_next_prompt_generation_draft()`가 **주기당 1건**, 주기 5초 | 최소 **약 11분** (Grok 지연 별도) |
| 승격 | 주기당 20건(G-12) | 약 35초 |
| 영상 생성 | `max_active_tasks_per_user=3`, 디스패치 주기당 1건 | 영상 1건 5분 가정 시 **약 3.5시간** |

G-1(공정 스케줄링)이 적용되면 대화형 사용자의 요청이 배치보다 먼저 나가므로 위 값은 하한이다.
이는 결함이 아니라 기존 큐 설계의 귀결이며, 이 계획은 처리량을 바꾸지 않는다.
사용자에게 "몇 시간 걸린다"는 기대치를 화면에서 전달할지는 별도 판단 사항이다.

**main과 달라 계획을 고친 부분 (아래 태스크에 반영됨):**

- **C-1** `history.py`가 main에는 이미 필터를 갖고 있다 — `prompt_history(page, generationStatus, runpodStatus)`, `runpod_history(page, workflowId, resultStatus, workerId, dateFrom, dateTo)`. `batchId`는 **추가만** 해야 하며 시그니처를 대체하면 기존 필터가 사라진다 → Task 8 재작성
- **C-2** `client.ts`의 이력 호출이 **객체 파라미터**이고 헬퍼 이름이 `requestJson`이다 → Task 9 수정
- **C-3** `StudioShell.tsx`에 `ROUTE_REQUIRED_PERMISSION`(`:112`)과 `ROUTE_LABEL`(`:158`) 맵이 있고, 신규 라우트를 등록하지 않으면 **직접 URL 진입 시 권한 검사가 통과된다** → Task 9에 추가
- **C-4** 라인 번호가 전부 이동했다 → 각 태스크에 main 기준 번호로 갱신
- **C-5** main의 `GENERATE_NAV_ITEMS`는 4개이고 `assets` 라벨이 "컬렉션 관리"다 (perf 브랜치와 다름). 삽입 위치(`runpodRequests` 아래)는 그대로 유효

---

## 사이드 이펙트 검토 및 가드레일

이 기능은 **모든 사용자가 공유하는 단일 서버 큐 두 개**에 대량 작업을 밀어넣는다. 조사에서 확인한 실제 위험과 그에 대응하는 가드레일이다. 각 가드레일에는 그것을 지키는 테스트가 붙어 있고, 해당 태스크에 명시했다.

### SE-1 (심각) 배치가 대화형 사용자를 굶긴다

`prompt_batch_service.process_next_prompt_generation_draft()`(main `backend/app/services/prompt_batch_service.py:85`, 쿼리 `:89-93`)는 **전역에서 가장 오래된 PENDING draft 1건**만 처리하고, `monitor_loop`은 `task_monitor_interval_seconds`(기본 **5초**, `core/config.py:79`) 간격으로 돈다.

128장 배치를 만들면 그 128건이 전부 뒤에 오는 다른 사용자의 단건 요청보다 `created_at`이 빠르다. → **다른 사용자는 최소 128 × 5초 ≈ 11분 동안 프롬프트를 한 건도 못 받는다.** Grok 지연을 더하면 더 길어진다.

`task_tracking_service.claim_next_pending_submission()`(main `:499`, 쿼리 `:510-519`)도 `WorkflowTask.created_at.asc()` 전역 FIFO라 RunPod 제출 큐에 같은 문제가 있다.

> **가드레일 G-1 (Task 5):** 두 큐의 정렬을 `(배치 여부, created_at, id)`로 바꿔 **배치가 아닌 작업이 항상 먼저** 나가게 한다. SQL에서 `False < True`이므로 `batch_job_id IS NULL`인 행이 앞선다. 배치 작업끼리는 기존대로 FIFO다.
> 테스트: 배치가 없을 때 순서가 기존과 동일할 것 · 배치보다 늦게 들어온 단건이 먼저 나올 것.

### SE-2 GZipMiddleware가 ZIP 스트림을 재압축한다

`main.py:116`이 `GZipMiddleware(minimum_size=1024)`를 전역 등록한다. Starlette의 `GZipResponder`는 **응답에 `content-encoding` 헤더가 없으면** 콘텐츠 타입과 무관하게 압축한다. 이미 압축된 mp4를 담은 ZIP을 다시 gzip하면 이득 0에 CPU만 태운다.

> **가드레일 G-2 (Task 6):** ZIP 응답에 `Content-Encoding: identity`를 명시해 미들웨어를 건너뛰게 한다. 테스트로 헤더 존재를 고정한다.

### SE-3 monitor_loop 신규 단계가 기존 모니터링을 죽인다

`main.py:81`의 `monitor_loop`은 **한 개의 try/except**로 사이클 전체를 감싼다. 새 단계에서 예외가 나면 그 사이클의 뒷단계가 통째로 스킵된다.

> **가드레일 G-3 (Task 7):** 신규 단계 두 개를 **기존 단계들 뒤에** 놓고, **각각 독립된 try/except**로 감싼다. 배치 버그가 `monitor_active_jobs`(RunPod 상태 폴링)를 절대 멈추지 못하게 한다.

### SE-4 `storage_backends`에 읽기 메서드가 없다

`storage_backends.py`는 `save_bytes` / `save_file` / `delete` / `presigned_url`만 제공한다. **읽기 API가 없다.** 스펙 초안의 "storage_backends 어댑터로 읽는다"는 전제는 틀렸다.

> **가드레일 G-4 (Task 6):** 기존 파일 제공 경로와 동일하게 `studio_api_service.get_asset(asset_id) -> (dict, Path)`를 쓴다(`api/v1/assets.py:96`이 쓰는 바로 그 함수). 1MB 청크로 읽어 스트리밍한다 — 대용량 mp4를 메모리에 올리지 않는다.

### SE-5 `create_request_batch` 시그니처 변경이 기존 호출자를 깬다

승격 시 `RunpodRequestBatch`에 `batch_job_id`를 **행 생성 시점에** 심어야 한다. 그래야 뒤이어 만들어지는 WorkflowTask가 `job_payload_from_request_item`을 통해 그 값을 받아간다(닭-달걀 문제).

> **가드레일 G-5 (Task 3):** `batch_job_id`를 **키워드 전용 · 기본값 None**으로만 추가한다. 기존 호출자(`studio_api_service.create_runpod_request_batch`)는 무변경으로 동작한다. 테스트로 기존 경로가 `batch_job_id=None`을 남기는지 고정한다.

### SE-6 `reviewScreens.tsx`의 grid 정의가 head/row에 중복돼 있다

`gridTemplateColumns: "32px 36px 70px ..."` 문자열이 헤더(main `:451`)와 각 행(main `:467`)에 **각각 하드코딩**돼 있다. Batch ID 열을 추가하면서 한쪽만 고치면 표가 어긋난다.

> **가드레일 G-6 (Task 11):** 먼저 두 곳을 모듈 상수 하나(`RUNPOD_HISTORY_GRID`)로 뽑아내고 그 다음 열을 추가한다. 물리적으로 드리프트가 불가능해진다.

### SE-7 업로드 실패로 고아 자산이 남는다

폴더 128장을 업로드한 뒤 배치 생성이 실패하면 자산만 서버에 남는다.

> **가드레일 G-7 (Task 2, Task 10):** 배치 생성은 **단일 트랜잭션**이다. 실패 시 draft가 하나도 안 생기므로 `upload_cleanup_service.delete_unsubmitted_upload()`가 그 자산들을 계속 지울 수 있다(그 함수는 draft/task에 연결된 자산만 거부한다). 프론트는 배치 생성 실패 시 업로드된 assetId를 순회 삭제한다.

### SE-8 동시 활성 Task 한도가 배치를 자연 감속시킨다 (의도된 동작)

`task_execution_policies`의 기본값은 `max_active_tasks_per_user=3`, `max_active_tasks_total=10`이다. 다만 `task_policy_service.py:12` 주석대로 이 한도는 **RunPod가 job을 받아들인 뒤**에 적용되고, `PENDING_SUBMIT` 대기 항목에는 적용되지 않는다. 따라서 128건 배치는 큐에 얌전히 쌓였다가 유휴 worker가 생길 때 하나씩 나간다.

> **가드레일 없음 — 기존 정책을 그대로 존중한다.** 배치는 RunPod 용량을 독점하지 않는다. 단, G-1과 합쳐져야 대화형 사용자가 배치 뒤에 줄 서지 않는다.

### SE-9 history 엔드포인트 시그니처 변경

`/history/prompts`, `/history/runpod`에 `batchId`를 추가한다.

> **가드레일 G-8 (Task 8):** `batchId: str | None = None` 기본값으로만 추가한다. 미지정 시 쿼리에 `where`를 붙이지 않아 기존 결과가 바이트 단위로 동일해야 한다. 테스트로 고정한다.

### SE-10 `AppShell` 네비 권한 모델 변경

새 메뉴는 권한 두 개를 **동시에** 요구하는 첫 항목이다.

> **가드레일 G-9 (Task 9):** 기존 `permission?: string`은 그대로 두고 `permissions?: string[]`를 **추가**한다. 기존 8개 GENERATE/ADMIN 항목의 노출 조건은 한 줄도 바뀌지 않는다.

---

### SE-11 (치명) ECS Canary 배포마다 승격이 중복 실행된다

runbook은 배포 전략을 **"ECS Express Canary, 신규 task health check 후 이전 revision drain"**
(`docs/ecs-express-deployment-runbook.md:18`)으로 못박고 있다. Canary 구간에서는 **구·신 revision이
동시에 살아 있고 각자 `monitor_loop`을 돌린다.** 정상 운영이 단일 인스턴스여도 **배포할 때마다**
창이 열린다.

`promote_ready_batch_drafts()`는 READY draft를 조회한 뒤 요청을 만든다. 그 사이에 다른 프로세스가
같은 draft를 읽는다. `runpod_request_items`에는 `prompt_draft_id` 중복 방지 제약이 없고,
`JOB_LOCK`은 프로세스 내부 락이라 소용이 없다. 결과는 **RunPod 이중 제출 = 실제 이중 과금 +
영상 두 벌**이다.

> **가드레일 G-10 (R-D):** 승격 대상 draft를 조건부 UPDATE로 **선점(claim)한 뒤** 요청을 만든다.
> `task_tracking_service.claim_next_pending_submission()`(`:510-540`)이 같은 목적으로 쓰는
> 패턴을 그대로 따른다 — 후보를 읽고, `WHERE ... AND <아직 미선점>` 조건부 UPDATE의 `rowcount`가
> 1일 때만 그 행을 자기 것으로 삼는다.
> **`prompt_draft_id` 유니크 인덱스는 쓸 수 없다** — 사용자가 같은 draft를 정당하게 재제출하는
> 기존 동작(기존 RunPod 요청 관리 화면)을 깨뜨린다.

### SE-12 (치명) `create_batch_job`의 "단일 트랜잭션"이 실제로는 성립하지 않는다

`prompt_batch_service.create_prompt_generation_batch()`는 **내부에서 `db.commit()`을 호출한다**
(`prompt_batch_service.py:81`). 현재 커밋된 `create_batch_job`(`48a030b`)의 실행 순서는
`BatchJob` add → `flush` → **내부 commit** → `batch_job_id` UPDATE 2회 → `commit` 이다.

내부 commit 시점에 `BatchJob`·`PromptGenerationBatch`·draft N건이 **`batch_job_id = NULL`인 채로
영구 저장된다.** 그 뒤 UPDATE가 실패하거나 프로세스가 죽으면 `_counts_for()`는 그 배치의 draft를
0건으로 보고, `promptTerminal(0) >= total_images(N)`가 영원히 거짓이 되어 **배치가 대시보드에서
사라지지 않는다.**

Task 2 리뷰는 이 창을 놓쳤다 — "지시문 없는 워크플로"(쓰기 **전** raise) 경로만 검증했고
내부 commit **이후** 창은 보지 않았다.

> **가드레일 G-11 (R-C):** `create_prompt_generation_batch()`에 `commit: bool = True` 키워드를
> 추가하고, 배치 경로는 `commit=False`로 호출해 **배치 서비스가 트랜잭션을 소유**한다.
> 기존 호출자는 기본값으로 무변경 동작한다. 링크 컬럼은 UPDATE가 아니라 **행을 만들 때 채운다.**

### SE-13 (높음) 128건 승격이 monitor_loop을 장기 점유한다

`studio_api_service.create_runpod_request_batch()`는 `JOB_LOCK`을 잡은 채 항목마다
`job_payload_from_request_item()` → `create_job()`을 **순차 호출**한다(`:487`, `:503-506`).
`create_job`은 워크플로 JSON을 패치하고 입력 이미지를 읽는다. 한 배치의 READY draft 128건을
한 주기에 몰아 승격하면 그 사이 `monitor_active_jobs`(RunPod 상태 폴링)와 프롬프트 처리가 밀린다.

> **가드레일 G-12 (R-D):** 승격을 **주기당 상한**(`PROMOTION_LIMIT_PER_CYCLE = 20`)으로 끊는다.
> 남은 draft는 다음 주기에 처리된다. 이는 스펙이 요구하는 "서버가 유휴 worker를 확인해 순차 전송"과
> 오히려 더 잘 맞고, G-1(공정 스케줄링)의 의도와도 일관된다.

### SE-14 (높음) 대시보드가 비정규화 카운터를 쓰지 않는다

`batch_jobs`에 카운터를 둔 이유는 조회 시 조인·집계를 피하기 위해서인데, 계획의
`list_active_batch_jobs()`는 배치마다 `_counts_for()`를 호출해 **매번 GROUP BY 2회를 다시 돈다.**
화면 폴링 3초 × 활성 배치 수만큼 반복되고 monitor의 5초 갱신과 겹친다. 인덱스도
`batch_job_id` 단일 컬럼뿐이라 `WHERE batch_job_id = ? GROUP BY status`에 부족하다.
이 저장소는 과거 운영에서 MySQL 정렬 메모리 오류를 겪은 이력이 있다.

> **가드레일 G-13 (R-A + Task 4):** 대시보드가 쓰는 5개 값(`prompt_waiting_count`,
> `prompt_generating_count`, `runpod_pending_submit_count`, `runpod_queued_count`,
> `runpod_in_progress_count`)도 `batch_jobs`에 **저장**한다. `_counts_for()`는 monitor의
> `refresh_batch_job_counters()`만 호출하고, 조회 경로는 단순 SELECT만 한다.
> 복합 인덱스 `(batch_job_id, status)` on `image_prompt_drafts`,
> `(batch_job_id, deleted_at, status)` on `workflow_tasks`를 추가한다.

### SE-15 (치명) 배포 게이트가 빠져 있다

운영은 `RUN_SERVER_AUTO_MIGRATE=0`이다(`.env.example:86`, `backend/app/main.py:45`).
새 ORM 컬럼 `batch_job_id`는 `WorkflowTask`·`ImagePromptDraft` 등 **기존 화면이 매번 조회하는
테이블**에 붙는다. SQLAlchemy는 컬럼을 명시해 SELECT하므로, 마이그레이션 전에 새 이미지가 뜨면
`Unknown column 'batch_job_id'`로 **Task History·프롬프트 생성 관리·RunPod 요청 관리가 전부
장애**가 난다.

> **가드레일 G-14 (Task 12):** 최종 배포 단계에 runbook의 순서를 명시한다 —
> ① 새 이미지로 `--check` 실행 → ② `migrationRequired=true`면 `--if-needed` one-off task로
> 마이그레이션 → ③ 성공 확인 후 Canary 배포. `docs/ecs-express-deployment-runbook.md:80-88` 참조.

### SE-16 (중간) batch 참조 무결성

`batch_job_id` 네 컬럼은 String + index만 있고 FK가 없다.

**"이 저장소는 FK를 안 쓴다"는 틀린 설명이다.** 실측하면 41개 테이블 중 26개, 425개 컬럼 중
44개에 FK가 걸려 있다. 실제 관례는 그보다 정확하다 — **컬럼의 역할에 따라 갈린다**:

| 역할 | FK | 실측 예 |
|---|---|---|
| 소유자·자산 등 전방 관계 | **있음** | `workflow_tasks.user_id`, `image_prompt_drafts.asset_id`·`created_by`, `runpod_request_batches.created_by`·`submitted_by` |
| 전용 스냅샷 테이블의 관계 | **있음** | `runpod_request_items`의 `request_batch_id`·`prompt_draft_id`·`asset_id`·`task_id` (4/14) |
| **나중에 덧붙인 파이프라인 단계 역참조** | **없음** | `workflow_tasks.prompt_draft_id`·`request_batch_id`·`request_item_id`, `image_prompt_drafts.prompt_batch_id` |

`batch_job_id`는 세 번째 부류다. 특히 `image_prompt_drafts.prompt_batch_id`는
**구조적으로 완전히 같은 관계**(draft → 자신이 속한 배치)인데 인덱스만 있다.
여기에만 FK를 걸면 동일한 두 관계가 서로 다른 규칙으로 동작하게 된다.

> **판단:** FK는 추가하지 않는다. 근거는 "관례"라는 막연한 말이 아니라 위 실측이다 —
> 같은 모양의 기존 컬럼 네 개가 모두 인덱스만 갖는다.
> 실질적 위험(중복 승격)은 G-10의 원자적 claim이 해소하고,
> Task 12의 orphan 검증 쿼리가 배포 후 점검을 담당한다.
> **이 판단을 뒤집으려면** `prompt_batch_id`를 포함한 기존 네 컬럼까지 함께 FK로 바꾸는
> 별도 작업이어야 하며, `workflow_tasks`는 가장 큰 테이블이라 운영 RDS에서 FK 추가 시
> 메타데이터 락과 전체 스캔 비용을 따로 평가해야 한다.

### SE-17 (치명) request item은 있는데 WorkflowTask가 없으면 배치가 영구 대기한다

**이것은 배치가 만든 결함이 아니라, 기존 대화형 경로에 이미 있는 결함을 배치가 증폭시킨 것이다.**

`studio_api_service.create_runpod_request_batch()`는 두 단계로 나뉘어 있다:

1. `create_request_batch(...)` — `RunpodRequestItem` N건을 만들고 **commit** 한다
2. `for item in batch["items"]:` — 항목마다 `create_job()`으로 `WorkflowTask`를 만든다 (`:487-506`)

1단계가 커밋된 뒤 2단계 도중 **프로세스가 죽으면** `task_id IS NULL`인 item이 `PENDING_SUBMIT`
상태로 남는다. 예외가 났을 때만 `mark_request_item_failed()`가 돌기 때문에, 컨테이너 종료·배포 중단은
아무 표시도 남기지 않는다.

대화형 경로에서는 항목이 3~10건이고 사용자가 화면에서 재시도할 수 있어 눈에 띄지 않았다.
배치는 다르다 — 항목이 128건이라 창이 훨씬 넓고, 지켜보는 사람이 없으며, **완료 판정식이
그 틈을 영구 고착으로 바꾼다.**

계획의 판정식 `counts["promptReady"] == counts["videoRequested"]`는 **독립적으로 관리되는 두 모집단의
동등성**이다. `videoRequested`는 `workflow_tasks` 행 수이므로, task가 안 만들어진 item이 하나라도
있으면 이 식은 영원히 거짓이고 배치는 대시보드에서 사라지지 않는다.

> **가드레일 G-15 (R-E):** 두 가지를 함께 한다.
>
> 1. **고아 item 복구기(materializer).** monitor가 `task_id IS NULL`이고 `PENDING_SUBMIT`이며
>    일정 시간 지난 `runpod_request_items`를 찾아 누락된 task를 만든다(또는 재시도 한도 초과 시
>    item을 FAILED로 확정한다). 이는 **대화형 경로도 함께 고친다.**
> 2. **완료 판정을 동등성이 아니라 잔여 검사로 바꾼다.** "모든 draft가 종료 상태이고,
>    이 배치의 모든 request item이 종료 상태" 이면 완료다. 두 모집단을 비교하지 않으므로
>    카운트가 어긋나 배치가 고착되는 **버그 부류 자체가 사라진다.** item 상태는
>    `runpod_request_batch_service.refresh_request_batch_summary()`가 이미 task로부터 동기화한다.

---

## File Structure

**신규 (백엔드)**

| 파일 | 책임 |
|---|---|
| `backend/app/db/migrations/versions/20260904_0033_batch_jobs.py` | 스키마 변경 전부 |
| `backend/app/services/batch_job_service.py` | 배치 생성 · 승격 · 카운터/상태 · 조회. 이 기능의 유일한 로직 소유자 |
| `backend/app/services/batch_zip_service.py` | ZIP 스트리밍만. 서비스 파일이 비대해지지 않게 분리 |
| `backend/app/api/v1/batch_jobs.py` | HTTP 경계 · 권한 검사 |
| `backend/tests/test_batch_job_service.py` | 생성/승격/카운터/조회 |
| `backend/tests/test_batch_zip_service.py` | ZIP 구조 · 파일명 규칙 · gzip 우회 |
| `backend/tests/test_batch_fair_scheduling.py` | G-1 공정 스케줄링 |

**수정 (백엔드)**

| 파일 | 변경 |
|---|---|
| `backend/app/db/models.py` | `BatchJob` 모델 + 4개 테이블에 `batch_job_id` 컬럼 |
| `backend/app/services/prompt_batch_service.py` | G-1 정렬 |
| `backend/app/services/task_tracking_service.py` | G-1 정렬 + `batch_job_id` 컬럼 복사 |
| `backend/app/services/runpod_request_batch_service.py` | G-5 `batch_job_id` 키워드 인자 |
| `backend/app/services/studio_api_service.py` | `batchJobId` 전달 · history 응답 필드 · `batchId` 필터 |
| `backend/app/api/v1/history.py` | `batchId` 쿼리 파라미터 |
| `backend/app/main.py` | 라우터 등록 + monitor_loop 2단계 (G-3) |

**신규/수정 (프론트엔드)**

| 파일 | 변경 |
|---|---|
| `frontend/src/helpers/batchFolder.ts` | 신규. 폴더 파일 목록 필터링 순수 함수 |
| `frontend/src/screens/batchJobScreen.tsx` | 신규. 화면 5개 섹션 |
| `frontend/src/router.ts` | `create.batchJobs` 라우트 |
| `frontend/src/components/AppShell.tsx` | `permissions?: string[]` (G-9) + 메뉴 항목 |
| `frontend/src/helpers/navigation.ts` | `shellNavigate` 매핑 |
| `frontend/src/api/client.ts` | 타입 + 호출 5개 |
| `frontend/src/screens/reviewScreens.tsx` | grid 상수화(G-6) + Batch 열/필터/ZIP 버튼 |
| `frontend/src/StudioShell.tsx` | 화면 렌더 분기 |
| `frontend/src/styles.css` | 배치 화면 스타일 |

---

## ✅ Task 1 (완료 · 재수행 금지): 스키마 — 마이그레이션과 모델

> **커밋 `7b1ec62`로 이미 완료됐다. 이 절은 기록이며 다시 수행하지 않는다.**
> `20260904_0033_batch_jobs.py`와 `BatchJob` 모델이 이미 존재한다. 다시 만들면 마이그레이션이 충돌한다.
> 이 태스크에 대한 보강은 **R-A**에서 같은 리비전 파일을 수정하는 방식으로 한다.

**Files:**
- Create: `backend/app/db/migrations/versions/20260904_0033_batch_jobs.py`
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_batch_job_service.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `BatchJob` ORM 모델. 필드 — `id: str`, `workflow_id: str`, `status: str`, `source_dir_name: str | None`, `requested_frames: int`, `duration_seconds: int`, `total_images: int`, `prompt_completed_count: int`, `prompt_failed_count: int`, `video_requested_count: int`, `video_completed_count: int`, `video_failed_count: int`, `last_downloaded_at: datetime | None`, `created_by: str | None`, `created_at: datetime`, `updated_at: datetime`.
  추가 컬럼 — `PromptGenerationBatch.batch_job_id`, `RunpodRequestBatch.batch_job_id`, `ImagePromptDraft.batch_job_id`, `WorkflowTask.batch_job_id` (모두 `str | None`).
  상수 — `BATCH_JOB_INCOMPLETE = "INCOMPLETE"`, `BATCH_JOB_COMPLETE = "COMPLETE"`.

- [ ] **Step 1: 현재 head 리비전 확인**

Run:
```bash
cd "/Users/changkyuneun/Documents/New project/comfyui-video-studio-app-v4"
grep -rn "down_revision" backend/app/db/migrations/versions/20260903_0032_prune_runpod_status_media.py
grep -rln 'down_revision = "20260903_0032"' backend/app/db/migrations/versions/
```
Expected: 첫 명령은 `down_revision = "20260903_0031"` 출력. 두 번째 명령은 **아무것도 출력하지 않음** (= `0032`가 head, 분기 없음). 두 번째가 파일을 출력하면 중단하고 사용자에게 보고한다.

- [ ] **Step 2: 실패 테스트 작성**

Create `backend/tests/test_batch_job_service.py`:

```python
"""Batch job orchestration: creation, promotion, counters and queries."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect

from backend.app.db.models import BatchJob, ImagePromptDraft, PromptGenerationBatch, RunpodRequestBatch, WorkflowTask
from backend.app.db.session import SessionLocal


def test_batch_job_table_exists():
    session = SessionLocal()
    try:
        inspector = inspect(session.get_bind())
        assert "batch_jobs" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("batch_jobs")}
        assert {
            "id",
            "workflow_id",
            "status",
            "source_dir_name",
            "requested_frames",
            "duration_seconds",
            "total_images",
            "prompt_completed_count",
            "prompt_failed_count",
            "video_requested_count",
            "video_completed_count",
            "video_failed_count",
            "last_downloaded_at",
            "created_by",
            "created_at",
            "updated_at",
        } <= columns
    finally:
        session.close()


@pytest.mark.parametrize(
    "table, model",
    [
        ("prompt_generation_batches", PromptGenerationBatch),
        ("runpod_request_batches", RunpodRequestBatch),
        ("image_prompt_drafts", ImagePromptDraft),
        ("workflow_tasks", WorkflowTask),
    ],
)
def test_batch_job_id_column_added(table, model):
    session = SessionLocal()
    try:
        inspector = inspect(session.get_bind())
        assert "batch_job_id" in {column["name"] for column in inspector.get_columns(table)}
        assert hasattr(model, "batch_job_id")
    finally:
        session.close()
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'BatchJob'`

- [ ] **Step 4: 마이그레이션 작성**

Create `backend/app/db/migrations/versions/20260904_0033_batch_jobs.py`:

```python
"""add batch job orchestration tables and links

Revision ID: 20260904_0033
Revises: 20260903_0032
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0033"
down_revision = "20260903_0032"
branch_labels = None
depends_on = None

_LINKED_TABLES = (
    "prompt_generation_batches",
    "runpod_request_batches",
    "image_prompt_drafts",
    "workflow_tasks",
)


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "batch_jobs" not in tables:
        op.create_table(
            "batch_jobs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("workflow_id", sa.String(length=191), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="INCOMPLETE"),
            sa.Column("source_dir_name", sa.String(length=512), nullable=True),
            sa.Column("requested_frames", sa.Integer(), nullable=False, server_default="81"),
            sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("total_images", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prompt_completed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prompt_failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("video_requested_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("video_completed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("video_failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_downloaded_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_batch_jobs_created_by", "batch_jobs", ["created_by"])
        op.create_index("ix_batch_jobs_workflow_id", "batch_jobs", ["workflow_id"])
        # 미완료 대시보드(상태 필터 + 최신순)와 내역 조회가 함께 쓰는 복합 인덱스.
        op.create_index("ix_batch_jobs_status_created_at", "batch_jobs", ["status", "created_at"])

    for table in _LINKED_TABLES:
        if table not in tables:
            continue
        if "batch_job_id" in _columns(inspector, table):
            continue
        op.add_column(table, sa.Column("batch_job_id", sa.String(length=64), nullable=True))
        op.create_index(f"ix_{table}_batch_job_id", table, ["batch_job_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table in _LINKED_TABLES:
        if table not in tables or "batch_job_id" not in _columns(inspector, table):
            continue
        index_names = {index["name"] for index in inspector.get_indexes(table)}
        if f"ix_{table}_batch_job_id" in index_names:
            op.drop_index(f"ix_{table}_batch_job_id", table_name=table)
        op.drop_column(table, "batch_job_id")

    if "batch_jobs" in tables:
        op.drop_table("batch_jobs")
```

- [ ] **Step 5: 모델 추가**

`backend/app/db/models.py`의 `RunpodRequestItem` 클래스 **바로 뒤**(`class PromptFeedback` 앞)에 추가한다:

```python
class BatchJob(Base):
    """One folder-scoped bulk run: prompt generation through RunPod video output."""

    __tablename__ = "batch_jobs"
    __table_args__ = (
        Index("ix_batch_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    # INCOMPLETE / COMPLETE. Dashboards read only INCOMPLETE rows.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="INCOMPLETE")
    # Browsers never expose an absolute path, so only the picked folder name is stored.
    source_dir_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    requested_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=81)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    total_images: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_requested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)
```

같은 파일의 네 클래스에 각각 한 줄씩 추가한다 (`created_at` 선언 바로 위):

```python
    # class PromptGenerationBatch
    batch_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # class RunpodRequestBatch
    batch_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # class ImagePromptDraft
    batch_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # class WorkflowTask
    batch_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
```

- [ ] **Step 6: 테스트 통과 확인**

Run:
```bash
python3 -m compileall -q backend/app
python3 -m pytest backend/tests/test_batch_job_service.py -q
```
Expected: PASS (5 passed)

- [ ] **Step 7: 전체 회귀 확인 (스키마 변경은 광범위하다)**

Run: `python3 -m pytest backend/tests -q`
Expected: 기존 테스트 전부 PASS. 실패가 있으면 마이그레이션 조건부 실행 로직을 먼저 의심한다.

- [ ] **Step 8: 커밋**

```bash
git add backend/app/db/migrations/versions/20260904_0033_batch_jobs.py backend/app/db/models.py backend/tests/test_batch_job_service.py
git commit -m "feat(batch): add batch_jobs table and batch_job_id links"
```

---

## ✅ Task 2 (완료 · 재수행 금지): 배치 생성 (`create_batch_job`)

> **커밋 `48a030b`로 이미 완료됐다. 이 절은 기록이며 다시 수행하지 않는다.**
> 다만 SE-12(트랜잭션이 실제로는 쪼개짐) 결함이 이 코드에 있다 — **R-C**에서 고친다.

**Files:**
- Create: `backend/app/services/batch_job_service.py`
- Test: `backend/tests/test_batch_job_service.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `BatchJob` 모델
- Produces:
  - `ALLOWED_FRAMES: frozenset[int] = frozenset({49, 81, 161})`
  - `DEFAULT_FRAMES: int = 81`
  - `resolve_duration_seconds(workflow_id: str, requested_frames: int) -> int`
  - `create_batch_job(db: Session, payload: dict, *, created_by: str) -> dict`
    payload: `{"workflowId": str, "sourceDirName": str, "requestedFrames": int, "items": [{"assetId": str, "fileName": str}]}`
    반환: `batch_job_payload()` 결과
  - `batch_job_payload(db: Session, batch_job_id: str) -> dict`
    반환 키: `id`, `workflowId`, `status`, `sourceDirName`, `requestedFrames`, `durationSeconds`, `totalImages`, `promptCompletedCount`, `promptFailedCount`, `videoRequestedCount`, `videoCompletedCount`, `videoFailedCount`, `failedCount`, `lastDownloadedAt`, `createdBy`, `createdByName`, `createdAt`, `updatedAt`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_batch_job_service.py` 끝에 추가한다. **주의:** `conftest.py`에는 `db_session`·`api_client`·`fake_runpod` 세 픽스처뿐이다. 아래 테스트가 쓰는 `operator_user`/`seeded_assets`/`other_user`는 **존재하지 않으므로 이 테스트 파일 안에서 직접 만들어야 한다.** `backend/tests/test_prompt_batch_service.py:14`의 `_asset()` 헬퍼 패턴을 따를 것.

```python
from backend.app.services import batch_job_service


def _asset_items(count: int) -> list[dict]:
    return [{"assetId": f"asset_{index}", "fileName": f"image{index}.jpg"} for index in range(1, count + 1)]


def test_create_batch_job_persists_batch_prompt_batch_and_drafts(db_session, operator_user, seeded_assets):
    result = batch_job_service.create_batch_job(
        db_session,
        {
            "workflowId": "Blowbang1.json",
            "sourceDirName": "shoot-0904",
            "requestedFrames": 81,
            "items": _asset_items(3),
        },
        created_by=operator_user.id,
    )

    assert result["totalImages"] == 3
    assert result["status"] == "INCOMPLETE"
    assert result["sourceDirName"] == "shoot-0904"
    assert result["requestedFrames"] == 81
    # fps 16 기준 81 프레임 = 5초.
    assert result["durationSeconds"] == 5

    batch = db_session.get(BatchJob, result["id"])
    assert batch is not None

    prompt_batches = db_session.scalars(
        select(PromptGenerationBatch).where(PromptGenerationBatch.batch_job_id == batch.id)
    ).all()
    assert len(prompt_batches) == 1
    assert prompt_batches[0].total_count == 3

    drafts = db_session.scalars(
        select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == batch.id)
    ).all()
    assert len(drafts) == 3
    assert {draft.status for draft in drafts} == {"PENDING"}
    # 사용자가 고른 Length가 모든 draft에 그대로 적용된다.
    assert {draft.requested_frames for draft in drafts} == {81}


@pytest.mark.parametrize("frames, expected_seconds", [(49, 3), (81, 5), (161, 10)])
def test_duration_seconds_matches_frame_choice(db_session, operator_user, seeded_assets, frames, expected_seconds):
    result = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": frames, "items": _asset_items(1)},
        created_by=operator_user.id,
    )
    assert result["requestedFrames"] == frames
    assert result["durationSeconds"] == expected_seconds


@pytest.mark.parametrize("frames", [0, 30, 100, 200, -1])
def test_create_batch_job_rejects_unsupported_frames(db_session, operator_user, seeded_assets, frames):
    with pytest.raises(ValueError, match="영상 길이"):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": frames, "items": _asset_items(1)},
            created_by=operator_user.id,
        )


def test_create_batch_job_rejects_empty_items(db_session, operator_user):
    with pytest.raises(ValueError, match="이미지"):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": []},
            created_by=operator_user.id,
        )


def test_create_batch_job_leaves_no_partial_rows_when_workflow_has_no_instruction(db_session, operator_user, seeded_assets):
    """G-7: 실패한 생성은 batch_jobs 행을 남기지 않아야 고아 자산을 지울 수 있다."""
    before = db_session.scalars(select(BatchJob.id)).all()
    with pytest.raises(ValueError):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "workflow-without-instructions", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(2)},
            created_by=operator_user.id,
        )
    db_session.rollback()
    after = db_session.scalars(select(BatchJob.id)).all()
    assert after == before
```

파일 상단 import에 `from sqlalchemy import inspect, select`를 반영한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.app.services.batch_job_service`

- [ ] **Step 3: 서비스 구현**

Create `backend/app/services/batch_job_service.py`:

```python
"""Folder-scoped batch orchestration over the existing prompt and RunPod pipelines.

A batch job owns nothing that the existing pipelines already own. It records the
user's folder-level intent, links the prompt and RunPod batches it spawned, and
keeps denormalized counters so the dashboards never join across three tables.
"""
from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import BatchJob, ImagePromptDraft, PromptGenerationBatch, User
from backend.app.services import prompt_batch_service, workflow_service

ALLOWED_FRAMES = frozenset({49, 81, 161})
DEFAULT_FRAMES = 81
DEFAULT_FPS = 16
# 이 두 상수는 backend/app/db/models.py 에 있다. 서비스 모듈에서 재정의하지 말고 import 할 것.


def resolve_duration_seconds(workflow_id: str, requested_frames: int) -> int:
    """Seconds of video for a frame count, using the workflow's own output fps."""
    fps = DEFAULT_FPS
    try:
        schema = workflow_service.get_workflow_schema(workflow_id)
    except Exception:
        # A missing schema must not block batch creation; the frame count is
        # what RunPod actually consumes and 16 is what the payload builder uses.
        schema = None
    if schema:
        for segment in schema.get("segments") or []:
            for control in segment.get("configControls") or []:
                if str(control.get("key")) == "output_fps":
                    candidate = control.get("default")
                    if isinstance(candidate, (int, float)) and int(candidate) > 0:
                        fps = int(candidate)
                    break
    return max(1, round(requested_frames / fps))


def _validated_frames(value: Any) -> int:
    try:
        frames = int(value)
    except (TypeError, ValueError):
        frames = DEFAULT_FRAMES
    if frames not in ALLOWED_FRAMES:
        allowed = ", ".join(str(item) for item in sorted(ALLOWED_FRAMES))
        raise ValueError(f"영상 길이(Length)는 {allowed} 중 하나여야 합니다.")
    return frames


def create_batch_job(db: Session, payload: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    """Create the batch job and its prompt generation batch in one transaction."""
    workflow_id = str(payload.get("workflowId") or "").strip()
    if not workflow_id:
        raise ValueError("워크플로우를 먼저 선택하세요.")
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValueError("배치로 처리할 이미지를 하나 이상 선택하세요.")
    requested_frames = _validated_frames(payload.get("requestedFrames", DEFAULT_FRAMES))

    batch = BatchJob(
        id=f"batch_{uuid.uuid4().hex[:16]}",
        workflow_id=workflow_id,
        status=BATCH_JOB_INCOMPLETE,
        source_dir_name=str(payload.get("sourceDirName") or "").strip()[:512] or None,
        requested_frames=requested_frames,
        duration_seconds=resolve_duration_seconds(workflow_id, requested_frames),
        total_images=len(items),
        created_by=created_by,
    )
    db.add(batch)
    db.flush()

    # Reuse the existing prompt pipeline wholesale. It raises before any write
    # when the workflow has no active instruction, so a failed batch leaves no
    # rows behind and the uploaded assets stay deletable.
    prompt_batch = prompt_batch_service.create_prompt_generation_batch(
        db,
        {
            "workflowId": workflow_id,
            "items": [
                {
                    "assetId": str(item.get("assetId") or "").strip(),
                    "slotIndex": index,
                    "requestedFrames": requested_frames,
                }
                for index, item in enumerate(items, start=1)
            ],
        },
        created_by=created_by,
    )

    db.execute(
        PromptGenerationBatch.__table__.update()
        .where(PromptGenerationBatch.id == prompt_batch["id"])
        .values(batch_job_id=batch.id)
    )
    db.execute(
        ImagePromptDraft.__table__.update()
        .where(ImagePromptDraft.prompt_batch_id == prompt_batch["id"])
        .values(batch_job_id=batch.id)
    )
    db.commit()
    return batch_job_payload(db, batch.id)


def batch_job_payload(db: Session, batch_job_id: str) -> dict[str, Any]:
    batch = db.get(BatchJob, batch_job_id)
    if batch is None:
        raise ValueError("배치 작업을 찾을 수 없습니다.")
    return _batch_payload(db, batch)


def _batch_payload(db: Session, batch: BatchJob) -> dict[str, Any]:
    return {
        "id": batch.id,
        "workflowId": batch.workflow_id,
        "status": batch.status,
        "sourceDirName": batch.source_dir_name,
        "requestedFrames": batch.requested_frames,
        "durationSeconds": batch.duration_seconds,
        "totalImages": batch.total_images,
        "promptCompletedCount": batch.prompt_completed_count,
        "promptFailedCount": batch.prompt_failed_count,
        "videoRequestedCount": batch.video_requested_count,
        "videoCompletedCount": batch.video_completed_count,
        "videoFailedCount": batch.video_failed_count,
        "failedCount": batch.prompt_failed_count + batch.video_failed_count,
        # 대시보드 단계별 값. 저장된 카운터를 그대로 내보낸다(G-13).
        "promptWaiting": batch.prompt_waiting_count,
        "promptGenerating": batch.prompt_generating_count,
        "runpodPendingSubmit": batch.runpod_pending_submit_count,
        "runpodQueued": batch.runpod_queued_count,
        "runpodInProgress": batch.runpod_in_progress_count,
        "lastDownloadedAt": batch.last_downloaded_at.isoformat() if batch.last_downloaded_at else None,
        "createdBy": batch.created_by,
        "createdByName": _user_name(db, batch.created_by),
        "createdAt": batch.created_at.isoformat() if batch.created_at else None,
        "updatedAt": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _user_name(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user.name if user else None
```

`get_workflow_schema`가 실제 이름임은 재검토에서 확인했다(위 '코드베이스 검증 완료 사실' 표). 추가 확인 불필요.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/batch_job_service.py backend/tests/test_batch_job_service.py
git commit -m "feat(batch): create batch jobs over the existing prompt pipeline"
```

---

## ✅ Task 3 (완료 · 재수행 금지): 승격 — READY 프롬프트 → RunPod 요청 (G-5)

> **커밋 `c592000`로 이미 완료됐다(리뷰 미실시). 이 절은 기록이며 다시 수행하지 않는다.**
> SE-11(원자적 claim 없음)·SE-13(주기당 상한 없음) 결함이 이 코드에 있다 — **R-D**에서 고친다.
> `batchJobId` 인젝션 수정은 작업 트리에 프로덕션 코드만 있고 테스트가 없다 — **R-B**에서 마무리한다.

**Files:**
- Modify: `backend/app/services/runpod_request_batch_service.py:14` (`create_request_batch` 시그니처)
- Modify: `backend/app/services/studio_api_service.py:475`·`:500` (`create_runpod_request_batch`), `:432`·`:462` (`job_payload_from_request_item`) — main 기준
- Modify: `backend/app/services/task_tracking_service.py` (`task.request_item_id = ...` 줄 바로 뒤)
- Modify: `backend/app/services/batch_job_service.py`
- Test: `backend/tests/test_batch_job_service.py` (추가)

**Interfaces:**
- Consumes: Task 2의 `batch_job_service`, `BatchJob`
- Produces: `promote_ready_batch_drafts() -> dict` — 반환 `{"promoted": int, "batches": list[str]}`.
  `runpod_request_batch_service.create_request_batch(db, *, items, created_by, submitted_by=None, batch_job_id=None)`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_batch_job_service.py`에 추가:

```python
def test_promote_ready_drafts_creates_runpod_request_items(db_session, operator_user, seeded_assets):
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(2)},
        created_by=operator_user.id,
    )
    drafts = db_session.scalars(
        select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])
    ).all()
    for draft in drafts:
        draft.status = "READY"
        draft.positive_prompt = "a cinematic shot"
    db_session.commit()

    result = batch_job_service.promote_ready_batch_drafts()

    assert result["promoted"] == 2
    request_batches = db_session.scalars(
        select(RunpodRequestBatch).where(RunpodRequestBatch.batch_job_id == created["id"])
    ).all()
    assert len(request_batches) == 1
    items = db_session.scalars(
        select(RunpodRequestItem).where(RunpodRequestItem.request_batch_id == request_batches[0].id)
    ).all()
    assert len(items) == 2
    assert {item.requested_frames for item in items} == {81}


def test_promote_is_idempotent(db_session, operator_user, seeded_assets):
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(2)},
        created_by=operator_user.id,
    )
    for draft in db_session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])).all():
        draft.status = "READY"
        draft.positive_prompt = "a cinematic shot"
    db_session.commit()

    first = batch_job_service.promote_ready_batch_drafts()
    second = batch_job_service.promote_ready_batch_drafts()

    assert first["promoted"] == 2
    assert second["promoted"] == 0
    total_items = db_session.scalars(
        select(RunpodRequestItem)
        .join(RunpodRequestBatch, RunpodRequestItem.request_batch_id == RunpodRequestBatch.id)
        .where(RunpodRequestBatch.batch_job_id == created["id"])
    ).all()
    assert len(total_items) == 2


def test_failed_drafts_are_never_promoted(db_session, operator_user, seeded_assets):
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(3)},
        created_by=operator_user.id,
    )
    drafts = db_session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])).all()
    drafts[0].status = "READY"
    drafts[0].positive_prompt = "ok"
    drafts[1].status = "FAILED"
    drafts[2].status = "MANUAL_REQUIRED"
    db_session.commit()

    result = batch_job_service.promote_ready_batch_drafts()

    assert result["promoted"] == 1


def test_existing_request_batch_path_records_no_batch_job_id(db_session, operator_user, ready_draft):
    """G-5: 기존 RunPod 요청 관리 경로는 batch_job_id를 남기지 않는다."""
    from backend.app.services.runpod_request_batch_service import create_request_batch

    batch = create_request_batch(
        db_session,
        items=[{"promptDraftId": ready_draft.id}],
        created_by=operator_user.id,
    )
    row = db_session.get(RunpodRequestBatch, batch["id"])
    assert row.batch_job_id is None
```

import에 `RunpodRequestItem`을 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -q -k promote`
Expected: FAIL — `AttributeError: module ... has no attribute 'promote_ready_batch_drafts'`

- [ ] **Step 3: `create_request_batch`에 키워드 인자 추가 (G-5)**

`backend/app/services/runpod_request_batch_service.py:14`의 시그니처를 바꾼다:

```python
def create_request_batch(
    db: Session,
    *,
    items: list[dict],
    created_by: str,
    submitted_by: str | None = None,
    batch_job_id: str | None = None,
) -> dict:
```

같은 함수의 `RunpodRequestBatch(...)` 생성부에 한 줄 추가한다 (`submitted_by=` 다음 줄):

```python
        # Set at row creation so the tasks built from these items can read it
        # back through job_payload_from_request_item.
        batch_job_id=batch_job_id,
```

- [ ] **Step 4: `studio_api_service`에 batchJobId 전달**

`backend/app/services/studio_api_service.py:500`(main) `create_runpod_request_batch()`를 바꾼다.

> **보안 (실행 중 발견해 수정된 항목):** 이 함수의 `payload`는 `POST /api/v1/jobs/request-batches`
> (`jobs.py:71-72`)가 브라우저 body를 그대로 넘긴 **검증되지 않은 dict**다. `payload.get("batchJobId")`로
> 읽으면 `jobs:run` 권한만 가진 사용자가 남의 배치 id를 실어 보내 자기 task를 그 배치에 붙일 수 있고,
> 배치 카운터·ZIP 내보내기·이력 필터가 모두 오염된다.
> **payload에서 읽지 말고 keyword 전용 인자로 받는다.** `payload.pop()` 같은 필터는 미래의 라우트가
> 잊을 수 있지만, 인자로 올리면 HTTP 호출자가 설정할 방법 자체가 사라진다.

시그니처를 바꾼다:

```python
def create_runpod_request_batch(
    payload: dict, *, user: dict[str, object], batch_job_id: str | None = None
) -> dict:
```

HTTP 라우트(`jobs.py`)는 이 인자를 **넘기지 않는다**. 내부 호출자인
`batch_job_service.promote_ready_batch_drafts()`만 `batch_job_id=batch_id`로 넘긴다
(payload dict 안에 `"batchJobId"`를 넣지 않는다).

그리고 `create_request_batch(...)` 호출을 바꾼다:

```python
            batch = create_request_batch(
                session,
                items=raw_items,
                created_by=worker_id,
                submitted_by=user_id,
                batch_job_id=str(batch_job_id or "").strip() or None,
            )
```

`:432` `job_payload_from_request_item()`의 반환 dict에 한 줄 추가한다 (`"requestItemId": item.id,` — main `:462` 다음):

```python
            "batchJobId": batch_owner.batch_job_id,
```

- [ ] **Step 5: `task_tracking_service`가 컬럼을 복사하게 한다**

`backend/app/services/task_tracking_service.py`의 `task.request_item_id = ...` 줄 **바로 다음**에 추가한다:

```python
    # 여기의 `payload`는 HTTP body가 아니라 job_payload_from_request_item()이
    # 내부에서 만든 job payload다. 바로 윗줄들의 request_batch_id/request_item_id와
    # 똑같은 경로이므로 여기서 읽는 것은 안전하다(§Task 3 Step 4의 보안 주의와 무관).
    task.batch_job_id = str(job.get("batchJobId") or payload.get("batchJobId") or task.batch_job_id or "") or None
```

- [ ] **Step 6: 승격 로직 구현**

`backend/app/services/batch_job_service.py` 끝에 추가한다. import에 다음을 더한다:

```python
from backend.app.db.models import RunpodRequestBatch, RunpodRequestItem
from backend.app.db.session import SessionLocal
```

```python
def promote_ready_batch_drafts() -> dict[str, Any]:
    """Turn newly-READY batch prompts into RunPod requests.

    Called once per monitor cycle. Reuses studio_api_service wholesale so batch
    submissions are indistinguishable from interactive ones: same request-item
    snapshot, same durable task record, same dispatcher.
    """
    # Imported here: studio_api_service imports this module's siblings, and a
    # module-level import would create a cycle at application start.
    from backend.app.services import studio_api_service

    db = SessionLocal()
    promoted_batches: list[str] = []
    promoted = 0
    try:
        incomplete_ids = list(db.scalars(
            select(BatchJob.id).where(BatchJob.status == BATCH_JOB_INCOMPLETE)
        ))
        pending: list[tuple[str, str, list[str]]] = []
        for batch_id in incomplete_ids:
            batch = db.get(BatchJob, batch_id)
            if batch is None:
                continue
            already = set(db.scalars(
                select(RunpodRequestItem.prompt_draft_id)
                .join(RunpodRequestBatch, RunpodRequestItem.request_batch_id == RunpodRequestBatch.id)
                .where(RunpodRequestBatch.batch_job_id == batch_id)
            ))
            draft_ids = [
                draft_id
                for draft_id in db.scalars(
                    select(ImagePromptDraft.id).where(
                        ImagePromptDraft.batch_job_id == batch_id,
                        ImagePromptDraft.status == "READY",
                    )
                )
                if draft_id not in already
            ]
            if draft_ids:
                pending.append((batch_id, str(batch.created_by or ""), draft_ids))
    finally:
        db.close()

    for batch_id, owner_id, draft_ids in pending:
        if not owner_id:
            continue
        studio_api_service.create_runpod_request_batch(
            {
                "workerId": owner_id,
                "batchJobId": batch_id,
                "items": [{"promptDraftId": draft_id} for draft_id in draft_ids],
            },
            user={"id": owner_id},
        )
        promoted += len(draft_ids)
        promoted_batches.append(batch_id)

    return {"promoted": promoted, "batches": promoted_batches}
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py backend/tests/test_durable_runpod_request_batch.py -q`
Expected: PASS. 기존 `test_durable_runpod_request_batch.py`가 함께 통과해야 G-5가 지켜진 것이다.

- [ ] **Step 8: 커밋**

```bash
git add backend/app/services/batch_job_service.py backend/app/services/runpod_request_batch_service.py backend/app/services/studio_api_service.py backend/app/services/task_tracking_service.py backend/tests/test_batch_job_service.py
git commit -m "feat(batch): promote ready batch prompts into RunPod requests"
```

---

## Task R-A: 마이그레이션 0033 보강 — 복합 인덱스와 대시보드 카운터 (G-13)

**Files:**
- Modify: `backend/app/db/migrations/versions/20260904_0033_batch_jobs.py`
- Modify: `backend/app/db/models.py` (`BatchJob`)
- Test: `backend/tests/test_batch_job_service.py`

**왜 새 리비전 0034가 아니라 0033을 고치는가:** 이 브랜치는 아직 머지되지도 배포되지도 않았고,
0033은 어떤 운영 DB에서도 실행된 적이 없다. 리비전을 쪼개면 배포 시 one-off 마이그레이션이
두 번 필요해질 뿐이다. **머지 이후라면 절대 이렇게 하지 말 것** — 그때는 0034를 새로 만든다.

> **Step 0의 사전 확인이 이 판단의 전제다.** alembic은 이미 적용된 리비전을 다시 실행하지 않으므로,
> **어느 환경에서든 0033이 이미 적용됐다면 그 환경은 이 수정을 영원히 받지 못한다.**
> 운영 RDS는 `1d3eee1` 기준이라 0033이 없지만, 개발자 로컬 DB나 별도 검증 DB에서 이미 돌렸을 수 있다.
> 하나라도 적용된 환경이 있으면 **0033 수정을 포기하고 0034로 분리한다.**

- [ ] **Step 0: 0033 적용 여부 사전 확인 (F)**

Run:
```bash
python3 -m alembic current
ls -1 data/*.db 2>/dev/null | while read db; do
  echo "--- $db"; DATABASE_URL="sqlite:///$db" python3 -m alembic current 2>/dev/null | tail -1
done
```

Expected: 어느 것도 `20260904_0033`을 출력하지 않아야 한다. 2026-09-04 확인 시점의 로컬 개발 DB는
`20260903_0031`이었다. **하나라도 `20260904_0033`이면 이 태스크를 중단하고**, 이 태스크와 R-D의
스키마 변경을 새 리비전 `20260904_0034_batch_durability.py`(`down_revision = "20260904_0033"`)로
옮긴 뒤 진행한다. 운영 RDS는 배포 시 `--check`로 판정하므로 여기서 확인할 필요가 없다.

**Interfaces:**
- Consumes: Task 1의 `BatchJob`
- Produces: `BatchJob`에 컬럼 5개 추가 — `prompt_waiting_count`, `prompt_generating_count`,
  `runpod_pending_submit_count`, `runpod_queued_count`, `runpod_in_progress_count` (전부 `int`, default 0).
  인덱스 2개 — `ix_image_prompt_drafts_batch_status`, `ix_workflow_tasks_batch_deleted_status`.

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_batch_job_service.py`의 기존 스키마 테스트 옆에 추가한다:

```python
def test_batch_jobs_has_dashboard_counter_columns(db_session):
    inspector = inspect(db_session.get_bind())
    columns = {column["name"] for column in inspector.get_columns("batch_jobs")}
    assert {
        "prompt_waiting_count",
        "prompt_generating_count",
        "runpod_pending_submit_count",
        "runpod_queued_count",
        "runpod_in_progress_count",
    } <= columns


def test_batch_aggregation_indexes_exist(db_session):
    """G-13: WHERE batch_job_id = ? GROUP BY status 를 단일 컬럼 인덱스로는 감당 못 한다."""
    inspector = inspect(db_session.get_bind())
    draft_indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("image_prompt_drafts")}
    task_indexes = {index["name"]: index["column_names"] for index in inspector.get_indexes("workflow_tasks")}
    assert draft_indexes.get("ix_image_prompt_drafts_batch_status") == ["batch_job_id", "status"]
    assert task_indexes.get("ix_workflow_tasks_batch_deleted_status") == ["batch_job_id", "deleted_at", "status"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -rf -k "dashboard_counter or aggregation_indexes"`
Expected: FAIL — 두 테스트 모두 AssertionError

- [ ] **Step 3: 마이그레이션 보강**

`20260904_0033_batch_jobs.py`의 `upgrade()`에서 `batch_jobs` `create_table` 블록에 컬럼 5개를 추가한다
(`video_failed_count` 다음 줄):

```python
            sa.Column("prompt_waiting_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prompt_generating_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runpod_pending_submit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runpod_queued_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runpod_in_progress_count", sa.Integer(), nullable=False, server_default="0"),
```

같은 `upgrade()`의 링크 컬럼 루프 **다음**에 승격 선점 컬럼을 먼저 추가한다.
아래 인덱스가 이 컬럼을 참조하므로 순서가 중요하다:

```python
    # G-10: 승격 선점 lease. ECS Canary 구간에 구·신 revision이 동시에 승격해
    # RunPod에 이중 제출하는 것을 조건부 UPDATE로 막는다. 플래그가 아니라 만료가 있는
    # lease인 이유는 R-D 참조 — 프로세스가 죽으면 release가 돌지 않기 때문이다.
    if "image_prompt_drafts" in tables and "promotion_claimed_at" not in _columns(inspector, "image_prompt_drafts"):
        op.add_column("image_prompt_drafts", sa.Column("promotion_claimed_at", sa.DateTime(), nullable=True))
```

그 다음 복합 인덱스를 추가한다. 기존 관례대로 존재 확인 후 생성한다:

```python
    # G-13: 대시보드와 monitor가 함께 쓰는 집계 경로.
    # WHERE batch_job_id = ? GROUP BY status 를 단일 컬럼 인덱스로는 감당하지 못한다.
    aggregation_indexes = (
        ("image_prompt_drafts", "ix_image_prompt_drafts_batch_status", ["batch_job_id", "status"]),
        ("workflow_tasks", "ix_workflow_tasks_batch_deleted_status", ["batch_job_id", "deleted_at", "status"]),
        # R-D의 승격 후보 조회 전용. WHERE status='READY' AND (claim IS NULL OR claim <= cutoff)를
        # 5초마다 돌리므로 status·claim이 인덱스에 함께 있어야 한다.
        ("image_prompt_drafts", "ix_image_prompt_drafts_promotion", ["status", "promotion_claimed_at", "batch_job_id"]),
        # SE-17 복구기 전용. task_id IS NULL AND status='PENDING_SUBMIT' 스캔.
        ("runpod_request_items", "ix_runpod_request_items_orphan", ["status", "task_id"]),
    )
    for table, index_name, columns in aggregation_indexes:
        if table not in tables:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table)}
        if index_name not in existing:
            op.create_index(index_name, table, columns)
```

`downgrade()`의 링크 컬럼 제거 루프 **앞**에 대응 제거를 넣는다:

```python
    for table, index_name, _columns in (
        ("image_prompt_drafts", "ix_image_prompt_drafts_batch_status", None),
        ("workflow_tasks", "ix_workflow_tasks_batch_deleted_status", None),
    ):
        if table in tables and index_name in {index["name"] for index in inspector.get_indexes(table)}:
            op.drop_index(index_name, table_name=table)
```

- [ ] **Step 4: 모델 보강**

`backend/app/db/models.py`의 `BatchJob`에서 `video_failed_count` 선언 다음에 추가한다:

```python
    # 대시보드가 읽는 단계별 카운터. monitor가 갱신하고 조회 경로는 SELECT만 한다(G-13).
    prompt_waiting_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_generating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runpod_pending_submit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runpod_queued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runpod_in_progress_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

같은 파일의 `ImagePromptDraft`에 승격 선점 컬럼을 추가한다 (R-D가 사용한다):

```python
    # 승격 선점 lease. NULL이거나 STALE_PROMOTION_CLAIM_SECONDS 이전이면 재선점 가능하다(G-10).
    promotion_claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

`downgrade()`의 인덱스 제거 목록에 `ix_image_prompt_drafts_promotion`·`ix_runpod_request_items_orphan`을
포함하고, `promotion_claimed_at` 컬럼 제거도 넣는다:

```python
    if "image_prompt_drafts" in tables and "promotion_claimed_at" in _columns(inspector, "image_prompt_drafts"):
        op.drop_column("image_prompt_drafts", "promotion_claimed_at")
```

- [ ] **Step 5: 테스트 통과 + 마이그레이션 실물 검증**

Run:
```bash
python3 -m compileall -q backend/app
python3 -m pytest backend/tests/test_batch_job_service.py -rf
rm -f /tmp/batch_mig_check.db
DATABASE_URL=sqlite:////tmp/batch_mig_check.db python3 -m alembic upgrade head
DATABASE_URL=sqlite:////tmp/batch_mig_check.db python3 -m alembic downgrade -1
DATABASE_URL=sqlite:////tmp/batch_mig_check.db python3 -m alembic upgrade head
```
Expected: 테스트 전부 PASS, alembic 세 명령 모두 exit 0.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/db/migrations/versions/20260904_0033_batch_jobs.py backend/app/db/models.py backend/tests/test_batch_job_service.py
git commit -m "feat(batch): add dashboard counters and aggregation indexes"
```

---

## Task R-B: `batchJobId` 인젝션 수정 마무리

**Files:**
- Modify: `backend/app/services/studio_api_service.py` (작업 트리에 이미 수정됨)
- Modify: `backend/app/services/batch_job_service.py` (작업 트리에 이미 수정됨)
- Test: `backend/tests/test_batch_job_service.py`

**배경:** `c592000`이 `create_runpod_request_batch()`에서 `payload.get("batchJobId")`를 읽게 만들었다.
그 `payload`는 `POST /api/v1/jobs/request-batches`(`jobs.py:71-72`)가 **브라우저 body를 그대로 넘긴
검증되지 않은 dict**다. `jobs:run` 권한만 가진 사용자가 남의 배치 id를 실어 보내 자기 task를 그 배치에
붙일 수 있고, 배치 카운터·ZIP 내보내기·이력 필터가 전부 오염된다.

**프로덕션 코드 수정은 작업 트리에 이미 들어가 있다.** 확인 후 회귀 테스트만 붙이고 커밋한다.

- [ ] **Step 1: 작업 트리의 수정 확인**

Run: `git diff backend/app/services/studio_api_service.py backend/app/services/batch_job_service.py`

기대하는 내용:
- `create_runpod_request_batch(payload: dict, *, user: dict[str, object], batch_job_id: str | None = None)`
- `create_request_batch(..., batch_job_id=str(batch_job_id or "").strip() or None)` — `payload.get`이 아님
- `promote_ready_batch_drafts()`가 payload dict에서 `"batchJobId"`를 빼고 `batch_job_id=batch_id`를 인자로 전달

diff가 이와 다르면 위 형태로 맞춘다. **`payload.pop("batchJobId", None)` 방식은 쓰지 않는다** —
필터는 미래의 라우트가 잊을 수 있지만, 인자로 올리면 HTTP 호출자가 설정할 방법 자체가 사라진다.

- [ ] **Step 2: 실패 테스트 작성**

`backend/tests/test_batch_job_service.py`에 추가한다. 이 파일의 기존 헬퍼(`_asset`·`_user`·
`_asset_items`·`_seed_assets`)를 재사용한다:

```python
def test_batch_job_id_cannot_be_injected_through_the_request_body(db_session, monkeypatch):
    """HTTP body의 batchJobId는 무시되어야 한다 — 남의 배치에 task를 붙일 수 없다."""
    from backend.app.services import studio_api_service

    db_session.add(_user("victim"))
    db_session.add(_user("attacker"))
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    victim_batch = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(1)},
        created_by="victim",
    )
    draft = db_session.scalars(
        select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == victim_batch["id"])
    ).one()
    draft.status = "READY"
    draft.positive_prompt = "ok"
    draft.created_by = "attacker"
    db_session.commit()

    created = studio_api_service.create_runpod_request_batch(
        {"workerId": "attacker", "batchJobId": victim_batch["id"], "items": [{"promptDraftId": draft.id}]},
        user={"id": "attacker"},
    )

    row = db_session.get(RunpodRequestBatch, created["id"])
    assert row.batch_job_id is None, "요청 본문의 batchJobId가 반영되면 안 된다"
```

`create_job` 실물 실행이 워크플로 JSON과 이미지 파일을 요구하면, Task 3 테스트가 쓴 것과 같은
방식으로 `job_runtime`을 스텁한다. `RunpodRequestBatch` import를 파일 상단에 추가한다.

- [ ] **Step 3: 테스트 실패 확인 (작업 트리 수정을 되돌린 상태에서)**

Run:
```bash
git stash push backend/app/services/studio_api_service.py backend/app/services/batch_job_service.py
python3 -m pytest backend/tests/test_batch_job_service.py -rf -k injected
```
Expected: FAIL — `assert row.batch_job_id is None`이 victim 배치 id 때문에 실패

그 다음 복원한다: `git stash pop`

- [ ] **Step 4: 테스트 통과 + 회귀 확인**

Run:
```bash
python3 -m pytest backend/tests/test_batch_job_service.py -rf
python3 -m pytest backend/tests/test_durable_runpod_request_batch.py backend/tests/test_runpod_submission_queue.py -rf
python3 -m compileall -q backend/app
```
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/studio_api_service.py backend/app/services/batch_job_service.py backend/tests/test_batch_job_service.py
git commit -m "fix(batch): stop accepting batchJobId from the request body"
```

---

## Task R-C: `create_batch_job` 트랜잭션 소유권 (G-11 · SE-12)

**Files:**
- Modify: `backend/app/services/prompt_batch_service.py` (`create_prompt_generation_batch`)
- Modify: `backend/app/services/batch_job_service.py` (`create_batch_job`)
- Test: `backend/tests/test_batch_job_service.py`

**Interfaces:**
- Produces: `prompt_batch_service.create_prompt_generation_batch(db, payload, *, created_by, commit: bool = True, batch_job_id: str | None = None)`
  — 기존 호출자는 기본값으로 무변경 동작한다.

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_create_batch_job_leaves_no_rows_when_the_link_step_fails(db_session, monkeypatch):
    """SE-12: 내부 commit 때문에 batch_job_id가 NULL인 고아 행이 남으면 안 된다."""
    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))

    # 프롬프트 배치 생성 직후 단계에서 강제로 실패시킨다.
    original = batch_job_service._link_prompt_batch

    def boom(*args, **kwargs):
        raise RuntimeError("link step failed")

    monkeypatch.setattr(batch_job_service, "_link_prompt_batch", boom)
    with pytest.raises(RuntimeError):
        batch_job_service.create_batch_job(
            db_session,
            {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(2)},
            created_by="operator_1",
        )
    db_session.rollback()
    monkeypatch.setattr(batch_job_service, "_link_prompt_batch", original)

    assert db_session.scalars(select(BatchJob)).all() == []
    assert db_session.scalars(select(PromptGenerationBatch)).all() == []
    assert db_session.scalars(select(ImagePromptDraft)).all() == []


def test_prompt_batch_creation_still_commits_for_existing_callers(db_session, monkeypatch):
    """commit 기본값은 True — 기존 프롬프트 생성 관리 화면 경로가 바뀌면 안 된다."""
    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    result = prompt_batch_service.create_prompt_generation_batch(
        db_session,
        {"workflowId": "Blowbang1.json", "items": [{"assetId": "asset_1", "slotIndex": 1, "requestedFrames": 81}]},
        created_by="operator_1",
    )
    db_session.rollback()  # commit 되었다면 rollback 후에도 남아 있어야 한다
    assert db_session.get(PromptGenerationBatch, result["id"]) is not None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -rf -k "link_step_fails or still_commits"`
Expected: FAIL — 첫 테스트에서 고아 행이 남아 `assert ... == []` 실패

- [ ] **Step 3: `create_prompt_generation_batch`에 트랜잭션 제어 추가**

`backend/app/services/prompt_batch_service.py`의 시그니처를 바꾼다:

```python
def create_prompt_generation_batch(
    db: Session,
    payload: dict[str, Any],
    *,
    created_by: str,
    commit: bool = True,
    batch_job_id: str | None = None,
) -> dict[str, Any]:
```

`PromptGenerationBatch(...)` 생성 인자에 한 줄, `ImagePromptDraft(...)` 생성 인자에 한 줄 추가한다.
링크를 **행 생성 시점에 채우면** 사후 UPDATE 자체가 사라진다:

```python
        batch_job_id=batch_job_id,
```

함수 끝의 `db.commit()`을 바꾼다:

```python
    # 배치 파이프라인은 자기 트랜잭션 안에서 이 함수를 부른다(SE-12). 그 경우
    # 여기서 commit하면 batch_jobs 행과 draft가 서로 다른 트랜잭션에 묶여
    # 중간 실패 시 batch_job_id가 NULL인 고아 행이 영구히 남는다.
    if commit:
        db.commit()
    else:
        db.flush()
    return prompt_generation_batch_payload(db, batch.id)
```

- [ ] **Step 4: `create_batch_job`을 트랜잭션 소유자로 바꾼다**

`backend/app/services/batch_job_service.py`의 `create_batch_job`에서 `create_prompt_generation_batch`
호출 뒤의 **`db.execute(...)` UPDATE 2개를 삭제**하고, 호출에 두 인자를 넘긴다:

```python
    prompt_batch = _link_prompt_batch(
        db,
        workflow_id=workflow_id,
        items=items,
        requested_frames=requested_frames,
        created_by=created_by,
        batch_job_id=batch.id,
    )
    db.commit()
    return batch_job_payload(db, batch.id)
```

그리고 테스트가 가로챌 수 있도록 얇은 위임 함수를 둔다:

```python
def _link_prompt_batch(db, *, workflow_id, items, requested_frames, created_by, batch_job_id):
    """프롬프트 배치를 만들되 commit은 하지 않는다 — 트랜잭션은 create_batch_job이 소유한다."""
    return prompt_batch_service.create_prompt_generation_batch(
        db,
        {
            "workflowId": workflow_id,
            "items": [
                {"assetId": str(item.get("assetId") or "").strip(), "slotIndex": index, "requestedFrames": requested_frames}
                for index, item in enumerate(items, start=1)
            ],
        },
        created_by=created_by,
        commit=False,
        batch_job_id=batch_job_id,
    )
```

- [ ] **Step 5: 테스트 통과 + 회귀 확인**

Run:
```bash
python3 -m pytest backend/tests/test_batch_job_service.py -rf
python3 -m pytest backend/tests/test_prompt_batch_service.py backend/tests/test_prompt_batch_api.py -rf
python3 -m compileall -q backend/app
```
Expected: 전부 PASS. 두 번째 명령이 `commit=True` 기본값 호환을 지키는지 검증한다.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/services/prompt_batch_service.py backend/app/services/batch_job_service.py backend/tests/test_batch_job_service.py
git commit -m "fix(batch): own the batch creation transaction end to end"
```

---

## Task R-D: 원자적 승격 claim과 주기당 상한 (G-10 · G-12 · SE-11 · SE-13)

**Files:**
- Modify: `backend/app/db/migrations/versions/20260904_0033_batch_jobs.py`
- Modify: `backend/app/db/models.py` (`ImagePromptDraft`)
- Modify: `backend/app/services/batch_job_service.py` (`promote_ready_batch_drafts`)
- Test: `backend/tests/test_batch_job_service.py`

**왜 필요한가 (SE-11):** 배포 전략이 **ECS Express Canary**다 — 구·신 revision이 동시에 살아 있고
각자 `monitor_loop`을 돌린다. 현재 승격은 READY draft를 **조회한 뒤** 요청을 만들므로, 그 사이에
다른 프로세스가 같은 draft를 읽어 **RunPod에 이중 제출**한다. 실제 이중 과금이다.
`prompt_draft_id` 유니크 인덱스는 정당한 재제출을 깨뜨리므로 쓸 수 없다.

**Interfaces:**
- Produces: `ImagePromptDraft.promotion_claimed_at: datetime | None`
- Produces: `batch_job_service.PROMOTION_LIMIT_PER_CYCLE = 20`
- Produces: `batch_job_service.claim_batch_drafts_for_promotion(db, *, limit) -> tuple[list[tuple[str, str, str]], datetime]`
  — `([(batch_job_id, owner_id, draft_id), ...], claim_stamp)`. 선점에 성공한 것만 담긴다.
- Produces: `batch_job_service.still_owns_claim(db, draft_ids, claimed_at) -> list[str]` — 제출 직전 재확인용

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_claim_is_exclusive_across_independent_sessions(db_session, monkeypatch):
    """SE-11: Canary 구간의 두 프로세스를 독립 Session 두 개로 모사한다.

    같은 Session에서 두 번 부르면 SQLAlchemy identity map과 단일 트랜잭션 때문에
    조건부 UPDATE의 경합을 전혀 재현하지 못한다 — 반드시 별도 Session이어야 한다.
    """
    from backend.app.db.session import SessionLocal

    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 3)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(3)},
        created_by="operator_1",
    )
    for draft in db_session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])):
        draft.status = "READY"
        draft.positive_prompt = "ok"
    db_session.commit()

    session_a, session_b = SessionLocal(), SessionLocal()
    try:
        claimed_a = batch_job_service.claim_batch_drafts_for_promotion(session_a, limit=10)
        claimed_b = batch_job_service.claim_batch_drafts_for_promotion(session_b, limit=10)
    finally:
        session_a.close()
        session_b.close()

    ids_a = {draft_id for _batch, _owner, draft_id in claimed_a}
    ids_b = {draft_id for _batch, _owner, draft_id in claimed_b}
    assert len(ids_a) == 3
    assert ids_a & ids_b == set(), "두 프로세스가 같은 draft를 선점했다 — RunPod 이중 제출이 발생한다"


def test_two_threads_racing_the_same_candidates_never_double_claim(db_session, monkeypatch):
    """SE-11: 두 스레드가 후보를 **모두 읽은 뒤에** 동시에 쓰기를 시작한다.

    배리어가 핵심이다. 배리어 없이 순차로 부르면 두 번째 워커의 SELECT가 이미
    커밋된 상태를 보므로, 조건부 UPDATE의 `AND promotion_claimed_at IS NULL`을
    통째로 지워도 테스트가 통과한다 — 아무것도 검증하지 못하는 테스트가 된다.

    측정 결과(2026-09-04, SQLite): 배리어를 넣으면 가드가 있을 때 overlap 0,
    가드를 제거하면 overlap이 후보 전량으로 터진다. 3/3 결정적이며 오류도 없다.
    """
    import threading
    from backend.app.db.session import SessionLocal

    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 10)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(10)},
        created_by="operator_1",
    )
    for draft in db_session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])):
        draft.status = "READY"
        draft.positive_prompt = "ok"
    db_session.commit()

    barrier = threading.Barrier(2)
    results: dict[str, list[str]] = {}
    errors: list[str] = []

    def worker(name: str) -> None:
        session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            results[name] = [draft_id for _b, _o, draft_id in
                             batch_job_service.claim_batch_drafts_for_promotion(session, limit=10)]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {type(exc).__name__}")
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(f"w{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    claimed = list(results.values())
    assert set(claimed[0]) & set(claimed[1]) == set(), "두 스레드가 같은 draft를 선점했다 — RunPod 이중 제출"
    assert len(claimed[0]) + len(claimed[1]) == 10, "선점 총합이 후보 수와 달라 draft가 유실됐다"


def test_expired_claim_is_reclaimed_after_a_process_dies(db_session, monkeypatch):
    """SE-11 후속: 승격 도중 컨테이너가 죽으면 release가 못 돈다. lease가 회수해야 한다."""
    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(1)},
        created_by="operator_1",
    )
    draft = db_session.scalars(
        select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])
    ).one()
    draft.status = "READY"
    draft.positive_prompt = "ok"
    # 프로세스가 선점 직후 죽은 상태를 모사한다 — request item은 만들어지지 않았다.
    draft.promotion_claimed_at = datetime.utcnow() - timedelta(
        seconds=batch_job_service.STALE_PROMOTION_CLAIM_SECONDS + 60
    )
    db_session.commit()

    reclaimed = batch_job_service.claim_batch_drafts_for_promotion(db_session, limit=10)

    assert [draft_id for _b, _o, draft_id in reclaimed] == [draft.id], "만료된 선점이 회수되지 않아 draft가 영구 방치된다"


def test_expired_claim_is_not_reclaimed_when_the_request_item_exists(db_session, monkeypatch):
    """선점이 만료됐더라도 request item이 있으면 제출은 실제로 일어난 것이다 — 재승격 금지."""
    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(1)},
        created_by="operator_1",
    )
    draft = db_session.scalars(
        select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])
    ).one()
    draft.status = "READY"
    draft.positive_prompt = "ok"
    draft.promotion_claimed_at = datetime.utcnow() - timedelta(
        seconds=batch_job_service.STALE_PROMOTION_CLAIM_SECONDS + 60
    )
    request_batch = RunpodRequestBatch(
        id="rpb_existing", workflow_id="Blowbang1.json", requested_count=1,
        status="QUEUED", created_by="operator_1", batch_job_id=created["id"],
    )
    db_session.add(request_batch)
    db_session.add(RunpodRequestItem(
        id="rpi_existing", request_batch_id=request_batch.id, sequence_no=1,
        prompt_draft_id=draft.id, asset_id=draft.asset_id, workflow_id="Blowbang1.json",
        positive_prompt="ok", requested_frames=81, status="PENDING_SUBMIT",
    ))
    db_session.commit()

    assert batch_job_service.claim_batch_drafts_for_promotion(db_session, limit=10) == []


def test_claim_respects_the_per_cycle_limit(db_session, monkeypatch):
    """SE-13: 128건을 한 주기에 몰아 처리하면 monitor loop이 밀린다."""
    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 25)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(25)},
        created_by="operator_1",
    )
    for draft in db_session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])):
        draft.status = "READY"
        draft.positive_prompt = "ok"
    db_session.commit()

    claimed = batch_job_service.claim_batch_drafts_for_promotion(db_session, limit=batch_job_service.PROMOTION_LIMIT_PER_CYCLE)

    assert len(claimed) == batch_job_service.PROMOTION_LIMIT_PER_CYCLE == 20


def test_already_promoted_drafts_are_never_reclaimed(db_session, monkeypatch):
    """멱등성: 이미 runpod_request_items가 있는 draft는 후보에서 빠진다."""
    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 2)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(2)},
        created_by="operator_1",
    )
    drafts = db_session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])).all()
    for draft in drafts:
        draft.status = "READY"
        draft.positive_prompt = "ok"
    db_session.commit()

    batch_job_service.promote_ready_batch_drafts()
    again = batch_job_service.promote_ready_batch_drafts()

    assert again["promoted"] == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -rf -k "claim or per_cycle or reclaimed"`
Expected: FAIL — `claim_batch_drafts_for_promotion`이 없어 `AttributeError`

- [ ] **Step 3: 스키마는 R-A에서 이미 끝났음을 확인**

`promotion_claimed_at` 컬럼과 `ix_image_prompt_drafts_promotion` 인덱스는 **R-A가 이미 추가했다.**
같은 마이그레이션 파일을 두 태스크가 나눠 고치면 인덱스가 컬럼보다 먼저 생성되는 순서 문제가 생기므로,
스키마 변경은 전부 R-A에 모았다. 여기서는 확인만 한다:

Run: `python3 -c "from backend.app.db.models import ImagePromptDraft; print(ImagePromptDraft.promotion_claimed_at)"`
Expected: 컬럼 객체가 출력된다. `AttributeError`가 나면 R-A가 완료되지 않은 것이므로 먼저 R-A를 끝낸다.

- [ ] **Step 4: 원자적 claim 구현**

`backend/app/services/batch_job_service.py`에 추가한다. `task_tracking_service.claim_next_pending_submission()`
(`:510-540`)이 쓰는 것과 같은 패턴 — 후보를 읽고, 조건부 UPDATE의 `rowcount`가 1일 때만 자기 것으로 삼는다:

```python
PROMOTION_LIMIT_PER_CYCLE = 20
# task_tracking_service.STALE_DISPATCH_CLAIM_SECONDS(=300)와 같은 값·같은 의미다.
# 이 저장소는 이미 같은 문제를 같은 방식으로 푼다 — 선점 표식에 만료를 두고,
# "실제로는 일어나지 않았음"을 확인한 뒤에만 회수한다.
STALE_PROMOTION_CLAIM_SECONDS = 300


def _unpromoted_ready_drafts(limit: int, cutoff: datetime):
    """Candidate query: READY batch drafts with no request item and a free/expired claim.

    NOT EXISTS keeps this O(candidates). Loading every historical
    RunpodRequestItem.prompt_draft_id into a Python set — the obvious
    alternative — grows without bound and runs every 5 seconds forever.
    """
    already_promoted = (
        select(RunpodRequestItem.id)
        .where(RunpodRequestItem.prompt_draft_id == ImagePromptDraft.id)
        .exists()
    )
    return (
        select(ImagePromptDraft.id, ImagePromptDraft.batch_job_id, BatchJob.created_by)
        .join(BatchJob, BatchJob.id == ImagePromptDraft.batch_job_id)
        .where(
            BatchJob.status == BATCH_JOB_INCOMPLETE,
            ImagePromptDraft.status == "READY",
            # 미선점이거나, 선점 후 만료된 것(프로세스가 죽어 release가 못 돈 경우).
            or_(
                ImagePromptDraft.promotion_claimed_at.is_(None),
                ImagePromptDraft.promotion_claimed_at <= cutoff,
            ),
            ~already_promoted,
        )
        .order_by(ImagePromptDraft.created_at.asc(), ImagePromptDraft.id.asc())
        .limit(limit)
    )


def claim_batch_drafts_for_promotion(db: Session, *, limit: int) -> list[tuple[str, str, str]]:
    """Take exclusive ownership of up to `limit` READY batch drafts.

    A conditional UPDATE is the only thing standing between an ECS Canary
    rollout — where the old and new revision both run the monitor loop — and a
    duplicated, separately billed RunPod submission for every draft in flight.

    The claim is a lease, not a flag. A container killed mid-promotion never
    runs its release, so a plain flag would strand those drafts forever; an
    expired claim is reclaimable, but only while no request item exists for the
    draft — that item is the proof the submission actually happened.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=STALE_PROMOTION_CLAIM_SECONDS)
    candidates = db.execute(_unpromoted_ready_drafts(limit, cutoff)).all()

    claimed: list[tuple[str, str, str]] = []
    # 호출자가 제출 직전에 still_owns_claim(db, ids, now)로 재확인할 수 있도록
    # 이 사이클의 claim 시각을 함께 돌려준다.
    claim_stamp = now
    for draft_id, batch_job_id, owner_id in candidates:
        if not owner_id:
            continue
        result = db.execute(
            ImagePromptDraft.__table__.update()
            .where(
                ImagePromptDraft.id == draft_id,
                # 경합하는 다른 프로세스가 그 사이에 선점했다면 rowcount가 0이 된다.
                or_(
                    ImagePromptDraft.promotion_claimed_at.is_(None),
                    ImagePromptDraft.promotion_claimed_at <= cutoff,
                ),
            )
            .values(promotion_claimed_at=now)
        )
        if result.rowcount:
            claimed.append((str(batch_job_id), str(owner_id), str(draft_id)))
    db.commit()
    return claimed, claim_stamp


def still_owns_claim(db: Session, draft_ids: list[str], claimed_at: datetime) -> list[str]:
    """Drop drafts whose lease was taken over by another process while we worked.

    The lease alone does not cover a process that is slow rather than dead: if
    our promotion outlives STALE_PROMOTION_CLAIM_SECONDS, another monitor may
    reclaim the same drafts and submit them, and we would then submit again.
    Re-reading the claim timestamp right before submitting closes that window —
    promotion_claimed_at doubles as the claim token, so no extra column is
    needed. A residual race remains between this check and the submit itself;
    STALE_PROMOTION_CLAIM_SECONDS must therefore stay comfortably above the
    worst plausible promotion time for PROMOTION_LIMIT_PER_CYCLE items.
    """
    if not draft_ids:
        return []
    return [str(row) for row in db.scalars(
        select(ImagePromptDraft.id).where(
            ImagePromptDraft.id.in_(draft_ids),
            ImagePromptDraft.promotion_claimed_at == claimed_at,
        )
    )]


def release_promotion_claim(db: Session, draft_ids: list[str]) -> None:
    """Hand drafts back when the submission never happened, so a later cycle retries.

    Best-effort only — a killed process never reaches here. The lease expiry in
    claim_batch_drafts_for_promotion() is what actually guarantees recovery.
    """
    if not draft_ids:
        return
    db.execute(
        ImagePromptDraft.__table__.update()
        .where(ImagePromptDraft.id.in_(draft_ids))
        .values(promotion_claimed_at=None)
    )
    db.commit()
```

`from datetime import datetime, timedelta` 와 `from sqlalchemy import or_` 를 import에 추가한다.

- [ ] **Step 5: `promote_ready_batch_drafts`를 claim 기반으로 교체**

기존 본문의 "미완료 배치를 훑어 READY draft를 모으는" 부분을 위 claim 호출로 바꾼다.
배치별 `try/except`는 유지한다 — 소유자가 비활성인 배치 하나가 매 주기 전체 승격을 막으면 안 된다.
실패한 배치의 draft는 `release_promotion_claim`으로 되돌려 다음 주기에 재시도되게 한다:

```python
def promote_ready_batch_drafts() -> dict[str, Any]:
    """Turn newly-READY batch prompts into RunPod requests.

    Called once per monitor cycle. Reuses studio_api_service wholesale so batch
    submissions are indistinguishable from interactive ones: same request-item
    snapshot, same durable task record, same dispatcher. The per-cycle limit
    keeps a 128-image batch from starving RunPod status polling (SE-13).
    """
    from backend.app.services import studio_api_service

    db = SessionLocal()
    try:
        claimed, claim_stamp = claim_batch_drafts_for_promotion(db, limit=PROMOTION_LIMIT_PER_CYCLE)
    finally:
        db.close()

    by_batch: dict[tuple[str, str], list[str]] = {}
    for batch_job_id, owner_id, draft_id in claimed:
        by_batch.setdefault((batch_job_id, owner_id), []).append(draft_id)

    promoted = 0
    promoted_batches: list[str] = []
    for (batch_id, owner_id), draft_ids in by_batch.items():
        # 제출 직전 재확인: 우리가 느린 사이 다른 monitor가 lease를 가져갔다면
        # 그쪽이 이미 제출했을 수 있으므로 여기서 빠진다(SE-11 잔여 창).
        recheck_db = SessionLocal()
        try:
            draft_ids = still_owns_claim(recheck_db, draft_ids, claim_stamp)
        finally:
            recheck_db.close()
        if not draft_ids:
            continue
        try:
            studio_api_service.create_runpod_request_batch(
                {"workerId": owner_id, "items": [{"promptDraftId": draft_id} for draft_id in draft_ids]},
                user=_submitter_user(owner_id),
                batch_job_id=batch_id,
            )
        except Exception as exc:  # noqa: BLE001 - one bad batch must not stop the rest
            _PROMOTION_FAILURES[batch_id] = str(exc)
            release_db = SessionLocal()
            try:
                release_promotion_claim(release_db, draft_ids)
            finally:
                release_db.close()
            continue
        _PROMOTION_FAILURES.pop(batch_id, None)
        promoted += len(draft_ids)
        promoted_batches.append(batch_id)

    return {"promoted": promoted, "batches": promoted_batches}
```

- [ ] **Step 6: 테스트 통과 + 회귀 확인**

Run:
```bash
python3 -m pytest backend/tests/test_batch_job_service.py -rf
python3 -m pytest backend/tests/test_durable_runpod_request_batch.py backend/tests/test_runpod_submission_queue.py backend/tests/test_prompt_batch_service.py -rf
python3 -m compileall -q backend/app
rm -f /tmp/batch_mig_check.db
DATABASE_URL=sqlite:////tmp/batch_mig_check.db python3 -m alembic upgrade head
DATABASE_URL=sqlite:////tmp/batch_mig_check.db python3 -m alembic downgrade -1
DATABASE_URL=sqlite:////tmp/batch_mig_check.db python3 -m alembic upgrade head
```
Expected: 전부 PASS / exit 0

- [ ] **Step 7: 커밋**

```bash
git add backend/app/db/migrations/versions/20260904_0033_batch_jobs.py backend/app/db/models.py backend/app/services/batch_job_service.py backend/tests/test_batch_job_service.py
git commit -m "fix(batch): claim drafts atomically and cap promotion per cycle"
```

---

## Task R-E: 고아 request item 복구와 잔여 기반 완료 판정 (G-15 · SE-17)

**Files:**
- Modify: `backend/app/services/batch_job_service.py`
- Modify: `backend/app/main.py` (monitor 단계 추가)
- Test: `backend/tests/test_batch_job_service.py`

**이 태스크는 배치만의 문제가 아니다.** `create_runpod_request_batch()`가 request item을 commit한 뒤
항목마다 task를 만드는 2단계 구조는 **기존 대화형 경로에도 있다**(`studio_api_service.py:487-506`).
프로세스가 그 사이에 죽으면 `task_id IS NULL`인 item이 남고, 예외가 아닌 강제 종료라 실패 표시조차 없다.
복구기는 대화형 경로도 함께 고친다 — 리뷰 시 반드시 대화형 회귀망을 함께 돌린다.

**Interfaces:**
- Produces: `STALE_ORPHAN_ITEM_SECONDS = 300`, `MAX_MATERIALIZE_ATTEMPTS = 3`
- Produces: `materialize_orphan_request_items() -> dict` — 반환 `{"materialized": int, "failed": int}`
- Produces: `_batch_is_settled(db, batch) -> bool` — Task 4의 완료 판정이 이것을 쓴다

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_orphan_request_item_gets_its_task_created(db_session, monkeypatch):
    """SE-17: item만 commit되고 task 생성 전에 죽은 경우를 복구한다."""
    db_session.add(_user("operator_1"))
    _seed_assets(db_session, 1)
    monkeypatch.setattr(prompt_batch_service, "active_instruction_text", lambda _: ("instruction", "wf@1"))
    created = batch_job_service.create_batch_job(
        db_session,
        {"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": _asset_items(1)},
        created_by="operator_1",
    )
    draft = db_session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])).one()
    draft.status = "READY"
    draft.positive_prompt = "ok"
    request_batch = RunpodRequestBatch(
        id="rpb_orphan", workflow_id="Blowbang1.json", requested_count=1, status="QUEUED",
        created_by="operator_1", batch_job_id=created["id"],
    )
    db_session.add(request_batch)
    db_session.add(RunpodRequestItem(
        id="rpi_orphan", request_batch_id=request_batch.id, sequence_no=1,
        prompt_draft_id=draft.id, asset_id=draft.asset_id, workflow_id="Blowbang1.json",
        positive_prompt="ok", requested_frames=81, status="PENDING_SUBMIT",
        task_id=None,  # 프로세스가 여기서 죽었다
        created_at=datetime.utcnow() - timedelta(seconds=batch_job_service.STALE_ORPHAN_ITEM_SECONDS + 60),
    ))
    db_session.commit()

    result = batch_job_service.materialize_orphan_request_items()

    db_session.expire_all()
    item = db_session.get(RunpodRequestItem, "rpi_orphan")
    assert result["materialized"] == 1
    assert item.task_id is not None, "고아 item의 task가 만들어지지 않아 배치가 영구 대기한다"


def test_recent_orphan_items_are_left_alone(db_session, monkeypatch):
    """정상 생성 중인 item을 복구기가 가로채면 안 된다."""
    # 위와 같은 준비를 하되 created_at을 now로 둔다.
    ...  # 위 테스트에서 created_at만 datetime.utcnow()로 바꿔 복제한다
    assert batch_job_service.materialize_orphan_request_items()["materialized"] == 0


def test_orphan_item_is_failed_after_the_attempt_limit(db_session, monkeypatch):
    """복구가 반복 실패하면 item을 FAILED로 확정해 배치가 종료될 수 있게 한다."""
    # materialize 내부의 task 생성을 항상 raise 하도록 monkeypatch 하고
    # MAX_MATERIALIZE_ATTEMPTS 회 호출한 뒤 item.status == "FAILED" 를 확인한다.
    ...


def test_batch_settles_even_when_an_item_never_became_a_task(db_session, monkeypatch):
    """G-15: 완료 판정이 두 모집단의 동등성이 아니라 잔여 검사여야 한다."""
    # draft 2건 모두 READY, item 2건 중 1건은 COMPLETED task, 1건은 FAILED(task 없음).
    # 이전 판정식(promptReady == videoRequested)이면 영원히 INCOMPLETE였다.
    batch_job_service.refresh_batch_job_counters()
    db_session.expire_all()
    assert db_session.get(BatchJob, batch_id).status == "COMPLETE"
```

`...`로 둔 두 테스트는 위 첫 테스트의 준비 코드를 복제해 해당 조건만 바꿔 완성한다.
`from datetime import datetime, timedelta` 를 테스트 파일 import에 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -rf -k "orphan or settles"`
Expected: FAIL — `materialize_orphan_request_items`가 없어 `AttributeError`

- [ ] **Step 3: 복구기 구현**

`backend/app/services/batch_job_service.py`에 추가한다. R-D의 lease와 같은 사고방식이다 —
"충분히 오래됐고, 실제로는 일어나지 않았음"을 확인한 뒤에만 개입한다:

```python
STALE_ORPHAN_ITEM_SECONDS = 300
MAX_MATERIALIZE_ATTEMPTS = 3


def materialize_orphan_request_items() -> dict[str, Any]:
    """Create the WorkflowTask for request items whose creation loop died.

    create_runpod_request_batch() commits its items, then creates one task per
    item. A container killed between those two steps leaves items that no code
    path will ever pick up: the dispatcher only claims tasks, and the failure
    handler only runs on an exception, not on SIGKILL. Those items then pin
    their batch open forever.

    This also repairs the interactive path, which has the same two-phase gap.
    """
    from backend.app.services import studio_api_service
    from backend.app.services.runpod_request_batch_service import attach_task_to_request_item, mark_request_item_failed

    cutoff = datetime.utcnow() - timedelta(seconds=STALE_ORPHAN_ITEM_SECONDS)
    db = SessionLocal()
    try:
        orphans = db.execute(
            select(RunpodRequestItem.id, RunpodRequestBatch.created_by)
            .join(RunpodRequestBatch, RunpodRequestBatch.id == RunpodRequestItem.request_batch_id)
            .where(
                RunpodRequestItem.task_id.is_(None),
                RunpodRequestItem.status == "PENDING_SUBMIT",
                RunpodRequestItem.created_at <= cutoff,
            )
            .order_by(RunpodRequestItem.created_at.asc())
            .limit(PROMOTION_LIMIT_PER_CYCLE)
        ).all()
    finally:
        db.close()

    materialized = 0
    failed = 0
    for item_id, owner_id in orphans:
        try:
            job_payload = studio_api_service.job_payload_from_request_item(
                item_id, user={"id": owner_id}, worker_id=owner_id
            )
            job = studio_api_service.create_job(job_payload, user=_submitter_user(owner_id))
            link_db = SessionLocal()
            try:
                attach_task_to_request_item(link_db, item_id=item_id, task_id=job["taskId"])
            finally:
                link_db.close()
            materialized += 1
        except Exception as exc:  # noqa: BLE001
            attempts = _MATERIALIZE_ATTEMPTS.get(item_id, 0) + 1
            _MATERIALIZE_ATTEMPTS[item_id] = attempts
            if attempts >= MAX_MATERIALIZE_ATTEMPTS:
                # 무한 재시도로 배치를 영구 대기시키느니, 실패로 확정해 종료시킨다.
                fail_db = SessionLocal()
                try:
                    mark_request_item_failed(fail_db, item_id=item_id, message=f"복구 {attempts}회 실패: {exc}")
                finally:
                    fail_db.close()
                _MATERIALIZE_ATTEMPTS.pop(item_id, None)
                failed += 1
    return {"materialized": materialized, "failed": failed}
```

모듈 상단에 `_MATERIALIZE_ATTEMPTS: dict[str, int] = {}`를 둔다. `_PROMOTION_FAILURES`와 마찬가지로
프로세스 로컬이며, 재시작 시 초기화되어 다시 3회를 시도한다 — 그 편이 영구 실패보다 안전하다.

`studio_api_service`에 `create_job`이 모듈 레벨로 노출돼 있지 않으면, `create_runpod_request_batch`가
쓰는 것과 같은 import 경로를 찾아 맞춘다:

Run: `grep -n "^from\|^import\|def create_job" backend/app/services/studio_api_service.py | grep -i "create_job"`

- [ ] **Step 4: 완료 판정을 잔여 검사로 바꾼다**

`batch_job_service.py`에 추가한다. Task 4의 `refresh_batch_job_counters()`가 이 함수를 쓴다:

```python
NON_TERMINAL_ITEM_STATES = frozenset({"PENDING_SUBMIT", "DISPATCHING", "QUEUED", "IN_QUEUE", "IN_PROGRESS", "RUNNING"})


def _batch_is_settled(db: Session, batch: BatchJob) -> bool:
    """A batch is done when nothing is left running — not when two counts match.

    The earlier formula compared two independently maintained populations
    (`promptReady == videoRequested`). Any gap between them — an item whose task
    never materialized, a draft counted differently — froze the batch forever.
    Asking "is anything still in flight?" cannot drift.
    """
    pending_drafts = db.scalar(
        select(func.count())
        .select_from(ImagePromptDraft)
        .where(
            ImagePromptDraft.batch_job_id == batch.id,
            ImagePromptDraft.status.notin_(TERMINAL_DRAFT_STATES),
        )
    ) or 0
    if pending_drafts:
        return False

    pending_items = db.scalar(
        select(func.count())
        .select_from(RunpodRequestItem)
        .join(RunpodRequestBatch, RunpodRequestBatch.id == RunpodRequestItem.request_batch_id)
        .where(
            RunpodRequestBatch.batch_job_id == batch.id,
            RunpodRequestItem.status.in_(NON_TERMINAL_ITEM_STATES),
        )
    ) or 0
    return pending_items == 0
```

`runpod_request_items.status`는 `runpod_request_batch_service.refresh_request_batch_summary()`가
task로부터 이미 동기화하고 있으므로 새로 유지할 상태가 아니다.

- [ ] **Step 5: monitor에 복구 단계 추가**

`backend/app/main.py`의 `monitor_loop`, 배치 승격 단계 **다음**에 넣는다.
G-3에 따라 독립 try/except로 감싼다:

```python
                try:
                    await asyncio.to_thread(materialize_orphan_request_items)
                except Exception:
                    LOGGER.exception("Orphan request item recovery failed")
```

import에 `materialize_orphan_request_items`를 추가한다.

- [ ] **Step 6: 테스트 통과 + 대화형 회귀 확인**

Run:
```bash
python3 -m pytest backend/tests/test_batch_job_service.py -rf
python3 -m pytest backend/tests/test_durable_runpod_request_batch.py backend/tests/test_runpod_submission_queue.py -rf
python3 -m compileall -q backend/app
```
Expected: 전부 PASS. 두 번째 명령이 중요하다 — 복구기는 대화형 경로의 item에도 작동하므로,
정상 흐름의 item을 가로채지 않는지 여기서 확인된다.

- [ ] **Step 7: 커밋 — 반드시 두 개로 나눈다**

복구기는 **대화형 경로의 기존 결함도 고치므로 배치와 독립적인 가치가 있다.** 배치 기능이 지연되거나
축소되면 복구기만 main으로 cherry-pick할 수 있어야 하므로, 완료 판정식과 섞지 않는다:

```bash
# 1) 공유 결함 수정 — 단독으로 cherry-pick 가능해야 한다
git add backend/app/services/batch_job_service.py backend/app/main.py backend/tests/test_batch_job_service.py
git commit -m "fix(runpod): materialize request items whose task creation died

create_runpod_request_batch commits its items, then creates one task per item.
A process killed between those steps leaves items no code path picks up —
the dispatcher only claims tasks, and the failure handler only runs on an
exception, not on SIGKILL. This affects the interactive request screen too,
not just batch jobs."

# 2) 배치 전용 — 완료 판정식
git add backend/app/services/batch_job_service.py backend/tests/test_batch_job_service.py
git commit -m "fix(batch): settle batches on remainder instead of count equality"
```

> **분리 여부 결정 (2026-09-04):** 재작업 R-A~R-E를 별도 선행 브랜치로 떼지 않는다.
> 다섯 중 넷(R-A·R-B·R-C·R-D)이 배치 전용이고 — `promote_ready_batch_drafts`는 배치에만 존재하며,
> `create_prompt_generation_batch`의 `commit=False`와 `create_runpod_request_batch`의
> `batch_job_id`는 기본값으로 기존 호출자를 바꾸지 않는다 — `batch_job_id` 컬럼은 이미 이 브랜치에
> 커밋돼 있어 분리 비용만 든다. 진짜 공유 가치가 있는 것은 이 복구기 하나뿐이므로,
> 브랜치를 쪼개는 대신 **커밋을 쪼개** cherry-pick 가능성만 확보한다.

---

## Task 4: 카운터 · 상태 판정 · 조회

**Files:**
- Modify: `backend/app/services/batch_job_service.py`
- Test: `backend/tests/test_batch_job_service.py` (추가)

**Interfaces:**
- Consumes: Task 3의 `promote_ready_batch_drafts`
- Produces:
  - `refresh_batch_job_counters() -> dict` — 반환 `{"refreshed": int, "completed": int}`

> **주의:** `promote_ready_batch_drafts()`가 반환하는 `promoted`는 파이프라인에 **넘긴** draft 수이며,
> 넘긴 뒤 파이프라인 내부에서 실패한 항목도 포함한다. `video_requested_count`는 이 반환값이 아니라
> `workflow_tasks` 실제 행에서 세야 한다(`_counts_for()`가 그렇게 한다).
  - `list_active_batch_jobs(db: Session, *, created_by: str | None) -> dict` — 반환 `{"items": [batch payload + {"promptWaiting": int, "promptGenerating": int, "runpodPendingSubmit": int, "runpodQueued": int, "runpodInProgress": int}]}`
  - `list_batch_jobs(db, *, created_by: str | None, page: int, date_from: str | None, date_to: str | None, worker_id: str | None, status: str | None) -> dict` — 반환 `{"items": [...], "page": int, "pageSize": 10, "total": int, "workers": [{"workerId": str, "workerName": str}]}`

- [ ] **Step 1: 실패 테스트 작성**

```python
TERMINAL_TASK_STATES = ("COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT")


def test_batch_stays_incomplete_while_a_task_runs(db_session, operator_user, seeded_assets, make_batch_with_tasks):
    batch_id = make_batch_with_tasks(draft_states=["READY", "READY"], task_states=["COMPLETED", "IN_PROGRESS"])
    batch_job_service.refresh_batch_job_counters()
    db_session.expire_all()
    assert db_session.get(BatchJob, batch_id).status == "INCOMPLETE"


def test_batch_completes_when_every_task_is_terminal(db_session, operator_user, seeded_assets, make_batch_with_tasks):
    batch_id = make_batch_with_tasks(draft_states=["READY", "READY"], task_states=["COMPLETED", "FAILED"])
    batch_job_service.refresh_batch_job_counters()
    db_session.expire_all()
    batch = db_session.get(BatchJob, batch_id)
    assert batch.status == "COMPLETE"
    assert batch.video_completed_count == 1
    assert batch.video_failed_count == 1


def test_failed_prompts_alone_complete_the_batch(db_session, operator_user, seeded_assets, make_batch_with_tasks):
    """요구사항 8: 실패도 종료로 본다."""
    batch_id = make_batch_with_tasks(draft_states=["FAILED", "FAILED"], task_states=[])
    batch_job_service.refresh_batch_job_counters()
    db_session.expire_all()
    batch = db_session.get(BatchJob, batch_id)
    assert batch.status == "COMPLETE"
    assert batch.prompt_failed_count == 2


def test_active_list_excludes_completed_batches(db_session, operator_user, seeded_assets, make_batch_with_tasks):
    """요구사항 9: 대시보드는 미완료만."""
    done = make_batch_with_tasks(draft_states=["READY"], task_states=["COMPLETED"])
    running = make_batch_with_tasks(draft_states=["READY"], task_states=["IN_PROGRESS"])
    batch_job_service.refresh_batch_job_counters()
    db_session.expire_all()
    ids = {item["id"] for item in batch_job_service.list_active_batch_jobs(db_session, created_by=None)["items"]}
    assert running in ids
    assert done not in ids


def test_list_batch_jobs_paginates_by_ten(db_session, operator_user, seeded_assets, make_batch_with_tasks):
    """요구사항 12: 10건 단위."""
    for _ in range(12):
        make_batch_with_tasks(draft_states=["READY"], task_states=["COMPLETED"])
    page_one = batch_job_service.list_batch_jobs(db_session, created_by=None, page=1, date_from=None, date_to=None, worker_id=None, status=None)
    page_two = batch_job_service.list_batch_jobs(db_session, created_by=None, page=2, date_from=None, date_to=None, worker_id=None, status=None)
    assert page_one["pageSize"] == 10
    assert len(page_one["items"]) == 10
    assert page_one["total"] >= 12
    assert len(page_two["items"]) >= 2


def test_list_batch_jobs_status_filter(db_session, operator_user, seeded_assets, make_batch_with_tasks):
    make_batch_with_tasks(draft_states=["READY"], task_states=["COMPLETED"])
    make_batch_with_tasks(draft_states=["READY"], task_states=["IN_PROGRESS"])
    batch_job_service.refresh_batch_job_counters()
    only_done = batch_job_service.list_batch_jobs(db_session, created_by=None, page=1, date_from=None, date_to=None, worker_id=None, status="COMPLETE")
    assert {item["status"] for item in only_done["items"]} == {"COMPLETE"}


def test_list_batch_jobs_isolates_non_managers(db_session, operator_user, other_user, seeded_assets, make_batch_with_tasks):
    mine = make_batch_with_tasks(draft_states=["READY"], task_states=["COMPLETED"], owner=operator_user.id)
    theirs = make_batch_with_tasks(draft_states=["READY"], task_states=["COMPLETED"], owner=other_user.id)
    scoped = batch_job_service.list_batch_jobs(db_session, created_by=operator_user.id, page=1, date_from=None, date_to=None, worker_id=None, status=None)
    ids = {item["id"] for item in scoped["items"]}
    assert mine in ids
    assert theirs not in ids
```

`make_batch_with_tasks` 픽스처를 `backend/tests/test_batch_job_service.py` 상단에 정의한다:

```python
@pytest.fixture
def make_batch_with_tasks(db_session, operator_user, seeded_assets):
    """Build a batch whose drafts and tasks are already in the requested states."""
    from backend.app.db.models import RunpodRequestBatch, RunpodRequestItem, WorkflowTask

    def _make(*, draft_states: list[str], task_states: list[str], owner: str | None = None) -> str:
        owner_id = owner or operator_user.id
        created = batch_job_service.create_batch_job(
            db_session,
            {
                "workflowId": "Blowbang1.json",
                "sourceDirName": "d",
                "requestedFrames": 81,
                "items": _asset_items(len(draft_states)),
            },
            created_by=owner_id,
        )
        drafts = db_session.scalars(
            select(ImagePromptDraft).where(ImagePromptDraft.batch_job_id == created["id"])
        ).all()
        for draft, state in zip(drafts, draft_states):
            draft.status = state
            if state == "READY":
                draft.positive_prompt = "ok"
        if task_states:
            request_batch = RunpodRequestBatch(
                id=f"rpb_{uuid.uuid4().hex[:16]}",
                workflow_id="Blowbang1.json",
                requested_count=len(task_states),
                status="QUEUED",
                created_by=owner_id,
                batch_job_id=created["id"],
            )
            db_session.add(request_batch)
            for index, state in enumerate(task_states, start=1):
                task = WorkflowTask(
                    id=f"task_{uuid.uuid4().hex[:16]}",
                    workflow_id="Blowbang1.json",
                    status=state,
                    user_id=owner_id,
                    batch_job_id=created["id"],
                    request_batch_id=request_batch.id,
                )
                db_session.add(task)
                db_session.add(RunpodRequestItem(
                    id=f"rpi_{uuid.uuid4().hex[:16]}",
                    request_batch_id=request_batch.id,
                    sequence_no=index,
                    prompt_draft_id=drafts[index - 1].id,
                    asset_id=drafts[index - 1].asset_id,
                    workflow_id="Blowbang1.json",
                    positive_prompt="ok",
                    requested_frames=81,
                    status=state,
                    task_id=task.id,
                ))
        db_session.commit()
        return created["id"]

    return _make
```

`WorkflowTask`의 필수 컬럼이 위와 다르면 먼저 확인해 채운다:

Run: `python3 -c "from backend.app.db.models import WorkflowTask; print([c.name for c in WorkflowTask.__table__.columns if not c.nullable and c.default is None and not c.primary_key])"`

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -q -k "counter or active_list or list_batch or complete"`
Expected: FAIL — `AttributeError: ... 'refresh_batch_job_counters'`

- [ ] **Step 3: 구현**

`backend/app/services/batch_job_service.py`에 추가한다. import에 `from datetime import datetime`, `from sqlalchemy import func`, `from backend.app.db.models import WorkflowTask`를 더한다.

```python
# 이 두 집합은 backend/app/services/task_tracking_service.py:29 의
# TERMINAL_STATES = {"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"} 와
# 일치해야 한다. 이 저장소는 "SUCCESS"를 완료로 취급하는 곳이 여러 군데다
# (task_tracking_service.py:198·1383, job_service.py:278, db_adapter.py:43).
# SUCCESS를 빠뜨리면 그 상태로 끝난 task가 종료로 집계되지 않아 배치가
# 영원히 INCOMPLETE에 머물고 대시보드에서 사라지지 않는다(요구사항 8·9 위반).
# "PARTIAL_FAILED"는 task가 아니라 RunpodRequestBatch의 상태이므로
# (runpod_request_batch_service.py:492) task 상태 집합에 넣지 않는다.
TERMINAL_TASK_STATES = frozenset({"COMPLETED", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"})
SUCCESS_TASK_STATES = frozenset({"COMPLETED", "SUCCESS"})
TERMINAL_DRAFT_STATES = frozenset({"READY", "FAILED", "MANUAL_REQUIRED"})
FAILED_DRAFT_STATES = frozenset({"FAILED", "MANUAL_REQUIRED"})
PAGE_SIZE = 10


def refresh_batch_job_counters() -> dict[str, Any]:
    """Recompute denormalized counters and completion state for open batches."""
    db = SessionLocal()
    refreshed = 0
    completed = 0
    try:
        batches = db.scalars(select(BatchJob).where(BatchJob.status == BATCH_JOB_INCOMPLETE)).all()
        for batch in batches:
            counts = _counts_for(db, batch.id)
            batch.prompt_completed_count = counts["promptReady"]
            batch.prompt_failed_count = counts["promptFailed"]
            batch.video_requested_count = counts["videoRequested"]
            batch.video_completed_count = counts["videoCompleted"]
            batch.video_failed_count = counts["videoFailed"]
            # G-13: 대시보드가 읽을 단계별 값도 여기서 저장한다. 조회 경로는
            # 이 컬럼들을 SELECT만 하고 GROUP BY를 다시 돌지 않는다.
            batch.prompt_waiting_count = counts["promptWaiting"]
            batch.prompt_generating_count = counts["promptGenerating"]
            batch.runpod_pending_submit_count = counts["videoPendingSubmit"]
            batch.runpod_queued_count = counts["videoQueued"]
            batch.runpod_in_progress_count = counts["videoInProgress"]
            # G-15: 두 모집단의 동등성(promptReady == videoRequested)이 아니라
            # 잔여 검사를 쓴다. 동등성은 어느 한쪽에 틈이 생기면 배치를 영구
            # 고착시켰다(SE-17). R-E에서 정의한다.
            if _batch_is_settled(db, batch):
                batch.status = BATCH_JOB_COMPLETE
                completed += 1
            refreshed += 1
        db.commit()
    finally:
        db.close()
    return {"refreshed": refreshed, "completed": completed}


def _counts_for(db: Session, batch_job_id: str) -> dict[str, int]:
    draft_rows = db.execute(
        select(ImagePromptDraft.status, func.count())
        .where(ImagePromptDraft.batch_job_id == batch_job_id)
        .group_by(ImagePromptDraft.status)
    ).all()
    task_rows = db.execute(
        select(WorkflowTask.status, func.count())
        .where(WorkflowTask.batch_job_id == batch_job_id, WorkflowTask.deleted_at.is_(None))
        .group_by(WorkflowTask.status)
    ).all()
    drafts = {str(status).upper(): int(total) for status, total in draft_rows}
    tasks = {str(status).upper(): int(total) for status, total in task_rows}
    return {
        "promptWaiting": drafts.get("PENDING", 0),
        "promptGenerating": drafts.get("GENERATING", 0),
        "promptReady": drafts.get("READY", 0),
        "promptFailed": sum(drafts.get(state, 0) for state in FAILED_DRAFT_STATES),
        "promptTerminal": sum(drafts.get(state, 0) for state in TERMINAL_DRAFT_STATES),
        "videoRequested": sum(tasks.values()),
        "videoPendingSubmit": tasks.get("PENDING_SUBMIT", 0) + tasks.get("DISPATCHING", 0),
        "videoQueued": tasks.get("QUEUED", 0) + tasks.get("IN_QUEUE", 0),
        "videoInProgress": tasks.get("IN_PROGRESS", 0) + tasks.get("RUNNING", 0),
        "videoCompleted": sum(tasks.get(state, 0) for state in SUCCESS_TASK_STATES),
        "videoFailed": sum(tasks.get(state, 0) for state in TERMINAL_TASK_STATES - SUCCESS_TASK_STATES),
        "videoTerminal": sum(tasks.get(state, 0) for state in TERMINAL_TASK_STATES),
    }


def list_active_batch_jobs(db: Session, *, created_by: str | None) -> dict[str, Any]:
    """Rows for the two incomplete-only dashboards (요구사항 9).

    Reads only the denormalized counters (G-13). This runs on a 3-second screen
    poll for every open batch; recomputing the GROUP BYs here would defeat the
    counters that refresh_batch_job_counters() exists to maintain.
    """
    query = select(BatchJob).where(BatchJob.status == BATCH_JOB_INCOMPLETE)
    if created_by:
        query = query.where(BatchJob.created_by == created_by)
    batches = db.scalars(query.order_by(BatchJob.created_at.desc())).all()
    return {"items": [_batch_payload(db, batch) for batch in batches]}


def list_batch_jobs(
    db: Session,
    *,
    created_by: str | None,
    page: int = 1,
    date_from: str | None = None,
    date_to: str | None = None,
    worker_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Batch history with 일자/작업자/상태 filters, 10 rows per page (요구사항 12)."""
    query = select(BatchJob)
    if created_by:
        query = query.where(BatchJob.created_by == created_by)
    elif worker_id:
        query = query.where(BatchJob.created_by == worker_id)
    if status:
        query = query.where(BatchJob.status == status.upper())
    parsed_from = _parse_date(date_from)
    if parsed_from:
        query = query.where(BatchJob.created_at >= parsed_from)
    parsed_to = _parse_date(date_to, end_of_day=True)
    if parsed_to:
        query = query.where(BatchJob.created_at <= parsed_to)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    safe_page = max(1, int(page or 1))
    rows = db.scalars(
        query.order_by(BatchJob.created_at.desc(), BatchJob.id.desc())
        .offset((safe_page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    worker_rows = db.execute(
        select(BatchJob.created_by, User.name)
        .join(User, User.id == BatchJob.created_by, isouter=True)
        .where(BatchJob.created_by.is_not(None))
        .group_by(BatchJob.created_by, User.name)
    ).all()
    return {
        "items": [_batch_payload(db, row) for row in rows],
        "page": safe_page,
        "pageSize": PAGE_SIZE,
        "total": int(total),
        "workers": [
            {"workerId": str(worker_id), "workerName": str(name or worker_id)}
            for worker_id, name in worker_rows
        ],
    }


def _parse_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if end_of_day and len(text) == 10:
        return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_service.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/batch_job_service.py backend/tests/test_batch_job_service.py
git commit -m "feat(batch): add batch counters, completion state and queries"
```

---

## Task 5: 가드레일 G-1 — 공정 스케줄링

**Files:**
- Modify: `backend/app/services/prompt_batch_service.py:89-93` (main 기준)
- Modify: `backend/app/services/task_tracking_service.py:510-519` (main 기준)
- Test: `backend/tests/test_batch_fair_scheduling.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `batch_job_id` 컬럼
- Produces: 동작 변경만. 공개 시그니처 무변경 — `process_next_prompt_generation_draft()`, `claim_next_pending_submission()`

**왜 필요한가:** SE-1 참조. 이 태스크가 없으면 128장 배치 한 번이 다른 모든 사용자의 프롬프트 생성을 11분 넘게 막는다.

- [ ] **Step 1: 실패 테스트 작성**

Create `backend/tests/test_batch_fair_scheduling.py`:

```python
"""G-1: bulk batch work must never starve interactive single-image work."""
from __future__ import annotations

from datetime import timedelta
import uuid

from sqlalchemy import select

from backend.app.db.models import ImagePromptDraft, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services.prompt_batch_service import process_next_prompt_generation_draft
from backend.app.services.task_tracking_service import claim_next_pending_submission


def _draft(session, *, created_at, batch_job_id, asset_id, owner):
    draft = ImagePromptDraft(
        id=f"grok_draft_{uuid.uuid4().hex[:16]}",
        asset_id=asset_id,
        workflow_id="Blowbang1.json",
        slot_index=1,
        status="PENDING",
        provider="grok",
        batch_job_id=batch_job_id,
        warnings_json=[],
        raw_json={},
        created_by=owner,
        created_at=created_at,
    )
    session.add(draft)
    return draft


def test_interactive_draft_is_picked_before_older_batch_drafts(monkeypatch, operator_user, seeded_assets, frozen_now):
    """배치 128건이 먼저 들어와 있어도 뒤에 온 단건이 먼저 처리된다."""
    session = SessionLocal()
    try:
        for offset in range(5):
            _draft(
                session,
                created_at=frozen_now - timedelta(minutes=10) + timedelta(seconds=offset),
                batch_job_id="batch_older",
                asset_id=seeded_assets[0],
                owner=operator_user.id,
            )
        interactive = _draft(
            session,
            created_at=frozen_now,
            batch_job_id=None,
            asset_id=seeded_assets[0],
            owner=operator_user.id,
        )
        session.commit()
        interactive_id = interactive.id
    finally:
        session.close()

    picked: list[str] = []
    monkeypatch.setattr(
        "backend.app.services.prompt_batch_service._process_draft",
        lambda db, draft: picked.append(draft.id) or {"draftId": draft.id},
    )

    process_next_prompt_generation_draft()

    assert picked == [interactive_id]


def test_batch_drafts_keep_fifo_among_themselves(monkeypatch, operator_user, seeded_assets, frozen_now):
    session = SessionLocal()
    try:
        first = _draft(session, created_at=frozen_now - timedelta(minutes=2), batch_job_id="b1", asset_id=seeded_assets[0], owner=operator_user.id)
        _draft(session, created_at=frozen_now - timedelta(minutes=1), batch_job_id="b1", asset_id=seeded_assets[0], owner=operator_user.id)
        session.commit()
        first_id = first.id
    finally:
        session.close()

    picked: list[str] = []
    monkeypatch.setattr(
        "backend.app.services.prompt_batch_service._process_draft",
        lambda db, draft: picked.append(draft.id) or {"draftId": draft.id},
    )

    process_next_prompt_generation_draft()

    assert picked == [first_id]


def test_ordering_is_unchanged_when_no_batch_work_exists(monkeypatch, operator_user, seeded_assets, frozen_now):
    """배치가 하나도 없으면 기존 FIFO와 완전히 같아야 한다."""
    session = SessionLocal()
    try:
        oldest = _draft(session, created_at=frozen_now - timedelta(minutes=3), batch_job_id=None, asset_id=seeded_assets[0], owner=operator_user.id)
        _draft(session, created_at=frozen_now - timedelta(minutes=1), batch_job_id=None, asset_id=seeded_assets[0], owner=operator_user.id)
        session.commit()
        oldest_id = oldest.id
    finally:
        session.close()

    picked: list[str] = []
    monkeypatch.setattr(
        "backend.app.services.prompt_batch_service._process_draft",
        lambda db, draft: picked.append(draft.id) or {"draftId": draft.id},
    )

    process_next_prompt_generation_draft()

    assert picked == [oldest_id]


def test_interactive_task_is_dispatched_before_older_batch_tasks(operator_user, frozen_now):
    session = SessionLocal()
    try:
        for offset in range(3):
            session.add(WorkflowTask(
                id=f"task_{uuid.uuid4().hex[:16]}",
                workflow_id="Blowbang1.json",
                status="PENDING_SUBMIT",
                user_id=operator_user.id,
                batch_job_id="batch_older",
                created_at=frozen_now - timedelta(minutes=10) + timedelta(seconds=offset),
            ))
        interactive_id = f"task_{uuid.uuid4().hex[:16]}"
        session.add(WorkflowTask(
            id=interactive_id,
            workflow_id="Blowbang1.json",
            status="PENDING_SUBMIT",
            user_id=operator_user.id,
            batch_job_id=None,
            created_at=frozen_now,
        ))
        session.commit()
    finally:
        session.close()

    claimed = claim_next_pending_submission()

    assert claimed is not None
    assert claimed["taskId"] == interactive_id
```

`frozen_now`, `seeded_assets` 픽스처가 `conftest.py`에 없으면 이 파일 안에 정의한다:

```python
import pytest
from backend.app.core.timezone_utils import now_seoul_naive


@pytest.fixture
def frozen_now():
    return now_seoul_naive()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_fair_scheduling.py -q`
Expected: FAIL — 배치 draft가 먼저 뽑혀 `assert picked == [interactive_id]` 실패

- [ ] **Step 3: 프롬프트 큐 정렬 변경**

`backend/app/services/prompt_batch_service.py:89-93`(main)의 `select`를 바꾼다. 바로 아래 `process_prompt_generation_batch()`에도 비슷한 `select`가 있으니 **`process_next_prompt_generation_draft()` 안의 것만** 고친다:

```python
        draft = db.scalar(
            select(ImagePromptDraft)
            .where(ImagePromptDraft.status == DRAFT_PENDING)
            # G-1: 배치는 대량·비대화형 작업이다. 배치가 아닌 단건 요청을 항상
            # 먼저 처리해, 128장 배치 하나가 다른 사용자의 프롬프트 생성을
            # 수십 분 막는 일(SE-1)을 구조적으로 막는다. SQL에서 False < True.
            .order_by(
                ImagePromptDraft.batch_job_id.is_not(None).asc(),
                ImagePromptDraft.created_at.asc(),
                ImagePromptDraft.id.asc(),
            )
            .limit(1)
        )
```

- [ ] **Step 4: RunPod 제출 큐 정렬 변경**

`backend/app/services/task_tracking_service.py:510-519`(main)의 `candidate_ids` 쿼리를 바꾼다. main에는 바로 위에 `_recover_stale_dispatching_submissions(session, now)` 호출이 있다 — **그 줄은 건드리지 않는다**:

```python
        candidate_ids = list(session.scalars(
            select(WorkflowTask.id)
            .where(
                WorkflowTask.deleted_at.is_(None),
                WorkflowTask.status == "PENDING_SUBMIT",
                or_(WorkflowTask.next_dispatch_at.is_(None), WorkflowTask.next_dispatch_at <= now),
            )
            # G-1: 프롬프트 큐와 같은 이유. 배치 제출이 대화형 제출 앞에 서지 않는다.
            .order_by(
                WorkflowTask.batch_job_id.is_not(None).asc(),
                WorkflowTask.created_at.asc(),
                WorkflowTask.id.asc(),
            )
            .limit(10)
        ))
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python3 -m pytest backend/tests/test_batch_fair_scheduling.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: 기존 큐 테스트 회귀 확인**

Run: `python3 -m pytest backend/tests/test_runpod_submission_queue.py backend/tests/test_durable_runpod_request_batch.py -q`
Expected: PASS. 실패하면 정렬 변경이 기존 계약을 깬 것이므로 되돌리고 원인을 보고한다.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/services/prompt_batch_service.py backend/app/services/task_tracking_service.py backend/tests/test_batch_fair_scheduling.py
git commit -m "fix(queue): prioritize interactive work over batch work in both queues"
```

---

## Task 6: ZIP 스트리밍 (G-2, G-4)

**Files:**
- Create: `backend/app/services/batch_zip_service.py`
- Test: `backend/tests/test_batch_zip_service.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `BatchJob`, Task 4의 `batch_job_service`
- Produces:
  - `zip_entry_name(source_file_name: str, used: set[str]) -> str` — 순수 함수. `image1.jpg` + 빈 set → `output/image1.mp4`. 중복 시 `output/image1-1.mp4`
  - `collect_batch_outputs(db: Session, batch_job_id: str, *, task_ids: list[str] | None) -> list[dict]` — 각 `{"assetId": str, "entryName": str}`
  - `stream_batch_zip(batch_job_id: str, *, task_ids: list[str] | None) -> tuple[Iterator[bytes], int]` — `(청크 생성기, 건너뛴 건수)`
  - `ZIP_RESPONSE_HEADERS: dict[str, str]` — `{"Content-Encoding": "identity"}` 포함

- [ ] **Step 1: 실패 테스트 작성**

Create `backend/tests/test_batch_zip_service.py`:

```python
"""Batch ZIP export: entry naming, output/ prefix and gzip bypass."""
from __future__ import annotations

import io
import zipfile

import pytest

from backend.app.services import batch_zip_service


def test_entry_name_uses_output_prefix_and_mp4_extension():
    assert batch_zip_service.zip_entry_name("image1.jpg", set()) == "output/image1.mp4"


def test_entry_name_indexes_duplicates():
    used: set[str] = set()
    first = batch_zip_service.zip_entry_name("image1.jpg", used)
    used.add(first)
    second = batch_zip_service.zip_entry_name("image1.png", used)
    used.add(second)
    third = batch_zip_service.zip_entry_name("image1.webp", used)
    assert first == "output/image1.mp4"
    assert second == "output/image1-1.mp4"
    assert third == "output/image1-2.mp4"


def test_entry_name_strips_path_separators():
    """압축 해제 시 상위 디렉토리로 빠져나가는 경로를 만들지 않는다."""
    assert batch_zip_service.zip_entry_name("../../etc/passwd.jpg", set()) == "output/passwd.mp4"


def test_zip_response_headers_bypass_gzip_middleware():
    """G-2: 이미 압축된 mp4를 GZipMiddleware가 다시 압축하지 못하게 한다."""
    assert batch_zip_service.ZIP_RESPONSE_HEADERS["Content-Encoding"] == "identity"


def test_stream_batch_zip_produces_a_readable_archive(batch_with_completed_outputs):
    batch_id = batch_with_completed_outputs["batchJobId"]
    chunks, skipped = batch_zip_service.stream_batch_zip(batch_id, task_ids=None)
    buffer = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buffer) as archive:
        names = sorted(archive.namelist())
        assert names == ["output/image1.mp4", "output/image2.mp4"]
        assert archive.read("output/image1.mp4") == batch_with_completed_outputs["bytesByName"]["image1.mp4"]
    assert skipped == 0


def test_stream_batch_zip_skips_missing_assets(batch_with_missing_output):
    chunks, skipped = batch_zip_service.stream_batch_zip(batch_with_missing_output, task_ids=None)
    buffer = io.BytesIO(b"".join(chunks))
    with zipfile.ZipFile(buffer) as archive:
        assert archive.namelist() == ["output/image1.mp4"]
    assert skipped == 1
```

두 픽스처는 같은 파일에 정의한다. 완료 task 2건 + 각각의 `TaskOutputAsset` + 실제 파일을 만든다. `TaskOutputAsset`의 컬럼을 먼저 확인한다:

Run: `python3 -c "from backend.app.db.models import TaskOutputAsset; print([c.name for c in TaskOutputAsset.__table__.columns])"`

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_zip_service.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.app.services.batch_zip_service`

- [ ] **Step 3: 구현**

Create `backend/app/services/batch_zip_service.py`:

```python
"""Stream a batch's finished videos as one ZIP archive.

The archive shape is the deliverable: unzipping into any folder yields an
`output/` directory named after each source image, which is exactly what the
batch spec asks for. Nothing is buffered whole — a 128-video batch is gigabytes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Asset, BatchJob, TaskOutputAsset, WorkflowTask
from backend.app.db.session import SessionLocal

OUTPUT_DIR = "output"
CHUNK_SIZE = 1024 * 1024
# GZipMiddleware compresses any response without a content-encoding header,
# regardless of media type. A ZIP of mp4 files gains nothing from gzip and
# costs CPU on every download, so we declare identity to opt out. (G-2)
ZIP_RESPONSE_HEADERS = {"Content-Encoding": "identity"}


def zip_entry_name(source_file_name: str, used: set[str]) -> str:
    """`image1.jpg` -> `output/image1.mp4`, colliding names get a `-N` suffix."""
    stem = Path(str(source_file_name or "video")).name
    stem = Path(stem).stem or "video"
    candidate = f"{OUTPUT_DIR}/{stem}.mp4"
    if candidate not in used:
        return candidate
    index = 1
    while f"{OUTPUT_DIR}/{stem}-{index}.mp4" in used:
        index += 1
    return f"{OUTPUT_DIR}/{stem}-{index}.mp4"


def collect_batch_outputs(db: Session, batch_job_id: str, *, task_ids: list[str] | None) -> list[dict]:
    """Completed tasks of a batch, paired with their ZIP entry name."""
    query = (
        select(WorkflowTask.id, TaskOutputAsset.asset_id, Asset.file_name)
        .join(TaskOutputAsset, TaskOutputAsset.task_id == WorkflowTask.id)
        .join(Asset, Asset.id == TaskOutputAsset.asset_id)
        .where(
            WorkflowTask.batch_job_id == batch_job_id,
            WorkflowTask.deleted_at.is_(None),
            # batch_job_service.SUCCESS_TASK_STATES 와 같은 집합이어야 한다.
            # "COMPLETED"만 보면 "SUCCESS"로 끝난 영상이 ZIP에서 통째로 빠진다.
            WorkflowTask.status.in_(batch_job_service.SUCCESS_TASK_STATES),
        )
        .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
    )
    if task_ids:
        query = query.where(WorkflowTask.id.in_(task_ids))

    source_names = _source_file_names(db, batch_job_id)
    used: set[str] = set()
    collected: list[dict] = []
    for task_id, asset_id, output_file_name in db.execute(query).all():
        # The deliverable is named after the INPUT image, not RunPod's output file.
        base_name = source_names.get(task_id) or output_file_name or task_id
        entry = zip_entry_name(base_name, used)
        used.add(entry)
        collected.append({"assetId": str(asset_id), "entryName": entry})
    return collected


def _source_file_names(db: Session, batch_job_id: str) -> dict[str, str]:
    from backend.app.db.models import TaskInputAsset

    rows = db.execute(
        select(WorkflowTask.id, Asset.file_name)
        .join(TaskInputAsset, TaskInputAsset.task_id == WorkflowTask.id)
        .join(Asset, Asset.id == TaskInputAsset.asset_id)
        .where(WorkflowTask.batch_job_id == batch_job_id)
        .order_by(TaskInputAsset.slot_index.asc())
    ).all()
    names: dict[str, str] = {}
    for task_id, file_name in rows:
        names.setdefault(str(task_id), str(file_name))
    return names


def stream_batch_zip(batch_job_id: str, *, task_ids: list[str] | None) -> tuple[Iterator[bytes], int]:
    """Return a chunk generator plus the number of entries that had no file."""
    from backend.app.services import studio_api_service

    db = SessionLocal()
    try:
        if db.get(BatchJob, batch_job_id) is None:
            raise ValueError("배치 작업을 찾을 수 없습니다.")
        entries = collect_batch_outputs(db, batch_job_id, task_ids=task_ids)
    finally:
        db.close()

    resolved: list[tuple[str, Path]] = []
    skipped = 0
    for entry in entries:
        try:
            # G-4: storage_backends exposes no read API; this is the same
            # resolver the /api/files/{assetId} route uses.
            _, path = studio_api_service.get_asset(entry["assetId"])
        except (KeyError, FileNotFoundError):
            skipped += 1
            continue
        if not path.exists():
            skipped += 1
            continue
        resolved.append((entry["entryName"], path))

    if not resolved:
        raise ValueError("내려받을 완료 영상이 없습니다.")

    def generate() -> Iterator[bytes]:
        buffer = _StreamBuffer()
        # ZIP_STORED: mp4 is already compressed, deflating only burns CPU.
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
            for entry_name, path in resolved:
                with archive.open(entry_name, mode="w") as target, path.open("rb") as source:
                    while True:
                        chunk = source.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        target.write(chunk)
                        yield from buffer.drain()
                yield from buffer.drain()
        yield from buffer.drain()

    return generate(), skipped


class _StreamBuffer:
    """Unseekable sink so zipfile emits data descriptors instead of rewinding."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        return None

    def drain(self) -> Iterator[bytes]:
        parts, self._parts = self._parts, []
        for part in parts:
            if part:
                yield part
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest backend/tests/test_batch_zip_service.py -q`
Expected: PASS. `zipfile`이 seek을 요구하며 실패하면 `_StreamBuffer`에 `def seekable(self) -> bool: return False`와 `def tell(self) -> int`를 추가한다 — `tell`은 지금까지 write한 바이트 누적을 반환해야 한다.

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/batch_zip_service.py backend/tests/test_batch_zip_service.py
git commit -m "feat(batch): stream batch outputs as an output/-prefixed zip"
```

---

## Task 7: API 라우터 + monitor_loop 배선 (G-3)

**Files:**
- Create: `backend/app/api/v1/batch_jobs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_batch_job_api.py` (신규)

**Interfaces:**
- Consumes: Task 2·4의 `batch_job_service`, Task 6의 `batch_zip_service`
- Produces: HTTP 엔드포인트 4개 — `POST /api/v1/batch-jobs`, `GET /api/v1/batch-jobs/active`, `GET /api/v1/batch-jobs`, `GET /api/v1/batch-jobs/{id}/download`

- [ ] **Step 1: 라우터 등록 관례 확인**

Run: `grep -n "include_router\|require_permission" backend/app/main.py backend/app/api/v1/jobs.py | head -20`

권한 두 개를 동시에 요구하는 의존성이 이미 있는지 확인한다:

Run: `grep -n "def require_permission\|def has_permission" -A 12 backend/app/core/security.py`

- [ ] **Step 2: 실패 테스트 작성**

Create `backend/tests/test_batch_job_api.py`:

```python
"""HTTP boundary for batch jobs: permissions, validation and isolation."""
from __future__ import annotations


def test_create_batch_job_requires_both_permissions(client, viewer_token, seeded_assets):
    response = client.post(
        "/api/v1/batch-jobs",
        json={"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 81, "items": [{"assetId": seeded_assets[0], "fileName": "image1.jpg"}]},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


def test_create_batch_job_rejects_bad_frames(client, operator_token, seeded_assets):
    response = client.post(
        "/api/v1/batch-jobs",
        json={"workflowId": "Blowbang1.json", "sourceDirName": "d", "requestedFrames": 100, "items": [{"assetId": seeded_assets[0], "fileName": "image1.jpg"}]},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 400


def test_create_batch_job_defaults_to_81_frames(client, operator_token, seeded_assets):
    response = client.post(
        "/api/v1/batch-jobs",
        json={"workflowId": "Blowbang1.json", "sourceDirName": "d", "items": [{"assetId": seeded_assets[0], "fileName": "image1.jpg"}]},
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 200
    assert response.json()["requestedFrames"] == 81
    assert response.json()["durationSeconds"] == 5


def test_batch_history_defaults_to_ten_per_page(client, operator_token):
    response = client.get("/api/v1/batch-jobs", headers={"Authorization": f"Bearer {operator_token}"})
    assert response.status_code == 200
    assert response.json()["pageSize"] == 10


def test_download_rejects_another_users_batch(client, operator_token, other_user_batch_id):
    response = client.get(
        f"/api/v1/batch-jobs/{other_user_batch_id}/download",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert response.status_code == 403
```

`client`, `operator_token`, `viewer_token` 픽스처가 `conftest.py`에 있는지 먼저 확인한다:

Run: `grep -n "^def \|^@pytest.fixture" backend/tests/conftest.py`

없으면 기존 API 테스트 파일이 어떻게 클라이언트를 만드는지 보고 같은 방식을 쓴다:

Run: `ls backend/tests && grep -rln "TestClient" backend/tests`

- [ ] **Step 3: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_job_api.py -q`
Expected: FAIL — 404 (라우트 없음)

- [ ] **Step 4: 라우터 구현**

Create `backend/app/api/v1/batch_jobs.py`:

```python
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.core.security import CurrentUser, has_permission, require_permission
from backend.app.db.session import get_db
from backend.app.services import batch_job_service, batch_zip_service

router = APIRouter(prefix="/batch-jobs", tags=["batch-jobs"])
LOGGER = logging.getLogger(__name__)


def _require_batch_access(current_user: CurrentUser) -> CurrentUser:
    """Batch work spans prompt generation and RunPod submission — require both."""
    if not has_permission(current_user.permissions, "jobs:run"):
        raise HTTPException(status_code=403, detail="배치 작업 권한이 없습니다.")
    return current_user


def _scope(current_user: CurrentUser) -> str | None:
    """Managers see every worker's batches; everyone else sees only their own."""
    return None if has_permission(current_user.permissions, "jobs:manage") else current_user.id


@router.post("")
def create_batch_job(
    payload: dict,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    try:
        return batch_job_service.create_batch_job(db, payload, created_by=current_user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/active")
def active_batch_jobs(
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    return batch_job_service.list_active_batch_jobs(db, created_by=_scope(current_user))


@router.get("")
def batch_job_history(
    page: int = 1,
    dateFrom: str | None = None,
    dateTo: str | None = None,
    workerId: str | None = None,
    status: str | None = None,
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    return batch_job_service.list_batch_jobs(
        db,
        created_by=_scope(current_user),
        page=page,
        date_from=dateFrom,
        date_to=dateTo,
        worker_id=workerId,
        status=status,
    )


@router.get("/{batch_job_id}/download")
def download_batch_zip(
    batch_job_id: str,
    taskIds: list[str] | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("prompts:build")),
    db: Session = Depends(get_db),
):
    _require_batch_access(current_user)
    try:
        batch = batch_job_service.batch_job_payload(db, batch_job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scope = _scope(current_user)
    if scope and batch["createdBy"] != scope:
        raise HTTPException(status_code=403, detail="다른 작업자의 배치는 내려받을 수 없습니다.")
    try:
        chunks, skipped = batch_zip_service.stream_batch_zip(batch_job_id, task_ids=taskIds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    batch_job_service.mark_batch_downloaded(db, batch_job_id)
    return StreamingResponse(
        chunks,
        media_type="application/zip",
        headers={
            **batch_zip_service.ZIP_RESPONSE_HEADERS,
            "Content-Disposition": f'attachment; filename="{batch_job_id}.zip"',
            "X-Batch-Zip-Skipped": str(skipped),
        },
    )
```

`batch_job_service`에 추가한다:

```python
def mark_batch_downloaded(db: Session, batch_job_id: str) -> None:
    batch = db.get(BatchJob, batch_job_id)
    if batch is None:
        return
    batch.last_downloaded_at = datetime.utcnow()
    db.commit()
```

- [ ] **Step 5: main.py 배선 (G-3)**

`backend/app/main.py` import에 추가한다:

```python
from backend.app.api.v1 import batch_jobs as batch_jobs_router
from backend.app.services.batch_job_service import promote_ready_batch_drafts, refresh_batch_job_counters
```

라우터 등록부에 다른 `include_router` 옆으로 추가한다 (기존 호출의 prefix 인자를 그대로 흉내낸다):

```python
    # main.py:155-169는 라우터를 api_routers 리스트에 모아 두 prefix
    # (settings.api_prefix="/api/v1" 와 "/api") 양쪽에 등록한다. 단독
    # include_router로 /api/v1만 붙이면 프론트가 쓰는 /api 경로가 생기지 않는다.
    # 따라서 새 라우터는 그 리스트에 한 줄 추가하는 것으로 끝낸다:
    #     sandbox_pod_router,
    #     batch_jobs_router,        # ← 추가
    # ]
```

`monitor_loop`의 `await asyncio.to_thread(process_next_prompt_generation_draft)` **다음**에 추가한다:

```python
                # G-3: 배치 단계는 항상 마지막이고, 각각 독립된 try/except를 갖는다.
                # 배치 로직의 어떤 예외도 위의 RunPod 상태 폴링을 멈추면 안 된다.
                try:
                    await asyncio.to_thread(promote_ready_batch_drafts)
                except Exception:
                    LOGGER.exception("Batch promotion step failed")
                try:
                    await asyncio.to_thread(refresh_batch_job_counters)
                except Exception:
                    LOGGER.exception("Batch counter refresh failed")
```

- [ ] **Step 6: 테스트 통과 확인**

Run:
```bash
python3 -m compileall -q backend/app
python3 -m pytest backend/tests -q
```
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add backend/app/api/v1/batch_jobs.py backend/app/main.py backend/app/services/batch_job_service.py backend/tests/test_batch_job_api.py
git commit -m "feat(batch): expose batch job API and wire the monitor steps"
```

---

## Task 8: Task History의 batch_id 필터 (G-8)

**Files:**
- Modify: `backend/app/api/v1/history.py:27`(`prompt_history`), `:57`(`runpod_history`) — main 기준
- Modify: `backend/app/services/prompt_batch_service.py:167`(`list_prompt_drafts`)
- Modify: `backend/app/services/studio_api_service.py:71`(`paginated_history`), `:110`(`paginated_runpod_history`), `task_history_items`, `task_history_total`
- Test: `backend/tests/test_batch_history_filter.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `batch_job_id` 컬럼
- Produces:
  - `prompt_batch_service.list_prompt_drafts(..., batch_job_id: str = "")` — 기존 인자 뒤에 **추가**
  - `studio_api_service.paginated_history(..., batch_job_id: str = "")` / `paginated_runpod_history(..., batch_job_id: str = "")` / `task_history_items(..., batch_job_id: str = "")` / `task_history_total(..., batch_job_id: str = "")`
  - 두 응답의 항목 dict에 `batchJobId` 키 추가

> **C-1 경고 (main 대조에서 발견):** main의 두 엔드포인트는 **이미 필터를 갖고 있다.**
> `prompt_history(page, generationStatus, runpodStatus, ...)` ·
> `runpod_history(page, workflowId, resultStatus, workerId, dateFrom, dateTo, ...)`
> `list_prompt_drafts`도 `workflow_id / status / generation_status / runpod_status`를 이미 받고,
> `paginated_runpod_history`는 `workflow_id / result_status / worker_id / date_from / date_to`를 이미 받는다.
> **시그니처를 대체하지 말고 인자를 하나 추가할 것.** 기존 필터를 지우면 Task History가 퇴행한다.

- [ ] **Step 1: 실패 테스트 작성**

Create `backend/tests/test_batch_history_filter.py`:

```python
"""요구사항 13: 프롬프트/RunPod 이력에 batch_id 컬럼과 필터."""
from __future__ import annotations


def test_prompt_history_without_batch_filter_is_unchanged(client, operator_token, mixed_history):
    """G-8: batchId 미지정 시 기존 결과와 완전히 동일해야 한다."""
    response = client.get("/api/history/prompts?page=1", headers={"Authorization": f"Bearer {operator_token}"})
    assert response.status_code == 200
    assert response.json()["total"] == mixed_history["totalPromptDrafts"]


def test_prompt_history_filters_by_batch_id(client, operator_token, mixed_history):
    batch_id = mixed_history["batchJobId"]
    response = client.get(
        f"/api/history/prompts?page=1&batchId={batch_id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    items = response.json()["items"]
    assert items
    assert {item["batchJobId"] for item in items} == {batch_id}


def test_runpod_history_exposes_batch_job_id(client, operator_token, mixed_history):
    response = client.get("/api/history/runpod?page=1", headers={"Authorization": f"Bearer {operator_token}"})
    assert response.status_code == 200
    assert all("batchJobId" in item for item in response.json()["items"])


def test_runpod_history_filters_by_batch_id(client, operator_token, mixed_history):
    batch_id = mixed_history["batchJobId"]
    response = client.get(
        f"/api/history/runpod?page=1&batchId={batch_id}",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    items = response.json()["items"]
    assert items
    assert {item["batchJobId"] for item in items} == {batch_id}


def test_non_batch_rows_report_null_batch_job_id(client, operator_token, mixed_history):
    response = client.get("/api/history/runpod?page=1", headers={"Authorization": f"Bearer {operator_token}"})
    assert any(item["batchJobId"] is None for item in response.json()["items"])
```

`mixed_history` 픽스처는 배치 소속 task 2건과 비배치 task 1건을 만들고 `{"batchJobId": str, "totalPromptDrafts": int}`를 반환한다.

history 라우트의 실제 prefix를 먼저 확인한다:

Run: `grep -n "history" backend/app/main.py | head`

- [ ] **Step 2: 테스트 실패 확인**

Run: `python3 -m pytest backend/tests/test_batch_history_filter.py -q`
Expected: FAIL — `KeyError: 'batchJobId'`

- [ ] **Step 3: 프롬프트 이력 구현 (기존 인자 유지)**

`backend/app/services/prompt_batch_service.py:167` `list_prompt_drafts`의 **키워드 인자 목록 끝**(`include_worker_stats: bool = True,` 다음)에 추가한다. 다른 인자는 손대지 않는다:

```python
    batch_job_id: str = "",
```

같은 함수 안, 기존 `created_by` 조건 바로 뒤에 추가한다. main은 `statement`와 `count_statement` **두 개**를 함께 만들므로 둘 다에 걸어야 한다:

```python
    # G-8: 미지정이면 절을 붙이지 않는다 — 기존 호출자의 결과가 바뀌면 안 된다.
    if batch_job_id:
        statement = statement.where(ImagePromptDraft.batch_job_id == batch_job_id)
        count_statement = count_statement.where(ImagePromptDraft.batch_job_id == batch_job_id)
```

draft 응답을 만드는 `_draft_payload_from_related()`의 반환 dict에 추가한다:

```python
        "batchJobId": draft.batch_job_id,
```

`backend/app/api/v1/history.py:27` `prompt_history`에 **파라미터 하나만 추가**한다. `generationStatus` / `runpodStatus`는 그대로 둔다:

```python
def prompt_history(
    page: int = 1,
    generationStatus: str = "",
    runpodStatus: str = "",
    batchId: str = "",
    current_user: CurrentUser = Depends(require_permission("history:read")),
    db: Session = Depends(get_db),
):
```

같은 함수의 `list_prompt_drafts(...)` 호출에 인자 한 줄만 더한다 (기존 인자 전부 유지):

```python
            batch_job_id=batchId,
```

- [ ] **Step 4: RunPod 이력 구현 (기존 필터 5개 유지)**

`backend/app/services/studio_api_service.py`의 세 함수에 `batch_job_id: str = ""`를 **기존 키워드 인자 뒤에 추가**하고 그대로 아래로 전달한다:

1. `task_history_items(...)` — 태스크 조회 쿼리에 조건부 절을 건다:

```python
    if batch_job_id:
        statement = statement.where(WorkflowTask.batch_job_id == batch_job_id)
```

2. `task_history_total(...)` — 같은 조건을 count 쿼리에 건다.

3. `paginated_history(page, page_size, *, workflow_id, result_status, worker_id, date_from, date_to, batch_job_id="")` — 본문에서 `batch_job_id = str(batch_job_id or "").strip()`로 정규화하고 `task_history_items` / `task_history_total` 양쪽에 전달한다.

4. `paginated_runpod_history(page, *, workflow_id, result_status, worker_id, date_from, date_to, batch_job_id="")` — `paginated_history`로 전달한다.

history 항목을 만드는 `_task_to_history_item()`의 반환 dict에 추가한다:

```python
        "batchJobId": task.batch_job_id,
```

`backend/app/api/v1/history.py:57` `runpod_history`에 **파라미터 하나만 추가**한다. 기존 5개는 그대로 둔다:

```python
def runpod_history(
    page: int = 1,
    workflowId: str = "",
    resultStatus: str = "",
    workerId: str = "",
    dateFrom: str = "",
    dateTo: str = "",
    batchId: str = "",
    _: CurrentUser = Depends(require_permission("history:read")),
):
    return studio_api_service.paginated_runpod_history(
        page,
        workflow_id=workflowId,
        result_status=resultStatus,
        worker_id=workerId,
        date_from=dateFrom,
        date_to=dateTo,
        batch_job_id=batchId,
    )
```

- [ ] **Step 4b: 기존 필터가 살아 있는지 확인**

Run: `python3 -m pytest backend/tests/test_history_tab_api.py -q`
Expected: PASS. 이 파일이 main의 기존 필터 계약을 검증한다 — 실패하면 C-1을 어긴 것이다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `python3 -m pytest backend/tests/test_batch_history_filter.py backend/tests/ -q`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/app/api/v1/history.py backend/app/services/prompt_batch_service.py backend/app/services/studio_api_service.py backend/tests/test_batch_history_filter.py
git commit -m "feat(history): add batch_job_id column and filter to both histories"
```

---

## Task 9: 프론트 기반 — 라우팅 · 네비 · API 클라이언트 · 폴더 헬퍼 (G-9)

**Files:**
- Create: `frontend/src/helpers/batchFolder.ts`
- Modify: `frontend/src/router.ts`, `frontend/src/components/AppShell.tsx:43-61`·`:117`, `frontend/src/helpers/navigation.ts`, `frontend/src/api/client.ts:1043`·`:1050`, `frontend/src/StudioShell.tsx:112`·`:158`

**Interfaces:**
- Consumes: Task 7의 엔드포인트
- Produces:
  - `StudioRoute`에 `"create.batchJobs"` 추가, 경로 `/studio/create/batch`
  - `NavItem.permissions?: string[]`
  - `batchFolder.ts`: `IMAGE_EXTENSIONS: readonly string[]`, `selectBatchImages(files: File[]): File[]`, `folderNameOf(files: File[]): string`
  - `client.ts`: `BatchJobResponse`, `BatchJobActiveResponse`, `BatchJobHistoryResponse` 타입 + `apiClient.createBatchJob`, `.activeBatchJobs`, `.batchJobHistory`, `.batchJobDownloadUrl`

- [ ] **Step 1: 폴더 헬퍼 작성**

Create `frontend/src/helpers/batchFolder.ts`:

```typescript
// 배치 폴더 선택은 <input type="file" webkitdirectory>를 쓴다. 브라우저는 어떤
// API로도 절대경로를 주지 않으므로 폴더 "이름"만 얻을 수 있고, 하위 폴더 제외는
// webkitRelativePath의 세그먼트 수로 판정한다.
export const IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"] as const;

function extensionOf(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot < 0 ? "" : fileName.slice(dot + 1).toLowerCase();
}

/** 최상위 폴더의 대상 이미지만 남긴다. 하위 폴더(= 세그먼트 3개 이상)는 제외. */
export function selectBatchImages(files: File[]): File[] {
  return files.filter((file) => {
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
    if (relative.split("/").length > 2) return false;
    return (IMAGE_EXTENSIONS as readonly string[]).includes(extensionOf(file.name));
  });
}

/** 선택한 폴더의 이름. 경로가 없으면 빈 문자열. */
export function folderNameOf(files: File[]): string {
  for (const file of files) {
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || "";
    const [folder] = relative.split("/");
    if (folder && folder !== file.name) return folder;
  }
  return "";
}

export function countByExtension(files: File[]): Record<string, number> {
  const counts: Record<string, number> = {};
  files.forEach((file) => {
    const extension = extensionOf(file.name);
    counts[extension] = (counts[extension] || 0) + 1;
  });
  return counts;
}
```

- [ ] **Step 2: 라우트 추가**

`frontend/src/router.ts`:
- `StudioRoute` 유니온에 `| "create.batchJobs"`를 `"create.runpodRequests"` 다음에 추가
- `ROUTE_PATH`에 `"create.batchJobs": "/studio/create/batch",` 추가
- 파일 상단 주석 블록의 화면 id 대응 목록에 한 줄 추가:
  `//   create.batchJobs  — 폴더 단위 일괄 처리(프롬프트 생성 + RunPod 요청). 신규.`

- [ ] **Step 3: AppShell 다중 권한 지원 (G-9)**

`frontend/src/components/AppShell.tsx`의 `NavItem` 타입에 추가한다:

```typescript
  /** 모두 보유해야 노출되는 권한 목록. `permission`(단일)과 병행 지원한다 -
      기존 8개 항목의 노출 조건을 한 줄도 바꾸지 않기 위해 추가만 한다. */
  permissions?: string[];
```

`GENERATE_NAV_ITEMS`의 `runpodRequests` 다음 줄에 추가한다:

```typescript
  { key: "batchJobs", label: "Batch 작업 요청 관리", permissions: ["prompts:build", "jobs:run"] },
```

`visibleNavItems` 계산을 바꾼다:

```typescript
  const visibleNavItems = navItems.filter((item) => {
    if (item.permissions && !item.permissions.every((permission) => canUse(user, permission))) return false;
    return !item.permission || canUse(user, item.permission);
  });
```

- [ ] **Step 4: 네비게이션 매핑**

`frontend/src/helpers/navigation.ts`의 key→route 매핑에 `batchJobs: "create.batchJobs"`를 추가한다. 먼저 파일 구조를 확인한다:

Run: `cat frontend/src/helpers/navigation.ts`

- [ ] **Step 5: API 클라이언트**

`frontend/src/api/client.ts`에 타입을 추가한다:

```typescript
export type BatchJobResponse = {
  id: string;
  workflowId: string;
  status: "INCOMPLETE" | "COMPLETE";
  sourceDirName?: string | null;
  requestedFrames: number;
  durationSeconds: number;
  totalImages: number;
  promptCompletedCount: number;
  promptFailedCount: number;
  videoRequestedCount: number;
  videoCompletedCount: number;
  videoFailedCount: number;
  failedCount: number;
  lastDownloadedAt?: string | null;
  createdBy?: string | null;
  createdByName?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type BatchJobActiveItem = BatchJobResponse & {
  promptWaiting: number;
  promptGenerating: number;
  runpodPendingSubmit: number;
  runpodQueued: number;
  runpodInProgress: number;
};

export type BatchJobActiveResponse = { items: BatchJobActiveItem[] };

export type BatchJobHistoryResponse = {
  items: BatchJobResponse[];
  page: number;
  pageSize: number;
  total: number;
  workers: Array<{ workerId: string; workerName: string }>;
};
```

`apiClient` 객체에 메서드를 추가한다. **main의 요청 헬퍼 이름은 `requestJson`이다** (C-2):

```typescript
  createBatchJob: (payload: {
    workflowId: string;
    sourceDirName: string;
    requestedFrames: number;
    items: Array<{ assetId: string; fileName: string }>;
  }) => requestJson<BatchJobResponse>("/api/v1/batch-jobs", { method: "POST", body: JSON.stringify(payload) }),

  activeBatchJobs: () => requestJson<BatchJobActiveResponse>("/api/v1/batch-jobs/active"),

  batchJobHistory: (params: { page?: number; dateFrom?: string; dateTo?: string; workerId?: string; status?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page || 1));
    if (params.dateFrom) query.set("dateFrom", params.dateFrom);
    if (params.dateTo) query.set("dateTo", params.dateTo);
    if (params.workerId) query.set("workerId", params.workerId);
    if (params.status) query.set("status", params.status);
    return requestJson<BatchJobHistoryResponse>(`/api/v1/batch-jobs?${query.toString()}`);
  },

  batchJobDownloadUrl: (batchJobId: string, taskIds?: string[]) => {
    const query = new URLSearchParams();
    (taskIds || []).forEach((taskId) => query.append("taskIds", taskId));
    const suffix = query.toString();
    return `/api/v1/batch-jobs/${batchJobId}/download${suffix ? `?${suffix}` : ""}`;
  },
```

POST 본문을 보내는 기존 메서드가 `requestJson`을 어떤 형태로 호출하는지 먼저 확인해 맞춘다:

Run: `grep -n "requestJson" frontend/src/api/client.ts | head -5; grep -n "method: \"POST\"" frontend/src/api/client.ts | head -3`

**C-2:** main의 이력 호출은 **객체 파라미터**이며 이미 필터를 받는다. 위치 인자로 바꾸지 말고 `batchId`를 필드로 **추가**한다 (`client.ts:1043`, `:1050`):

```typescript
  promptHistory: (params: { page?: number; generationStatus?: string; runpodStatus?: string; batchId?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page || 1));
    if (params.generationStatus) query.set("generationStatus", params.generationStatus);
    if (params.runpodStatus) query.set("runpodStatus", params.runpodStatus);
    if (params.batchId) query.set("batchId", params.batchId);
    return requestJson<PromptDraftListResponse>(`/api/history/prompts?${query.toString()}`);
  },
  runpodHistory: (params: { page?: number; workflowId?: string; resultStatus?: string; workerId?: string; dateFrom?: string; dateTo?: string; batchId?: string } = {}) => {
    // ... 기존 5개 set 유지 ...
    if (params.batchId) query.set("batchId", params.batchId);
    // ... 기존 return 유지 ...
  },
```

`HistoryItem` 타입에 `batchJobId?: string | null;`을, `PromptDraftListResponse`의 항목 타입에도 `batchJobId?: string | null;`을 추가한다.

- [ ] **Step 5b: StudioShell 라우트 맵 등록 (C-3)**

**main 대조에서 발견:** `frontend/src/StudioShell.tsx`에는 라우트별 맵 두 개가 있고, 신규 라우트를 등록하지 않으면 **직접 URL 진입 시 권한 검사 없이 통과하고** 헤더 라벨이 비어 있다.

`ROUTE_REQUIRED_PERMISSION`(`:112`)에 추가한다. 이 맵은 단일 권한만 표현하므로 **더 좁은 쪽인 `jobs:run`**을 쓰고, 두 번째 권한은 사이드바 노출(G-9)과 백엔드 403이 담당한다:

```typescript
  "create.batchJobs": "jobs:run",
```

`ROUTE_LABEL`(`:158`)에 추가한다:

```typescript
  "create.batchJobs": "Batch 작업 요청 관리",
```

두 맵의 정확한 위치를 확인한다:

Run: `grep -n "ROUTE_REQUIRED_PERMISSION\|ROUTE_LABEL" frontend/src/StudioShell.tsx`

- [ ] **Step 6: 빌드 확인**

Run: `npm run build`
Expected: 성공. 이 시점에서 화면은 아직 없으므로 라우트로 이동해도 기본 화면이 뜬다.

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/helpers/batchFolder.ts frontend/src/router.ts frontend/src/components/AppShell.tsx frontend/src/helpers/navigation.ts frontend/src/api/client.ts frontend/src/StudioShell.tsx
git commit -m "feat(batch): add batch route, nav entry and API client bindings"
```

---

## Task 10: 배치 화면

**Files:**
- Create: `frontend/src/screens/batchJobScreen.tsx`
- Modify: `frontend/src/StudioShell.tsx`, `frontend/src/styles.css`

**Interfaces:**
- Consumes: Task 9의 `apiClient.createBatchJob` / `.activeBatchJobs` / `.batchJobHistory` / `.batchJobDownloadUrl`, `batchFolder.ts`
- Produces: `export function BatchJobScreen(props: { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; workflows: WorkflowItem[] })`

- [ ] **Step 1: 화면 작성**

Create `frontend/src/screens/batchJobScreen.tsx`. 섹션 5개를 스펙 §5.2 순서대로 그린다. 기존 `promptManagementScreen.tsx`의 클래스명(`v3-card`, `v3-prompt-workflow-card`, `v3-prompt-workflow-option`, `v3-pagination`)을 그대로 재사용해 두비덥 스타일을 유지한다.

```tsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiClient, BatchJobActiveItem, BatchJobResponse, HealthResponse, WorkflowItem } from "../api/client";
import { canUse, User } from "../auth";
import { AppShell } from "../components/AppShell";
import { countByExtension, folderNameOf, selectBatchImages } from "../helpers/batchFolder";
import { shellNavigate } from "../helpers/navigation";
import { fileToDataUrl } from "../helpers/workflow";
import { StudioRoute } from "../router";

type Props = { user: User; health: HealthResponse | null; onGoTo: (route: StudioRoute) => void; workflows: WorkflowItem[] };

const LENGTH_CHOICES = [49, 81, 161] as const;
const DEFAULT_FRAMES = 81;
const UPLOAD_CONCURRENCY = 4;
const ALL = "";

const workflowName = (workflow: WorkflowItem) => workflow.label || workflow.name || workflow.id;
// fps 16 기준. 서버가 워크플로우 output_fps로 최종 계산하므로 여기서는 표시용이다.
const secondsOf = (frames: number) => Math.max(1, Math.round(frames / 16));

/** 동시 실행 수를 제한한 map. 128장을 한꺼번에 올려 브라우저를 막지 않는다. */
async function mapWithLimit<T, R>(items: T[], limit: number, task: (item: T, index: number) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length);
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor++;
      results[index] = await task(items[index], index);
    }
  }));
  return results;
}

export function BatchJobScreen({ user, health: _health, onGoTo, workflows }: Props) {
  const canManage = canUse(user, "jobs:manage");
  const [workflowId, setWorkflowId] = useState("");
  const [instructionStatus, setInstructionStatus] = useState<{ configured: boolean; count: number } | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [requestedFrames, setRequestedFrames] = useState<number>(DEFAULT_FRAMES);
  const [active, setActive] = useState<BatchJobActiveItem[]>([]);
  const [history, setHistory] = useState<BatchJobResponse[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [workers, setWorkers] = useState<Array<{ workerId: string; workerName: string }>>([]);
  const [dateFrom, setDateFrom] = useState(ALL);
  const [dateTo, setDateTo] = useState(ALL);
  const [workerFilter, setWorkerFilter] = useState(ALL);
  const [statusFilter, setStatusFilter] = useState(ALL);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [notice, setNotice] = useState("");
  const folderInput = useRef<HTMLInputElement | null>(null);

  const selectedWorkflow = workflows.find((workflow) => workflow.id === workflowId);
  const folderName = useMemo(() => folderNameOf(files), [files]);
  const extensionCounts = useMemo(() => countByExtension(files), [files]);
  const canGenerate = Boolean(workflowId) && Boolean(instructionStatus?.configured) && files.length > 0 && !busy;

  useEffect(() => {
    if (!workflowId) { setInstructionStatus(null); return; }
    void apiClient.grokInstructionStatus(workflowId)
      .then(setInstructionStatus)
      .catch((error: Error) => { setInstructionStatus(null); setNotice(error.message); });
  }, [workflowId]);

  async function loadActive() {
    try { setActive((await apiClient.activeBatchJobs()).items); }
    catch { /* 대시보드 실패가 새 배치 생성을 막아서는 안 된다. */ }
  }

  async function loadHistory(page = historyPage) {
    try {
      const response = await apiClient.batchJobHistory({
        page,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        workerId: workerFilter || undefined,
        status: statusFilter || undefined,
      });
      setHistory(response.items);
      setHistoryTotal(response.total);
      setWorkers(response.workers);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "배치 내역을 불러오지 못했습니다.");
    }
  }

  useEffect(() => { void loadActive(); void loadHistory(1); }, []);
  useEffect(() => { setHistoryPage(1); void loadHistory(1); }, [dateFrom, dateTo, workerFilter, statusFilter]);

  // 미완료 배치가 있을 때만 폴링한다 (기존 두 화면과 같은 규칙).
  useEffect(() => {
    if (!active.length) return;
    const timer = window.setInterval(() => { void loadActive(); void loadHistory(); }, 3000);
    return () => window.clearInterval(timer);
  }, [active.length, historyPage, dateFrom, dateTo, workerFilter, statusFilter]);

  function pickFolder(fileList: FileList | null) {
    setNotice("");
    const picked = selectBatchImages(Array.from(fileList || []));
    setFiles(picked);
    if (!picked.length) setNotice("선택한 폴더에 처리할 이미지가 없습니다. (jpg · jpeg · png · webp)");
  }

  async function generate() {
    if (!canGenerate) return;
    setBusy(true);
    setNotice("");
    const uploaded: Array<{ assetId: string; fileName: string }> = [];
    const failed: string[] = [];
    try {
      let done = 0;
      await mapWithLimit(files, UPLOAD_CONCURRENCY, async (file) => {
        try {
          const result = await apiClient.upload({
            fileName: file.name,
            mimeType: file.type || "image/png",
            dataUrl: await fileToDataUrl(file),
          });
          uploaded.push({ assetId: result.assetId, fileName: file.name });
        } catch {
          failed.push(file.name);
        } finally {
          done += 1;
          setProgress(`업로드 ${done}/${files.length}`);
        }
      });

      if (!uploaded.length) {
        setNotice(`이미지를 한 장도 업로드하지 못했습니다. (${failed.length}건 실패)`);
        return;
      }

      try {
        await apiClient.createBatchJob({
          workflowId,
          sourceDirName: folderName || "(폴더)",
          requestedFrames,
          items: uploaded,
        });
      } catch (error) {
        // G-7: 배치가 안 만들어졌으면 draft도 없으므로 업로드 자산을 지울 수 있다.
        await Promise.allSettled(uploaded.map((item) => apiClient.deleteUnsubmittedUpload(item.assetId)));
        throw error;
      }

      setFiles([]);
      if (folderInput.current) folderInput.current.value = "";
      setNotice(failed.length ? `배치를 등록했습니다. 업로드 실패 ${failed.length}건: ${failed.join(", ")}` : "배치를 등록했습니다.");
      await loadActive();
      await loadHistory(1);
      setHistoryPage(1);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "배치 등록에 실패했습니다.");
    } finally {
      setProgress("");
      setBusy(false);
    }
  }

  const historyPageCount = Math.max(1, Math.ceil(historyTotal / 10));

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="batchJobs"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="GENERATE · BATCH"
      headerTitle="Batch 작업 요청 관리"
      headerActions={<button className="v3-secondary-button" type="button" onClick={() => { void loadActive(); void loadHistory(); }}>상태 새로고침</button>}
    >
      {/* ① Prompt Workflow */}
      <section className="v3-card v3-prompt-workflow-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Prompt Workflow</div><span className="v3-muted-text">프롬프트 생성 전에 워크플로우 지시문을 선택합니다.</span></div>
        <div className="v3-prompt-workflow-list">
          {workflows.map((workflow) => (
            <button key={workflow.id} type="button" className={`v3-prompt-workflow-option ${workflow.id === workflowId ? "is-selected" : ""}`} onClick={() => { setWorkflowId(workflow.id); setNotice(""); }}>
              <b>{workflowName(workflow)}</b><small>{workflow.keyframeCount || 1} kf · {workflow.id === workflowId ? "SELECTED" : "ACTIVE"}</small>
            </button>
          ))}
        </div>
        <p className={`v3-prompt-workflow-callout${!selectedWorkflow || (instructionStatus && !instructionStatus.configured) ? " is-error" : ""}`}>
          {selectedWorkflow
            ? instructionStatus?.configured
              ? `${workflowName(selectedWorkflow)}의 활성 프롬프트 지시문 ${instructionStatus.count}개를 사용합니다.`
              : `${workflowName(selectedWorkflow)}에 활성 프롬프트 지시문이 없습니다. 관리자 > 프롬프트 생성 지시 관리에서 먼저 설정하세요.`
            : "워크플로우를 선택하세요. 연결된 지시문이 없으면 배치를 시작할 수 없습니다."}
        </p>
      </section>

      {/* ② 폴더 선택 + 생성 */}
      <section className="v3-card v3-batch-launch">
        <div className="v3-batch-launch-left">
          <button className="v3-batch-folder-button" type="button" disabled={busy} onClick={() => folderInput.current?.click()}>작업 폴더 선택</button>
          {/* webkitdirectory는 표준 DOM 타입에 없어 캐스팅이 필요하다. */}
          <input
            ref={folderInput}
            hidden
            type="file"
            multiple
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
            onChange={(event) => pickFolder(event.target.files)}
          />
          {files.length ? (
            <div className="v3-batch-folder-summary">
              <b>{folderName || "(선택한 폴더)"}</b>
              <span>대상 이미지 {files.length}건 ({Object.entries(extensionCounts).map(([extension, count]) => `${extension} ${count}`).join(" · ")})</span>
              <small>최상위 폴더만 처리합니다. 브라우저는 절대경로를 제공하지 않아 폴더명만 기록됩니다.</small>
            </div>
          ) : <span className="v3-muted-text">폴더를 선택하면 대상 이미지 수가 표시됩니다.</span>}
        </div>
        <div className="v3-batch-launch-right">
          <small>BATCH GENERATIONS</small>
          <div className="v3-batch-length">
            <span>영상 길이</span>
            <div className="v3-runpod-length-buttons">
              {LENGTH_CHOICES.map((frames) => (
                <button key={frames} type="button" disabled={busy} className={requestedFrames === frames ? "is-selected" : ""} onClick={() => setRequestedFrames(frames)}>
                  {frames}
                </button>
              ))}
            </div>
            <b>{requestedFrames}f · {secondsOf(requestedFrames)}초</b>
          </div>
          <button className="v3-primary-button" type="button" disabled={!canGenerate} onClick={() => void generate()}>
            {busy ? (progress || "요청 중...") : `생성 (${files.length} Images)`}
          </button>
        </div>
      </section>

      {/* ③ 프롬프트 미완료 대시보드 */}
      <section className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">프롬프트(Grok) 미완료 배치 대시보드</div><span className="v3-muted-text">미완료 배치만 표시</span></div>
        {!active.length ? <div className="v3-empty-panel">진행 중인 배치가 없습니다.</div> : (
          <div className="v3-batch-table">
            <div className="v3-batch-table-head v3-batch-prompt-grid"><span>Batch_id</span><span>작업자</span><span>총 요청 이미지</span><span>프롬프트 생성대기</span><span>프롬프트 생성중</span><span>프롬프트 생성 완료</span><span>프롬프트 생성 실패</span></div>
            {active.map((item) => (
              <div className="v3-batch-table-row v3-batch-prompt-grid" key={`prompt-${item.id}`}>
                <span>{item.id}</span><span>{item.createdByName || item.createdBy || "-"}</span><span>{item.totalImages}</span>
                <span>{item.promptWaiting}</span><span>{item.promptGenerating}</span><span>{item.promptCompletedCount}</span><span>{item.promptFailedCount}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ④ 영상 미완료 대시보드 */}
      <section className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">영상(RunPod) 미완료 배치 대시보드</div><span className="v3-muted-text">미완료 배치만 표시</span></div>
        {!active.length ? <div className="v3-empty-panel">진행 중인 배치가 없습니다.</div> : (
          <div className="v3-batch-table">
            <div className="v3-batch-table-head v3-batch-runpod-grid"><span>Batch_id</span><span>작업자</span><span>프롬프트 생성완료</span><span>Pending Submit</span><span>RunPod queue</span><span>진행</span><span>완료</span><span>실패</span></div>
            {active.map((item) => (
              <div className="v3-batch-table-row v3-batch-runpod-grid" key={`runpod-${item.id}`}>
                <span>{item.id}</span><span>{item.createdByName || item.createdBy || "-"}</span><span>{item.promptCompletedCount}</span>
                <span>{item.runpodPendingSubmit}</span><span>{item.runpodQueued}</span><span>{item.runpodInProgress}</span>
                <span>{item.videoCompletedCount}</span><span>{item.videoFailedCount}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ⑤ Batch 작업 내역 */}
      <section className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Batch 작업</div><span className="v3-muted-text">전체 배치 · 10건 단위</span></div>
        <div className="v3-runpod-filter-bar">
          <label>시작일<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
          <label>종료일<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
          {canManage ? (
            <label>작업자<select value={workerFilter} onChange={(event) => setWorkerFilter(event.target.value)}>
              <option value={ALL}>전체</option>
              {workers.map((worker) => <option key={worker.workerId} value={worker.workerId}>{worker.workerName}</option>)}
            </select></label>
          ) : null}
          <label>상태<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value={ALL}>전체</option>
            <option value="INCOMPLETE">미완료</option>
            <option value="COMPLETE">완료</option>
          </select></label>
        </div>
        {!history.length ? <div className="v3-empty-panel">표시할 배치 작업이 없습니다.</div> : (
          <div className="v3-batch-table">
            <div className="v3-batch-table-head v3-batch-history-grid"><span>Batch ID</span><span>Date</span><span>작업자</span><span>상태</span><span>영상길이(초)</span><span>이미지 완료 건수</span><span>영상 완료 건수</span><span>이미지 디렉토리</span><span>다운로드</span><span>실패건수</span></div>
            {history.map((item) => (
              <div className="v3-batch-table-row v3-batch-history-grid" key={item.id}>
                <span>{item.id}</span>
                <span>{item.createdAt ? item.createdAt.slice(0, 10) : "-"}</span>
                <span>{item.createdByName || item.createdBy || "-"}</span>
                <span className={`v3-status-badge ${item.status === "COMPLETE" ? "is-ready" : "is-pending"}`}>{item.status === "COMPLETE" ? "완료" : "미완료"}</span>
                <span>{item.durationSeconds}초</span>
                <span>{item.promptCompletedCount}</span>
                <span>{item.videoCompletedCount}</span>
                <span>{item.sourceDirName || "-"}</span>
                <span className="v3-batch-download-cell">
                  {item.videoCompletedCount > 0
                    ? <a className="v3-text-link-button" href={apiClient.batchJobDownloadUrl(item.id)} download>ZIP 다운로드</a>
                    : <span className="v3-muted-text">-</span>}
                  {item.lastDownloadedAt ? <small>{item.lastDownloadedAt.slice(0, 16).replace("T", " ")}</small> : null}
                </span>
                <span>{item.failedCount}</span>
              </div>
            ))}
          </div>
        )}
        <div className="v3-pagination">
          <span className="v3-pagination-meta">{historyTotal ? `${(historyPage - 1) * 10 + 1}-${Math.min(historyPage * 10, historyTotal)} / ${historyTotal}건` : "0건"} · 페이지당 10건</span>
          <div className="v3-pagination-controls">
            <button className="v3-page-button" type="button" disabled={historyPage <= 1} onClick={() => { const next = historyPage - 1; setHistoryPage(next); void loadHistory(next); }}>이전</button>
            <span className="v3-page-button is-current">{historyPage}</span>
            <button className="v3-page-button" type="button" disabled={historyPage >= historyPageCount} onClick={() => { const next = historyPage + 1; setHistoryPage(next); void loadHistory(next); }}>다음</button>
          </div>
        </div>
      </section>

      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
    </AppShell>
  );
}
```

- [ ] **Step 2: 화면 렌더 분기 추가**

`frontend/src/StudioShell.tsx`에서 `create.runpodRequests`를 렌더하는 분기를 찾아 그 옆에 같은 형태로 `create.batchJobs` 분기를 추가한다:

Run: `grep -n "create.runpodRequests\|RunpodRequestScreen" frontend/src/StudioShell.tsx`

찾은 패턴을 그대로 복제해 `BatchJobScreen`을 렌더한다.

- [ ] **Step 3: 스타일 추가**

`frontend/src/styles.css` 끝에 추가한다:

```css
/* Batch 작업 요청 관리 */
.v3-batch-launch { display: grid; grid-template-columns: 1fr 320px; gap: 16px; align-items: start; }
.v3-batch-launch-left { display: flex; flex-direction: column; gap: 10px; }
.v3-batch-folder-button { padding: 22px; border-radius: 8px; border: none; background: var(--v3-accent); color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; }
.v3-batch-folder-button:disabled { opacity: .5; cursor: default; }
.v3-batch-folder-summary { display: flex; flex-direction: column; gap: 3px; }
.v3-batch-folder-summary small { color: var(--v3-text-secondary); }
.v3-batch-launch-right { display: flex; flex-direction: column; gap: 10px; padding: 14px; border-radius: 8px; background: var(--v3-bg-muted); }
.v3-batch-length { display: flex; flex-direction: column; gap: 6px; }
.v3-batch-table { display: flex; flex-direction: column; overflow-x: auto; }
.v3-batch-table-head, .v3-batch-table-row { display: grid; gap: 8px; padding: 9px 10px; align-items: center; font-size: 12px; }
.v3-batch-table-head { font-weight: 600; background: var(--v3-bg-muted); border-radius: 6px; }
.v3-batch-table-row { border-bottom: 1px solid var(--v3-border); }
.v3-batch-prompt-grid { grid-template-columns: minmax(150px, 1.4fr) 90px 100px 110px 100px 120px 110px; min-width: 900px; }
.v3-batch-runpod-grid { grid-template-columns: minmax(150px, 1.4fr) 90px 110px 110px 110px 70px 70px 70px; min-width: 940px; }
.v3-batch-history-grid { grid-template-columns: minmax(150px, 1.2fr) 96px 90px 76px 96px 110px 104px minmax(110px, .8fr) 130px 84px; min-width: 1120px; }
.v3-batch-download-cell { display: flex; flex-direction: column; gap: 2px; }
.v3-batch-download-cell small { color: var(--v3-text-secondary); font-size: 10px; }
```

위 변수들(`--v3-bg-muted`·`--v3-accent`·`--v3-border`·`--v3-text-secondary`)은 재검토에서 존재를 확인했다. `--v3-surface-muted`는 존재하지 않으므로 절대 쓰지 말 것.

- [ ] **Step 4: 빌드 확인**

Run: `npm run build`
Expected: 성공

- [ ] **Step 5: 화면 확인**

Run: `npm start` 후 브라우저에서 `http://127.0.0.1:8790/studio/create/batch`
Expected: 사이드바에 `Batch 작업 요청 관리`가 보이고, 워크플로우 카드·폴더 선택·Length 버튼(81 선택됨)·`생성 (0 Images)` 비활성 버튼·표 3개가 렌더된다.

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/screens/batchJobScreen.tsx frontend/src/StudioShell.tsx frontend/src/styles.css
git commit -m "feat(batch): add the batch job management screen"
```

---

## Task 11: Task History — Batch 열 · 필터 · ZIP 버튼 (G-6)

**Files:**
- Modify: `frontend/src/screens/reviewScreens.tsx`

**Interfaces:**
- Consumes: Task 8의 `batchJobId` 필드/필터, Task 9의 `apiClient.runpodHistory(page, batchId)` · `.promptHistory(page, batchId)` · `.batchJobDownloadUrl`
- Produces: 없음 (최종 소비자)

- [ ] **Step 1: grid 정의를 상수로 뽑는다 (G-6)**

main의 `frontend/src/screens/reviewScreens.tsx:451`(헤더)과 `:467`(행)에 **같은 문자열이 두 번** 하드코딩돼 있다 (`"32px 36px 70px 96px 130px 120px 82px 72px 72px minmax(150px, .8fr) 86px 52px"`, `minWidth: 1120`). 같은 파일 `:1019`·`:1040`·`:1288`·`:1299`는 이미 `gridColumns` 변수를 쓰고 있으니 **건드리지 않는다**. 열을 추가하기 전에 먼저 상수화한다. 파일 상단(import 다음)에 추가한다:

```typescript
// 헤더와 행이 같은 정의를 공유해야 한다. 이전에는 두 곳에 하드코딩돼 있어
// 열을 추가할 때 한쪽만 고치면 표가 어긋났다.
const RUNPOD_HISTORY_GRID = "32px 36px 70px 96px 130px 120px 120px 82px 72px 72px minmax(150px, .8fr) 86px 52px";
const RUNPOD_HISTORY_MIN_WIDTH = 1240;
```

두 곳의 `style={{ gridTemplateColumns: "32px 36px ...", minWidth: 1120, ... }}`를 각각 바꾼다:

```typescript
style={{ gridTemplateColumns: RUNPOD_HISTORY_GRID, minWidth: RUNPOD_HISTORY_MIN_WIDTH }}
```

행 쪽에는 기존 `cursor: "pointer"`를 유지한다:

```typescript
style={{ gridTemplateColumns: RUNPOD_HISTORY_GRID, minWidth: RUNPOD_HISTORY_MIN_WIDTH, cursor: "pointer" }}
```

(위 `RUNPOD_HISTORY_GRID`는 `Prompt ID` 다음에 `120px` 한 칸을 이미 추가한 값이다.)

- [ ] **Step 2: Batch ID 열 추가**

헤더의 `<span>Prompt ID</span>` 다음에 추가한다:

```tsx
<span>Batch ID</span>
```

각 행의 Prompt ID `<span>` 다음에 추가한다:

```tsx
<span className="v3-review-prompt" title={item.batchJobId || ""}>{item.batchJobId || "-"}</span>
```

- [ ] **Step 3: Batch 필터 + ZIP 다운로드 버튼 추가**

RunPod 이력 상태를 추가한다:

```typescript
const [batchFilter, setBatchFilter] = useState("");
const batchOptions = useMemo(() => {
  const ids = new Set<string>();
  runpodHistoryItems.forEach((item) => { if (item.batchJobId) ids.add(item.batchJobId); });
  return [...ids].sort();
}, [runpodHistoryItems]);
```

`apiClient.runpodHistory({ ... })` 호출에 **`batchId: batchFilter || undefined`를 추가**한다. main은 이미 `workflowId` / `resultStatus` / `workerId` / `dateFrom` / `dateTo`를 넘기고 있으므로 **그 인자들을 지우지 말 것** (C-1/C-2). 그 effect의 의존성 배열에 `batchFilter`를 추가한다.

Run: `grep -n "apiClient.runpodHistory\|apiClient.promptHistory" frontend/src/screens/reviewScreens.tsx`

`선택 삭제` 버튼이 있는 액션 바에 필터와 버튼을 추가한다:

```tsx
<label className="v3-review-batch-filter">
  Batch
  <select value={batchFilter} onChange={(event) => { setBatchFilter(event.target.value); setRunpodPage(1); }}>
    <option value="">전체</option>
    {batchOptions.map((id) => <option key={id} value={id}>{id}</option>)}
  </select>
</label>
<a
  className={`v3-secondary-button${!batchFilter || !selectedRunpodTaskIds.length ? " is-disabled" : ""}`}
  // ZIP은 배치 단위 엔드포인트라 특정 Batch로 좁혀졌을 때만 의미가 있다.
  title={!batchFilter ? "Batch를 선택하세요" : ""}
  href={batchFilter && selectedRunpodTaskIds.length ? apiClient.batchJobDownloadUrl(batchFilter, selectedRunpodTaskIds) : undefined}
  download
  aria-disabled={!batchFilter || !selectedRunpodTaskIds.length}
  onClick={(event) => { if (!batchFilter || !selectedRunpodTaskIds.length) event.preventDefault(); }}
>
  선택 {selectedRunpodTaskIds.length}건 ZIP 다운로드
</a>
```

`frontend/src/styles.css`에 추가한다:

```css
.v3-review-batch-filter { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.v3-secondary-button.is-disabled { opacity: .45; pointer-events: none; }
```

- [ ] **Step 4: 프롬프트 이력에도 같은 처리**

프롬프트 이력 표의 `apiClient.promptHistory({ ... })` 호출에도 `batchId`를 **추가**하고(기존 `generationStatus` / `runpodStatus` 유지), `Batch ID` 열과 `Batch` 필터를 넣는다. 그 표는 이미 `gridColumns` 변수를 쓰므로 상수화가 필요 없다 — 변수 정의 한 곳에 열 폭을 더하면 헤더와 행에 동시에 반영된다.

Run: `grep -n "gridColumns" frontend/src/screens/reviewScreens.tsx | head`

- [ ] **Step 5: 빌드 확인**

Run: `npm run build`
Expected: 성공

- [ ] **Step 6: 화면 확인**

Run: `npm start` 후 `http://127.0.0.1:8790/studio/review/history`
Expected: 두 이력 표에 `Batch ID` 열이 보이고, RunPod 이력 상단에 `Batch` 필터와 ZIP 버튼이 있다. Batch가 `전체`일 때 ZIP 버튼은 비활성이다.

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/screens/reviewScreens.tsx frontend/src/styles.css
git commit -m "feat(history): add batch id column, filter and zip download"
```

---

## Task 12: 통합 검증

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 검증 스위트**

Run: `./scripts/verify.sh`
Expected: 4단계 전부 통과 — 백엔드 컴파일 · pytest · 프론트 빌드 · `git diff --check`

- [ ] **Step 2: 가드레일 회귀 확인**

Run:
```bash
python3 -m pytest backend/tests/test_batch_fair_scheduling.py backend/tests/test_runpod_submission_queue.py backend/tests/test_durable_runpod_request_batch.py -q
```
Expected: PASS — G-1이 기존 큐 계약을 깨지 않았음을 확인한다.

- [ ] **Step 3: 종단 수동 확인**

Run: `npm start`

`RUNPOD_DRY_RUN=1`로 실행해 실제 RunPod 호출 없이 확인한다.

1. `/studio/create/batch` 진입 → 지시문이 설정된 워크플로우 선택
2. 이미지 3장이 든 폴더 선택 → 버튼이 `생성 (3 Images)`로 바뀌는지
3. Length를 161로 바꾸면 `161f · 10초`가 표시되는지
4. 생성 클릭 → ③ 대시보드에 배치가 나타나고 카운터가 움직이는지
5. 모든 항목이 종료되면 ③④에서 사라지고 ⑤에만 남는지 (요구사항 8·9)
6. ⑤의 `ZIP 다운로드` → 압축을 풀면 `output/` 아래 원본 이미지명 mp4가 나오는지 (요구사항 10·11)
7. `/studio/review/history` → Batch 필터로 좁힌 뒤 선택 ZIP 다운로드
8. 다른 브라우저 탭에서 단건 프롬프트 생성을 요청해, 배치가 도는 중에도 **먼저** 처리되는지 (G-1)

- [ ] **Step 4: 참조 무결성 점검 (SE-16)**

`batch_job_id` 네 컬럼에는 FK가 없다 — 저장소 관례를 따른 의도된 선택이다
(`20260901_0026`이 `request_batch_id`·`prompt_draft_id`도 같은 방식으로 추가했다).
대신 고아 행이 없는지 쿼리로 확인한다:

```sql
-- 존재하지 않는 배치를 가리키는 행 (전부 0이어야 한다)
SELECT 'drafts', COUNT(*) FROM image_prompt_drafts d
  LEFT JOIN batch_jobs b ON b.id = d.batch_job_id
  WHERE d.batch_job_id IS NOT NULL AND b.id IS NULL
UNION ALL
SELECT 'tasks', COUNT(*) FROM workflow_tasks t
  LEFT JOIN batch_jobs b ON b.id = t.batch_job_id
  WHERE t.batch_job_id IS NOT NULL AND b.id IS NULL
UNION ALL
-- 같은 draft가 두 번 승격된 흔적 (SE-11이 재발하면 여기서 잡힌다)
SELECT 'double_promoted', COUNT(*) FROM (
  SELECT prompt_draft_id FROM runpod_request_items
  WHERE prompt_draft_id IS NOT NULL
  GROUP BY prompt_draft_id HAVING COUNT(*) > 1
) x;
```

- [ ] **Step 5: 배포 게이트 (G-14 · SE-15) — 운영 배포 시 반드시 이 순서로**

**이 순서를 지키지 않으면 Task History·프롬프트 생성 관리·RunPod 요청 관리가 전부 장애가 난다.**
운영은 `RUN_SERVER_AUTO_MIGRATE=0`이고(`.env.example:86`, `backend/app/main.py:45`) 배포는
ECS Express Canary다. 새 ORM 컬럼 `batch_job_id`는 기존 화면이 매번 조회하는 테이블에 붙으므로,
마이그레이션 전에 새 이미지가 뜨면 SQLAlchemy가 만드는 SELECT가 `Unknown column 'batch_job_id'`로
전부 실패한다.

기준 문서는 `docs/ecs-express-deployment-runbook.md`(특히 `:80-88`)이며, 순서는 다음과 같다:

1. ECR immutable 이미지 push
2. 기존 task definition 복제
3. **새 이미지로 `--check` 실행** → `migrationRequired` 판정
4. `migrationRequired=true`이면 **`--if-needed` one-off task로 마이그레이션 실행**하고 성공을 확인
5. **그 다음에만** Canary 배포. ECS가 health check와 draining을 관리하므로 이전 revision을 수동 중지하지 않는다
6. 배포 후 Step 4의 무결성 쿼리와 `python3 scripts/fastapi_smoke_check.py` 실행

Canary 구간에는 구·신 revision이 동시에 monitor_loop을 돌린다는 점을 기억한다 — R-D의 원자적 claim이
그 구간의 RunPod 이중 제출을 막는 유일한 장치다.

- [ ] **Step 6: 문서 갱신**

`README.md`의 화면 표에 `Batch 작업 요청 관리` / `/studio/create/batch` 행을 추가한다.

- [ ] **Step 7: 최종 커밋**

```bash
git add README.md
git commit -m "docs: document the batch job management screen"
```

---

## 자체 검토 결과

**3차 개정 결함 커버리지:**

| 결함 | 가드레일 | 태스크 |
|---|---|---|
| SE-11 Canary 중복 승격 (치명) | G-10 원자적 claim | R-D |
| SE-12 트랜잭션 분리 (치명) | G-11 `commit=False` | R-C |
| SE-13 monitor 장기 점유 (높음) | G-12 주기당 상한 20 | R-D |
| SE-14 카운터 미사용 (높음) | G-13 저장 카운터 + 복합 인덱스 | R-A, Task 4 |
| SE-15 배포 게이트 (치명) | G-14 `--check` → one-off → Canary | Task 12 Step 5 |
| SE-16 참조 무결성 (중간) | FK 미도입 + orphan 쿼리 | Task 12 Step 4 |
| SE-17 고아 request item (치명) | G-15 복구기 + 잔여 기반 완료 판정 | R-E |
| `batchJobId` 인젝션 (치명) | keyword 인자로 승격 | R-B |
| 만료 없는 선점 (치명) | lease + 만료 회수(기존 `_recover_stale_dispatching_submissions` 패턴) **+ 제출 직전 claim 재확인** | R-D |
| 승격 후보 전량 메모리 로드 (높음) | `NOT EXISTS` 상관 서브쿼리 + 전용 복합 인덱스 | R-A, R-D |
| 동시성 테스트 부재 (높음) | **배리어 스레드 경합** + 독립 Session + stale 회수 + item 존재 시 재승격 금지 | R-D |
| 0033 수정 전제 미확인 (중간) | R-A Step 0 사전 확인, 적용 이력 있으면 0034 분리 | R-A |

**스펙 커버리지** — 스펙 §별 대응 태스크:

| 스펙 | 태스크 |
|---|---|
| §2 서버 저장 | Task 2(업로드 재사용), Task 6(서버 자산에서 ZIP) |
| §5.1 라우팅·권한 | Task 9 |
| §5.2 ①~⑤ | Task 10 |
| §6 생성 동작 | Task 2, Task 10 |
| §7 monitor_loop | Task 3, Task 4, Task 7 |
| §8 ZIP | Task 6, Task 7 |
| §9 Length·초 | Task 2 (검증·저장), Task 10 (선택 UI) |
| §10 Task History | Task 8, Task 11 |
| §11 DB | Task 1 |
| §12 API | Task 7 |
| §13 오류 처리 | Task 2·7 (백엔드 400/403), Task 10 (프론트 안내) |
| §14 테스트 | Task 1~8, Task 12 |

**타입 일관성** — 태스크 간 이름을 대조했다: `create_batch_job` / `batch_job_payload` / `promote_ready_batch_drafts` / `refresh_batch_job_counters` / `list_active_batch_jobs` / `list_batch_jobs` / `mark_batch_downloaded` / `zip_entry_name` / `collect_batch_outputs` / `stream_batch_zip` / `ZIP_RESPONSE_HEADERS` — 정의한 태스크와 사용하는 태스크에서 철자가 같다. 프론트의 `BatchJobResponse` 필드명은 백엔드 `_batch_payload()`의 키와 1:1로 일치한다.

**미해결 가정** (스펙 §16과 동일): 중복 배치 감지 없음 · 하위 폴더 미탐색 · 배치 단위 취소 없음 · 대용량 ZIP 분할 없음.
