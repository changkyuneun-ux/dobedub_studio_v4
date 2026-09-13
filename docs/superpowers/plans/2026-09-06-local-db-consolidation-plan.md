# Local DB Canonicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로컬 서버가 `data/dobedub-studio.db` 하나만 사용하게 하고, 실수로 `data/studio.db`에 연결되는 경로를 차단한다.

**Architecture:** 현재 실제 로컬 데이터는 `data/dobedub-studio.db`에 있으며 `data/studio.db`는 스키마만 있고 업무 데이터가 없다. 따라서 데이터를 옮기지 않고 `dobedub-studio.db`를 canonical 로컬 DB로 확정한다. 로컬 실행 스크립트는 `DATABASE_URL` 미지정 시 `sqlite:///./data/dobedub-studio.db`를 사용하고, `sqlite:///./data/studio.db`가 들어오면 시작 전에 실패시킨다.

**Tech Stack:** SQLite, Alembic, FastAPI, npm local scripts, pytest.

**Spec:** 사용자 요청: "data/dobedub-studio.db만 참조하고 data/studio.db 참조는 차단해도 문제 없으면 로컬에서는 data/dobedub-studio.db 연결만 이용"

## Global Constraints

- 운영 RDS/ECS DB는 건드리지 않는다.
- 로컬 canonical DB는 `data/dobedub-studio.db`다.
- `data/studio.db`는 로컬 서버 실행 DB로 사용하지 않는다.
- DB 파일은 Git에 커밋하지 않는다.
- 스크립트/테스트/문서 변경만 커밋 대상이다.

---

### Task 1: 현재 DB 상태를 확인한다

**Files:**
- Read: `data/studio.db`
- Read: `data/dobedub-studio.db`

**Interfaces:**
- Consumes: 로컬 SQLite DB 파일 2개
- Produces: canonical 결정 근거

- [ ] **Step 1: 두 DB의 핵심 카운트를 확인한다**

```bash
sqlite3 -header -column data/studio.db "
SELECT 'studio.db' AS db, version_num FROM alembic_version;
SELECT 'workflow_tasks' AS table_name, COUNT(*) AS cnt FROM workflow_tasks
UNION ALL SELECT 'image_prompt_drafts', COUNT(*) FROM image_prompt_drafts
UNION ALL SELECT 'batch_jobs', COUNT(*) FROM batch_jobs
UNION ALL SELECT 'assets', COUNT(*) FROM assets
UNION ALL SELECT 'users', COUNT(*) FROM users;
"

sqlite3 -header -column data/dobedub-studio.db "
SELECT 'dobedub-studio.db' AS db, version_num FROM alembic_version;
SELECT 'workflow_tasks' AS table_name, COUNT(*) AS cnt FROM workflow_tasks
UNION ALL SELECT 'image_prompt_drafts', COUNT(*) FROM image_prompt_drafts
UNION ALL SELECT 'batch_jobs', COUNT(*) FROM batch_jobs
UNION ALL SELECT 'assets', COUNT(*) FROM assets
UNION ALL SELECT 'users', COUNT(*) FROM users;
"
```

Expected current state:

```text
studio.db: workflow_tasks 0, image_prompt_drafts 0, batch_jobs 0, assets 0, users 0
dobedub-studio.db: workflow_tasks 86, image_prompt_drafts 83, batch_jobs 1, assets 293, users 8
```

### Task 2: `studio.db` 사용 차단 계약을 추가한다

**Files:**
- Modify: `backend/tests/test_local_server_contract.py`
- Modify: `scripts/run_local.py`

**Interfaces:**
- Consumes: canonical URL `sqlite:///./data/dobedub-studio.db`
- Produces: `ensure_local_database_url() -> str`

- [ ] **Step 1: 실패 테스트를 작성한다**

`backend/tests/test_local_server_contract.py`에 아래 테스트를 추가한다.

```python
def test_run_local_blocks_the_legacy_studio_sqlite_database(monkeypatch):
    run_local = _load_script("run_local")

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/studio.db")

    with pytest.raises(RuntimeError, match="data/studio.db"):
        run_local.ensure_local_database_url()
```

Run:

```bash
python3.12 -m pytest backend/tests/test_local_server_contract.py::test_run_local_blocks_the_legacy_studio_sqlite_database -q
```

Expected: `ensure_local_database_url`가 아직 없으므로 FAIL.

- [ ] **Step 2: 허용 테스트를 작성한다**

