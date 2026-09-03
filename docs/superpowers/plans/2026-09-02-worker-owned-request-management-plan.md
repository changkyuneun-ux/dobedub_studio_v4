# Worker-Owned Request Management Plan

1. Add focused failing service tests for request submitter/worker separation,
   cross-worker draft listing statistics, and workflow instruction-set copying.
2. Add an additive Alembic migration for `RunpodRequestBatch.submitted_by` and
   update model/service payloads with worker and submitter names.
3. Add `jobs:manage` to the permission catalogue and guard cross-worker query,
   batch creation, and batch restoration paths with it.
4. Extend prompt APIs with instruction readiness and management-scoped draft
   listing/statistics. Extend RunPod APIs with worker/workflow filters and
   grouped queue summary data.
5. Update the Prompt Generation, RunPod Request, Prompt History, and Admin
   instruction screens to use the approved management flow. Preserve root
   workspace persistence and the durable serial RunPod dispatcher.
6. Run focused backend tests, dispatcher regression tests, backend compilation,
   frontend build, and the repository verification script. No Git push, ECS
   deployment, RDS migration execution, or historic data cleanup is included.
