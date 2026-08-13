# DOBEDUB STUDIO v3 리팩터링 진행 체크리스트

작성일: 2026-08-02  
기준 문서: `docs/refactor-and-prompt-llm-advancement-plan.md`

## 운영 원칙

- ECS 배포는 사용자 승인 시에만 수행한다. 현재 단계는 운영 배포 전 preflight 검증과 배포 문서 정비까지 포함한다.
- 각 단계는 로컬 검증을 통과한 뒤 다음 단계로 진행한다.
- 가능한 단계마다 자동 smoke test를 추가하거나 갱신한다.
- 기존 monolith 앱의 동작을 먼저 보존한 뒤 구조를 나눈다.
- GitHub 동기화는 사용자 지시 또는 단계 완료 보고 시점에만 수행한다.

## Step 0. 기준선 고정 및 회귀 테스트

- [x] v3 독립 작업 폴더 생성
- [x] v3 GitHub 저장소 동기화
- [x] 불필요한 `Workflow2/` 제거
- [x] 로컬 smoke test 스크립트 추가
- [x] 현재 monolith API 기준 smoke test 통과
- [x] 기존 주요 기능별 수동 확인 항목 문서화

로컬 확인 명령:

```bash
python3 scripts/local_smoke_check.py
python3 -m py_compile server.py
node --check src/app.js
```

## Step 1. FastAPI 백엔드 skeleton

- [x] `backend/` 디렉토리 생성
- [x] FastAPI 앱 skeleton 추가
- [x] config/settings 모듈 추가
- [x] `/api/v1/health` 구현
- [x] 기존 monolith와 병렬 실행 가능하게 구성
- [x] smoke test에 FastAPI health 확인 추가

로컬 확인 기준:

- monolith smoke test 통과
- FastAPI `/api/v1/health` 응답 확인
- 기존 UI 파일은 아직 변경하지 않음

로컬 확인 명령:

```bash
python3 scripts/fastapi_smoke_check.py
python3 scripts/local_smoke_check.py
python3 -m py_compile server.py scripts/local_smoke_check.py scripts/fastapi_smoke_check.py backend/app/main.py
node --check src/app.js
```

## Step 2. 서비스 계층 추출

- [x] workflow 조회 service wrapper 추가
- [x] segment defaults 조회 service wrapper 추가
- [x] metadata 조회 service wrapper 추가
- [x] FastAPI workflow/metadata 조회 endpoint 추가
- [x] monolith `system_status`에 Segment Defaults/Metadata 진단 정보 추가
- [x] `Check Status` 모달에 Segment Defaults/Metadata 상태 카드 추가
- [x] ECS/EFS 경로 차이에 대비한 bundled segment defaults fallback 확인
- [x] `.env`보다 실제 환경변수가 우선되도록 로더 수정
- [x] metadata rebuild 동시 실행 시 고정 tmp 파일명 충돌 이슈 진단
- [x] JSON 파일 저장을 고유 tmp 파일명과 process lock 기반으로 안정화
- [x] monolith/FastAPI smoke test가 repo `metadata/*.json`을 갱신하지 않도록 임시 metadata 경로로 격리
- [x] workflow parser 추출
- [x] segment defaults loader 추출
- [x] FastAPI workflow service의 `server.py` 직접 의존 제거
- [x] metadata loader 추출
- [x] FastAPI metadata service의 `server.py` 직접 의존 제거
- [x] FastAPI health service의 `legacy_monolith` wrapper 의존 제거
- [x] `legacy_monolith.py` wrapper 파일 제거
- [x] RunPod client 독립 모듈 추가
- [x] asset storage 독립 모듈 추가
- [x] monolith job 실행 경로에서 RunPod client 모듈 사용하도록 전환
- [x] monolith asset 파일명/인코딩/등록/삭제 가드 경로에서 asset storage 모듈 사용하도록 전환
- [x] monolith history/assets/configs JSON repository 경로를 `json_repository` 모듈로 전환
- [x] local smoke test에 upload/download/history delete/config save-list 회귀 검증 추가
- [x] monolith와 FastAPI가 workflow parser/metadata/defaults service 함수를 재사용하도록 조정
- [x] monolith `server.py`의 미사용 metadata builder/read-write helper 중복 제거
- [x] job orchestration service 추출
- [x] monolith `server.py`의 job create/status/cancel/history-save public 함수가 `job_service`를 사용하도록 전환
- [x] local smoke test에 dry-run job complete/history-save/cancel 회귀 검증 추가
- [x] workflow patch service 추출
- [x] output classification/save service 추출
- [x] monolith `server.py`의 workflow patch/output public 함수가 service wrapper를 사용하도록 전환
- [x] FastAPI auth/upload/file/job/history/config/prompt/report/system/segment-defaults/manual router 추가
- [x] FastAPI `/api/v1/...`와 기존 프론트 호환용 `/api/...` 경로 병행 제공
- [x] FastAPI manual HTML 및 `/docs/manual-assets/...` 정적 리소스 제공 경로 추가
- [x] FastAPI 루트 `/`와 `/index.html`에서 기존 vanilla UI 정적 서빙 추가
- [x] FastAPI `/src/*` 정적 리소스 제공 경로 추가
- [x] 로컬 기본 실행 스크립트 `scripts/run_local.py` 추가
- [x] Docker 기본 CMD를 FastAPI 실행으로 전환
- [x] 운영용 Docker CMD를 `scripts/run_server.py`로 전환
- [x] `server.py` monolith HTTP handler 제거
- [x] `server.py`를 FastAPI 실행 호환 entrypoint로 축소
- [x] `scripts/local_smoke_check.py`를 `server.py` 호환 entrypoint smoke로 전환

