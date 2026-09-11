# Sandbox Pod GPU Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자가 Sandbox Pod **Start** 한 번으로 `start → create(1순위 GPU) → create(fallback GPU…)` 를 서버가 자동으로 밟게 하고, 단계별 시도 결과(`attempts`)를 응답·audit·로그·메트릭에 남기며, 프론트는 실패 시 이전 상태를 지우지 않는다.

**Architecture:** 모든 재시도 로직은 `backend/app/services/sandbox_pod_service.py` 안에 둔다. RunPod 오류 분류(`_classify_error`), GPU 후보 선택(`_gpu_candidates`)을 별도 순수 함수로 분리해 REST v2 이관 시에도 재사용한다. 전부 실패는 새 예외 `SandboxPodUnavailable(RuntimeError)`로 표현하고 API 계층이 이를 **503 + 구조화 detail**로 변환한다. 프론트는 `lastKnownStatus`를 유지하고 오류 배너만 갱신한다.

**Tech Stack:** FastAPI + urllib(REST v1) 백엔드, React/TypeScript 프론트, pytest(unittest + urlopen mock), Python 소스 컨트랙트 테스트(프론트).

**Spec:** `docs/superpowers/specs/2026-09-11-sandbox-pod-gpu-fallback-design.md`

**Branch:** `feat/enhance` (base: `feat/s3` HEAD `a386786` — main보다 60커밋 앞선 현재 작업 브랜치. `sandbox_pod_service.py`의 최신 변경이 여기에만 있어 이 브랜치를 base로 함)

## Global Constraints

- 스펙 §4 최종안: 각 create 요청은 **GPU 하나만** `gpuTypeIds:[x]`에 넣는다. 다중값 방식(A안)은 쓰지 않는다.
- `_resolve_pod`, `_present_pod`, `_request`, `_hydrate_pod` 의 기존 시그니처·동작은 유지한다. 새 동작은 `start_sandbox_pod` 와 새 helper에 한정.
- `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS` 미설정 시 **현행과 동일하게** 동작해야 한다(롤아웃 1단계). 모든 테스트에서 이 불변식을 검증한다.
- create 본문에 `dataCenterIds`를 넣지 않는다(볼륨 DC 고정). 파드 이름에 접미사를 붙이지 않는다(`_resolve_pod` name prefix 매칭 보호).
- 실패 응답에서 `httpServices`를 갱신하지 않는다.
- 저장소에 Vitest가 없다(`frontend/package.json` scripts: `tsc -b && vite build`만). 스펙 §7의 "프론트 Vitest"는 기존 관례인 **Python 소스 컨트랙트 테스트**(`backend/tests/test_frontend_*_contract.py`)로 대체한다. Vitest 도입은 범위 밖.
- 스펙 §6 검증(EU-RO-1 재고·CUDA·SageAttention·VRAM)은 **코드 구현과 독립**이며 `FALLBACK_TYPE_IDS`를 운영에 설정하기 전에 완료한다(Task 9). 구현은 빈 fallback으로 먼저 배포 가능해야 한다.
- 검증: `python3.12 -m pytest backend/tests/test_sandbox_pod_service.py backend/tests/test_frontend_sandbox_pod_contract.py -q` 와 `npm run build` 통과 후 완료 보고.
- 작업 트리에 이미 수정된 `metadata/*.json` 3개는 이 작업과 무관하다. 커밋에 포함하지 않는다.

---

### Task 1: Settings 확장 + 환경변수 문서

**Files:**
- Modify: `backend/app/core/config.py:39-50` (필드), `:97-103` (파싱), `:191-202` (생성자 인자)
- Modify: `.env.example:35-37`
- Modify: `docs/aws-ecs-deployment.md:41-46`
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- Produces: `Settings.sandbox_pod_gpu_fallback_type_ids: tuple[str, ...]` (기본 `()`), `sandbox_pod_start_retry_count: int` (기본 `1`), `sandbox_pod_create_attempt_delay_seconds: float` (기본 `2.0`), `sandbox_pod_min_vram_gb: int` (기본 `24`)

- [ ] **Step 1: 실패 테스트 추가**

`backend/tests/test_sandbox_pod_service.py`에 새 클래스 추가:

```python
class SandboxPodSettingsTests(unittest.TestCase):
    def test_fallback_settings_default_to_no_fallback(self) -> None:
        settings = Settings()
        self.assertEqual(settings.sandbox_pod_gpu_fallback_type_ids, ())
        self.assertEqual(settings.sandbox_pod_start_retry_count, 1)
        self.assertEqual(settings.sandbox_pod_create_attempt_delay_seconds, 2.0)
        self.assertEqual(settings.sandbox_pod_min_vram_gb, 24)

    @patch.dict("os.environ", {
        "RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS": " NVIDIA GeForce RTX 4090 , NVIDIA L40S ,, ",
        "RUNPOD_SANDBOX_START_RETRY_COUNT": "0",
        "RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS": "0.5",
        "RUNPOD_SANDBOX_MIN_VRAM_GB": "48",
    })
    def test_fallback_settings_parse_comma_list_and_numbers(self) -> None:
        from backend.app.core.config import get_settings  # 캐시 없음(:87), 매 호출 환경변수 재파싱
        settings = get_settings()
        self.assertEqual(settings.sandbox_pod_gpu_fallback_type_ids, ("NVIDIA GeForce RTX 4090", "NVIDIA L40S"))
        self.assertEqual(settings.sandbox_pod_start_retry_count, 0)
        self.assertEqual(settings.sandbox_pod_create_attempt_delay_seconds, 0.5)
        self.assertEqual(settings.sandbox_pod_min_vram_gb, 48)
```

`Settings`는 `@dataclass(frozen=True)`(`config.py:11`)이므로 fallback 목록은 **`tuple[str, ...]`**(기본 `()`)로 둔다 — 해시 가능성 유지, `[]` 기본값 금지. 스펙의 `list[str]`는 이 튜플로 대체(사용처는 iterate만 함).

- [ ] **Step 2: 실패 확인**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py::SandboxPodSettingsTests -q
```

Expected: `AttributeError: 'Settings' object has no attribute 'sandbox_pod_gpu_fallback_type_ids'`.

- [ ] **Step 3: Settings 필드 추가**

`config.py:50` 뒤에:

```python
    sandbox_pod_gpu_fallback_type_ids: tuple[str, ...] = ()
    sandbox_pod_start_retry_count: int = 1
    sandbox_pod_create_attempt_delay_seconds: float = 2.0
    sandbox_pod_min_vram_gb: int = 24
