# 배치 Grok 프롬프트 · RunPod 요청 관리 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 이미지를 여러 장 업로드해 이미지별 Grok 프롬프트를 생성·검수·편집하고, 선택한 쌍을 RunPod에 등록하면 브라우저를 닫아도 서버가 한 건씩 순차 제출하도록 만든다.

**Architecture:** Generate 영역에 두 화면(Prompt Generation Management, RunPod Request Management)을 추가한다. `image_prompt_drafts`가 이미지 단위 프롬프트 쌍 레코드로 남고, 배치/시도 테이블이 진행률과 감사 기록을 담당하며, `workflow_tasks`는 그대로 RunPod 작업 상태의 유일한 출처다. DB 조건부 UPDATE로 클레임하는 디스패처가 정책과 엔드포인트 여유가 허용될 때만 한 건씩 제출한다.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, MySQL·SQLite 양립 마이그레이션, React/TypeScript, 기존 v4 CSS 토큰, Grok Responses API 클라이언트, RunPod Serverless REST API, pytest.

**선행 문서:** `docs/superpowers/plans/2026-09-01-batch-grok-runpod-management.md`(원안), `docs/superpowers/specs/2026-08-31-grok-vision-first-priority-plan.md`(스펙), `docs/superpowers/specs/2026-08-31-grok-instruction-admin-mockup.html`.

**이 문서가 원안을 대체하는 이유:** 원안은 코드베이스와 대조했을 때 (1) 존재하지 않는 pytest를 전제했고, (2) `workflow_tasks.status`의 기존 소비자 4곳과 충돌하는 새 저장 어휘를 도입했고, (3) 실행 경로의 실제 소유자(`studio_api_service.py`)와 화면 렌더 지점(`StudioShell.tsx`, `AppShell.tsx`)을 파일 맵에서 빠뜨렸고, (4) `prepare_workflow_for_job`이 받는 payload 계약과 다른 구조를 지정했다. 이 문서는 같은 목표를 확정된 세 가지 결정에 맞춰 다시 분해한 것이다. 원안은 참고용으로 남기고 실행은 이 문서를 따른다.

## 구현 현황 (2026-09-01)

| 구현 단계 | 상태 | 검증 근거 |
| --- | --- | --- |
| DB 계약 | 완료 | 마이그레이션 `20260901_0026_batch_prompt_runpod_queue.py`와 배치/초안/시도/큐 모델 테스트 |
| Grok 배치 | 완료 | 이미지별 성공·실패 격리, 재시도, 지시문 필수 검증, 사용량·지연 메타데이터 테스트 |
| RunPod 큐 | 완료 | 유휴 워커 검사, 순차 제출, 로컬 대기열, 정책 집계, 실제 `/run` 호출 테스트 |
| 화면 계약 | 완료 | 프롬프트 생성 관리, RunPod 요청 관리, 전용 이력 API 사용 소스 계약 및 TypeScript/Vite 빌드 |
| 이력 계약 | 완료 | `/api/history/prompts`, `/api/history/runpod`의 20건 고정 페이지·Grok/RunPod 응답 메타데이터 API 테스트 |
| 전체 회귀 | 완료 | `python3 -m pytest backend/tests -q` 56 passed, `npm --prefix frontend run build` 통과 |

이번 단계에서는 기존 마이그레이션 0026을 사용했으며 새 DB 마이그레이션은 추가하지 않았다. Git 동기화와 ECS 배포도 수행하지 않는다.

## 확정된 결정 (2026-09-01)

1. **로컬·테스트에서도 실제 RunPod 호출을 유지한다.** 디스패처에 dry-run 시뮬레이션 분기를 만들지 않는다. 단위 테스트는 `JobRuntime.runpod_request` 콜러블을 가짜로 주입해 네트워크를 타지 않는다.
2. **pytest를 도입한다.** 기존 `unittest.TestCase` 테스트는 pytest가 그대로 수집하므로 재작성하지 않는다.
3. **표시용 어휘는 파생 필드로 두고 저장 어휘는 유지한다.** `workflow_tasks.status`에는 기존 RunPod 원시값을 계속 저장하고, 신규 저장값은 `PENDING_SUBMIT` 하나만 추가한다. `REQUEST_WAITING` / `RUNPOD_QUEUE` / `RUNPOD_IN_PROGRESS` / `COMPLETED` / `FAILED`는 API 응답의 파생 필드로만 존재하며 DB에 절대 쓰지 않는다.

## Global Constraints

