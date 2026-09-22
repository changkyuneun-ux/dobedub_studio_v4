# Prompt History Manual Edit and Immediate RunPod Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow an owner or manager to repair a failed Positive Prompt from Prompt History, mark it successful, and durably enqueue exactly one RunPod task before the save response returns.

**Architecture:** Preserve the existing draft PATCH behavior and add an opt-in `submitImmediately` recovery command. A focused orchestration service owns permission/state checks and delegates to the existing Batch promotion or standalone request-batch paths; Prompt History sends one command and renders its draft/submission result.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, React, TypeScript, Pytest, existing frontend source-contract tests.

**Spec:** `docs/superpowers/specs/2026-09-22-prompt-history-manual-submit-design.md`

## Global Constraints

- Visible UI changes are limited to Prompt History.
- Existing Prompt Management edits keep their request and response shape when `submitImmediately` is absent.
- Existing Batch, Grok, RunPod dispatcher, workflow JSON, and Param Config contracts remain compatible.
- A manager may repair another worker's draft, but the RunPod task remains owned by the original worker.
- Submission means a durable local `PENDING_SUBMIT` task exists before the response; never wait for external RunPod synchronously.
- Never create a second non-deleted request item or WorkflowTask for one prompt draft.
- Never mutate an immutable RunPod request snapshot.
- Add an Alembic migration only if tests prove existing constraints cannot enforce idempotency.
- Do not commit, push, or deploy unless explicitly requested.

## Review Focus

- Concurrent saves must produce one task and one conflict, never duplicate work.
- Manager repair must preserve the original worker and identify the manager as submitter.
- Queue creation failure must preserve the repaired prompt and report `runpodQueued=false`.
- Ordinary Prompt Management edits must not auto-submit.
- Legacy `MANUAL_REQUIRED` rows must behave like failures without data migration.

---

### Task 1: Normalize Empty Grok Results to Failed

**Files:**
- Modify: `backend/app/services/prompt_batch_service.py`
- Modify: `backend/tests/test_prompt_batch_service.py`
- Modify: `backend/tests/test_history_tab_api.py`

**Interfaces:**
- Retains: `PROMPT_FAILURE_STATES = {"FAILED", "MANUAL_REQUIRED"}` for historical filtering.
- Changes: `_process_draft(db, draft)` stores a blank provider result as `FAILED`.
- Produces failure message: `Grok 응답에 Positive Prompt가 없어 수동 입력이 필요합니다.`

- [ ] **Step 1: Write a failing blank-result test**

Stub `generate_image_prompt` with an empty `positive_prompt`. Assert the draft and latest `PromptGenerationAttempt` are `FAILED`, the prompt is null, and the failure message mentions manual input.

```python
def test_blank_grok_result_is_failed(db_session, monkeypatch):
    draft = _pending_draft(db_session, draft_id="draft_blank")
    monkeypatch.setattr(service, "generate_image_prompt", lambda *_args, **_kwargs: SimpleNamespace(
        positive_prompt="", warnings=["manual_input_required"],
        image_type="indoor_background", raw_response={}
    ))
    result = service._process_draft(db_session, draft)
    assert result["status"] == service.DRAFT_FAILED
    assert result["positivePrompt"] is None
    assert "수동 입력" in result["error"]
```

- [ ] **Step 2: Run it and confirm RED**

Run: `python3 -m pytest -q backend/tests/test_prompt_batch_service.py -k blank_grok_result`

Expected: FAIL because blank results currently become `MANUAL_REQUIRED`.

- [ ] **Step 3: Implement the explicit branch**

```python
if result.positive_prompt:
    draft.status = DRAFT_READY
    draft.failure_message = None
    attempt.status = DRAFT_READY
else:
    draft.status = DRAFT_FAILED
    draft.failure_message = "Grok 응답에 Positive Prompt가 없어 수동 입력이 필요합니다."
    attempt.status = DRAFT_FAILED
    attempt.failure_message = draft.failure_message
```

Preserve warnings and the raw provider response for audit.

