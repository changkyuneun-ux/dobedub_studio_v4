# Sandbox Pod 다중 보유·선택 실행 및 GPU Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 네트워크 볼륨에 붙은 여러 Sandbox Pod를 화면에서 목록으로 보여주고 관리자가 하나를 **선택해 기동**하되, 서버가 **실행 중 파드는 최대 1개** 불변식을 강제(전환 시 stop→대기, 2개 RUNNING이면 conflict/409)한다. 기동은 `stop(전환) → start(선택) → start(대체 파드) → create(1순위 GPU) → create(fallback GPU)` 단계형으로 자동화하고 `attempts`를 응답·audit·로그·메트릭에 남긴다. 프론트는 실패 시 이전 상태를 지우지 않는다.

**Architecture:** 파드 해석은 `_resolve_pod` 단일 선택을 `_resolve_pods`(볼륨 기준 전체 목록 + 불변식 판정)로 대체한다. 선택 파드·자동 전환 옵션·우선순위는 `task_execution_policies`와 같은 **단일 행 DB 설정**(`sandbox_pod_settings`)에 둔다. 서비스 함수는 `(settings, db, pod_id)` 시그니처로 DB 설정을 읽고 갱신한다. 예외는 `SandboxPodConflict`(409), `SandboxPodUnavailable`(503), `SandboxPodApiError`(RunPod HTTP 래핑, `RuntimeError` 호환)로 나눠 API 계층이 상태코드로 매핑한다. RunPod 오류 분류·GPU 후보 선택·전환 대기는 순수 함수/작은 helper로 분리한다.

**Tech Stack:** FastAPI + SQLAlchemy(alembic) + urllib(REST v1) 백엔드, React/TypeScript 프론트, pytest(unittest + urlopen mock, `api_client` fixture), Python 소스 컨트랙트 테스트(프론트).

**Spec:** `docs/superpowers/specs/2026-09-11-sandbox-pod-gpu-fallback-design.md` (v2, 다중 파드 선택 반영)

**Branch:** `feat/enhance` (base: `feat/s3` HEAD `a386786`)

## Global Constraints

- **실행 중 파드 최대 1개**: start 계열 진입 시 `conflict`면 409. 전환은 다른 RUNNING/STARTING 파드를 모두 stop하고 `EXITED` 확인 후에만 target을 start한다. 대기 타임아웃이면 start 없이 409.
- **식별자 역할 분리**(스펙 §5.2): `RUNPOD_SANDBOX_NETWORK_VOLUME_ID`가 파드 **유일 식별자**. `RUNPOD_SANDBOX_TEMPLATE_ID`·`GPU_TYPE_ID`는 **생성 사양**으로만 쓰고 파드 찾기에는 쓰지 않는다(볼륨 selector가 없을 때만 legacy 필터). 이 원칙은 0단계 패치로 `_resolve_pod`에 이미 적용됨(작업 트리, 미커밋) — Task 0에서 커밋하고 `_resolve_pods`도 같은 원칙을 따른다. TERMINATED 제외. 파드는 **ID·GPU로 구분**하고 이름은 표시용.
- 각 create 요청은 GPU **하나만** `gpuTypeIds:[x]`. `dataCenterIds` 미지정. 이름은 `RUNPOD_SANDBOX_DEPLOY_NAME` 그대로.
- 기존 응답 단일 필드(`podId`, `desiredStatus`, `runtimeStatus`, `httpServices`, `systemStatus`, …)는 유지하되 `activePodId` 기준으로 채운다(하위 호환). RUNNING 파드가 없으면 `selectedPodId` → 최근 EXITED 순으로 채운다.
- `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS` 빈 값이면 create는 1순위 GPU 1회만(롤아웃 2단계까지 동작 동일).
- 실패 응답에서 `httpServices`·상태 카드를 갱신하지 않는다.
- 저장소에 Vitest 없음(`frontend/package.json`: `tsc -b && vite build`). 스펙 §7 "프론트 Vitest"는 기존 관례인 Python 소스 컨트랙트 테스트(`backend/tests/test_frontend_*_contract.py`)로 대체. 우선순위 "드래그 정렬"은 DnD 라이브러리가 없으므로 ▲/▼ 버튼으로 구현(스펙 편차, §8 메모에 기록).
- `Settings`는 `@dataclass(frozen=True)`(`config.py:11`) → 목록 설정은 `tuple[str, ...]`.
- 스펙 §6 잔여 검증(4090 SageAttention, 5090 `--cache-none`, PRO 6000 Server CUDA 13.2)은 코드와 독립. 코드는 fallback 빈 값으로 먼저 배포 가능해야 한다.
- 작업 트리의 `metadata/*.json` 수정 3건·`workflow-json-downloads/`·`2026-09-10-final-batch-s3-structure.md`는 이 작업과 무관. 커밋에 포함하지 않는다. 반면 `sandbox_pod_service.py`·`test_sandbox_pod_service.py`·스펙의 미커밋 변경은 0단계 패치이므로 Task 0에서 커밋한다.
- 검증 명령: `python3.12 -m pytest backend/tests/test_sandbox_pod_service.py backend/tests/test_sandbox_pod_api.py backend/tests/test_frontend_sandbox_pod_contract.py -q` + `npm run build`.