```python
def test_run_local_accepts_the_canonical_dobedub_sqlite_database(monkeypatch):
    run_local = _load_script("run_local")

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/dobedub-studio.db")

    assert run_local.ensure_local_database_url() == "sqlite:///./data/dobedub-studio.db"
```

- [ ] **Step 3: `scripts/run_local.py`에 검증 함수를 추가한다**

```python
CANONICAL_LOCAL_DATABASE_URL = "sqlite:///./data/dobedub-studio.db"
BLOCKED_LOCAL_DATABASE_PATH = PROJECT_ROOT / "data" / "studio.db"


def ensure_local_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL") or CANONICAL_LOCAL_DATABASE_URL
    sqlite_path = _sqlite_database_path(database_url)
    if sqlite_path and sqlite_path.resolve() == BLOCKED_LOCAL_DATABASE_PATH.resolve():
        raise RuntimeError(
            "로컬 서버는 data/studio.db를 사용하지 않습니다. "
            "DATABASE_URL을 비우거나 sqlite:///./data/dobedub-studio.db로 설정하세요."
        )
    os.environ.setdefault("DATABASE_URL", database_url)
    return database_url
```

- [ ] **Step 4: `.env` 로드 직후 DB URL을 검증한다**

```python
load_env_file(PROJECT_ROOT / ".env")
ensure_local_database_url()
prepare_local_database()
```

### Task 3: 잔여 `studio.db` 참조를 분류한다

**Files:**
- Read: `scripts/*.py`
- Read: `backend/*.py`
- Read: `.env.example`
- Read: `package.json`

**Interfaces:**
- Consumes: repo text search
- Produces: 운영/로컬 실행 참조와 smoke-test 전용 참조의 구분

- [ ] **Step 1: 검색한다**

```bash
rg -n "studio\\.db|dobedub-studio\\.db|DATABASE_URL" scripts backend .env .env.example package.json
```

Expected:

```text
backend/app/core/config.py: default sqlite:///./data/dobedub-studio.db
scripts/start_local.py: DEFAULT_DATABASE_URL sqlite:///./data/dobedub-studio.db
backend/tests/test_local_server_contract.py: expected sqlite:///./data/dobedub-studio.db
```

`scripts/*_smoke_check.py`의 임시 `studio.db`, `smoke.db`, `test.db`는 테스트 전용이므로 차단 대상이 아니다.

### Task 4: 검증한다

**Files:**
- Read: `scripts/run_local.py`
- Read: `backend/tests/test_local_server_contract.py`

**Interfaces:**
- Consumes: Task 2 구현
- Produces: 테스트/빌드 검증 결과

- [ ] **Step 1: 계약 테스트를 실행한다**

```bash
python3.12 -m pytest backend/tests/test_local_server_contract.py -q
```

Expected: PASS.

- [ ] **Step 2: 전체 테스트와 빌드를 실행한다**

```bash
python3.12 -m pytest -q
npm run build
git diff --check
```

Expected: 모두 exit code 0.

### Task 5: 운영 방식

**Files:**
- Read: `data/dobedub-studio.db`
- Ignore or archive manually: `data/studio.db`

**Interfaces:**
- Consumes: canonical 로컬 DB
- Produces: 일관된 로컬 실행 방식

- [ ] **Step 1: 평소 로컬 실행은 아래 명령만 사용한다**

```bash
npm run local:up
```

또는 foreground 실행:

```bash
python3.12 scripts/run_local.py
```

- [ ] **Step 2: 직접 DB URL을 지정해야 하면 canonical만 사용한다**

```bash
DATABASE_URL=sqlite:///./data/dobedub-studio.db python3.12 scripts/run_local.py
```

- [ ] **Step 3: `studio.db` 지정은 실패해야 한다**

```bash
DATABASE_URL=sqlite:///./data/studio.db python3.12 scripts/run_local.py
```

Expected:

```text
RuntimeError: 로컬 서버는 data/studio.db를 사용하지 않습니다.
```

## Rollback

로컬 실행에서 `studio.db` 사용을 다시 허용해야 한다면 `scripts/run_local.py`의 `ensure_local_database_url()` 호출과 관련 테스트 2개를 되돌린다. DB 파일 자체는 이 계획에서 수정하지 않으므로 데이터 롤백은 필요 없다.

## Self-Review

- Spec coverage: `dobedub-studio.db` canonical 유지, `studio.db` 차단, 로컬 실행 명령 검증을 포함했다.
- Placeholder scan: 실행 명령과 기대 결과를 모두 명시했다.
- Type consistency: canonical URL은 전 구간 `sqlite:///./data/dobedub-studio.db`로 통일했다.
