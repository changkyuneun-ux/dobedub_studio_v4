# S3 Media Storage Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ECS 앱의 입력 이미지와 출력 영상을 S3 중심 저장 구조로 전환하고, RunPod의 S3 스토리지 구성을 활용해 API/EFS 경유 바이트 전송을 줄인다.

**Architecture:** S3를 입력/출력 미디어의 원본 저장소로 승격한다. ECS API는 메타데이터, 권한 검증, presigned URL 발급, 작업 상태 관리를 담당하고, RunPod 워커는 S3에서 입력을 읽고 S3에 출력을 쓰는 계약으로 전환한다. EFS는 전환 기간의 호환 계층과 임시 롤백 경로로만 유지한다.

**Tech Stack:** FastAPI, SQLAlchemy/RDS MySQL, ECS/Fargate, S3, IAM task role, RunPod Serverless, React frontend.

**Spec:** 2026-09-09 사용자 요청 및 `docs/superpowers/specs/2026-08-30-runpod-performance-design.md`

## Global Constraints

- 운영 데이터는 앱 코드가 직접 파괴적으로 이관하지 않는다. 기존 EFS/RDS 데이터 변경은 별도 승인된 one-off 작업으로만 수행한다.
- RunPod 제출 재현성을 유지한다. input asset id, prompt text, workflow settings, submission snapshot은 계속 저장한다.
- S3 객체는 비공개 bucket에 저장하고 앱은 인증 후 presigned URL 또는 프록시 응답만 제공한다.
- ECS task role에만 S3 접근 권한을 부여한다. execution role에는 이미지 pull, logs, secrets 권한만 둔다.
- RunPod용 S3 권한은 최소 범위 prefix로 분리한다. 모든 RunPod 실행 미디어 object key는 `request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/...` 또는 `batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/...` scope 아래에 있어야 하며, 앱 prefix와 RunPod read/write prefix를 같은 bucket에 두더라도 IAM 조건으로 격리한다.
- 대용량 ZIP, 이미지, 영상 바이트를 DB와 provider status JSON에 저장하지 않는다.
- 전환 중 `/api/files/{assetId}` 계약은 유지한다. 프론트엔드 변경은 최소화하고 서버 응답 정책으로 흡수한다.
- rollback은 `STORAGE_BACKEND=local` + 기존 EFS path로 돌아갈 수 있어야 한다.

---

## Current State

- `backend/app/core/config.py`에는 `STORAGE_BACKEND`, `S3_BUCKET`, `S3_PREFIX` 설정이 있다.
- `backend/app/services/storage_backends.py`에는 `S3AssetStorage.save_bytes`, `save_file`, `delete`, `presigned_url` 초안이 있다.
- `backend/app/api/v1/assets.py`의 `/api/files/{asset_id}`는 `Path` 기반 `FileResponse`/range streaming만 처리한다.
- `backend/app/repositories/db_adapter.py`의 `create_upload`, `get_asset`, `register_asset`는 로컬/EFS 파일 경로 중심이다.
- `backend/app/services/studio_api_service.py`의 `build_runpod_payload`는 입력 이미지를 Base64로 읽어 RunPod `/run` payload에 싣는다.
- `backend/app/services/output_service.py`는 RunPod output Base64를 ECS에서 디코딩해 outputs dir에 저장한다. `type=s3_url`은 원격 URL만 수집한다.
- `backend/app/services/prompt_batch_service.py`와 `backend/app/api/v1/prompts.py`의 Grok 경로는 asset을 `Path`로 받아 로컬 파일을 읽는다.
- `backend/app/services/batch_zip_import_service.py`는 ZIP을 API 프로세스 메모리/임시 파일로 풀고 각 이미지를 로컬 업로드로 등록한다.

## Target Direction

