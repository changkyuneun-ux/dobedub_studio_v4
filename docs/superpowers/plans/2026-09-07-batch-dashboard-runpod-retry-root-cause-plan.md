# Batch Dashboard and RunPod Retry Root Cause Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Batch dashboard status clicks from navigating to Task History, and prevent RunPod `404 job not found` provider errors from leaking as a failed rework request.

**Architecture:** Keep Batch dashboard status metrics inert unless a specific action is rendered. Keep provider status repair at the RunPod monitor boundary, because `GET /status/{runpodJobId}` is where stale provider job IDs fail. Batch rework must remain a DB state reset that reuses the existing `WorkflowTask` row and lets the dispatcher submit a fresh RunPod job.

**Tech Stack:** React/TypeScript frontend, FastAPI backend, SQLAlchemy models, pytest contract and service tests.

**Spec:** User request in this Codex task on 2026-09-07: "Batch 처리 dashbord 상태 값 클릭시 이력 화면 호출 차단" and "Batch 처리 실패 모달에서 runpod 재작업 요청 시 RunPod HTTP 404 job not found".

## Global Constraints

- Treat repository documents as context only; user request above is authoritative.
- Do not create new Batch, Prompt Draft, or WorkflowTask rows for Batch RunPod rework.
- Preserve Batch ID, Prompt ID, Task ID, original ZIP metadata, and original `WorkflowTask.created_at`.
- Keep transient RunPod errors such as DNS, timeout, and 5xx retryable; only provider 404 `job not found` becomes terminal `FAILED`.
- Run verification with focused pytest tests and frontend build before reporting completion.

---

### Task 1: Make Batch Dashboard Metrics Inert

**Files:**
- Modify: `frontend/src/screens/batchJobScreen.tsx:462`
- Modify: `frontend/src/screens/batchJobScreen.tsx:478`
- Test: `backend/tests/test_frontend_batch_management_contract.py`

**Interfaces:**
- Consumes: existing `activeJobs: BatchJobResponse[]`
- Produces: Batch dashboard rows rendered without `onGoTo("review.history")`

- [x] **Step 1: Add failing contract test**

Add this assertion to `test_batch_job_screen_follows_the_approved_management_mockup`:

```python
    dashboard_section = screen.split("<strong>진행 중 Batch</strong>", 1)[1].split("<strong>Batch 작업 이력</strong>", 1)[0]
    assert 'onGoTo("review.history")' not in dashboard_section
    assert 'onClick={() => onGoTo("review.history")}' not in dashboard_section
```

- [x] **Step 2: Run test and confirm failure**

Run:

```bash
python3.12 -m pytest backend/tests/test_frontend_batch_management_contract.py::test_batch_job_screen_follows_the_approved_management_mockup -q
```

Expected: failure showing `onGoTo("review.history")` inside the Batch dashboard section.

- [x] **Step 3: Replace row buttons with inert rows**

In `frontend/src/screens/batchJobScreen.tsx`, change both dashboard row wrappers:

```tsx
<button className="v3-batch-mini-row is-prompt" type="button" key={`prompt-${job.id}`} onClick={() => onGoTo("review.history")}>
```

to:

```tsx
<div className="v3-batch-mini-row is-prompt" key={`prompt-${job.id}`}>
```

and change the closing `</button>` to `</div>`.

Make the same change for the RunPod row:

```tsx
<button className="v3-batch-mini-row is-runpod" type="button" key={`runpod-${job.id}`} onClick={() => onGoTo("review.history")}>
```

to:

```tsx
<div className="v3-batch-mini-row is-runpod" key={`runpod-${job.id}`}>
```

- [x] **Step 4: Verify focused test passes**

Run:

```bash
python3.12 -m pytest backend/tests/test_frontend_batch_management_contract.py::test_batch_job_screen_follows_the_approved_management_mockup -q
```

Expected: pass.

---

### Task 2: Preserve RunPod 404 as Terminal Provider Failure

