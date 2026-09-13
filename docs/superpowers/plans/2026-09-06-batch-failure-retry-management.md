# Batch Failure Retry Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 배치 처리 중 Grok 프롬프트 생성 또는 RunPod 영상 생성에서 중간 오류가 발생해도 기존 Batch/Prompt/Task 식별자를 유지하면서 자동/수동 재처리를 안전하게 관리한다.

**Architecture:** 기존 배치 파이프라인(`BatchJob` -> `ImagePromptDraft` -> `WorkflowTask`)을 유지한다. 배치 작업은 RunPod 요청관리의 `RunpodRequestBatch/Item`을 만들지 않고 Task History에서만 추적하는 구조이므로, 재처리도 `ImagePromptDraft`와 `WorkflowTask` 기존 행을 갱신하는 방식으로 구현한다. 새 입력 ZIP 없이 새 Batch/Prompt/RunPod 행을 만들지 않는 것을 최상위 불변 조건으로 둔다.

**Tech Stack:** Python FastAPI, SQLAlchemy/Alembic, MySQL RDS/SQLite, React/TypeScript, pytest, Vite.

**Spec:** `docs/superpowers/specs/2026-09-04-batch-job-management-design.md`, 현재 Codex task의 사용자 승인 설계(2026-09-06).

## Global Constraints

- ECS 배포는 별도 사용자 승인 전까지 수행하지 않는다.
- 운영 RDS/EFS 데이터는 삭제하거나 초기화하지 않는다.
- 새 입력 파일 또는 새 ZIP 업로드가 없으면 새 `batch_jobs`, `image_prompt_drafts`, `workflow_tasks` 행을 만들지 않는다.
- 같은 `prompt_draft_id`에는 살아있는 RunPod `workflow_tasks` 행이 최대 1개만 존재해야 한다.
- 배치 재처리는 RunPod 요청관리 화면의 요청 큐(`runpod_request_batches`, `runpod_request_items`)를 사용하지 않는다.
- 성공한 프롬프트/영상 항목은 자동/수동 재처리 대상에서 제외한다.
- 실패 재처리 후에도 Batch ID, Prompt ID, Task ID, 원본 ZIP 파일명, 원본 생성일은 보존한다.
- 재처리 시작 시각, 재처리 횟수, 마지막 오류는 원본 생성 시각과 분리해 기록한다.
- 기존 단일 RunPod 이력의 버튼 용어는 `재작업`, 배치 단위 장애 복구 용어는 `재처리`로 사용한다.

---

## Current Findings

- `backend/app/services/batch_job_service.py`의 `promote_ready_batch_drafts()`는 배치 소속 `READY` draft를 직접 `WorkflowTask`로 승격한다. 주석 그대로 배치 작업은 RunPod 요청관리 batch/item을 만들지 않는다.
- `_unpromoted_ready_drafts()`는 같은 `prompt_draft_id + batch_job_id`에 살아있는 `WorkflowTask`가 있으면 다시 승격하지 않는다. 이 불변 조건은 재처리 설계에서도 유지해야 한다.
- `backend/app/services/task_tracking_service.py`의 `requeue_task_for_rework()`는 같은 `WorkflowTask.id`를 재사용하지만 현재 `created_at`을 현재 시각으로 바꾼다. 재처리 이력과 원본 작업 이력을 구분하려면 `created_at`은 보존하고 별도 재작업 시각 필드를 추가해야 한다.
- `WorkflowTask`에는 이미 `dispatch_attempts`, `next_dispatch_at`, `last_dispatch_error`가 있어 RunPod 제출 단계의 일시적 실패는 재큐잉할 수 있다. 다만 Grok 단계와 provider terminal failure에 대한 일관된 재처리 메타데이터는 없다.
- `ImagePromptDraft`에는 `failure_message`는 있지만 재처리 횟수, 재처리 가능 여부, 다음 재처리 시각이 없다.
- 배치 대시보드 카운터는 `refresh_batch_job_counters()`가 `image_prompt_drafts.status`와 `workflow_tasks.status`에서 재계산한다. 재처리 상태도 이 함수에서 일관되게 집계돼야 한다.

