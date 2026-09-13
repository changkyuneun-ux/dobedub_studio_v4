# Batch 작업 요청 관리 설계

- 작성일: 2026-09-04
- 대상 화면: 스튜디오 → GENERATE → **Batch 작업 요청 관리** (`create.batchJobs`)
- 관련 기존 화면: `create.promptManagement`(프롬프트 생성 관리), `create.runpodRequests`(RunPod 요청 관리), `review.history`(Task History)

## 1. 목적

폴더 하나를 지정하면 그 안의 이미지 전부에 대해 **프롬프트 생성 → RunPod 영상 생성**까지
한 번의 버튼으로 끝내고, 결과 영상은 Task History에서 **batch_id로 필터해 ZIP으로 한 번에 내려받는다.**

기존 두 화면은 이미지를 한 장씩 올리고 프롬프트 결과를 확인한 뒤 다시 RunPod 요청을 선택 제출하는
대화형 흐름이며, 수십~수백 장을 처리할 때는 사람이 계속 붙어 있어야 한다. 이 화면은 그 개입을 없앤다.

## 2. 저장 위치 (중요)

입력 이미지와 출력 영상은 **기존 경로 그대로 서버에 저장한다.** 별도의 로컬 저장 경로를 만들지 않는다.

- 입력 이미지: 브라우저가 폴더에서 읽어 기존 `POST /api/uploads`로 업로드 → `assets`(`input_image`)
- 출력 영상: RunPod가 base64로 반환 → 서버가 디코딩해 저장 (`output_service.save_runpod_outputs`) → `assets`(`output_video`)
- 사용자가 파일을 로컬에 두는 시점은 **ZIP 다운로드 한 번뿐**이다

브라우저는 어떤 API로도 폴더의 절대경로를 노출하지 않는다(`webkitdirectory`·`showDirectoryPicker` 모두
폴더 **이름**만 준다). 따라서 배치 내역의 `이미지 디렉토리` 컬럼에는 선택한 폴더명(`shoot-0904`)만 남는다.

## 3. 범위 밖

- 배치 단위 취소·일시정지 (개별 Task 취소는 기존 Task History에서 계속 가능)
- 같은 폴더를 다시 배치로 돌릴 때의 중복 감지 — 매번 새 배치로 처리한다
- 다중 keyframe(2장 이상 입력) 워크플로우 — 기존 RunPod 요청 관리와 동일하게 `keyframeCount == 1`만 대상
- 배치 자산의 보관 기한 변경 — 기존 자산 보관 정책을 그대로 따른다

## 4. 채택한 접근

**배치 오케스트레이션 테이블(`batch_jobs`)을 상위 개념으로 신설하고, 이미 존재하는
`prompt_generation_batches` / `runpod_request_batches` 파이프라인을 그 자식으로 연결한다.**

검토한 대안:

| 안 | 내용 | 기각 사유 |
|---|---|---|
| B | `prompt_generation_batches`에 폴더명·모드 컬럼을 추가해 확장 | batch-id가 "프롬프트 배치 id"가 되어 영상 요청/완료 건수를 프롬프트 배치에 얹게 된다. 화면의 세 테이블이 하나의 batch_id로 묶이는 구조와 어긋난다 |
| C | 배치 전용 프롬프트 생성·RunPod 디스패치 로직을 새로 작성 | 기존 Grok 생성(`prompt_batch_service`)과 디스패치(`runpod_dispatch_service`)를 통째로 복제하게 된다. 유지비가 두 배 |

A안은 기존 파이프라인·화면·이력·저장 경로를 건드리지 않고 재사용하며, 첨부 설계 화면의 세 테이블
(프롬프트 대시보드 / 영상 대시보드 / Batch 작업 내역)이 **하나의 batch_id**를 공유하는 구조와 일치한다.

## 5. 화면 설계

### 5.1 라우팅 · 메뉴

- `StudioRoute`에 `create.batchJobs` 추가, 경로 `/studio/create/batch`
- `AppShell`의 `GENERATE_NAV_ITEMS`에 `RunPod 요청 관리` 바로 아래 `{ key: "batchJobs", label: "Batch 작업 요청 관리" }` 추가
- 노출 권한: `prompts:build` **AND** `jobs:run`
  - `NavItem`은 현재 `permission?: string` 단일 값만 지원하므로 `permissions?: string[]`(전부 보유해야 노출)를
    추가하고, 기존 `permission` 항목은 그대로 둔다
