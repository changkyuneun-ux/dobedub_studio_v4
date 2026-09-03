# Durable Request Batch Workspace Plan

## Sequence

1. **DB contract**
   - Extend `runpod_request_batches` with lifecycle counters and timestamps.
   - Add `runpod_request_items` with immutable prompt/workflow/frame snapshots and a link to `workflow_tasks`.
   - Add `workflow_tasks.request_item_id`.
   - Use an additive Alembic migration only; do not alter or remove existing RDS rows.

2. **Service/API**
   - Implement batch creation from selected prompt draft IDs in one database transaction.
   - Create all `PENDING_SUBMIT` tasks in the transaction, link them to items and batch, and preserve compatibility for the single draft endpoint.
   - Return batch/item payloads and the most recent non-terminal request batch for the logged-in user.
   - Derive request batch counters from child task/item states after creation and status monitoring.

3. **Frontend state**
   - Add a root workspace state provider/cache keyed by authenticated user.
   - Keep active prompt batch and RunPod request batch IDs across route unmounts.
   - Replace browser-loop submission with one batch request API call.
   - Restore prompt and request views from server payloads if the shell is reloaded.

4. **Verification**
   - Model/service tests: snapshot integrity, one transaction creates all child records, legacy single-draft compatibility.
   - Dispatcher test: only one queued task is claimed and submitted when worker capacity is one; no idle worker leaves all tasks `PENDING_SUBMIT`; a dispatch failure returns the claimed item to the durable queue.
   - API test: a selected set returns one `requestBatchId` and its child task IDs.
   - Frontend build and source contract tests.

## Rollback safety

- Migration is additive. Reverting application code leaves the new tables/columns unused and does not modify existing task records.
- No old task is migrated or deleted.
- Existing task history remains driven by `workflow_tasks`.