---

## Mockup-Based Failure Case Review

The approved mockup opens `재처리 관리` from the `Batch 작업 이력` table only when the row's `실패` value is greater than zero. A zero value is inert and must not open the modal.

| Case | Source row | Expected modal row | Retry action | Identity rule | Counter rule |
|---|---|---|---|---|---|
| Grok transient failure | `ImagePromptDraft.status = FAILED`, no `WorkflowTask` yet | 프롬프트 상태 `FAILED`, RunPod 상태 `미요청` | `재처리` resets the same draft to `PENDING` | keep `draft.id`, `batch_job_id`, `asset_id`, source ZIP metadata | prompt failed decreases, prompt waiting increases |
| Grok permanent/manual failure | `ImagePromptDraft.status = MANUAL_REQUIRED` or non-retryable `FAILED` | 프롬프트 상태 `FAILED`, RunPod 상태 `미요청`, retry disabled | skipped with reason `non_retryable` | no new draft or task | failed count remains |
| RunPod submit failure before provider job id | existing `WorkflowTask.status = FAILED` or retryable dispatch failure | 프롬프트 상태 `READY`, RunPod 상태 `FAILED` or `PENDING_SUBMIT` | `재작업` resets the same task to `PENDING_SUBMIT` | keep `task.id`, `prompt_draft_id`, `batch_job_id`; do not create a task | video failed decreases, pending submit increases |
| RunPod provider terminal failure | existing `WorkflowTask.status = FAILED/TIMED_OUT` with provider data | 프롬프트 상태 `READY`, RunPod 상태 terminal failed | `재작업` only if retryable/manual allowed | keep original `created_at`; set `rework_requested_at` | video failed moves to pending/in-progress during rework |
| RunPod still active | `WorkflowTask.status = PENDING_SUBMIT/DISPATCHING/QUEUED/IN_PROGRESS/RUNNING` | status shown as active, checkbox disabled | no retry action | no mutation from modal except `상태 새로고침` | active counters unchanged |
| Completed item | `WorkflowTask.status = COMPLETED/SUCCESS` | shown only for context or excluded from retry list | disabled/excluded | no mutation | completed counters unchanged |
| Duplicate live task anomaly | more than one non-deleted task for the same `prompt_draft_id + batch_job_id` | warning row in modal | retry blocked until cleanup | never create or select a third task | counters must flag diagnostic instead of hiding mismatch |
| Missing linkage anomaly | draft has `batch_job_id` but task lost `batch_job_id`, or task has `batch_job_id` without `prompt_draft_id` | warning row in modal | `상태 새로고침` may repair only derivable missing `batch_job_id`; retry otherwise blocked | repair links only when source is unambiguous | report skipped/warning count |

Information consistency checks required for every modal load:

- `BatchJob.failedCount` must equal `prompt_failed_count + video_failed_count`.
- Item rows must be loaded by `batch_job_id`, not by currently visible page rows.
- A Grok-failed item must not appear as a RunPod failure because no RunPod task exists yet.
- A RunPod-failed item must keep its original `prompt_draft_id`; retry must not create a second `WorkflowTask`.
- `sourceRelativePath`, `sourceZipFileName`, input `asset_id`, and output asset links must remain traceable for ZIP download.
- `상태 새로고침` is read/repair-only and must not enqueue Grok or RunPod execution.
- `선택 항목 재처리` affects only checked retryable failed rows.
- `전체 실패 재처리` affects all retryable failed rows in the selected batch and skips completed, active, non-retryable, duplicate, or ambiguous-link rows.

---

## Task 1: Define Retry Metadata and Migration

**Files:**
- Modify: `backend/app/db/models.py`
- Add: `backend/alembic/versions/20260906_0035_batch_retry_metadata.py`
- Test: `backend/tests/test_batch_queue_models.py`