```

- [ ] **Step 4: 파싱 추가**

`config.py:97-103` 근처 기존 `sandbox_pod_timeout`/`gpu_count` try/except 패턴을 따라:

```python
    sandbox_pod_gpu_fallback_type_ids = tuple(
        item.strip()
        for item in os.environ.get("RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS", "").split(",")
        if item.strip()
    )
    try:
        sandbox_pod_start_retry_count = max(0, int(os.environ.get("RUNPOD_SANDBOX_START_RETRY_COUNT", "1")))
    except ValueError:
        sandbox_pod_start_retry_count = 1
    try:
        sandbox_pod_create_attempt_delay_seconds = max(0.0, float(os.environ.get("RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS", "2")))
    except ValueError:
        sandbox_pod_create_attempt_delay_seconds = 2.0
    try:
        sandbox_pod_min_vram_gb = max(0, int(os.environ.get("RUNPOD_SANDBOX_MIN_VRAM_GB", "24")))
    except ValueError:
        sandbox_pod_min_vram_gb = 24
```

그리고 `:196` 뒤 생성자 호출에 4개 인자 전달.

- [ ] **Step 5: `.env.example`, `docs/aws-ecs-deployment.md` §1 갱신**

`.env.example:35` 다음에:

```
RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS=
RUNPOD_SANDBOX_START_RETRY_COUNT=1
RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS=2
RUNPOD_SANDBOX_MIN_VRAM_GB=24
```

`docs/aws-ecs-deployment.md:41` 다음에 같은 4줄(값은 `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS=NVIDIA GeForce RTX 4090,NVIDIA L40S` 예시). §1 아래 설명 문단(`:68` 근처)에 "빈 값이면 fallback 없음, §6 검증 후 설정" 한 줄 추가.

- [ ] **Step 6: 테스트 통과 확인 후 커밋**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py -q
git add backend/app/core/config.py .env.example docs/aws-ecs-deployment.md backend/tests/test_sandbox_pod_service.py
git commit -m "feat(sandbox): add GPU fallback settings"
```

---

### Task 2: RunPod 오류 분류 + GPU 후보 선택 순수 함수

**Files:**
- Modify: `backend/app/services/sandbox_pod_service.py` (`_request` 아래에 helper 추가, `:191-213`)
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- Produces: `class SandboxPodApiError(RuntimeError)` — `status: int | None`, `detail: str` 속성. `_request`가 HTTPError 시 이것을 raise (기존 `RuntimeError` 서브클래스라 호출부 호환).
- Produces: `_classify_error(exc: Exception) -> Literal["no_capacity", "not_found", "config", "transient", "unknown"]`
  - `no_capacity`: 본문에 `no instances` / `not available` 포함, 또는 HTTP 500·503
  - `not_found`: HTTP 404
  - `config`: HTTP 400·401·403·422
  - `transient`: `URLError` 계열(연결 실패)
- Produces: `_gpu_candidates(settings, vram_by_gpu: dict[str, float] | None) -> list[tuple[str, str | None]]` — `[(gpu_type_id, skip_reason)]`. 1순위 + fallback을 중복 제거하며 순서 유지, `vram_by_gpu`가 주어지고 값이 `min_vram_gb` 미만이면 `skip_reason="vram"`.
- Produces: `_fetch_gpu_vram(settings) -> dict[str, float] | None` — `GET /gpus` 호출, 실패 시 `None`(필터 생략).

- [ ] **Step 1: 실패 테스트 추가**

```python
class SandboxPodFallbackHelpersTests(unittest.TestCase):
    def test_classifies_no_capacity_from_body_and_5xx(self) -> None:
        from backend.app.services.sandbox_pod_service import SandboxPodApiError, _classify_error
        self.assertEqual(_classify_error(SandboxPodApiError(500, '{"error":"create pod: There are no instances currently available"}')), "no_capacity")
        self.assertEqual(_classify_error(SandboxPodApiError(503, "")), "no_capacity")
        self.assertEqual(_classify_error(SandboxPodApiError(404, "pod not found")), "not_found")
        for code in (400, 401, 403, 422):
            self.assertEqual(_classify_error(SandboxPodApiError(code, "bad")), "config")
        self.assertEqual(_classify_error(RuntimeError("Sandbox Pod API 연결 실패: timed out")), "transient")

    def test_gpu_candidates_preserve_priority_and_dedupe(self) -> None:
        from backend.app.services.sandbox_pod_service import _gpu_candidates
        settings = Settings(sandbox_pod_gpu_type_id="NVIDIA GeForce RTX 5090",
                            sandbox_pod_gpu_fallback_type_ids=("NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 5090", "NVIDIA L40S"))
        self.assertEqual(_gpu_candidates(settings, None),
                         [("NVIDIA GeForce RTX 5090", None), ("NVIDIA GeForce RTX 4090", None), ("NVIDIA L40S", None)])

    def test_gpu_candidates_skip_low_vram_when_catalog_available(self) -> None:
        from backend.app.services.sandbox_pod_service import _gpu_candidates
        settings = Settings(sandbox_pod_gpu_type_id="NVIDIA GeForce RTX 5090",
                            sandbox_pod_gpu_fallback_type_ids=("NVIDIA RTX A4000", "NVIDIA L40S"), sandbox_pod_min_vram_gb=24)
        vram = {"NVIDIA GeForce RTX 5090": 32, "NVIDIA RTX A4000": 16, "NVIDIA L40S": 48}
        self.assertEqual(_gpu_candidates(settings, vram),
                         [("NVIDIA GeForce RTX 5090", None), ("NVIDIA RTX A4000", "vram"), ("NVIDIA L40S", None)])

    def test_gpu_candidates_without_fallback_is_primary_only(self) -> None:
        from backend.app.services.sandbox_pod_service import _gpu_candidates
        settings = Settings(sandbox_pod_gpu_type_id="NVIDIA GeForce RTX 5090")
        self.assertEqual(_gpu_candidates(settings, None), [("NVIDIA GeForce RTX 5090", None)])
```

- [ ] **Step 2: 실패 확인**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py::SandboxPodFallbackHelpersTests -q
```

Expected: `ImportError: cannot import name 'SandboxPodApiError'`.

- [ ] **Step 3: 구현**

`sandbox_pod_service.py:14` 근처에 예외 정의:

```python
class SandboxPodApiError(RuntimeError):
    def __init__(self, status: int | None, detail: str) -> None:
        self.status = status
        self.detail = detail
        prefix = f"Sandbox Pod API HTTP {status}" if status else "Sandbox Pod API 연결 실패"
        super().__init__(f"{prefix}: {detail}" if detail else prefix)


class SandboxPodUnavailable(RuntimeError):
    def __init__(self, message: str, attempts: list[dict], *, retry_after_seconds: int = 300) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.retry_after_seconds = retry_after_seconds
