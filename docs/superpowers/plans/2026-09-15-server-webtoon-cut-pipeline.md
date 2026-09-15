# Server Webtoon Cut Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DOBEDUB STUDIO의 이미지 컷 관리를 서버 업로드/S3 보관/서버 Python 컷분리/이력 조회/선택 컷 I2V 파이프라인 연결 방식으로 전환한다.

**Architecture:** 사용자는 PDF, ZIP, 이미지 원본을 업로드하고 서버는 S3에 원본과 결과물을 저장한다. 서버 worker는 vendored `batch_split.py`/`grid_split.py` 계열 Python 엔진과 Poppler/OpenCV로 컷을 생성한다. 생성된 컷은 `webtoon_cut_image` asset으로 등록되어 컷 분할 이력에서 조회·필터·다운로드할 수 있고, 선택 컷은 재업로드 없이 assetId로 Grok 프롬프트 생성 또는 Batch 처리에 연결한다.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, S3 storage backend, Python 3, OpenCV headless, numpy, Poppler `pdfinfo`/`pdftoppm`, React/TypeScript, existing `Asset`, `PromptGenerationBatch`, `BatchJob`, `/api/files/{assetId}` streaming.

**Spec:** This plan supersedes the local-only storage clauses in `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md`. Keep the cut naming/output quality requirements from that spec, but replace “업로드/다운로드 없음” with server upload/download and S3 retention policies in this plan.

## Global Constraints

- 신규 웹툰 컷 분리 원본과 결과는 S3에 저장한다. 기존 NFS/EFS 자산은 과거 파일 호환용으로 유지한다.
- 서버는 사용자 업로드 원본을 처리하므로 기존 “ECS/S3/RDS에 저장하지 않음” 요구는 폐기한다.
- 원본, 렌더 페이지, 컷 PNG, debug PNG, manifest, summary, 다운로드 ZIP은 서로 다른 asset type과 보존 정책을 가진다.
- 컷 이미지는 모두 PNG다.
- PDF는 Poppler `pdftoppm -r 300 -png` 기준으로 렌더링한다.
- Python 엔진은 `/Users/changkyuneun/webtoon Pannel/batch_split.py`와 `/Users/changkyuneun/webtoon Pannel/files/grid_split.py`를 기준으로 vendoring한다.
- `fullpage` 단독은 검수 대상이 아니라 정상 출력 플래그다.
- 컷 출력 naming은 기존 정책을 유지한다: PDF는 `<sourceStem>/PPP-CC.png`, 이미지는 `<sourceStem>/<sourceStem>-CC.png`, ZIP은 `<zipStem>_cuts/<zip internal relative dir>/<sourceStem>/...`.
- 파일명은 화면 표시용 원본명과 S3 storage key용 안전명을 분리한다. DB와 manifest에는 둘 다 기록한다.
- S3 object는 public 금지다. 보기/다운로드는 기존 `/api/files/{assetId}?download=0|1` 인증 프록시를 기본으로 한다.
- 선택 컷을 Grok/Batch로 보낼 때 파일 재업로드는 금지한다. 이미 생성된 `webtoon_cut_image` assetId만 연결한다.
- Grok/Batch 연결 액션은 선택 컷 `assetId`와 정렬 순서를 다음 화면 입력으로 전달하는 역할까지만 수행한다. Grok 프롬프트 옵션, Batch workflow/quality/length 선택은 각 기존 화면에서 처리한다.
- 기존 `input_image`, Batch, Grok, RunPod 경로와 충돌하지 않도록 웹툰 전용 API prefix와 asset type을 사용한다.
- 같은 사용자는 기본적으로 active webtoon cut job 1개만 실행한다. 추가 요청은 409로 거부하거나 명시적 큐 정책을 별도 도입할 때까지 보류한다.
- 작업 요청 후 active job이 있으면 UI의 `작업 요청` 버튼은 `작업 취소`로 전환한다. 취소 요청은 `cancel_requested` 상태를 만들고 worker는 현재 처리 단위 완료 후 중단한다. 취소 시점까지 생성된 컷, manifest, summary는 보존한다.
- 작업 삭제 시 원본, 렌더, 컷, debug, manifest, summary, download ZIP, DB rows를 일관되게 정리한다. 이미 I2V에 사용된 컷은 삭제 제한 또는 강한 경고를 적용한다.
- 웹툰 컷 분리 worker는 기존 `main.py`의 RunPod/Grok/Batch `monitor_loop` 안에서 장시간 실행하면 안 된다. 별도 `asyncio.create_task` 워커 루프 또는 별도 worker process로 분리한다.
- PDF 처리는 전체 문서를 한 번에 렌더링하지 않는다. 페이지 단위 또는 작은 chunk 단위로 `render → split → S3 upload → local temp cleanup`을 수행한다.
- `webtoon_cut_image` asset은 I2V/RunPod 입력으로 사용할 때 원본 `Asset.storage_key`를 배치 입력 경로로 변경하면 안 된다.
- 웹툰 관련 asset 등록 시 `metadata_json.createdBy`를 반드시 기록한다. `/api/files/{assetId}` 권한 검사가 이 값을 사용한다.

---

## File Structure

### Backend

- Create `backend/app/api/v1/webtoon_cuts.py`
  - Webtoon cut upload, job, history, output selection, download endpoints.
- Create `backend/app/services/webtoon_cut_service.py`
  - Job creation, ownership checks, state transition, output registration, selection bridge.
- Create `backend/app/services/webtoon_cut_worker.py`
  - Server-side processing loop entrypoint. Processes one job at a time per user/claim.
- Create `backend/app/services/webtoon_cut_worker_runtime.py`
  - Independent background worker loop. Must not block the existing RunPod/Grok/Batch monitor loop.
- Create `backend/app/services/webtoon_panel_engine/`
  - Vendored Python engine based on `batch_split.py` and `grid_split.py`.
- Create `backend/app/services/webtoon_cut_naming.py`
  - NFC normalization, display name preservation, safe storage segment, output relative path policy.
- Create `backend/app/services/webtoon_cut_storage.py`
  - S3 key policy, asset registration helpers, manifest/summary/debug/cut asset creation.
- Modify `backend/app/db/models.py`
  - Add `WebtoonCutJob`, `WebtoonCutSource`, `WebtoonCutUnit`, `WebtoonCutOutput`, `WebtoonCutDownload`.
- Create Alembic migration under `backend/alembic/versions/`
  - Adds new tables and indexes.
- Modify `backend/app/main.py`
  - Register `webtoon_cuts_router`, start/stop a separate webtoon cut worker task.
- Modify `backend/app/services/studio_api_service.py`
  - Add a RunPod input scoping guard so `webtoon_cut_image` assets are copied for dispatch without mutating their canonical `storage_key`.
- Modify `backend/requirements.txt`
  - Add Python dependencies for server engine.
- Modify Docker/ECS build files
  - Install Poppler utilities and native image libs required by OpenCV.
