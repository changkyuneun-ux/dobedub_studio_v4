# DOBEDUB STUDIO (ComfyUI Video Studio App) v4

RunPod Serverless ComfyUI에서 실행되는 WAN Image-to-Video 워크플로우를, 사내 사용자가 웹 UI로 실행·검수·관리할 수 있게 하는 프로젝트입니다. React(TypeScript) 프론트엔드와 FastAPI 백엔드가 한 서버에서 함께 동작하며, 프로젝트 내부 `workflows/`의 ComfyUI Export(API) JSON을 읽어 workflow/segment schema를 만들고, `.env` 설정에 따라 dry-run 또는 실제 RunPod Serverless endpoint로 작업을 제출합니다. 프롬프트는 정형화된 카탈로그(포지티브/네거티브 용어 트리)를 조합해 RunPod vLLM(Qwen)으로 생성합니다.

v4는 `design_handoff_dobedub_v3/`의 설계 문서를 기준으로 화면 전체를 업무 흐름(S1~S5) 단위로 전면 재구축한 버전입니다. 기능 단위로 흩어져 있던 구버전(v3) 모달·페이지 구조를 걷어내고, 사이드바 212px + 헤더 + 본문 + 우측 패널의 공통 레이아웃(`AppShell`)을 모든 화면이 공유하도록 다시 짰습니다.

## 실행

권장 실행:

```bash
cd comfyui-video-studio-app-v4
cp .env.example .env
python3 -m pip install -r backend/requirements.txt
python3 scripts/run_local.py
```

브라우저에서 접속:

```text
http://127.0.0.1:8787
```

React 프론트엔드는 별도 Vite 앱으로 구성되어 있습니다.

```bash
cd frontend
npm install
npm run dev
```

React 개발 서버:

```text
http://127.0.0.1:5173/studio/
```

React production build는 FastAPI의 `/studio` 경로에서 제공됩니다. 빌드 결과가 없으면 안내 placeholder가 표시됩니다.

```bash
cd frontend
npm run build
cd ..
python3 scripts/run_local.py
```

```text
http://127.0.0.1:8787/studio
```

현재 로컬 실행은 FastAPI/uvicorn 기반입니다. `server.py`는 같은 FastAPI 앱을 실행하는 호환 entrypoint로 유지됩니다.

> 이 샌드박스에서 `npm run build`가 `lightningcss` 네이티브 바이너리 누락으로 실패하면 `npx vite build --minify false`로 대체하십시오.

## 업무 흐름과 화면 구성

로그인 후 좌측 사이드바는 **GENERATE**(영상 생성 흐름)와 **ADMIN**(관리자 콘솔) 두 영역을 오가며, 두 영역 모두 하단에 **HELP**(User Manual · System Status · Metadata) 그룹을 둡니다. 아래 표의 화면 id는 `design_handoff_dobedub_v3/Screen Map.dc.html` 기준입니다.

### 1 Access — 접속 · 안내

| id | 화면 | 라우트 |
|---|---|---|
| `6a` | 로그인 | `/studio/access/login` |
| `6b` | 사용자 매뉴얼 (문서 내 검색·강조·이동 지원) | `/studio/access/manual` |
| `7g` | 403 권한 없음 / 401 세션 만료 / 서버 오류 | (권한 가드가 자동 진입) |

### 2 Create — 영상 생성 (S1~S5 핵심 흐름)

| id | 단계 | 화면 | 라우트 |
|---|---|---|---|
| `2a` | S1 이미지 로드 | 워크플로 선택 + 키프레임 업로드 | `/studio/create/load` |
| `2b`+`2e` | S2 세그먼트 설정 | 프롬프트 키워드 카탈로그(포지티브/네거티브 스코프 아코디언) + Wan Node Config를 좌우 분할로 병합 | `/studio/create/prompt` |
| `2f` | S3 실행 전 확인 | 제출 payload 확인 후 Run | `/studio/create/confirm` |
| `2c` | S4 진행 | 상태 인포그래픽 + 로그 + 취소 요청(Cancelling) | `/studio/create/progress` |
| `2d` | S5 결과 | Final 병합본 + 구간별 검수본 | `/studio/create/result` |