로컬 확인 기준:

- monolith smoke test 통과
- FastAPI workflow endpoint 최소 1개 통과
- workflow parser 결과가 monolith workflow schema/list 결과와 동일함
- metadata loader 핵심 결과가 monolith metadata 결과와 동일함
- smoke test 후 repo metadata 파일이 추가로 변경되지 않음

현재 확인된 리스크:

- RunPod `/run`, `/status`, `/cancel`, `/health` 호출은 `runpod_client`를 사용한다.
- asset 파일명 정규화, data URL decode, base64 encode, asset record 생성, managed path 삭제 가드는 `asset_storage`를 사용한다.
- `history.json`, `assets.json`, `configs.json` 읽기/쓰기와 hydration/delete/register/upload/get asset 로직은 `json_repository`를 사용한다.
- monolith `server.py`의 workflow/schema/list/metadata/defaults public 함수는 compatibility wrapper로 남아 있지만 내부 구현은 FastAPI와 같은 service 함수를 사용한다.
- job create/status/cancel/history-save orchestration은 `job_service`를 사용한다.
- workflow image/prompt/node config patch 로직은 `workflow_patch_service`를 사용한다.
- SaveVideo final/segment output 판별 및 RunPod output asset 저장 로직은 `output_service`를 사용한다.
- `server.py`의 monolith HTTP handler는 제거되었다. 현재 `server.py`는 FastAPI 앱 실행 wrapper다.
- 기존 monolith API 회귀 기준선은 FastAPI smoke와 `server.py` entrypoint smoke로 대체되었다.
- 로컬은 DB adapter와 JSON legacy 병합을 병행한다. 운영 ECS/RDS 전환 시 migration 실행 순서와 asset storage 정책을 별도로 확정해야 한다.
- DB 로그인과 서버 서명 JWT 기반 API 인증 1차 전환은 완료했다. `AUTH_JWT_SECRET`은 ECS에서 반드시 secret으로 주입해야 한다.

2026-08-02 추가 검증:

- `python3 scripts/fastapi_smoke_check.py` 통과
- `python3 scripts/local_smoke_check.py` 통과
- `python3 -m py_compile server.py scripts/local_smoke_check.py scripts/fastapi_smoke_check.py backend/app/core/config.py backend/app/main.py backend/app/services/*.py backend/app/api/v1/*.py` 통과
- `node --check src/app.js` 통과
- `git diff --check` 통과
- workflow parser schema/list parity 확인 통과
- metadata loader 핵심 필드 parity 확인 통과
- RunPod client/asset storage 순수 함수 smoke 확인 통과
- monolith RunPod/asset delegated utility parity 확인 통과
- smoke test 전후 repo `metadata/*.json` diff fingerprint 동일 확인
- json repository delegated utility smoke 확인 통과
- local smoke에서 upload/download/history delete/config save-list HTTP 경로 확인 통과
- monolith workflow/metadata/defaults service reuse parity 확인 통과
- job service dry-run smoke 확인 통과
- local smoke에서 dry-run job complete/history-save/cancel HTTP 경로 확인 통과
- workflow patch/output service parity 확인 통과
- workflow patch/output service 추출 후 `python3 scripts/local_smoke_check.py` 재통과
- local smoke 재실행 전후 repo `metadata/*.json` diff fingerprint 동일 확인
- 확장된 `python3 scripts/fastapi_smoke_check.py`에서 `/api` 호환 경로, login/upload/file range/job complete/history/prompts/config/report/cancel/manual 확인 통과
- FastAPI router 추가 후 `python3 scripts/local_smoke_check.py` 재통과
- `python3 scripts/fastapi_http_smoke_check.py`에서 FastAPI 로컬 HTTP 실행, `/`, `/src/styles.css`, `/manual`, `/api/workflows` 확인 통과
- `python3 scripts/run_local.py` 기본 포트 실행 후 `http://127.0.0.1:8787/api/health`가 `backend=fastapi`로 응답 확인
- `http://127.0.0.1:8787/` 메인 HTML에서 manual placeholder 치환 확인
- `server.py` monolith handler 제거 후 `python3 scripts/local_smoke_check.py`에서 호환 entrypoint 확인 통과

## Step 3. MySQL 도입 준비

- [x] SQLAlchemy/Alembic 설정
- [x] MySQL schema 초안 migration 작성
- [x] JSON repository adapter와 DB repository adapter 인터페이스 분리 초안
- [x] `docker-compose.dev.yml`에 MySQL 추가
- [x] migration dry-run 또는 SQLite 대체 검증 전략 확정
- [x] ECS/RDS 환경변수 및 migration 운영 방식 문서화
- [x] 로컬 MySQL migration smoke script 추가
- [x] 로컬 MySQL 컨테이너 기준 Alembic migration 적용 확인
- [x] DB adapter query/command mapping 구현
- [x] JSON history/assets/configs를 DB로 이관하는 one-off migration script 작성
- [x] asset storage S3 adapter 구현
- [x] 운영 전환 플래그(`PERSISTENCE_BACKEND=json|db`) 적용