```

`_request:209-213`의 두 `raise RuntimeError(...)`를 `raise SandboxPodApiError(exc.code, detail)` / `raise SandboxPodApiError(None, str(exc.reason))`로 교체. 기존 테스트 `test_runpod_rest_request_uses_explicit_http_client_headers`와 `_hydrate_pod`의 `except RuntimeError`는 서브클래스라 그대로 통과.

helper:

```python
_NO_CAPACITY_MARKERS = ("no instances", "not available", "no longer available")


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, SandboxPodApiError):
        body = (exc.detail or "").lower()
        if exc.status is None:
            return "transient"
        if exc.status == 404:
            return "not_found"
        if exc.status in {400, 401, 403, 422}:
            return "config"
        if any(marker in body for marker in _NO_CAPACITY_MARKERS) or exc.status in {500, 503}:
            return "no_capacity"
        return "unknown"
    if "연결 실패" in str(exc):
        return "transient"
    return "unknown"


def _gpu_candidates(settings: Settings, vram_by_gpu: dict[str, float] | None) -> list[tuple[str, str | None]]:
    ordered: list[str] = []
    for gpu in [settings.sandbox_pod_gpu_type_id, *settings.sandbox_pod_gpu_fallback_type_ids]:
        gpu = gpu.strip()
        if gpu and gpu not in ordered:
            ordered.append(gpu)
    result = []
    for gpu in ordered:
        reason = None
        if vram_by_gpu is not None and gpu in vram_by_gpu and vram_by_gpu[gpu] < settings.sandbox_pod_min_vram_gb:
            reason = "vram"
        result.append((gpu, reason))
    return result


def _fetch_gpu_vram(settings: Settings) -> dict[str, float] | None:
    try:
        response = _request(settings, "GET", "/gpus")
    except RuntimeError:
        return None
    items = response if isinstance(response, list) else response.get("items") or response.get("gpus") or []
    result: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        gpu_id = str(item.get("id") or item.get("displayName") or "").strip()
        vram = _number_or_none(item.get("memoryInGb"))
        if gpu_id and vram is not None:
            result[gpu_id] = float(vram)
    return result or None
```

주의: REST v1 `/gpus` 응답의 실제 필드명(`id` vs `displayName`, `memoryInGb`)은 구현 시 `rest.runpod.io/v1/gpus`로 1회 확인하고 위 파싱을 맞춘다. 1순위 GPU는 VRAM 필터 대상에서 제외하지 않는다(스펙은 "fallback 후보 중"이라 했으나 1순위는 운영자가 명시한 값이므로 skip되어도 `attempts`에 기록되면 원인이 드러남 — 구현 시 1순위는 필터 제외로 단순화해도 됨; 테스트 `test_gpu_candidates_skip_low_vram...`의 기대값을 그에 맞춰 고정).

- [ ] **Step 4: 통과 확인 후 커밋**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py -q
git commit -am "feat(sandbox): classify RunPod errors and select GPU candidates"
```

---

### Task 3: `start_sandbox_pod` 단계형 재시도 (start → create → fallback)

**Files:**
- Modify: `backend/app/services/sandbox_pod_service.py:38-46` (`start_sandbox_pod`), `:63-87` (`_deploy_sandbox_pod`)
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- `start_sandbox_pod(settings) -> dict` 반환값에 `attempts: list[dict]`, `gpuTypeId`, `gpuTier`, `createdBy` 추가. 전부 실패 시 `SandboxPodUnavailable` raise (attempts 포함).
- attempt 항목: `{"stage": "start"|"create", "ok": bool, "at": ISO-UTC, "podId"?: str, "gpuTypeId"?: str, "error"?: str, "skipped"?: "vram"}`
- 내부: `_attempt_start(settings, pod, attempts) -> dict | None`, `_attempt_create(settings, attempts) -> dict` (성공 pod dict 반환 또는 `SandboxPodUnavailable`/`ValueError`), `_sleep = time.sleep` 모듈 변수(테스트에서 patch).

- [ ] **Step 1: 테스트 fixture 작성**

`urlopen` mock으로 `(method, path) → 응답 시퀀스`를 스크립트하는 helper를 테스트 파일에 추가:

```python
import urllib.error
from io import BytesIO


class _FakeResponse:
    def __init__(self, body: dict | list) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.status = 200
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self) -> bytes: return self._body


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://rest.runpod.io/v1", code, "err", hdrs=None, fp=BytesIO(body.encode("utf-8")))


class _RunPodScript:
    """method+path 별 응답 큐. 항목이 Exception이면 raise."""
    def __init__(self, script: dict[tuple[str, str], list]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, str, dict | None]] = []
    def __call__(self, request, timeout):
        path = request.full_url.replace("https://rest.runpod.io/v1", "")
        body = json.loads(request.data) if request.data else None
        self.calls.append((request.get_method(), path, body))
        key = (request.get_method(), path.split("?")[0])
        queue = self.script.get(key) or []
        if not queue:
            raise AssertionError(f"unexpected call {key}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


FALLBACK_SETTINGS = dict(
    sandbox_pod_api_key="k", sandbox_pod_network_volume_id="18jhx6rxjd", sandbox_pod_template_id="nh1d177m2w",
    sandbox_pod_gpu_type_id="NVIDIA GeForce RTX 5090",
    sandbox_pod_gpu_fallback_type_ids=("NVIDIA GeForce RTX 4090", "NVIDIA L40S"),
    sandbox_pod_create_attempt_delay_seconds=0,
)
EXITED_POD = {"id": "s2lqjdfpdoyqa0", "name": "dobedub_comfyUI_Sandbox", "desiredStatus": "EXITED",
              "templateId": "nh1d177m2w", "networkVolume": {"id": "18jhx6rxjd"}, "ports": ["8188/http"]}
NO_CAP = '{"error":"create pod: There are no instances currently available","status":500}'
```

모든 시나리오 테스트는 `@patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="INITIALIZING")`, `@patch("...._runtime_metrics", return_value={"available": False, "gpus": []})`, `@patch("...._sleep")`, `@patch("...._fetch_gpu_vram", return_value=None)`(VRAM 테스트 제외)로 외부 호출을 차단한다.

- [ ] **Step 2: 시나리오 테스트 7건 추가 (스펙 §7)**