### 3 Review — 검수 · 자산

| id | 화면 | 라우트 |
|---|---|---|
| `3a`(+`3f`/`3c` 통합) | 작업 이력 — 목록 + 우측 패널 Overview/Assets/Node Config/Prompt Review 아코디언, 삭제 확인창 | `/studio/review/history` |
| `4c` | 프롬프트 재사용 — 서버사이드 페이지네이션(20건) | `/studio/review/reuse` |
| `5a`+`5c` 통합 | Asset 관리 — 자산 목록(작업 출력 기준) + 컬렉션 필터/칩 | `/studio/review/assets` |

### 4 Admin — 관리자 콘솔

| id | 화면 | 라우트 |
|---|---|---|
| `3b` | 역할 × 권한 매트릭스 | `/studio/admin/roles` |
| `7b` | 기능 리소스 매핑 (조회 전용) | `/studio/admin/resource-map` |
| `3e` | 사용자 목록 | `/studio/admin/users` |
| `7c` | 사용자 상세/등록 (비밀번호 초기화·비활성화 포함) | `/studio/admin/users/detail` |
| `4a` | 워크플로 정의 목록/활성화 | `/studio/admin/workflows` |
| `4d` | 워크플로 등록/갱신 | `/studio/admin/workflows/register` |
| `4e` | 프롬프트 카탈로그 계층 (스코프→그룹→서브카테고리→용어) | `/studio/admin/catalog/hierarchy` |
| `3d` | 용어 관리 (CRUD, `4e`와 같은 트리 컴포넌트 공유) | `/studio/admin/catalog/terms` |
| `4b` | Negative 기본값 (NEGATIVE 스코프 필터) | `/studio/admin/catalog/negative-defaults` |
| `7a` | 시스템 프롬프트 (LLM 지시문, 버전 이력·되돌리기) | `/studio/admin/system-prompt` |
| `5b` | Sandbox Pod 시작/정지 | `/studio/admin/sandbox` |
| — | 감사 로그 | `/studio/admin/audit-log` |

`6c`(시스템 상태)와 `6d`(메타데이터)는 설계상 ADMIN 사이드바 소속이 아니라 스튜디오 HELP 그룹 소속입니다. HELP 메뉴에서 진입하면 관리자 콘솔 쉘로 전환되지 않고 GENERATE 영역 그대로 유지됩니다(`/studio/admin/status`, `/studio/admin/metadata` 경로는 유지하되 화면은 `area="generate"`로 렌더링).

### 권한 · 역할

역할은 `SUPER_ADMIN` `ADMIN` `OPERATOR` `VIEWER` 4종입니다. 권한이 없는 메뉴는 사이드바에서 숨기고, 직접 URL 진입만 `7g` 403 화면에 도달합니다. 주요 권한 코드:

| 동작 | 권한 코드 |
|---|---|
| 작업 실행 / 취소 | `jobs:run` / `jobs:cancel` |
| 이력 조회 / 삭제 | `history:read` / `history:delete` |
| 프롬프트 생성 / 평가 / 재사용 | `prompts:build` / `prompts:review` / `prompts:reuse` |
| 카탈로그 조회 / 편집 | `prompt-catalog:read` / `prompt-catalog:write` |
| 역할 조회 / 편집 | `roles:read` / `roles:write` |
| 사용자 조회 / 편집 | `users:read` / `users:write` |
| 워크플로 조회 / 편집 / 활성화 | `workflows:read` / `workflows:write` / `workflows:activate` |
| 메타데이터 조회 / 재생성 | `metadata:read` / `metadata:rebuild` |
| 시스템 상태 조회 | `system:read` |
| Sandbox 조회 / 제어 | `sandbox:read` / `sandbox:control` |