## 롤아웃 매핑 (스펙 §8)

| 롤아웃 단계 | 포함 Task | 동작 변화 |
|---|---|---|
| 0. `_resolve_pod` 템플릿 필터 완화 (적용됨, 배포 대기) | Task 0 | 볼륨 selector가 있으면 template null 파드(`3i50u1x4pyz0vr`)도 인식. env 변경 없음 |
| 1. `pods[]` 응답 확장만 | Task 1, 3, 4 | GET에 목록 추가. start/stop은 현행(단, conflict면 409) |
| 2. select/settings/전환/fallback 로직 | Task 2, 5, 6, 7, 8 | `FALLBACK_TYPE_IDS` 빈 값 → create는 1회 |
| 3. fallback 활성 | Task 11 후 env 설정 | — |
| 4. 운영가이드 | Task 9 | — |

---

### Task 0: 0단계 패치 커밋 — `_resolve_pod` 템플릿 필터 완화 (이미 적용됨)

**Files:**
- Already modified (uncommitted): `backend/app/services/sandbox_pod_service.py:104-109` (`if template_id and not volume_id:`), `:149-152` (`resolved_by`에서 볼륨 있으면 template-id 제외)
- Already modified (uncommitted): `backend/tests/test_sandbox_pod_service.py:110-203` (`SandboxPodResolutionTests` 3건)
- Already modified (uncommitted): `docs/superpowers/specs/…-design.md` §5.2 원칙 표 + §8 0단계

**Interfaces:**
- 변경 없음. `_resolve_pod(settings) -> tuple[dict, str]` 시그니처 유지. 볼륨 selector가 있을 때 `resolved_by == "network-volume"`(템플릿이 설정돼 있어도 `+template-id`를 붙이지 않음).

- [ ] **Step 1: 변경 내용 검토** — `git diff backend/app/services/sandbox_pod_service.py backend/tests/test_sandbox_pod_service.py`. 스펙 §5.2 표와 일치하는지 확인: 볼륨 있으면 템플릿 필터 미적용, 템플릿만 설정된 legacy 구성은 기존 동작 유지.

- [ ] **Step 2: 테스트 실행**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py -q
```

Expected: 기존 4건 + `SandboxPodResolutionTests` 3건 통과. (이 세션의 로컬 VM에는 python3.12/pytest가 없어 실행하지 못했음 — 호스트에서 실행.)

- [ ] **Step 3: 별도 커밋** — 롤아웃 0단계 경계. 이 커밋만 배포해도 현재 PRO 6000 파드를 관리자 페이지가 인식한다.

```bash
git add backend/app/services/sandbox_pod_service.py backend/tests/test_sandbox_pod_service.py docs/superpowers/specs/2026-09-11-sandbox-pod-gpu-fallback-design.md
git commit -m "fix(sandbox): treat network volume as sole pod identity; template is a creation spec"
```

---

### Task 1: Settings 확장 (env 5개) + 환경변수 문서

**Files:**
- Modify: `backend/app/core/config.py:39-50` (필드), `:97-103` (파싱), `:191-202` (생성자 인자)
- Modify: `.env.example:35-37`, `docs/aws-ecs-deployment.md:41-46`, `:68`
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- `Settings.sandbox_pod_gpu_fallback_type_ids: tuple[str, ...] = ()`
- `Settings.sandbox_pod_start_retry_count: int = 1`
- `Settings.sandbox_pod_create_attempt_delay_seconds: float = 2.0`
- `Settings.sandbox_pod_min_vram_gb: int = 24`
- `Settings.sandbox_pod_stop_wait_seconds: int = 60`

- [ ] **Step 1: 실패 테스트**

```python
class SandboxPodSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        s = Settings()
        self.assertEqual(s.sandbox_pod_gpu_fallback_type_ids, ())
        self.assertEqual(s.sandbox_pod_start_retry_count, 1)
        self.assertEqual(s.sandbox_pod_create_attempt_delay_seconds, 2.0)
        self.assertEqual(s.sandbox_pod_min_vram_gb, 24)
        self.assertEqual(s.sandbox_pod_stop_wait_seconds, 60)

    @patch.dict("os.environ", {
        "RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS": " NVIDIA RTX PRO 4500 Blackwell , NVIDIA GeForce RTX 4090 ,, ",
        "RUNPOD_SANDBOX_START_RETRY_COUNT": "0",
        "RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS": "0.5",
        "RUNPOD_SANDBOX_MIN_VRAM_GB": "48",
        "RUNPOD_SANDBOX_STOP_WAIT_SECONDS": "15",
    })
    def test_parses_env(self) -> None:
        from backend.app.core.config import get_settings  # 캐시 없음(config.py:87)
        s = get_settings()
        self.assertEqual(s.sandbox_pod_gpu_fallback_type_ids, ("NVIDIA RTX PRO 4500 Blackwell", "NVIDIA GeForce RTX 4090"))
        self.assertEqual((s.sandbox_pod_start_retry_count, s.sandbox_pod_create_attempt_delay_seconds,
                          s.sandbox_pod_min_vram_gb, s.sandbox_pod_stop_wait_seconds), (0, 0.5, 48, 15))
