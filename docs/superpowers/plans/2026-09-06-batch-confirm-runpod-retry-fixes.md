# Batch Confirm and RunPod Retry Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adjust the batch request confirmation UX, remove the negative prompt column from prompt history, and make stale RunPod tasks/retries recover to visible terminal states instead of staying stuck.

**Architecture:** Keep the UX changes in the existing React screens and keep RunPod state repair in the backend task tracking boundary. The backend should treat provider 404 for an already-submitted RunPod job as a terminal provider failure, while transient network/5xx errors should remain retryable.

**Tech Stack:** React/TypeScript frontend, FastAPI backend, SQLAlchemy models/services, SQLite/RDS-compatible persistence, pytest contract tests, Vite build.

**Spec:** User request on 2026-09-06 in the current Codex task.

## Global Constraints

- Do not deploy until the user explicitly requests it.
- Preserve existing DB data; migrations are not expected for this change.
- Confirmation must be Studio app style, not browser `confirm`/`alert`.
- Default batch length must be 10 seconds.
- RunPod request/retry records must remain traceable in Task History.

---

## Findings

- `frontend/src/screens/batchJobScreen.tsx` currently shows a folder-selection notice immediately after folder selection. There is no Studio confirmation modal before batch creation.
- `frontend/src/screens/batchJobScreen.tsx` defaults `requestedFrames` to `81`, which displays as `5초`. The 10-second option is currently `161` frames.
- `frontend/src/screens/reviewScreens.tsx` still renders the prompt history header and row cell for `워크플로우 내장 Negative Prompt`.
- Local DB has two active tasks:
  - `task_20260905_162810_d7bd0c` / RunPod `97fecb86-08f6-415f-aabc-de52665b3c3a-e2`
  - `task_20260905_161615_bb4892` / RunPod `01874a84-e951-4d9e-b1a9-9cb9ff905abd-e2`
- Direct RunPod status checks returned HTTP 404 `job not found` for both active job IDs. Current monitor catches that exception and leaves the DB rows as `IN_PROGRESS`, so the UI never sees a terminal failure.
- Failed-task regeneration creates or reuses a durable queued task. If stale `IN_PROGRESS` tasks consume the active-task limit, later retry jobs can remain `PENDING_SUBMIT` until those stale tasks are terminalized.

---

### Task 1: Batch Request Confirmation UX

**Files:**
- Modify: `frontend/src/screens/batchJobScreen.tsx`
- Modify: `frontend/src/styles.css`
- Test: `backend/tests/test_frontend_batch_management_contract.py`

**Interfaces:**
- Consumes: existing `apiClient.createBatchJob()`
- Produces: Studio-style confirm modal with `진행` and `취소` actions

- [ ] **Step 1: Write/extend the frontend contract test**

Add assertions that the batch screen source does not call browser `confirm`/`alert`, has a confirmation modal state, includes copy for workflow/folder/image count/length, and defaults to `161` frames.

- [ ] **Step 2: Remove folder-selection completion notice**

In `chooseFolder()`, keep setting `selectedFiles`, `folderName`, and clearing `uploadedRows`, but remove the success notice like `N개 이미지를 선택했습니다.`. Keep the error notice for zero valid images.

- [ ] **Step 3: Change default length**

Change `useState(81)` to `useState(161)`. Update any label constant if needed so `161` displays as `161f · 10초`.

- [ ] **Step 4: Split create click from actual submit**

Add modal state such as `confirmingBatch`, and change the primary button click to open the modal only when `workflowId` and `selectedFiles` exist. Keep validation notice when required fields are missing.

- [ ] **Step 5: Add Studio-style modal**

Render a modal inside `BatchJobScreen` with:
- Title: `작업 요청 내역 확인`
- Rows: `워크플로우`, `폴더명`, `이미지수`, `길이`
- Body question: `진행하시겠습니까?`
- Buttons: `진행`, `취소`

- [ ] **Step 6: Wire modal actions**

`진행` closes the modal and calls `startBatch()`. `취소` closes the modal and resets the batch creation form: selected files, folder name, uploaded rows, notice, hidden file input value, and length back to `161`.

- [ ] **Step 7: Verify**

Run:

```bash
python3.12 -m pytest backend/tests/test_frontend_batch_management_contract.py
npm run build
```

---

### Task 2: Prompt History Negative Prompt Column Removal

**Files:**
- Modify: `frontend/src/screens/reviewScreens.tsx`
- Modify: `frontend/src/styles.css`
- Test: `backend/tests/test_frontend_batch_management_contract.py`

**Interfaces:**
- Consumes: existing prompt history API response
- Produces: prompt history table without visible negative prompt column

- [ ] **Step 1: Write/extend test**

Assert the prompt history header no longer includes `워크플로우 내장 Negative Prompt` and that the prompt history row no longer renders `item.negativePrompt` as a separate column.

- [ ] **Step 2: Remove header cell**

In `PromptGenerationHistory`, remove the negative prompt `<span>` from `.v3-prompt-history-head`.

- [ ] **Step 3: Remove row cell**

Remove the row `<div className="v3-review-prompt" title={item.negativePrompt || ""}>...`.

- [ ] **Step 4: Adjust CSS grid**

Update the prompt history grid column definition to remove the extra column so the table width no longer reserves space for it.