**Interfaces:**
- Consumes: existing `BatchJob`, `ImagePromptDraft`, `WorkflowTask`
- Produces: retry metadata columns shared by Grok and RunPod batch recovery

- [ ] **Step 1: Add migration test expectations**

Add model/DDL assertions that the following columns exist after migration:

```text
image_prompt_drafts.retry_count
image_prompt_drafts.retryable
image_prompt_drafts.next_retry_at
image_prompt_drafts.last_retry_at
image_prompt_drafts.last_error_code
workflow_tasks.rework_count
workflow_tasks.rework_requested_at
workflow_tasks.next_rework_at
workflow_tasks.last_rework_error_code
```

- [ ] **Step 2: Add columns to SQLAlchemy models**

Add nullable/default-safe columns:

```python
# ImagePromptDraft
retry_count: int = 0
retryable: bool = True
next_retry_at: datetime | None = None
last_retry_at: datetime | None = None
last_error_code: str | None = None

# WorkflowTask
rework_count: int = 0
rework_requested_at: datetime | None = None
next_rework_at: datetime | None = None
last_rework_error_code: str | None = None
```

Use `retry_*` for Grok draft regeneration and `rework_*` for RunPod task rework so the naming matches existing UI/API language.

- [ ] **Step 3: Add indexes for worker scans**

Add indexes:

```text
ix_image_prompt_drafts_retry_scan(status, retryable, next_retry_at, updated_at)
ix_workflow_tasks_rework_scan(status, next_rework_at, updated_at)
```

- [ ] **Step 4: Write Alembic migration**

Create `20260906_0035_batch_retry_metadata.py` with additive columns only. Existing rows must default to `retry_count=0`, `retryable=true`, `rework_count=0`, with nullable timestamp/error fields.

- [ ] **Step 5: Verify migration downgrade is safe**

Downgrade should drop only the newly added indexes and columns.

---

## Task 2: Centralize Retry Classification

**Files:**
- Add: `backend/app/services/batch_retry_policy.py`
- Test: `backend/tests/test_batch_retry_policy.py`

**Interfaces:**
- Consumes: provider error/status strings from Grok and RunPod
- Produces: retry/rework decision used by services and monitors

- [ ] **Step 1: Add retry decision value object**

Create a small dataclass:

```python
@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    code: str
    reason: str
    delay_seconds: int | None = None
```

- [ ] **Step 2: Classify Grok errors**

Implement `classify_prompt_error(error: str | None, status_code: int | None = None, retry_count: int = 0)`.

Retryable:
- timeout
- connection/reset
- HTTP 429
- HTTP 500/502/503/504
- malformed response if provider returned empty/partial content

Non-retryable:
- authentication/authorization, HTTP 401/403
- invalid image payload
- missing active instruction
- unsupported workflow
- user-correctable prompt/schema validation

- [ ] **Step 3: Classify RunPod errors**

Implement `classify_runpod_error(error: str | None, provider_status: str | None = None, retry_count: int = 0)`.

Retryable:
- RunPod 429
- RunPod 5xx
- request timeout/network error
- stale `DISPATCHING` without provider job id
- provider `IN_QUEUE`/`IN_PROGRESS` older than configured stale threshold

Non-retryable:
- missing input asset
- missing prompt
- invalid workflow payload
- provider 404 `job not found` after a provider job id was recorded
- user-cancelled task

- [ ] **Step 4: Cap automatic attempts**

Use conservative backoff:

```text
attempt 1: 60 seconds
attempt 2: 5 minutes
attempt 3: 15 minutes
after attempt 3: non-auto retryable, manual only
```

- [ ] **Step 5: Add tests**

Test status-code and message combinations for retryable/non-retryable behavior.

---

## Task 3: Record Grok Draft Failures as Retryable or Final

**Files:**
- Modify: `backend/app/services/prompt_batch_service.py`
- Modify: `backend/app/services/grok_image_prompt_service.py` if needed for richer error data
- Test: `backend/tests/test_prompt_batch_service.py`
- Test: `backend/tests/test_grok_image_prompt_service.py`