- Tests:
  - `backend/tests/test_webtoon_cut_naming.py`
  - `backend/tests/test_webtoon_cut_storage_policy.py`
  - `backend/tests/test_webtoon_cut_api_contract.py`
  - `backend/tests/test_webtoon_cut_i2v_bridge.py`
  - `backend/tests/test_webtoon_cut_worker_contract.py`
  - `backend/tests/test_webtoon_cut_runpod_scope_guard.py`

### Frontend

- Replace current single `webtoonCuts` route with:
  - `imageCuts.split`
  - `imageCuts.history`
  - `imageCuts.historyDetail`
- Create `frontend/src/screens/imageCutSplitScreen.tsx`
  - Upload, job request, progress.
- Create `frontend/src/screens/imageCutHistoryScreen.tsx`
  - Job list, filters, status.
- Create `frontend/src/screens/imageCutDetailScreen.tsx`
  - Cut list/grid toggle, thumbnail preview, debug preview, selection, download, Grok/Batch handoff actions.
- Create `frontend/src/features/image-cuts/types.ts`
- Create `frontend/src/features/image-cuts/api.ts`
- Create `frontend/src/features/image-cuts/selection.ts`
- Modify `frontend/src/StudioShell.tsx`, `frontend/src/router.ts`, `frontend/src/helpers/navigation.ts`
  - Sidebar and route integration.
- Tests:
  - `frontend/src/features/image-cuts/selection.test.ts`
  - `frontend/src/features/image-cuts/api.test.ts`
  - `frontend/src/screens/imageCutHistoryScreen.test.tsx`

---

## Data Model

### Asset types

Use existing `assets` table, but register new values:

```text
webtoon_source_original
webtoon_source_extracted
webtoon_rendered_page
webtoon_cut_image
webtoon_debug_overlay
webtoon_manifest
webtoon_summary
webtoon_download_zip
```

Guardrail: do not reuse `input_image` for raw webtoon cuts. A selected cut becomes an I2V input by reference, not by copying into `input_image`.

### New tables

```python
class WebtoonCutJob(Base):
    __tablename__ = "webtoon_cut_jobs"
    id = mapped_column(String(64), primary_key=True)
    created_by = mapped_column(String(191), ForeignKey("users.id"), nullable=False, index=True)
    status = mapped_column(String(64), nullable=False, index=True)
    source_asset_id = mapped_column(String(64), ForeignKey("assets.id"), nullable=False, index=True)
    source_file_name = mapped_column(String(512), nullable=False)
    input_kind = mapped_column(String(32), nullable=False)
    engine_version = mapped_column(String(64), nullable=False)
    policy_version = mapped_column(String(64), nullable=False)
    total_units = mapped_column(Integer, nullable=False, default=0)
    completed_units = mapped_column(Integer, nullable=False, default=0)
    failed_units = mapped_column(Integer, nullable=False, default=0)
    review_required_units = mapped_column(Integer, nullable=False, default=0)
    generated_cut_count = mapped_column(Integer, nullable=False, default=0)
    manifest_asset_id = mapped_column(String(64), ForeignKey("assets.id"), nullable=True)
    summary_asset_id = mapped_column(String(64), ForeignKey("assets.id"), nullable=True)
    storage_prefix = mapped_column(String(1024), nullable=False)
    options_json = mapped_column(JSON, nullable=False, default=dict)
    error_code = mapped_column(String(128), nullable=True)
    error_message = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime, nullable=False)
    started_at = mapped_column(DateTime, nullable=True)
    completed_at = mapped_column(DateTime, nullable=True)
    deleted_at = mapped_column(DateTime, nullable=True, index=True)
```

```python
class WebtoonCutUnit(Base):
    __tablename__ = "webtoon_cut_units"
    id = mapped_column(String(64), primary_key=True)
    job_id = mapped_column(String(64), ForeignKey("webtoon_cut_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_path = mapped_column(String(1024), nullable=False)
    display_source_path = mapped_column(String(1024), nullable=False)
    source_kind = mapped_column(String(32), nullable=False)
    page_number = mapped_column(Integer, nullable=True)
    status = mapped_column(String(64), nullable=False, index=True)
    flags_json = mapped_column(JSON, nullable=False, default=list)
    output_count = mapped_column(Integer, nullable=False, default=0)
    error_code = mapped_column(String(128), nullable=True)
    error_message = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime, nullable=False)
    updated_at = mapped_column(DateTime, nullable=False)
```

```python
class WebtoonCutOutput(Base):
    __tablename__ = "webtoon_cut_outputs"
    id = mapped_column(String(64), primary_key=True)
    job_id = mapped_column(String(64), ForeignKey("webtoon_cut_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_id = mapped_column(String(64), ForeignKey("webtoon_cut_units.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = mapped_column(String(64), ForeignKey("assets.id"), nullable=False, unique=True)
    relative_path = mapped_column(String(1024), nullable=False)
    display_path = mapped_column(String(1024), nullable=False)
    page_number = mapped_column(Integer, nullable=True, index=True)
    cut_index = mapped_column(Integer, nullable=False)
    mode = mapped_column(String(64), nullable=False)
    x0 = mapped_column(Integer, nullable=True)
    y0 = mapped_column(Integer, nullable=True)
    x1 = mapped_column(Integer, nullable=True)
    y1 = mapped_column(Integer, nullable=True)
    width = mapped_column(Integer, nullable=False)
    height = mapped_column(Integer, nullable=False)
    flags_json = mapped_column(JSON, nullable=False, default=list)
    used_in_prompt_count = mapped_column(Integer, nullable=False, default=0)
    used_in_batch_count = mapped_column(Integer, nullable=False, default=0)
    created_at = mapped_column(DateTime, nullable=False)
```

Indexes:

```python
Index("ix_webtoon_cut_jobs_user_status_created", WebtoonCutJob.created_by, WebtoonCutJob.status, WebtoonCutJob.created_at)
Index("ix_webtoon_cut_units_job_page", WebtoonCutUnit.job_id, WebtoonCutUnit.page_number)
Index("ix_webtoon_cut_outputs_job_page_cut", WebtoonCutOutput.job_id, WebtoonCutOutput.page_number, WebtoonCutOutput.cut_index)
Index("ix_webtoon_cut_outputs_job_mode", WebtoonCutOutput.job_id, WebtoonCutOutput.mode)
```

Guardrails:

- Do not add local absolute path columns.
- Do not store raw base64 in DB.
- Store flags as JSON arrays, not delimited strings.
- Use `created_by` checks on every read/write/delete.

---

## S3 Key Policy

All keys use a job-scoped prefix:

```text
webtoon-cut/users/{userId}/jobs/{jobId}/
```

Subpaths:

```text
source/original/{sourceAssetId}/{safeFileName}
source/extracted/{safeZipPath}
rendered/{sourceStem}/pages/{PPP}.png
outputs/{sourceRelativeStem}/{outputFileName}.png
debug/{sourceRelativeStem}/{PPP or overlay}.png
metadata/manifest.json
metadata/summary.csv
downloads/webtoon-cut-{jobId}.zip
```