```python
class SandboxPodStartFallbackTests(unittest.TestCase):
    def _run(self, script, **overrides):
        settings = Settings(**{**FALLBACK_SETTINGS, **overrides})
        fake = _RunPodScript(script)
        with patch("backend.app.services.sandbox_pod_service.urllib.request.urlopen", side_effect=fake), \
             patch("backend.app.services.sandbox_pod_service._runtime_status", return_value="INITIALIZING"), \
             patch("backend.app.services.sandbox_pod_service._runtime_metrics", return_value={"available": False, "gpus": []}), \
             patch("backend.app.services.sandbox_pod_service._sleep"), \
             patch("backend.app.services.sandbox_pod_service._fetch_gpu_vram", return_value=None):
            from backend.app.services.sandbox_pod_service import start_sandbox_pod
            return start_sandbox_pod(settings), fake

    def test_1_exited_start_succeeds_without_create(self) -> None:
        running = {**EXITED_POD, "desiredStatus": "RUNNING", "runtime": {"uptimeInSeconds": 1}}
        result, fake = self._run({
            ("GET", "/pods"): [[EXITED_POD]],
            ("GET", "/pods/s2lqjdfpdoyqa0"): [EXITED_POD, running],
            ("POST", "/pods/s2lqjdfpdoyqa0/start"): [{}],
        })
        self.assertEqual([a["stage"] for a in result["attempts"]], ["start"])
        self.assertTrue(result["attempts"][0]["ok"])
        self.assertEqual(result["gpuTier"], "primary")
        self.assertFalse(any(m == "POST" and p == "/pods" for m, p, _ in fake.calls))

    def test_2_start_no_capacity_then_primary_fails_then_fallback_succeeds(self) -> None:
        created = {"id": "caiuvooekq9qqw", "desiredStatus": "CREATED", "gpuTypeIds": ["NVIDIA GeForce RTX 4090"], "ports": ["8188/http"]}
        result, fake = self._run({
            ("GET", "/pods"): [[EXITED_POD]],
            ("GET", "/pods/s2lqjdfpdoyqa0"): [EXITED_POD],
            ("POST", "/pods/s2lqjdfpdoyqa0/start"): [_http_error(500, NO_CAP), _http_error(500, NO_CAP)],  # retry_count=1 → 2회
            ("POST", "/pods"): [_http_error(500, NO_CAP), created],
        })
        stages = [(a["stage"], a.get("gpuTypeId"), a["ok"]) for a in result["attempts"]]
        self.assertEqual(stages, [("start", None, False), ("start", None, False),
                                  ("create", "NVIDIA GeForce RTX 5090", False), ("create", "NVIDIA GeForce RTX 4090", True)])
        self.assertEqual(result["gpuTier"], "fallback")
        self.assertEqual(result["gpuTypeId"], "NVIDIA GeForce RTX 4090")
        self.assertEqual(result["createdBy"], "auto-fallback")
        self.assertEqual(result["resolvedBy"], "template+network-volume+gpu:NVIDIA GeForce RTX 4090")
        create_bodies = [b for m, p, b in fake.calls if m == "POST" and p == "/pods"]
        self.assertEqual([b["gpuTypeIds"] for b in create_bodies], [["NVIDIA GeForce RTX 5090"], ["NVIDIA GeForce RTX 4090"]])
        self.assertNotIn("dataCenterIds", create_bodies[0])
        self.assertEqual(create_bodies[1]["name"], "dobedub_comfyUI_Sandbox")
        self.assertIn("4090", result["message"])

    def test_3_terminated_skips_start(self) -> None:
        terminated = {**EXITED_POD, "desiredStatus": "TERMINATED"}
        created = {"id": "new1", "desiredStatus": "CREATED", "gpuTypeIds": ["NVIDIA GeForce RTX 5090"], "ports": ["8188/http"]}
        result, fake = self._run({
            ("GET", "/pods"): [[terminated]],
            ("GET", "/pods/s2lqjdfpdoyqa0"): [terminated],
            ("POST", "/pods"): [created],
        })
        self.assertEqual([a["stage"] for a in result["attempts"]], ["create"])
        self.assertEqual(result["gpuTier"], "primary")

    def test_4_config_error_stops_immediately(self) -> None:
        with self.assertRaises(ValueError):
            self._run({
                ("GET", "/pods"): [[{**EXITED_POD, "desiredStatus": "TERMINATED"}]],
                ("GET", "/pods/s2lqjdfpdoyqa0"): [{**EXITED_POD, "desiredStatus": "TERMINATED"}],
                ("POST", "/pods"): [_http_error(400, '{"error":"templateId invalid"}')],
            })
        # 4090 시도 없음은 큐가 1개뿐이므로 AssertionError 없이 통과하면 검증됨

    def test_5_all_candidates_fail_raises_unavailable_with_attempts(self) -> None:
        from backend.app.services.sandbox_pod_service import SandboxPodUnavailable
        with self.assertRaises(SandboxPodUnavailable) as ctx:
            self._run({
                ("GET", "/pods"): [[EXITED_POD]],
                ("GET", "/pods/s2lqjdfpdoyqa0"): [EXITED_POD],
                ("POST", "/pods/s2lqjdfpdoyqa0/start"): [_http_error(500, NO_CAP)],
                ("POST", "/pods"): [_http_error(500, NO_CAP)] * 3,
            }, sandbox_pod_start_retry_count=0)
        self.assertEqual(len(ctx.exception.attempts), 4)
        self.assertEqual(ctx.exception.retry_after_seconds, 300)
        self.assertIn("5090", str(ctx.exception))

    def test_6_no_fallback_configured_matches_legacy_single_create(self) -> None:
        from backend.app.services.sandbox_pod_service import SandboxPodUnavailable
        with self.assertRaises(SandboxPodUnavailable) as ctx:
            self._run({
                ("GET", "/pods"): [[{**EXITED_POD, "desiredStatus": "TERMINATED"}]],
                ("GET", "/pods/s2lqjdfpdoyqa0"): [{**EXITED_POD, "desiredStatus": "TERMINATED"}],
                ("POST", "/pods"): [_http_error(500, NO_CAP)],
            }, sandbox_pod_gpu_fallback_type_ids=())
        self.assertEqual([a.get("gpuTypeId") for a in ctx.exception.attempts], ["NVIDIA GeForce RTX 5090"])

    def test_7_vram_filter_records_skip_then_continues(self) -> None:
        created = {"id": "new2", "desiredStatus": "CREATED", "gpuTypeIds": ["NVIDIA L40S"], "ports": ["8188/http"]}
        settings_overrides = dict(sandbox_pod_gpu_fallback_type_ids=("NVIDIA RTX A4000", "NVIDIA L40S"))
        with patch("backend.app.services.sandbox_pod_service._fetch_gpu_vram",
                   return_value={"NVIDIA GeForce RTX 5090": 32, "NVIDIA RTX A4000": 16, "NVIDIA L40S": 48}):
            # _run 내부 patch가 이 patch를 덮으므로 _run에 fetch_vram 인자를 추가해 주입하도록 helper를 확장한다
            result, fake = self._run({...}, **settings_overrides)
        skipped = [a for a in result["attempts"] if a.get("skipped") == "vram"]
        self.assertEqual(skipped[0]["gpuTypeId"], "NVIDIA RTX A4000")
        self.assertEqual(result["gpuTypeId"], "NVIDIA L40S")
```

추가로 스펙 §5.2 "start 성공 후 GPU 미배정" 케이스:

```python
    def test_8_start_ok_but_pod_stays_exited_falls_through_to_create(self) -> None:
        # start 200 → 재조회 desiredStatus EXITED, runtime null → create 진행
```