**Interfaces:**
- Consumes: `ImagePromptDraft.status`, `failure_message`
- Produces: draft retry metadata and next retry scheduling

- [ ] **Step 1: Add failing test for transient Grok failure**

Create a draft in `PENDING`, simulate a transient Grok error, then assert:

```text
status = FAILED
retryable = true
retry_count remains current attempt count
next_retry_at is set
last_error_code is set
failure_message is preserved
```

- [ ] **Step 2: Add failing test for permanent Grok failure**

Simulate missing instruction or invalid image and assert:

```text
status = FAILED or MANUAL_REQUIRED
retryable = false
next_retry_at is null
last_error_code is set
```

- [ ] **Step 3: Update failure recording path**

Where `process_next_prompt_generation_draft()` marks a draft failed, call `batch_retry_policy.classify_prompt_error()` and update the new metadata fields in the same transaction.

- [ ] **Step 4: Preserve source metadata on retry**

Ensure `retry_prompt_draft()` resets only generated output and failure state, while keeping:

```text
draft.id
draft.asset_id
draft.batch_job_id
draft.created_at
sourceRelativePath
sourceZipFileName
requested_frames
```

- [ ] **Step 5: Verify batch counter refresh**

After draft retry is scheduled back to `PENDING`, `refresh_batch_job_counters()` must move the count from `prompt_failed_count` to `prompt_waiting_count`.

---

## Task 4: Make RunPod Rework Preserve the Existing Task Identity

**Files:**
- Modify: `backend/app/services/task_tracking_service.py`
- Modify: `backend/app/services/studio_api_service.py`
- Test: `backend/tests/test_history_tab_api.py`
- Test: `backend/tests/test_runpod_submission_queue.py`

**Interfaces:**
- Consumes: existing `POST /api/history/{task_id}/rework`
- Produces: same `WorkflowTask.id` resubmitted through durable queue

- [ ] **Step 1: Add regression test for same-row rework**

Create a failed `WorkflowTask` with `batch_job_id` and `prompt_draft_id`, call rework, and assert:

```text
workflow_tasks row count for prompt_draft_id stays 1
returned taskId equals original task id
batch_job_id is unchanged
prompt_draft_id is unchanged
created_at is unchanged
status = PENDING_SUBMIT
rework_count increments by 1
rework_requested_at is set
```

- [ ] **Step 2: Stop updating `created_at` during rework**

In `requeue_task_for_rework()`, remove the assignment that changes `task.created_at`. Keep `updated_at` and `rework_requested_at` as the visible rework time.

- [ ] **Step 3: Keep output cleanup local to the same task**

Delete stale `TaskOutputAsset` links for the same task before requeueing, but do not delete input assets, prompt draft, batch job, or the task row itself.

- [ ] **Step 4: Preserve payload identity**

Keep `payload_json["batchJobId"]`, `prompt_draft_id`, `request_batch_id`, and `request_item_id` as-is unless the value is missing and can be restored from the current row.

- [ ] **Step 5: Sync batch counters**

After requeue, call the same batch counter refresh path so the batch dashboard changes from failed to pending submit.

---

## Task 5: Add Batch-Level Manual Retry APIs

**Files:**
- Modify: `backend/app/api/v1/batch_jobs.py`
- Modify: `backend/app/services/batch_job_service.py`
- Test: `backend/tests/test_batch_job_service.py`

**Interfaces:**
- Adds: `POST /api/batch-jobs/{batch_job_id}/retry-failed`
- Adds: `POST /api/batch-jobs/{batch_job_id}/items/retry`

- [ ] **Step 1: Define API request shape**

Use this request body:

```json
{
  "stage": "all",
  "draftIds": [],
  "taskIds": []
}
```

Allowed `stage`: `all`, `prompt`, `runpod`.

- [ ] **Step 2: Implement owner and permission checks**