1. 입력 업로드는 브라우저가 앱에서 받은 presigned PUT/POST로 S3에 직접 업로드한다.
2. 앱은 업로드 전에 실행 scope를 먼저 예약한다. 프롬프트 초안 기반 일반 작업은 `requestBatchId`(`rpb_...`)와 `requestItemId`(`rpi_...`)를 예약하고, 배치 ZIP 작업은 `batchJobId`와 item/task id를 함께 사용한다. 업로드 완료 callback/confirm에서 `assets` DB row를 생성하며 `storage_backend=s3`, `storage_key=<prefix>/request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/inputs/...` 또는 `<prefix>/batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/inputs/...`를 저장한다.
3. RunPod 제출 payload는 Base64 대신 `input.images[*].s3Uri` 또는 `input.images[*].url` 형태로 바꾼다. RunPod 워커 구현에 맞춰 한 가지 계약만 표준화한다.
4. RunPod 출력은 워커가 S3 `outputs/` prefix에 직접 업로드하고, 같은 job scope의 `manifests/runpod-result.json`을 S3에 쓴다.
5. RunPod 워커는 ECS backend callback을 호출하지 않는다. 앱은 RunPod `/status` polling 결과가 `COMPLETED`이면 S3 manifest를 읽어 output asset row를 upsert하고 `/api/files/{assetId}`에서 presigned GET redirect 또는 서버 프록시를 제공한다.
6. EFS는 migration 완료 전까지 기존 local asset을 읽는 fallback으로 유지하고, 신규 미디어 쓰기는 S3로 고정한다.
7. S3 lifecycle, CloudWatch log retention, NAT/S3 gateway endpoint, prefix별 비용 태그를 함께 적용한다.

## Local Test Environment Direction

Local development has three levels. The default remains cheap and offline; S3 behavior is opt-in.

1. Unit tests use fake S3 clients only. These tests verify key generation, metadata, presigned URL calls, manifest validation, and idempotency without Docker or AWS credentials.
2. Local app development keeps `STORAGE_BACKEND=local` by default. This preserves the current `data/uploads` and `data/outputs` workflow for fast UI/backend work.
3. S3 integration development uses a local S3-compatible service through a compose profile. Prefer LocalStack when matching AWS S3 API behavior matters; MinIO is acceptable only for storage adapter smoke tests because presigned URL and IAM behavior differ from AWS.

Add these local-only settings:

```env
STORAGE_BACKEND=s3
S3_BUCKET=dobedub-studio-local
S3_PREFIX=local
S3_ENDPOINT_URL=http://127.0.0.1:4566
S3_FORCE_PATH_STYLE=1
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=ap-northeast-2
RUNPOD_DRY_RUN=1
```

Local S3 object examples:

- `s3://dobedub-studio-local/local/request-batches/rpb_local_001/items/rpi_local_001/jobs/task_local_001/inputs/asset_local_001/scene_001.png`
- `s3://dobedub-studio-local/local/request-batches/rpb_local_001/items/rpi_local_001/jobs/task_local_001/outputs/asset_output_local_001/final.mp4`
- `s3://dobedub-studio-local/local/request-batches/rpb_local_001/items/rpi_local_001/jobs/task_local_001/manifests/runpod-result.json`
- `s3://dobedub-studio-local/local/batches/local_batch_001/source/source.zip`
- `s3://dobedub-studio-local/local/batches/local_batch_001/items/rpi_local_002/jobs/task_local_002/inputs/asset_local_002/0001.png`

RunPod is not called in local S3 integration tests. The local dry-run path should emit a fake S3 output manifest and register output assets against the local S3-compatible bucket.

## S3 Object Layout

- Standard request item input: `s3://<bucket>/<prefix>/request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/inputs/<assetId>/<safeFileName>`
- Standard request item output: `s3://<bucket>/<prefix>/request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/outputs/<assetId>/<safeFileName>`
- Standard request item manifest: `s3://<bucket>/<prefix>/request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/manifests/runpod-result.json`
- Batch source ZIP: `s3://<bucket>/<prefix>/batches/<batchJobId>/source/source.zip`
- Batch item input: `s3://<bucket>/<prefix>/batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/inputs/<assetId>/<safeFileName>`
- Batch item output: `s3://<bucket>/<prefix>/batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/outputs/<assetId>/<safeFileName>`
- Batch manifest: `s3://<bucket>/<prefix>/batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/manifests/runpod-result.json`

Do not write new media to date-only prefixes such as `<prefix>/inputs/<yyyy>/<mm>/<dd>/...`. Dates are metadata and lifecycle/filter dimensions, not ownership boundaries. The first routing dimension must be `request-batches/<requestBatchId>` for normal prompt-draft execution or `batches/<batchJobId>` for ZIP/batch-job execution.

Object metadata:

- `asset-id`
- `task-id` when known
- `job-id`
- `request-batch-id`
- `request-item-id`
- `prompt-batch-id` when known
- `batch-job-id` when known
- `created-by`
- `asset-type`
- `source-file-name`
- `workflow-id` when known

## RunPod S3 Contract

Use one manifest shape across app and worker:

```json
{
  "input": {
    "workflow": {},
    "images": [
      {
        "name": "scene_001.png",
        "assetId": "asset_abc123",
        "s3Uri": "s3://bucket/dobedub-studio/request-batches/rpb_2b7a1e329dc84413/items/rpi_47a88a1d24594f90/jobs/task_123/inputs/asset_abc123/scene_001.png"
      }
    ],
    "output": {
      "mode": "s3",
      "bucket": "bucket",
      "prefix": "dobedub-studio/request-batches/rpb_2b7a1e329dc84413/items/rpi_47a88a1d24594f90/jobs/task_123/outputs",
      "manifestKey": "dobedub-studio/request-batches/rpb_2b7a1e329dc84413/items/rpi_47a88a1d24594f90/jobs/task_123/manifests/runpod-result.json"
    }
  }
}
```

RunPod `/status` may return only terminal state. ECS must then read the S3 manifest from `manifestKey`:

```json
{
  "jobId": "task_123",
  "status": "completed",
  "outputs": [
    {
      "type": "video",
      "assetId": "asset_output_001",
      "bucket": "bucket",
      "key": "dobedub-studio/request-batches/rpb_2b7a1e329dc84413/items/rpi_47a88a1d24594f90/jobs/task_123/outputs/asset_output_001/final.mp4",
      "filename": "final.mp4",
      "contentType": "video/mp4",
      "sizeBytes": 12345678,
      "node_id": "42"
    }
  ]
}
```

Inline RunPod media is a legacy/local fallback only. The production contract is S3 manifest reconciliation, not RunPod-to-ECS callback.

Do not use public S3 URLs as the durable record. Store bucket/key and generate short-lived access URLs at request time.

## Phase 0: Decision And Safety Gates

**Files:**
- Modify: `docs/ecs-production-deployment-checklist.md`
- Modify: `docs/aws-ecs-deployment.md`
- Modify: `.env.example`
- Modify: `docker-compose.dev.yml`

- [ ] Decide RunPod input mode: `s3Uri` if RunPod worker has AWS credentials, `presignedGetUrl` if worker cannot assume AWS permissions.
- [ ] Decide output mode: RunPod writes directly to app-owned S3 bucket/prefix, not to transient RunPod-only storage.
- [ ] Create staging bucket or staging prefix and block public access.
- [ ] Add a local S3 compose profile. Use LocalStack service `localstack` on `127.0.0.1:4566`, create bucket `dobedub-studio-local`, and keep it disabled unless the developer opts in.
- [ ] Add `S3_ENDPOINT_URL` and `S3_FORCE_PATH_STYLE` settings for local S3-compatible testing. Production must leave `S3_ENDPOINT_URL` empty.
- [ ] Add S3 lifecycle policy draft: inputs to IA after 30 days, outputs to IA after 30 days, archive after 90 days if business accepts slower retrieval, noncurrent versions expire.
- [ ] Add rollback rule: changing `STORAGE_BACKEND=local` must keep existing EFS-backed assets readable.
- [ ] Define migration acceptance: new upload, Grok prompt generation, RunPod submission, completion output preview, output download, batch ZIP download all pass in staging.

## Phase 1: Storage Service Interface

**Files:**
- Modify: `backend/app/services/storage_backends.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/repositories/interfaces.py`
- Modify: `backend/app/repositories/db_adapter.py`
- Test: `backend/tests/test_storage_backends.py`
- Test: `backend/tests/test_db_asset_storage_s3.py`

- [ ] Add `StoredObject.bucket`, `etag`, `last_modified` optional fields without breaking local storage.
- [ ] Build the boto3 S3 client with optional local endpoint support: when `S3_ENDPOINT_URL` is set, pass `endpoint_url=settings.s3_endpoint_url`; when `S3_FORCE_PATH_STYLE=1`, use path-style addressing.
- [ ] Add `open_read(storage_key) -> BinaryIO`, `stat(storage_key) -> StoredObject`, and `presigned_put(key, content_type, expires_in)` to storage backends.
- [ ] Keep `LocalAssetStorage` behavior compatible with current `Path` callers during the bridge phase.
- [ ] Update `DbStudioRepository.get_asset` to return an asset descriptor that can represent S3, not only `(dict, Path)`.
- [ ] Add tests with a fake S3 client for save, stat, read, delete, presigned GET, presigned PUT.
- [ ] Add tests proving S3 assets do not raise `FileNotFoundError` merely because no local path exists.
- [ ] Add one LocalStack-backed integration smoke test that is skipped unless `DOBEDUB_S3_INTEGRATION=1`.

## Phase 2: Upload Path To S3