로컬 확인 기준:

- migration 생성/검증
- 기존 JSON adapter 동작 유지

2026-08-02 추가 검증:

- `python3 scripts/db_migration_smoke_check.py` 통과
- 임시 SQLite DB 기준 Alembic `upgrade head` 및 핵심 table 생성 확인 통과
- `docker compose -f docker-compose.dev.yml ps`에서 `dobedub-studio-mysql` healthy 확인
- `python3 scripts/mysql_migration_smoke_check.py` 통과
- 로컬 MySQL 기준 Alembic `upgrade head`, 핵심 table 생성, smoke user upsert 확인 통과
- `docs/db-persistence-mapping.md`에 JSON history/assets/configs -> DB table/column 매핑 기준 작성
- `python3 scripts/db_adapter_smoke_check.py` 통과
- DB adapter 기준 upload/register asset, append/load history, append/load config, delete history/asset file smoke 확인 통과
- `python3 scripts/json_to_db_migration_smoke_check.py` 통과
- `python3 scripts/storage_backend_smoke_check.py` 통과
- `python3 scripts/persistence_backend_smoke_check.py` 통과
- `python3 scripts/migrate_json_to_db.py --apply --database-url mysql+pymysql://dobedub:dobedub_password@127.0.0.1:3306/dobedub_studio` 통과
- 로컬 MySQL 기준 현재 JSON assets 39개, history 10개, configs 2개 이관 확인
- `PERSISTENCE_BACKEND=db` API smoke에서 upload/file/config/history 조회 확인 통과
- S3 adapter는 저장/삭제/presigned URL 단위 구현 및 fake client smoke 검증 완료. 실제 AWS S3 런타임 연결은 AWS 배포 단계에서 파일 응답 정책과 함께 진행한다.

## Step 4. React 프론트 skeleton

- [x] `frontend/` Vite + React + TypeScript 생성
- [x] 라우터 구성
- [x] API client 구성
- [x] Login/Studio shell 구현
- [x] 기존 vanilla UI와 병렬 유지

로컬 확인 기준:

- React dev server 실행
- `/login`, `/studio` 렌더 확인
- 기존 monolith UI 동작 유지

2026-08-02 추가 검증:

- `frontend/package.json`, `vite.config.ts`, TypeScript 설정, React entrypoint 추가
- React app은 Vite dev server 기준 `/studio/` base로 구성
- FastAPI는 `frontend/dist`가 있으면 `/studio`에서 React build를 서빙하고, build 전에는 안내 placeholder를 표시
- Dockerfile에 frontend Node build stage 추가. 최종 Python image는 `/app/frontend/dist`를 포함한다.
- `python3 scripts/frontend_smoke_check.py` 통과
- `npm run build` 통과
- `npm audit --omit=dev` 취약점 0개 확인
- 기존 vanilla UI `/` 경로는 유지
- `/api/workflows` 배열 응답 기준으로 React API client 수정
- workflow 선택 시 `/api/workflows/{workflowId}/schema` 로드
- schema의 `segments`, `keyframeCount`, `configControls` 기준으로 React segment/keyframe/config 상태 구성
- 이미지 선택 시 preview URL 생성 및 `/api/uploads` 업로드 연결
- React payload preview에서 `workflowId`, `keyframes`, `segments`, config snapshot 확인 가능
- React `GENERATE VIDEO`에서 `/api/jobs` 제출 연결
- React job polling으로 progress/log/segment progress 갱신 연결
- React 생성 중 `/api/jobs/{taskId}/cancel` 취소 요청 연결
- React output asset 기준 preview video/download 링크 연결
- React 우측 패널의 중복 `Recent History` 제거 및 현재 작업 `Output Assets` 요약으로 대체
- React History/Saved Videos 모달 연결
- React history 10개 단위 페이지네이션, 상세 탭, prompt copy 연결
- React history 재작업으로 workflow/input assets/segment prompt/config 복원 연결
- React history 삭제 확인창 및 `/api/history/{taskId}/delete` 연결
- React Check Status 모달과 `/api/system/status`, `/api/runpod/connection` 연결
- React User Manual 모달과 `/manual` HTML 조회 연결
- React Metadata View 모달과 workflow widget metadata/status/models/rebuild 연결
- `Load Past Prompts`와 `Generate Report`는 현재 UI 범위에서 제거한다.
- `/studio/history`, `/studio/status`, `/studio/metadata`, `/studio/manual`, `/studio/admin` 페이지 라우트 전환을 반영한다.
- TanStack Query는 현재 단계에서 진행하지 않고 `apiClient + useState/useEffect` 기준을 유지한다.
- `python3 scripts/fastapi_http_smoke_check.py`에서 `/studio` 최신 build 서빙 확인 통과

## Step 5A. Prompt DB 및 Prompt Builder v0