- 신규 화면 파일: `frontend/src/screens/batchJobScreen.tsx`

### 5.2 화면 구성 (설계 화면 순서 그대로)

**① Prompt Workflow**

기존 `promptManagementScreen`의 워크플로우 카드 리스트를 동일한 마크업으로 재사용한다
(`v3-prompt-workflow-card`). 선택 시 `apiClient.grokInstructionStatus(workflowId)`로 활성 지시문
보유 여부를 확인하고, 없으면 기존 화면과 같은 경고 문구를 띄운다.

**② 작업 폴더 선택 / Batch Generations · 생성**

좌우 2단. 좌측 `작업 폴더 선택` 버튼, 우측 `생성` 버튼.

- 폴더 선택은 `<input type="file" webkitdirectory>` — 모든 브라우저에서 동작하고,
  선택 후 별도의 권한 유지가 필요 없다
- **최상위 폴더만** 대상으로 한다. `webkitRelativePath`에 `/`가 두 번 이상 들어간 파일(하위 폴더)은 제외한다
- 대상 확장자: `jpg` `jpeg` `png` `webp`
- 좌측에 폴더명과 `대상 이미지 128건 (jpg 96 · png 32)` 표시
- 우측 생성 버튼 라벨: `생성 (128 Images)` — **대상 이미지 개수를 버튼에 표시**(요구사항 4)
- 생성 버튼 활성 조건(요구사항 5): 폴더 선택됨 **AND** 워크플로우 선택됨 **AND** 그 워크플로우에 활성 지시문 있음
- **Length 선택기**를 생성 버튼 위에 둔다(§9). 기존 RunPod 요청 관리 화면과 같은
  `49 / 81 / 161` 버튼 그룹이며 **기본 선택은 81**. 선택한 초 수를 함께 표시한다: `81f · 5초`

**③ 프롬프트(Grok) 미완료 배치 대시보드**

| Batch_id | 작업자 | 총 요청 이미지 | 프롬프트 생성대기 | 프롬프트 생성중 | 프롬프트 생성 완료 | 프롬프트 생성 실패 |

**④ 영상(RunPod) 미완료 배치 대시보드**

| Batch_id | 작업자 | 프롬프트 생성완료 | Pending Submit | RunPod queue | 진행 | 완료 | 실패 |

③·④ 모두 **상태가 `미완료`인 배치만** 조회한다(요구사항 9). 완료된 배치는 이 두 표에서 사라지고
⑤에만 남는다. 폴링 주기 3초 — 미완료 배치가 0건이면 폴링을 멈춘다(기존 두 화면과 동일한 규칙).

**⑤ Batch 작업 (작업 내역)**

| Batch ID | Date | 작업자 | 상태 | **영상길이(초)** | 이미지 완료 건수 | 영상 완료 건수 | 이미지 디렉토리 | **다운로드** | 실패건수(프롬프트+영상) |

- 설계 화면의 `영상 디렉토리` 컬럼은 **`다운로드` 열로 교체**한다. 영상이 서버에 저장되므로 사용자에게
  보여줄 로컬 경로가 존재하지 않는다. 이 열에는 `ZIP 다운로드` 버튼과 마지막 다운로드 일시가 들어간다
- `영상길이(초)`는 `batch_jobs.duration_seconds`를 그대로 표시한다 (`5초` / `10초`)
- `이미지 디렉토리`는 선택한 폴더명(§2)
- 필터(요구사항 12): **일자**(시작~종료), **작업자**, **상태**(전체/완료/미완료). 기본값 모두 **전체**
- 페이지네이션: **5건 단위**
- `작업자` 필터는 `jobs:manage` 권한 보유자에게만 노출한다. 미보유자는 자기 배치만 조회된다
  (기존 `runpodRequestScreen`·`/history/prompts`의 격리 규칙과 동일)
- `실패건수`는 `prompt_failed_count + video_failed_count`

## 6. 생성 버튼 동작

