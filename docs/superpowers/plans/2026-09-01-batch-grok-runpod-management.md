# Batch Grok Prompt and RunPod Request Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users upload many images, generate Grok prompts per image, review and edit those prompt pairs, then submit selected pairs to RunPod one at a time while preserving durable prompt and execution history.

**Architecture:** The application gains two desktop screens under Generate: Prompt Generation Management owns image-to-prompt work, and RunPod Request Management owns durable execution requests. `image_prompt_drafts` remains the image-level prompt pair record; additive batch and attempt tables provide progress and auditability; `workflow_tasks` remains the sole source of RunPod task status and outputs. A DB-claimed dispatcher creates at most one new RunPod submission when the local policy and endpoint availability permit it, so browser or session termination never cancels queued work.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, MySQL/SQLite-compatible migrations, React/TypeScript, existing v4 CSS design tokens, Grok image prompt client, RunPod Serverless REST API.

**Spec:** `docs/superpowers/specs/2026-08-31-grok-vision-first-priority-plan.md`, `docs/superpowers/specs/2026-08-31-grok-instruction-admin-mockup.html`, and the approved desktop prompt/RunPod flow mockup.

## Global Constraints

- A Prompt Generation item is exactly one uploaded image in this release; multi-keyframe grouping is explicitly deferred.
- Every Grok generation request requires a selected active workflow and that workflow's active JSON instruction set.
- Instruction content is JSON-file backed, not DB-backed. Markdown import converts a source document to the selected workflow's JSON instruction set.
- A workflow owns exactly one instruction set. Inside that set, `CORE` and `ROUTER` each occur at most once; `GUIDE` may occur many times.
- RunPod requests are accepted into `REQUEST_WAITING`, never rejected solely because active capacity is full. The dispatcher submits one request only after availability and policy checks pass.
- RunPod state vocabulary is `REQUEST_WAITING`, `RUNPOD_QUEUE`, `RUNPOD_IN_PROGRESS`, `COMPLETED`, and `FAILED`. Cancelled and timed-out remote jobs normalize to `FAILED` for this flow.
- User active-task and global active-task policy defaults remain 3 and 10 and are administered through the existing Task Policy menu.
- Each RunPod request sends the source input asset, final editable positive and negative prompts, requested length `49`, `81`, or `161`, fixed FPS `16`, and a server-generated seed. All other node settings remain the registered workflow defaults.
- Image width and height are passed as uploaded. Do not add Wan range rejection or ratio normalization; record both source dimensions and submitted dimensions for troubleshooting.
- No deployment, Git push, or destructive data migration is part of this implementation plan.

---

## File and Responsibility Map

| File | Responsibility |
| --- | --- |
| `backend/app/db/models.py` | Add durable batch, Grok attempt, and dispatch metadata models/columns. |
| `backend/app/db/migrations/versions/20260901_0026_batch_prompt_runpod_queue.py` | Additive database migration and indexes. |
| `backend/app/services/grok_instruction_service.py` | Resolve one workflow-scoped JSON instruction set and validate role cardinality. |
| `backend/app/services/grok_image_prompt_service.py` | Build one image-plus-instruction Grok request and return response telemetry. |
| `backend/app/services/prompt_batch_service.py` | Own prompt batches, image draft lifecycle, retries, and prompt history DTOs. |
| `backend/app/services/runpod_dispatch_service.py` | Claim waiting work, enforce limits, submit serially, reconcile remote state, and recover after restart. |
| `backend/app/services/task_tracking_service.py` | Expose RunPod history DTOs built from `workflow_tasks` and linked prompt records. |
| `backend/app/api/v1/prompts.py` | Add prompt batch, item retry/edit, and prompt history APIs. |
| `backend/app/api/v1/jobs.py` | Add queued RunPod batch submission APIs; retain legacy single-job compatibility. |
| `backend/app/main.py` | Start and stop the durable dispatcher monitor exactly once per process. |
| `frontend/src/router.ts` | Register Generate prompt-management and RunPod-request-management routes. |
| `frontend/src/helpers/navigation.ts` | Replace Workspace navigation with the two approved Generate menu entries. |
| `frontend/src/api/client.ts` | Typed client operations for batches, prompt drafts, request queues, and history tabs. |
| `frontend/src/screens/createScreens.tsx` | Render Prompt Generation Management and RunPod Request Management using existing desktop components. |
| `frontend/src/screens/adminScreens.tsx` | Keep existing instruction UI and bind left-side workflow selection to the JSON instruction set. |
| `frontend/src/screens/reviewScreens.tsx` | Render Prompt History and RunPod History tabs, preview modals, actions, and fixed 20-row pagination. |
| `frontend/src/styles.css` | Add only token-aligned table, progress, status, and image-card styles. |