- Prompt Generation 항목 1개 = 업로드 이미지 1장. 멀티 키프레임 그룹핑은 이번 릴리스에서 명시적으로 제외한다.
- 모든 Grok 생성 요청은 선택된 활성 워크플로우와 그 워크플로우의 활성 JSON 지시문 세트를 필수로 요구한다.
- 지시문 내용은 DB가 아니라 JSON 파일이 유일한 기준이다. Markdown 임포트는 원본 문서를 선택된 워크플로우의 JSON 지시문 세트로 변환한다.
- 워크플로우 하나가 지시문 세트 하나를 소유한다. 그 세트 안에서 `CORE`와 `ROUTER`는 각각 최대 1개, `GUIDE`는 여러 개 가능하다.
- RunPod 요청은 활성 용량이 가득 차 있어도 거부하지 않고 `PENDING_SUBMIT`으로 접수한다. 디스패처가 가용성·정책 검사를 통과한 뒤에만 제출한다.
- **저장 상태 어휘:** `workflow_tasks.status`는 기존 값(`queued`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING`, `COMPLETED`, `SUCCESS`, `FAILED`, `CANCELLED`, `TIMED_OUT`)을 그대로 유지한다. 신규 추가는 `PENDING_SUBMIT` 하나뿐이며 이 값은 RunPod가 돌려주지 않는 로컬 전용 값이다.
- **표시 상태 어휘:** `REQUEST_WAITING`, `RUNPOD_QUEUE`, `RUNPOD_IN_PROGRESS`, `COMPLETED`, `FAILED`. `runpod_display_status()` 하나만이 이 값을 만들고, API 응답의 `runpodDisplayStatus` 필드로만 노출한다.
- `PENDING_SUBMIT`과 원자적 전환 상태 `DISPATCHING`은 `task_policy_service.ACTIVE_TASK_STATUSES` 및 `task_tracking_service.ACTIVE_STATES`에 포함하지 않는다. 아직 RunPod 용량을 쓰지 않고 상태 폴링 대상도 아니기 때문이다. 실제 RunPod가 수락한 `QUEUED`·`IN_QUEUE`·`IN_PROGRESS`·`RUNNING`만 사용자별·전체 활성 Task 정책을 점유한다.
- 기존 `_history_status_label()`의 반환값과 `item["status"]` 계약은 바꾸지 않는다. 신규 필드만 추가한다.
- 사용자별·전체 활성 Task 정책 기본값은 3과 10을 유지하고 기존 Task Policy 메뉴로 관리한다.
- 각 RunPod 요청은 원본 입력 asset, 최종 편집된 positive/negative 프롬프트, 요청 프레임 수 `49`·`81`·`161`, 고정 FPS `16`, 서버 생성 seed를 보낸다. 나머지 노드 설정은 등록된 워크플로우 기본값을 유지한다.
- 노드 config 키는 `frames`와 `fps`다(`length`가 아니다). `ui_config_to_param_config()`가 인식하는 키만 패치된다.
- 이미지 width/height는 업로드된 값을 그대로 전달한다. 종횡비 정규화·16배수 스냅·범위 거부를 추가하지 않는다. 이는 `validate_segment_resolution()`의 현재 동작과 일치하며, 스펙 §6.1의 정규화·fail-closed 규정을 이번 릴리스에서 명시적으로 대체한다. 원본 해상도와 제출 해상도를 모두 기록해 추적만 가능하게 한다.
- 배포, Git push, 파괴적 데이터 마이그레이션은 이 계획에 포함하지 않는다.

---

## File and Responsibility Map

| File | Responsibility |
| --- | --- |
| `pytest.ini` | pytest 루트 설정. `pythonpath = .`로 `backend.app` 임포트를 보장한다. |
| `backend/tests/conftest.py` | 임시 SQLite DB 환경변수 고정, 공용 세션·앱 클라이언트 픽스처. |
| `backend/requirements.txt` | pytest 의존성 추가. |
| `scripts/verify.sh` | 검증 파이프라인을 pytest로 전환. |
| `backend/app/services/grok_instruction_service.py` | 워크플로우 스코프 JSON 지시문 세트 해석, 역할 카디널리티 검증, 1.0→2.0 자동 승격. |
| `backend/app/api/v1/admin.py` | 지시문 API에 `workflowId` 필수화 전달. |
| `backend/app/data/grok_instruction_set.json` | 시드 세트를 2.0 스키마로 갱신. |
| `scripts/convert_grok_instruction_markdown.py` | `--workflow-id` 옵션으로 GUIDE 문서를 해당 워크플로우 세트에 기록. |
| `backend/app/db/models.py` | 배치·시도 모델과 디스패치 메타데이터 컬럼 추가. |
| `backend/app/db/migrations/versions/20260901_0026_batch_prompt_runpod_queue.py` | 추가 전용 마이그레이션과 인덱스. |
| `backend/app/services/task_tracking_service.py` | `runpod_display_status()` 파생 계층, 이력 DTO, 큐 카운트. |
| `backend/app/services/prompt_batch_service.py` | 프롬프트 배치·드래프트 수명주기·재시도·이력 DTO. |
| `backend/app/services/grok_image_prompt_service.py` | 응답 usage/지연 텔레메트리 반환. |
| `backend/app/services/runpod_dispatch_service.py` | 대기 작업 클레임, 한도 검사, 직렬 제출, 재시작 복구. |
| `backend/app/services/studio_api_service.py` | 디스패처가 쓰는 런타임 조립·자산 해석 재사용 지점. 인메모리 `JOBS`의 단일 소유자로 유지. |
| `backend/app/api/v1/prompts.py` | 배치·드래프트 편집·재시도 API. |
| `backend/app/api/v1/jobs.py` | 큐 등록·큐 요약 API. 기존 단건 API 유지. |
| `backend/app/api/v1/history.py` | 프롬프트/RunPod 이력 탭 엔드포인트. |
| `backend/app/main.py` | 기존 모니터 루프 안에서 디스패처 1회 호출. |
| `frontend/src/router.ts` | 신규 라우트 키와 경로 등록. |
| `frontend/src/components/AppShell.tsx` | 사이드바 Generate 메뉴 항목 교체. |
| `frontend/src/StudioShell.tsx` | 신규 라우트의 실제 렌더 분기. |
| `frontend/src/helpers/navigation.ts` | 메뉴 key → 라우트 매핑. |
| `frontend/src/api/client.ts` | 배치·드래프트·큐·이력 타입드 클라이언트. |
| `frontend/src/screens/promptBatchScreen.tsx` | Prompt Generation Management 화면(신규 파일). |
| `frontend/src/screens/runpodRequestScreen.tsx` | RunPod Request Management 화면(신규 파일). |
| `frontend/src/screens/reviewScreens.tsx` | Prompt History / RunPod History 탭. |
| `frontend/src/screens/adminScreens.tsx` | 좌측 워크플로우 선택과 JSON 지시문 세트 연결. |
| `frontend/src/styles.css` | 토큰 정합 테이블·진행률·상태·이미지 카드 스타일만 추가. |
| `README.md`, `docs/dobedub-studio-user-manual.md`, `.env.example` | 운영 문서와 실행 전제 갱신. |

**변경 범위 메모:** `backend/app/services/task_policy_service.py`는 대기열 정책 정합성을 위해 변경했다. `PENDING_SUBMIT`과 `DISPATCHING`을 활성 실행 집계에서 제외하며, `backend/app/repositories/db_adapter.py`는 변경하지 않는다.

**신규 화면을 `createScreens.tsx`(1541줄)에 넣지 않는 이유:** 두 화면이 각각 수백 줄이고 서로 독립적이다. 파일을 나누면 Task 6과 Task 7이 서로의 diff를 건드리지 않는다.

---

## Task 0: pytest 기반 검증 파이프라인 도입

**Files:**
- Create: `pytest.ini`
- Create: `backend/tests/conftest.py`
- Modify: `backend/requirements.txt`
- Modify: `scripts/verify.sh`

**Interfaces:**
- Produces: `db_session` 픽스처(`sqlalchemy.orm.Session`), `api_client` 픽스처(`fastapi.testclient.TestClient`), `fake_runpod` 픽스처(`list[tuple[str, str, dict | None]]` 호출 기록을 가진 콜러블).
- Consumes: 없음.

- [ ] **Step 1: pytest를 설치하고 의존성에 기록한다**

```bash
python3 -m pip install "pytest>=8.0"
```

`backend/requirements.txt` 끝에 다음 줄을 추가한다.

```text
pytest>=8.0
```

- [ ] **Step 2: pytest 루트 설정을 만든다**

`backend/tests`에는 `__init__.py`가 없다. pytest는 기본적으로 테스트 파일이 있는 디렉터리를 `sys.path`에 넣으므로 `import backend.app...`이 실패한다. `pythonpath`로 저장소 루트를 고정한다.

`pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = backend/tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 3: 기존 unittest 테스트가 그대로 수집되는지 확인한다**

Run: `python3 -m pytest backend/tests -q`

Expected: 기존 8개 파일이 수집되어 PASS. 실패가 있으면 그것은 이 계획 이전부터 있던 문제이므로 기록만 하고 넘어가지 말 것 — 먼저 원인을 확인한 뒤 진행한다.

- [ ] **Step 4: 공용 픽스처를 작성한다**

`backend/app/db/session.py`의 `engine`과 `SessionLocal`은 모듈 임포트 시점에 `get_settings().database_url`로 바인딩된다. 따라서 conftest는 backend를 임포트하기 **전에** 환경변수를 세팅해야 한다. `get_settings()`는 캐시되지 않으므로 이후 호출은 항상 최신 환경변수를 읽는다.

`backend/tests/conftest.py`:

```python
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# backend 패키지를 임포트하기 전에 실행 환경을 고정한다. session.py의 engine은
# 모듈 로드 시점에 DATABASE_URL로 바인딩되므로 순서를 바꾸면 안 된다.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="dobedub-tests-"))
os.environ.setdefault("STUDIO_DATA_DIR", str(_TEST_ROOT / "data"))
(_TEST_ROOT / "data").mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'test.db'}"

from backend.app.db.base import Base  # noqa: E402
from backend.app.db.session import SessionLocal, engine  # noqa: E402


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    Base.metadata.create_all(bind=engine)
    with TestClient(create_app()) as client:
        yield client
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def fake_runpod():
    """RunPod HTTP 호출을 대신하는 콜러블.

    결정 1에 따라 프로덕션 코드에는 dry-run 분기를 두지 않는다. 테스트는
    JobRuntime.runpod_request 자리에 이 콜러블을 주입해 네트워크를 차단한다.
    """

    class _FakeRunpod:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []
            self.submit_response: dict = {"id": "runpod_job_test_1"}
            self.status_response: dict = {"status": "IN_QUEUE"}

        def __call__(self, method: str, path: str, payload=None):
            self.calls.append((method, path, payload))
            if path == "/run":
                return dict(self.submit_response)
            if path.startswith("/status/"):
                return dict(self.status_response)
            if path == "/health":
                return {"workers": {"idle": 1, "ready": 1}}
            raise AssertionError(f"unexpected RunPod path: {path}")

    return _FakeRunpod()
```

- [ ] **Step 5: 픽스처 동작을 검증하는 테스트를 작성한다**

`backend/tests/test_pytest_harness.py`:

```python
from __future__ import annotations

from backend.app.db.models import WorkflowTask


def test_db_session_fixture_creates_schema(db_session):
    task = WorkflowTask(id="task_fixture_1", workflow_id="1-images.json", status="COMPLETED")
    db_session.add(task)
    db_session.commit()
    assert db_session.get(WorkflowTask, "task_fixture_1").workflow_id == "1-images.json"


def test_fake_runpod_records_calls(fake_runpod):
    assert fake_runpod("POST", "/run", {"input": {}}) == {"id": "runpod_job_test_1"}
    assert fake_runpod.calls == [("POST", "/run", {"input": {}})]
```

- [ ] **Step 6: 테스트를 실행해 통과를 확인한다**

Run: `python3 -m pytest backend/tests/test_pytest_harness.py -q`

Expected: 2 passed.

- [ ] **Step 7: verify.sh를 pytest로 전환한다**

`scripts/verify.sh`의 2단계를 교체한다.

```bash
echo "[2/4] Run backend tests"
python3 -m pytest backend/tests -q
```

Run: `bash scripts/verify.sh`

Expected: 4단계 모두 통과 후 `Verification completed.`

- [ ] **Step 8: 커밋한다**

```bash
git add pytest.ini backend/tests/conftest.py backend/tests/test_pytest_harness.py backend/requirements.txt scripts/verify.sh
git commit -m "test: adopt pytest as the backend verification runner"
```

---

## Task 1: 워크플로우 스코프 JSON 지시문 계약

**Files:**
- Modify: `backend/app/services/grok_instruction_service.py`
- Modify: `backend/app/api/v1/admin.py:36-75`
- Modify: `backend/app/api/v1/prompts.py:416`
- Modify: `backend/app/data/grok_instruction_set.json`
- Modify: `scripts/convert_grok_instruction_markdown.py`
- Create: `backend/tests/test_grok_instruction_service.py`

**Interfaces:**
- Consumes: Task 0의 `db_session`은 쓰지 않는다(이 서비스는 파일 기반).
- Produces:
  - `resolve_workflow_instruction_set(workflow_id: str) -> dict[str, Any]` — 키 `workflowId`, `version`, `documents`, `compiledMarkdown`.
  - `validate_instruction_set(payload: dict[str, Any]) -> None` — 위반 시 `ValueError`.
  - `list_instruction_documents(workflow_id: str) -> dict[str, Any]`
  - `save_instruction_document(payload: dict[str, Any], *, document_id: str | None) -> dict[str, Any]` — `payload["workflowId"]` 필수.
  - `active_instruction_text(workflow_id: str) -> tuple[str, str]` — (지시문 본문, 버전 문자열).

- [ ] **Step 1: 실패하는 계약 테스트를 작성한다**

`backend/tests/test_grok_instruction_service.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.services import grok_instruction_service as svc


def _write_set(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_resolve_workflow_instruction_set_returns_only_selected_workflow(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {
        "schemaVersion": "2.0",
        "workflowInstructionSets": [
            {
                "workflowId": "1-images.json",
                "version": 1,
                "documents": [
                    {"id": "core", "role": "CORE", "isActive": True, "contentMarkdown": "핵심 규칙"},
                    {"id": "router", "role": "ROUTER", "isActive": True, "contentMarkdown": "분기 규칙"},
                ],
            },
            {
                "workflowId": "3-images.json",
                "version": 1,
                "documents": [
                    {"id": "core3", "role": "CORE", "isActive": True, "contentMarkdown": "다른 워크플로우"},
                ],
            },
        ],
    })
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    result = svc.resolve_workflow_instruction_set("1-images.json")

    assert result["workflowId"] == "1-images.json"
    assert "[CORE]" in result["compiledMarkdown"]
    assert "핵심 규칙" in result["compiledMarkdown"]
    assert "다른 워크플로우" not in result["compiledMarkdown"]


def test_resolve_unknown_workflow_raises(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {"schemaVersion": "2.0", "workflowInstructionSets": []})
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    with pytest.raises(ValueError, match="활성 프롬프트 지시문이 없습니다"):
        svc.resolve_workflow_instruction_set("1-images.json")


def test_duplicate_core_is_rejected():
    with pytest.raises(ValueError, match="CORE 역할은 워크플로우당 1개만"):
        svc.validate_instruction_set({
            "workflowId": "1-images.json",
            "documents": [{"role": "CORE"}, {"role": "CORE"}],
        })


def test_multiple_guides_are_allowed():
    svc.validate_instruction_set({
        "workflowId": "1-images.json",
        "documents": [{"role": "CORE"}, {"role": "GUIDE"}, {"role": "GUIDE"}],
    })


def test_legacy_v1_file_is_promoted_to_default_workflow(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {
        "schemaVersion": "1.0",
        "code": "grok_wan_i2v_transformer",
        "version": 7,
        "documents": [
            {"id": "legacy-core", "role": "CORE", "isActive": True, "contentMarkdown": "기존 관리자 편집본"},
        ],
    })
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    result = svc.resolve_workflow_instruction_set(svc.LEGACY_DEFAULT_WORKFLOW_ID)

    assert result["version"] == 7
    assert "기존 관리자 편집본" in result["compiledMarkdown"]
    promoted = json.loads(target.read_text(encoding="utf-8"))
    assert promoted["schemaVersion"] == "2.0"
    assert promoted["workflowInstructionSets"][0]["workflowId"] == svc.LEGACY_DEFAULT_WORKFLOW_ID


def test_save_requires_workflow_id(tmp_path, monkeypatch):
    target = tmp_path / "grok_instruction_set.json"
    _write_set(target, {"schemaVersion": "2.0", "workflowInstructionSets": []})
    monkeypatch.setattr(svc, "_runtime_path", lambda: target)

    with pytest.raises(ValueError, match="워크플로우를 먼저 선택"):
        svc.save_instruction_document({"role": "GUIDE", "contentMarkdown": "x"}, document_id=None)
```

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_grok_instruction_service.py -q`

Expected: `AttributeError: module ... has no attribute 'resolve_workflow_instruction_set'` 등으로 FAIL.

- [ ] **Step 3: 2.0 스키마와 승격 경로를 구현한다**

런타임 파일은 관리자가 이미 편집했을 수 있다. 1.0 파일을 만나면 데이터를 버리지 않고 기존 문서 전체를 기본 워크플로우 세트로 옮겨 담은 뒤 2.0으로 저장한다.

```python
_SCHEMA_VERSION = "2.0"
LEGACY_DEFAULT_WORKFLOW_ID = "1-images.json"
_VALID_ROLES = {"CORE", "ROUTER", "GUIDE"}
_SINGLETON_ROLES = ("CORE", "ROUTER")


def validate_instruction_set(payload: dict[str, Any]) -> None:
    documents = payload.get("documents") or []
    for document in documents:
        role = _normalize_role(document.get("role"))
        if role not in _VALID_ROLES:
            raise ValueError(f"허용되지 않는 역할입니다: {document.get('role')}")
    for role in _SINGLETON_ROLES:
        count = sum(1 for document in documents if _normalize_role(document.get("role")) == role)
        if count > 1:
            raise ValueError(f"{role} 역할은 워크플로우당 1개만 등록할 수 있습니다.")


def _promote_legacy_set(document_set: dict[str, Any]) -> dict[str, Any]:
    """1.0 단일 세트를 2.0 워크플로우 배열로 승격한다. 문서는 그대로 보존한다."""
    return {
        "schemaVersion": _SCHEMA_VERSION,
        "workflowInstructionSets": [
            {
                "workflowId": LEGACY_DEFAULT_WORKFLOW_ID,
                "version": _safe_int(document_set.get("version"), 1),
                "documents": list(document_set.get("documents") or []),
            }
        ],
    }


def _load_set() -> dict[str, Any]:
    document_set = _read_set(_runtime_path())
    if str(document_set.get("schemaVersion") or "") != _SCHEMA_VERSION:
        document_set = _promote_legacy_set(document_set)
        _write_set(document_set, _runtime_path())
    return document_set


def _find_set(document_set: dict[str, Any], workflow_id: str) -> dict[str, Any] | None:
    for item in document_set.get("workflowInstructionSets") or []:
        if str(item.get("workflowId") or "") == workflow_id:
            return item
    return None


def resolve_workflow_instruction_set(workflow_id: str) -> dict[str, Any]:
    workflow_id = str(workflow_id or "").strip()
    if not workflow_id:
        raise ValueError("워크플로우를 먼저 선택하세요.")
    entry = _find_set(_load_set(), workflow_id)
    documents = [item for item in (entry or {}).get("documents") or [] if item.get("isActive")]
    if not documents:
        raise ValueError("선택한 워크플로우에 활성 프롬프트 지시문이 없습니다.")
    validate_instruction_set({"workflowId": workflow_id, "documents": documents})
    ordered = sorted(documents, key=lambda item: (_ROLE_ORDER.get(_normalize_role(item.get("role")), 9), _safe_int(item.get("sortOrder"), 0)))
    compiled = "\n\n".join(
        f"[{_normalize_role(item.get('role'))}] {item.get('title') or ''}\n{item.get('contentMarkdown') or ''}".strip()
        for item in ordered
    )
    return {
        "workflowId": workflow_id,
        "version": _safe_int(entry.get("version"), 1),
        "documents": ordered,
        "compiledMarkdown": compiled,
    }


_ROLE_ORDER = {"CORE": 0, "ROUTER": 1, "GUIDE": 2}


def active_instruction_text(workflow_id: str) -> tuple[str, str]:
    resolved = resolve_workflow_instruction_set(workflow_id)
    return resolved["compiledMarkdown"], f"{resolved['workflowId']}@{resolved['version']}"
```

`save_instruction_document`은 `payload["workflowId"]`가 비면 `ValueError("워크플로우를 먼저 선택하세요.")`를 던지고, 같은 워크플로우에 두 번째 세트를 만들지 않고 기존 세트를 갱신한다. 저장 직전 `validate_instruction_set`을 호출해 역할 카디널리티를 강제한다. `list_instruction_documents(workflow_id)`도 같은 방식으로 워크플로우를 필수 인자로 받는다.

- [ ] **Step 4: 호출부 세 곳을 새 시그니처에 맞춘다**

`backend/app/api/v1/admin.py`에서 `GET /admin/grok-instructions`는 쿼리 파라미터 `workflowId`를 필수로 받고, POST/PUT/import는 `payload["workflowId"]`를 그대로 서비스에 넘긴다. 워크플로우 미선택이나 역할 위반은 `ValueError`를 잡아 `400`으로 변환한다.

```python
@router.get("/grok-instructions")
def grok_instructions(workflowId: str = "", _: CurrentUser = Depends(require_permission("prompt-catalog:read"))):
    try:
        return list_instruction_documents(workflowId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Grok instruction load failed: {exc}") from exc
```

`backend/app/api/v1/prompts.py:416`의 호출을 워크플로우 스코프로 바꾼다.

```python
try:
    instruction_text, instruction_version = active_instruction_text(workflow_id)
except ValueError as exc:
    raise HTTPException(status_code=409, detail=str(exc)) from exc
```

`scripts/convert_grok_instruction_markdown.py`는 `--workflow-id` 인자를 필수로 받아 해당 워크플로우 세트 안에 `GUIDE` 문서를 생성하거나 같은 `id`가 있으면 교체한다.

- [ ] **Step 5: 시드 JSON을 2.0으로 갱신한다**

`backend/app/data/grok_instruction_set.json`:

```json
{
  "schemaVersion": "2.0",
  "workflowInstructionSets": [
    {
      "workflowId": "1-images.json",
      "version": 1,
      "documents": [
        {"id": "core", "role": "CORE", "title": "핵심 규칙", "sortOrder": 0, "isActive": true, "contentMarkdown": "..."},
        {"id": "router", "role": "ROUTER", "title": "유형 분기", "sortOrder": 1, "isActive": true, "contentMarkdown": "..."}
      ]
    }
  ]
}
```

기존 시드의 `contentMarkdown` 본문은 그대로 옮긴다. 내용을 새로 쓰지 않는다.

- [ ] **Step 6: 테스트를 실행해 통과를 확인한다**

Run: `python3 -m pytest backend/tests/test_grok_instruction_service.py backend/tests/test_admin_workflow_id.py -q`

Expected: PASS.

- [ ] **Step 7: 커밋한다**

```bash
git add backend/app/services/grok_instruction_service.py backend/app/api/v1/admin.py backend/app/api/v1/prompts.py backend/app/data/grok_instruction_set.json scripts/convert_grok_instruction_markdown.py backend/tests/test_grok_instruction_service.py
git commit -m "feat: scope Grok instruction sets by workflow"
```

---

## Task 2: 추가 전용 배치·시도·큐 스키마

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/db/migrations/versions/20260901_0026_batch_prompt_runpod_queue.py`
- Create: `backend/tests/test_batch_queue_models.py`

**Interfaces:**
- Consumes: Task 0의 `db_session` 픽스처.
- Produces:
  - ORM 모델 `PromptGenerationBatch`, `PromptGenerationAttempt`, `RunpodRequestBatch`.
  - `ImagePromptDraft.prompt_batch_id`, `.negative_prompt`, `.requested_frames` (모두 nullable).
  - `WorkflowTask.prompt_draft_id`, `.request_batch_id`, `.dispatch_claimed_at`, `.dispatch_attempts`, `.next_dispatch_at`, `.last_dispatch_error`.
  - 인덱스 `ix_workflow_tasks_dispatch` on `(status, next_dispatch_at, created_at)`.

- [ ] **Step 1: 실패하는 모델 테스트를 작성한다**

`backend/tests/test_batch_queue_models.py`:

```python
from __future__ import annotations

from backend.app.db.models import (
    ImagePromptDraft,
    PromptGenerationAttempt,
    PromptGenerationBatch,
    WorkflowTask,
)


def test_prompt_draft_records_batch_negative_prompt_and_frames(db_session):
    batch = PromptGenerationBatch(id="pgb_1", workflow_id="1-images.json", status="WAITING", created_by=None)
    draft = ImagePromptDraft(
        id="prm_1",
        asset_id=None,
        workflow_id="1-images.json",
        slot_index=1,
        status="GENERATING",
        provider="grok",
        model="grok-test",
        instruction_version="1-images.json@1",
        warnings_json=[],
        raw_json={},
        prompt_batch_id="pgb_1",
        negative_prompt="low quality",
        requested_frames=81,
    )
    db_session.add_all([batch, draft])
    db_session.commit()

    stored = db_session.get(ImagePromptDraft, "prm_1")
    assert stored.requested_frames == 81
    assert stored.negative_prompt == "low quality"
    assert stored.prompt_batch_id == "pgb_1"


def test_attempt_records_grok_telemetry(db_session):
    attempt = PromptGenerationAttempt(
        id="pga_1",
        draft_id="prm_1",
        attempt_no=1,
        status="COMPLETED",
        endpoint="https://api.x.ai/v1/responses",
        model="grok-test",
        latency_ms=1234,
        input_tokens=120,
        output_tokens=45,
        response_json={"ok": True},
    )
    db_session.add(attempt)
    db_session.commit()
    assert db_session.get(PromptGenerationAttempt, "pga_1").input_tokens == 120


def test_task_dispatch_columns_and_index_exist(db_session):
    task = WorkflowTask(
        id="task_dispatch_1",
        workflow_id="1-images.json",
        status="PENDING_SUBMIT",
        prompt_draft_id="prm_1",
        dispatch_attempts=0,
    )
    db_session.add(task)
    db_session.commit()

    stored = db_session.get(WorkflowTask, "task_dispatch_1")
    assert stored.dispatch_claimed_at is None
    assert stored.next_dispatch_at is None
    assert stored.last_dispatch_error is None
    assert "ix_workflow_tasks_dispatch" in {index.name for index in WorkflowTask.__table__.indexes}
```

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_batch_queue_models.py -q`

Expected: `ImportError`(신규 모델 없음) 또는 `TypeError`(신규 컬럼 없음)로 FAIL.

- [ ] **Step 3: ORM 모델과 컬럼을 추가한다**

`backend/app/db/models.py`의 `WorkflowTask.__table_args__`에 인덱스를 추가한다.

```python
    __table_args__ = (
        Index("ix_workflow_tasks_created_at_id", "created_at", "id"),
        # 디스패처가 PENDING_SUBMIT 대기열을 backoff 시각 순으로 스캔한다.
        Index("ix_workflow_tasks_dispatch", "status", "next_dispatch_at", "created_at"),
    )
```

`WorkflowTask`에 다음 컬럼을 추가한다.

```python
    prompt_draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    request_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 디스패처 클레임 메타데이터. dispatch_claimed_at이 NULL이 아니면 어떤 사이클이
    # 이 행을 집어간 상태이며, 제출 실패 시 NULL로 되돌리고 next_dispatch_at을 민다.
    dispatch_claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_dispatch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`ImagePromptDraft`에 추가한다.

```python
    prompt_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

신규 모델 세 개를 추가한다.

```python
class PromptGenerationBatch(Base):
    __tablename__ = "prompt_generation_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class PromptGenerationAttempt(Base):
    __tablename__ = "prompt_generation_attempts"
    __table_args__ = (
        Index("ix_prompt_generation_attempts_draft", "draft_id", "attempt_no"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(191), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class RunpodRequestBatch(Base):
    __tablename__ = "runpod_request_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(191), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
```

`PromptGenerationAttempt.draft_id`에는 FK를 걸지 않는다. 드래프트가 지워져도 Grok 호출 감사 기록은 남아야 한다.

- [ ] **Step 4: 추가 전용 마이그레이션을 작성한다**

기존 `workflow_tasks`, `task_prompts`, `assets`, `image_prompt_drafts` 데이터를 삭제·개명·재작성·백필하지 않는다. 신규 테이블, nullable 컬럼, 인덱스만 만든다.

`backend/app/db/migrations/versions/20260901_0026_batch_prompt_runpod_queue.py`:

```python
"""add durable prompt batch and RunPod dispatch queue metadata

Revision ID: 20260901_0026
Revises: 20260831_0025
Create Date: 2026-09-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260901_0026"
down_revision = "20260831_0025"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "prompt_generation_batches" not in tables:
        op.create_table(
            "prompt_generation_batches",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("workflow_id", sa.String(length=191), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_prompt_generation_batches_workflow_id", "prompt_generation_batches", ["workflow_id"])
        op.create_index("ix_prompt_generation_batches_status", "prompt_generation_batches", ["status"])

    if "prompt_generation_attempts" not in tables:
        op.create_table(
            "prompt_generation_attempts",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("draft_id", sa.String(length=64), nullable=False),
            sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("endpoint", sa.String(length=255), nullable=True),
            sa.Column("model", sa.String(length=191), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=True),
            sa.Column("output_tokens", sa.Integer(), nullable=True),
            sa.Column("response_json", sa.JSON(), nullable=False),
            sa.Column("failure_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_prompt_generation_attempts_draft", "prompt_generation_attempts", ["draft_id", "attempt_no"])

    if "runpod_request_batches" not in tables:
        op.create_table(
            "runpod_request_batches",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("workflow_id", sa.String(length=191), nullable=False),
            sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_runpod_request_batches_workflow_id", "runpod_request_batches", ["workflow_id"])

    draft_columns = _columns(inspector, "image_prompt_drafts")
    if "prompt_batch_id" not in draft_columns:
        op.add_column("image_prompt_drafts", sa.Column("prompt_batch_id", sa.String(length=64), nullable=True))
        op.create_index("ix_image_prompt_drafts_prompt_batch_id", "image_prompt_drafts", ["prompt_batch_id"])
    if "negative_prompt" not in draft_columns:
        op.add_column("image_prompt_drafts", sa.Column("negative_prompt", sa.Text(), nullable=True))
    if "requested_frames" not in draft_columns:
        op.add_column("image_prompt_drafts", sa.Column("requested_frames", sa.Integer(), nullable=True))

    task_columns = _columns(inspector, "workflow_tasks")
    if "prompt_draft_id" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("prompt_draft_id", sa.String(length=64), nullable=True))
        op.create_index("ix_workflow_tasks_prompt_draft_id", "workflow_tasks", ["prompt_draft_id"])
    if "request_batch_id" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("request_batch_id", sa.String(length=64), nullable=True))
        op.create_index("ix_workflow_tasks_request_batch_id", "workflow_tasks", ["request_batch_id"])
    if "dispatch_claimed_at" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("dispatch_claimed_at", sa.DateTime(), nullable=True))
    if "dispatch_attempts" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"))
    if "next_dispatch_at" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("next_dispatch_at", sa.DateTime(), nullable=True))
    if "last_dispatch_error" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("last_dispatch_error", sa.Text(), nullable=True))

    existing_indexes = {index["name"] for index in inspector.get_indexes("workflow_tasks")}
    if "ix_workflow_tasks_dispatch" not in existing_indexes:
        op.create_index(
            "ix_workflow_tasks_dispatch",
            "workflow_tasks",
            ["status", "next_dispatch_at", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    # 이 마이그레이션은 데이터를 만들지 않는다. 되돌릴 때도 기존 이력 테이블은
    # 건드리지 않고 신규 구조만 제거한다.
    op.drop_index("ix_workflow_tasks_dispatch", table_name="workflow_tasks")
    for column in ("last_dispatch_error", "next_dispatch_at", "dispatch_attempts", "dispatch_claimed_at", "request_batch_id", "prompt_draft_id"):
        op.drop_column("workflow_tasks", column)
    for column in ("requested_frames", "negative_prompt", "prompt_batch_id"):
        op.drop_column("image_prompt_drafts", column)
    op.drop_table("runpod_request_batches")
    op.drop_table("prompt_generation_attempts")
    op.drop_table("prompt_generation_batches")
```

- [ ] **Step 5: 새 SQLite DB에 마이그레이션을 적용하고 테스트를 실행한다**

```bash
mkdir -p data
DATABASE_URL="sqlite:///./data/plan-schema-test.db" python3 -m alembic upgrade head
python3 -m pytest backend/tests/test_batch_queue_models.py -q
```

Expected: `alembic upgrade head`가 `20260901_0026`까지 성공하고, 테스트 3개 PASS.

- [ ] **Step 6: 커밋한다**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/20260901_0026_batch_prompt_runpod_queue.py backend/tests/test_batch_queue_models.py
git commit -m "feat: add durable prompt batch and RunPod dispatch schema"
```

---

## Task 3: 표시용 상태 파생 계층

**Files:**
- Modify: `backend/app/services/task_tracking_service.py`
- Create: `backend/tests/test_runpod_display_status.py`

**Interfaces:**
- Consumes: Task 2의 `WorkflowTask.status` 저장값(`PENDING_SUBMIT` 포함).
- Produces:
  - `PENDING_SUBMIT_STATUS: str` = `"PENDING_SUBMIT"`
  - `RUNPOD_DISPLAY_STATUSES: tuple[str, ...]`
  - `runpod_display_status(status: Any) -> str`
  - `runpod_display_counts(session: Session, user_id: str | None = None) -> dict[str, int]`
  - `_task_to_history_item()`이 만드는 항목에 `runpodDisplayStatus` 키 추가.

이 Task는 결정 3을 코드로 고정한다. 저장 어휘를 바꾸지 않으므로 기존 행과 신규 행이 같은 규칙으로 표시된다.

- [ ] **Step 1: 실패하는 매핑 테스트를 작성한다**

`backend/tests/test_runpod_display_status.py`:

```python
from __future__ import annotations

import pytest

from backend.app.db.models import WorkflowTask
from backend.app.services.task_tracking_service import (
    ACTIVE_STATES,
    PENDING_SUBMIT_STATUS,
    runpod_display_counts,
    runpod_display_status,
)
from backend.app.services.task_policy_service import ACTIVE_TASK_STATUSES


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("PENDING_SUBMIT", "REQUEST_WAITING"),
        ("queued", "RUNPOD_QUEUE"),
        ("QUEUED", "RUNPOD_QUEUE"),
        ("IN_QUEUE", "RUNPOD_QUEUE"),
        ("IN_PROGRESS", "RUNPOD_IN_PROGRESS"),
        ("RUNNING", "RUNPOD_IN_PROGRESS"),
        ("COMPLETED", "COMPLETED"),
        ("SUCCESS", "COMPLETED"),
        ("FAILED", "FAILED"),
        ("CANCELLED", "FAILED"),
        ("TIMED_OUT", "FAILED"),
    ],
)
def test_stored_status_maps_to_display_bucket(stored, expected):
    assert runpod_display_status(stored) == expected


def test_unknown_remote_status_is_treated_as_in_flight():
    assert runpod_display_status("SOMETHING_NEW") == "RUNPOD_QUEUE"


def test_pending_submit_does_not_consume_active_capacity():
    # PENDING_SUBMIT은 아직 RunPod 용량을 쓰지 않으므로 활성 집합에 없어야 한다.
    assert PENDING_SUBMIT_STATUS not in ACTIVE_TASK_STATUSES
    assert PENDING_SUBMIT_STATUS not in ACTIVE_STATES


def test_display_counts_group_every_bucket(db_session):
    db_session.add_all([
        WorkflowTask(id="t1", workflow_id="w", status="PENDING_SUBMIT"),
        WorkflowTask(id="t2", workflow_id="w", status="IN_QUEUE"),
        WorkflowTask(id="t3", workflow_id="w", status="IN_PROGRESS"),
        WorkflowTask(id="t4", workflow_id="w", status="COMPLETED"),
        WorkflowTask(id="t5", workflow_id="w", status="TIMED_OUT"),
    ])
    db_session.commit()

    counts = runpod_display_counts(db_session)

    assert counts == {
        "REQUEST_WAITING": 1,
        "RUNPOD_QUEUE": 1,
        "RUNPOD_IN_PROGRESS": 1,
        "COMPLETED": 1,
        "FAILED": 1,
    }
```

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_runpod_display_status.py -q`

Expected: `ImportError: cannot import name 'runpod_display_status'`로 FAIL.

- [ ] **Step 3: 파생 계층을 구현한다**

`backend/app/services/task_tracking_service.py`의 기존 상수 옆에 추가한다. `ACTIVE_STATES`와 `TERMINAL_STATES`는 건드리지 않는다.

```python
# 결정 3: 저장 어휘는 RunPod 원시값을 유지하고, 화면용 5분류는 여기서만 파생한다.
# PENDING_SUBMIT은 RunPod가 절대 돌려주지 않는 로컬 전용 저장값이며, 아직 원격
# 용량을 쓰지 않으므로 ACTIVE_STATES / ACTIVE_TASK_STATUSES에 넣지 않는다.
PENDING_SUBMIT_STATUS = "PENDING_SUBMIT"
RUNPOD_DISPLAY_STATUSES = (
    "REQUEST_WAITING",
    "RUNPOD_QUEUE",
    "RUNPOD_IN_PROGRESS",
    "COMPLETED",
    "FAILED",
)


def runpod_display_status(status: Any) -> str:
    text = str(status or "").upper()
    if text == PENDING_SUBMIT_STATUS:
        return "REQUEST_WAITING"
    if text in {"QUEUED", "IN_QUEUE", "SUBMITTED", "SUBMITTING"}:
        return "RUNPOD_QUEUE"
    if text in {"IN_PROGRESS", "RUNNING"}:
        return "RUNPOD_IN_PROGRESS"
    if text in {"COMPLETED", "SUCCESS"}:
        return "COMPLETED"
    if text in {"FAILED", "CANCELLED", "TIMED_OUT"}:
        return "FAILED"
    # 모르는 원격 상태는 아직 진행 중인 것으로 보고 큐 분류에 남긴다. 실패로
    # 단정하면 정상 작업이 이력에서 실패로 보이게 된다.
    return "RUNPOD_QUEUE"


def runpod_display_counts(session: Session, user_id: str | None = None) -> dict[str, int]:
    conditions = [WorkflowTask.deleted_at.is_(None)]
    if user_id:
        conditions.append(WorkflowTask.user_id == user_id)
    rows = session.execute(
        select(WorkflowTask.status, func.count())
        .where(*conditions)
        .group_by(WorkflowTask.status)
    ).all()
    counts = {name: 0 for name in RUNPOD_DISPLAY_STATUSES}
    for status, total in rows:
        counts[runpod_display_status(status)] += int(total or 0)
    return counts
```

`_task_to_history_item()`에서 기존 `item["status"]` 줄 바로 아래에 파생 필드를 추가한다. 기존 줄은 그대로 둔다.

```python
    item["status"] = _history_status_label(task.status)
    # 저장 어휘를 바꾸지 않고 화면용 5분류만 덧붙인다(결정 3).
    item["runpodDisplayStatus"] = runpod_display_status(task.status)
```

- [ ] **Step 4: 테스트를 실행해 통과를 확인한다**

Run: `python3 -m pytest backend/tests/test_runpod_display_status.py -q`

Expected: 15 passed.

- [ ] **Step 5: 기존 이력 회귀를 확인한다**

Run: `python3 -m pytest backend/tests -q`

Expected: 기존 테스트 전부 PASS. `item["status"]` 계약을 바꾸지 않았으므로 프런트 회귀는 없어야 한다.

- [ ] **Step 6: 커밋한다**

```bash
git add backend/app/services/task_tracking_service.py backend/tests/test_runpod_display_status.py
git commit -m "feat: derive RunPod display statuses without changing stored vocabulary"
```

---

## Task 4: 이미지 단위 Grok 배치 생성

**Files:**
- Create: `backend/app/services/prompt_batch_service.py`
- Modify: `backend/app/services/grok_image_prompt_service.py`
- Modify: `backend/app/api/v1/prompts.py`
- Create: `backend/tests/test_prompt_batch_service.py`
- Modify: `backend/tests/test_grok_image_prompt_service.py`

**Interfaces:**
- Consumes: Task 1의 `resolve_workflow_instruction_set`, Task 2의 `PromptGenerationBatch`/`PromptGenerationAttempt`/`ImagePromptDraft` 신규 컬럼.
- Produces:
  - `create_prompt_batch(session, *, workflow_id: str, asset_ids: list[str], user_id: str) -> dict[str, Any]`
  - `generate_prompt_batch(session, batch_id: str, *, retry_draft_id: str | None = None) -> dict[str, Any]`
  - `update_prompt_draft(session, draft_id: str, *, positive_prompt: str, negative_prompt: str, requested_frames: int) -> dict[str, Any]`
  - `prompt_history_page(session, *, page: int, page_size: int) -> dict[str, Any]`
  - `GrokImagePromptResult`에 `latency_ms: int`, `input_tokens: int`, `output_tokens: int`, `endpoint: str` 필드 추가.

**드래프트 상태 어휘:** 기존 값 `GENERATING` / `READY` / `MANUAL_REQUIRED` / `FAILED`를 그대로 저장한다(결정 3의 원칙을 드래프트에도 동일 적용). 화면용 분류는 `prompt_draft_display_status()`가 파생한다: `GENERATING`→`IN_PROGRESS`, `READY`→`COMPLETED`, `MANUAL_REQUIRED`→`MANUAL_REQUIRED`, `FAILED`→`FAILED`.

- [ ] **Step 1: 실패하는 서비스 테스트를 작성한다**

`backend/tests/test_prompt_batch_service.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.app.db.models import ImagePromptDraft, PromptGenerationAttempt
from backend.app.services.grok_image_prompt_service import GrokImagePromptResult, GrokPromptError
from backend.app.services.prompt_batch_service import (
    create_prompt_batch,
    generate_prompt_batch,
    prompt_draft_display_status,
    update_prompt_draft,
)


def _result(prompt: str) -> GrokImagePromptResult:
    return GrokImagePromptResult(
        positive_prompt=prompt,
        image_type="static_character",
        warnings=[],
        raw_response={"usage": {"input_tokens": 120, "output_tokens": 45}},
        latency_ms=1500,
        input_tokens=120,
        output_tokens=45,
        endpoint="https://api.x.ai/v1/responses",
    )


def test_batch_creates_one_draft_per_asset_and_records_telemetry(db_session, seeded_assets):
    batch = create_prompt_batch(
        db_session,
        workflow_id="1-images.json",
        asset_ids=["asset_a", "asset_b"],
        user_id="dobedub",
    )

    with patch("backend.app.services.prompt_batch_service.generate_image_prompt", side_effect=[_result("A"), _result("B")]):
        result = generate_prompt_batch(db_session, batch["id"])

    assert result["counts"] == {"total": 2, "completed": 2, "failed": 0}
    attempts = db_session.query(PromptGenerationAttempt).all()
    assert len(attempts) == 2
    assert {attempt.input_tokens for attempt in attempts} == {120}
    assert {attempt.output_tokens for attempt in attempts} == {45}
    assert all(attempt.latency_ms == 1500 for attempt in attempts)


def test_failed_attempt_keeps_positive_prompt_null_and_stores_error(db_session, seeded_assets):
    batch = create_prompt_batch(db_session, workflow_id="1-images.json", asset_ids=["asset_a"], user_id="dobedub")

    with patch(
        "backend.app.services.prompt_batch_service.generate_image_prompt",
        side_effect=GrokPromptError("rate limited", status_code=429, retryable=True),
    ):
        result = generate_prompt_batch(db_session, batch["id"])

    item = result["items"][0]
    assert item["positivePrompt"] is None
    assert item["status"] == "FAILED"
    assert "rate limited" in item["failureMessage"]
    assert result["counts"] == {"total": 1, "completed": 0, "failed": 1}


def test_retry_targets_one_draft_and_increments_attempt_no(db_session, seeded_assets):
    batch = create_prompt_batch(db_session, workflow_id="1-images.json", asset_ids=["asset_a"], user_id="dobedub")
    with patch("backend.app.services.prompt_batch_service.generate_image_prompt", side_effect=GrokPromptError("boom")):
        generate_prompt_batch(db_session, batch["id"])
    draft_id = db_session.query(ImagePromptDraft).one().id

    with patch("backend.app.services.prompt_batch_service.generate_image_prompt", side_effect=[_result("복구된 프롬프트")]):
        result = generate_prompt_batch(db_session, batch["id"], retry_draft_id=draft_id)

    assert result["items"][0]["positivePrompt"] == "복구된 프롬프트"
    attempt_numbers = sorted(attempt.attempt_no for attempt in db_session.query(PromptGenerationAttempt).all())
    assert attempt_numbers == [1, 2]


def test_missing_instruction_set_raises_before_any_grok_call(db_session, seeded_assets):
    with pytest.raises(ValueError, match="활성 프롬프트 지시문이 없습니다"):
        create_prompt_batch(db_session, workflow_id="unregistered.json", asset_ids=["asset_a"], user_id="dobedub")


def test_update_draft_persists_edited_pair_and_frames(db_session, seeded_assets):
    batch = create_prompt_batch(db_session, workflow_id="1-images.json", asset_ids=["asset_a"], user_id="dobedub")
    with patch("backend.app.services.prompt_batch_service.generate_image_prompt", side_effect=[_result("원본")]):
        generate_prompt_batch(db_session, batch["id"])
    draft_id = db_session.query(ImagePromptDraft).one().id

    updated = update_prompt_draft(
        db_session,
        draft_id,
        positive_prompt="편집된 프롬프트",
        negative_prompt="low quality",
        requested_frames=161,
    )

    assert updated["positivePrompt"] == "편집된 프롬프트"
    assert updated["negativePrompt"] == "low quality"
    assert updated["requestedFrames"] == 161


def test_invalid_frames_value_is_rejected(db_session, seeded_assets):
    batch = create_prompt_batch(db_session, workflow_id="1-images.json", asset_ids=["asset_a"], user_id="dobedub")
    with patch("backend.app.services.prompt_batch_service.generate_image_prompt", side_effect=[_result("원본")]):
        generate_prompt_batch(db_session, batch["id"])
    draft_id = db_session.query(ImagePromptDraft).one().id

    with pytest.raises(ValueError, match="49, 81, 161 중 하나"):
        update_prompt_draft(db_session, draft_id, positive_prompt="p", negative_prompt="n", requested_frames=100)


def test_display_status_derives_from_stored_vocabulary():
    assert prompt_draft_display_status("GENERATING") == "IN_PROGRESS"
    assert prompt_draft_display_status("READY") == "COMPLETED"
    assert prompt_draft_display_status("MANUAL_REQUIRED") == "MANUAL_REQUIRED"
    assert prompt_draft_display_status("FAILED") == "FAILED"
```

`seeded_assets` 픽스처를 `backend/tests/conftest.py`에 추가한다.

```python
@pytest.fixture
def seeded_assets(db_session, tmp_path):
    from backend.app.db.models import Asset

    records = []
    for asset_id in ("asset_a", "asset_b"):
        image_path = tmp_path / f"{asset_id}.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        records.append(Asset(
            id=asset_id,
            file_name=f"{asset_id}.png",
            mime_type="image/png",
            image_width=720,
            image_height=1280,
        ))
    db_session.add_all(records)
    db_session.commit()
    return {"asset_a": tmp_path / "asset_a.png", "asset_b": tmp_path / "asset_b.png"}
```

`Asset` 모델의 필수 컬럼이 위와 다르면 `backend/app/db/models.py`의 실제 정의에 맞춰 필드를 채운다. 픽스처가 모델 정의를 바꾸게 하지 말 것.

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_prompt_batch_service.py -q`

Expected: `ModuleNotFoundError: backend.app.services.prompt_batch_service`로 FAIL.

- [ ] **Step 3: Grok 결과에 텔레메트리를 싣는다**

`backend/app/services/grok_image_prompt_service.py`의 `GrokImagePromptResult`를 확장한다. xAI Responses API(`/responses`)의 usage 키는 `input_tokens` / `output_tokens`다.

```python
@dataclass(frozen=True)
class GrokImagePromptResult:
    positive_prompt: str
    image_type: str
    warnings: list[str]
    raw_response: dict[str, Any]
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    endpoint: str = ""
```

`generate_image_prompt()`에서 요청 직전·직후 시각을 재고 usage를 읽어 채운다.

```python
    endpoint = f"{settings.grok_base_url.rstrip('/')}/responses"
    started_at = time.monotonic()
    response = _json_request_with_retry(
        endpoint,
        settings.grok_api_key,
        payload,
        settings.grok_request_timeout_seconds,
        max_retries=settings.grok_max_retries,
        retry_backoff_seconds=settings.grok_retry_backoff_seconds,
    )
    latency_ms = int((time.monotonic() - started_at) * 1000)
    usage = response.get("usage") or {}
```

그리고 `return GrokImagePromptResult(...)`에 다음을 추가한다.

```python
        latency_ms=latency_ms,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        endpoint=endpoint,
```

기존 호출부(`prompts.py`의 단건 `/image-drafts/generate`)는 기본값 덕분에 그대로 동작한다.

- [ ] **Step 4: 배치 서비스를 구현한다**

`backend/app/services/prompt_batch_service.py`:

```python
"""이미지 단위 Grok 프롬프트 배치의 수명주기.

이 서비스는 이미지를 서버에서 직접 읽어 Grok에 보낸다. 브라우저는 저장 경로,
provider key, 지시문 본문 중 어느 것도 받지 않는다.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.timezone_utils import utc_now
from backend.app.db.models import ImagePromptDraft, PromptGenerationAttempt, PromptGenerationBatch
from backend.app.services import studio_api_service
from backend.app.services.grok_image_prompt_service import (
    GrokPromptError,
    GrokPromptInputError,
    generate_image_prompt,
)
from backend.app.services.grok_instruction_service import active_instruction_text

ALLOWED_FRAMES = (49, 81, 161)
DEFAULT_FRAMES = 81

_DRAFT_DISPLAY = {
    "GENERATING": "IN_PROGRESS",
    "READY": "COMPLETED",
    "MANUAL_REQUIRED": "MANUAL_REQUIRED",
    "FAILED": "FAILED",
}


def prompt_draft_display_status(status: Any) -> str:
    return _DRAFT_DISPLAY.get(str(status or "").upper(), "WAITING")


def create_prompt_batch(session: Session, *, workflow_id: str, asset_ids: list[str], user_id: str) -> dict[str, Any]:
    if not asset_ids:
        raise ValueError("이미지를 한 장 이상 선택하세요.")
    # 지시문이 없으면 Grok을 한 번도 호출하지 않고 즉시 막는다.
    instruction_text, instruction_version = active_instruction_text(workflow_id)
    settings = get_settings()
    now = utc_now().replace(tzinfo=None)
    batch = PromptGenerationBatch(
        id=f"pgb_{uuid.uuid4().hex[:16]}",
        workflow_id=workflow_id,
        status="WAITING",
        total_count=len(asset_ids),
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(batch)
    for slot_index, asset_id in enumerate(asset_ids, start=1):
        session.add(ImagePromptDraft(
            id=f"grok_draft_{uuid.uuid4().hex[:16]}",
            asset_id=asset_id,
            workflow_id=workflow_id,
            slot_index=slot_index,
            status="GENERATING",
            provider="grok",
            model=settings.grok_model,
            instruction_version=instruction_version,
            warnings_json=[],
            raw_json={},
            prompt_batch_id=batch.id,
            requested_frames=DEFAULT_FRAMES,
            created_by=user_id,
            created_at=now,
            updated_at=now,
        ))
    session.commit()
    return _batch_payload(session, batch.id)
```

`generate_prompt_batch()`는 대상 드래프트를 하나씩 처리한다. 각 드래프트마다 `PromptGenerationAttempt`를 만들고, 성공하면 `READY`(빈 프롬프트면 `MANUAL_REQUIRED`), 실패하면 `FAILED` + `failure_message`를 남기며 **`positive_prompt`는 `NULL`로 둔다.** 한 건의 실패가 나머지 항목을 막지 않는다.

```python
def generate_prompt_batch(session: Session, batch_id: str, *, retry_draft_id: str | None = None) -> dict[str, Any]:
    batch = session.get(PromptGenerationBatch, batch_id)
    if not batch:
        raise ValueError("프롬프트 배치를 찾을 수 없습니다.")
    instruction_text, instruction_version = active_instruction_text(batch.workflow_id)
    settings = get_settings()

    statement = select(ImagePromptDraft).where(ImagePromptDraft.prompt_batch_id == batch_id)
    if retry_draft_id:
        statement = statement.where(ImagePromptDraft.id == retry_draft_id)
    drafts = list(session.scalars(statement.order_by(ImagePromptDraft.slot_index.asc())))

    for draft in drafts:
        attempt_no = 1 + int(session.scalar(
            select(func.count()).select_from(PromptGenerationAttempt).where(PromptGenerationAttempt.draft_id == draft.id)
        ) or 0)
        started_at = utc_now().replace(tzinfo=None)
        draft.status = "GENERATING"
        draft.instruction_version = instruction_version
        draft.failure_message = None
        session.commit()
        try:
            asset, asset_path = studio_api_service.get_asset(draft.asset_id)
            result = generate_image_prompt(
                settings,
                asset_path=asset_path,
                mime_type=str(asset.get("mimeType") or ""),
                file_name=str(asset.get("fileName") or asset_path.name),
                image_width=asset.get("imageWidth"),
                image_height=asset.get("imageHeight"),
                instruction_text=instruction_text,
            )
        except (GrokPromptError, GrokPromptInputError, KeyError, FileNotFoundError) as exc:
            draft.status = "FAILED"
            draft.positive_prompt = None
            draft.failure_message = str(exc)
            session.add(PromptGenerationAttempt(
                id=f"pga_{uuid.uuid4().hex[:16]}",
                draft_id=draft.id,
                attempt_no=attempt_no,
                status="FAILED",
                model=settings.grok_model,
                started_at=started_at,
                completed_at=utc_now().replace(tzinfo=None),
                response_json={},
                failure_message=str(exc),
                created_at=started_at,
            ))
            session.commit()
            continue

        draft.status = "MANUAL_REQUIRED" if not result.positive_prompt else "READY"
        draft.positive_prompt = result.positive_prompt or None
        draft.warnings_json = result.warnings
        draft.raw_json = {"imageType": result.image_type, "response": result.raw_response}
        session.add(PromptGenerationAttempt(
            id=f"pga_{uuid.uuid4().hex[:16]}",
            draft_id=draft.id,
            attempt_no=attempt_no,
            status="COMPLETED",
            endpoint=result.endpoint,
            model=settings.grok_model,
            started_at=started_at,
            completed_at=utc_now().replace(tzinfo=None),
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            response_json=result.raw_response,
            created_at=started_at,
        ))
        session.commit()

    _refresh_counts(session, batch_id)
    return _batch_payload(session, batch_id)
```

`update_prompt_draft()`는 `requested_frames`가 `ALLOWED_FRAMES`에 없으면 `ValueError("프레임 수는 49, 81, 161 중 하나여야 합니다.")`를 던진다. 편집으로 프롬프트가 채워지면 `MANUAL_REQUIRED` 드래프트를 `READY`로 승격한다.

`_batch_payload()`가 만드는 항목 키: `draftId`, `assetId`, `slotIndex`, `status`(파생 표시값), `storedStatus`, `positivePrompt`, `negativePrompt`, `requestedFrames`, `failureMessage`, `warnings`, `imageWidth`, `imageHeight`, `thumbnailUrl`. `counts`는 `{"total", "completed", "failed"}`이고 `completed`는 저장값 `READY`, `failed`는 `FAILED`를 센다.

- [ ] **Step 5: REST 엔드포인트를 추가한다**

`backend/app/api/v1/prompts.py`에 `prompts:build` 권한으로 다음 라우트를 추가한다.

```text
POST   /api/prompts/batches
POST   /api/prompts/batches/{batch_id}/generate
POST   /api/prompts/drafts/{draft_id}/regenerate
PATCH  /api/prompts/drafts/{draft_id}
GET    /api/prompts/batches/{batch_id}
```

지시문이 없을 때 생성 라우트는 `409`와 정확한 문구 `"선택한 워크플로우에 활성 프롬프트 지시문이 없습니다."`를 반환한다.

```python
@router.post("/batches", status_code=201)
def create_batch(payload: dict, current_user: CurrentUser = Depends(require_permission("prompts:build")), db: Session = Depends(get_db)):
    try:
        return create_prompt_batch(
            db,
            workflow_id=str(payload.get("workflowId") or "").strip(),
            asset_ids=[str(item) for item in payload.get("assetIds") or []],
            user_id=current_user.id,
        )
    except ValueError as exc:
        status_code = 409 if "지시문" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
```

- [ ] **Step 6: 테스트를 실행해 통과를 확인한다**

Run: `python3 -m pytest backend/tests/test_prompt_batch_service.py backend/tests/test_grok_image_prompt_service.py -q`

Expected: PASS.

- [ ] **Step 7: 커밋한다**

```bash
git add backend/app/services/prompt_batch_service.py backend/app/services/grok_image_prompt_service.py backend/app/api/v1/prompts.py backend/tests/conftest.py backend/tests/test_prompt_batch_service.py backend/tests/test_grok_image_prompt_service.py
git commit -m "feat: generate Grok prompts per uploaded image in batches"
```

---

## Task 5: 내구성 직렬 RunPod 디스패처

**Files:**
- Create: `backend/app/services/runpod_dispatch_service.py`
- Modify: `backend/app/services/studio_api_service.py`
- Modify: `backend/app/api/v1/jobs.py`
- Modify: `backend/app/main.py:80-91`
- Create: `backend/tests/test_runpod_dispatch_service.py`

**Interfaces:**
- Consumes: Task 2의 디스패치 컬럼, Task 3의 `PENDING_SUBMIT_STATUS`/`runpod_display_counts`, Task 4의 완료 드래프트.
- Produces:
  - `enqueue_runpod_tasks(session, *, draft_ids: list[str], user_id: str, user: dict[str, Any]) -> dict[str, Any]`
  - `dispatch_next_waiting_task(runtime=None) -> str | None`
  - `reconcile_active_runpod_tasks() -> int`
  - `queue_summary(session, user_id: str | None = None) -> dict[str, Any]`
  - `GET /api/jobs/queue-summary`, `POST /api/jobs/queue`

**결정 1 적용:** 이 서비스에는 dry-run 분기가 없다. `dispatch_next_waiting_task()`는 항상 실제 RunPod 제출을 수행한다. 테스트는 `runtime` 인자로 `JobRuntime`을 주입하고 그 안의 `runpod_request`를 `fake_runpod`로 바꾼다. `settings.dry_run`은 이 경로에서 읽지 않는다.

- [ ] **Step 1: 실패하는 디스패처 테스트를 작성한다**

`backend/tests/test_runpod_dispatch_service.py`:

```python
from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.db.models import WorkflowTask
from backend.app.services.runpod_dispatch_service import (
    dispatch_next_waiting_task,
    enqueue_runpod_tasks,
    queue_summary,
    reconcile_active_runpod_tasks,
)


def test_enqueue_accepts_beyond_capacity_without_rejecting(db_session, ready_drafts, dispatch_runtime):
    result = enqueue_runpod_tasks(
        db_session,
        draft_ids=[draft.id for draft in ready_drafts],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )

    assert result["queued"] == len(ready_drafts)
    statuses = {task.status for task in db_session.query(WorkflowTask).all()}
    assert statuses == {"PENDING_SUBMIT"}


def test_enqueued_task_carries_existing_payload_contract(db_session, ready_drafts, dispatch_runtime):
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[ready_drafts[0].id],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )
    task = db_session.query(WorkflowTask).one()

    payload = task.payload_json
    assert payload["workflowId"] == "1-images.json"
    # prepare_workflow_for_job이 실제로 읽는 키만 쓴다.
    assert payload["keyframes"][0]["uploadId"] == ready_drafts[0].asset_id
    segment = payload["segments"][0]
    assert segment["positivePrompt"] == ready_drafts[0].positive_prompt
    assert segment["negativePromptAddition"] == ready_drafts[0].negative_prompt
    # 노드 config 키는 frames/fps다. length가 아니다.
    assert segment["config"]["frames"] == 81
    assert segment["config"]["fps"] == 16
    assert segment["config"]["width"] == 720
    assert segment["config"]["height"] == 1280


def test_dispatcher_submits_one_and_leaves_the_rest_waiting(db_session, ready_drafts, dispatch_runtime):
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[draft.id for draft in ready_drafts],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )

    dispatched = dispatch_next_waiting_task(runtime=dispatch_runtime)

    assert dispatched is not None
    tasks = {task.id: task for task in db_session.query(WorkflowTask).all()}
    db_session.expire_all()
    submitted = tasks[dispatched]
    db_session.refresh(submitted)
    assert submitted.status == "IN_QUEUE"
    assert submitted.runpod_job_id == "runpod_job_test_1"
    remaining = [task for task_id, task in tasks.items() if task_id != dispatched]
    for task in remaining:
        db_session.refresh(task)
        assert task.status == "PENDING_SUBMIT"


def test_dispatcher_returns_none_when_no_waiting_work(db_session, dispatch_runtime):
    assert dispatch_next_waiting_task(runtime=dispatch_runtime) is None


def test_capacity_full_keeps_task_waiting_and_sets_backoff(db_session, ready_drafts, dispatch_runtime, saturated_policy):
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[ready_drafts[0].id],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )

    assert dispatch_next_waiting_task(runtime=dispatch_runtime) is None

    task = db_session.query(WorkflowTask).filter(WorkflowTask.status == "PENDING_SUBMIT").one()
    db_session.refresh(task)
    assert task.status == "PENDING_SUBMIT"
    assert task.next_dispatch_at is not None
    assert task.dispatch_claimed_at is None


def test_submit_failure_releases_claim_with_bounded_backoff(db_session, ready_drafts, dispatch_runtime):
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[ready_drafts[0].id],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )

    def _boom(method, path, payload=None):
        raise RuntimeError("RunPod HTTP 500: upstream error")

    failing_runtime = replace(dispatch_runtime, runpod_request=_boom)
    assert dispatch_next_waiting_task(runtime=failing_runtime) is None

    task = db_session.query(WorkflowTask).one()
    db_session.refresh(task)
    assert task.status == "PENDING_SUBMIT"
    assert task.dispatch_claimed_at is None
    assert task.dispatch_attempts == 1
    assert "upstream error" in task.last_dispatch_error


def test_claim_is_not_handed_out_twice(db_session, ready_drafts, dispatch_runtime):
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[ready_drafts[0].id],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )

    first = dispatch_next_waiting_task(runtime=dispatch_runtime)
    second = dispatch_next_waiting_task(runtime=dispatch_runtime)

    assert first is not None
    assert second is None