## 구현된 API

| API | 설명 |
|---|---|
| `GET /api/health` | 헬스 체크 |
| `GET /api/system/status`, `GET /api/runpod/connection` | 시스템 상태, RunPod 연결 테스트 |
| `POST /api/auth/login`, `GET /api/auth/session`, `POST /api/auth/refresh` | 로그인, 세션 조회, 무중단 세션 연장 |
| `GET /api/workflows`, `GET /api/workflows/{id}/schema`, `GET /api/workflows/{id}/segment-defaults`, `GET /api/workflows/{id}/widget-metadata` | 워크플로 목록·schema·기본값·메타데이터 |
| `GET /api/segment-defaults`, `GET /api/segment-defaults/{workflowId}` | 세그먼트 기본값 |
| `POST /api/uploads`, `GET /api/files/{assetId}` | 이미지 업로드, 보호된 자산 다운로드 |
| `GET /api/assets` | 자산 목록(작업 출력 기준, type/workflowId/기간/컬렉션 필터 + 페이지네이션) |
| `GET/POST /api/collections`, `GET /api/collections/{id}`, `POST /api/collections/{id}/items`, `DELETE /api/collections/{id}/items/{assetId}` | 컬렉션 CRUD |
| `POST /api/jobs`, `GET /api/jobs/{taskId}`, `POST /api/jobs/{taskId}/cancel` | 작업 제출·조회·취소 |
| `GET /api/jobs/{taskId}/prompts`, `PATCH .../quality`, `PATCH .../review` | 세그먼트별 프롬프트 조회·품질/평가 저장 |
| `GET /api/history`, `POST /api/history/{taskId}/delete` | 작업 이력 조회(20건 페이지네이션)·삭제(진행 중 작업은 차단) |
| `GET /api/prompts/catalog`, `GET /api/prompts/reusable`, `GET /api/prompts/scene-schema` | 프롬프트 카탈로그, 재사용 검색, Scene schema |
| `POST /api/prompts/scene`, `POST /api/prompts/generate`, `POST /api/prompts/feedback` | Scene JSON 생성, LLM 프롬프트 생성, 피드백 저장 |
| `GET/PUT /api/prompts/system-prompt`, `GET /api/prompts/system-prompt/versions` | 시스템 프롬프트 조회/저장, 버전 이력 |
| `POST/PUT /api/prompts/category-groups`, `/categories`, `/terms` (+ `deactivate`) | 카탈로그 그룹·카테고리·용어 CRUD |
| `GET /api/metadata/status`, `GET /api/metadata/models`, `POST /api/metadata/rebuild` | 워크플로 메타데이터 조회·재생성 |
| `GET/POST /api/admin/users`, `PUT /api/admin/users/{id}`, `POST .../deactivate`, `POST .../reset-password` | 사용자 CRUD, 비활성화, 비밀번호 초기화 |
| `GET /api/admin/permissions`, `PUT /api/admin/roles/{roleCode}/permissions` | 역할×권한 매트릭스, 기능 리소스 매핑 |
| `GET/POST /api/admin/workflows`, `POST .../activate`, `POST .../deactivate` | 워크플로 정의 등록·활성화 |
| `GET /api/admin/audit-logs` | 감사 로그 조회(권한 변경·사용자 변경·카탈로그 수정·Sandbox 제어) |
| `GET/POST /api/admin/sandbox-pod`, `POST .../start`, `POST .../stop` | Sandbox Pod 상태·시작·정지 |
| `GET /manual` | 사용자 매뉴얼 HTML (검색 지원 iframe으로 렌더) |
| `GET/POST /api/configs`, `POST/GET /api/reports` | 코드·테이블은 유지하되 화면·프론트 호출은 **연결하지 않음**(D-01 결정) |

## 환경변수