Use the existing `_scope(current_user)` behavior:
- normal operator can retry only own batch
- manager with `jobs:manage` can retry visible workers' batches
- all callers require `jobs:run`

- [ ] **Step 3: Implement retry service function**

Add:

```python
retry_failed_batch_items(
    db: Session,
    batch_job_id: str,
    *,
    actor_id: str,
    can_manage: bool,
    stage: str,
    draft_ids: list[str] | None = None,
    task_ids: list[str] | None = None,
) -> dict[str, Any]
```

It must:
- reset retryable failed Grok drafts to `PENDING`
- reset failed RunPod tasks to `PENDING_SUBMIT`
- skip completed items
- skip non-retryable items and return them in `skipped`
- never create new `WorkflowTask` rows
- refresh the batch counters before returning

- [ ] **Step 4: Add selected-items API**

`POST /api/batch-jobs/{batch_job_id}/items/retry` should use explicit `draftIds`/`taskIds` and return the same summary format.

- [ ] **Step 5: Add response contract**

Return:

```json
{
  "batchJobId": "장균은_2권_08-10화_260906",
  "promptRetried": 2,
  "runpodReworked": 3,
  "skipped": [
    {"id": "task_...", "reason": "completed"},
    {"id": "grok_draft_...", "reason": "non_retryable"}
  ],
  "batch": {}
}
```

---

## Task 6: Add Batch Detail API for Recovery UI

**Files:**
- Modify: `backend/app/api/v1/batch_jobs.py`
- Modify: `backend/app/services/batch_job_service.py`
- Test: `backend/tests/test_batch_job_service.py`

**Interfaces:**
- Adds: `GET /api/batch-jobs/{batch_job_id}`

- [ ] **Step 1: Add detail payload**

Return batch summary plus item list:

```json
{
  "batch": {},
  "items": [
    {
      "sourceFileName": "001.jpg",
      "sourceRelativePath": "2권 08화/001.jpg",
      "promptDraftId": "grok_draft_...",
      "promptStatus": "READY",
      "promptError": "",
      "promptRetryCount": 0,
      "taskId": "task_...",
      "runpodStatus": "FAILED",
      "runpodError": "RunPod HTTP 404: job not found",
      "runpodReworkCount": 1,
      "nextRetryAt": null,
      "retryable": true
    }
  ]
}
```

- [ ] **Step 2: Keep query efficient**

Load all draft rows for the batch and all task rows for those `prompt_draft_id`s in two bounded queries. Do not perform per-row queries.

- [ ] **Step 3: Normalize latest task selection**

Because the intended invariant is one task per prompt draft, detail selection should flag duplicates if existing historical data has more than one non-deleted task for a `prompt_draft_id`.

- [ ] **Step 4: Return duplicate diagnostics**

Add optional `warnings`:

```json
{"type": "duplicate_runpod_task", "promptDraftId": "...", "taskIds": ["task_a", "task_b"]}
```

This is diagnostic only; cleanup should remain an explicit admin action.

---

## Task 7: Add Batch Recovery UI

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/batchJobScreen.tsx`
- Modify: `frontend/src/styles.css`
- Test: `backend/tests/test_frontend_batch_management_contract.py`

**Interfaces:**
- Consumes: new batch detail and retry APIs
- Produces: operator-facing recovery controls in `Batch 처리`

- [ ] **Step 1: Extend API client types**

Add `BatchJobDetailResponse`, `BatchJobItemResponse`, and retry API methods:

```ts
batchJobDetail(batchJobId: string)
retryFailedBatchItems(batchJobId: string, payload)
retrySelectedBatchItems(batchJobId: string, payload)
```

- [ ] **Step 2: Open recovery from the failed-count cell**

Render the `실패` value as a button only when `failedCount > 0`. Clicking it opens a Studio-style `재처리 관리` modal for that exact batch. Render `0` as an inert gray value.

- [ ] **Step 3: Render recovery summary**

For the selected batch show:
- failed prompt count
- failed RunPod count
- retryable count
- non-retryable count
- next scheduled retry time if any

- [ ] **Step 4: Render failed/incomplete item list**

Columns:

```text
선택 | 원본 파일 | 프롬프트 상태 | RunPod 상태 | 오류 | 재처리 횟수 | 다음 재처리 | 작업
```

- [ ] **Step 5: Add actions**

Buttons:
- `상태 새로고침`: refresh selected batch detail and active dashboards without starting execution
- `선택 항목 재처리`: retry selected retryable failed items only
- `전체 실패 재처리`: retry all retryable failed prompt and RunPod items in selected batch

- [ ] **Step 6: Keep button disable rules strict**

Disable retry buttons while a request is in flight. Do not show retry controls for completed rows.

- [ ] **Step 7: Refresh after retry**

After retry API success, reload:
- active batch jobs
- batch history page
- selected batch detail
- RunPod/Prompt task history if the user is currently on that route

---

## Task 8: Add Automatic Retry Worker

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/batch_job_service.py`
- Test: `backend/tests/test_batch_job_service.py`