- [x] prompt category/term schema 작성
- [x] prompt rule/template/generation request/output/feedback schema 작성
- [x] 예시 catalog 데이터 작성
- [x] prompt catalog 조회 API
- [x] prompt builder scene JSON 생성 API
- [x] positive/negative 직접 입력 방식과 병행 유지
- [x] React Prompt Builder UI
- [x] Prompt Builder 결과를 현재 segment prompt field에 적용
- [x] `Load Past Prompts`/`Generate Report` UI 제거

로컬 확인 기준:

- 카테고리/키워드 조회 가능
- scene JSON 생성 가능
- Studio에서 Prompt Builder 모달을 열고 term 선택 후 현재 서브그래프에 positive/negative 초안 적용 가능

2026-08-02 추가 검증:

- `prompt_categories`, `prompt_terms`, `prompt_term_relations`, `prompt_rules`, `prompt_templates`, `prompt_generation_requests`, `prompt_generation_outputs`, `prompt_feedback` migration 추가
- `/api/prompts/catalog` 조회 API 추가
- Prompt catalog 예시 데이터는 테스트/초기 검증용 내부 데이터로 유지하며 운영 UI/API에서는 적용 버튼을 제공하지 않음
- `/api/prompts/scene` scene JSON 및 deterministic prompt draft 생성 API 추가
- `python3 scripts/prompt_db_smoke_check.py` 통과
- React Studio Prompt Builder 모달 추가
- Prompt Builder는 직접 positive/negative 입력 방식을 유지하면서 현재 선택 segment에만 초안을 적용한다.
- `npm run build` 통과
- `python3 scripts/frontend_smoke_check.py` 통과
- `python3 scripts/fastapi_smoke_check.py` 통과
- `python3 scripts/fastapi_http_smoke_check.py` 통과

현재 진단:

- 현재 구현은 catalog/scene/prompt 생성 흐름을 검증하기 위한 v0이다.
- 첨부 제안 기준으로는 단어 나열만으로 복수 객체의 주체/대상/관계를 표현하기 어렵다.
- LLM 연결 전에 catalog v1, Scene JSON v1, backend validation을 보강한다.

## Step 5B. Prompt Catalog v1 및 Scene JSON v1 보강