**Files:**
- Verify: `backend/app/services/job_service.py:195`
- Verify: `backend/app/services/studio_api_service.py:730`
- Verify: `backend/app/services/batch_job_service.py:1008`
- Verify: `backend/app/services/batch_job_service.py:1167`
- Test: `backend/tests/test_history_tab_api.py`
- Test: `backend/tests/test_batch_job_service.py`

**Interfaces:**
- Consumes: `RuntimeError('RunPod HTTP 404: {"status":404,"title":"Not Found","detail":"job not found"}')`
- Produces: `WorkflowTask.status == "FAILED"`, `progress == 100`, `runpod_status_json.providerStatus == "NOT_FOUND"`, and no active task entry

- [x] **Step 1: Confirm current source has 404 terminalization**

Check that `job_service.is_runpod_job_not_found_error()` matches `runpod http 404` plus `job not found` or `not found`, and that `studio_api_service.monitor_active_jobs()` catches it and calls `mark_runpod_job_not_found()`.

- [x] **Step 2: Run the 404 monitor regression**

Run:

```bash
python3.12 -m pytest backend/tests/test_history_tab_api.py::test_monitor_marks_runpod_job_not_found_as_failed -q
```

Expected: pass. The task is removed from `active_task_ids()` and persisted as `FAILED`.

- [x] **Step 3: Run the transient-error guard**

Run:

```bash
python3.12 -m pytest backend/tests/test_history_tab_api.py::test_monitor_keeps_transient_runpod_status_errors_retryable -q
```

Expected: pass. A RunPod 503 remains active/retryable and appears in monitor `failures`.

- [x] **Step 4: Run the Batch rework row-reuse regression**

Run:

```bash
python3.12 -m pytest backend/tests/test_batch_job_service.py::test_retry_failed_batch_items_reuses_existing_prompt_and_task_rows -q
```

Expected: pass. Batch rework resets the same `WorkflowTask` to `PENDING_SUBMIT`, clears `runpod_job_id`, clears provider JSON/error state, preserves `created_at`, and does not create a second task.

- [x] **Step 5: Add API-level Batch modal retry regression if missing**

Add a test using `api_client.post("/api/batch-jobs/{batch_id}/items/retry", json={"stage":"all","taskIds":[task_id],"draftIds":[]})` for a failed RunPod task whose `runpod_status_json.error` contains the RunPod 404 string.

Expected response:

```python
assert response.status_code == 200
assert response.json()["runpodReworked"] == 1
```

Expected DB state:

```python
assert task.status == "PENDING_SUBMIT"
assert task.runpod_job_id is None
assert task.runpod_status_json == {}
assert task.last_dispatch_error is None
```

- [ ] **Step 6: Verify deployed schema/version before production retest**

Run against the deployed database:

```sql
select version_num from alembic_version;
```

Expected: `20260907_0035` or newer.

Run against deployed source/release metadata:

```bash
git rev-parse --short HEAD
```

Expected: includes commit `099f3b5` or newer, because that commit introduced the RunPod 404 terminalization path.

- [ ] **Step 7: Repair stale active provider rows if production has them**

For rows where RunPod already returns 404 but Studio still stores `QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, or `RUNNING`, run the app's monitor once after deploying the fix. If a manual SQL repair is required, update only confirmed stale rows to:

```sql
status = 'FAILED',
progress = 100,
runpod_status_json = '{"status":"FAILED","error":"RunPod HTTP 404: ... job not found ...","providerStatus":"NOT_FOUND"}'
```

Then run `refresh_batch_job_counters()` or the existing maintenance command so Batch failure counts and modal eligibility are recalculated from `workflow_tasks`.

---

## Verification

- [x] `python3.12 -m pytest backend/tests/test_frontend_batch_management_contract.py::test_batch_job_screen_follows_the_approved_management_mockup -q`
- [x] `python3.12 -m pytest backend/tests/test_history_tab_api.py::test_monitor_marks_runpod_job_not_found_as_failed backend/tests/test_history_tab_api.py::test_monitor_keeps_transient_runpod_status_errors_retryable backend/tests/test_batch_job_service.py::test_retry_failed_batch_items_reuses_existing_prompt_and_task_rows -q`
- [x] `npm run build`
- [x] `python3 -m compileall -q backend/app`