Naming functions:

```python
def normalize_display_name(value: str) -> str:
    return unicodedata.normalize("NFC", value or "").strip()

def safe_storage_segment(value: str, fallback: str = "item") -> str:
    normalized = normalize_display_name(value)
    cleaned = re.sub(r"[\\/\0\r\n\t]+", "_", normalized).strip(" ._")
    return cleaned[:180] or fallback

def pdf_cut_relative_path(source_path: str, page: int, cut_index: int) -> str:
    source_stem = safe_storage_segment(Path(source_path).stem)
    return f"{source_stem}/{page:03d}-{cut_index:02d}.png"

def image_cut_relative_path(source_path: str, cut_index: int) -> str:
    source_stem = safe_storage_segment(Path(source_path).stem)
    return f"{source_stem}/{source_stem}-{cut_index:02d}.png"
```

Guardrails:

- ZIP entries must reject absolute paths, `..`, symlinks, `__MACOSX`, `.DS_Store`, `._*`.
- If storage segment collisions occur, append `__2`, `__3`.
- Display filenames in UI must use `display_path`, not S3 key.
- Download filename must use RFC 5987 `filename*` to preserve Korean names.
- Never use existing `asset_storage.safe_filename()` for webtoon display names because it strips Korean into underscores.

---

## API Contract

### Upload

```http
POST /api/webtoon-cuts/uploads/presign
```

Request:

```json
{
  "fileName": "과학사_2권_내지_인쇄용_수정.pdf",
  "mimeType": "application/pdf",
  "sizeBytes": 59000000
}
```

Response:

```json
{
  "assetId": "asset_...",
  "uploadUrl": "https://s3-presigned...",
  "headers": { "Content-Type": "application/pdf" },
  "storageKey": "webtoon-cut/users/u/jobs/pending/asset.../source/original/...",
  "expiresAt": "2026-09-15T..."
}
```

```http
POST /api/webtoon-cuts/uploads/complete
```

Creates `assets.asset_type = webtoon_source_original`.

Guardrail: do not call existing `/api/uploads/complete` because that hardcodes `input_image` and requires request/batch scope.

### Jobs

```http
POST /api/webtoon-cuts/jobs
```

Request:

```json
{
  "sourceAssetId": "asset_...",
  "originalFileName": "과학사_2권_내지_인쇄용_수정.pdf",
  "options": {
    "deleteOriginalAfterCompletion": false
  }
}
```

Response:

```json
{
  "jobId": "wcut_...",
  "status": "PENDING",
  "detailUrl": "/api/webtoon-cuts/jobs/wcut_..."
}
```

```http
GET /api/webtoon-cuts/jobs
```

Filters: `status`, `inputKind`, `createdBy`, `dateFrom`, `dateTo`, `query`, `page`, `pageSize`.

```http
GET /api/webtoon-cuts/jobs/{jobId}
```

Returns job, counters, source metadata, summary asset, manifest asset.

```http
POST /api/webtoon-cuts/jobs/{jobId}/cancel
```

Sets cancel flag. Worker stops after current unit.

### Outputs

```http
GET /api/webtoon-cuts/jobs/{jobId}/outputs
```

Filters:

```text
pageFrom, pageTo, status, flags, usedState, createdBy, query, mode, viewMode, page, pageSize
```

Response item:

```json
{
  "outputId": "wcut_out_...",
  "assetId": "asset_...",
  "viewUrl": "/api/files/asset_...?download=0",
  "downloadUrl": "/api/files/asset_...?download=1",
  "displayPath": "과학사_2권/017-03.png",
  "pageNumber": 17,
  "cutIndex": 3,
  "width": 966,
  "height": 488,
  "mode": "grid",
  "flags": [],
  "usedInPromptCount": 0,
  "usedInBatchCount": 0,
  "i2vResultCount": 0,
  "createdBy": "user_..."
}
```

### Downloads

```http
POST /api/webtoon-cuts/jobs/{jobId}/downloads
```

Request:

```json
{
  "type": "selected",
  "outputIds": ["wcut_out_1", "wcut_out_2"]
}
```

For all:

```json
{ "type": "all" }
```

Guardrails:

- 500MB 이하: stream 가능.
- 500MB 초과: async ZIP asset `webtoon_download_zip`.
- Download ZIP retention: 24h.

### I2V Bridge

```http
POST /api/webtoon-cuts/jobs/{jobId}/outputs/grok-batch
```

Request:

```json
{
  "workflowId": "workflow_xxx",
  "outputIds": ["wcut_out_1", "wcut_out_2"],
  "excludeReviewRequired": true
}
```

Implementation calls `prompt_batch_service.create_prompt_generation_batch()` with:

```json
{
  "workflowId": "workflow_xxx",
  "items": [
    {
      "assetId": "asset_cut_1",
      "slotIndex": 1,
      "requestedFrames": 81,
      "sourceRelativePath": "과학사_2권/017-01.png",
      "requestItemId": "wcut_017_01"
    }
  ]
}
```

```http
POST /api/webtoon-cuts/jobs/{jobId}/outputs/batch-job
```

Request:

```json
{
  "workflowId": "workflow_xxx",
  "requestedFrames": 81,
  "resolutionTier": "sd",
  "negativePrompt": "",
  "outputIds": ["wcut_out_1", "wcut_out_2"],
  "pipeline": "direct"
}
```

Implementation calls `batch_job_service.create_batch_job()` with existing assetIds.

Guardrails:

- Only `webtoon_cut_image` outputs owned by the current user may be bridged.
- `missing_output`, `error` outputs are not selectable.
- If `excludeReviewRequired` is true, drop outputs with `review_required`, `thin`, `many`, or `review_continuous`.
- Preserve order by `(source path order, page_number nulls last, cut_index)`.
- Enforce limits:
  - Grok batch max 200 outputs per request.
  - Batch job max 500 outputs per request.
  - Larger selections require chunking UX, not silent partial processing.

---

## Python Engine and Dependencies

### Vendored engine

Create package:

```text
backend/app/services/webtoon_panel_engine/
├── __init__.py
├── batch_split.py
├── grid_split.py
├── engine.py
└── manifest_adapter.py
```

`engine.py` must expose:

```python
def split_pdf_to_directory(
    *,
    pdf_path: Path,
    output_dir: Path,
    source_relative_path: str,
    dpi: int = 300,
    pages: tuple[int, int] | None = None,
) -> EngineResult:
    ...
```

```python
def split_image_to_directory(
    *,
    image_path: Path,
    output_dir: Path,
    source_relative_path: str,
) -> EngineResult:
    ...
```

`EngineResult`:

```python
@dataclass
class EngineOutput:
    relative_path: str
    page_number: int | None
    cut_index: int
    width: int
    height: int
    mode: str
    flags: list[str]
    x0: int | None = None
    y0: int | None = None
    x1: int | None = None
    y1: int | None = None

@dataclass
class EngineUnit:
    source_path: str
    page_number: int | None
    status: str
    flags: list[str]
    outputs: list[EngineOutput]
    error_code: str | None = None
    error_message: str | None = None

@dataclass
class EngineResult:
    units: list[EngineUnit]
    summary_csv_path: Path
    manifest_json_path: Path
    debug_dir: Path
```

Dependencies:

```text
opencv-python-headless
numpy
Pillow
```

System packages:

```text
poppler-utils
libgl1
libglib2.0-0
```

Guardrails:

- Check `pdfinfo` and `pdftoppm` availability at startup/status.
- If Poppler missing, job fails fast with `engine_dependency_missing`.
- Do not write temp files inside the repository. Use `tempfile.TemporaryDirectory()`.
- Cleanup temp directory on success, failure, and cancellation.
- Do not keep rendered pages longer than the configured policy unless debug retention requires it.

---

## Tasks

### Task 1: Freeze server-side policy and retire local-only assumptions

**Files:**
- Modify: `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md`
- Create: `docs/superpowers/specs/2026-09-15-server-webtoon-cut-policy.md`
- Test: `backend/tests/test_frontend_webtoon_cut_contract.py`

**Interfaces:**
- Produces policy constants:
  - `WEBTOON_CUT_STORAGE_MODE = "server_s3"`
  - `WEBTOON_CUT_ENGINE_MODE = "server_python_poppler_opencv"`

- [ ] **Step 1: Add the policy spec**

Create `docs/superpowers/specs/2026-09-15-server-webtoon-cut-policy.md` containing:

```markdown
# Server Webtoon Cut Policy

- 원본은 서버에 업로드한다.
- 원본과 결과는 S3에 저장한다.
- 컷 분리는 서버 Python 엔진에서 실행한다.
- 보기와 다운로드는 인증된 `/api/files/{assetId}` 프록시를 사용한다.
- 선택 컷은 재업로드 없이 assetId로 Grok 또는 Batch에 연결한다.
```

- [ ] **Step 2: Mark the previous local-only spec as superseded**

At the top of `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md`, add:

```markdown
> Superseded for implementation by `2026-09-15-server-webtoon-cut-policy.md`.
> The previous local-only/no-upload clauses no longer apply to the server implementation.
```

- [ ] **Step 3: Update the frontend contract test**

Modify `backend/tests/test_frontend_webtoon_cut_contract.py` so the expected menu labels become:

```python
assert "이미지 컷 관리" in shell_source
assert "컷 분할 처리" in shell_source
assert "컷 분할 이력" in shell_source
```

- [ ] **Step 4: Run contract test**

Run:

```bash
python -m pytest backend/tests/test_frontend_webtoon_cut_contract.py -q
```

Expected: the updated assertions fail until routes are implemented.

### Task 2: Add database models and migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/20260915_0001_webtoon_cut_jobs.py`
- Test: `backend/tests/test_webtoon_cut_db_models.py`

**Interfaces:**
- Produces SQLAlchemy models:
  - `WebtoonCutJob`
  - `WebtoonCutUnit`
  - `WebtoonCutOutput`
  - `WebtoonCutDownload`

- [ ] **Step 1: Write model smoke test**

Create `backend/tests/test_webtoon_cut_db_models.py`:

```python
from backend.app.db.models import WebtoonCutJob, WebtoonCutOutput, WebtoonCutUnit


def test_webtoon_cut_models_have_expected_table_names():
    assert WebtoonCutJob.__tablename__ == "webtoon_cut_jobs"
    assert WebtoonCutUnit.__tablename__ == "webtoon_cut_units"
    assert WebtoonCutOutput.__tablename__ == "webtoon_cut_outputs"
```

- [ ] **Step 2: Add models**

Add the models described in the Data Model section to `backend/app/db/models.py`.

- [ ] **Step 3: Add migration**

Create Alembic migration with tables and indexes described above.

- [ ] **Step 4: Run model test**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_db_models.py -q
```

Expected: PASS.

### Task 3: Implement naming and storage guardrails

**Files:**
- Create: `backend/app/services/webtoon_cut_naming.py`
- Create: `backend/app/services/webtoon_cut_storage.py`
- Test: `backend/tests/test_webtoon_cut_naming.py`
- Test: `backend/tests/test_webtoon_cut_storage_policy.py`

**Interfaces:**
- Produces:
  - `normalize_display_name(value: str) -> str`
  - `safe_storage_segment(value: str, fallback: str = "item") -> str`
  - `pdf_cut_relative_path(source_path: str, page: int, cut_index: int) -> str`
  - `image_cut_relative_path(source_path: str, cut_index: int) -> str`
  - `webtoon_job_prefix(user_id: str, job_id: str) -> str`

- [ ] **Step 1: Write naming tests**

Create `backend/tests/test_webtoon_cut_naming.py`:

```python
from backend.app.services.webtoon_cut_naming import (
    image_cut_relative_path,
    normalize_display_name,
    pdf_cut_relative_path,
    safe_storage_segment,
)


def test_korean_name_is_preserved_for_display_normalization():
    assert normalize_display_name("과학사_2권.pdf") == "과학사_2권.pdf"


def test_pdf_cut_relative_path_uses_page_and_cut_sequence():
    assert pdf_cut_relative_path("과학사_2권_내지_인쇄용_수정.pdf", 17, 3).endswith("017-03.png")


def test_image_cut_relative_path_uses_source_stem():
    assert image_cut_relative_path("진실의 방_001_006.jpg", 5).endswith("진실의 방_001_006-05.png")


def test_storage_segment_rejects_path_traversal_characters():
    assert "/" not in safe_storage_segment("../bad/name.pdf")
```

- [ ] **Step 2: Implement naming module**

Create functions exactly as in the S3 Key Policy section.

- [ ] **Step 3: Write storage prefix test**

Create `backend/tests/test_webtoon_cut_storage_policy.py`:

```python
from backend.app.services.webtoon_cut_storage import webtoon_job_prefix


def test_webtoon_job_prefix_is_user_and_job_scoped():
    assert webtoon_job_prefix("user_1", "wcut_1") == "webtoon-cut/users/user_1/jobs/wcut_1/"
```

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_naming.py backend/tests/test_webtoon_cut_storage_policy.py -q
```

Expected: PASS.

### Task 4: Vendor Python engine and dependency checks

**Files:**
- Create: `backend/app/services/webtoon_panel_engine/__init__.py`
- Create: `backend/app/services/webtoon_panel_engine/grid_split.py`
- Create: `backend/app/services/webtoon_panel_engine/batch_split.py`
- Create: `backend/app/services/webtoon_panel_engine/engine.py`
- Modify: `backend/requirements.txt`
- Modify: Dockerfile/ECS build config
- Test: `backend/tests/test_webtoon_panel_engine_contract.py`

**Interfaces:**
- Consumes reference files:
  - `/Users/changkyuneun/webtoon Pannel/batch_split.py`
  - `/Users/changkyuneun/webtoon Pannel/files/grid_split.py`