로컬 서버는 앱 폴더의 `.env` 파일을 자동으로 읽습니다. 먼저 샘플을 복사한 뒤 실제 값을 입력합니다. **전체 목록·최신 기본값의 정본은 `.env.example`입니다** — 아래는 용도별 핵심 값만 발췌한 것입니다.

```bash
cp .env.example .env
```

**경로 · 저장소**

```bash
WORKFLOWS_DIR=./workflows
WORKFLOW_SEED_DIR=./workflows
STUDIO_DATA_DIR=./data
METADATA_DIR=./metadata
OUTPUTS_DIR=./data/outputs
PERSISTENCE_BACKEND=json      # json | db — 운영은 db, 이력·자산 경로는 항상 db만 사용(D-03)
DATABASE_URL=mysql+pymysql://dobedub:dobedub_password@127.0.0.1:3306/dobedub_studio
STORAGE_BACKEND=local         # local | s3
S3_BUCKET=
```

**인증**

```bash
AUTH_JWT_SECRET=replace_with_a_long_random_secret
AUTH_TOKEN_TTL_MINUTES=480
```

**RunPod Serverless (ComfyUI 영상 생성)**

```bash
RUNPOD_DRY_RUN=1
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_runpod_endpoint_id
RUNPOD_BASE_URL=https://api.runpod.ai/v2
RUNPOD_TIMEOUT=30
PORT=8787
```

실제 RunPod Serverless에 제출하려면 `RUNPOD_DRY_RUN=0`으로 실행하고 `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`를 설정합니다. 이때 서버는 프로젝트 내부 workflow JSON을 패치하고 업로드 이미지를 RunPod `images` payload로 변환한 뒤 `/run`과 `/status/{jobId}`를 사용합니다.

**RunPod Sandbox Pod (`5b` 화면 전용)** — 영상 생성용 Serverless 설정과 별개로, ComfyUI를 직접 켜고 끄는 Pod 접근에만 씁니다.

```bash
RUNPOD_SANDBOX_NETWORK_VOLUME_ID=   # Pod 재배치에도 안정적인 기본 식별자
RUNPOD_SANDBOX_TEMPLATE_ID=         # 선택. RunPod Pods API가 주는 template id(사람이 읽는 이름 아님)
RUNPOD_SANDBOX_GPU_TYPE_ID=NVIDIA GeForce RTX 5090
RUNPOD_SANDBOX_GPU_COUNT=1
RUNPOD_SANDBOX_DEPLOY_NAME=dobedub_comfyUI_Sandbox
RUNPOD_SANDBOX_POD_API_KEY=
RUNPOD_SANDBOX_POD_REST_URL=https://rest.runpod.io/v1
RUNPOD_SANDBOX_POD_TIMEOUT=20
```

> **실행 모드 기본값**: 서버 코드의 실제 기본값은 `RUNPOD_DRY_RUN=0`(실제 실행)입니다. 운영 배포 문서(`docs/ecs-express-deployment-runbook.md` 외)가 모두 이 값을 운영 환경 필수값으로 명시하고 있어 코드 기본값을 여기에 맞췄습니다. 로컬에서 안전하게 시뮬레이션하려면 위처럼 `.env`에 `RUNPOD_DRY_RUN=1`을 **명시적으로** 설정하십시오 — 생략하면 `RUNPOD_API_KEY`/`RUNPOD_ENDPOINT_ID`가 없는 환경에서 조용히 dry-run으로 넘어가는 대신 설정 누락 오류로 즉시 실패합니다.

실행 후 스튜디오 `System Status`(HELP 메뉴)에서 `Test ComfyUI`를 누르면 실제 작업을 생성하지 않고 RunPod `/health`만 호출해 endpoint 접근, worker 상태, queue 상태를 확인합니다.

### Prompt LLM RunPod vLLM 연결

프롬프트 생성(`2b` 화면의 `프롬프트 생성 · Qwen`)은 기본값 `PROMPT_LLM_PROVIDER=mock`일 때 로컬 deterministic mock으로 동작합니다. 실제 RunPod vLLM endpoint를 사용하려면 영상 생성용 RunPod endpoint와 별도로 prompt 전용 endpoint를 설정합니다.