```

- [ ] **Step 2: 실패 확인** — `python3.12 -m pytest backend/tests/test_sandbox_pod_service.py::SandboxPodSettingsTests -q` → `AttributeError`.

- [ ] **Step 3: 구현**

`config.py:50` 뒤 필드 5개, `:103` 뒤 파싱(기존 try/except 패턴, 음수는 0으로 clamp, 쉼표 목록은 strip·빈 항목 제거 후 tuple), `:196` 뒤 생성자 인자 5개.

- [ ] **Step 4: 문서**

`.env.example:35` 뒤와 `docs/aws-ecs-deployment.md:41` 뒤에 5줄 추가(예시값은 스펙 §5.1 기본값, `FALLBACK_TYPE_IDS`는 `.env.example`에서 빈 값). `:68` 문단에 "fallback은 빈 값으로 먼저 배포하고 §6 검증 후 설정, `RUNPOD_SANDBOX_POD_ID`는 DB 선택값이 있으면 무시" 추가.

- [ ] **Step 5: 통과 후 커밋** — `feat(sandbox): add multi-pod and GPU fallback settings`

---

### Task 2: DB 단일 행 설정 `sandbox_pod_settings` + 서비스

**Files:**
- Modify: `backend/app/db/models.py:239-250` 아래에 모델 추가
- Create: `backend/app/db/migrations/versions/20260911_0037_sandbox_pod_settings.py`
- Create: `backend/app/services/sandbox_pod_settings_service.py`
- Test: `backend/tests/test_sandbox_pod_settings_service.py`

**Interfaces:**
- 모델 `SandboxPodSetting` (`__tablename__="sandbox_pod_settings"`, `id=1` 고정): `selected_pod_id: str | None (String(64))`, `auto_switch_on_start_failure: bool (default True)`, `pod_priority_json: list (JSON, default list)`, `updated_by`, `created_at`, `updated_at` — `TaskExecutionPolicy`(`models.py:239`)와 동일 패턴.
- `sandbox_pod_settings(session) -> SandboxPodSetting` — 없으면 생성(`task_policy_service.task_execution_policy` 패턴).
- `sandbox_pod_settings_payload(session) -> dict` → `{"selectedPodId", "autoSwitchOnStartFailure", "podPriority": [...], "updatedBy", "updatedAt*"}`
- `select_sandbox_pod(session, *, pod_id: str, updated_by: str) -> dict` (commit)
- `update_sandbox_pod_settings(session, *, auto_switch_on_start_failure: object, pod_priority: object, updated_by: str) -> dict` — bool 강제, priority는 str 목록·중복 제거, 아니면 `ValueError`.

- [ ] **Step 1: 실패 테스트** (기존 DB 테스트가 쓰는 세션 fixture — `backend/tests/conftest.py` 확인)

```python
def test_settings_row_is_created_with_defaults(db_session):
    payload = sandbox_pod_settings_payload(db_session)
    assert payload["selectedPodId"] is None
    assert payload["autoSwitchOnStartFailure"] is True
    assert payload["podPriority"] == []

def test_select_and_update_persist(db_session):
    select_sandbox_pod(db_session, pod_id="caiuvooekq9qqw", updated_by="admin")
    update_sandbox_pod_settings(db_session, auto_switch_on_start_failure=False,
                                pod_priority=["3i50u1x4pyz0vr", "caiuvooekq9qqw", "3i50u1x4pyz0vr"], updated_by="admin")
    payload = sandbox_pod_settings_payload(db_session)
    assert payload["selectedPodId"] == "caiuvooekq9qqw"
    assert payload["autoSwitchOnStartFailure"] is False
    assert payload["podPriority"] == ["3i50u1x4pyz0vr", "caiuvooekq9qqw"]

def test_update_rejects_non_list_priority(db_session):
    with pytest.raises(ValueError):
        update_sandbox_pod_settings(db_session, auto_switch_on_start_failure=True, pod_priority="x", updated_by="admin")