1. **업로드** — 폴더의 이미지 파일을 기존 `POST /api/uploads`(`apiClient.upload`)로 업로드한다.
   동시 4건, 실패 건은 3회까지 재시도한다. 진행률(`업로드 34/128`)을 버튼 자리에 표시한다.
   전부 실패하면 배치를 만들지 않고 오류만 표시한다. 일부 실패하면 성공한 자산만으로 배치를 만들고
   실패 파일명을 안내한다.
2. **배치 생성** — `POST /api/v1/batch-jobs` 한 번 호출.
   서버가 한 트랜잭션에서 `batch_jobs` 1행 + `prompt_generation_batches` 1행 +
   `image_prompt_drafts` N행(status `PENDING`)을 만든다.
3. **이후는 전부 서버 주도.** 프론트는 상태를 읽기만 한다.
4. 성공 시 폴더 선택을 비우고, ③ 대시보드 첫 행에 새 배치가 나타난다.

**탭을 닫아도 프롬프트 생성과 영상 생성은 끝까지 진행되며, 결과는 서버에 남는다.**

## 7. 서버측 진행 (monitor_loop 확장)

`backend/app/main.py`의 `monitor_loop`은 현재 매 주기마다
`monitor_active_jobs` → `monitor_active_prompt_generations` → `process_next_prompt_generation_draft`
를 실행한다. 여기에 **두 단계를 추가**한다.

```
promote_ready_batch_drafts()   # 신규: 프롬프트 READY → RunPod 요청 항목 생성
refresh_batch_job_counters()   # 신규: batch_jobs 카운터·상태 갱신
```

### 7.1 `promote_ready_batch_drafts()` (`batch_job_service.py`)

미완료 `batch_jobs`에 속한 draft 중 다음 조건을 모두 만족하는 것을 찾는다.

- `status == "READY"`
- 아직 `runpod_request_items`에 승격된 적이 없음

찾은 draft에 대해 해당 배치의 `runpod_request_batches`(없으면 생성)에
`runpod_request_items`(status `PENDING_SUBMIT`)를 추가한다. 이후 전송은 기존
`dispatch_next_pending_submission`이 유휴 worker를 확인해 순차 처리한다 — **디스패치 로직은 손대지 않는다.**

`FAILED` draft는 승격하지 않고 `prompt_failed_count`로만 집계한다(요구사항 6·8).
`MANUAL_REQUIRED`는 기존 화면에서 사람이 프롬프트를 채워야 하는 상태이므로 배치에서는 실패로 취급한다.

승격은 **멱등**해야 한다. `runpod_request_items.prompt_draft_id`에 이미 행이 있으면 건너뛴다.

### 7.2 `refresh_batch_job_counters()`

`batch_jobs`의 비정규화 카운터를 자식 테이블 집계로 갱신한다. 기존
`prompt_batch_service._refresh_batch_counts`와 같은 패턴이며, 이 브랜치(`perf/server-read-performance`)가
진행 중인 "조회 시 조인 대신 미리 계산된 카운터를 읽는다" 방향과 일치한다.

### 7.3 상태 판정 (요구사항 8)

```
완료  ⇔  모든 draft가 READY 또는 FAILED(MANUAL_REQUIRED 포함)
     AND  READY에서 파생된 모든 workflow_task가 종료 상태
          (COMPLETED / PARTIAL_FAILED / FAILED / CANCELLED / TIMED_OUT)
미완료 ⇔ 그 외 전부
```

즉 실패도 종료로 본다. ③④ 대시보드는 `미완료`만 조회한다.

## 8. ZIP 다운로드 (요구사항 10 · 11)

배치 결과 영상을 하나의 ZIP으로 내려받는다. 요구사항 10의 `output` 디렉토리와 11의 파일명 규칙은
**ZIP 내부 구조**로 만족한다 — 사용자가 원하는 폴더에 압축을 풀면 그대로 나온다.

```
BATCH-20260904-0001.zip
└ output/
    image1.mp4
    image2.mp4
    image3-1.mp4
```

- ZIP 안의 최상위 디렉토리는 항상 `output/` (요구사항 10)
- 파일명 = **원본 이미지 파일명(확장자 제외) + `.mp4`** (요구사항 11). `image1.jpg` → `image1.mp4`
- 같은 이름이 이미 담겼으면 인덱스를 붙인다: `image1-1.mp4`, `image1-2.mp4`, …
  (원본 폴더에 `image1.jpg`와 `image1.png`가 함께 있는 경우)