**Interfaces:**
- Adds: monitor-loop calls for due retry/rework items

- [ ] **Step 1: Add service functions**

Add:

```python
process_due_batch_prompt_retries(limit: int = 10) -> dict[str, Any]
process_due_batch_runpod_reworks(limit: int = 10) -> dict[str, Any]
```

- [ ] **Step 2: Claim due Grok draft retries atomically**

Select failed batch drafts where:

```text
batch_job_id is not null
status in FAILED/MANUAL_REQUIRED
retryable = true
next_retry_at <= now
retry_count < 3
```

Reset claimed rows to `PENDING`, increment `retry_count`, clear generated prompt fields, preserve source metadata.

- [ ] **Step 3: Claim due RunPod reworks atomically**

Select failed batch tasks where:

```text
batch_job_id is not null
status in FAILED/TIMED_OUT
next_rework_at <= now
rework_count < 3
deleted_at is null
```

Reset claimed rows to `PENDING_SUBMIT`, increment `rework_count`, clear provider result fields, preserve task identity.

- [ ] **Step 4: Add monitor loop integration**

In `backend/app/main.py`, run these after provider status refresh and before `refresh_batch_job_counters()`:

```python
process_due_batch_prompt_retries()
process_due_batch_runpod_reworks()
```

- [ ] **Step 5: Keep automatic retry conservative**

Do not automatically retry non-retryable failures or items already attempted 3 times. Those remain visible for manual review.

---

## Task 9: Strengthen Duplicate-Prevention Guardrails

**Files:**
- Modify: `backend/app/services/batch_job_service.py`
- Modify: `backend/app/services/studio_api_service.py`
- Test: `backend/tests/test_batch_job_service.py`
- Test: `backend/tests/test_prompt_draft_job_submission.py`

**Interfaces:**
- Consumes: `prompt_draft_id`, `batch_job_id`
- Produces: invariant that one prompt draft has one live RunPod task

- [ ] **Step 1: Add duplicate regression tests**

Cases:
- `promote_ready_batch_drafts()` does not create a second task when a failed task already exists.
- manual batch retry does not create a second task.
- direct RunPod history `재작업` does not create a second task.
- a soft-deleted task does not block explicit admin cleanup/recovery behavior.

- [ ] **Step 2: Add defensive query helper**

Create helper:

```python
live_task_for_prompt_draft(db, draft_id: str, batch_job_id: str | None) -> WorkflowTask | None
```

Use it in promotion and retry paths instead of duplicating `exists()` queries.

- [ ] **Step 3: Return clear error on unexpected duplicates**

If more than one live task already exists for a prompt draft, do not create or rework another task. Return a diagnostic warning that points to manual cleanup.

---

## Task 10: Observability and ECS Release Guide Update