- [ ] **Step 3: 실패 확인**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py::SandboxPodStartFallbackTests -q
```

Expected: `KeyError: 'attempts'` 등.

- [ ] **Step 4: `start_sandbox_pod` 재작성**

```python
import time
_sleep = time.sleep
_ACTIVE_STATES = {"RUNNING", "STARTING", "PENDING", "CREATED", "RESTARTING"}
_START_RECHECK_DELAY_SECONDS = 3


def start_sandbox_pod(settings: Settings) -> dict:
    _require_configuration(settings)
    attempts: list[dict] = []
    try:
        pod, resolved_by = _resolve_pod(settings)
    except ValueError as exc:
        # selector에 일치 파드 없음 → create로
        if "찾지 못했습니다" not in str(exc):
            raise
        pod, resolved_by = None, ""

    if pod is not None:
        status = str(pod.get("desiredStatus") or "").upper()
        if status in _ACTIVE_STATES:
            response = _request(settings, "POST", f"/pods/{pod['id']}/start")
            result = _present_pod(settings, _hydrate_pod(settings, response or pod, strict=False), resolved_by)
            result["message"] = "Sandbox Pod 시작을 요청했습니다. RUNNING 상태와 HTTP 서비스 준비 여부를 새로고침으로 확인하세요."
            return _with_attempt_fields(settings, result, attempts, created_by=None)
        if status == "EXITED":
            started = _attempt_start(settings, pod, attempts)
            if started is not None:
                result = _present_pod(settings, started, resolved_by)
                result["message"] = "정지된 Sandbox Pod를 다시 시작했습니다. HTTP 서비스 준비 여부를 새로고침으로 확인하세요."
                return _with_attempt_fields(settings, result, attempts, created_by=None)
        # TERMINATED 또는 start 실패 → create

    created_pod, gpu = _attempt_create(settings, attempts)
    result = _present_pod(settings, created_pod, f"template+network-volume+gpu:{gpu}")
    result["message"] = _create_message(settings, gpu, attempts)
    return _with_attempt_fields(settings, result, attempts, created_by="auto-fallback")
```

`_attempt_start`:

```python
def _attempt_start(settings: Settings, pod: dict, attempts: list[dict]) -> dict | None:
    pod_id = str(pod["id"])
    for _ in range(settings.sandbox_pod_start_retry_count + 1):
        entry = {"stage": "start", "podId": pod_id, "at": _now_iso()}
        try:
            _request(settings, "POST", f"/pods/{pod_id}/start")
        except RuntimeError as exc:
            kind = _classify_error(exc)
            attempts.append({**entry, "ok": False, "error": _short_error(exc)})
            _log_attempt(settings, attempts[-1])
            if kind in {"no_capacity", "not_found", "transient", "unknown"}:
                continue
            raise  # config 오류는 그대로 전파(API에서 400)
        _sleep(_START_RECHECK_DELAY_SECONDS)
        refreshed = _hydrate_pod(settings, pod, strict=False)
        if str(refreshed.get("desiredStatus") or "").upper() == "EXITED" and not refreshed.get("runtime"):
            attempts.append({**entry, "ok": False, "error": "start accepted but pod stayed EXITED (no GPU assigned)"})
            _log_attempt(settings, attempts[-1])
            continue
        attempts.append({**entry, "ok": True})
        _log_attempt(settings, attempts[-1])
        return refreshed
    return None
```

`_attempt_create`(기존 `_deploy_sandbox_pod`의 검증·본문 구성을 옮김):

```python
def _attempt_create(settings: Settings, attempts: list[dict]) -> tuple[dict, str]:
    template_id = settings.sandbox_pod_template_id.strip()
    network_volume_id = settings.sandbox_pod_network_volume_id.strip()
    if not (template_id and network_volume_id and settings.sandbox_pod_gpu_type_id.strip()):
        raise ValueError("새 Sandbox Pod 생성에는 RUNPOD_SANDBOX_TEMPLATE_ID, RUNPOD_SANDBOX_NETWORK_VOLUME_ID, RUNPOD_SANDBOX_GPU_TYPE_ID가 필요합니다.")
    candidates = _gpu_candidates(settings, _fetch_gpu_vram(settings))
    tried: list[str] = []
    for index, (gpu, skip_reason) in enumerate(candidates):
        entry = {"stage": "create", "gpuTypeId": gpu, "at": _now_iso()}
        if skip_reason:
            attempts.append({**entry, "ok": False, "skipped": skip_reason})
            _log_attempt(settings, attempts[-1]); continue
        if tried and settings.sandbox_pod_create_attempt_delay_seconds > 0:
            _sleep(settings.sandbox_pod_create_attempt_delay_seconds)
        tried.append(gpu)
        try:
            response = _request(settings, "POST", "/pods", {
                "name": settings.sandbox_pod_deploy_name.strip() or "dobedub_comfyUI_Sandbox",
                "templateId": template_id, "networkVolumeId": network_volume_id,
                "gpuTypeIds": [gpu], "gpuCount": settings.sandbox_pod_gpu_count,
            })
        except RuntimeError as exc:
            kind = _classify_error(exc)
            attempts.append({**entry, "ok": False, "error": _short_error(exc)})
            _log_attempt(settings, attempts[-1])
            if kind == "config":
                raise ValueError(f"Sandbox Pod 생성 설정 오류 ({gpu}): {_short_error(exc)}") from exc
            continue
        attempts.append({**entry, "ok": True, "podId": str(response.get("id") or "")})
        _log_attempt(settings, attempts[-1])
        if index > 0 or any(a["stage"] == "start" for a in attempts):
            _emit_fallback_metric(settings, gpu)  # Task 5
        return response, gpu
    raise SandboxPodUnavailable(_unavailable_message(tried), attempts)
```

보조: `_now_iso()` (`utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")`), `_short_error(exc)` (HTTPError 본문에서 `error` 키 추출, 200자 제한), `_unavailable_message(tried)` → `"사용 가능한 GPU가 없습니다. ({'·'.join(_gpu_label(g) for g in tried)} 모두 재고 없음)"`, `_gpu_label("NVIDIA GeForce RTX 5090") == "RTX 5090"`, `_create_message(settings, gpu, attempts)` → 1순위면 기존 문구, fallback이면 스펙 §5.3 문구.

`_with_attempt_fields`:

```python
def _with_attempt_fields(settings: Settings, result: dict, attempts: list[dict], *, created_by: str | None) -> dict:
    gpu = result.get("systemStatus", {}).get("gpuType")
    primary = settings.sandbox_pod_gpu_type_id.strip()
    result["gpuTypeId"] = gpu
    result["gpuTier"] = "unknown" if not gpu else ("primary" if gpu == primary else "fallback")
    result["attempts"] = attempts
    result["createdBy"] = created_by
    return result
```

