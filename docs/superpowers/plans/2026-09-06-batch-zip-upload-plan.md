# Batch ZIP Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan.

**Goal:** Replace batch job image-folder selection with ZIP file selection and upload. The user selects a ZIP file, confirms the request in the Studio app modal, the backend uploads and safely extracts the ZIP, registers image assets, then starts the existing batch prompt/RunPod pipeline.

**Architecture:** Keep the existing `BatchJob` creation and downstream prompt generation flow. Add a ZIP import layer before `batch_job_service.create_batch_job()` so the batch service still receives normal asset IDs and item metadata.

**Tech Stack:** FastAPI, SQLAlchemy, existing asset repository/storage, React/Vite frontend, pytest contract tests.

**Spec Source:** User request on 2026-09-06:
- Use `zip 파일 선택 & 업로드 -> 요청 확인 -> 실행`.
- In the confirmation modal, image count is not known before upload, so show ZIP file name instead.
- Server uploads ZIP, extracts it, and proceeds with batch processing.
- Do not use native folder selection because browser security confirmation cannot be styled or suppressed.
- Batch job id rule: `작업자_업로드압축파일명_yymmdd`.

## Global Constraints

- Do not commit or deploy during this plan execution unless the user explicitly asks.
- Do not change DB schema unless implementation discovers an unavoidable need.
- Preserve the current Task History-only model for direct ZIP batch execution; do not reintroduce duplicate RunPod request-management rows.
- Keep the Studio-style confirmation modal. Do not use `window.confirm()`.
- Do not trust ZIP entry paths. Prevent path traversal, absolute paths, symlinks, and unsafe metadata files.
- Multi-level ZIP directories must be supported recursively.

## Desired User Flow

1. User opens Batch 작업 요청 관리.
2. User chooses workflow.
3. User chooses video length. Default stays 10 seconds.
4. User selects one `.zip` file.
5. User clicks 작업 요청.
6. Studio confirmation modal appears with:
   - 워크플로우
   - ZIP 파일명
   - 길이
   - 진행 하시겠습니까?
7. On 진행:
   - frontend uploads the ZIP as multipart form data.
   - backend extracts image files recursively.
   - backend registers extracted images as assets.
   - backend creates one batch job using the registered image asset IDs.
8. After server response, UI shows created batch and imported image count from backend response.
9. On 취소:
   - request state is reset to the initial batch creation state.

## ZIP Handling Rules

- Accept only `.zip` uploads.
- Process image files recursively from any nested directory depth.
- Supported image extensions:
  - `.jpg`
  - `.jpeg`
  - `.png`
  - `.webp`
- Ignore:
  - directories
  - `__MACOSX/`
  - `.DS_Store`
  - AppleDouble files such as `._filename.jpg`
  - non-image files
- Reject the entire upload if:
  - ZIP is invalid or encrypted
  - no supported images are found
  - any entry attempts path traversal such as `../`
  - any entry is absolute path style
  - extracted total size or image count exceeds configured limits
- Preserve each image's original file name for display and Task History mapping.
- Preserve relative path as metadata if useful for duplicate file names.

## Source Directory Naming

Derive `sourceDirName` as follows:

1. If all imported images are under one common top-level directory inside the ZIP, use that top-level directory.
2. Otherwise use the ZIP filename without `.zip`.

Examples:

- `shoot-0906.zip` containing `shoot-0906/0001.jpg` and `shoot-0906/sub/0002.png` -> `sourceDirName = shoot-0906`
- `upload.zip` containing `a/0001.jpg` and `b/0002.jpg` -> `sourceDirName = upload`

## Batch Job ID Naming

Change batch job id generation for ZIP-based batch jobs to:

`작업자_업로드압축파일명_yymmdd`

Examples:

- worker `장균은`, uploaded ZIP `픽미툰_씬.zip`, created at 2026-09-04 KST -> `장균은_픽미툰_씬_260904`
- worker `장균은`, uploaded ZIP `shoot-0906.zip`, created at 2026-09-06 KST -> `장균은_shoot-0906_260906`

Rules:

- Use the authenticated user's display name when available; otherwise use user id.
- Use the uploaded ZIP filename stem, without `.zip`.
- Use the batch creation date in KST as `yymmdd`.
- Normalize whitespace to `_`.
- Remove path separators and control characters from worker and ZIP tokens.
- Preserve Korean characters.
- Preserve ASCII letters, numbers, `_`, and `-`.
- Because `batch_jobs.id` is currently `String(64)`, truncate the middle ZIP token first when the full id would exceed 64 characters.
- If the generated id already exists, append `_2`, `_3`, etc. while still keeping the final id within 64 characters.
- Store the original uploaded ZIP filename in asset/batch metadata or response context if later UI needs the exact original name; do not rely on the truncated id as the only copy of the filename.

