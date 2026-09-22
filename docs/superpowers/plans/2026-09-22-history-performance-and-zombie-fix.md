# History Performance and Zombie Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent legacy RunPod 404 failures from appearing active, make batch failure detail load only one 10-row server page, and paginate webtoon cut history in 10-row pages with exact totals.

**Architecture:** Keep existing mutation/retry endpoints intact. Add a read-only paginated batch-failure endpoint and exact-count job listing, while tightening 404 reconciliation so only genuinely active jobs enter a grace window.

**Tech Stack:** FastAPI, SQLAlchemy, React/TypeScript, pytest contract and service tests.

**Spec:** Approved in-chat designs from 2026-09-22.

## Global Constraints

- Preserve prompt draft, WorkflowTask, BatchJob, and RunPod request identity links.
- Do not create migrations or change workflow JSON contracts.
- Page size is fixed at 10 for both requested history surfaces.
- Existing retry-all and selected-retry mutations remain authoritative.

## Review Focus

- Legacy failed 404 with no manifest remains failed.
- Legacy failed 404 with a durable manifest recovers to completed.
- Batch failure pagination includes prompt, promotion, RunPod, and orphan-task failures.
- Empty and final pages return exact totals without loading all ORM rows.
- Filter changes reset webtoon history to page one and next-page state uses total.

---

### Task 1: RunPod 404 zombie-state guard

**Files:** `backend/app/services/job_service.py`, `backend/app/services/studio_api_service.py`, `backend/tests/test_job_service.py`, `backend/tests/test_history_tab_api.py`

- [ ] Add failing tests proving legacy failed jobs stay failed without a manifest and recover only when a manifest exists.
- [ ] Run focused tests and confirm the expected failures.
- [ ] Separate legacy reconciliation from active-job grace handling.
- [ ] Run focused tests and confirm they pass.

### Task 2: Paginated batch failure detail

**Files:** `backend/app/services/batch_job_service.py`, `backend/app/api/v1/batch_jobs.py`, `frontend/src/api/client.ts`, `frontend/src/screens/batchJobScreen.tsx`, `backend/tests/test_batch_job_service.py`, `backend/tests/test_frontend_batch_management_contract.py`

- [ ] Add failing tests for a 10-row failure page, exact total, and immediate modal loading shell.
- [ ] Add a read-only `/batch-jobs/{id}/failures?page=&pageSize=10` endpoint using filtered SQL queries and aggregate counts.
- [ ] Switch the modal to server pages and keep retry mutations unchanged.
- [ ] Run service and contract tests.

### Task 3: Webtoon cut history pagination

**Files:** `backend/app/services/webtoon_cut_service.py`, `frontend/src/api/client.ts`, `frontend/src/screens/webtoonCutScreen.tsx`, `backend/tests/test_webtoon_cut_service.py`, `backend/tests/test_frontend_webtoon_cut_contract.py`

- [ ] Add failing tests for fixed 10-row requests and exact total/page rendering.
- [ ] Return total from the job list and render total-derived controls.
- [ ] Run service and frontend contract tests.

### Task 4: Verification

- [ ] Run focused suites for all changed areas.
- [ ] Run `scripts/verify.sh` and `git diff --check`.
- [ ] Review the final diff for identity-link and mutation-side effects.