## Task 1: Lock Down the JSON Instruction-Set Contract

**Files:**
- Modify: `backend/app/services/grok_instruction_service.py`
- Modify: `backend/app/data/grok_instruction_set.json`
- Modify: `scripts/convert_grok_instruction_markdown.py`
- Test: `backend/tests/test_grok_instruction_service.py`

**Interfaces:**
- Produces `resolve_workflow_instruction_set(workflow_id: str) -> dict[str, Any]`.
- Produces `validate_instruction_set(payload: dict[str, Any]) -> None`.
- The returned set has `workflowId`, `documents`, `version`, and `compiledMarkdown` fields.

- [ ] **Step 1: Write failing workflow-scoped instruction tests**

```python
def test_resolve_workflow_instruction_set_returns_only_selected_workflow(tmp_path, settings):
    write_instruction_json(tmp_path, workflow_id="1-images.json", roles=["CORE", "ROUTER", "GUIDE"])
    result = resolve_workflow_instruction_set("1-images.json")
    assert result["workflowId"] == "1-images.json"
    assert "[CORE]" in result["compiledMarkdown"]

def test_duplicate_core_is_rejected():
    with pytest.raises(ValueError, match="CORE 역할은 워크플로우당 1개만"):
        validate_instruction_set({"documents": [{"role": "CORE"}, {"role": "CORE"}]})
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest backend/tests/test_grok_instruction_service.py -q`

Expected: failure because workflow-scoped resolution and role validation do not exist.

- [ ] **Step 3: Implement the JSON structure and converter output**

```json
{
  "schemaVersion": "2.0",
  "workflowInstructionSets": [
    {
      "workflowId": "1-images.json",
      "version": 1,
      "documents": [
        {"id": "core", "role": "CORE", "isActive": true, "contentMarkdown": "..."},
        {"id": "router", "role": "ROUTER", "isActive": true, "contentMarkdown": "..."}
      ]
    }
  ]
}
```

`save_instruction_document` must require a selected `workflowId`; adding a second set for the same workflow updates that set rather than creating a second set. The Markdown converter must accept `--workflow-id` and create or replace a `GUIDE` item in that workflow's set.

- [ ] **Step 4: Run contract and Markdown conversion tests**

Run: `pytest backend/tests/test_grok_instruction_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the JSON instruction contract**

```bash
git add backend/app/services/grok_instruction_service.py backend/app/data/grok_instruction_set.json scripts/convert_grok_instruction_markdown.py backend/tests/test_grok_instruction_service.py
git commit -m "feat: scope Grok instruction sets by workflow"
```

## Task 2: Add Durable Batch, Attempt, and Queue Schema

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/db/migrations/versions/20260901_0026_batch_prompt_runpod_queue.py`
- Test: `backend/tests/test_batch_queue_models.py`

**Interfaces:**
- Produces `PromptGenerationBatch`, `PromptGenerationAttempt`, and `RunpodRequestBatch` ORM models.
- Adds nullable links `ImagePromptDraft.prompt_batch_id`, `ImagePromptDraft.negative_prompt`, `ImagePromptDraft.requested_length`, `WorkflowTask.prompt_draft_id`, and `WorkflowTask.request_batch_id`.
- Adds queue metadata `WorkflowTask.dispatch_claimed_at`, `dispatch_attempts`, `next_dispatch_at`, and `last_dispatch_error`.

- [ ] **Step 1: Write the migration/ORM tests before changing the schema**