```

- [ ] **Step 2: 실패 확인** — `ImportError`.

- [ ] **Step 3: 모델 + 마이그레이션**

마이그레이션은 `20260909_0036`을 `down_revision`으로, 기존 파일처럼 `inspector.get_table_names()`로 존재 확인 후 `op.create_table`. downgrade는 `drop_table`. `main.py:59-63`의 부트스트랩이 `alembic upgrade head`를 돌리므로 새 배포에서 자동 적용됨을 확인.

- [ ] **Step 4: 서비스 구현 → 테스트 통과 → 커밋** — `feat(sandbox): persist selected pod and switch settings`

---

### Task 3: RunPod 오류 분류 + GPU 후보 선택 + 예외 타입

**Files:**
- Modify: `backend/app/services/sandbox_pod_service.py:14` (예외), `:191-213` (`_request` → `SandboxPodApiError`), helper 추가
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- `class SandboxPodApiError(RuntimeError)`: `status: int | None`, `detail: str`. `_request`가 HTTPError/URLError를 이것으로 raise. 메시지 포맷은 기존과 동일(`Sandbox Pod API HTTP {code}: {detail}` / `Sandbox Pod API 연결 실패: {reason}`)이라 기존 테스트·`_hydrate_pod`의 `except RuntimeError` 호환.
- `class SandboxPodUnavailable(RuntimeError)`: `attempts: list[dict]`, `retry_after_seconds: int = 300`
- `class SandboxPodConflict(RuntimeError)`: `attempts: list[dict]`, `running_pod_ids: list[str]`
- `_classify_error(exc) -> "no_capacity" | "not_found" | "config" | "transient" | "unknown"` — `no_capacity`: 본문 `no instances`/`not available`/`no longer available` 또는 HTTP 500·503; `not_found`: 404; `config`: 400·401·403·422; `transient`: status None(연결 실패).
- `_gpu_candidates(settings, vram_by_gpu: dict[str, float] | None) -> list[tuple[str, str | None]]` — `[GPU_TYPE_ID] + FALLBACK` 순서 유지·중복 제거, `vram_by_gpu`가 있고 `< min_vram_gb`면 `"vram"`. 1순위 GPU는 필터 제외(운영자 명시값).
- `_fetch_gpu_catalog(settings) -> dict[str, dict] | None` — `GET /gpus`를 `{id: {"memoryInGb", "securePrice"…}}`로. 실패 시 `None`. Task 4의 `vramGb`/`pricePerHr` 보완에도 재사용(요청당 1회 호출, 인자로 전달).

- [ ] **Step 1: 실패 테스트** — 분류 5케이스(500 본문/503/404/400·401·403·422/연결 실패), 후보 순서·중복 제거, VRAM skip, fallback 미설정 시 1순위만.
- [ ] **Step 2: 실패 확인 → 구현 → 통과** (`/gpus` 실제 필드명은 `rest.runpod.io/v1/gpus` 1회 조회로 확인해 파싱 고정)
- [ ] **Step 3: 커밋** — `feat(sandbox): classify RunPod errors and select GPU candidates`

---

### Task 4: `_resolve_pods` + `pods[]` 응답 확장 (롤아웃 1단계 산출물)

**Files:**
- Modify: `backend/app/services/sandbox_pod_service.py:27-35` (`sandbox_pod_status`), `:90-153` (`_resolve_pod` → `_resolve_pods`), `:250-301` (`_present_pod`), `:304-323` (`_http_services`)
- Modify: `backend/app/api/v1/sandbox_pod.py:16-21` (GET에 `db` 주입)
- Modify: `frontend/src/api/client.ts:187-230` (타입만)
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- `_resolve_pods(settings) -> list[dict]` — `GET /pods?includeNetworkVolume=true` → **볼륨 ID 일치만**으로 필터(템플릿 ID는 절대 필터에 쓰지 않음 — Task 0 원칙) & 비TERMINATED 전부. 볼륨 ID 미설정이면 기존 `_resolve_pod` legacy 경로(pod-id/template/name)로 1건 목록 반환. `_resolve_pod`는 legacy 전용으로 남기고 `SandboxPodResolutionTests` 3건은 그대로 통과해야 한다. 각 파드는 `_hydrate_pod`로 상세 보강.
- `_pod_summary(settings, pod, catalog) -> dict` → `{"podId","name","gpuTypeId","vramGb","ramGb","pricePerHr","desiredStatus","runtimeStatus","lastStartedAt*","httpServices"}`. `pricePerHr`는 파드 `costPerHr`, `ramGb`는 `memoryInGb`, `vramGb`는 catalog에서(없으면 null). RUNNING이 아니면 `runtimeStatus`는 `desiredStatus`(HTTP 8188 프로브는 RUNNING만).
- `_http_services(pod_id, ports, *, jupyter_auth_required: bool)` — 8888 항목에 `authRequired`. 판정: 파드 `env`에 `JUPYTER_PASSWORD` 키 존재.
- `_pick_display_pod(pods, selected_pod_id) -> dict | None` — RUNNING/STARTING 1개 → 그것, 없으면 `selected_pod_id` 일치, 없으면 `_most_recent_pod`.
- `_conflict(pods) -> list[str]` — `desiredStatus ∈ ACTIVE_STATES` 파드 ID가 2개 이상이면 그 목록, 아니면 `[]`.
- `sandbox_pod_status(settings, db) -> dict` — 기존 필드(`_present_pod(display_pod)`) + `pods`, `selectedPodId`, `activePodId`(RUNNING 1개면 ID, 아니면 null), `conflict: bool`, `conflictPodIds`, `settings`(Task 2 payload), `attempts: []`, `gpuTypeId`, `gpuTier`.
- `gpuTier`: `gpuTypeId == settings.sandbox_pod_gpu_type_id` → `"primary"`, 값 없음 → `"unknown"`, 그 외 `"fallback"`.

- [ ] **Step 1: 테스트 fixture** — `_RunPodScript`(method+path별 응답 큐, HTTPError 지원)와 파드 상수 2개(`POD_5090` EXITED `caiuvooekq9qqw`, `POD_PRO6000` RUNNING `3i50u1x4pyz0vr`, 둘 다 `networkVolume.id="18jhx6rxjd"`, PRO6000은 `templateId` null, `env: {"JUPYTER_PASSWORD": "x"}`). 외부 호출(`_runtime_status`, `_runtime_metrics`, `_fetch_gpu_catalog`, `_sleep`)은 patch.

- [ ] **Step 2: 실패 테스트** (스펙 §7-1, §7-8 및 호환성)

```python
def test_lists_all_pods_on_volume_including_template_null(self): ...   # pods 2건, PRO6000(template null) 포함, 다른 볼륨의 같은 템플릿 파드는 제외
def test_active_pod_fills_legacy_fields(self): ...                      # podId == 3i50…, httpServices 8888 authRequired True
def test_no_running_pod_uses_selected_then_most_recent(self): ...       # 둘 다 EXITED, selected=caiuv → podId caiuv; selected None → 최근
def test_two_running_pods_flag_conflict(self): ...                      # conflict True, conflictPodIds 2개, activePodId None
def test_volume_unset_falls_back_to_legacy_single_pod_selector(self): ...
```

- [ ] **Step 3: 구현** — `_resolve_pod`는 legacy 경로 전용 내부 함수로 축소. `sandbox_pod_status`가 `db`를 받도록 바꾸고 API GET에 `db: Session = Depends(get_db)` 추가(권한 `sandbox:read`). `client.ts` `SandboxPodStatus`에 `pods`, `selectedPodId`, `activePodId`, `conflict`, `conflictPodIds`, `settings`, `attempts`, `gpuTypeId`, `gpuTier` 타입 추가(`SandboxPodSummary`, `SandboxPodAttempt`, `SandboxPodSettings` export). `httpServices` 항목에 `authRequired?: boolean`.

- [ ] **Step 4: 통과 + `npm run build` → 커밋** — `feat(sandbox): list every pod on the network volume with conflict detection`

---

### Task 5: 기동 절차 `start_sandbox_pod(settings, db, pod_id)` — 전환 → start → 대체 파드 → create → fallback

**Files:**
- Modify: `backend/app/services/sandbox_pod_service.py:38-55` (`start_sandbox_pod`, `stop_sandbox_pod`), `:63-87` (`_deploy_sandbox_pod` 제거)
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- `start_sandbox_pod(settings, db, pod_id: str | None = None) -> dict` — 반환은 `sandbox_pod_status` 형태 + `attempts`, `switched: bool`, `createdBy: "auto-fallback" | None`, `message`. 예외: `SandboxPodConflict`, `SandboxPodUnavailable`, `ValueError`(설정 오류), `SandboxPodApiError`(기타).
- `stop_sandbox_pod(settings, db, pod_id: str | None = None) -> dict` — `pod_id` 없으면 `activePodId`, 그것도 없으면 `ValueError("실행 중인 Sandbox Pod가 없습니다.")`.
- attempt 항목: `{"stage": "stop"|"start"|"switch"|"create", "ok": bool, "at": ISO-UTC, "podId"?, "gpuTypeId"?, "error"?, "skipped"?: "vram"}`
- 내부: `_switch_off_others(settings, pods, target_id, attempts)` (stop + `_wait_until_exited` 폴링, 타임아웃 시 `SandboxPodConflict`), `_attempt_start(settings, pod, attempts, *, stage="start"|"switch") -> dict | None` (retry_count+1회, 성공 후 `_sleep(3)` + 재조회, EXITED & runtime null이면 실패 처리), `_attempt_create(settings, attempts) -> tuple[dict, str]`, `_ordered_switch_candidates(pods, priority, exclude_id)` (priority 순, 없으면 `pricePerHr` 오름차순·null은 뒤), `_sleep = time.sleep`, `_now_iso()`, `_short_error()`.

절차(스펙 §5.3 그대로):

```
pods = _resolve_pods(settings); settings_row = sandbox_pod_settings(db)
conflict_ids = _conflict(pods) → 있으면 SandboxPodConflict(running_pod_ids=…)
target = pods[pod_id] (없으면 ValueError 404성 메시지) or pods[selected] or 최근 EXITED
if target RUNNING: 상태 반환(멱등, attempts [])
⓪ _switch_off_others(...)              # 다른 ACTIVE 파드 stop → EXITED 폴링(최대 STOP_WAIT_SECONDS, 3초 간격)
① _attempt_start(target, stage="start") → 성공 시 selected=target 저장, 반환
② settings_row.auto_switch_on_start_failure 이면 후보별 _attempt_start(stage="switch") → 성공 시 selected=후보, switched=True
③④ _attempt_create → 성공 시 selected=새 파드, createdBy="auto-fallback", resolvedBy=f"create:{gpu}"
전부 실패 → SandboxPodUnavailable(attempts)
```

- `_attempt_create`의 create 본문: `{name, templateId, networkVolumeId, gpuTypeIds:[후보], gpuCount, startJupyter: true, startSsh: true}`. `config` 분류 오류는 즉시 `ValueError`. `templateId`는 `RUNPOD_SANDBOX_TEMPLATE_ID` **생성 시에만** 필수(없으면 `ValueError`) — 파드 찾기에는 관여하지 않는다. 새로 생긴 파드는 `templateId`가 남으므로 이후 목록에 볼륨 기준으로 자연히 포함된다.
- 성공 시 `select_sandbox_pod(db, pod_id=…, updated_by="system:auto")`로 DB 갱신(호출자 user id를 인자로 받아도 됨 — API에서 `actor_id` 전달).
- 메시지: 단계별 한국어 문구(스펙 §5.4 예시 참조). GPU 짧은 라벨 `_gpu_label`: `"NVIDIA GeForce RTX 5090"→"RTX 5090"`, `"NVIDIA RTX PRO 6000 Blackwell Workstation Edition"→"RTX PRO 6000 WK"`.

- [ ] **Step 1: 실패 테스트** (스펙 §7-2~7, 9, 10 + 보강)

```python
class SandboxPodStartTests(unittest.TestCase):
    def _run(self, script, *, pod_id=None, settings_overrides=None, db_settings=None, catalog=None): ...
    # 2. 선택 A(EXITED), B RUNNING → stop B → GET B EXITED → start A 200 → 재조회 RUNNING. attempts [stop B ✓, start A ✓]. selected == A
    # 3. stop B 후 폴링 내내 RUNNING(STOP_WAIT_SECONDS=6, _sleep patch) → SandboxPodConflict, POST start 호출 없음
    # 4. start A 500 no instances ×(retry+1) + autoSwitch on → start B 200 + 재조회 RUNNING → selected B, attempts에 switch ✓, switched True
    # 5. start A 실패 + autoSwitch off → create 5090 500 → create PRO4500 200 → gpuTier fallback, createdBy auto-fallback, 본문 startJupyter/startSsh True, gpuTypeIds 단일값
    # 6. create 5090 400 → ValueError, 다음 후보 호출 없음
    # 7. 전 단계 실패 → SandboxPodUnavailable, attempts = stop? + start×2 + switch + create×N, retry_after 300
    # 8. RUNNING 2개 → SandboxPodConflict, stop/start 호출 없음
    # 9. FALLBACK 미설정 → create 1회만
    # 10. catalog에 16GB 후보 → skipped vram 후 다음 후보
    # 11. target RUNNING → 멱등 반환, RunPod 쓰기 호출 없음
    # 12. start 200이지만 재조회 EXITED & runtime null → 실패 간주 → 다음 단계
    # 13. pod_id가 목록에 없음 → ValueError
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과**
- [ ] **Step 3: 커밋** — `feat(sandbox): staged switch→start→switch-pod→create fallback with attempts`