**Files:**
- Modify: `docs/ecs-batch-zip-history-release-guide.md`
- Modify: `backend/app/services/batch_job_service.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Test: `backend/tests/test_observability.py`

**Interfaces:**
- Produces: release checklist and structured logs for retry lifecycle

- [ ] **Step 1: Add structured log events**

Log these events without secrets:

```text
batch.retry.prompt_scheduled
batch.retry.prompt_started
batch.retry.prompt_skipped
batch.rework.runpod_scheduled
batch.rework.runpod_started
batch.rework.runpod_skipped
batch.rework.duplicate_guard
```

- [ ] **Step 2: Update ECS guide migration section**

Add `20260906_0035_batch_retry_metadata.py` to the deployment checklist after the existing `260906_0034_batch_source_zip_name.py` migration.

- [ ] **Step 3: Add production smoke checks**

Document checks:
- `GET /api/health` reports migration head
- create a small ZIP batch
- force or simulate one failed draft/task in a non-production DB
- run retry API and confirm same IDs are preserved
- verify Batch dashboard counters change from failed to pending/active
- verify Task History shows same task ID after `재작업`

---

## Verification Commands

Run targeted backend tests:

```bash
python3.12 -m pytest \
  backend/tests/test_batch_queue_models.py \
  backend/tests/test_batch_retry_policy.py \
  backend/tests/test_prompt_batch_service.py \
  backend/tests/test_batch_job_service.py \
  backend/tests/test_history_tab_api.py \
  backend/tests/test_runpod_submission_queue.py \
  backend/tests/test_prompt_draft_job_submission.py
```

Run frontend contract and build:

```bash
python3.12 -m pytest backend/tests/test_frontend_batch_management_contract.py
npm run build
```

Run local DB migration smoke:

```bash
DATABASE_URL=sqlite:///data/dobedub-studio.db python3 -m alembic upgrade head
python3 scripts/run_local.py
```

Manual local scenario:

1. Upload a small ZIP batch.
2. Confirm Batch ID appears in `Batch 처리` history and in RunPod history.
3. Mark one Grok draft failed in local DB and call `POST /api/batch-jobs/{batch_id}/retry-failed`.
4. Confirm the same `image_prompt_drafts.id` returns to `PENDING`.
5. Mark one RunPod task failed in local DB and call the same retry API.
6. Confirm the same `workflow_tasks.id` returns to `PENDING_SUBMIT`.
7. Confirm no extra live task exists for the same `prompt_draft_id`.

Manual SQL invariant check:

```sql
select prompt_draft_id, batch_job_id, count(*) as live_tasks
from workflow_tasks
where deleted_at is null
  and prompt_draft_id is not null
group by prompt_draft_id, batch_job_id
having count(*) > 1;
```

Expected result: zero rows.

---

## Risks and Mitigations

- **Risk:** Automatic retry hides permanent input problems.
  **Mitigation:** classify validation/auth/instruction errors as non-retryable and surface them in the detail UI.

- **Risk:** Existing dirty historical rows may already have duplicate tasks per prompt draft.
  **Mitigation:** new APIs should return duplicate diagnostics and refuse to create/rework additional tasks until explicit cleanup.

- **Risk:** Reworking a task while provider status polling is still updating it can race.
  **Mitigation:** retry/rework claim updates must include a conditional status predicate and run in a single transaction.

- **Risk:** Changing `created_at` during rework distorts execution date filters and Batch ID history.
  **Mitigation:** preserve `created_at`; use `rework_requested_at`/`updated_at` for rework timing.

---

## Implementation Order

1. Add metadata migration/model fields and tests.
2. Add retry classification service and unit tests.
3. Update Grok draft failure/retry handling.
4. Correct RunPod `재작업` to preserve original task identity fields.
5. Add batch retry APIs and detail API.
6. Add Batch 처리 UI recovery controls.
7. Add automatic retry worker.
8. Strengthen duplicate-prevention tests.
9. Update ECS release guide and run full verification.

---

## Execution Choice

This plan is ready to execute after user approval. Use `superpowers:subagent-driven-development` if implementing all tasks in one session; otherwise use `superpowers:executing-plans` and commit each logical checkpoint separately.