```python
def test_prompt_draft_can_record_batch_prompt_and_length(session):
    draft = ImagePromptDraft(id="prm_1", asset_id="asset_1", workflow_id="1-images.json", slot_index=1, model="grok")
    draft.negative_prompt = "low quality"
    draft.requested_length = 81
    session.add(draft)
    session.commit()
    assert session.get(ImagePromptDraft, "prm_1").requested_length == 81

def test_task_queue_indexes_support_waiting_work(session):
    assert "ix_workflow_tasks_dispatch" in WorkflowTask.__table__.indexes
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `pytest backend/tests/test_batch_queue_models.py -q`

Expected: failure because the models and queue fields are absent.

- [ ] **Step 3: Write an additive, data-preserving migration**

The migration must create only new tables, nullable columns, and indexes. It must not delete, rename, rewrite, or backfill historical `workflow_tasks`, `task_prompts`, `assets`, or instruction tables. Include:

```python
op.create_index(
    "ix_workflow_tasks_dispatch",
    "workflow_tasks",
    ["status", "next_dispatch_at", "created_at"],
    unique=False,
)
```

`PromptGenerationAttempt` records `draft_id`, `attempt_no`, `status`, `endpoint`, `model`, `started_at`, `completed_at`, `latency_ms`, `input_tokens`, `output_tokens`, `response_json`, and `failure_message`.

- [ ] **Step 4: Upgrade a fresh SQLite database and run ORM tests**

Run: `DATABASE_URL=sqlite:///./data/plan-schema-test.db alembic upgrade head && pytest backend/tests/test_batch_queue_models.py -q`

Expected: migration succeeds and tests pass.

- [ ] **Step 5: Commit the schema change**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/20260901_0026_batch_prompt_runpod_queue.py backend/tests/test_batch_queue_models.py
git commit -m "feat: add durable prompt batch and RunPod queue schema"
```

## Task 3: Implement Image-Level Grok Batch Generation

**Files:**
- Modify: `backend/app/services/grok_image_prompt_service.py`
- Create: `backend/app/services/prompt_batch_service.py`
- Modify: `backend/app/api/v1/prompts.py`
- Test: `backend/tests/test_prompt_batch_service.py`
- Test: `backend/tests/test_grok_image_prompt_service.py`

**Interfaces:**
- `create_prompt_batch(*, workflow_id: str, asset_ids: list[str], user_id: str) -> dict[str, Any]`
- `generate_prompt_batch(batch_id: str, *, retry_draft_id: str | None = None) -> dict[str, Any]`
- `update_prompt_draft(draft_id: str, *, positive_prompt: str, negative_prompt: str, requested_length: int) -> dict[str, Any]`

- [ ] **Step 1: Write the service tests for success, retry, and failure preservation**

```python
def test_batch_generation_creates_one_draft_per_asset_and_records_telemetry(mock_grok):
    batch = create_prompt_batch(workflow_id="1-images.json", asset_ids=["asset_a", "asset_b"], user_id="dobedub")
    result = generate_prompt_batch(batch["id"])
    assert result["counts"] == {"total": 2, "completed": 2, "failed": 0}
    assert attempt_for("asset_a").input_tokens == 120

def test_failed_grok_attempt_keeps_positive_prompt_null(mock_grok):
    mock_grok.side_effect = GrokPromptError("rate limited", status_code=429, retryable=True)
    result = generate_prompt_batch(batch_id)
    assert result["items"][0]["positivePrompt"] is None
    assert result["items"][0]["status"] == "FAILED"
```

- [ ] **Step 2: Run the service tests and confirm they fail**

Run: `pytest backend/tests/test_prompt_batch_service.py backend/tests/test_grok_image_prompt_service.py -q`

Expected: failure because batch lifecycle and telemetry persistence do not exist.

- [ ] **Step 3: Send the exact image and selected workflow instruction set to Grok**

The backend must read the authenticated asset from storage, encode it for the Grok image input, and compose the request from `resolve_workflow_instruction_set(workflow_id)`. The browser must never send a storage path, provider key, or instruction text. Persist response usage values when present:

```python
usage = response.get("usage") or {}
attempt.input_tokens = int(usage.get("input_tokens") or 0)
attempt.output_tokens = int(usage.get("output_tokens") or 0)
attempt.latency_ms = int((completed_at - started_at).total_seconds() * 1000)
```

Set a draft to `WAITING`, `IN_PROGRESS`, `COMPLETED`, or `FAILED`; failures must retain the provider error and leave `positive_prompt` as `NULL`.

- [ ] **Step 4: Add REST endpoints and permission checks**

Add these routes behind `prompts:build`:

```text
POST /api/prompts/batches
POST /api/prompts/batches/{batch_id}/generate
POST /api/prompts/drafts/{draft_id}/regenerate
PATCH /api/prompts/drafts/{draft_id}
GET /api/prompts/batches/{batch_id}
GET /api/prompts/history?page=1&pageSize=20
```

The create route returns `409` with `"선택한 워크플로우에 활성 프롬프트 지시문이 없습니다."` when no instruction set exists.

- [ ] **Step 5: Run API and service tests**

Run: `pytest backend/tests/test_prompt_batch_service.py backend/tests/test_grok_image_prompt_service.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Grok batch generation**