## Backend Changes

### 1. Add ZIP Import Service

Create:

`backend/app/services/batch_zip_import_service.py`

Responsibilities:

- Validate uploaded ZIP.
- Extract to a temporary working directory.
- Enumerate supported image files recursively.
- Normalize and validate paths.
- Skip system metadata files.
- Enforce configurable safety limits:
  - max ZIP upload bytes
  - max extracted bytes
  - max image count
- Register each extracted image using existing asset registration flow.
- Return:

```python
{
    "source_dir_name": "shoot-0906",
    "items": [
        {"assetId": "...", "fileName": "0001.jpg", "relativePath": "shoot-0906/0001.jpg"}
    ],
    "image_count": 1,
}
```

Implementation note:

- Prefer `zipfile.ZipFile`.
- Use `pathlib.PurePosixPath` for ZIP member paths.
- Never call `extractall()` directly.
- Copy each safe member manually into a controlled temp directory.
- Delete the uploaded temporary ZIP in `finally`.
- Preserve extracted image files under the normal upload storage tree because the current asset registration stores file paths instead of copying files.

### 2. Add Batch ZIP Endpoint

Modify:

`backend/app/api/v1/batch_jobs.py`

Add:

`POST /api/batch-jobs/zip`

Request:

- multipart form data
- `workflowId`
- `requestedFrames`
- `file`

Behavior:

- Require same auth/permissions as current batch job creation.
- Call `batch_zip_import_service.import_zip_upload(...)`.
- Call existing `batch_job_service.create_batch_job()` with:

```python
{
    "workflowId": workflow_id,
    "requestedFrames": requested_frames,
    "sourceDirName": imported.source_dir_name,
    "sourceZipFileName": uploaded_zip_file_name,
    "items": imported.items,
}
```

Response:

- Reuse existing `BatchJobResponse`.
- Include image count through existing `totalImages` field.
- Optionally include `sourceDirName` if already part of response.

Dependency check:

- FastAPI file upload requires `python-multipart`.
- If not already present, add it to `backend/requirements.txt`.

### 3. Update Batch Job ID Generation

Modify:

`backend/app/services/batch_job_service.py`

Current behavior:

- `_next_batch_job_id(db, created_by, created_at)` creates ids as `작업자_yymmdd_sequence`.

New ZIP behavior:

- Add a ZIP-aware id path that accepts the uploaded ZIP filename stem.
- Keep the current sequence-based rule only for non-ZIP/internal callers if still needed.
- For ZIP endpoint calls, generate ids as `작업자_업로드압축파일명_yymmdd`.
- Add collision suffix `_2`, `_3`, etc. only when the same id already exists.

Proposed interface:

```python
def create_batch_job(db: Session, payload: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    source_zip_file_name = str(payload.get("sourceZipFileName") or "").strip()
    if source_zip_file_name:
        batch_id = _next_zip_batch_job_id(
            db,
            created_by=created_by,
            created_at=created_at,
            zip_file_name=source_zip_file_name,
        )
    else:
        batch_id = _next_batch_job_id(db, created_by=created_by, created_at=created_at)
```

Add helpers:

```python
def _safe_batch_token(value: str) -> str:
    cleaned = "_".join(str(value or "").strip().split())
    cleaned = cleaned.replace("/", "_").replace("\\", "_").replace(":", "_")
    return "".join(ch for ch in cleaned if ch.isprintable()).strip("_") or "unknown"


def _zip_file_stem(file_name: str) -> str:
    name = Path(str(file_name or "")).name
    return Path(name).stem or "upload"


def _next_zip_batch_job_id(db: Session, *, created_by: str, created_at: datetime, zip_file_name: str) -> str:
    worker_token = _safe_batch_token(_worker_batch_token(db, created_by))
    zip_token = _safe_batch_token(_zip_file_stem(zip_file_name))
    date_token = _aware_utc(created_at).astimezone(SEOUL_TIMEZONE).strftime("%y%m%d")
    base_suffix = f"_{date_token}"
    candidate = _fit_batch_id(worker_token, zip_token, base_suffix, collision_suffix="")
    counter = 2
    while db.get(BatchJob, candidate) is not None:
        collision_suffix = f"_{counter}"
        candidate = _fit_batch_id(worker_token, zip_token, base_suffix, collision_suffix=collision_suffix)
        counter += 1
    return candidate
```