RunPod Serverless native `/runsync` 방식:

```bash
PROMPT_LLM_PROVIDER=runpod_vllm
PROMPT_LLM_API_KEY=your_runpod_api_key
PROMPT_LLM_ENDPOINT_ID=your_prompt_vllm_endpoint_id
PROMPT_LLM_ENDPOINT_URL=
PROMPT_LLM_MODEL=your-model-name
PROMPT_LLM_RUNPOD_INPUT_MODE=prompt
PROMPT_LLM_TEMPERATURE=0.2
PROMPT_LLM_MAX_TOKENS=900
PROMPT_LLM_TIMEOUT=90
```

`PROMPT_LLM_ENDPOINT_URL`에 전체 URL을 직접 넣는 것도 가능합니다. 예: `https://api.runpod.ai/v2/{PROMPT_ENDPOINT_ID}` 또는 `https://api.runpod.ai/v2/{PROMPT_ENDPOINT_ID}/runsync`.

RunPod vLLM quick start가 `{"input":{"prompt":"..."}}` 형태를 안내하므로 `PROMPT_LLM_RUNPOD_INPUT_MODE=prompt`가 기본값입니다. handler가 `messages`를 받도록 구성된 경우에만 `PROMPT_LLM_RUNPOD_INPUT_MODE=messages`로 바꿉니다.

콜드스타트로 인한 502/503/504는 `prompt_llm_client.py`가 최대 4회(백오프 3·5·8초)까지 자동 재시도합니다.

vLLM OpenAI-compatible 방식:

```bash
PROMPT_LLM_PROVIDER=openai_compatible
PROMPT_LLM_API_KEY=your_runpod_api_key
PROMPT_LLM_ENDPOINT_URL=https://api.runpod.ai/v2/{PROMPT_ENDPOINT_ID}/openai/v1
PROMPT_LLM_MODEL=your-model-name
```

프론트엔드는 provider를 강제로 지정하지 않습니다. 따라서 서버 `.env`의 `PROMPT_LLM_PROVIDER` 값이 실제 prompt generation 방식을 결정합니다.

## 로컬 검증

```bash
python3 scripts/fastapi_smoke_check.py
python3 scripts/fastapi_http_smoke_check.py
python3 scripts/local_smoke_check.py
python3 scripts/db_migration_smoke_check.py
python3 scripts/db_adapter_smoke_check.py
python3 scripts/json_to_db_migration_smoke_check.py
python3 scripts/storage_backend_smoke_check.py
python3 scripts/persistence_backend_smoke_check.py
python3 scripts/prompt_db_smoke_check.py
python3 scripts/frontend_smoke_check.py
```

React build/audit 확인:

```bash
cd frontend
npx tsc -b
npm run build
npm audit --omit=dev
```

`fastapi_http_smoke_check.py`가 현재 기본 로컬 실행 경로를 검증합니다. `local_smoke_check.py`는 `python3 server.py` 호환 entrypoint가 같은 FastAPI 앱으로 뜨는지 확인합니다.

로컬 MySQL까지 확인하려면:

```bash
docker compose -f docker-compose.dev.yml up -d mysql
python3 scripts/mysql_migration_smoke_check.py
```

현재 JSON 데이터를 로컬 MySQL로 이관하려면:

```bash
python3 scripts/migrate_json_to_db.py --apply \
  --database-url mysql+pymysql://dobedub:dobedub_password@127.0.0.1:3306/dobedub_studio
```

저장소 전환은 환경변수로 제어합니다. 운영 기준은 DB이며, 이력·자산 관련 경로는 항상 DB만 사용합니다(JSON 경로는 이관 도구 전용).

```bash
PERSISTENCE_BACKEND=json
PERSISTENCE_BACKEND=db
```