def test_restart_picks_up_an_existing_waiting_row(db_session, ready_drafts, dispatch_runtime):
    # 프로세스가 죽어 클레임이 남은 행은 다음 사이클이 회수한다.
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[ready_drafts[0].id],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )
    task = db_session.query(WorkflowTask).one()
    task.dispatch_claimed_at = task.created_at
    db_session.commit()

    assert dispatch_next_waiting_task(runtime=dispatch_runtime, stale_claim_seconds=0) == task.id


@pytest.mark.parametrize(
    ("remote", "expected"),
    [("COMPLETED", "COMPLETED"), ("FAILED", "FAILED"), ("CANCELLED", "CANCELLED"), ("TIMED_OUT", "TIMED_OUT")],
)
def test_reconcile_stores_raw_remote_status(db_session, ready_drafts, dispatch_runtime, remote, expected):
    # 결정 3: CANCELLED/TIMED_OUT을 FAILED로 덮어쓰지 않는다. 저장은 원시값,
    # FAILED 분류는 runpod_display_status()가 화면에서만 수행한다.
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[ready_drafts[0].id],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )
    dispatch_next_waiting_task(runtime=dispatch_runtime)
    dispatch_runtime.runpod_request.status_response = {"status": remote}

    reconcile_active_runpod_tasks(runtime=dispatch_runtime)

    task = db_session.query(WorkflowTask).one()
    db_session.refresh(task)
    assert task.status == expected