The implementation must keep the final id length `<= 64`.

## Frontend Changes

### 1. API Client

Modify:

`frontend/src/api/client.ts`

Add:

`createBatchJobFromZip({ workflowId, requestedFrames, file })`

Rules:

- Use `FormData`.
- Do not manually set `Content-Type`; browser must set multipart boundary.
- Return the same response shape as current `createBatchJob()`.

### 2. Batch Job Screen

Modify:

`frontend/src/screens/batchJobScreen.tsx`

Replace folder/image upload flow with ZIP file flow:

- Remove `webkitdirectory` folder input.
- Remove per-image `apiClient.upload()` loop.
- Add single ZIP file state.
- File input accepts ZIP only:

```tsx
accept=".zip,application/zip,application/x-zip-compressed"
```

- The selection UI shows ZIP file name and size.
- 작업 요청 is enabled only when:
  - workflow selected
  - ZIP file selected
  - length selected
- Confirmation modal text shows:
  - 워크플로우
  - ZIP 파일명
  - 길이
  - "진행 하시겠습니까?"
- Confirmation modal does not show image count before upload.
- After upload succeeds, use backend `totalImages` for result feedback.
- 취소 resets selected ZIP and request state.

## Tests

### Backend Unit Tests

Add:

`backend/tests/test_batch_zip_import_service.py`

Cover:

- Valid ZIP with root-level images imports successfully.
- Valid ZIP with nested `dir/dir/file.jpg` imports successfully.
- Metadata files are ignored.
- Non-image files are ignored.
- Empty/no-image ZIP returns validation error.
- Path traversal entry is rejected.
- Absolute-path entry is rejected.
- Duplicate filenames in different directories preserve relative path metadata.
- ZIP filename is returned so batch id generation can use it.

### Batch ID Tests

Add or extend:

`backend/tests/test_batch_job_service.py`

Cover:

- ZIP batch id uses `작업자_압축파일명_yymmdd`.
- `.zip` extension is removed from the id.
- KST date is used.
- Korean worker names and Korean ZIP names are preserved.
- Long ZIP filename is truncated so `len(batch.id) <= 64`.
- Same worker, same ZIP, same date creates a collision-safe suffix such as `_2`.
- Non-ZIP callers keep the existing sequence behavior unless product decision says all batch jobs must use the new ZIP rule.

### Backend API Tests

Add or extend:

`backend/tests/test_batch_job_service.py`

Cover:

- `POST /api/batch-jobs/zip` creates a batch job from ZIP upload.
- Response `totalImages` equals imported image count.
- Existing `sourceDirName` derivation works.
- Invalid ZIP returns 400.

### Frontend Contract Tests

Extend:

`backend/tests/test_frontend_batch_management_contract.py`

Assert:

- Batch screen uses ZIP selection.
- `webkitdirectory` is removed.
- `apiClient.upload()` loop is removed from batch request path.
- `createBatchJobFromZip()` is used.
- Confirmation modal includes ZIP filename and does not claim image count before upload.
- Default length remains 10 seconds.
- Created batch notice displays the backend-returned batch id, not a client-generated id.

## Verification Commands

Run from repository root:

```bash
python3.12 -m pytest backend/tests/test_batch_zip_import_service.py backend/tests/test_batch_job_service.py backend/tests/test_frontend_batch_management_contract.py
npm run build
git diff --check
```

If `python3.12` is not available in the environment, use the project-local Python runtime already used by `scripts/run_local.py`.

## Rollout Notes

- This change affects local batch upload UX and backend upload API.
- It should not require Alembic migration.
- It should not change existing Task History schemas.
- Existing folder-selection code should be removed only after ZIP flow tests are in place.
- ECS deployment should be a separate explicit step after local verification and commit.

## Integration Compatibility Review

Checked against current code paths on 2026-09-06.

### Batch 작업 대시보드

The ZIP flow should work if it enters the existing path through:

`batch_job_service.create_batch_job()`

That function creates:

- `BatchJob`
- linked `PromptGenerationBatch`
- linked `ImagePromptDraft` rows with `batch_job_id`

The active dashboard reads only `batch_jobs` rows where `status = INCOMPLETE` through:

- `GET /api/batch-jobs/active`
- `batch_job_service.list_active_batch_jobs()`

Counters are refreshed by the background monitor:

