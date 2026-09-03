# Worker-Owned Prompt and RunPod Request Management

## Goal

Make prompt and RunPod request management usable across multiple workers without
losing the identity of the person whose image and prompt are being processed.
An administrator may submit a request on behalf of a worker, but the generated
task, history record, and result remain owned by that worker.

## Ownership model

| Field | Meaning |
| --- | --- |
| `created_by` | The worker who owns the image prompt drafts and resulting RunPod work. |
| `submitted_by` | The authenticated user who created the request batch. It may differ from the worker only with `jobs:manage`. |
| `WorkflowTask.user_id` | The worker owner. Task History therefore always presents the worker's name. |

`RunpodRequestBatch` is single-worker only. The request screen filters by one
worker before submission, and every selected draft must belong to that worker.
This avoids mixed ownership inside one request ID while allowing an administrator
to manage several workers from the same screen.

## Prompt and RunPod screens

### Prompt Generation Management

- A workflow must be selected before prompt generation is enabled.
- The selected workflow must have an active instruction-document set. Without
  one, the page shows an explicit instruction setup message and disables the
  batch generation control.
- Draft listings include worker name for management users.

### RunPod Request Management

- Worker and workflow filters narrow the pending prompt-draft list before any
  selection is made.
- The dashboard contains an overall count and worker-scoped cards for request
  waiting, provider queued, in progress, and failed work.
- A batch created from a filtered list records the worker as owner and the
  acting administrator as submitter. The existing durable serial dispatcher
  continues to submit one eligible `PENDING_SUBMIT` task at a time after worker
  capacity is available.

### Prompt History

- The list shows the worker's display name rather than a raw user ID.
- A right-side worker statistics panel summarizes total, pending, generating,
  ready, and failed prompt drafts for the currently visible management scope.

## Workflow instruction-document contract

- An instruction-document set is scoped 1:1 to one workflow ID.
- Legacy documents are retained only for `1-images.json`; other workflows start
  unconfigured.
- The administrator selects the target workflow in the left workflow selector,
  then creates or imports documents for that workflow.
- A **Copy documents** action creates an independent target set from a selected
  source workflow. It never silently overwrites an existing target set.
- A document can be deleted from its selected workflow. Each workflow may have
  at most one `CORE` and one `ROUTER` document.

## Authorization

- Users can see and submit their own drafts with `prompts:build` and `jobs:run`.
- `jobs:manage` permits an administrator/operator to view another worker's
  drafts, submit an owned batch for that worker, and inspect that batch.
- `submitted_by` is retained as an audit field and does not grant ownership of
  the underlying task or assets.

## Data changes

- Add nullable `runpod_request_batches.submitted_by` referencing `users.id`.
- Backfill existing rows with `created_by`.
- Add an index for batch owner/status queries.
- All changes are additive; no existing task, asset, prompt, or RDS record is
  rewritten except the ownership-audit backfill for the new nullable column.

## Verification

1. A manager can submit a worker's READY draft and the created task keeps the
   worker identity while the batch records the manager as submitter.
2. A non-manager cannot query or submit another worker's drafts.
3. The dispatcher claims only one eligible item per available capacity and
   leaves other batch items pending.
4. Unconfigured workflows reject prompt-generation batches before writing
   drafts; configured workflow documents can be copied and then edited
   independently.
5. Frontend build verifies the worker filters, management dashboard, prompt
   history statistics panel, and disabled generation states compile.