- [ ] **Step 4: Pin legacy filtering**

Add an API test proving `generationStatus=FAILED` returns both `FAILED` and legacy `MANUAL_REQUIRED` rows.

- [ ] **Step 5: Run Task 1 tests**

Run: `python3 -m pytest -q backend/tests/test_prompt_batch_service.py backend/tests/test_history_tab_api.py`

Expected: PASS.

---

### Task 2: Permission-Aware Failed-Draft Repair

**Files:**
- Modify: `backend/app/services/prompt_batch_service.py`
- Modify: `backend/app/api/v1/prompts.py`
- Modify: `backend/tests/test_prompt_batch_service.py`
- Modify: `backend/tests/test_prompt_batch_api.py`

**Interfaces:**
- Produces: `repair_failed_prompt_draft(db: Session, draft_id: str, *, actor_id: str, can_manage: bool, positive_prompt: str) -> dict[str, Any]`.
- Keeps `update_prompt_draft` owner-only by default for existing callers.
- Produces distinct not-found, permission, validation, and conflict errors for HTTP 404/403/400/409.

- [ ] **Step 1: Write failing permission and state tests**

Cover owner repair, manager repair, foreign-user denial, blank input, `GENERATING` denial, legacy `MANUAL_REQUIRED`, and an existing WorkflowTask/request-item conflict.

```python
def test_manager_repairs_another_workers_failed_draft(db_session):
    draft = _failed_draft(db_session, owner="worker-a", status="FAILED")
    result = service.repair_failed_prompt_draft(
        db_session, draft.id, actor_id="manager", can_manage=True,
        positive_prompt="A subject turns gently while the camera remains still.",
    )
    assert result["status"] == "READY"
    assert result["error"] is None
```

- [ ] **Step 2: Run and confirm RED**

Run: `python3 -m pytest -q backend/tests/test_prompt_batch_service.py -k "repair or manager"`

Expected: FAIL because the repair API does not exist.

- [ ] **Step 3: Implement locked repair**

Load the draft with `with_for_update()`. Validate ownership or `can_manage`, accept only `FAILED`/`MANUAL_REQUIRED`, reject blank input, and reject any existing non-deleted `WorkflowTask` or `RunpodRequestItem`. Set the prompt, status `READY`, clear failure data, remove `manual_input_required`, refresh batch counts, and commit.

```python
if draft.created_by != actor_id and not can_manage:
    raise PromptDraftPermissionError("다른 작업자의 프롬프트를 수정할 권한이 없습니다.")
if str(draft.status).upper() not in PROMPT_FAILURE_STATES:
    raise PromptDraftConflictError("실패한 프롬프트만 수동 복구할 수 있습니다.")
```

- [ ] **Step 4: Map API errors and manager permission**

Pass `has_permission(current_user.permissions, "jobs:manage")`. Map validation 400, permission 403, missing 404, and conflict 409. Preserve the current direct draft response when `submitImmediately` is false.

- [ ] **Step 5: Add endpoint authorization tests**

Use two workers and one manager. Assert owner/manager success, foreign user 403, blank input 400, conflict 409, and missing draft 404.

- [ ] **Step 6: Run Task 2 tests**

Run: `python3 -m pytest -q backend/tests/test_prompt_batch_service.py backend/tests/test_prompt_batch_api.py`

Expected: PASS.

---

### Task 3: Enqueue Exactly One RunPod Task

**Files:**
- Create: `backend/app/services/prompt_recovery_service.py`
- Create: `backend/tests/test_prompt_recovery_service.py`
- Modify: `backend/app/services/batch_job_service.py`
- Modify: `backend/app/services/studio_api_service.py`
- Modify: `backend/app/api/v1/prompts.py`
- Modify: `backend/tests/test_batch_job_service.py`
- Modify: `backend/tests/test_durable_runpod_request_batch.py`