`sandbox_pod_status()`(GET)에도 `gpuTypeId`/`gpuTier`/`attempts: []`를 붙이도록 `_present_pod` 끝에서 `_with_attempt_fields(settings, status, [], created_by=None)`를 호출하거나 `_present_pod` 자체에 필드를 넣는다(GET의 `attempts`는 서버 무상태이므로 `[]` 고정 — 스펙 "마지막 start의 기록 또는 []" 중 `[]` 채택, 이유: ECS 다중 태스크에서 메모리 캐시는 불일치).

`_deploy_sandbox_pod`는 삭제(호출부 없음 확인 후).

- [ ] **Step 5: 전체 테스트 통과 후 커밋**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py -q
git commit -am "feat(sandbox): staged start→create→GPU fallback with attempts"
```

---

### Task 4: API 계층 — 503 구조화 응답 + audit `start_failed`

**Files:**
- Modify: `backend/app/api/v1/sandbox_pod.py:24-46`
- Modify: `frontend/src/api/client.ts:187-230` (타입, Task 6에서 함께)
- Test: `backend/tests/test_sandbox_pod_api.py` (신규, `api_client` fixture 사용 — `test_prompt_batch_api.py` 참고)

**Interfaces:**
- `POST /api/admin/sandbox-pod/start`: 성공 200 (기존 + `attempts/gpuTypeId/gpuTier/createdBy`); `SandboxPodUnavailable` → **503** `{"detail": {"message", "attempts", "retryAfterSeconds"}}`; 기타 `RuntimeError` → 502(기존).
- audit: 성공 `sandbox_pod.start` `after={desiredStatus, runtimeStatus, attempts, gpuTypeId, gpuTier, createdBy}`; 실패 `sandbox_pod.start_failed` `after={attempts, error}` (`target_id`는 마지막 attempt의 podId 또는 "").

- [ ] **Step 1: API 테스트 작성**

```python
def test_start_returns_503_with_attempts_and_records_failed_audit(api_client, monkeypatch):
    from backend.app.services.sandbox_pod_service import SandboxPodUnavailable
    attempts = [{"stage": "create", "gpuTypeId": "NVIDIA GeForce RTX 5090", "ok": False, "error": "HTTP 500: no instances", "at": "2026-09-11T00:20:31Z"}]
    monkeypatch.setattr("backend.app.api.v1.sandbox_pod.start_sandbox_pod",
                        lambda settings: (_ for _ in ()).throw(SandboxPodUnavailable("GPU 없음", attempts)))
    response = api_client.post("/api/admin/sandbox-pod/start", headers=_headers("admin", role="admin"))
    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["message"] == "GPU 없음"
    assert body["attempts"] == attempts
    assert body["retryAfterSeconds"] == 300
    # audit 확인: AuditLog 테이블에서 action == "sandbox_pod.start_failed" 1건, after["attempts"] == attempts


def test_start_success_audit_includes_fallback_fields(api_client, monkeypatch):
    ...  # start_sandbox_pod을 dict 반환으로 patch, audit after에 gpuTier/attempts/createdBy 포함 확인
```

`_headers`와 권한(`sandbox:control`)이 있는 role은 `backend/app/core/security.py`/`permission_service.py`에서 확인. `api_client` fixture는 `backend/tests/conftest.py:40`에 있음.

- [ ] **Step 2: 실패 확인**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_api.py -q
```

Expected: `assert 502 == 503`.

- [ ] **Step 3: 구현**

`sandbox_pod.py:30-46`:

```python
    try:
        result = start_sandbox_pod(get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SandboxPodUnavailable as exc:
        record_audit_log(db, actor_id=current_user.id, action="sandbox_pod.start_failed", target_type="sandbox_pod",
                         target_id=_last_pod_id(exc.attempts), before=None,
                         after={"attempts": exc.attempts, "error": str(exc)},
                         ip=request.client.host if request.client else None)
        raise HTTPException(status_code=503, detail={"message": str(exc), "attempts": exc.attempts,
                                                     "retryAfterSeconds": exc.retry_after_seconds}) from exc
    except RuntimeError as exc:
        record_audit_log(... action="sandbox_pod.start_failed", after={"attempts": [], "error": str(exc)} ...)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record_audit_log(..., after={
        "desiredStatus": result.get("desiredStatus"), "runtimeStatus": result.get("runtimeStatus"),
        "attempts": result.get("attempts", []), "gpuTypeId": result.get("gpuTypeId"),
        "gpuTier": result.get("gpuTier"), "createdBy": result.get("createdBy"),
    })
```

`SandboxPodUnavailable`는 `RuntimeError` 서브클래스이므로 **반드시 `except RuntimeError`보다 앞에** 둔다.

- [ ] **Step 4: 통과 확인 후 커밋**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_api.py backend/tests/test_sandbox_pod_service.py -q
git add backend/app/api/v1/sandbox_pod.py backend/tests/test_sandbox_pod_api.py
git commit -m "feat(sandbox): 503 with attempts and start_failed audit"
```

---

### Task 5: 관측 — 구조화 로그 + EMF 메트릭

**Files:**
- Modify: `backend/app/core/observability.py` (`observe_asset_stream` 아래, `:119` 근처)
- Modify: `backend/app/services/sandbox_pod_service.py` (`_log_attempt`, `_emit_fallback_metric` 구현)
- Test: `backend/tests/test_sandbox_pod_service.py`

**Interfaces:**
- `observability.observe_sandbox_pod_attempt(*, stage: str, gpu_type_id: str | None, ok: bool, error: str | None, skipped: str | None) -> None` — `OBSERVABILITY_LOGGER.info(json)` 로 EMF payload 1건. Namespace `DOBEDUB/Studio`, Dimensions `[["Environment","Stage","GpuTypeId","Ok"]]`, Metric `SandboxPodStartAttemptCount` (Count=1). `event: "sandbox_pod.attempt"`.
- `observability.observe_sandbox_pod_fallback(*, gpu_type_id: str) -> None` — Metric `SandboxPodFallbackCount`, Dimensions `[["Environment","GpuTypeId"]]`.
- `settings.observability_enabled`가 False면 no-op(기존 함수와 동일).

- [ ] **Step 1: 테스트**

```python
class SandboxPodObservabilityTests(unittest.TestCase):
    def test_attempt_emits_emf_payload(self) -> None:
        from backend.app.core import observability
        with self.assertLogs("dobedub.observability", level="INFO") as logs:
            observability.observe_sandbox_pod_attempt(stage="create", gpu_type_id="NVIDIA GeForce RTX 5090", ok=False, error="HTTP 500: no instances", skipped=None)
        payload = json.loads(logs.output[0].split(":", 2)[2])
        self.assertEqual(payload["event"], "sandbox_pod.attempt")
        self.assertEqual(payload["SandboxPodStartAttemptCount"], 1)
        self.assertEqual(payload["Stage"], "create")
        self.assertEqual(payload["Ok"], "false")
        self.assertEqual(payload["_aws"]["CloudWatchMetrics"][0]["Dimensions"], [["Environment", "Stage", "GpuTypeId", "Ok"]])