```bash
git add backend/app/services/grok_image_prompt_service.py backend/app/services/prompt_batch_service.py backend/app/api/v1/prompts.py backend/tests/test_prompt_batch_service.py backend/tests/test_grok_image_prompt_service.py
git commit -m "feat: generate Grok prompts per uploaded image"
```

## Task 4: Implement the Durable Serial RunPod Dispatcher

**Files:**
- Create: `backend/app/services/runpod_dispatch_service.py`
- Modify: `backend/app/services/job_service.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Modify: `backend/app/api/v1/jobs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_runpod_dispatch_service.py`

**Interfaces:**
- `enqueue_runpod_tasks(*, draft_ids: list[str], user_id: str) -> dict[str, Any]`
- `dispatch_next_waiting_task() -> str | None`
- `reconcile_active_runpod_tasks() -> int`
- `start_runpod_dispatcher(app: FastAPI) -> None`

- [ ] **Step 1: Write dispatch policy tests**

```python
def test_dispatcher_leaves_second_task_waiting_when_one_submission_is_active(session, runpod_online):
    first, second = enqueue_two_waiting_tasks(session, same_user=True)
    assert dispatch_next_waiting_task() == first.id
    assert session.get(WorkflowTask, second.id).status == "REQUEST_WAITING"

def test_dispatcher_marks_timeout_and_cancelled_remote_status_as_failed(session, runpod_status):
    runpod_status.return_value = {"status": "TIMED_OUT"}
    reconcile_active_runpod_tasks()
    assert session.get(WorkflowTask, task_id).status == "FAILED"
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `pytest backend/tests/test_runpod_dispatch_service.py -q`

Expected: failure because no durable dispatcher exists.

- [ ] **Step 3: Create queued tasks before contacting RunPod**

For every selected completed draft, create a `WorkflowTask` in a single transaction with:

```python
task.status = "REQUEST_WAITING"
task.prompt_draft_id = draft.id
task.payload_json = resolved_payload
task.config_json = {"length": draft.requested_length, "fps": 16, "seed": "server-auto"}
task.positive_prompts = [draft.positive_prompt]
task.negative_prompts = [draft.negative_prompt]
```

`resolved_payload` contains the uploaded asset ID, its exact image width/height, final prompts, length, FPS, a generated seed, and the workflow-default configuration snapshot. `prepare_workflow_for_job` must patch only the workflow's registered height/width, length, FPS, seed, positive, and negative bindings.

- [ ] **Step 4: Claim and submit only one eligible request per cycle**

`dispatch_next_waiting_task` must calculate active counts from `REQUEST_WAITING` excluded, `RUNPOD_QUEUE` included, and `RUNPOD_IN_PROGRESS` included. It must use a transaction and a claim timestamp to avoid duplicate submissions. If policy is at capacity or endpoint availability is unavailable, keep the task as `REQUEST_WAITING`, set `next_dispatch_at` with bounded backoff, and return without failure.

After remote submit, store the RunPod response, Job ID, filename if present, delay/execution metrics if present, and transition to `RUNPOD_QUEUE`. The polling reconciler maps `IN_QUEUE` to `RUNPOD_QUEUE`, `IN_PROGRESS` to `RUNPOD_IN_PROGRESS`, `COMPLETED` to `COMPLETED`, and `FAILED`, `CANCELLED`, or `TIMED_OUT` to `FAILED`.

- [ ] **Step 5: Run dispatcher tests including restart recovery**

Run: `pytest backend/tests/test_runpod_dispatch_service.py -q`

Expected: PASS, including an existing waiting row being picked up after `start_runpod_dispatcher` starts.

- [ ] **Step 6: Commit the RunPod queue**

```bash
git add backend/app/services/runpod_dispatch_service.py backend/app/services/job_service.py backend/app/services/task_tracking_service.py backend/app/api/v1/jobs.py backend/app/main.py backend/tests/test_runpod_dispatch_service.py
git commit -m "feat: queue and serially dispatch RunPod tasks"
```

## Task 5: Build the Prompt Generation Management Screen

**Files:**
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/helpers/navigation.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/createScreens.tsx`
- Modify: `frontend/src/styles.css`
- Test: `backend/tests/test_frontend_prompt_management_contract.py`

**Interfaces:**
- Route key: `create.prompt-management`.
- Client methods: `createPromptBatch`, `generatePromptBatch`, `regeneratePromptDraft`, `updatePromptDraft`, `getPromptBatch`.

- [ ] **Step 1: Write source-contract tests for the page state rules**

```python
def test_prompt_management_uses_batch_generation_and_disables_duplicate_submit():
    source = Path("frontend/src/screens/createScreens.tsx").read_text(encoding="utf-8")
    assert "generatePromptBatch" in source
    assert "생성 중" in source
    assert "disabled={isGenerating}" in source