**Files:**
- Modify: `backend/app/api/v1/assets.py`
- Modify: `backend/app/services/studio_api_service.py`
- Modify: `backend/app/repositories/db_adapter.py`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/screens/createScreens.tsx`
- Test: `backend/tests/test_asset_upload_s3.py`
- Test: frontend contract test under `backend/tests/test_frontend_*`

- [ ] Add `POST /api/uploads/presign` requiring `jobs:run`, returning `assetId`, `uploadUrl`, `headers`, `storageKey`, `expiresAt`.
- [ ] Require upload scope in `POST /api/uploads/presign`: either `requestBatchId` + `requestItemId` + `jobId`, or `batchJobId` + `requestItemId` + `jobId`. If the create screen uploads before submission, add a server-issued request batch/item reservation first and use it in the S3 key.
- [ ] Generate input keys only under `request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/inputs/...` or `batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/inputs/...`; reject date-only or unscoped input prefixes.
- [ ] Add `POST /api/uploads/complete` requiring `jobs:run`, validating object existence and size before creating the DB asset row.
- [ ] Preserve current `POST /api/uploads` Base64 endpoint only as local/development compatibility.
- [ ] Change frontend upload flow to use presigned upload when `storageBackend=s3`.
- [ ] Store input image dimensions after upload by reading the object header/range or by client-provided dimensions verified within allowed bounds.
- [ ] Ensure failed upload completion does not create an asset row.

## Phase 3: File Serving And Authorization

**Files:**
- Modify: `backend/app/api/v1/assets.py`
- Modify: `backend/app/services/studio_api_service.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Test: `backend/tests/test_asset_file_access_s3.py`

- [ ] Keep `/api/files/{assetId}` as the stable frontend URL.
- [ ] For S3 assets, return `307` to a short-lived presigned GET for ordinary full-file requests.
- [ ] For range requests on S3 assets, either proxy ranged GET through the API or redirect if the generated URL preserves range behavior in the browser.
- [ ] Enforce object-level authorization before URL issuance: owner, task owner, or `history:read`/`jobs:manage` depending on asset type.
- [ ] Set `Cache-Control: private, no-cache` for authenticated app responses and short S3 URL expiration.
- [ ] Confirm logout invalidates app access even if an old `/api/files/{assetId}` URL is reused after URL expiry.

## Phase 4: RunPod Input/Output S3 Integration

**Files:**
- Modify: `backend/app/services/studio_api_service.py`
- Modify: `backend/app/services/job_service.py`
- Modify: `backend/app/services/output_service.py`
- Modify: `backend/app/services/task_tracking_service.py`
- Test: `backend/tests/test_runpod_s3_payload.py`
- Test: `backend/tests/test_output_service_s3_manifest.py`

- [ ] Replace `build_runpod_payload` Base64 images with S3 image references when all inputs are S3 assets.
- [ ] Keep a bounded fallback for legacy local assets by uploading them to S3 before RunPod submission.
- [ ] Add output destination to RunPod payload: bucket, prefix, and manifest key only, never long-lived credentials in payload.
- [ ] Build output destination from the task scope: `request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/outputs` for normal request-item jobs and `batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/outputs` for batch jobs.
- [ ] Require RunPod worker to write `manifests/runpod-result.json` after all output objects are uploaded.
- [ ] Do not expose an ECS callback endpoint for RunPod completion; completion is detected by RunPod status polling plus S3 manifest reconciliation.
- [ ] Teach `save_runpod_outputs` to register `type=s3_object` results as output assets without downloading media through ECS.
- [ ] Reject RunPod result objects whose bucket/prefix are outside the exact expected `request-batches/<requestBatchId>/items/<requestItemId>/jobs/<jobId>/outputs` or `batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/outputs` prefix.
- [ ] Store output manifest in `runpod_status_json` only after pruning large fields.
- [ ] Add idempotency by making `(task_id, asset_id)` or `(task_id, storage_key, output_role, segment_index)` unique for output links.

## Phase 5: Grok And Prompt Batch Compatibility

**Files:**
- Modify: `backend/app/services/grok_image_prompt_service.py`
- Modify: `backend/app/services/prompt_batch_service.py`
- Modify: `backend/app/api/v1/prompts.py`
- Test: `backend/tests/test_grok_prompt_s3_asset.py`
- Test: `backend/tests/test_prompt_batch_s3_asset.py`

