# ComfyUI Video Studio App

RunPod Serverless에서 실행되는 ComfyUI Export(API) 워크플로우를 사내 사용자가 웹 UI로 실행하기 위한 새 프로젝트입니다.

현재 버전은 프론트 UI와 로컬 API 서버가 함께 동작하는 구현입니다. API 서버는 프로젝트 내부 `workflows/`의 ComfyUI Export(API) JSON을 읽어 workflow/segment schema를 만들고, `.env` 설정에 따라 dry-run 또는 실제 RunPod Serverless endpoint로 작업을 제출합니다.

## 실행

권장 실행:

```bash
cd comfyui-video-studio-app-v4
python3 -m pip install -r backend/requirements.txt
python3 scripts/run_local.py
```

브라우저에서 접속:

```text
http://127.0.0.1:8787
```

React 프론트엔드 skeleton은 별도 Vite 앱으로 병렬 구성되어 있습니다.

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

현재 React skeleton 구현 범위:

- login/logout shell
- workflow list 조회
- workflow schema 로드
- schema 기반 subgraph segment 목록
- schema 기반 keyframe upload slot
- 이미지 선택/미리보기 및 `/api/uploads` 업로드
- segment별 positive/negative prompt 입력
- schema `configControls` 기반 Wan node config 렌더링
- generation payload preview
- `/api/jobs` 기반 generation submit
- job status polling 기반 progress/log 표시
- 생성 중 cancel request
- output asset preview/download
- 우측 패널 `Output Assets` 현재 작업 결과 요약
- History/Saved Videos 모달
- history 10개 단위 페이지네이션, 상세보기, prompt copy
- history 재작업 로드
- history 삭제 확인 및 삭제 API 연결
- Check Status 모달
- User Manual 모달
- Metadata View 모달
- Prompt Builder 모달

정적 UI만 확인하려면 아래 파일을 직접 열 수도 있습니다. 이 경우 API 호출은 fallback mock 데이터로 동작합니다.

```text
index.html
```

현재 로컬 실행은 FastAPI/uvicorn 기반입니다. 기존 `server.py`는 같은 FastAPI 앱을 실행하는 호환 entrypoint로 유지합니다.

## 포함 화면

- 로그인 화면
  - ID, Password, Name 필수 입력
  - 외부 SSO 없음
- 메인 대시보드
  - workflow 선택
  - workflow 입력 이미지 수에 맞춘 고정 keyframe upload 슬롯
  - 다중 이미지 선택 시 슬롯 순서대로 자동 배치
  - 슬롯별 이미지 미리보기, 교체, 삭제
  - segment 선택
  - segment별 positive/negative prompt 편집
  - FPS, Frames, Steps, CFG Scale, Motion Shift, Seed 설정
  - generation progress
  - RunPod status log
  - output preview/download
- 작업이력 모달
  - 작업 리스트
  - 작업 상세
  - node config
  - output preview
  - 재작업
  - 삭제
- 상태 확인 모달
  - system status
  - RunPod connection test
  - workflow/defaults/metadata/storage 상태
- 사용자 매뉴얼 모달
  - `/manual` HTML 문서 표시
- Metadata View 모달
  - workflow별 widget metadata 조회
  - subgraph/parameter/model/node 정보
  - metadata rebuild

## React 이관 보류 항목

아래 기능은 Prompt 생성 작업 결과를 확인한 뒤 유지, 통합, 제거 여부를 다시 결정합니다. 따라서 현재 React 이관 완료 기준에는 포함하지 않습니다.

- `Load Past Prompts`
- `Generate Report`

## 구현된 API

- `GET /api/health`
- `GET /api/system/status`
- `GET /api/runpod/connection`
- `GET /api/workflows`
- `GET /api/workflows/{workflowId}/schema`
- `POST /api/auth/login`
- `POST /api/uploads`
- `POST /api/jobs`
- `GET /api/jobs/{taskId}`
- `GET /api/history`
- `GET /api/configs`
- `POST /api/configs`
- `GET /api/prompts/catalog`
- `POST /api/prompts/seed`
- `POST /api/prompts/scene`
- `POST /api/prompts/generate`
- `POST /api/prompts/feedback`
- `POST /api/reports`
- `GET /api/reports/{reportId}`
- `GET /api/files/{assetId}`