def test_queue_summary_reports_display_buckets(db_session, ready_drafts, dispatch_runtime):
    enqueue_runpod_tasks(
        db_session,
        draft_ids=[draft.id for draft in ready_drafts],
        user_id="dobedub",
        user={"id": "dobedub", "name": "dobedub", "role": "admin", "permissions": ["jobs:run"]},
    )

    summary = queue_summary(db_session)

    assert summary["counts"]["REQUEST_WAITING"] == len(ready_drafts)
    assert summary["counts"]["RUNPOD_QUEUE"] == 0
```

`backend/tests/conftest.py`에 픽스처 세 개를 추가한다.

```python
@pytest.fixture
def ready_drafts(db_session, seeded_assets):
    """편집까지 끝난 상태의 완료 드래프트 두 건."""
    from backend.app.db.models import ImagePromptDraft

    drafts = []
    for index, asset_id in enumerate(("asset_a", "asset_b"), start=1):
        draft = ImagePromptDraft(
            id=f"grok_draft_ready_{index}",
            asset_id=asset_id,
            workflow_id="1-images.json",
            slot_index=index,
            status="READY",
            provider="grok",
            model="grok-test",
            instruction_version="1-images.json@1",
            warnings_json=[],
            raw_json={},
            positive_prompt=f"positive {index}",
            negative_prompt="low quality",
            requested_frames=81,
            created_by="dobedub",
        )
        drafts.append(draft)
    db_session.add_all(drafts)
    db_session.commit()
    return drafts