- [ ] Replace direct `Path.read_bytes()` dependency with an asset byte reader or bounded temporary file context.
- [ ] Enforce `GROK_MAX_IMAGE_BYTES` before downloading full S3 objects.
- [ ] Ensure logs never include presigned URLs or Base64 image data.
- [ ] Verify cached Grok draft lookup remains based on asset id, workflow id, slot index, creator, model, and instruction version.

## Phase 6: Batch ZIP Path

**Files:**
- Modify: `backend/app/api/v1/batch_jobs.py`
- Modify: `backend/app/services/batch_zip_import_service.py`
- Modify: `backend/app/services/batch_zip_service.py`
- Test: `backend/tests/test_batch_zip_import_s3.py`
- Test: `backend/tests/test_batch_zip_service.py`

- [ ] Store uploaded source ZIP in S3 under `batches/<batchJobId>/source/source.zip`.
- [ ] Stream ZIP members instead of loading the full archive into API memory when feasible.
- [ ] Register each extracted image as an S3 input asset under `batches/<batchJobId>/items/<requestItemId>/jobs/<jobId>/inputs/...`.
- [ ] Keep source ZIP filename in `batch_jobs.source_zip_file_name`.
- [ ] For output ZIP download, stream S3 output objects into the archive without first copying all videos to EFS.
- [ ] Keep `Content-Encoding: identity` for ZIP responses to avoid gzip overhead.

## Phase 7: ECS/IAM/Network

**Files:**
- Modify: deployment task definition or IaC source when present
- Modify: `docs/ecs-express-deployment-runbook.md`
- Modify: `docs/ecs-production-deployment-checklist.md`

- [ ] Add ECS task role permissions: `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:HeadObject`, multipart permissions if used, scoped to exact bucket/prefix.
- [ ] Keep ECS execution role limited to ECR, CloudWatch Logs, Secrets Manager/SSM, and KMS decrypt for injected secrets.
- [ ] Add S3 gateway VPC endpoint for private S3 traffic and NAT data processing cost reduction.
- [ ] Inject bucket/prefix via environment and secrets via ECS `secrets`, not hardcoded values.
- [ ] Set CloudWatch log retention explicitly.
- [ ] Add alarms for S3 4xx/5xx, upload completion failure rate, RunPod S3 manifest rejection, and API 5xx.

## Phase 8: Data Migration And Cutover

**Files:**
- Create: `scripts/migrate_efs_assets_to_s3.py`
- Create: `scripts/verify_s3_media_cutover.py`
- Create: `docs/runbooks/s3-media-cutover.md`
- Test: dry-run script output reviewed in staging

- [ ] Write migration script with `--dry-run` default, explicit `--execute`, and prefix allowlist.
- [ ] Copy EFS input/output files to S3 preserving asset id and file name.
- [ ] Update DB asset rows only after S3 `HeadObject` confirms expected size.
- [ ] Produce CSV report: asset id, old backend/key, new key, size, status, error.
- [ ] Run staging migration against a copied database or sampled asset set.
- [ ] Cut over new writes to S3 first, then migrate historical reads.
- [ ] Keep EFS mounted read-only during validation window.
- [ ] Remove EFS write dependency only after historical preview/download success rate is confirmed.

## Managed Optimization Checklist

Use this as the master board. Keep one owner and target date per line when moving into issue tracking.