`GET /api/prompts/catalog`는 Prompt Builder와 Admin Prompt Catalog가 공통으로 사용하는 단일 카탈로그 조회 API입니다.

## 환경변수

로컬 서버는 앱 폴더의 `.env` 파일을 자동으로 읽습니다. 먼저 샘플을 복사한 뒤 실제 값을 입력합니다.

```bash
cp .env.example .env
```

```bash
WORKFLOWS_DIR=./workflows
STUDIO_DATA_DIR=./data
OUTPUTS_DIR=./data/outputs
RUNPOD_DRY_RUN=1
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_runpod_endpoint_id
PROMPT_LLM_PROVIDER=mock
PROMPT_LLM_API_KEY=
PROMPT_LLM_ENDPOINT_ID=
PROMPT_LLM_ENDPOINT_URL=
PROMPT_LLM_MODEL=
PROMPT_LLM_RUNPOD_INPUT_MODE=prompt
PROMPT_LLM_TEMPERATURE=0.2
PROMPT_LLM_MAX_TOKENS=900
PROMPT_LLM_TIMEOUT=45
PORT=8787
```

실제 RunPod Serverless에 제출하려면 `RUNPOD_DRY_RUN=0`으로 실행하고 `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`를 설정합니다. 이때 서버는 프로젝트 내부 workflow JSON을 패치하고 업로드 이미지를 RunPod `images` payload로 변환한 뒤 `/run`과 `/status/{jobId}`를 사용합니다.

> **B-04·실행 모드 기본값**: 서버 코드의 실제 기본값은 `RUNPOD_DRY_RUN=0`(실제 실행)입니다. 운영 배포 문서(`docs/ecs-express-deployment-runbook.md` 외)가 모두 이 값을 운영 환경 필수값으로 명시하고 있어 코드 기본값을 여기에 맞췄습니다. 로컬에서 안전하게 시뮬레이션하려면 위 `.env.example`처럼 `RUNPOD_DRY_RUN=1`을 **명시적으로** 설정하세요 - 이 값을 생략하면 `RUNPOD_API_KEY`/`RUNPOD_ENDPOINT_ID`가 없는 환경에서는 조용히 dry-run으로 넘어가는 대신 설정 누락 오류로 즉시 실패합니다.

실행 후 상단 `Check Status` 모달에서 `Test RunPod`를 누르면 실제 작업을 생성하지 않고 RunPod `/health`만 호출해 endpoint 접근, worker 상태, queue 상태를 확인합니다.

### Prompt LLM RunPod vLLM 연결

Prompt Builder의 `Generate Prompt`는 기본값 `PROMPT_LLM_PROVIDER=mock`일 때 로컬 deterministic mock으로 동작합니다. 실제 RunPod vLLM endpoint를 사용하려면 영상 생성용 RunPod endpoint와 별도로 prompt 전용 endpoint를 설정합니다.

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

저장소 전환은 환경변수로 제어합니다. 기본값은 기존 JSON 저장소입니다.

```bash
PERSISTENCE_BACKEND=json
PERSISTENCE_BACKEND=db
```

`STORAGE_BACKEND=s3`용 adapter는 구현되어 있지만, 실제 AWS S3 런타임 연결은 AWS 배포 단계에서 파일 미리보기/다운로드 응답 정책과 함께 활성화합니다.

## 다음 구현 단계

1. Prompt DB 및 Prompt Builder를 설계/구현합니다.
2. Prompt category/term schema와 seed data를 작성합니다.
3. Prompt Builder가 scene JSON을 생성하는 API를 추가합니다.
4. 기존 positive/negative 직접 입력 방식과 Prompt Builder 결과 적용 흐름을 병행합니다.
5. 이후 LLM 프롬프트 생성 연동, JSON Schema 검증, 프롬프트 생성/수정/평가 이력 저장을 진행합니다.
6. Prompt 생성 결과를 검토한 뒤 `Load Past Prompts`, `Generate Report`의 유지/통합/제거 여부를 결정합니다.

## 참조 문서

- `../docs/comfyui-video-studio-ui-design.md`
- `../docs/serverless-comfyui-app-implementation-design.md`
- `./workflows`