@pytest.fixture
def dispatch_runtime(fake_runpod, seeded_assets):
    """실제 제출 경로를 그대로 쓰되 HTTP 전송만 교체한 런타임(결정 1)."""
    from backend.app.services import job_service, studio_api_service

    return job_service.JobRuntime(
        jobs={},
        dry_run=False,
        prepare_workflow_for_job=lambda payload: ({}, [], {"seed": {"value": 12345}}),
        build_runpod_payload=lambda workflow, images: {"input": {"workflow": workflow}},
        runpod_request=fake_runpod,
        save_runpod_outputs=lambda result, job: {},
        append_history=lambda item: None,
        build_wan_node_config_snapshot=lambda workflow_id, segments: {},
        hydrate_input_images=lambda item, assets: [],
        record_job=lambda job: None,
    )


@pytest.fixture
def saturated_policy(db_session):
    """전체 활성 한도를 이미 채운 상태."""
    from backend.app.db.models import TaskExecutionPolicy, WorkflowTask

    db_session.add(TaskExecutionPolicy(id=1, max_active_tasks_per_user=1, max_active_tasks_total=1))
    db_session.add(WorkflowTask(id="task_busy", workflow_id="1-images.json", status="IN_PROGRESS", user_id="dobedub"))
    db_session.commit()