- 압축 방식은 `ZIP_STORED`. mp4는 이미 압축되어 있어 재압축 이득이 없고 CPU만 쓴다
- 임시 파일을 만들지 않고 `StreamingResponse`로 생성기 기반 스트리밍한다.
  자산 바이트는 기존 `storage_backends` 어댑터로 읽어 로컬/S3 백엔드 모두에서 동일하게 동작한다
- 종료 상태가 아니거나 출력 자산이 없는 항목은 건너뛰고, 응답 헤더 `X-Batch-Zip-Skipped`에 건수를 담는다

다운로드 진입점은 두 곳이며 같은 엔드포인트를 쓴다.

1. **배치 내역 ⑤의 `다운로드` 열** — 그 배치 전체
2. **Task History → RunPod 이력** — batch 필터로 좁힌 뒤 선택한 항목 (§10)

## 9. 영상 길이 (Length)

**사용자가 배치 요청 전에 고른다.** 기존 RunPod 요청 관리 화면(`runpodRequestScreen`)의
`49 / 81 / 161` 버튼 그룹과 동일한 UI를 쓰고, **기본 선택은 81**이다.
선택값은 배치 전체(모든 이미지)에 동일하게 적용된다.

`requested_frames`는 `POST /batch-jobs` 요청 본문으로 전달되며, 서버는 `{49, 81, 161}` 중 하나인지
검증하고 그 외 값은 400으로 거부한다.

### 영상 길이(초) 산출

프레임 수와 함께 **초 단위 길이를 계산해 `batch_jobs.duration_seconds`에 저장**한다.

```
duration_seconds = round(requested_frames / fps)
fps = 워크플로우 output_fps 컨트롤의 default, 없으면 16
```

`fps = 16` 기준 대응표 — 화면의 Length 버튼에도 이 초 수를 함께 표시한다.

| frames | 초 |
|---|---|
| 49 | 3 |
| 81 | **5** (기본값) |
| 161 | 10 |

fps 16은 현재 RunPod 제출 payload가 실제로 쓰는 값이다
(`studio_api_service.py:417` — `config = {..., "fps": 16}`).

## 10. Task History 연동 (요구사항 13)

배치로 만들어진 프롬프트와 RunPod 작업은 **별도 이력 테이블 없이 기존 이력에 그대로 쌓인다.**
여기에 batch_id 컬럼과 필터, 그리고 ZIP 다운로드 버튼을 더한다.

- `GET /history/prompts`에 `batchId` 쿼리 파라미터 추가 → `image_prompt_drafts.batch_job_id` 필터
- `GET /history/runpod`에 `batchId` 쿼리 파라미터 추가 → `workflow_tasks.batch_job_id` 필터
- 두 응답 항목에 `batchJobId` 필드 추가
- `reviewScreens.tsx`의 프롬프트 이력·RunPod 이력 표에 **Batch ID 컬럼** 추가
- 두 표의 필터 바에 **Batch 필터**(기본값 `전체`) 추가. 선택지는 응답이 내려주는 배치 id 목록
- RunPod 이력에는 이미 행별 체크박스가 있다. 상단 액션 바(`선택 삭제` 버튼 옆)에
  **`선택 N건 ZIP 다운로드`** 버튼을 추가한다.
  ZIP은 배치 단위 엔드포인트를 쓰므로 이 버튼은 **Batch 필터가 특정 배치로 좁혀졌을 때만 활성화**된다
  (`전체`인 상태에서는 비활성 + `Batch를 선택하세요` 툴팁). 선택한 행의 `taskId` 목록을
  `taskIds` 쿼리로 넘긴다
- 기존 행별 `입력 View` / `결과 View` / `Download`는 **그대로 둔다.** 자산이 서버에 있으므로
  기존 `/api/files/{assetId}` preview가 배치 작업에도 변경 없이 동작한다
- 배치가 아닌 기존/신규 단건 작업은 Batch ID 열에 `-`로 표시된다

## 11. 데이터베이스