---

### Task 6: API — select/start/stop/settings, 409/503, audit

**Files:**
- Modify: `backend/app/api/v1/sandbox_pod.py` 전체
- Modify: `frontend/src/api/client.ts:1589-1591` (클라이언트 함수), `:1093-1115` (`requestJson` → `ApiError` with `status`/`detail`)
- Test: `backend/tests/test_sandbox_pod_api.py` (신규, `api_client` fixture `conftest.py:40`)

**Interfaces (스펙 §5.4):**
- `GET /api/admin/sandbox-pod` (`sandbox:read`) → Task 4 응답
- `POST /api/admin/sandbox-pod/select {podId}` (`sandbox:control`) → 저장 후 GET 응답과 동일 형태. audit `sandbox_pod.select` before/after `{selectedPodId}`
- `POST /api/admin/sandbox-pod/start {podId?}` → 200 / 400(`ValueError`) / 409(`SandboxPodConflict`, detail `{message, attempts, runningPodIds}`) / 503(`SandboxPodUnavailable`, detail `{message, attempts, retryAfterSeconds}`) / 502(기타 `RuntimeError`). audit 성공 `sandbox_pod.start` after `{desiredStatus, runtimeStatus, attempts, activePodId, gpuTypeId, gpuTier, switched, createdBy}`, 실패 `sandbox_pod.start_failed` after `{attempts, error, status}`.
- `POST /api/admin/sandbox-pod/stop {podId?}` → audit `sandbox_pod.stop` target_id = 정지한 podId
- `PUT /api/admin/sandbox-pod/settings {autoSwitchOnStartFailure, podPriority}` → audit `sandbox_pod.settings_update` before/after payload
- 요청 본문은 pydantic 모델 `SandboxPodTargetBody(podId: str | None = None)`, `SandboxPodSettingsBody`. 기존 프론트가 본문 없이 POST하므로 `Body(default=None)` 허용.
- `except` 순서: `ValueError` → `SandboxPodConflict` → `SandboxPodUnavailable` → `RuntimeError` (앞 둘이 `RuntimeError` 서브클래스).
- `client.ts`: `export class ApiError extends Error { status: number; detail: unknown }`; `selectSandboxPod(podId)`, `startSandboxPod(podId?)`, `stopSandboxPod(podId?)`, `updateSandboxPodSettings(body)`.