**Interfaces:**
- Produces: `repair_and_submit_prompt(db: Session, draft_id: str, *, actor: dict[str, object], can_manage: bool, positive_prompt: str) -> dict[str, Any]`.
- Produces: `promote_ready_batch_draft(draft_id: str) -> dict[str, Any]`, scoped to one draft.
- Returns `draft`, `promptSaved`, `runpodQueued`, `runpodTaskId`, `runpodStatus`, and `submissionError`.

- [ ] **Step 1: Write failing standalone recovery tests**

Assert a manager repair creates one immutable `RunpodRequestItem` and one `WorkflowTask(status="PENDING_SUBMIT")`, owned by the draft creator. A repeated call must conflict and leave both counts at one.

```python
result = recovery.repair_and_submit_prompt(
    db_session, draft.id,
    actor={"id": "manager", "name": "Manager", "permissions": ["jobs:manage", "jobs:run"]},
    can_manage=True,
    positive_prompt="A person makes a subtle hand gesture.",
)
assert result["runpodQueued"] is True
task = db_session.scalar(select(WorkflowTask).where(WorkflowTask.prompt_draft_id == draft.id))
assert task.status == "PENDING_SUBMIT"
assert task.user_id == "worker-a"
```

- [ ] **Step 2: Write failing Batch recovery tests**

Assert a Batch draft inherits Batch ID, workflow, requested frames, resolution tier, and original worker. Assert a cancelled Batch is rejected with zero tasks.

- [ ] **Step 3: Run and confirm RED**

Run: `python3 -m pytest -q backend/tests/test_prompt_recovery_service.py backend/tests/test_batch_job_service.py -k "repair or promote_ready_batch_draft"`

Expected: FAIL because orchestration and scoped promotion do not exist.

- [ ] **Step 4: Extract target-scoped Batch promotion**

Refactor the current `promote_ready_batch_drafts()` inner operation into a helper that claims only the requested ID, uses `job_payload_from_prompt_draft`, applies Batch ID/resolution, calls `create_job`, and marks `TASK_CREATED` or `FAILED`. The periodic sweep must reuse the same helper.

- [ ] **Step 5: Implement recovery orchestration**

Call Task 2 repair first. For Batch drafts, restore `promotion_status=PENDING` and invoke the scoped promotion. For standalone drafts, call `studio_api_service.create_runpod_request_batch` with original owner as `workerId` and acting user as submitter. Require a returned local task with `PENDING_SUBMIT`.

- [ ] **Step 6: Preserve repaired text on queue failure**

If request materialization fails, retain `READY` and the prompt, record existing promotion/request failure state, and return `runpodQueued=false` plus `submissionError`. Never revert the prompt to failed.

- [ ] **Step 7: Enforce idempotency**

Check for an existing request item/task before repair and before materialization. Use row locking and conditional update. Add a migration only if the concurrency test proves a DB constraint is required.

- [ ] **Step 8: Wire the opt-in endpoint path**

```python
if payload.get("submitImmediately"):
    return repair_and_submit_prompt(
        db, draft_id,
        actor={"id": current_user.id, "name": current_user.name,
               "role": current_user.role, "permissions": current_user.permissions},
        can_manage=has_permission(current_user.permissions, "jobs:manage"),
        positive_prompt=payload.get("positivePrompt"),
    )
```

- [ ] **Step 9: Run Task 3 integration tests**

Run: `python3 -m pytest -q backend/tests/test_prompt_recovery_service.py backend/tests/test_batch_job_service.py backend/tests/test_durable_runpod_request_batch.py backend/tests/test_runpod_submission_queue.py`

Expected: PASS with exactly one task per repaired draft.

---

### Task 4: Prompt History Preview and Recovery Editor

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/reviewScreens.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `backend/tests/test_frontend_batch_management_contract.py`
- Modify: `backend/tests/test_history_tab_api.py`

**Interfaces:**
- Produces `PromptRecoveryResponse` matching Task 3.
- Produces `apiClient.repairAndSubmitImagePromptDraft(draftId, positivePrompt)`.
- Adds local preview/editor/saving state only inside `PromptGenerationHistory`.

- [ ] **Step 1: Write failing frontend contract tests**