```

`JobRuntime`의 실제 필드명이 위와 다르면 `backend/app/services/job_service.py`의 dataclass 정의를 그대로 따른다.

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_runpod_dispatch_service.py -q`

Expected: `ModuleNotFoundError: backend.app.services.runpod_dispatch_service`로 FAIL.

- [ ] **Step 3: 기존 payload 계약대로 대기 작업을 만든다**

`prepare_workflow_for_job()`이 실제로 읽는 키는 `workflowId`, `keyframes[].uploadId`, `keyframes[].index`, `segments[].positivePrompt`, `segments[].negativePromptAddition`, `segments[].config`다. `config`는 `ui_config_to_param_config()`가 인식하는 카멜/스네이크 키만 반영되므로 `frames`, `fps`, `width`, `height`를 쓴다.

```python
def _build_task_payload(draft: ImagePromptDraft, asset: dict, user: dict[str, Any]) -> dict[str, Any]:
    """기존 실행 파이프라인이 이해하는 payload 형태를 그대로 만든다."""
    width = int(asset.get("imageWidth") or 0)
    height = int(asset.get("imageHeight") or 0)
    return {
        "workflowId": draft.workflow_id,
        "keyframes": [
            {"index": 1, "uploadId": draft.asset_id, "fileName": asset.get("fileName")}
        ],
        "segments": [
            {
                "index": 1,
                "positivePrompt": draft.positive_prompt or "",
                "negativePromptAddition": draft.negative_prompt or "",
                # length가 아니라 frames다. ui_config_to_param_config 참조.
                "config": {
                    "frames": int(draft.requested_frames or DEFAULT_FRAMES),
                    "fps": 16,
                    "width": width,
                    "height": height,
                },
            }
        ],
        "user": {
            "id": str(user.get("id") or ""),
            "name": str(user.get("name") or user.get("id") or ""),
            "role": str(user.get("role") or ""),
            "permissions": list(user.get("permissions") or []),
        },
        # 원본과 제출 해상도를 함께 남겨 추적만 가능하게 한다(정규화하지 않는다).
        "sourceDimensions": {"width": width, "height": height},
        "submittedDimensions": {"width": width, "height": height},
    }
```

`enqueue_runpod_tasks()`는 선택된 드래프트마다 한 트랜잭션에서 `WorkflowTask`를 만든다. 한도를 이유로 거부하지 않는다.

```python
def enqueue_runpod_tasks(session, *, draft_ids, user_id, user):
    drafts = list(session.scalars(select(ImagePromptDraft).where(ImagePromptDraft.id.in_(draft_ids))))
    if len(drafts) != len(set(draft_ids)):
        raise ValueError("요청한 프롬프트 초안 중 일부를 찾을 수 없습니다.")
    now = utc_now().replace(tzinfo=None)
    batch = RunpodRequestBatch(
        id=f"rrb_{uuid.uuid4().hex[:16]}",
        workflow_id=drafts[0].workflow_id,
        requested_count=len(drafts),
        created_by=user_id,
        created_at=now,
    )
    session.add(batch)
    queued = 0
    for draft in drafts:
        if not (draft.positive_prompt or "").strip():
            raise ValueError("Positive Prompt가 비어 있는 항목은 요청할 수 없습니다.")
        asset, _path = studio_api_service.get_asset(draft.asset_id)
        task_id = f"task_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        session.add(WorkflowTask(
            id=task_id,
            workflow_id=draft.workflow_id,
            status=PENDING_SUBMIT_STATUS,
            execution_mode="runpod",
            user_id=user_id,
            prompt_draft_id=draft.id,
            request_batch_id=batch.id,
            payload_json=_build_task_payload(draft, asset, user),
            config_json={"frames": int(draft.requested_frames or DEFAULT_FRAMES), "fps": 16, "seed": "server-auto"},
            positive_prompts=[draft.positive_prompt or ""],
            negative_prompts=[draft.negative_prompt or ""],
            dispatch_attempts=0,
            created_at=now,
            updated_at=now,
        ))
        queued += 1
    session.commit()
    return {"batchId": batch.id, "queued": queued}
```

`execution_mode`는 `"runpod"`로 고정한다. 결정 1에 따라 이 경로에는 dry-run이 없기 때문이다.

- [ ] **Step 4: 조건부 UPDATE로 한 건만 클레임해 제출한다**

MySQL과 SQLite 모두에서 동작해야 하므로 `SELECT ... FOR UPDATE SKIP LOCKED`를 쓰지 않는다. 후보를 고른 뒤 조건부 `UPDATE`의 영향 행 수로 클레임 성공을 판정한다. 이 방식은 프로세스가 여러 개여도 안전하다.

```python
BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300
STALE_CLAIM_SECONDS = 600


def _claim_next_task(session, *, stale_claim_seconds: int = STALE_CLAIM_SECONDS):
    now = utc_now().replace(tzinfo=None)
    stale_before = now - timedelta(seconds=stale_claim_seconds)
    candidate_id = session.scalar(
        select(WorkflowTask.id)
        .where(
            WorkflowTask.status == PENDING_SUBMIT_STATUS,
            WorkflowTask.deleted_at.is_(None),
            or_(WorkflowTask.dispatch_claimed_at.is_(None), WorkflowTask.dispatch_claimed_at <= stale_before),
            or_(WorkflowTask.next_dispatch_at.is_(None), WorkflowTask.next_dispatch_at <= now),
        )
        .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
        .limit(1)
    )
    if not candidate_id:
        return None
    # 영향 행 수가 1일 때만 이 사이클이 소유권을 가진다. 다른 프로세스가 먼저
    # 집어갔으면 0이 되고 이번 사이클은 조용히 물러난다.
    claimed = session.execute(
        update(WorkflowTask)
        .where(
            WorkflowTask.id == candidate_id,
            WorkflowTask.status == PENDING_SUBMIT_STATUS,
            or_(WorkflowTask.dispatch_claimed_at.is_(None), WorkflowTask.dispatch_claimed_at <= stale_before),
        )
        .values(dispatch_claimed_at=now, dispatch_attempts=WorkflowTask.dispatch_attempts + 1)
    ).rowcount
    session.commit()
    if not claimed:
        return None
    return session.get(WorkflowTask, candidate_id)


def _release_with_backoff(session, task, message: str) -> None:
    delay = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** max(0, task.dispatch_attempts - 1)))
    task.dispatch_claimed_at = None
    task.next_dispatch_at = utc_now().replace(tzinfo=None) + timedelta(seconds=delay)
    task.last_dispatch_error = message
    session.commit()
```

`dispatch_next_waiting_task()`의 순서는 다음과 같다.

1. 대기 행이 하나도 없으면 즉시 `None`을 반환한다(엔드포인트 호출 없음).
2. `task_policy_service.active_task_counts(session, user_id)`로 사용자·전체 활성 수를 읽는다. `PENDING_SUBMIT`은 여기에 포함되지 않으므로 실제 RunPod 점유량만 센다. 한도에 도달했으면 클레임을 풀고 backoff만 설정한 뒤 `None`을 반환한다. 실패로 기록하지 않는다.
3. 엔드포인트 가용성을 확인한다. 확인 실패도 실패가 아니라 backoff다.
4. `runtime.prepare_workflow_for_job(payload)` → `runtime.runpod_request("POST", "/run", runtime.build_runpod_payload(workflow, images))`로 제출한다.
5. 성공하면 `runpod_job_id`, `runpod_submit_json`, `patch_summary`, `wan_node_config`를 저장하고 상태를 `"IN_QUEUE"`(기존 저장 어휘)로 바꾸며 `dispatch_claimed_at`을 비운다.
6. 제출이 예외로 끝나면 `_release_with_backoff()`로 되돌린다. 작업을 `FAILED`로 만들지 않는다. 일시적 장애로 큐 항목을 잃으면 안 되기 때문이다.

`reconcile_active_runpod_tasks()`는 `runpod_job_id`가 있고 종료 상태가 아닌 작업을 폴링해 **RunPod가 준 상태 문자열을 그대로 저장한다.** `CANCELLED`나 `TIMED_OUT`을 `FAILED`로 바꾸지 않는다. 화면의 `FAILED` 분류는 `runpod_display_status()`가 담당한다.

- [ ] **Step 5: API와 라이프사이클에 연결한다**

`backend/app/api/v1/jobs.py`에 라우트 두 개를 추가한다. 기존 `POST /jobs` 단건 경로는 그대로 둔다.