| Priority | Status | Item | Acceptance |
| --- | --- | --- | --- |
| P0 | [ ] | Remove blank-password bootstrap superadmin | No production user can authenticate with `password_hash=NULL`; bootstrap requires explicit secret or one-time setup path |
| P0 | [ ] | Remove predictable JWT fallback secret | App fails fast in production when `AUTH_JWT_SECRET` is missing or default |
| P0 | [ ] | Make Grok prompt batch claim atomic | Multiple ECS replicas cannot process the same pending draft |
| P0 | [ ] | Make dry-run semantics explicit and safe | `RUNPOD_DRY_RUN=1` never performs paid provider network calls, or the env var is removed and docs/tests align |
| P0 | [ ] | Add object-level authorization for task/status/prompts/cancel/history delete | Non-owner users cannot read, cancel, or delete another user's task without manage permission |
| P1 | [ ] | Add RunPod submit idempotency and bounded retry | Ambiguous `/run` timeout cannot create duplicate paid GPU jobs indefinitely |
| P1 | [ ] | Split web API and background worker ownership | Scaling ECS web replicas does not multiply monitor/dispatcher loops |
| P1 | [ ] | Make output persistence idempotent | Repeated status processing does not create duplicate final links/assets |
| P1 | [ ] | Replace queue/dashboard full materialization with SQL pagination | Queue API returns one page without loading all rows or large provider payloads |
| P1 | [ ] | Reduce frontend polling pressure | Active screens avoid overlapping requests and use backoff/visibility pause |
| P1 | [ ] | Move media I/O to S3 | New input images and output videos do not traverse ECS as Base64 or EFS writes |
| P1 | [ ] | Stream ZIP import/export | Large ZIP workflows avoid full memory buffering and unnecessary gzip |
| P1 | [ ] | Improve `/api/health` | Health includes DB/storage dependency checks and non-200 unhealthy status for ECS health checks |
| P2 | [ ] | Consolidate JSON/DB persistence boundary | Production paths use DB consistently; JSON remains local/dev import/export only |
| P2 | [ ] | Add storage/log retention | S3 lifecycle, EFS cleanup plan, CloudWatch retention, and RDS backup policy are documented and active |
| P2 | [ ] | Harden Docker/runtime | Pin runtime deps, remove test-only packages from production image, run as non-root where feasible |
| P2 | [ ] | Add frontend lint/test baseline | Frontend has at least build, lint, and focused behavior tests in CI |
| P2 | [ ] | Split oversized modules | `task_tracking_service.py`, `prompt_builder_service.py`, large frontend shell/styles are split by responsibility |
| P2 | [ ] | Version ECS/IAM/storage configuration | Task definition/IAM/S3 lifecycle/log retention are managed through reviewed IaC or a documented release artifact |

## Verification Commands

Run after implementation tasks, not after this planning document only:

```bash
python3.12 -m pytest backend/tests/test_storage_backends.py backend/tests/test_db_asset_storage_s3.py -q
python3.12 -m pytest backend/tests/test_asset_upload_s3.py backend/tests/test_asset_file_access_s3.py -q
python3.12 -m pytest backend/tests/test_runpod_s3_payload.py backend/tests/test_output_service_s3_manifest.py -q
python3.12 -m pytest backend/tests/test_grok_prompt_s3_asset.py backend/tests/test_prompt_batch_s3_asset.py -q
python3.12 -m pytest backend/tests/test_batch_zip_import_s3.py backend/tests/test_batch_zip_service.py -q
npm run build
```

For deployment validation:

```bash
python3.12 scripts/verify_s3_media_cutover.py --env staging
```

Expected staging result:

- New upload creates `storage_backend=s3`.
- Preview and download work through `/api/files/{assetId}`.
- RunPod payload contains S3 input references, not Base64 image data.
- RunPod output manifest registers S3 output assets without ECS downloading video bytes.
- Batch ZIP download contains expected completed videos.
- CloudWatch shows no repeated S3 access denied, missing object, or RunPod manifest rejection errors.

For local S3 integration validation:

```bash
docker compose -f docker-compose.dev.yml --profile s3 up -d localstack
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=ap-northeast-2 aws --endpoint-url http://127.0.0.1:4566 s3 mb s3://dobedub-studio-local
DOBEDUB_S3_INTEGRATION=1 STORAGE_BACKEND=s3 S3_BUCKET=dobedub-studio-local S3_PREFIX=local S3_ENDPOINT_URL=http://127.0.0.1:4566 S3_FORCE_PATH_STYLE=1 python3.12 -m pytest backend/tests/test_storage_backends.py backend/tests/test_asset_upload_s3.py -q
```

Expected local result:

- No real AWS credentials are required.
- No real RunPod request is made.
- Objects are written under `local/request-batches/...` or `local/batches/...`.
- `/api/files/{assetId}` works against the local S3-compatible endpoint.

## Execution Order

1. Finish P0 security/reliability items before exposing S3 presigned upload broadly.
2. Implement S3 read/write interface and `/api/files` S3 serving.
3. Move new uploads to S3 while keeping old EFS reads.
4. Switch RunPod input/output contract to S3 in staging.
5. Make Grok/prompt batch and batch ZIP paths storage-backend neutral.
6. Add ECS IAM, S3 endpoint, lifecycle, log retention, and alarms.
7. Cut over production new writes to S3.
8. Migrate historical EFS assets after production new-write path is stable.

## Open Decisions

- RunPod worker credential model: AWS IAM-compatible credentials inside RunPod, or app-generated short-lived presigned URLs.
- Whether outputs remain in the app-owned AWS S3 bucket or RunPod-managed S3-compatible storage is replicated back to AWS S3.
- Historical media retention period by asset type.
- Whether public CDN/CloudFront is required later. It is not required for the first secure S3 cutover.