```

(`OBSERVABILITY_LOGGER.propagate = False` 라 `assertLogs`가 못 잡으면 `patch.object(observability.OBSERVABILITY_LOGGER, "info")`로 캡처.)

- [ ] **Step 2: 실패 확인, 구현, 통과**

`sandbox_pod_service.py`에서 `from backend.app.core import observability`는 **함수 내부 지연 import**로 한다(observability가 `get_settings`를 import하므로 순환 방지). `_log_attempt(settings, entry)`는 `observability.observe_sandbox_pod_attempt(...)`를 호출하고 예외는 삼킨다(관측 장애가 파드 제어를 막으면 안 됨).

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py -q
git commit -am "feat(sandbox): attempt logs and EMF metrics"
```

---

### Task 6: 프론트엔드 — 타입 + 실패 시 상태 유지 + attempts 배너 + fallback 배지 + retryAfter 카운트다운

**Files:**
- Modify: `frontend/src/api/client.ts:187-230` (`SandboxPodStatus` 타입), `:1093-1115` (`requestJson` 오류 detail 객체 보존)
- Modify: `frontend/src/screens/adminScreens.tsx:472-605` (Sandbox 패널)
- Test: `backend/tests/test_frontend_sandbox_pod_contract.py` (신규, `test_frontend_batch_management_contract.py` 패턴)

**Interfaces:**
- `SandboxPodStatus`에 추가: `gpuTypeId?: string | null; gpuTier?: "primary" | "fallback" | "unknown"; attempts?: SandboxPodAttempt[]; createdBy?: string | null;`
- `export type SandboxPodAttempt = { stage: "start" | "create"; ok: boolean; at: string; podId?: string; gpuTypeId?: string; error?: string; skipped?: string }`
- `export class ApiError extends Error { status: number; detail: unknown }` — `requestJson`이 throw. `detail`이 객체면 `message` 필드를 `Error.message`로 쓰고 객체는 `detail`에 보존. 기존 `error instanceof Error` 호출부는 호환.
- `export type SandboxPodStartFailure = { message: string; attempts: SandboxPodAttempt[]; retryAfterSeconds?: number }`

- [ ] **Step 1: 컨트랙트 테스트 작성**

```python
from pathlib import Path

SCREEN = Path("frontend/src/screens/adminScreens.tsx").read_text(encoding="utf-8")
CLIENT = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")


def _sandbox_section(source: str) -> str:
    return source.split('activeItem="adminSandbox"', 1)[1].split("</AppShell>", 1)[0]


def test_client_exposes_attempts_and_api_error_detail():
    assert "gpuTier?: \"primary\" | \"fallback\" | \"unknown\"" in CLIENT
    assert "export type SandboxPodAttempt" in CLIENT
    assert "export class ApiError extends Error" in CLIENT


def test_sandbox_panel_keeps_last_known_status_on_start_failure():
    assert "lastKnownStatus" in SCREEN or "setSandboxPod(response)" in SCREEN
    control = SCREEN.split("async function controlSandboxPod", 1)[1].split("useEffect", 1)[0]
    assert "setSandboxPod(null)" not in control
    assert "setStartFailure(" in control


def test_sandbox_panel_renders_attempts_and_fallback_badge():
    section = _sandbox_section(SCREEN)
    assert "attempts" in section and "v3-sandbox-attempt" in section
    assert 'gpuTier === "fallback"' in section
    assert "1순위 GPU로 재생성" in section
    assert "retryAfterSeconds" in SCREEN
```

- [ ] **Step 2: 실패 확인**

```bash
python3.12 -m pytest backend/tests/test_frontend_sandbox_pod_contract.py -q
```

- [ ] **Step 3: `client.ts` 변경**

`requestJson:1103-1114`:

```ts
  if (!response.ok) {
    let message = friendlyApiErrorMessage(rawMessage, response, path);
    let detail: unknown = undefined;
    try {
      const parsed = JSON.parse(rawMessage) as { detail?: unknown; message?: unknown; error?: unknown };
      detail = parsed.detail ?? parsed.message ?? parsed.error;
      if (typeof detail === "string" && detail.trim()) {
        message = detail.trim();
      } else if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
        message = (detail as { message: string }).message;
      }
    } catch { /* keep friendly message */ }
    throw new ApiError(message, response.status, detail);
  }
```

`ApiError` 클래스를 `requestJson` 위에 정의·export. 타입 추가는 `:187` 블록.

- [ ] **Step 4: `adminScreens.tsx` 변경**

상태 추가(`:476` 뒤):

```tsx
  const [startFailure, setStartFailure] = useState<SandboxPodStartFailure | null>(null);
  const [retryAfterUntil, setRetryAfterUntil] = useState<number | null>(null);
  const [retryCountdown, setRetryCountdown] = useState(0);
```

`controlSandboxPod:492-504`:

```tsx
  async function controlSandboxPod(action: "start" | "stop") {
    setSandboxPodLoading(true);
    setNotice("");
    setStartFailure(null);
    try {
      const response = action === "start" ? await apiClient.startSandboxPod() : await apiClient.stopSandboxPod();
      setSandboxPod(response);            // 성공 응답에서만 갱신 → httpServices 잔존 방지
      setNotice(response.message || ...);
    } catch (error) {
      // 이전 sandboxPod 상태는 그대로 유지한다(카드 공백 방지)
      const detail = error instanceof ApiError && error.detail && typeof error.detail === "object" ? (error.detail as SandboxPodStartFailure) : null;
      if (action === "start" && detail?.attempts) {
        setStartFailure(detail);
        if (detail.retryAfterSeconds) setRetryAfterUntil(Date.now() + detail.retryAfterSeconds * 1000);
      }
      setNotice(error instanceof Error ? error.message : "Sandbox Pod control failed");
    } finally {
      setSandboxPodLoading(false);
    }
  }
```

카운트다운 `useEffect`: `retryAfterUntil`이 있으면 1초 interval로 `retryCountdown` 갱신, 0이 되면 `setRetryAfterUntil(null)`.

`loadSandboxPod`(Refresh)은 성공 시 `setStartFailure(null)`도 수행.