- [ ] **Step 5: Verify**

Run:

```bash
python3.12 -m pytest backend/tests/test_frontend_batch_management_contract.py
npm run build
```

---

### Task 3: Terminalize RunPod 404 Active Tasks

**Files:**
- Modify: `backend/app/services/job_service.py`
- Modify: `backend/app/services/studio_api_service.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Test: `backend/tests/test_history_tab_api.py`
- Test: `backend/tests/test_durable_runpod_request_batch.py`

**Interfaces:**
- Consumes: RunPod status exceptions raised by `runpod_request("GET", "/status/{jobId}")`
- Produces: durable task status `FAILED` when provider reports HTTP 404 `job not found`

- [ ] **Step 1: Add failing backend test**

Create a test where a persisted active `WorkflowTask` has `runpod_job_id`, status `IN_PROGRESS`, and the runtime status call raises `RuntimeError('RunPod HTTP 404: {"detail":"job not found"}')`. Expected result: monitor marks the task `FAILED`, records the provider message, and the row no longer appears in `active_task_ids()`.

- [ ] **Step 2: Add helper for provider-not-found detection**

Add a small helper such as `is_runpod_job_not_found_error(exc: Exception) -> bool` that checks for `RunPod HTTP 404` and `job not found`/`Not Found` in the exception string.

- [ ] **Step 3: Convert provider 404 to failed job**

In the active monitor path, catch only provider-not-found errors and update the restored job to:
- `status = "FAILED"`
- `progress = 100`
- `runpodStatus = {"status": "FAILED", "error": "..."}`

Then call `record_job()` so `workflow_tasks`, output/request-batch sync, and history behavior remain consistent.

- [ ] **Step 4: Keep transient errors retryable**

Do not terminalize DNS failures, timeout, RunPod 5xx, or unknown exceptions. Those should continue to appear in `monitor_active_jobs()["failures"]`.

- [ ] **Step 5: Verify existing stuck local rows manually**

After implementation, run one monitor cycle locally and confirm these two IDs become `FAILED`:

```bash
python3.12 -c "from scripts.run_local import load_env_file, PROJECT_ROOT; load_env_file(PROJECT_ROOT / '.env'); from backend.app.services.studio_api_service import monitor_active_jobs; print(monitor_active_jobs())"
sqlite3 -header -column data/dobedub-studio.db "select id,status,runpod_job_id,updated_at from workflow_tasks where id in ('task_20260905_162810_d7bd0c','task_20260905_161615_bb4892');"
```

- [ ] **Step 6: Verify**

Run:

```bash
python3.12 -m pytest backend/tests/test_history_tab_api.py backend/tests/test_durable_runpod_request_batch.py
```

---

### Task 4: Regeneration Dispatch Visibility

**Files:**
- Modify: `frontend/src/screens/reviewScreens.tsx`
- Modify: `backend/app/services/studio_api_service.py`
- Modify: `backend/app/services/task_policy_service.py` only if tests prove active-limit messaging is misleading
- Test: `backend/tests/test_history_tab_api.py`

**Interfaces:**
- Consumes: existing `POST /api/history/{task_id}/regenerate`
- Produces: UI-visible retry state that explains whether the retry is queued, blocked by active limit, dispatched, or completed

- [ ] **Step 1: Add test for existing retry reuse**

Persist an original failed task and an existing retry task whose payload has `regeneratedFromTaskId`. Verify the regenerate API returns the existing retry task instead of creating a duplicate.

- [ ] **Step 2: Add test for retry blocked by active limit**

Set active count to the per-user limit and create a retry. Run dispatch once. Verify the retry remains `PENDING_SUBMIT` with a visible `lastDispatchError` or API status message explaining the active limit.

- [ ] **Step 3: Improve returned regenerate payload**

Include enough fields in the regenerate response for the UI to show actual state:
- `taskId`
- `sourceTaskId`
- `status`
- `statusLabel`
- `runpodJobId`
- `lastDispatchError` when present

- [ ] **Step 4: Refresh retry status after API response**

In `reviewScreens.tsx`, after regenerate response, add the retry task to the local status map and keep the action disabled while status is `PENDING_SUBMIT`, `DISPATCHING`, `QUEUED`, `IN_QUEUE`, or `IN_PROGRESS`.

- [ ] **Step 5: Show clear queued/blocked label**

If retry status is `PENDING_SUBMIT` and `lastDispatchError` contains the active limit text, show `한도 대기`. Otherwise show `제출 대기`.

- [ ] **Step 6: Verify**

Run:

```bash
python3.12 -m pytest backend/tests/test_history_tab_api.py
npm run build
```

---

## Recommended Execution Order

1. Task 3 first, because stale active RunPod rows are the root cause that can block regeneration dispatch.
2. Task 4 second, to make retry state understandable and prevent the “요청됨인데 실행 안 됨” ambiguity.
3. Task 1 third, because it is isolated frontend UX.
4. Task 2 last, because it is a small UI column removal.

## Final Verification

Run:

```bash
python3.12 -m pytest backend/tests/test_local_server_contract.py backend/tests/test_history_tab_api.py backend/tests/test_frontend_batch_management_contract.py backend/tests/test_durable_runpod_request_batch.py
npm run build
git diff --check
```