- [x] `prompt_categories`에 `parent_category_id`, `scope_type`, `selection_type`, `required_yn`, `max_select_count` 추가
- [x] `prompt_terms`에 `canonical_key`, `description`, `risk_level` 추가
- [x] `prompt_category_terms` 중간 테이블 추가 및 migration 작성
- [x] `model_profiles` 테이블 추가
- [x] `prompt_term_renderings` 테이블 추가
- [x] builder draft 생성 시 active `model_profiles`와 `prompt_term_renderings` 우선 적용
- [x] `GENRE` selection mode를 multi로 수정
- [x] `ACTION`의 핵심 예시 데이터를 `CHARACTER_ACTION`으로 이관
- [x] `CAMERA_FRAMING`, `CAMERA_MOVEMENT` 핵심 카테고리 추가
- [x] `BACKGROUND`, `TIME_OF_DAY`, `WEATHER` 핵심 환경 카테고리 추가
- [x] `NEGATIVE_ANATOMY`, `NEGATIVE_ARTIFACT`, `NEGATIVE_TEMPORAL` 핵심 네거티브 카테고리 추가
- [x] Scene JSON v1 기본 구조 확정
- [x] scene/entity/relation 구조 생성 로직 추가
- [x] `/api/prompts/scene` payload의 복수 entity/action/relation 반영
- [x] single/multi/max count validation 추가
- [x] required category validation 및 warning 추가
- [x] `OBJECT_ACTION`, `MOTION_SPEED`, `MOTION_INTENSITY` 확장 카테고리 예시 데이터 추가
- [x] `CAMERA_ANGLE`, `LENS_TYPE`, `FOCUS_STYLE` 확장 카메라 카테고리 예시 데이터 추가
- [x] `CLOTHING`, `POSE`, `GAZE_DIRECTION`, `FACIAL_EXPRESSION`, `EMOTION` 확장 대상 카테고리 예시 데이터 추가
- [x] `ANIMATION_STYLE`, `RENDERING_STYLE`, `SCENE_TRANSITION`, `SHOT_DURATION` 확장 스타일/편집 카테고리 예시 데이터 추가
- [x] `NEGATIVE_QUALITY`, `NEGATIVE_CAMERA`, `NEGATIVE_TEXT` 확장 네거티브 카테고리 예시 데이터 추가
- [x] 내부 schema validator 기반 Scene JSON v1 validation 추가
- [x] 표준 JSON Schema artifact를 `schemas/scene-json-v1.schema.json`으로 분리
- [x] `/api/prompts/scene-schema`로 Scene JSON v1 schema 제공
- [x] `jsonschema` 기반 표준 JSON Schema runtime validation 연동
- [x] rule type `EXCLUDE`, `RECOMMEND`, `IMPLY` 1차 처리 구현
- [ ] rule type `REQUIRE`, `LIMIT`, `RATING_BLOCK`, `MODEL_BLOCK`, `REPLACE`, `ORDER` 처리 범위 정의
- [x] Prompt Builder UI에서 scene/entity/relation 구조를 확인할 수 있도록 preview 개선
- [x] Prompt Builder UI에서 복수 entity/action/relation 직접 편집 1차 구현
- [x] Prompt Builder entity asset picker, relation predicate template, validation hint 1차 구현
- [x] 사용자 UX 검토 후 entity/relation 직접 편집 UI 제거 및 `Scene Detail` 자유 입력 방식으로 단순화
- [x] Prompt Catalog Admin 1차 화면 추가(category/term 추가, 수정, 비활성화)
- [x] `prompt_scopes`, `prompt_category_groups`, `prompt_subcategories`, `prompt_subcategory_keywords` 계층 schema 추가
- [x] Prompt Builder tree를 Positive/Negative fixed scope 하위 category group/subcategory/key word accordion 구조로 변경
- [x] Prompt Builder accordion 기본 접힘 및 Refresh Catalog 시 접힘 상태 복귀
- [x] Selected Key Words를 Positive/Negative 박스로 분리하고 comma-separated text로 표시
- [x] Prompt Catalog Admin tree를 Prompt Builder와 동일한 계층형 accordion 스타일로 정리
- [x] Prompt Catalog Admin에서 scope는 편집 대상에서 제외
- [x] Prompt Catalog Admin에서 선택한 category/subcategory/key word 레벨만 우측 패널에 표시
- [x] subcategory 선택 시 상위 category group 정보를 함께 표시
- [x] key word 선택 시 상위 category group/subcategory 정보를 함께 표시
- [x] key word 관리 화면에서 기술 필드(code/canonical/categoryId/risk/sort)를 숨기고 사용자 입력 필드와 prompt text만 노출
- [x] key word 저장 payload는 legacy category id와 자동 code/canonical 값을 내부에서 보정
- [x] Admin Console 1차 화면 추가
- [x] Admin Console에 사용자 관리 탭 추가
- [x] 사용자 관리에서 사용자 조회, 추가, 수정, 비활성화, 비밀번호 저장/재설정 API 연결
- [x] Admin Console에 워크플로우 관리 탭 추가
- [x] 워크플로우 관리에서 workflow 조회, JSON 등록, 활성화, 비활성화 API 연결
- [x] 비활성화된 workflow는 Studio workflow list에서 제외
- [x] Admin Console의 Prompt Catalog 탭에서 catalog 관리 화면을 내부 탭 콘텐츠로 직접 표시
- [x] Admin Console 탭 스타일을 Metadata modal의 detail tab 스타일과 통일
- [x] 사용자 관리 화면을 workflow 관리와 동일한 좌측 목록/우측 상세/편집 구조로 정리
- [x] workflow 관리 화면에서 등록된 workflow 선택 시 우측 상세 정보 표시
- [x] workflow 등록을 JSON 직접 입력 대신 Workflow JSON/Param Config JSON 파일 불러오기 후 저장 흐름으로 변경
- [x] 사용자/workflow 목록에서 selected 상태와 active 상태를 별도 하이라이트/배지로 구분

2026-08-03 추가 검증:

- `python3 scripts/admin_smoke_check.py` 통과
- `python3 -m py_compile backend/app/db/models.py backend/app/services/prompt_builder_service.py backend/app/api/v1/prompts.py scripts/prompt_db_smoke_check.py scripts/db_migration_smoke_check.py scripts/mysql_migration_smoke_check.py` 통과
- `python3 scripts/db_migration_smoke_check.py` 통과
- `python3 scripts/prompt_db_smoke_check.py` 통과
- `python3 scripts/frontend_smoke_check.py` 통과
- `python3 scripts/fastapi_smoke_check.py` 통과
- `npm run build` 통과
- `validate_scene_json_v1()` 정상/오류 케이스 smoke 추가
- `/api/prompts/generate`가 잘못된 Scene JSON v1 입력을 `400`으로 반환하는지 smoke 확인
- `prompt_term_relations` 예시 데이터 및 `IMPLY` 자동 추가, `RECOMMEND` 추천 warning, `EXCLUDE` 충돌 warning smoke 확인
- `prompt_term_renderings`가 term 기본 prompt보다 우선 적용되는지 smoke 확인
- `/api/prompts/scene-schema` schema artifact 조회 smoke 확인
- `validate_scene_json_v1_with_schema()` 정상/오류 케이스 smoke 추가
- Prompt Builder `Scene Structure` preview 정적 smoke 추가
- 복수 entity별 action 주체 구분 및 relation schema smoke 추가
- Prompt Builder `Scene Entities` 편집 UI 정적 smoke 추가
- 확장 카테고리 catalog/selection/scope 및 Scene JSON 매핑 smoke 추가
- Prompt Builder asset picker/relation template/validation hint 정적 smoke 추가
- Prompt Catalog Admin category/term create-update-deactivate API smoke 추가
- Prompt Catalog Admin 모달 정적 smoke 추가
- Prompt Builder/Admin scroll container 회귀 smoke 보강
- Prompt Catalog Admin conditional panel, key word hidden technical fields 정적 smoke 보강
- Admin 사용자/워크플로우 관리 API smoke 추가
- Admin Console 정적 smoke 추가
- `npm run build` 후 FastAPI `/studio/app` 최신 React bundle 서빙 확인
- 로컬 최신 서버 `http://127.0.0.1:8788/studio/app` 재기동 후 `/api/admin/users`, `/api/admin/workflows` 응답 확인