렌더:
- Start 버튼(`:525`) `disabled`에 `|| retryCountdown > 0` 추가, 라벨에 `retryCountdown > 0 ? \`Deploy Sandbox Pod (${retryCountdown}s)\` : "Deploy Sandbox Pod"`.
- 배너: 헤더 아래에 `startFailure || sandboxPod?.attempts?.length` 이면 `<div className="v3-sandbox-attempts">` 로 각 attempt를 `<span className={\`v3-sandbox-attempt ${a.ok ? "is-ok" : "is-fail"}\`}>` 로 렌더. 포맷: `formatAttempt(a)` = `${a.stage} ${a.stage === "start" ? shortId(a.podId) : shortGpu(a.gpuTypeId)} ${a.ok ? "✓" : "✗"} ${a.ok ? shortId(a.podId) : (a.skipped === "vram" ? "VRAM 부족" : shortReason(a.error))}` 를 ` → ` 로 연결. `shortGpu("NVIDIA GeForce RTX 4090") === "4090"`, `shortId("s2lqjdfpdoyqa0") === "s2lq…"`, `shortReason`은 `no instances` 포함 시 `재고 없음`.
- 상태 카드 GPU 행(`:600`, configuration 모드 및 live 모드 양쪽)에 `sandboxPod.gpuTier === "fallback" ? <span className="v3-status-badge is-warning">fallback</span> : null`.
- fallback이고 `canControl`이면 헤더 액션에 `<button className="v3-secondary-button" onClick={() => setSandboxPodPendingAction("recreate")}>1순위 GPU로 재생성</button>`. `sandboxPodPendingAction` 타입에 `"recreate"` 추가; 실행은 `await apiClient.stopSandboxPod(); await apiClient.startSandboxPod();` 순차 호출(기존 확인 모달 재사용, 문구 "현재 파드를 중지하고 1순위 GPU로 새로 생성합니다").
- HTTP Services 카드는 `sandboxPod.httpServices`만 사용(현행 유지, 실패 시 `sandboxPod`를 안 바꾸므로 자동 충족).

CSS: `v3-sandbox-attempts`, `v3-sandbox-attempt.is-ok/.is-fail`, `is-warning` 배지가 없으면 기존 스타일시트(`frontend/src/**/*.css`에서 `v3-sandbox-service-list` 정의 위치)에 추가.

- [ ] **Step 5: 빌드 + 컨트랙트 테스트 통과 후 커밋**

```bash
npm run build
python3.12 -m pytest backend/tests/test_frontend_sandbox_pod_contract.py -q
git add frontend/src/api/client.ts frontend/src/screens/adminScreens.tsx frontend/src/**/*.css backend/tests/test_frontend_sandbox_pod_contract.py
git commit -m "feat(sandbox): keep last status on start failure, show attempts and fallback badge"
```

---

### Task 7: 운영가이드 갱신 (스펙 §8-3)

**Files:**
- Modify: `runpod mcp/운영가이드-RunPod-ComfyUI-Wan.md` (Sandbox Pod 절 끝)

- [ ] **Step 1: 절 추가**

"Start 실패 시 자동 fallback" 절: 동작 순서(start→create→fallback), 화면에서 `attempts` 배너 읽는 법, `fallback` 배지 의미, "1순위 GPU로 재생성" 버튼, 503 카운트다운 후 재시도, 관련 환경변수 4개와 롤아웃 순서(빈 값 배포 → §6 검증 → 설정), CloudWatch 메트릭 이름 2개.

- [ ] **Step 2: 커밋**

```bash
git add "runpod mcp/운영가이드-RunPod-ComfyUI-Wan.md"
git commit -m "docs(sandbox): operator guide for GPU fallback"
```

---

### Task 8: 통합 검증

- [ ] **Step 1: 전체 테스트·빌드**

```bash
python3.12 -m pytest backend/tests/test_sandbox_pod_service.py backend/tests/test_sandbox_pod_api.py backend/tests/test_frontend_sandbox_pod_contract.py -q
python3.12 -m pytest backend/tests -q   # 회귀
npm run build
```

- [ ] **Step 2: 불변식 수동 점검**

- `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS` 미설정 + EXITED 파드: start 1+retry회 → create(5090) 1회 → 실패면 503. create 본문이 기존과 동일(`gpuTypeIds:[5090]`, `dataCenterIds` 없음).
- 로컬 dev(`docker-compose.dev.yml`)에서 관리자 페이지 Start 실패 응답을 mock으로 재현해 카드가 비지 않는지, 배너·카운트다운이 나오는지 확인.

- [ ] **Step 3: 스펙 문서에 구현 메모 추기**

`docs/superpowers/specs/2026-09-11-sandbox-pod-gpu-fallback-design.md` §9 아래에 "구현 메모(feat/enhance)": GET `attempts`는 `[]` 고정으로 결정한 이유, Vitest 대신 컨트랙트 테스트 사용, `/gpus` 실제 필드명. 커밋.

---

### Task 9: §6 Fallback 후보 검증 (운영, 코드 배포와 분리)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-11-sandbox-pod-gpu-fallback-design.md` §6 표에 결과 추기

코드 머지 후, `FALLBACK_TYPE_IDS`를 운영 환경에 설정하기 **전에** EU-RO-1에서 1회 수행한다. Runpod MCP(`list-gpu-types`, `get-capacity`, `create-pod`)로 진행 가능.

- [ ] **Step 1: DC 재고** — `get-capacity`/`list-gpu-types`로 EU-RO-1 RTX 4090·L40S secure cloud 재고 확인. 없으면 후보에서 제외.
- [ ] **Step 2: CUDA 호환** — 템플릿 `nh1d177m2w`(`runpod/comfyui:cuda13.0`)로 4090 파드 1회 생성(`create-pod`, 볼륨 `18jhx6rxjd`, 요금 사전 고지). 기동 실패 시 `cuda12.8` 템플릿을 `RUNPOD_SANDBOX_FALLBACK_TEMPLATE_ID`로 분리하는 후속 Task를 연다(현 계획 범위 밖).
- [ ] **Step 3: SageAttention** — 4090 파드에서 `/workspace/runpod-slim/comfyui_args.txt`의 `--use-sage-attention` 유지 시 ComfyUI 기동 로그(`stream-pod-logs`) 확인. import 실패 시 기동 스크립트에 `nvidia-smi --query-gpu=compute_cap` 분기 추가(볼륨 내 스크립트 수정, 코드 저장소 밖).
- [ ] **Step 4: VRAM** — 현재 워크플로 1건 실행해 24 GB OOM 여부 확인. OOM이면 `RUNPOD_SANDBOX_MIN_VRAM_GB=48`.
- [ ] **Step 5: 검증 파드 삭제**(`delete-pod`), 결과를 §6 표에 기록, 운영 환경변수 설정.

---

## 커밋 순서 요약

1. `feat(sandbox): add GPU fallback settings`
2. `feat(sandbox): classify RunPod errors and select GPU candidates`
3. `feat(sandbox): staged start→create→GPU fallback with attempts`
4. `feat(sandbox): 503 with attempts and start_failed audit`
5. `feat(sandbox): attempt logs and EMF metrics`
6. `feat(sandbox): keep last status on start failure, show attempts and fallback badge`
7. `docs(sandbox): operator guide for GPU fallback`
8. `docs(sandbox): implementation notes`

1~5까지는 `FALLBACK_TYPE_IDS` 빈 값이면 동작 변화가 없으므로 먼저 배포 가능(롤아웃 1단계).