```

- [ ] **Step 2: Run the contract test and confirm it fails**

Run: `pytest backend/tests/test_frontend_prompt_management_contract.py -q`

Expected: failure because the route and batch state do not exist.

- [ ] **Step 3: Implement the desktop screen following the approved mockup**

The screen must use the existing shell and tokens. Put the upload area first, then workflow selection, batch progress counters, a per-image prompt-pair list, and editable built-in negative prompt. The main action state is exactly:

```tsx
<button disabled={!selectedWorkflowId || imageItems.length === 0 || isGenerating}>
  {isGenerating ? "프롬프트 생성 중" : hasGeneratedItems ? "프롬프트 재생성" : "프롬프트 생성"}
</button>
```

Show each item’s thumbnail, Asset ID, uploaded dimensions, Positive Prompt editable textarea, individual retry, Grok status, and last error. Do not add a pre-run confirmation page.

- [ ] **Step 4: Run frontend build and contract tests**

Run: `npm --prefix frontend run build && pytest backend/tests/test_frontend_prompt_management_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the prompt-management screen**

```bash
git add frontend/src/router.ts frontend/src/helpers/navigation.ts frontend/src/api/client.ts frontend/src/screens/createScreens.tsx frontend/src/styles.css backend/tests/test_frontend_prompt_management_contract.py
git commit -m "feat: add batch prompt generation management"
```

## Task 6: Build the RunPod Request Management Screen

**Files:**
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/helpers/navigation.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/createScreens.tsx`
- Modify: `frontend/src/styles.css`
- Test: `backend/tests/test_frontend_runpod_request_contract.py`

**Interfaces:**
- Route key: `create.runpod-requests`.
- Client methods: `listRunpodCandidates`, `enqueueRunpodTasks`, `getRunpodQueueSummary`.

- [ ] **Step 1: Write source-contract tests for all selection and duration options**

```python
def test_runpod_request_screen_exposes_fixed_lengths_and_batch_selection():
    source = Path("frontend/src/screens/createScreens.tsx").read_text(encoding="utf-8")
    assert "49" in source and "81" in source and "161" in source
    assert "전체 선택" in source
    assert "RunPod에 일괄 요청" in source
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest backend/tests/test_frontend_runpod_request_contract.py -q`

Expected: failure because the request-management page does not exist.

- [ ] **Step 3: Implement the request list and live dashboard**

The list contains only drafts with a non-empty positive prompt and no active or completed task for the selected image. Each row displays input thumbnail, final positive/negative prompts, selected workflow display name, resolution, duration controls, fixed `16 FPS`, and automatic seed. The header dashboard shows `REQUEST_WAITING`, `RUNPOD_QUEUE`, `RUNPOD_IN_PROGRESS`, `COMPLETED`, and `FAILED` counts. Submit preserves the current page and shows a non-blocking success notice with the number queued.

- [ ] **Step 4: Run build and contract tests**

Run: `npm --prefix frontend run build && pytest backend/tests/test_frontend_runpod_request_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit RunPod request management**

```bash
git add frontend/src/router.ts frontend/src/helpers/navigation.ts frontend/src/api/client.ts frontend/src/screens/createScreens.tsx frontend/src/styles.css backend/tests/test_frontend_runpod_request_contract.py
git commit -m "feat: add queued RunPod request management"
```

## Task 7: Split and Optimize Task History

**Files:**
- Modify: `backend/app/api/v1/history.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/reviewScreens.tsx`
- Modify: `frontend/src/styles.css`
- Test: `backend/tests/test_history_tabs.py`

**Interfaces:**
- `GET /api/history/prompts?page=1&pageSize=20`
- `GET /api/history/runpod?page=1&pageSize=20`
- Both endpoints always apply a page size of 20.

- [ ] **Step 1: Write DTO tests for both histories**