- Produces:
  - `assert_engine_dependencies() -> None`
  - `split_pdf_to_directory(...) -> EngineResult`

- [ ] **Step 1: Write dependency contract test**

Create `backend/tests/test_webtoon_panel_engine_contract.py`:

```python
from backend.app.services.webtoon_panel_engine.engine import engine_version


def test_engine_version_is_stable_string():
    assert engine_version().startswith("batch-split-")
```

- [ ] **Step 2: Copy and adapt engine files**

Copy the reference files into `backend/app/services/webtoon_panel_engine/`. Change imports from `from grid_split import split_panels` to `from .grid_split import split_panels`.

- [ ] **Step 3: Add engine wrapper**

Create `engine.py` with:

```python
def engine_version() -> str:
    return "batch-split-2026-09-15"
```

Then add `assert_engine_dependencies()` that checks `pdfinfo`, `pdftoppm`, `cv2`, and `numpy`.

- [ ] **Step 4: Add dependencies**

Append to `backend/requirements.txt`:

```text
opencv-python-headless
numpy
Pillow
```

Add OS packages to Docker/ECS build:

```text
poppler-utils
libgl1
libglib2.0-0
```

- [ ] **Step 5: Run contract test**

Run:

```bash
python -m pytest backend/tests/test_webtoon_panel_engine_contract.py -q
```

Expected: PASS.

### Task 5: Implement upload API without colliding with existing input_image upload

**Files:**
- Create: `backend/app/api/v1/webtoon_cuts.py`
- Create: `backend/app/services/webtoon_cut_service.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_webtoon_cut_api_contract.py`

**Interfaces:**
- Produces:
  - `POST /api/webtoon-cuts/uploads/presign`
  - `POST /api/webtoon-cuts/uploads/complete`
  - `POST /api/webtoon-cuts/jobs`

- [ ] **Step 1: Write API contract test**

Create `backend/tests/test_webtoon_cut_api_contract.py`:

```python
def test_webtoon_upload_complete_uses_webtoon_asset_type(client, auth_headers, monkeypatch):
    # Use a mocked service result so this test validates API contract, not S3.
    expected = {"assetId": "asset_webtoon", "type": "webtoon_source_original"}
    monkeypatch.setattr(
        "backend.app.services.webtoon_cut_service.complete_source_upload",
        lambda payload, created_by: expected,
    )
    response = client.post(
        "/api/webtoon-cuts/uploads/complete",
        json={"assetId": "asset_webtoon", "storageKey": "webtoon-cut/users/u/source.pdf"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["type"] == "webtoon_source_original"
```

- [ ] **Step 2: Add router**

Create `backend/app/api/v1/webtoon_cuts.py` with endpoints under prefix `/webtoon-cuts`.

- [ ] **Step 3: Register router**

Modify `backend/app/main.py`:

```python
from backend.app.api.v1.webtoon_cuts import router as webtoon_cuts_router
```

and include it in `api_routers`.

- [ ] **Step 4: Implement service stubs with strict asset type**

`complete_source_upload()` must register `Asset.asset_type = "webtoon_source_original"`, never `input_image`.

- [ ] **Step 5: Enforce ownership metadata on every webtoon asset**

Every asset created by webtoon cut services must include:

```python
asset.metadata_json = {
    **(asset.metadata_json or {}),
    "createdBy": created_by,
    "webtoonCutJobId": job_id,
}
```

This is required because `/api/files/{assetId}` checks `metadata.createdBy` for S3 assets before streaming. Missing `createdBy` will cause legitimate cut previews/downloads to return 403 or weaken ownership checks if bypassed.

- [ ] **Step 6: Add ZIP source validation before job creation**

For ZIP sources, reject before extraction or job creation:

```text
absolute path entries
entries containing ..
__MACOSX/
.DS_Store
._*
symlinks
encrypted ZIP
entry count > 10,000
total uncompressed bytes > 4 GiB
single entry > 500 MiB
compression ratio > 200:1
```

Test cases must include at least:

```text
../../evil.png
/absolute/path.png
__MACOSX/._page.png
zip bomb metadata where file_size / compress_size > 200
```

- [ ] **Step 7: Run API test**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_api_contract.py -q
```

Expected: PASS.

### Task 6: Implement worker processing and manifest integrity

**Files:**
- Create: `backend/app/services/webtoon_cut_worker.py`
- Create: `backend/app/services/webtoon_cut_worker_runtime.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_webtoon_cut_worker_contract.py`

**Interfaces:**
- Produces:
  - `process_next_webtoon_cut_job() -> dict | None`
  - `process_webtoon_cut_job(db: Session, job_id: str) -> dict`
  - `run_webtoon_cut_worker_loop(stop_event: asyncio.Event) -> None`

- [ ] **Step 1: Write worker state transition test**

Create `backend/tests/test_webtoon_cut_worker_contract.py`:

```python
def test_worker_marks_dependency_missing_as_failed(monkeypatch):
    from backend.app.services import webtoon_cut_worker

    monkeypatch.setattr(
        "backend.app.services.webtoon_panel_engine.engine.assert_engine_dependencies",
        lambda: (_ for _ in ()).throw(RuntimeError("pdftoppm missing")),
    )
    result = webtoon_cut_worker.dependency_error_payload(RuntimeError("pdftoppm missing"))
    assert result["errorCode"] == "engine_dependency_missing"
```

- [ ] **Step 2: Implement dependency error helper**

In `webtoon_cut_worker.py`:

```python
def dependency_error_payload(exc: Exception) -> dict:
    return {"errorCode": "engine_dependency_missing", "errorMessage": str(exc)}
```

- [ ] **Step 3: Implement race-safe job claim**

Claim only rows:

```text
status = PENDING
deleted_at IS NULL
```

Set:

```text
status = RUNNING
started_at = now
```

Guardrail: one active job per user. If user has RUNNING/CANCEL_REQUESTED job, leave additional PENDING jobs unclaimed.

In PostgreSQL, claim with one of these race-safe patterns:

```python
select(WebtoonCutJob)
  .where(WebtoonCutJob.status == "PENDING")
  .with_for_update(skip_locked=True)
  .limit(1)
```

or:

```sql
UPDATE webtoon_cut_jobs
SET status = 'RUNNING', started_at = now()
WHERE id = :id AND status = 'PENDING'
```

Proceed only if exactly one row was updated. This prevents duplicate processing in multi-container ECS deployments.

- [ ] **Step 4: Implement page/chunk processing and output registration**

The worker must process PDF inputs as a streaming pipeline:

```text
download source from S3 to temp dir
for each page:
  check cancel flag
  render one page with pdftoppm -r 300
  split page with grid_split.py
  upload generated cuts/debug to S3
  register assets and WebtoonCutOutput rows
  delete rendered page and local cut temp files
  commit unit progress