2026-08-04 추가 점검:

- Admin modal을 Metadata modal과 같은 탭 스타일로 정리
- Prompt Catalog 관리 화면을 Admin 내부 탭에 embed
- workflow 선택 하이라이트/active 배지 분리
- 사용자 관리도 workflow 관리와 같은 상세/편집 패턴으로 정리
- workflow JSON 파일 불러오기 후 저장 UI 적용
- `npm run build` 통과
- `python3 scripts/frontend_smoke_check.py` 통과
- `python3 scripts/admin_smoke_check.py` 통과
- `git diff --check` 통과

로컬 확인 기준:

- [x] catalog API가 category scope/selection/required/max count를 반환한다.
- [x] catalog API가 term relation 정보를 반환한다.
- [x] category 선택 규칙이 frontend뿐 아니라 backend에서도 검증된다.
- [x] `prompt_term_relations` 기반 기본 추천/충돌/암시 관계가 backend에서 처리된다.
- [x] 모델별 rendering 문구가 builder positive/negative draft에 우선 반영된다.
- [x] 단일 entity fallback scene/action 구조가 Scene JSON v1로 저장된다.
- [x] 복수 entity payload에서 entity별 action 주체가 구분되어 저장된다.
- [x] scene JSON v1이 내부 schema validation을 통과한다.
- [x] scene JSON v1 표준 JSON Schema artifact를 별도 파일로 관리한다.
- [x] scene JSON v1 표준 JSON Schema artifact가 runtime validation에 사용된다.
- [x] Prompt Builder에서 scene/entity/relation 구조를 raw JSON 이전에 요약 확인할 수 있다.
- [x] 두 개 이상 entity가 있는 scene에서 각 action의 주체를 구분할 수 있다.
- [x] Backend Scene JSON v1은 복수 entity/action/relation 구조를 수용한다.
- [x] 현재 Prompt Builder UI는 복수 entity/action/relation 직접 편집 대신 `Scene Detail` 입력으로 장면 보완 정보를 받는다.
- [x] Prompt Catalog Admin에서 category group/subcategory/key word를 추가, 수정, 비활성화할 수 있다.
- [x] Prompt Catalog Admin은 선택한 레벨만 표시하고 부모 정보를 함께 로드한다.
- [x] Admin Console에서 사용자와 권한 역할을 관리할 수 있다.
- [x] Admin Console에서 workflow 등록과 active/inactive 전환을 관리할 수 있다.
- [x] Admin Console에서 Prompt Catalog를 별도 모달 호출 없이 내부 탭에서 관리할 수 있다.
- [x] Role/Permission/Feature Governance 설계 문서 추가
- [x] RBAC role/permission/resource catalog migration 추가
- [x] DB 로그인 기반 사용자 role/effective permission 반환
- [x] TopBar 로그인 사용자 이름 표시
- [x] 로그아웃/브라우저 종료 시 session storage 정리
- [x] Admin 메뉴 노출을 role이 아닌 effective permission 기준으로 전환
- [x] `workflow_tasks`를 job 목록 원장 테이블로 활용할 수 있도록 작업 생성 시 DB task record를 생성한다.
- [x] 작업 생성 시 입력 asset을 `task_input_assets`로 연결한다.
- [x] 작업 생성 시 실제 ComfyUI/WAN에 전달되는 segment별 prompt를 `task_prompts`에 저장한다.
- [x] 작업 완료 시 출력 asset을 `task_output_assets`로 연결하고 `task_prompts.output_asset_ids`에 반영한다.
- [x] `task_prompts`에 품질등급과 코멘트를 저장/수정할 수 있는 최소 API를 제공한다.

## 후순위 Backlog

- [x] 별도 페이지 라우트 전환(`/studio/history`, `/studio/status`, `/studio/metadata`, `/studio/manual`, `/studio/admin`)
- [x] TanStack Query 도입 안 함: 현재 단계에서는 `apiClient + useState/useEffect` 유지
- [x] `roles`, `permissions`, `role_permissions`, `user_permissions`, `ui_permission_resources` DB schema 및 seed migration 추가
- [x] 기존 `users.permissions_json`을 사용자 추가 권한으로 마이그레이션
- [x] effective permission 계산 service 추가
- [x] Admin API에서 Role/Permission/Feature Resource catalog 조회 제공
- [x] 공통 `require_permission()` backend guard 추가
- [x] Admin API를 기능별 permission guard로 1차 전환
- [x] Jobs/History/Metadata/Prompt/Workflow/Asset/Config/Report/System/Manual API를 기능별 permission guard로 전환
- [x] TopBar 메뉴와 메인 Prompt/Generate/Cancel action button에 permission guard 적용
- [x] History/Admin 내부 상세 action button에 permission guard 적용
- [x] Admin Console에 `Roles & Permissions` 탭 추가
- [x] 사용자 관리 화면에서 permission 자유 입력 제거, Role 기본 권한 표시 + 추가 권한 선택 방식으로 변경
- [x] 기능 resource mapping 누락/orphan permission 검사 smoke 추가
- [x] 관리자 workflow 등록 시 기본 구조 validation, paramconfig 자동 생성, segment defaults 동기화, metadata rebuild, 기존 workflow/paramconfig 백업 적용
- [ ] 관리자 workflow version table 기반 review/rollback UI 고도화
- [x] `Load Past Prompts` 제거
- [x] `Generate Report` 제거