- [ ] **Step 1: API 테스트** — 서비스 함수를 `monkeypatch`로 대체해 상태코드·detail·audit 행(`AuditLog` action) 검증: 409, 503, select 저장, settings 갱신, 권한 없는 role 403.
- [ ] **Step 2: 실패 확인 → 구현 → 통과 → 커밋** — `feat(sandbox): select/settings endpoints, 409/503 mapping, audit events`

---

### Task 7: 관측 — 구조화 로그 + EMF 메트릭 4종

**Files:**
- Modify: `backend/app/core/observability.py` (`observe_asset_stream` 아래)
- Modify: `backend/app/services/sandbox_pod_service.py` (`_log_attempt`, 지연 import)
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- `observe_sandbox_pod_attempt(*, stage, pod_id, gpu_type_id, ok, error, skipped)` → `event:"sandbox_pod.attempt"`, Metric `SandboxPodStartAttemptCount`, Dimensions `[["Environment","Stage","GpuTypeId","Ok"]]`
- `observe_sandbox_pod_event(*, kind: "switch"|"fallback"|"conflict", pod_id, gpu_type_id)` → `SandboxPodSwitchCount` / `SandboxPodFallbackCount` / `SandboxPodConflictCount`, Dimensions `[["Environment","GpuTypeId"]]`
- `observability_enabled` False면 no-op. 서비스 쪽은 함수 내부 지연 import(순환 방지) + 예외 삼킴.