```

Do not render all PDF pages before uploading. Local temp usage must stay bounded by one page or a small chunk.

For each generated PNG:

1. Save to S3 under job prefix.
2. Register `Asset(asset_type="webtoon_cut_image")`.
3. Insert `WebtoonCutOutput`.
4. Set `Asset.metadata_json["createdBy"] = job.created_by`.
5. Verify PNG signature and dimensions before marking unit completed.
6. Release OpenCV/NumPy resources after each unit and call `gc.collect()` after large pages.

S3 uploads for cuts/debug files may use a bounded `ThreadPoolExecutor`, but must not create unbounded concurrency:

```python
WEBTOON_CUT_S3_UPLOAD_WORKERS = min(8, max(2, settings.webtoon_cut_s3_upload_workers))
```

Guardrail: DB rows are written only after each corresponding S3 upload succeeds. If parallel upload partially fails, the unit remains non-completed and retryable.

- [ ] **Step 5: Implement cancellation and stale job recovery**

Cancellation:

```text
POST /api/webtoon-cuts/jobs/{jobId}/cancel
→ set status = CANCEL_REQUESTED
→ worker observes before each page/unit
→ worker finishes current atomic unit
→ set status = CANCELLED or PAUSED with completed counts preserved
```

Stale recovery:

```text
RUNNING jobs with updated_at older than WEBTOON_CUT_STALE_SECONDS
→ FAILED_RETRYABLE or PENDING depending on retry policy
```

- [ ] **Step 6: Register a separate worker task, not a monitor-loop step**

Do not add this to the existing `monitor_loop`:

```python
await asyncio.to_thread(process_next_webtoon_cut_job)
```

Instead, create `backend/app/services/webtoon_cut_worker_runtime.py`:

```python
async def run_webtoon_cut_worker_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(process_next_webtoon_cut_job)
        except Exception:
            LOGGER.exception("Webtoon cut worker cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
```

Then start it in `main.py` lifecycle as an independent task:

```python
webtoon_stop_event = asyncio.Event()
webtoon_worker_task = asyncio.create_task(
    run_webtoon_cut_worker_loop(webtoon_stop_event),
    name="webtoon-cut-worker",
)
```

On shutdown, set the stop event, cancel the task if needed, and do not block the existing task-status monitor.

- [ ] **Step 7: Run worker test**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_worker_contract.py -q
```

Expected: PASS.

### Task 7: Implement history, filters, and download API

**Files:**
- Modify: `backend/app/api/v1/webtoon_cuts.py`
- Modify: `backend/app/services/webtoon_cut_service.py`
- Test: `backend/tests/test_webtoon_cut_history_filters.py`
- Test: `backend/tests/test_webtoon_cut_downloads.py`

**Interfaces:**
- Produces:
  - `GET /api/webtoon-cuts/jobs`
  - `GET /api/webtoon-cuts/jobs/{jobId}`
  - `GET /api/webtoon-cuts/jobs/{jobId}/outputs`
  - `POST /api/webtoon-cuts/jobs/{jobId}/downloads`

- [ ] **Step 1: Write filter test**

Create `backend/tests/test_webtoon_cut_history_filters.py`:

```python
def test_output_filter_rejects_unknown_flag():
    from backend.app.services.webtoon_cut_service import normalize_output_filters

    try:
        normalize_output_filters({"flags": "unknown"})
    except ValueError as exc:
        assert "지원하지 않는 flag" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Implement filter normalization**

Allowed flags:

```python
ALLOWED_FLAGS = {"fullpage", "review_required", "review_continuous", "thin", "many", "missing_output", "error"}
```

- [ ] **Step 3: Implement query scoping**

Every query must add:

```python
WebtoonCutJob.created_by == current_user.id
```

unless user has `jobs:manage`.

- [ ] **Step 4: Implement download creation**

For selected outputs, create ZIP entries from `WebtoonCutOutput.display_path`. For all outputs, include:

```text
outputs/
_debug/
manifest.json
summary.csv
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_history_filters.py backend/tests/test_webtoon_cut_downloads.py -q
```

Expected: PASS.

### Task 8: Implement I2V bridge to Grok and Batch

**Files:**
- Modify: `backend/app/api/v1/webtoon_cuts.py`
- Modify: `backend/app/services/webtoon_cut_service.py`
- Modify: `backend/app/services/studio_api_service.py`
- Test: `backend/tests/test_webtoon_cut_i2v_bridge.py`
- Test: `backend/tests/test_webtoon_cut_runpod_scope_guard.py`

**Interfaces:**
- Produces:
  - `create_grok_prompt_input_from_outputs(db, job_id, output_ids, created_by)`
  - `create_batch_input_from_outputs(db, job_id, output_ids, created_by)`
  - `is_canonical_webtoon_cut_asset(asset: Asset) -> bool`

- [ ] **Step 1: Write ownership guard test**

Create `backend/tests/test_webtoon_cut_i2v_bridge.py`:

```python
def test_i2v_bridge_requires_outputs_from_same_job():
    from backend.app.services.webtoon_cut_service import validate_output_selection

    outputs = [
        {"jobId": "wcut_1", "assetId": "asset_1", "flags": []},
        {"jobId": "wcut_2", "assetId": "asset_2", "flags": []},
    ]
    try:
        validate_output_selection(outputs, expected_job_id="wcut_1", exclude_review_required=False)
    except ValueError as exc:
        assert "같은 컷 분할 작업" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Implement selection validator**

Rules:

```python
def validate_output_selection(outputs, *, expected_job_id, exclude_review_required):
    if not outputs:
        raise ValueError("선택한 컷이 없습니다.")
    for output in outputs:
        if output["jobId"] != expected_job_id:
            raise ValueError("같은 컷 분할 작업의 컷만 선택할 수 있습니다.")
        if "error" in output["flags"] or "missing_output" in output["flags"]:
            raise ValueError("오류 컷은 후속 작업에 사용할 수 없습니다.")
    if exclude_review_required:
        outputs = [o for o in outputs if not set(o["flags"]) & {"review_required", "thin", "many", "review_continuous"}]
    return outputs
```

- [ ] **Step 3: Bridge selected cuts to Grok prompt input only**

Create a Grok prompt draft/input payload with selected `assetId`s and `sourceRelativePath`, then route the user to the existing Grok prompt screen. Do not choose prompt workflow, prompt template, model, or generation options in the cut history screen.

- [ ] **Step 4: Bridge selected cuts to Batch input only**

Create a Batch input payload with selected `assetId`s and source order, then route the user to the existing Batch screen. Do not choose workflow, frame length, quality, negative prompt, or RunPod dispatch options in the cut history screen. The payload must be indistinguishable from uploaded image assets to downstream RunPod code.

- [ ] **Step 5: Add RunPod S3 input scoping guard for webtoon cuts**

Current code path:

```text
build_runpod_images()
→ ensure_s3_input_asset_scoped()
→ copy S3 object to batch/job input prefix
→ UPDATE Asset.storage_key to copied key
```

This is correct for staged upload assets, but wrong for canonical webtoon cut outputs. Add this test:

```python
def test_webtoon_cut_asset_scope_does_not_mutate_original_storage_key(db_session, monkeypatch):
    from backend.app.db.models import Asset
    from backend.app.services.studio_api_service import ensure_s3_input_asset_scoped

    asset = Asset(
        id="asset_cut_1",
        asset_type="webtoon_cut_image",
        file_name="017-03.png",
        mime_type="image/png",
        size_bytes=10,
        storage_backend="s3",
        storage_key="webtoon-cut/users/u/jobs/wcut_1/outputs/book/017-03.png",
        public_url="s3://bucket/webtoon-cut/users/u/jobs/wcut_1/outputs/book/017-03.png",
        metadata_json={"createdBy": "user_1"},
    )
    db_session.add(asset)
    db_session.commit()

    ensure_s3_input_asset_scoped("asset_cut_1", {
        "batchJobId": "batch_1",
        "requestItemId": "item_1",
        "jobId": "task_1",
    })

    db_session.refresh(asset)
    assert asset.storage_key == "webtoon-cut/users/u/jobs/wcut_1/outputs/book/017-03.png"
```

Implement guard in `studio_api_service.ensure_s3_input_asset_scoped()`:

```python
def _is_canonical_webtoon_cut_asset(asset: Asset) -> bool:
    return (
        asset.asset_type == "webtoon_cut_image"
        or str(asset.storage_key or "").lstrip("/").startswith("webtoon-cut/")
    )
```

If this is true, do not mutate the asset row. For RunPod dispatch, either:

1. return the canonical `s3Uri` directly from `asset_to_runpod_image()`, or
2. copy to the batch input path and pass that copied S3 URI in the transient payload without updating `Asset.storage_key`.

Guardrail: the source `webtoon_cut_image` row remains the permanent record used by 컷 분할 이력.

- [ ] **Step 6: Update usage counters**

After successful bridge:

```text
WebtoonCutOutput.used_in_prompt_count += 1
WebtoonCutOutput.used_in_batch_count += 1
```

- [ ] **Step 7: Run bridge tests**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_i2v_bridge.py backend/tests/test_webtoon_cut_runpod_scope_guard.py -q
```

Expected: PASS.

### Task 9: Build frontend menu, split screen, history screen, and detail screen

**Files:**
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/StudioShell.tsx`
- Modify: `frontend/src/helpers/navigation.ts`
- Create: `frontend/src/features/image-cuts/types.ts`
- Create: `frontend/src/features/image-cuts/api.ts`
- Create: `frontend/src/features/image-cuts/selection.ts`
- Create: `frontend/src/screens/imageCutSplitScreen.tsx`
- Create: `frontend/src/screens/imageCutHistoryScreen.tsx`
- Create: `frontend/src/screens/imageCutDetailScreen.tsx`
- Test: `frontend/src/features/image-cuts/selection.test.ts`

**Interfaces:**
- Routes:
  - `imageCuts.split` -> `/studio/image-cuts/split`
  - `imageCuts.history` -> `/studio/image-cuts/history`
  - `imageCuts.historyDetail` -> `/studio/image-cuts/history/:jobId`

- [ ] **Step 1: Write selection order test**

Create `frontend/src/features/image-cuts/selection.test.ts`:

```ts
import { sortCutOutputs } from "./selection";

test("sortCutOutputs orders by page and cut index", () => {
  expect(sortCutOutputs([
    { outputId: "b", pageNumber: 17, cutIndex: 3 },
    { outputId: "a", pageNumber: 17, cutIndex: 1 }
  ] as any).map((item) => item.outputId)).toEqual(["a", "b"]);
});
```

- [ ] **Step 2: Implement selection helper**

```ts
export function sortCutOutputs<T extends { pageNumber?: number | null; cutIndex: number; outputId: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => (
    (left.pageNumber ?? Number.MAX_SAFE_INTEGER) - (right.pageNumber ?? Number.MAX_SAFE_INTEGER) ||
    left.cutIndex - right.cutIndex ||
    left.outputId.localeCompare(right.outputId)
  ));
}
```

- [ ] **Step 3: Add routes and labels**

Add route labels:

```ts
"imageCuts.split": "컷 분할 처리",
"imageCuts.history": "컷 분할 이력"
```

Add sidebar group:

```text
이미지 컷 관리
  컷 분할 처리
  컷 분할 이력
```

- [ ] **Step 4: Build split screen**

Screen features:

```text
원본 업로드
업로드 완료 asset 표시
작업 요청
진행률/상태
완료 시 컷 분할 이력으로 이동
```

- [ ] **Step 5: Build progress polling**

While a job is active, poll:

```text
GET /api/webtoon-cuts/jobs/{jobId}
```

every 1-2 seconds and render:

```text
status
completed_units / total_units
generated_cut_count
current source/page if available
failed_units
review_required_units
```

Guardrail: polling must stop on terminal status and when the component unmounts.

- [ ] **Step 6: Build history/detail screen with virtualization**

Filters:

```text
작업 상태, 원본 유형, 작업자, 페이지 범위, 플래그, 사용 여부, 생성일, 검색
```

Actions:

```text
Grok 프롬프트 화면으로 보내기
Batch 처리 화면으로 보내기
선택 컷 ZIP 다운로드
전체 결과 다운로드
```

Selection requirements:

```text
현재 페이지 선택
필터 결과 전체 선택
검수 제외 전체 선택 제거
선택 컷은 원본 페이지/컷 순서로 정렬
```

View requirements:

```text
default view: list
optional toggle: grid
thumbnail click: update right-side preview
large image preview: use /api/files/{assetId}?download=0
list rows: checkbox, thumbnail, display path, page, cut index, size, flags, used state, createdBy
```

The detail screen must not render hundreds or thousands of `<img>` elements at once. Use paginated list/grid with pageSize 50-100 and lazy loaded thumbnails with IntersectionObserver. It must not request all cut images simultaneously.

- [ ] **Step 7: Run frontend tests**

Run:

```bash
cd frontend
npm test -- image-cuts
```

Expected: PASS.

### Task 10: Remove or quarantine browser-local Web Worker path

**Files:**
- Modify: `frontend/src/features/webtoon-cut/*`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/screens/webtoonCutScreen.tsx`
- Test: `frontend/src/features/webtoon-cut/networkIsolation.test.ts`

**Interfaces:**
- Produces a clear deprecation guard:

```ts
export const WEBTOON_CUT_LOCAL_WORKER_DEPRECATED = true;
```

- [ ] **Step 1: Prevent accidental dual execution paths**

The old local worker must not run from the new menu. Keep files only for reference/tests until removed.

- [ ] **Step 2: Remove `WebtoonCutJobProvider` from app root**

If no route uses local worker state, remove provider wrapping from `frontend/src/main.tsx`.

- [ ] **Step 3: Keep old tests only if they guard naming parity**

Delete or skip local-only tests that assert no upload/network. They conflict with the new policy.

- [ ] **Step 4: Run frontend test suite**

Run:

```bash
cd frontend
npm test
```

Expected: PASS.

### Task 11: Add retention, deletion, and audit guardrails

**Files:**
- Create: `backend/app/services/webtoon_cut_retention_service.py`
- Modify: `backend/app/api/v1/webtoon_cuts.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_webtoon_cut_retention.py`

**Interfaces:**
- Produces:
  - `delete_webtoon_cut_job(db, job_id, actor_id, force=False)`
  - `cleanup_expired_webtoon_cut_assets()`

- [ ] **Step 1: Write delete guard test**

Create `backend/tests/test_webtoon_cut_retention.py`:

```python
def test_delete_blocks_used_cut_without_force():
    from backend.app.services.webtoon_cut_retention_service import can_delete_output

    assert can_delete_output({"usedInPromptCount": 1, "usedInBatchCount": 0}, force=False) is False
```

- [ ] **Step 2: Implement delete rules**

Rules:

```text
unused cut: delete allowed
used_in_prompt: warning/force required
used_in_batch: force or admin required
used_in_i2v_result: delete blocked unless admin override exists
```

- [ ] **Step 3: Implement retention**

Defaults:

```text
source original: 30 days
rendered pages: 7 days
cut PNG: 180 days
debug overlay: 30 days
manifest/summary: 180 days
download ZIP: 24 hours
```

- [ ] **Step 4: Add audit logs**

Record:

```text
webtoon_cut.job.create
webtoon_cut.job.delete
webtoon_cut.outputs.grok_batch
webtoon_cut.outputs.batch_job
webtoon_cut.download.create
```

- [ ] **Step 5: Run retention tests**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_retention.py -q
```

Expected: PASS.

### Task 12: Full verification and deployment checklist

**Files:**
- Modify: deployment docs / ECS task definition as applicable
- Test:
  - `backend/tests/test_webtoon_cut_*.py`
  - `backend/tests/test_asset_streaming.py`
  - `backend/tests/test_prompt_batch_service.py`
  - `backend/tests/test_batch_job_service.py`
  - frontend image-cuts tests

- [ ] **Step 1: Backend targeted tests**

Run:

```bash
python -m pytest backend/tests/test_webtoon_cut_*.py backend/tests/test_asset_streaming.py -q
```

- [ ] **Step 2: I2V regression tests**

Run:

```bash
python -m pytest backend/tests/test_prompt_batch_service.py backend/tests/test_batch_job_service.py -q
```

- [ ] **Step 3: Frontend tests**

Run:

```bash
cd frontend
npm test -- image-cuts
```

- [ ] **Step 4: Manual smoke**

Use one small PDF:

```text
업로드 → 컷 분리 작업 생성 → 완료 → 이력 조회 → 컷 보기 → 선택 ZIP 다운로드 → Grok 프롬프트 생성 → Batch 처리 연결
```

- [ ] **Step 5: Production guard checklist**

Verify:

```text
S3 bucket private
S3 CORS only allows expected PUT headers
Poppler installed in ECS image
OpenCV imports in ECS
No base64 original/cut bytes in DB
No absolute local paths in DB
/api/files ownership check works for webtoon assets
jobs:run user cannot read other user's webtoon jobs
history:read/admin scope works as intended
Download ZIP expires/cleans up
Old local worker route no longer starts processing
```

---

## Side Effect and Collision Guardrails

1. **Existing upload API collision**
   - Do not use `/api/uploads/complete` for webtoon source uploads because it writes `asset_type=input_image` and expects existing batch/request scope.
   - Use `/api/webtoon-cuts/uploads/*`.

2. **S3 key collision**
   - All webtoon keys must be under `webtoon-cut/users/{userId}/jobs/{jobId}/`.
   - No key may be derived solely from filename.

3. **NFS/S3 hybrid collision**
   - New webtoon assets must use `storage_backend=s3`.
   - Existing `/api/files/{assetId}` supports S3 and local; keep this behavior.

4. **I2V pipeline collision**
   - Do not duplicate cut bytes into new upload assets.
   - Pass `webtoon_cut_image` assetIds into existing Grok/Batch services.
   - Downstream services must read assets via `studio_api_service.read_asset_bytes()`.
   - `ensure_s3_input_asset_scoped()` must not update `Asset.storage_key` for `webtoon_cut_image` or any asset under `webtoon-cut/`.
   - If RunPod requires a batch-scoped copy, create a transient copied S3 object but keep the canonical cut asset row unchanged.

5. **Naming corruption**
   - Do not use ASCII-only `safe_filename()` for user-facing names.
   - Preserve Korean display names in DB and manifest.
   - Use safe storage segments only for S3 key path safety.

6. **Python dependency drift**
   - ECS image must pin system Poppler and Python OpenCV dependencies.
   - `engine_version` must change when `grid_split.py` logic changes.
   - Job manifest stores `engine_version` and `policy_version`.

7. **Result integrity**
   - A completed unit must have at least one verified PNG output.
   - If one cut file is missing or corrupt, unit is not completed.
   - Final job status is `COMPLETED_WITH_ERRORS` if any unit fails.
   - Final job status is `COMPLETED_WITH_REVIEW` if review flags exist but no errors.

8. **Security**
   - S3 public access blocked.
   - Presigned upload is short-lived.
   - Content type and file extension are validated after upload.
   - ZIP path traversal and zip bombs are rejected before extraction.
   - Every endpoint scopes by `created_by` unless the user has admin/manage permission.
   - Every webtoon asset must include `metadata_json.createdBy` so `/api/files/{assetId}` ownership checks remain valid.

9. **Operational**
   - One active cut job per user by default.
   - Worker uses temp directories and always cleans them.
   - Server restart leaves `RUNNING` jobs recoverable by marking stale running jobs back to `PENDING` or `FAILED_RETRYABLE` after a timeout.
   - Webtoon cut processing must run in a dedicated background worker task/process, not inside the existing RunPod/Grok/Batch monitor loop.
   - Worker job claiming must be race-safe with `FOR UPDATE SKIP LOCKED` or conditional update semantics.
   - PDF processing must be page/chunk based to avoid ECS temp disk exhaustion.
   - Frontend cut detail view must use pagination, virtualization, or lazy loading to avoid rendering all cut images at once.

---

## Self-review

- Spec coverage: The plan covers S3 storage, API, DB, Python dependencies, naming policy, server worker, history UI, download, Grok/Batch I2V connection, retention, and guardrails.
- Conflict handling: The old local-only/no-upload requirement is explicitly superseded, while naming/output semantics are retained.
- Side effects: Existing `input_image`, `/api/uploads`, `/api/files`, Batch, and Grok flows are protected by webtoon-specific asset types and API prefix.
- Placeholder scan: No task relies on unbounded “TBD” behavior. Decision points are converted into concrete policy defaults.
- Type consistency: Route names, endpoint names, asset types, model names, and service function names are defined before use.