```python
@router.post("/queue", status_code=201)
def enqueue_jobs(payload: dict, current_user: CurrentUser = Depends(require_permission("jobs:run")), db: Session = Depends(get_db)):
    try:
        return enqueue_runpod_tasks(
            db,
            draft_ids=[str(item) for item in payload.get("draftIds") or []],
            user_id=current_user.id,
            user={"id": current_user.id, "name": current_user.name, "role": current_user.role, "permissions": current_user.permissions},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/queue-summary")
def runpod_queue_summary(_: CurrentUser = Depends(require_any_permission(("jobs:run", "history:read"))), db: Session = Depends(get_db)):
    return queue_summary(db)
```

`backend/app/main.py`의 기존 `monitor_loop()` 안에 디스패처 호출을 넣는다. 별도 루프를 만들지 않는다.

```python
    async def monitor_loop() -> None:
        while True:
            try:
                result = await asyncio.to_thread(monitor_active_jobs)
                if result["failures"]:
                    LOGGER.warning("Task monitor could not refresh tasks: %s", result["failures"])
                prompt_result = await asyncio.to_thread(monitor_active_prompt_generations)
                if prompt_result["failures"]:
                    LOGGER.warning("Prompt monitor could not refresh requests: %s", prompt_result["failures"])
                # 대기 큐에서 정확히 한 건만 제출한다. 브라우저가 닫혀도 진행된다.
                dispatched = await asyncio.to_thread(dispatch_next_waiting_task)
                if dispatched:
                    LOGGER.info("RunPod dispatcher submitted task %s", dispatched)
            except Exception:
                LOGGER.exception("Task monitor cycle failed")
            await asyncio.sleep(settings.task_monitor_interval_seconds)
```

모니터 주기 기본값은 5초이므로 사이클당 1건 제출이면 활성 10건까지 약 50초가 걸린다. 이는 의도된 램프업이다.

- [ ] **Step 6: 테스트를 실행해 통과를 확인한다**

Run: `python3 -m pytest backend/tests/test_runpod_dispatch_service.py -q`

Expected: PASS. 재시작 회수, 중복 클레임 방지, 원시 상태 보존 케이스가 모두 포함된다.

- [ ] **Step 7: 커밋한다**

```bash
git add backend/app/services/runpod_dispatch_service.py backend/app/services/studio_api_service.py backend/app/api/v1/jobs.py backend/app/main.py backend/tests/conftest.py backend/tests/test_runpod_dispatch_service.py
git commit -m "feat: queue and serially dispatch RunPod tasks"
```

---

## Task 6: Prompt Generation Management 화면

**Files:**
- Create: `frontend/src/screens/promptBatchScreen.tsx`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/components/AppShell.tsx:56-62`
- Modify: `frontend/src/StudioShell.tsx:1982-2066`
- Modify: `frontend/src/helpers/navigation.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/styles.css`
- Create: `backend/tests/test_frontend_prompt_management_contract.py`

**Interfaces:**
- Consumes: Task 4의 배치 API.
- Produces:
  - 라우트 키 `create.prompt-management`, 경로 `/studio/create/prompt-management`.
  - 사이드바 메뉴 key `promptManagement`.
  - 클라이언트 메서드 `createPromptBatch`, `generatePromptBatch`, `regeneratePromptDraft`, `updatePromptDraft`, `getPromptBatch`.
  - 컴포넌트 `PromptBatchScreen`.

- [ ] **Step 1: 실패하는 소스 계약 테스트를 작성한다**

`backend/tests/test_frontend_prompt_management_contract.py`:

```python
from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_route_is_registered_and_rendered():
    router = _read("frontend/src/router.ts")
    assert '"create.prompt-management"' in router
    assert "/studio/create/prompt-management" in router

    shell = _read("frontend/src/StudioShell.tsx")
    assert 'route === "create.prompt-management"' in shell
    assert "PromptBatchScreen" in shell


def test_sidebar_menu_replaces_workspace_entry():
    app_shell = _read("frontend/src/components/AppShell.tsx")
    assert '{ key: "workspace", label: "Workspace" }' not in app_shell
    assert 'key: "promptManagement"' in app_shell

    navigation = _read("frontend/src/helpers/navigation.ts")
    assert 'key === "promptManagement"' in navigation
    assert 'onGoTo("create.prompt-management")' in navigation


def test_screen_uses_batch_generation_and_blocks_duplicate_submit():
    source = _read("frontend/src/screens/promptBatchScreen.tsx")
    assert "generatePromptBatch" in source
    assert "프롬프트 생성 중" in source
    assert "disabled={!selectedWorkflowId || imageItems.length === 0 || isGenerating}" in source


def test_screen_shows_per_image_controls():
    source = _read("frontend/src/screens/promptBatchScreen.tsx")
    for token in ("regeneratePromptDraft", "updatePromptDraft", "assetId", "imageWidth", "failureMessage"):
        assert token in source


def test_no_pre_run_confirmation_page_is_added():
    source = _read("frontend/src/screens/promptBatchScreen.tsx")
    assert "create.confirm" not in source
```

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_frontend_prompt_management_contract.py -q`

Expected: `FileNotFoundError: frontend/src/screens/promptBatchScreen.tsx`로 FAIL.

- [ ] **Step 3: 라우트·메뉴·렌더 지점을 등록한다**

`frontend/src/router.ts`의 `StudioRoute` 유니온과 경로 맵에 추가한다.

```ts
  | "create.prompt-management"
  | "create.runpod-requests"
```

```ts
  "create.prompt-management": "/studio/create/prompt-management",
  "create.runpod-requests": "/studio/create/runpod-requests",
```

`frontend/src/components/AppShell.tsx:56`의 `{ key: "workspace", label: "Workspace" }` 항목을 두 항목으로 교체한다.

```ts
  { key: "promptManagement", label: "Prompt Generation", permission: "prompts:build" },
  { key: "runpodRequests", label: "RunPod Requests", permission: "jobs:run" },
```

`frontend/src/helpers/navigation.ts`의 `shellNavigate`에 매핑을 추가한다. 기존 `workspace` 분기는 옛 링크 호환을 위해 남긴다.

```ts
  if (key === "promptManagement") {
    onGoTo("create.prompt-management");
  } else if (key === "runpodRequests") {
    onGoTo("create.runpod-requests");
  } else if (key === "workspace") {
    // 옛 링크/북마크 호환. 사이드바에는 더 이상 노출하지 않는다.
    onGoTo("create.load");
  } else if (...) { ... }
```

`frontend/src/StudioShell.tsx`의 라우트 분기 체인에 항목을 추가한다.

```tsx
    ) : route === "create.prompt-management" ? (
      <PromptBatchScreen onGoTo={goTo} />
```

- [ ] **Step 4: 화면을 구현한다**

`frontend/src/screens/promptBatchScreen.tsx`는 기존 셸과 토큰을 사용한다. 순서는 업로드 영역 → 워크플로우 선택 → 배치 진행 카운터 → 이미지별 프롬프트 쌍 목록 → 편집 가능한 기본 negative prompt다. 실행 전 확인 페이지를 추가하지 않는다.

주 액션 버튼의 상태는 정확히 다음과 같다.

```tsx
<button
  className="v3-primary-button"
  disabled={!selectedWorkflowId || imageItems.length === 0 || isGenerating}
  onClick={handleGenerate}
>
  {isGenerating ? "프롬프트 생성 중" : hasGeneratedItems ? "프롬프트 재생성" : "프롬프트 생성"}
</button>
```

각 항목은 썸네일, Asset ID, 업로드 해상도(`imageWidth × imageHeight`), Positive Prompt 편집 textarea, 개별 재시도 버튼, Grok 상태, 마지막 오류를 표시한다.

```tsx
{imageItems.map((item) => (
  <li key={item.draftId} className="v3-prompt-batch-row">
    <img className="v3-prompt-batch-thumb" src={item.thumbnailUrl} alt={item.assetId} />
    <div className="v3-prompt-batch-meta">
      <span className="v3-prompt-batch-asset">{item.assetId}</span>
      <span className="v3-prompt-batch-size">{item.imageWidth} × {item.imageHeight}</span>
      <span className={`v3-status-chip v3-status-${item.status.toLowerCase()}`}>{item.status}</span>
    </div>
    <textarea
      className="v3-prompt-batch-input"
      value={item.positivePrompt ?? ""}
      onChange={(event) => handleEdit(item.draftId, event.target.value)}
      onBlur={() => updatePromptDraft(item.draftId, { positivePrompt: item.positivePrompt ?? "", negativePrompt: item.negativePrompt ?? "", requestedFrames: item.requestedFrames })}
    />
    {item.failureMessage ? <p className="v3-prompt-batch-error">{item.failureMessage}</p> : null}
    <button className="v3-secondary-button" onClick={() => regeneratePromptDraft(item.draftId)}>재시도</button>
  </li>
))}
```

`frontend/src/api/client.ts`에 다섯 메서드를 추가한다. 반환 타입은 Task 4의 `_batch_payload()` 키와 1:1로 맞춘다.

```ts
export type PromptDraftItem = {
  draftId: string;
  assetId: string;
  slotIndex: number;
  status: "WAITING" | "IN_PROGRESS" | "COMPLETED" | "MANUAL_REQUIRED" | "FAILED";
  storedStatus: string;
  positivePrompt: string | null;
  negativePrompt: string | null;
  requestedFrames: number;
  failureMessage: string | null;
  warnings: string[];
  imageWidth: number;
  imageHeight: number;
  thumbnailUrl: string;
};
```

`frontend/src/styles.css`에는 위에서 쓴 클래스(`v3-prompt-batch-row`, `v3-prompt-batch-thumb`, `v3-prompt-batch-meta`, `v3-prompt-batch-asset`, `v3-prompt-batch-size`, `v3-prompt-batch-input`, `v3-prompt-batch-error`, `v3-status-chip`)만 기존 토큰 변수를 사용해 추가한다. 새 색상 값을 하드코딩하지 않는다.

- [ ] **Step 5: 빌드와 계약 테스트를 실행한다**

Run: `npm run build && python3 -m pytest backend/tests/test_frontend_prompt_management_contract.py -q`

Expected: 빌드 성공, 테스트 5개 PASS.

- [ ] **Step 6: 커밋한다**

```bash
git add frontend/src/screens/promptBatchScreen.tsx frontend/src/router.ts frontend/src/components/AppShell.tsx frontend/src/StudioShell.tsx frontend/src/helpers/navigation.ts frontend/src/api/client.ts frontend/src/styles.css backend/tests/test_frontend_prompt_management_contract.py
git commit -m "feat: add batch prompt generation management screen"
```

---

## Task 7: RunPod Request Management 화면

**Files:**
- Create: `frontend/src/screens/runpodRequestScreen.tsx`
- Modify: `frontend/src/StudioShell.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/styles.css`
- Create: `backend/tests/test_frontend_runpod_request_contract.py`

**Interfaces:**
- Consumes: Task 5의 `POST /api/jobs/queue`, `GET /api/jobs/queue-summary`, Task 6에서 등록한 라우트 키 `create.runpod-requests`와 메뉴 key `runpodRequests`.
- Produces: 컴포넌트 `RunpodRequestScreen`, 클라이언트 메서드 `listRunpodCandidates`, `enqueueRunpodTasks`, `getRunpodQueueSummary`.

- [ ] **Step 1: 실패하는 소스 계약 테스트를 작성한다**

`backend/tests/test_frontend_runpod_request_contract.py`:

```python
from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_screen_is_rendered_for_its_route():
    shell = _read("frontend/src/StudioShell.tsx")
    assert 'route === "create.runpod-requests"' in shell
    assert "RunpodRequestScreen" in shell


def test_screen_exposes_fixed_frame_options_and_batch_selection():
    source = _read("frontend/src/screens/runpodRequestScreen.tsx")
    assert "49" in source and "81" in source and "161" in source
    assert "전체 선택" in source
    assert "RunPod에 일괄 요청" in source
    assert "16 FPS" in source


def test_dashboard_shows_every_display_bucket():
    source = _read("frontend/src/screens/runpodRequestScreen.tsx")
    for bucket in ("REQUEST_WAITING", "RUNPOD_QUEUE", "RUNPOD_IN_PROGRESS", "COMPLETED", "FAILED"):
        assert bucket in source


def test_submit_keeps_page_and_shows_non_blocking_notice():
    source = _read("frontend/src/screens/runpodRequestScreen.tsx")
    assert "onNavigate(\"review.history\")" not in source
    assert "queuedNotice" in source
```

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_frontend_runpod_request_contract.py -q`

Expected: `FileNotFoundError`로 FAIL.

- [ ] **Step 3: 후보 목록 API를 추가한다**

`backend/app/api/v1/prompts.py`에 요청 후보 조회를 추가한다. 조건은 "positive prompt가 비어 있지 않고, 해당 이미지에 대해 활성 또는 완료된 작업이 아직 없는 드래프트"다.

```python
@router.get("/drafts/runpod-candidates")
def runpod_candidates(_: CurrentUser = Depends(require_permission("jobs:run")), db: Session = Depends(get_db)):
    return list_runpod_candidates(db)
```

`prompt_batch_service.list_runpod_candidates(session)`는 `WorkflowTask.prompt_draft_id`가 이미 존재하는 드래프트를 제외한다.

- [ ] **Step 4: 화면을 구현한다**

각 행은 입력 썸네일, 최종 positive/negative 프롬프트, 워크플로우 표시 이름, 해상도, 길이 선택(`49` / `81` / `161`), 고정 `16 FPS` 표기, 자동 seed 표기를 보여준다. 헤더 대시보드는 다섯 분류 카운트를 `GET /api/jobs/queue-summary`에서 가져와 표시한다. 제출은 현재 페이지를 유지하고 큐에 들어간 건수를 비차단 알림으로 보여준다.

```tsx
const [queuedNotice, setQueuedNotice] = useState<string | null>(null);