`STORAGE_BACKEND=s3`용 adapter는 구현되어 있지만, 실제 AWS S3 런타임 연결은 AWS 배포 단계에서 파일 미리보기/다운로드 응답 정책과 함께 활성화합니다.

## 의도적으로 범위에서 제외한 항목

아래는 버그가 아니라 설계 단계에서 결정된 범위 제외입니다. 근거는 `design_handoff_dobedub_v3/TASKS.md`의 각 항목 각주에 있습니다.

- **컬렉션 태그·공개범위(PRIVATE/SHARED)** — 대응 백엔드 컬럼이 없어 `Asset 관리` 화면에서 제외(A-02).
- **알림 센터(`6e`)** — 영속 저장(테이블+읽음 상태)이 전제인 화면이라, 현재는 작업 종료 시 6초짜리 토스트(1안)만 제공합니다. 2안(알림 테이블)이 필요해지면 토스트는 유지한 채 센터 화면만 추가하면 됩니다(A-03).
- **로그인 접근 이력** — 한때 감사 로그에 `action="login"`으로 흡수했으나, "관리자 정보 수정사항만 남긴다"는 결정에 따라 기록 지점 자체를 제거했습니다. 사용자 상세(`7c`) 화면의 접근 이력 섹션도 함께 제거되었습니다(A-04/A-05).
- **구형 `prompt_terms`/`prompt_categories` 테이블 드롭** — 신형 카탈로그 계층(그룹→서브카테고리→용어) 이관은 완료되어 코드 어디도 구형 테이블을 참조하지 않지만, 테이블 자체의 드롭은 별도 릴리스로 미뤄두었습니다(B-06).
- **SYSTEM 프롬프트 그룹** — 화면상 POSITIVE·NEGATIVE·SYSTEM 3그룹처럼 보이지만, DB 스코프는 POSITIVE/NEGATIVE 둘뿐입니다. 시스템 지시문은 `prompt_system_prompts`라는 별도 테이블(code당 1건 + 버전 이력)로, 카탈로그 트리와 무관한 별도 화면(`7a`)입니다(B-07).
- **리포트·구성 프리셋(`reports`/`configs`)** — API·테이블은 유지하되 화면·프론트 연결은 만들지 않기로 결정했습니다(D-01).

## 참조 문서

- `design_handoff_dobedub_v3/README.md` — 화면 재설계 개요, Design Tokens, 진행 방식
- `design_handoff_dobedub_v3/TASKS.md` — 수행 리스트(0단계 권한 정렬 → A 신규 개발 → B 기존 코드 수정 → C 화면 구현 → D 결정 사항 → E 화면 전면 재구축). 모든 항목이 완료되었고, 이후 실사용 중 발견된 버그 수정·UX 개선 이력이 항목별 각주로 날짜순 기록되어 있습니다.
- `design_handoff_dobedub_v3/CHECKLIST.md` — 착수 전 확인, 화면 구현 중 규칙, 종료 전 검증 체크리스트
- `design_handoff_dobedub_v3/Screen Map.dc.html`, `*.dc.html` — 화면별 고fidelity 디자인 레퍼런스(그대로 복사할 production 코드 아님)
- `docs/dobedub-studio-user-manual.md` — 실제 사용자 매뉴얼 원문(`/manual` 라우트가 렌더하는 문서)
- `docs/rbac-feature-permission-governance.md` — 권한·역할 거버넌스
- `docs/prompt-ddl-and-generation-logic.md` — 프롬프트 카탈로그 스키마·생성 로직
- `docs/db-persistence-mapping.md` — JSON ↔ DB 저장소 매핑
- `docs/aws-ecs-deployment.md`, `docs/ecs-express-deployment-runbook.md`, `docs/ecs-production-deployment-checklist.md` — 배포 문서
- `docs/runpod-model-cleanup-guide.md` — RunPod 모델 정리 가이드
- `./workflows` — ComfyUI Export(API) 워크플로 JSON