```python
def test_prompt_history_returns_grok_result_and_null_prompt_for_failed_attempt(client):
    item = client.get("/api/history/prompts?page=1&pageSize=20").json()["items"][0]
    assert {"grokEndpoint", "grokModel", "latencyMs", "inputTokens", "outputTokens"} <= item.keys()
    assert item["positivePrompt"] is None if item["status"] == "FAILED" else True

def test_runpod_history_returns_preview_and_response_columns(client):
    item = client.get("/api/history/runpod?page=1&pageSize=20").json()["items"][0]
    assert {"inputPreview", "outputPreview", "filename", "delaySeconds", "executionSeconds", "runpodJobId"} <= item.keys()
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `pytest backend/tests/test_history_tabs.py -q`

Expected: failure because history is not separated by lifecycle.

- [ ] **Step 3: Add backend DTOs and tab UI**

Prompt History column order is No, user, KST date, image ID, thumbnail, positive prompt, success/failure, Grok telemetry, copy. RunPod History column order is No, user, KST date, workflow display name, prompt ID, result, input preview, output preview/play, filename/delay/execution/job ID, download, delete. Use preview modals and retain batch download/delete only for the RunPod tab.

- [ ] **Step 4: Verify pagination and actions**

Run: `pytest backend/tests/test_history_tabs.py -q && npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 5: Commit history separation**

```bash
git add backend/app/api/v1/history.py backend/app/services/task_tracking_service.py frontend/src/api/client.ts frontend/src/screens/reviewScreens.tsx frontend/src/styles.css backend/tests/test_history_tabs.py
git commit -m "feat: split prompt and RunPod task history"
```

## Task 8: Finalize Admin Instruction UX, Monitoring, and Documentation

**Files:**
- Modify: `frontend/src/screens/adminScreens.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `docs/dobedub-studio-user-manual.md`
- Modify: `README.md`
- Test: `backend/tests/test_admin_workflow_id.py`
- Test: `backend/tests/test_frontend_submission_flow.py`

**Interfaces:**
- Admin instruction API returns the selected workflow ID, its single JSON set, and an error message for missing/invalid role combinations.
- Dispatcher exposes queue counts through `GET /api/jobs/queue-summary` for request management polling.

- [ ] **Step 1: Write regression tests for the admin selection and submission preservation**

```python
def test_admin_instruction_screen_selects_workflow_from_left_panel():
    source = Path("frontend/src/screens/adminScreens.tsx").read_text(encoding="utf-8")
    assert "selectedInstructionWorkflowId" in source
    assert "resolveWorkflowInstructionSet" in source

def test_submission_persists_pair_and_does_not_navigate_to_history():
    # Retain the existing pairing-workspace contract while queued work is submitted.
    assert "onNavigate(\"review.history\")" not in generate_video_body()
```

- [ ] **Step 2: Run regression tests and confirm expected failures**

Run: `pytest backend/tests/test_admin_workflow_id.py backend/tests/test_frontend_submission_flow.py -q`

Expected: any missing new admin selection contract fails before the UI is completed.

- [ ] **Step 3: Implement admin messages and operational documentation**

Show the selected workflow in the left instruction area. On creation, deletion, or role violation, use the v4 centered application dialog rather than browser alerts. Update the manual with the two new Generate screens, Grok progress meanings, queued-worker behavior, task-history tabs, and the fact that closing the browser does not cancel submitted work.

- [ ] **Step 4: Run full verification**

Run: `pytest backend/tests -q && npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 5: Commit documentation and integration checks**

```bash
git add frontend/src/screens/adminScreens.tsx frontend/src/api/client.ts README.md docs backend/tests/test_admin_workflow_id.py backend/tests/test_frontend_submission_flow.py
git commit -m "docs: document durable Grok and RunPod workflow"
```

## Self-Review

- Spec coverage: Tasks 1 and 8 implement workflow-scoped JSON instruction management; Tasks 2 and 3 implement per-image Grok pairing and telemetry; Task 4 implements durable sequential RunPod dispatch; Tasks 5 and 6 implement the two Generate screens; Task 7 implements both history tabs and action columns.
- Data safety: Task 2 is explicitly additive. Existing RDS task, asset, prompt, and instruction records are neither deleted nor rewritten.
- Deferred scope: no multi-keyframe request grouping, no Wan ratio normalization, no deployment, and no Git synchronization are included.
- Naming check: `PromptGenerationBatch`, `PromptGenerationAttempt`, `RunpodRequestBatch`, `ImagePromptDraft`, and `WorkflowTask` are used consistently throughout the plan.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-01-batch-grok-runpod-management.md`.

Two execution options:

1. **Subagent-Driven (recommended)**: dispatch a fresh subagent per task and review each task before continuing.
2. **Inline Execution**: execute tasks in this session in sequence, with review checkpoints after the schema, dispatcher, and UI milestones.