- [ ] **Step 1: 테스트** — `patch.object(observability.OBSERVABILITY_LOGGER, "info")`로 payload 캡처, 이름·Dimensions·값 검증.
- [ ] **Step 2: 구현 → 통과 → 커밋** — `feat(sandbox): attempt logs and EMF metrics`

---

### Task 8: 프론트엔드 Sandbox 패널

**Files:**
- Modify: `frontend/src/screens/adminScreens.tsx:472-605`
- Modify: 스타일시트(`v3-sandbox-service-list` 정의 파일)
- Test: `backend/tests/test_frontend_sandbox_pod_contract.py` (신규)

**UI 요구 (스펙 §5.5):**
1. **파드 목록 테이블** (`v3-sandbox-pod-table`): 라디오 · GPU(짧은 라벨) · VRAM/RAM · $/h · 상태 배지(RUNNING/STARTING/EXITED) · 마지막 실행 · 행 액션(RUNNING 행에만 Stop). 라디오 변경 즉시 `selectSandboxPod` → 응답으로 `setSandboxPod`.
2. **Start 버튼**: 선택 파드 기준. `activePodId && activePodId !== selectedPodId`면 라벨 "전환 후 시작", 확인 모달 문구 "현재 실행 중인 {GPU A} 파드를 정지하고 {GPU B} 파드를 시작합니다. 진행 중인 ComfyUI 작업은 중단됩니다." 선택 파드가 RUNNING이면 비활성.
3. **conflict 배너**(`v3-sandbox-conflict`): "실행 중인 Sandbox Pod가 2개입니다. 볼륨 손상 위험" + "선택 파드만 남기고 정지" 버튼 → `conflictPodIds.filter(id => id !== selectedPodId)` 순차 `stopSandboxPod(id)` 후 새로고침. conflict 중 Start 비활성.
4. **상태 카드·HTTP Services**: 현행 유지(응답 단일 필드 = activePod 기준). Jupyter 항목 `authRequired`면 "비밀번호 필요(RunPod 콘솔 env `JUPYTER_PASSWORD`)" 보조 문구. GPU 행에 `gpuTier === "fallback"`이면 `fallback` 배지.
5. **실패 처리**: `controlSandboxPod` catch에서 `setSandboxPod` 호출 금지(이전 상태 유지). `ApiError.detail.attempts`가 있으면 `startFailure`로 저장해 배너에 단계별 렌더(`stop 3i50… ✓ → start caiuv… ✗ 재고 없음 → switch 3i50… ✓`). 성공 응답의 `attempts`도 같은 컴포넌트로 표시(`v3-sandbox-attempt.is-ok/.is-fail`). 409는 "이전 파드 정지 대기 중"/"실행 중 2개" 메시지 그대로.
6. **503 `retryAfterSeconds`**: Start 비활성 + 1초 카운트다운(라벨 `Start (Ns)`).
7. **설정 영역**(`v3-sandbox-settings`): "선택 파드 기동 실패 시 다른 파드 자동 시작" 토글, 우선순위 목록 ▲/▼ 버튼 → `updateSandboxPodSettings`. `canControl`일 때만 편집 가능.
8. `sandboxPodPendingAction` 타입 확장: `"start" | "switch" | "stop" | "stopOthers"`, `pendingPodId`.

- [ ] **Step 1: 컨트랙트 테스트** (`test_frontend_batch_management_contract.py` 패턴, `activeItem="adminSandbox"` ~ `</AppShell>` 구간 추출)

