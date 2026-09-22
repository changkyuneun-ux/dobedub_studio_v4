# Prompt Edit RunPod Requeue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task with test-driven development.

**Goal:** Mark an edited, previously submitted prompt as `재요청`, let an authorized user explicitly requeue it after confirmation, and replace the prior video only after the regenerated video succeeds.

**Architecture:** Derive the UI requeue state from the persisted draft and its single linked workflow task rather than adding a schema flag. A focused backend command synchronizes the edited prompt into the existing task, task prompt, and RunPod request item, then resets that same task for execution while retaining its current output links. The normal successful output persistence atomically replaces those links; pending and failed regeneration leave the old output linked.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React, TypeScript, Vitest/contract tests.

**Spec:** `docs/superpowers/specs/2026-09-22-prompt-edit-runpod-requeue-design.md`

## Global Constraints

- Reuse the existing `WorkflowTask` ID and relationship graph; do not create a replacement task.
- Do not submit during prompt save. Submission occurs only through the explicit `재요청` action.
- Preserve old output links throughout pending/running/failure and replace them only after new outputs are successfully persisted.
- Reject ambiguous multiple-task linkage and active tasks with a clear conflict response.
- Preserve unrelated untracked workflow metadata documents.
- Do not commit, push, or deploy in this turn because the current request authorizes implementation only; repository `AGENTS.md` requires explicit authorization for those actions.

## Review Focus

- Output preservation must not cause the job layer to treat old output assets as the new run's completed output.
- Prompt text must be synchronized consistently across `ImagePromptDraft`, `WorkflowTask` payload/snapshot, `TaskPrompt`, and `RunpodRequestItem`.
- The frontend confirmation text must match the approved Korean copy exactly.
- Existing RunPod batch/manual-submit behavior must remain unchanged.

---

### Task 1: Expose the derived requeue state in prompt history

**Files:**
- Modify: `backend/app/services/prompt_batch_service.py`
- Modify: `frontend/src/api/client.ts`
- Test: `backend/tests/test_prompt_batch_api.py`

- [ ] Add an API test with one terminal linked task whose execution prompt differs from the edited READY draft; assert `requeueRequired: true` and the existing task ID.
- [ ] Run the focused test and confirm it fails because the response does not yet expose the state.
- [ ] Add a small comparison helper that resolves exactly one linked task and compares normalized persisted execution prompt text to the draft positive prompt.
- [ ] Return `requeueRequired`, `linkedTaskId`, and a non-actionable reason/state for zero, multiple, or active-task linkage.
- [ ] Extend the frontend response type without changing existing required fields.
- [ ] Re-run the focused test and existing prompt batch API tests.

### Task 2: Add the explicit prompt-draft requeue command

**Files:**
- Modify: `backend/app/api/v1/prompts.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Modify: `backend/app/services/prompt_batch_service.py` or add a narrowly scoped service beside it
- Test: `backend/tests/test_prompt_batch_api.py`
- Test: `backend/tests/test_task_tracking_service.py`

- [ ] Add failing API/service tests for: manager authorization, single terminal task reuse, active-task conflict, multiple-task conflict, and missing-task response.
- [ ] Assert the successful command keeps the same task ID and synchronizes prompt text into the task payload/snapshot, `TaskPrompt`, and linked `RunpodRequestItem`.
- [ ] Add `POST /api/prompts/image-drafts/{draft_id}/requeue-runpod`.
- [ ] Implement the transactional command with row locking where supported and reuse the existing task reset primitives.
- [ ] Reset provider/job execution identifiers and retry state while keeping batch, draft, input asset, and request-item relationships intact.
- [ ] Re-run focused API and task-tracking tests.

### Task 3: Preserve the old output until regenerated output succeeds

**Files:**
- Modify: `backend/app/services/task_tracking_service.py`
- Modify if required: `backend/app/services/job_service.py`
- Test: `backend/tests/test_task_tracking_service.py`
- Test: `backend/tests/test_job_service.py`

- [ ] Add failing tests proving requeue retains current task-output links while the restored runtime job starts with no current `outputAssets`.
- [ ] Add a failing test proving failed regeneration leaves old links intact.
- [ ] Add a failing test proving successful regeneration replaces old links with the newly saved output assets.
- [ ] Split task reset semantics so prompt requeue can preserve linked outputs without presenting them as current-run results.
- [ ] Ensure `_replace_output_assets` is invoked only when a newly persisted successful output set is available; pending/running/failure snapshots must not clear preserved links.
- [ ] Re-run task tracking and job service suites.

### Task 4: Add the `재요청` interaction and confirmation

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/reviewScreens.tsx`
- Modify if needed: `frontend/src/styles.css`
- Test: `backend/tests/test_frontend_batch_management_contract.py`

- [ ] Add a failing frontend contract test asserting the RunPod cell renders `재요청` for `requeueRequired` drafts and calls the dedicated endpoint only after confirmation.
- [ ] Add the API client method for the requeue endpoint.
- [ ] Render `재요청` as an action in the existing RunPod column without changing other status labels.
- [ ] Before submission, show exactly: `기존 영상이 있는 경우 덮어쓰기가 됩니다. 진행하시겠습니까?`
- [ ] On cancel, perform no request. On confirm, call the endpoint, refresh the row/list, and surface server errors through the existing feedback pattern.
- [ ] Re-run the frontend contract test and build.

### Task 5: Regression verification

**Files:**
- Verify only; no production changes unless a failing test identifies an in-scope defect.

- [ ] Run focused backend tests for prompt history, task tracking, RunPod request batches, and job persistence.
- [ ] Run `npm run build`.
- [ ] Run `python3 -m compileall -q backend/app`.
- [ ] Run `./scripts/verify.sh` and report every failure by name, including pre-existing failures.
- [ ] Inspect `git diff --check` and `git status --short`; confirm only scoped implementation files plus the new plan are changed, while unrelated untracked documents remain untouched.
