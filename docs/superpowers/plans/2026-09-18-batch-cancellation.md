# Batch Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Allow an operator to select active Batch jobs and stop only work that has not started, while preserving every result and in-flight operation already underway.

**Architecture:** A transactional service marks the Batch `CANCELLED`, changes prompt drafts still in `PENDING` to `CANCELLED`, invalidates unsubmitted prompt-to-RunPod promotions, and changes only `PENDING_SUBMIT` workflow tasks to `CANCELLED`. The API enforces owner/manage permissions, while the Batch history UI provides persistent row selection and a DOBEDUB confirmation modal.

**Tech Stack:** FastAPI, SQLAlchemy, React, TypeScript, Pytest, Vitest

**Spec:** User request dated 2026-09-18 in the active task.

## Global Constraints

- Preserve completed prompts, completed videos, and all generated files.
- Do not cancel `GENERATING`, `DISPATCHING`, queued, or running work.
- Stop `PENDING` prompt drafts and `PENDING_SUBMIT` video tasks only.
- Do not contact RunPod to cancel an already submitted job.
- Do not deploy as part of this task unless separately requested.

---

### Task 1: Transactional cancellation service and API

**Files:**
- Modify: `backend/app/services/batch_job_service.py`
- Modify: `backend/app/api/v1/batch_jobs.py`
- Test: `backend/tests/test_batch_job_service.py`

**Interfaces:**
- Produces: `cancel_batch_job(db, batch_job_id, actor_id, can_manage) -> dict[str, Any]`
- Produces: `POST /api/batch-jobs/{batch_job_id}/cancel`

- [x] **Step 1: Write a failing service test**

Create a Batch containing `PENDING`, `GENERATING`, and `READY` drafts plus `PENDING_SUBMIT`, `DISPATCHING`, queued, running, and completed tasks. Assert cancellation changes only the two not-started states, invalidates unsubmitted promotions, preserves completed data, and returns exact cancellation counts.

- [x] **Step 2: Run the focused test and verify RED**

Run: `python3 -m pytest -q backend/tests/test_batch_job_service.py -k cancel_batch`

Expected: failure because `cancel_batch_job` does not exist.

- [x] **Step 3: Implement the minimal transaction**

Add `BATCH_JOB_CANCELLED`, `DRAFT_CANCELLED`, and `PROMOTION_CANCELLED`. Lock or reload the target Batch, enforce owner/manage authorization, update only `PENDING` drafts and `PENDING_SUBMIT` tasks, clear promotion claims, preserve other rows, refresh counters, and commit once.

- [x] **Step 4: Add and verify API authorization coverage**

Exercise the real FastAPI endpoint with owner, manager, and unrelated operator credentials. Expect success for owner/manager, 403 for unrelated operator, and 400 when the Batch is already terminal.

- [x] **Step 5: Prevent cancelled Batch resurrection**

Keep `batch_job_detail` and counter refresh from replacing `CANCELLED` with `INCOMPLETE` or `COMPLETE`. Ensure retry endpoints reject cancelled Batches.

### Task 2: Batch history selection and confirmation UI

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/batchJobScreen.tsx`

**Interfaces:**
- Consumes: `POST /api/batch-jobs/{batch_job_id}/cancel`
- Produces: selected active Batch IDs, confirmation modal, refresh after cancellation

- [x] **Step 1: Add the typed API method**

Add `cancelBatchJob(batchJobId)` returning the updated `BatchJobResponse` and cancellation counts.

- [x] **Step 2: Add active-row selection**

Render checkboxes only for `INCOMPLETE` rows, retain selections until cancellation or explicit toggle, and add current-page select/deselect behavior.

- [x] **Step 3: Add the confirmation modal**

State that completed work remains, prompt `PENDING` and video `PENDING_SUBMIT` stop, and submitted/in-progress operations continue. Require explicit confirmation.

- [x] **Step 4: Execute cancellation and refresh**

Call the endpoint for every selected Batch, report aggregate stopped counts, clear successful selections, and reload active jobs plus the current history page.

### Task 3: Verification

**Files:**
- Verify all modified files

**Interfaces:**
- Consumes: completed Tasks 1 and 2
- Produces: verified implementation ready for a separately authorized commit/deploy

- [x] **Step 1: Run focused backend tests**

Run: `python3 -m pytest -q backend/tests/test_batch_job_service.py`

- [x] **Step 2: Build the frontend**

Run: `npm run build`

- [x] **Step 3: Run repository verification**

Run: `./scripts/verify.sh`

- [x] **Step 4: Inspect the diff**

Run: `git diff --check && git status --short`