2026-08-05 추가 검증:

- `python3 scripts/rbac_permission_smoke_check.py` 추가 및 통과
- `python3 scripts/admin_smoke_check.py` 통과
- `python3 scripts/frontend_smoke_check.py` 통과
- `python3 scripts/prompt_db_smoke_check.py` 통과
- `python3 scripts/persistence_backend_smoke_check.py` 통과
- `python3 scripts/fastapi_smoke_check.py` 통과
- `npm run build` 통과
- API 사용자명 헤더는 비ASCII 안전성을 위해 frontend에서 URL encoding, backend에서 decoding 처리
- 기존 DB에도 `ui_permission_resources` 누락/변경분이 자동 보정되도록 permission governance 조회 시 resource catalog upsert 적용

## Step 6. LLM 프롬프트 생성 연동

- [x] LLM endpoint 설정 분리
- [x] mock provider 기반 prompt generation API 추가
- [x] scene JSON 최소 검증
- [x] 생성 output 이력 저장
- [x] 평가/수정 feedback 저장 API 추가
- [x] Studio prompt field 적용 흐름 구현
- [x] 실제 RunPod vLLM endpoint 호출 구현
- [x] 내부 schema validator 기반 Scene JSON v1 엄격 검증
- [x] 표준 JSON Schema artifact 제공
- [x] `jsonschema` validator를 사용한 표준 JSON Schema 검증

로컬 확인 기준:

- mock LLM provider로 deterministic output 생성
- RunPod vLLM endpoint 호출 경로는 mock network response로 smoke 검증
- 실제 endpoint 품질/응답 형식은 운영 endpoint 값 설정 후 수동 확인 필요

2026-08-02 추가 검증:

- `PROMPT_LLM_PROVIDER`, `PROMPT_LLM_API_KEY`, `PROMPT_LLM_ENDPOINT_ID`, `PROMPT_LLM_ENDPOINT_URL`, `PROMPT_LLM_MODEL`, `PROMPT_LLM_TEMPERATURE`, `PROMPT_LLM_MAX_TOKENS`, `PROMPT_LLM_TIMEOUT` 환경변수 추가
- `/api/prompts/generate` mock provider API 추가
- `/api/prompts/feedback` API 추가
- React Prompt Builder 모달에서 `Build Scene JSON` 후 `Generate Prompt` 실행 가능
- 생성 결과는 현재 선택 segment의 positive/negative prompt field에 적용 가능
- 현재 LLM provider 기본값은 local/mock이며, `PROMPT_LLM_PROVIDER=runpod_vllm` 또는 `openai_compatible` 설정 시 실제 RunPod vLLM endpoint 호출
- 시작 로그인 기능은 DB 사용자 권한 테스트를 위해 다시 활성화
- `Load Past Prompts`와 `Generate Report`는 현재 UI 범위에서 제거

## Step 7. Job/Task 중심 작업관리

- [x] `task_prompts` migration 추가
- [x] `WorkflowTask`와 `TaskPrompt` 관계 추가
- [x] 작업 생성 이벤트 발생 시 `workflow_tasks`에 job record 저장
- [x] 작업 생성 이벤트 발생 시 segment별 최종 WAN prompt 저장
- [x] 입력 image asset과 output video asset을 task 하위 연결 테이블에 저장
- [x] 품질등급/코멘트 업데이트 API 추가
- [x] 히스토리 화면을 JSON history 우선 조회에서 DB task 원장 조회 우선 + legacy JSON 병합으로 전환
- [x] 실행 중 job 상태를 메모리 `JOBS` 유실 시 DB `workflow_tasks` 기준으로 복구 가능하게 전환
- [x] prompt 재활용 UI에서 `task_prompts`의 quality/rating/comment/reuse reason을 검색 조건으로 활용

로컬 확인 기준:

- `python3 -m alembic upgrade head` 통과
- `python3 scripts/db_migration_smoke_check.py` 통과
- `python3 scripts/frontend_smoke_check.py` 통과
- dry-run job 생성 후 `workflow_tasks`와 `task_prompts` DB row 생성 확인
- `update_task_prompt_quality()`로 품질등급/코멘트 저장 확인
- 메모리 `JOBS`를 비운 뒤 `workflow_tasks`에서 `job_status` 복구 확인
- `load_history()`가 DB task 원장 이력과 legacy JSON history를 taskId 기준으로 병합하는지 확인
- Prompt Reuse에서 재사용 가능 prompt만 전체 workflow와 독립적으로 조회되고, prompt/comment/reuse reason keyword 검색으로 필터링되는지 확인

2026-08-05 추가 점검:

- `workflow_tasks` job 원장 기준 생성/상태/이력 구조 확인
- `task_prompts` review 상태는 품질등급 저장 여부로 `reviewed`/`unreviewed`가 자동 결정되도록 확인
- `reuse_eligible=true` 저장 시 재사용 사유가 하나 이상 필요하도록 backend validation 적용 확인
- Prompt Reuse 검색은 workflow 독립적으로 `reuse_eligible=true` prompt를 조회하는 구조로 확인

## Step 8. ECS 운영 배포 준비

- [x] Docker production runner `scripts/run_server.py` 추가
- [x] 운영 runner는 serving 전용으로 두고, migration은 `scripts/upgrade_database.py` one-off task로 분리
- [x] `upgrade_database.py --check`로 RDS revision/head 차이를 판별하고, pending일 때만 `--if-needed` one-off migration을 적용
- [x] Dockerfile에 frontend Node build stage 추가
- [x] Docker CMD를 `scripts/run_server.py`로 변경
- [x] Docker 기본 `PORT`와 `EXPOSE`를 ECS target 기준 `7860`으로 정렬
- [x] `.dockerignore`에서 `.env`, 로컬 SQLite DB, 업로드/출력 파일, 리포트, build cache, 구버전 `src/`, workflow backup 제외
- [x] `.gitignore`에서 TypeScript build cache와 frontend build output 제외
- [x] `docs/aws-ecs-deployment.md`에 RDS/MySQL, S3, RunPod ComfyUI, RunPod Qwen, JWT secret 필수 환경변수 보강
- [x] Docker image build 성공 확인
- [x] Docker image 내부에 `.env`, `data/dobedub-studio.db`, `data/uploads`, `data/outputs`, 구버전 `src/`가 없고 `data/segment-defaults.json`만 포함됨 확인
- [x] Docker image metadata가 `7860/tcp`, `PORT=7860`인지 확인
- [x] Docker image 내부 FastAPI app import 확인
- [ ] ECS/RDS 대상 Alembic migration one-off task 실행 (`scripts/upgrade_database.py`)
- [ ] ECR push
- [ ] ECS task definition revision 등록
- [ ] ECS service update
- [ ] 운영 URL에서 로그인, 권한별 메뉴, workflow 목록, prompt builder, task 생성, history, metadata, manual, RunPod/Qwen status 확인

2026-08-05 preflight 검증:

- `npm run build` 통과
- `python3 scripts/frontend_smoke_check.py` 통과
- `python3 scripts/rbac_permission_smoke_check.py` 통과
- `python3 scripts/admin_smoke_check.py` 통과
- `python3 scripts/fastapi_smoke_check.py` 통과
- `python3 scripts/db_migration_smoke_check.py` 통과
- `python3 scripts/storage_backend_smoke_check.py` 통과
- `python3 -m py_compile scripts/run_server.py` 통과
- `git diff --check` 통과
- `docker build -t dobedub-studio:ecs-check .` 통과

## Step 9. 다중 Task 제출 및 상태 운영

- [x] `task_execution_policies` singleton 테이블 및 Alembic migration 추가
- [x] 기본 동시 활성 Task 한도 설정: 사용자당 3개, 전체 10개
- [x] `POST /api/jobs`에서 인증 사용자 기준 한도 검사 및 서버 주도 사용자 스냅샷 기록
- [x] 활성 상태(`QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING`)를 `GET /api/history`에 포함
- [x] 서버 lifecycle task monitor가 DB 활성 Task를 RunPod 상태로 주기 갱신
- [x] 브라우저 종료/로그아웃 뒤에도 DB task 원장 기준 상태 관리 유지
- [x] 제출 후 Task History로 이동하고 워크스페이스를 다음 작업용으로 초기화
- [x] Task History 진행 필터, 활성 Task 진행률, 취소 액션 추가
- [x] Sandbox Pod 바로 아래의 독립 Task Policy 메뉴에 동시 작업 제출 정책 관리 추가
- [x] 생성 진행/결과 전용 route를 retired 처리하고 Task History를 단일 작업 상태·결과 화면으로 통합
- [x] 사용자 매뉴얼을 사용자 업무/관리자 운영 구분으로 현행화
- [x] User Manual 내부 목차 앵커가 iframe 안에서만 이동하도록 회귀 방지
- [x] 같은 탭 새로고침에서 JWT 세션을 복원하고 명시 로그아웃/만료 시에만 정리
- [x] README 현행화

로컬 확인 기준:

- `python3 scripts/upgrade_database.py`로 `20260812_0019` 적용
- 활성 Task 3건 생성 시 이력 목록에 `QUEUED` 상태로 보이는지 확인
- 같은 사용자 네 번째 제출이 409 한도 오류로 차단되는지 확인
- `npm run build`, `python3 -m compileall -q backend/app`, `git diff --check` 통과

운영 반영 전 확인:

- RDS에 migration one-off task를 먼저 적용한다.
- `TASK_MONITOR_INTERVAL_SECONDS`는 기본 5초이며, RunPod 상태 호출량에 맞춰 1~60초로 조정할 수 있다.
- 다중 ECS replica로 확장할 때는 제출 한도 검사에 DB 잠금 또는 원자적 SQL 카운트 갱신을 추가 검토한다.
