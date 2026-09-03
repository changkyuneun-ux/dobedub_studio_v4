# Durable Prompt and RunPod Request Workspace

## Goal

Keep the Prompt Generation Management and RunPod Request Management workspaces stable across route changes and browser refreshes. A browser may leave a screen, but an accepted Grok batch or RunPod request batch must remain queryable until the user explicitly refreshes, cancels, or deletes it.

## Ownership model

| Unit | Owner | Purpose |
| --- | --- | --- |
| `PromptGenerationBatch` | Grok prompt request | One selected workflow plus uploaded image prompt drafts. |
| `ImagePromptDraft` | Image | One source asset, one positive prompt, negative snapshot, requested frame count, and Grok generation state. |
| `RunpodRequestBatch` | User RunPod request | A durable request ID that groups a user-selected set of image prompt drafts. |
| `RunpodRequestItem` | Request batch item | Immutable snapshot of one selected image/prompt/workflow/frame combination and its generated `WorkflowTask`. |
| `WorkflowTask` | RunPod execution | Existing RunPod work record. It retains the provider status and links back to both request batch and item. |

`RunpodRequestBatch` is the parent aggregate. `WorkflowTask` remains the sole execution record and is not replaced.

## Submission and recovery

1. Prompt Management creates a Grok batch and image-scoped draft records.
2. RunPod Request Management selects `READY` drafts and creates one request batch.
3. The server creates a `RunpodRequestItem` and a `WorkflowTask(status=PENDING_SUBMIT)` for every selected draft in one transaction.
4. The background monitor calls the durable dispatcher. It claims only the oldest retry-eligible `PENDING_SUBMIT` task after RunPod reports an idle worker.
5. One accepted submission becomes `QUEUED`/`IN_QUEUE`; the next monitor pass decides whether another request can be submitted.
6. A route transition only changes the view. The batch/item/task records continue to exist and are restored by their active batch IDs.

## State rules

- Active policy limits apply only to provider-accepted active tasks: `QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING`.
- Local queued records (`PENDING_SUBMIT`, `DISPATCHING`) do not consume RunPod active capacity.
- A request batch can contain more than the active policy limit. The durable dispatcher serializes provider submission and enforces the limit at dispatch time.
- A request item snapshots positive prompt, negative prompt, workflow ID, source asset ID and requested frames. Editing a draft later cannot rewrite a submitted request.
- Existing single draft endpoint (`POST /api/jobs/from-prompt-draft`) remains as a compatibility endpoint and internally uses the same request-batch submission service.

## UI recovery contract

- The shell holds the current prompt batch ID and request batch ID in a root workspace store instead of route-local component state.
- The store is persisted per authenticated user in `sessionStorage`; initial screen load also restores the most recent non-terminal server batch for that user.
- Prompt Management keeps uploaded images, generated prompts and the active Grok dashboard after navigation.
- RunPod Request Management restores the active request ID, request dashboard and request item table after navigation or refresh.

## Non-goals for this increment

- Multi-keyframe grouping remains a later milestone.
- No resolution bounds or aspect-ratio normalization is added. Uploaded dimensions are sent as captured and Wan performs its own handling.
- No deployment, migration execution, Git push, or historical data rewrite is part of this code change.