Assert source contains the preview button, `ProtectedAssetPreview`, editor textarea, `submitImmediately: true`, `canUse` checks, response-based row replacement, and `프롬프트 생성` header.

```python
assert "promptHistoryImagePreview" in source
assert "ProtectedAssetPreview" in source
assert "promptHistoryEditor" in source
assert "submitImmediately: true" in source
assert 'canUse(user, "jobs:manage")' in source
assert "PromptRecoveryResponse" in client
```

- [ ] **Step 2: Run and confirm RED**

Run: `python3 -m pytest -q backend/tests/test_frontend_batch_management_contract.py backend/tests/test_history_tab_api.py -k prompt_history`

Expected: FAIL because the UI and typed client do not exist.

- [ ] **Step 3: Add the typed client wrapper**

```typescript
export type PromptRecoveryResponse = {
  draft: GrokImagePromptDraftResponse;
  promptSaved: boolean;
  runpodQueued: boolean;
  runpodTaskId?: string | null;
  runpodStatus?: string | null;
  submissionError?: string | null;
};
```

Add `repairAndSubmitImagePromptDraft` using PATCH with `{ positivePrompt, submitImmediately: true }`. Do not change existing `updateImagePromptDraft` callers.

- [ ] **Step 4: Implement the image preview**

Wrap the thumbnail in a button, stop click propagation, and open an existing-style `ProtectedAssetPreview` modal. Support backdrop, close button, Escape, and focus restoration.

- [ ] **Step 5: Implement the recovery editor**

Import `canUse`. Permit `FAILED`/`MANUAL_REQUIRED` with no `runpodTaskId` when the user has `prompts:build` and is owner or has `jobs:manage`. Show failure reason separately, validate nonblank text, and disable save while pending.

- [ ] **Step 6: Apply response state without page reload**

Replace the matching item with `response.draft` plus returned task/status, update the selected detail, preserve filters/page, and display either:

- `프롬프트를 저장하고 RunPod 요청 대기열에 등록했습니다.`
- `프롬프트 저장 완료 · RunPod 요청 실패: {submissionError}`

- [ ] **Step 7: Normalize labels**

Change `생성 결과` to `프롬프트 생성`; render `READY` as `SUCCESS` and both failure states as `FAILED`. Keep filter value `FAILED` so historical rows remain included.

- [ ] **Step 8: Add minimal scoped styles**

Reuse current modal/button tokens. Add only image-button and editor layout selectors; do not change table grid or other history screens.

- [ ] **Step 9: Run frontend verification**

Run: `python3 -m pytest -q backend/tests/test_frontend_batch_management_contract.py backend/tests/test_history_tab_api.py`

Run: `npm --prefix frontend run build`

Expected: PASS.

---

### Task 5: Cross-Flow Regression and Full Verification

**Files:**
- Modify only tests required by verified failures; do not broaden production scope.

**Interfaces:**
- Consumes Tasks 1–4.
- Produces no new application interface.

- [ ] **Step 1: Run affected backend suites**

Run: `python3 -m pytest -q backend/tests/test_prompt_batch_service.py backend/tests/test_prompt_batch_api.py backend/tests/test_prompt_recovery_service.py backend/tests/test_batch_job_service.py backend/tests/test_durable_runpod_request_batch.py backend/tests/test_runpod_submission_queue.py backend/tests/test_history_tab_api.py`

Expected: PASS.

- [ ] **Step 2: Reconfirm the five review-focus cases**

Use tests to prove one task per draft, original-owner preservation, no submission for ordinary edits, prompt preservation after queue failure, and legacy failure filtering.

- [ ] **Step 3: Run repository verification**

Run: `./scripts/verify.sh`

Expected: backend compile/tests, frontend webtoon-cut tests, frontend build, and diff whitespace checks pass.

- [ ] **Step 4: Review final scope**

Run: `git diff --check && git diff --stat && git status --short`

Expected: only files named in this plan plus an optional idempotency migration/test; no workflow JSON, Param Config, Docker, dependency, or deployment files.
