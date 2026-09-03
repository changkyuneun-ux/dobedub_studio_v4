# Active Prompt Batch Dashboard Plan

## Goal

Keep each in-progress Grok prompt-generation request visible after route changes, while allowing the operator to immediately start the next image-upload batch.

## Scope

1. Expose every active prompt-generation batch for the signed-in user.
2. Render active batches as independent dashboard groups in Prompt Management.
3. Clear only the completed submission workspace after a new batch is created; preserve the selected workflow and built-in negative prompt.
4. Add prompt batch ID and item number to the RunPod request queue, and remove its redundant detail action.
5. Keep instruction administration workflow-scoped, clear stale editor data, and use the same select control styling for copy sources.

## Contract

- Existing `GET /api/prompts/image-drafts/batches/active` remains compatible and returns the newest active batch.
- New `GET /api/prompts/image-drafts/batches/active-list` returns all `PENDING` and `GENERATING` batches, newest first.
- No database migration is required: `prompt_generation_batches`, `image_prompt_drafts.prompt_batch_id`, and `slot_index` already exist.

## Verification

1. Service tests prove active batches are user-scoped and newest-first.
2. Frontend contract tests require multi-batch loading, composer clearing, queue batch metadata, and the updated instruction controls.
3. Run backend tests and frontend build after implementation.