Alembic 마이그레이션 `20260904_0033_batch_jobs.py` (`down_revision = "20260903_0032"`).
기존 마이그레이션과 동일하게 **모든 DDL을 inspector로 존재 확인 후 조건부 실행**한다.

### 신규 테이블 `batch_jobs`

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | String(64) PK | 요구사항 7의 batch-id |
| `workflow_id` | String(191) NOT NULL | idx |
| `status` | String(32) NOT NULL | `INCOMPLETE` / `COMPLETE` — idx |
| `source_dir_name` | String(512) | 이미지 디렉토리(선택한 폴더명) |
| `requested_frames` | Integer NOT NULL | 사용자가 고른 Length (49/81/161, 기본 81) |
| `duration_seconds` | Integer NOT NULL | 영상 길이(초). §9 산출식 |
| `total_images` | Integer NOT NULL default 0 | 요청 이미지수 |
| `prompt_completed_count` | Integer NOT NULL default 0 | 프롬프트 생성 완료 건수 |
| `prompt_failed_count` | Integer NOT NULL default 0 | 프롬프트 생성 실패 건수 |
| `video_requested_count` | Integer NOT NULL default 0 | 영상 생성 요청 건수 |
| `video_completed_count` | Integer NOT NULL default 0 | 영상 생성 완료 건수 |
| `video_failed_count` | Integer NOT NULL default 0 | 영상 생성 실패 건수 |
| `last_downloaded_at` | DateTime NULL | ⑤ 다운로드 열 표시용 |
| `created_by` | String(191) FK users.id | 작업자 — idx |
| `created_at` / `updated_at` | DateTime NOT NULL | 일자 |

복합 인덱스 `ix_batch_jobs_status_created_at (status, created_at)` — ③④ 대시보드와 ⑤ 내역 조회용.

### 기존 테이블 추가 컬럼

| 테이블 | 컬럼 | 용도 |
|---|---|---|
| `prompt_generation_batches` | `batch_job_id` String(64), idx | 배치 → 프롬프트 배치 연결 |
| `runpod_request_batches` | `batch_job_id` String(64), idx | 배치 → RunPod 배치 연결 |
| `image_prompt_drafts` | `batch_job_id` String(64), idx | 프롬프트 이력 batch_id 컬럼·필터 (요구사항 13) |
| `workflow_tasks` | `batch_job_id` String(64), idx | RunPod 이력 batch_id 컬럼·필터 (요구사항 13) |

`image_prompt_drafts`·`workflow_tasks`의 `batch_job_id`는 조인으로도 구할 수 있지만 이력 필터가
자주 쓰이는 조회 경로이므로 비정규화한다(`20260903_0030_prompt_history_query_indexes`가 같은 이유로
인덱스를 추가한 전례를 따른다).

`downgrade()`는 이 리비전이 만든 구조만 제거하고 기존 이력 데이터는 건드리지 않는다.

## 12. API