```python
def test_client_has_multi_pod_api(): "selectSandboxPod" / "updateSandboxPodSettings" / "export class ApiError" / 'gpuTier?: "primary" | "fallback" | "unknown"' in CLIENT
def test_panel_renders_pod_table_with_radio_and_switch_label(): "v3-sandbox-pod-table", 'type="radio"', "전환 후 시작", "진행 중인 ComfyUI 작업은 중단됩니다" in section
def test_panel_keeps_last_status_on_failure(): controlSandboxPod 본문에 "setSandboxPod(null)" 없음, catch 블록에 "setStartFailure(" 있음
def test_panel_renders_conflict_banner_and_attempts(): "실행 중인 Sandbox Pod가 2개입니다", "선택 파드만 남기고 정지", "v3-sandbox-attempt", "retryAfterSeconds", 'gpuTier === "fallback"', "authRequired" in section
def test_panel_has_auto_switch_settings(): "자동 시작", "updateSandboxPodSettings" in section
```

- [ ] **Step 2: 실패 확인 → 구현 → `npm run build` + 컨트랙트 통과**
- [ ] **Step 3: 커밋** — `feat(sandbox): pod list with selection, switch confirm, conflict banner, attempts and fallback badge`

---

### Task 9: 운영가이드 갱신 (스펙 §8-4)

**Files:** `runpod mcp/운영가이드-RunPod-ComfyUI-Wan.md`

- [ ] 절 추가: 파드 선택·전환(확인 모달, 작업 중단 경고), 실행 중 1개 불변식과 conflict 배너 처리, 실패 시 자동 대체(순서·`attempts` 읽는 법), fallback 배지와 5090 복귀 절차, Jupyter 비밀번호 파드(`JUPYTER_PASSWORD`) 안내, 환경변수 6개·DB 설정 3개, 롤아웃 순서, CloudWatch 메트릭 4개.
- [ ] 커밋 — `docs(sandbox): operator guide for multi-pod selection and fallback`

---

### Task 10: 통합 검증 + 스펙 구현 메모

- [ ] 전체: `python3.12 -m pytest backend/tests -q`, `npm run build`
- [ ] 불변식 수동 점검(로컬 dev, urlopen mock 또는 RunPod dry): RUNNING 2개 상황에서 GET `conflict: true` & start 409; 전환 시 stop→EXITED 확인 전 start 미호출; fallback 빈 값이면 create 1회.
- [ ] 스펙 §8 아래 "구현 메모(feat/enhance)" 추기: `tuple` 설정, 컨트랙트 테스트 대체, 우선순위 ▲/▼, GET `attempts=[]`, `/gpus`·파드 객체 실제 필드명(`costPerHr`, `memoryInGb`, `env`), 표시 파드 선택 규칙(active → selected → 최근). 커밋 — `docs(sandbox): implementation notes`

---

### Task 11: §6 잔여 검증 (운영, 코드와 분리 — `FALLBACK_TYPE_IDS` 설정 전)

Runpod MCP(`list-gpu-types`, `get-capacity`, `create-pod`, `stream-pod-logs`, `delete-pod`)로 EU-RO-1에서 수행, 결과는 스펙 §6 표에 추기.

- [ ] RTX PRO 4500 Blackwell: 템플릿 `nh1d177m2w`로 1회 기동 → ComfyUI 기동·SageAttention 로드·워크플로 1건 확인(시간당 $0.72 사전 고지). 통과 시 fallback 1순위 확정.
- [ ] RTX PRO 6000 Server: 템플릿 `allowedCudaVersions`에 13.2 포함 여부 확인 후 목록 추가 여부 결정.
- [ ] RTX 4090: `comfyui_args.txt`의 `--use-sage-attention` 처리(compute capability 분기 또는 sm_89 빌드) 전까지 목록 끝 또는 제외.
- [ ] 5090 파드 `caiuvooekq9qqw`: `comfyui_args.txt`에 `--cache-none` 추가(RAM 60 GB OOM 회피) — 볼륨 내 파일, 코드 저장소 밖.
- [ ] 검증 파드 삭제 → 운영 env `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS` 설정, `autoSwitchOnStartFailure` on 확인.

---

## 커밋 순서 요약

0. `fix(sandbox): treat network volume as sole pod identity; template is a creation spec` ← 롤아웃 0단계 경계 (작업 트리에 이미 적용, 커밋만 필요)
1. `feat(sandbox): add multi-pod and GPU fallback settings`
2. `feat(sandbox): persist selected pod and switch settings`
3. `feat(sandbox): classify RunPod errors and select GPU candidates`
4. `feat(sandbox): list every pod on the network volume with conflict detection` ← 롤아웃 1단계 경계
5. `feat(sandbox): staged switch→start→switch-pod→create fallback with attempts`
6. `feat(sandbox): select/settings endpoints, 409/503 mapping, audit events`
7. `feat(sandbox): attempt logs and EMF metrics`
8. `feat(sandbox): pod list with selection, switch confirm, conflict banner, attempts and fallback badge` ← 롤아웃 2단계 경계
9. `docs(sandbox): operator guide for multi-pod selection and fallback`
10. `docs(sandbox): implementation notes`