async function handleSubmit() {
  const result = await enqueueRunpodTasks(selectedDraftIds);
  setQueuedNotice(`${result.queued}건을 RunPod 요청 대기열에 등록했습니다.`);
  await refreshCandidates();
  await refreshSummary();
}
```

```tsx
<button className="v3-primary-button" disabled={selectedDraftIds.length === 0} onClick={handleSubmit}>
  RunPod에 일괄 요청
</button>
```

- [ ] **Step 5: 빌드와 계약 테스트를 실행한다**

Run: `npm run build && python3 -m pytest backend/tests/test_frontend_runpod_request_contract.py -q`

Expected: 빌드 성공, 테스트 4개 PASS.

- [ ] **Step 6: 커밋한다**

```bash
git add frontend/src/screens/runpodRequestScreen.tsx frontend/src/StudioShell.tsx frontend/src/api/client.ts frontend/src/styles.css backend/app/api/v1/prompts.py backend/app/services/prompt_batch_service.py backend/tests/test_frontend_runpod_request_contract.py
git commit -m "feat: add queued RunPod request management screen"
```

---

## Task 8: Task History를 프롬프트/RunPod 탭으로 분리

**Files:**
- Modify: `backend/app/api/v1/history.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Modify: `backend/app/services/prompt_batch_service.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/reviewScreens.tsx`
- Modify: `frontend/src/styles.css`
- Create: `backend/tests/test_history_tabs.py`

**Interfaces:**
- Consumes: Task 3의 `runpod_display_status`, Task 4의 `PromptGenerationAttempt`.
- Produces:
  - `GET /api/history/prompts?page=1&pageSize=20`
  - `GET /api/history/runpod?page=1&pageSize=20`
  - 두 엔드포인트 모두 `pageSize`를 항상 20으로 강제한다.
  - 기존 `GET /api/history`는 그대로 유지한다.

- [ ] **Step 1: 실패하는 DTO 테스트를 작성한다**

`backend/tests/test_history_tabs.py`:

```python
from __future__ import annotations


def test_prompt_history_returns_grok_telemetry(api_client, prompt_history_seed):
    body = api_client.get("/api/history/prompts?page=1&pageSize=20").json()

    assert body["pageSize"] == 20
    item = body["items"][0]
    assert {"grokEndpoint", "grokModel", "latencyMs", "inputTokens", "outputTokens"} <= set(item.keys())


def test_prompt_history_keeps_null_prompt_for_failed_attempt(api_client, prompt_history_seed):
    items = api_client.get("/api/history/prompts?page=1&pageSize=20").json()["items"]
    failed = [item for item in items if item["status"] == "FAILED"]

    assert failed
    assert all(item["positivePrompt"] is None for item in failed)


def test_runpod_history_returns_preview_and_response_columns(api_client, runpod_history_seed):
    item = api_client.get("/api/history/runpod?page=1&pageSize=20").json()["items"][0]

    assert {"inputPreview", "outputPreview", "filename", "delaySeconds", "executionSeconds", "runpodJobId"} <= set(item.keys())
    assert item["runpodDisplayStatus"] in {"REQUEST_WAITING", "RUNPOD_QUEUE", "RUNPOD_IN_PROGRESS", "COMPLETED", "FAILED"}


def test_page_size_is_forced_to_twenty(api_client, runpod_history_seed):
    body = api_client.get("/api/history/runpod?page=1&pageSize=200").json()
    assert body["pageSize"] == 20
```

`prompt_history_seed`와 `runpod_history_seed` 픽스처는 `backend/tests/conftest.py`에 추가한다. 각각 성공 1건·실패 1건의 드래프트+시도, 완료 1건의 `WorkflowTask`를 만든다.

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_history_tabs.py -q`

Expected: 404 응답으로 FAIL.

- [ ] **Step 3: 백엔드 DTO와 라우트를 추가한다**

```python
HISTORY_PAGE_SIZE = 20


@router.get("/prompts")
def prompt_history(page: int = 1, pageSize: int = HISTORY_PAGE_SIZE, _: CurrentUser = Depends(require_permission("history:read")), db: Session = Depends(get_db)):
    # 두 이력 탭은 항상 20행 페이지네이션을 쓴다.
    return prompt_history_page(db, page=max(1, page), page_size=HISTORY_PAGE_SIZE)


@router.get("/runpod")
def runpod_history(page: int = 1, pageSize: int = HISTORY_PAGE_SIZE, _: CurrentUser = Depends(require_permission("history:read")), db: Session = Depends(get_db)):
    return runpod_history_page(db, page=max(1, page), page_size=HISTORY_PAGE_SIZE)
```

Prompt History 항목 키 순서: `no`, `user`, `createdAtKst`, `assetId`, `thumbnailUrl`, `positivePrompt`, `status`, `grokEndpoint`, `grokModel`, `latencyMs`, `inputTokens`, `outputTokens`. RunPod History 항목 키 순서: `no`, `user`, `createdAtKst`, `workflowName`, `promptDraftId`, `runpodDisplayStatus`, `inputPreview`, `outputPreview`, `filename`, `delaySeconds`, `executionSeconds`, `runpodJobId`.

- [ ] **Step 4: 탭 UI를 구현한다**

`frontend/src/screens/reviewScreens.tsx`에 Prompt History / RunPod History 탭을 추가한다. 컬럼 순서는 위 키 순서를 그대로 따른다. 미리보기는 모달로 열고, 일괄 다운로드/삭제 액션은 RunPod 탭에만 남긴다.

- [ ] **Step 5: 검증한다**

Run: `python3 -m pytest backend/tests/test_history_tabs.py -q && npm run build`

Expected: PASS.

- [ ] **Step 6: 커밋한다**

```bash
git add backend/app/api/v1/history.py backend/app/services/task_tracking_service.py backend/app/services/prompt_batch_service.py frontend/src/api/client.ts frontend/src/screens/reviewScreens.tsx frontend/src/styles.css backend/tests/conftest.py backend/tests/test_history_tabs.py
git commit -m "feat: split prompt and RunPod task history"
```

---

## Task 9: 관리자 지시문 UX, 운영 문서, 전체 검증

**Files:**
- Modify: `frontend/src/screens/adminScreens.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/dobedub-studio-user-manual.md`
- Modify: `backend/tests/test_admin_workflow_id.py`
- Modify: `backend/tests/test_frontend_submission_flow.py`

**Interfaces:**
- Consumes: Task 1의 워크플로우 스코프 지시문 API, Task 5의 큐 요약 API.
- Produces: 관리자 화면의 `selectedInstructionWorkflowId` 상태와 `resolveWorkflowInstructionSet` 클라이언트 메서드.

- [ ] **Step 1: 회귀 테스트를 작성한다**

`backend/tests/test_admin_workflow_id.py`에 추가한다.

```python
def test_admin_instruction_screen_selects_workflow_from_left_panel():
    source = Path("frontend/src/screens/adminScreens.tsx").read_text(encoding="utf-8")
    assert "selectedInstructionWorkflowId" in source
    assert "resolveWorkflowInstructionSet" in source
    # 브라우저 기본 대화상자 대신 v4 중앙 다이얼로그를 쓴다.
    assert "window.alert(" not in source


def test_instruction_role_violation_uses_application_dialog():
    source = Path("frontend/src/screens/adminScreens.tsx").read_text(encoding="utf-8")
    assert "CORE 역할은 워크플로우당 1개만" in source
```

`backend/tests/test_frontend_submission_flow.py`에 추가한다.

```python
def test_submission_persists_pair_and_does_not_navigate_to_history():
    # 큐 등록 후에도 사용자는 요청 화면에 남는다.
    source = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")
    assert 'onNavigate("review.history")' not in source
    assert "queuedNotice" in source
```

- [ ] **Step 2: 테스트를 실행해 실패를 확인한다**

Run: `python3 -m pytest backend/tests/test_admin_workflow_id.py backend/tests/test_frontend_submission_flow.py -q`

Expected: 새 assertion에서 FAIL.

- [ ] **Step 3: 관리자 화면과 문서를 구현한다**

`adminScreens.tsx`의 좌측 지시문 영역에 선택된 워크플로우를 표시하고, 생성·삭제·역할 위반 시 v4 중앙 애플리케이션 다이얼로그를 띄운다. `window.alert` / `window.confirm`을 쓰지 않는다.

`.env.example`에 결정 1을 명시한다.

```bash
# 큐 디스패처는 dry-run 시뮬레이션 분기가 없다. 로컬에서 RunPod 요청 흐름을
# 확인하려면 실제 키와 함께 0으로 두어야 한다.
RUNPOD_DRY_RUN=0
```

`README.md`와 `docs/dobedub-studio-user-manual.md`에 다음을 추가한다: 두 개의 새 Generate 화면, Grok 진행 상태의 의미, 큐 워커 동작(브라우저를 닫아도 제출된 작업은 취소되지 않음), 이력 탭 분리, 저장 상태와 표시 상태가 다르다는 점, 그리고 표시 상태는 `runpod_display_status()`가 유일하게 만든다는 점.

- [ ] **Step 4: 전체 검증을 실행한다**

Run: `bash scripts/verify.sh`

Expected: 컴파일, pytest 전체, 프런트 빌드, whitespace 검사 모두 통과.

- [ ] **Step 5: 커밋한다**

```bash
git add frontend/src/screens/adminScreens.tsx frontend/src/api/client.ts .env.example README.md docs/dobedub-studio-user-manual.md backend/tests/test_admin_workflow_id.py backend/tests/test_frontend_submission_flow.py
git commit -m "docs: document durable Grok and RunPod queue workflow"
```

---

## Self-Review

**스펙 커버리지**
- 워크플로우 스코프 JSON 지시문 관리(스펙 §4.3, §5.1): Task 1, Task 9.
- 이미지별 Grok 프롬프트 생성과 텔레메트리(스펙 §5.1, §5.3): Task 4.
- 자산 기반 이미지 전달과 키 미노출(스펙 §5.1): Task 4 Step 4의 서비스 docstring과 구현.
- frames 49/81/161, FPS 16, 자동 seed 주입(스펙 §6.2): Task 5 Step 3의 `_build_task_payload`, Task 7의 길이 선택.
- 해상도(스펙 §6.1): **의도적으로 대체함.** 업로드 값 그대로 전달하며, 이는 `validate_segment_resolution()`의 현재 구현과 일치한다. Global Constraints에 명시했다.
- Task 메타데이터·이력 표시(스펙 §7 순서 6): Task 8.
- 실행 전 별도 확인 화면 없음(스펙 필수 시나리오 8): Task 6 Step 4, Task 6 계약 테스트.
- Grok 실패 시 편집 중 내용 보존과 재시도(스펙 필수 시나리오 6): Task 4의 실패 시 `positive_prompt` NULL 유지 + 개별 재시도, Task 6의 재시도 버튼.

**결정 반영 확인**
- 결정 1: Task 5에 dry-run 분기가 없고, `execution_mode="runpod"` 고정, 테스트는 `dispatch_runtime` 픽스처로 전송만 교체. `.env.example`에 `RUNPOD_DRY_RUN=0` 명시(Task 9).
- 결정 2: Task 0에서 pytest 도입, `pythonpath = .`로 기존 임포트 유지, 기존 unittest 파일 무수정.
- 결정 3: Task 3이 파생 계층을 만들고, Task 5는 원시 상태를 그대로 저장하며(`test_reconcile_stores_raw_remote_status`), `ACTIVE_TASK_STATUSES`/`ACTIVE_STATES`/`db_adapter`는 변경하지 않는다.

**타입·이름 일관성**
- `requested_frames`(DB) ↔ `requestedFrames`(API/프런트)로 전 Task 통일. `requested_length`는 쓰지 않는다.
- `PENDING_SUBMIT_STATUS`는 Task 3에서 정의하고 Task 5가 임포트한다.
- 노드 config 키는 `frames`/`fps`/`width`/`height`로 전 Task 통일. `length`는 `config_json` 스냅샷에도 쓰지 않는다.
- `runpod_display_status` / `runpodDisplayStatus` / `RUNPOD_DISPLAY_STATUSES` 철자를 Task 3·5·7·8에서 동일하게 사용한다.
- `prompt_draft_display_status`(드래프트)와 `runpod_display_status`(작업)는 다른 함수다. 혼동하지 말 것.

**데이터 안전성**
- Task 2 마이그레이션은 신규 테이블·nullable 컬럼·인덱스만 만들고 모든 생성에 존재 검사를 건다. 기존 `workflow_tasks`, `task_prompts`, `assets`, `image_prompt_drafts` 행을 삭제·개명·재작성·백필하지 않는다.
- Task 1의 지시문 1.0→2.0 승격은 기존 문서 배열을 그대로 옮겨 담고 내용을 버리지 않는다.

**이번 릴리스에서 제외**
- 멀티 키프레임 요청 그룹핑, WAN 종횡비 정규화, 배포, Git 동기화.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-01-batch-grok-runpod-execution-plan.md`.

Two execution options:

1. **Subagent-Driven (recommended)**: Task마다 새 서브에이전트를 띄우고 각 Task 종료 시점에 리뷰한다.
2. **Inline Execution**: 이 세션에서 순서대로 실행하고 Task 0·2·3·5·7 종료 시점에 체크포인트를 둔다.

Task 6과 Task 7은 `StudioShell.tsx`, `api/client.ts`, `styles.css`를 함께 수정하므로 **병렬로 실행하지 않는다.**