신규 라우터 `backend/app/api/v1/batch_jobs.py` (prefix `/batch-jobs`).
권한은 모두 `prompts:build` + `jobs:run`을 함께 요구한다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/batch-jobs` | 배치 생성. body: `{ workflowId, sourceDirName, requestedFrames, items: [{ assetId, fileName }] }`. `requestedFrames`는 49/81/161만 허용(기본 81), 그 외는 400 |
| `GET` | `/batch-jobs/active` | ③④ 대시보드용. 미완료 배치 + 단계별 카운터 |
| `GET` | `/batch-jobs` | ⑤ 내역. query: `page`, `dateFrom`, `dateTo`, `workerId`, `status` (기본 전체), 5건 고정 |
| `GET` | `/batch-jobs/{id}/download` | §8 ZIP 스트리밍. query `taskIds`(선택)로 일부만 받을 수 있다. 응답 시 `last_downloaded_at` 갱신 |

`jobs:manage` 미보유자는 `GET /batch-jobs`·`/batch-jobs/active`에서 자기 배치만 받고,
남의 배치 ZIP은 403으로 막는다.

신규 서비스 `backend/app/services/batch_job_service.py`가 이 라우터의 유일한 로직 소유자이며,
프롬프트 생성과 RunPod 디스패치는 기존 `prompt_batch_service` / `runpod_request_batch_service` /
`runpod_dispatch_service`를 호출만 한다.

## 13. 오류 처리

| 상황 | 처리 |
|---|---|
| 폴더에 대상 이미지 0건 | 생성 버튼 비활성, `대상 이미지가 없습니다` 안내 |
| 워크플로우에 활성 지시문 없음 | 생성 버튼 비활성, 기존 화면과 동일한 안내 문구 |
| 업로드 일부 실패 | 성공분만 배치 생성, 실패 파일명 목록 표시 |
| 업로드 전부 실패 | 배치를 만들지 않고 오류만 표시 |
| 프롬프트 생성 실패 | RunPod 승격 제외, `prompt_failed_count` 집계, 배치는 계속 진행 |
| RunPod 작업 실패 | `video_failed_count` 집계, 배치는 계속 진행 |
| ZIP 대상이 0건 | 다운로드 버튼 비활성 + `내려받을 완료 영상이 없습니다` 안내 |
| ZIP 중 일부 자산 누락 | 그 항목만 건너뛰고 `X-Batch-Zip-Skipped` 헤더로 건수 전달, 화면에 안내 |
| 남의 배치 ZIP 요청 | 403 |

## 14. 테스트

`test-driven-development`에 따라 각 항목마다 실패 테스트를 먼저 쓴다.

**백엔드** (`backend/tests/test_batch_job_service.py` 신규)

1. `POST /batch-jobs`가 `batch_jobs` + `prompt_generation_batches` + N개 draft를 한 번에 만든다
2. 요청한 `requestedFrames`가 그대로 모든 draft·request item에 적용되고,
   `duration_seconds`가 `round(frames / fps)`로 저장된다 (81 → 5). 49/81/161 외의 값은 400
3. `promote_ready_batch_drafts`가 READY draft만 `runpod_request_items`로 승격한다
4. 같은 draft를 두 번 승격하지 않는다 (멱등)
5. FAILED draft는 승격되지 않고 `prompt_failed_count`에 잡힌다
6. 모든 draft가 종료 + 모든 task가 종료면 상태가 `COMPLETE`가 된다
7. `GET /batch-jobs/active`는 `COMPLETE` 배치를 제외한다
8. `GET /batch-jobs`의 일자·작업자·상태 필터와 5건 페이지네이션
9. `jobs:manage` 미보유자는 자기 배치만 받고, 남의 배치 ZIP은 403
10. ZIP 엔트리 경로가 `output/<원본명>.mp4`이고, 동일명 충돌 시 `-1` 인덱스가 붙는다
11. `/history/prompts?batchId=` · `/history/runpod?batchId=` 필터

**프론트엔드**

- `npm run build`
- 폴더 선택에서 하위 폴더 파일이 제외되고 대상 확장자만 남는 필터 로직은 순수 함수로 분리해
  단위 테스트 가능하게 둔다

**전체**: `./scripts/verify.sh`, `python3 -m compileall -q backend/app`

## 15. 구현 순서

1. 마이그레이션 `20260904_0033` + `models.py` 모델 추가
2. `batch_job_service.py` — 생성 · 승격 · 카운터 · 상태 판정 (테스트 선행)
3. `batch_job_service.py` — ZIP 스트리밍 (테스트 선행)
4. `api/v1/batch_jobs.py` 라우터 + `main.py` 라우터 등록
5. `main.py` monitor_loop에 승격·카운터 갱신 단계 추가
6. `history.py`의 `batchId` 필터 + 응답 필드
7. `router.ts` · `AppShell.tsx`(다중 권한 지원) · `client.ts` 타입/호출
8. `screens/batchJobScreen.tsx` + `styles.css`
9. `reviewScreens.tsx`의 Batch ID 컬럼·Batch 필터·선택 ZIP 다운로드 버튼
10. 빌드 · 검증

## 16. 미해결 가정

- 같은 폴더로 배치를 두 번 돌리면 별개 배치로 새로 처리한다. 중복 감지는 넣지 않는다
- 하위 폴더는 탐색하지 않는다
- 배치 단위 취소는 제공하지 않는다. 개별 Task 취소는 Task History에서 기존대로 가능하다
- 대용량 ZIP(수백 건)에 대한 분할 다운로드는 넣지 않는다. 필요해지면 별도 작업으로 다룬다