- `refresh_batch_job_counters()`

Therefore ZIP upload does not need a separate dashboard table or query.

Required invariant:

- The ZIP endpoint must call `create_batch_job()` with normal asset `items`.
- The imported image count must match `BatchJob.total_images`.
- `sourceDirName` must be derived from the ZIP structure or ZIP filename.

### Batch 작업 이력 관리

Batch history reads directly from `batch_jobs`:

- `GET /api/batch-jobs`
- `batch_job_service.list_batch_jobs()`

The ZIP flow should be visible here automatically once `BatchJob` is created.

Required invariant:

- ZIP import must not bypass `BatchJob`.
- The displayed 이미지 디렉토리 field should use derived `sourceDirName`.
- The date should remain the batch creation date, not the later RunPod completion date.

### 프롬프트 생성 이력

Prompt history reads `image_prompt_drafts`:

- `GET /api/history/prompts`
- `prompt_batch_service.list_prompt_drafts()`

The existing batch creation flow already creates one `ImagePromptDraft` per asset and sets:

- `prompt_batch_id`
- `batch_job_id`
- `workflow_id`
- `asset_id`
- `requested_frames`
- `created_by`

Therefore ZIP-uploaded images will appear in prompt history if and only if ZIP import registers assets first and then passes those asset IDs into `create_batch_job()`.

Required invariant:

- ZIP import must register each extracted image as an `input_image` asset.
- The draft `asset_id` must point to the registered extracted image.
- `batch_job_id` must be preserved so prompt history batch-id filtering continues to work.

### RunPod 생성 이력 관리

RunPod history reads `workflow_tasks`:

- `GET /api/history/runpod`
- `studio_api_service.paginated_runpod_history()`
- `task_tracking_service.task_history_items()`

Current batch behavior is:

1. Grok draft becomes `READY`.
2. `batch_job_service.promote_ready_batch_drafts()` builds a RunPod job payload from the draft.
3. It adds `job_payload["batchJobId"] = batch_id`.
4. `studio_api_service.create_job()` creates a durable `WorkflowTask`.
5. `task_tracking_service._upsert_task()` copies `batchJobId` into `WorkflowTask.batch_job_id`.

Therefore ZIP-uploaded batch jobs will appear in RunPod history automatically once prompt generation completes and drafts are promoted.

Required invariant:

- ZIP flow must not create `RunpodRequestBatch` or `RunpodRequestItem`.
- ZIP flow must rely on direct durable `WorkflowTask` creation through `promote_ready_batch_drafts()`.
- `WorkflowTask.batch_job_id` must be present for RunPod history batch-id filtering.

### RunPod 요청관리

The current product rule for file/folder/ZIP batch work is:

- Batch work should not appear as selectable rows in RunPod 요청관리.
- It should proceed directly from prompt completion to RunPod task submission.
- Progress should be checked in Batch 작업 대시보드, Batch 작업 이력, and Task/RunPod history.

Current code supports this because `promote_ready_batch_drafts()` calls:

- `studio_api_service.job_payload_from_prompt_draft()`
- `studio_api_service.create_job()`

It intentionally does not call:

- `create_runpod_request_batch()`
- `runpod_request_batch_service.create_request_batch()`

Required invariant:

- Do not use `/api/jobs/request-batches` for ZIP batch execution.
- Do not add request-management rows as a side effect of ZIP import.

## Compatibility Risks To Test

- If ZIP import creates assets but `create_batch_job()` fails, orphan input assets may remain. Wrap import and batch creation in a cleanup strategy or delete newly registered assets on failure.
- If ZIP extraction registers duplicate bare file names from different directories, display can be ambiguous. Preserve `relativePath` in asset metadata.
- If `python-multipart` is missing, the new endpoint will fail at startup or request parsing.
- If imported asset MIME/type is wrong, Grok prompt generation can fail later. Detect MIME from file content when possible.
- If a ZIP contains too many images, the first request can overload prompt generation queue. Enforce max image count before registering assets.
- If `batch_job_id` is missing from drafts or tasks, the four management screens will diverge. Add tests that assert the same batch id exists across `BatchJob`, `ImagePromptDraft`, and promoted `WorkflowTask`.
- If uploaded ZIP filenames are long, `batch_jobs.id` can exceed the current 64-character column. Truncate the ZIP token before insert and test the exact boundary.
- If the same worker uploads the same ZIP twice on the same day, the new id rule collides. Add deterministic collision suffixes while preserving the date token.
