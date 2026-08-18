# AWS ECS 배포 가이드

이 문서는 현재 운영 중인 `DOBEDUB STUDIO` ECS 서비스를 안전하게 갱신하기 위한 구성 기준입니다. 실제 명령, 조건부 migration, ECS Express Canary 모니터링 및 롤백 절차는 [ECS Express 배포 Runbook](./ecs-express-deployment-runbook.md)을 우선 사용합니다. 작업 전 확인 항목은 [ECS 운영 배포 체크리스트](./ecs-production-deployment-checklist.md)를 사용합니다.

## 전제

- AWS 리전: `ap-northeast-2`
- ECS 클러스터: `default`
- ECS 서비스: `dobedub-app`
- ECS task definition family: `default-dobedub-app`
- ECR repository: `dobedub-app`
- 컨테이너 포트: `7860`
- RunPod 실행 모드: `RUNPOD_DRY_RUN=0`
- 데이터베이스: Amazon RDS MySQL
- 파일 저장: EFS를 `/data/outputs`에 마운트한 local storage backend

## 필수 환경변수

ECS task definition 또는 secret manager에 아래 값을 설정합니다.

```text
HOST=0.0.0.0
PORT=7860
WORKFLOW_SEED_DIR=/app/workflows
WORKFLOWS_DIR=/data/outputs/dobedub-studio/workflows
STUDIO_DATA_DIR=/data/outputs/dobedub-studio
METADATA_DIR=/data/outputs/dobedub-studio/metadata
OUTPUTS_DIR=/data/outputs/dobedub-studio/outputs
PERSISTENCE_BACKEND=db
DATABASE_URL=mysql+pymysql://<user>:<password>@<rds-endpoint>:3306/dobedub_studio
DATABASE_ECHO=0
DATABASE_SSL_CA=/app/certs/global-bundle.pem
DATABASE_SSL_VERIFY_IDENTITY=1
STORAGE_BACKEND=local
RUNPOD_DRY_RUN=0
RUNPOD_API_KEY=<secret>
RUNPOD_ENDPOINT_ID=<endpoint-id>
RUNPOD_BASE_URL=https://api.runpod.ai/v2
RUNPOD_SANDBOX_NETWORK_VOLUME_ID=<sandbox-network-volume-id>
RUNPOD_SANDBOX_TEMPLATE_ID=<sandbox-template-id>
RUNPOD_SANDBOX_GPU_TYPE_ID=NVIDIA GeForce RTX 5090
RUNPOD_SANDBOX_GPU_COUNT=1
RUNPOD_SANDBOX_DEPLOY_NAME=dobedub_comfyUI_Sandbox
RUNPOD_SANDBOX_POD_API_KEY=<secret>
RUNPOD_SANDBOX_POD_REST_URL=https://rest.runpod.io/v1
RUNPOD_SANDBOX_POD_TIMEOUT=20
PROMPT_LLM_PROVIDER=runpod_vllm
PROMPT_LLM_API_KEY=<secret>
PROMPT_LLM_ENDPOINT_ID=<qwen-endpoint-id>
PROMPT_LLM_RUNPOD_INPUT_MODE=prompt
PROMPT_LLM_TIMEOUT=240
PROMPT_LLM_RUNPOD_EXECUTION_MODE=async
PROMPT_LLM_SUBMIT_TIMEOUT=20
PROMPT_LLM_COLD_START_TIMEOUT=900
PROMPT_LLM_POLL_INTERVAL=3
AUTH_JWT_SECRET=<strong-random-secret>
AUTH_TOKEN_TTL_MINUTES=480
TASK_MONITOR_INTERVAL_SECONDS=5
OBSERVABILITY_ENABLED=1
OBSERVABILITY_ENVIRONMENT=production
OBSERVABILITY_SLOW_REQUEST_MS=500
RUN_SERVER_AUTO_MIGRATE=0
RUN_SERVER_SKIP_ENV_LOAD=1
```

`RUNPOD_API_KEY`, `PROMPT_LLM_API_KEY`, `DATABASE_URL`, `AUTH_JWT_SECRET`는 Secrets Manager 또는 SSM Parameter Store 참조로 주입합니다. `PROMPT_LLM_API_KEY`가 같은 RunPod key를 쓰는 경우에도 별도 secret으로 분리해 두면 endpoint 교체가 쉽습니다. `DATABASE_SSL_CA`는 AWS RDS 콘솔이 안내하는 `global-bundle.pem` 경로를 container 안의 실제 파일 위치로 지정합니다. `DATABASE_SSL_VERIFY_IDENTITY=1`은 RDS 권장 접속 방식과 맞춥니다. `RUN_SERVER_AUTO_MIGRATE=0`으로 두고, migration은 one-off task로 분리합니다.

Sandbox Pod 운영을 사용할 때는 `RUNPOD_SANDBOX_POD_API_KEY`를 Secrets Manager 참조로 주입합니다. 현재 RunPod API key와 같은 키를 사용하더라도 별도 환경변수 이름으로 주입해야 하며, Pod ID나 Pod 이름은 migration에 따라 바뀔 수 있으므로 고정 selector로 사용하지 않습니다. `RUNPOD_SANDBOX_NETWORK_VOLUME_ID`를 기본 selector로, `RUNPOD_SANDBOX_TEMPLATE_ID`를 보조 selector로 사용합니다.

인증은 `Authorization: Bearer <JWT>`만 허용합니다. `AUTH_TRUST_PROXY_HEADERS` 및 `X-User-*` 헤더 기반 인증은 지원하지 않으므로, ECS task definition에서도 해당 환경변수를 제거합니다.

## Asset/Manual 관측성

`OBSERVABILITY_ENABLED=1`이면 앱은 `GET /api/assets`, `GET /api/files/{assetId}`, `/manual`, `/docs/manual-assets/*` 요청을 표준 출력 JSON으로 기록합니다. ECS CloudWatch Logs가 이 로그를 수집하면 Embedded Metric Format(EMF)을 통해 `DOBEDUB/Studio` namespace에 별도 에이전트 없이 지표가 생성됩니다.

- CloudWatch Metrics: `ApiLatencyMs`, `ApiRequestCount`, `ApiErrorCount`, `AssetRangeRequestCount`, `AssetStreamReadMs`, `AssetStreamBytes`
- 공통 dimension: `Environment`, `Operation`, `StatusFamily`만 사용합니다. user ID, asset ID, request ID는 지표 dimension으로 넣지 않아 고카디널리티 비용을 방지합니다.
- Browser Network 탭: 응답의 `Server-Timing`에서 `auth`, `db`, `file_stat`, `render`, `app` 시간을 밀리초로 확인합니다. 실제 byte stream 시간은 응답 전송 뒤 확정되므로 `AssetStreamReadMs` EMF 지표와 구조화 로그에서 확인합니다.
- 운영 task definition: `OBSERVABILITY_ENVIRONMENT=production`, `OBSERVABILITY_SLOW_REQUEST_MS=500`을 명시합니다. 이 변경은 DB migration이 필요 없습니다.

CloudWatch Logs Insights의 `/aws/ecs/default/dobedub-app-cf8b`에서 초기 병목을 확인할 때는 아래 query를 사용합니다.

```text
fields @timestamp, operation, status, totalMs, authMs, dbMs, fileStatMs, renderMs, rangeRequest, requestId
| filter event = "request_timing" and operation in ["asset_list", "asset_file", "manual_html", "manual_asset"]
| sort totalMs desc
| limit 100
```

## RDS/MySQL 운영 기준

- ECS task 내부에 MySQL을 실행하지 않습니다. 운영 DB는 Amazon RDS MySQL 또는 Aurora MySQL을 사용합니다.
- `DATABASE_URL`은 ECS task definition의 plaintext 환경변수보다 Secrets Manager 또는 SSM Parameter Store 참조를 권장합니다.
- `DATABASE_SSL_CA`와 `DATABASE_SSL_VERIFY_IDENTITY`를 설정해 RDS CA 검증을 함께 활성화합니다.
- RDS security group은 ECS task security group에서 오는 3306 inbound만 허용합니다.
- 기본 운영에서는 `PERSISTENCE_BACKEND=db`인 경우 웹 task 시작 시 migration을 하지 않습니다. 새 이미지의 Alembic head가 RDS보다 앞선 경우에만 별도 one-off ECS task 또는 CI/CD 단계에서 migration을 실행합니다.
- 웹 task는 `RUN_SERVER_AUTO_MIGRATE=0`을 유지해 app startup과 DB schema 변경을 분리합니다.
- 애플리케이션 task는 migration 완료 후 새 revision으로 교체합니다.
- Docker image의 기본 entrypoint는 `scripts/run_server.py`입니다. 앱 시작 시에는 serving만 담당하고, DB migration은 `scripts/upgrade_database.py`를 one-off task로 실행합니다.

로컬 migration 검증:

```bash
python3 scripts/db_migration_smoke_check.py
```

### 스키마 변경 조건부 one-off migration

새 이미지가 만들어진 뒤, **웹 서비스 배포 전에** 같은 이미지로 아래 check command를 실행합니다.

```bash
python3 scripts/upgrade_database.py --check
```

- 출력의 `migrationRequired`가 `false`이고 exit code가 `0`이면: schema 변경이 없으므로 one-off task와 migration을 생략하고 웹 서비스를 배포합니다.
- `migrationRequired`가 `true`이고 exit code가 `2`이면: 새 Alembic migration이 있으므로 같은 이미지와 동일한 RDS/Secrets/EFS 환경으로 one-off ECS task를 실행합니다.
- check가 DB 연결 오류로 실패하면: 웹 서비스 배포를 중단하고 RDS security group, secret, CA 경로를 먼저 확인합니다.

pending일 때 one-off ECS task의 command override는 아래와 같이 지정합니다. `--if-needed`는 실행 직전 다른 배포가 migration을 끝냈어도 안전하게 skip합니다.

```text
python3 scripts/upgrade_database.py --if-needed
```

one-off task가 exit code `0`으로 종료된 것을 확인한 뒤에만 새 ECS service revision을 배포합니다. `RUN_SERVER_AUTO_MIGRATE=0`은 항상 유지합니다.

로컬 migration 예시:

```bash
DATABASE_URL='mysql+pymysql://<user>:<password>@<rds-endpoint>:3306/dobedub_studio' \
DATABASE_SSL_CA='/app/certs/global-bundle.pem' \
DATABASE_SSL_VERIFY_IDENTITY=1 \
  python3 scripts/upgrade_database.py --if-needed
```

## Asset 저장소 기준

DB에는 파일 바이너리를 저장하지 않습니다. DB에는 `asset_id`, `file_name`, `mime_type`, `size_bytes`, `storage_backend`, `storage_key`, `public_url` 등 메타데이터만 저장합니다.

- 현재 운영: RDS에 metadata를 저장하고, 입력 이미지·생성 영상·리포트 파일은 EFS mount `/data/outputs`에 저장합니다.
- 현재 task definition은 `STORAGE_BACKEND=local`, `STUDIO_DATA_DIR=/data/outputs/dobedub-studio`, `OUTPUTS_DIR=/data/outputs/dobedub-studio/outputs`를 사용합니다.
- S3 backend는 장기 전환 후보일 뿐 현재 운영 task definition에는 설정하지 않습니다.
- 로컬 개발 데이터와 EFS/RDS 운영 데이터는 자동 동기화하지 않습니다. 운영 data migration은 별도 승인·실행 대상입니다.

## 이미지 빌드

```bash
IMAGE_TAG=$(git rev-parse --short HEAD)
docker buildx build --platform linux/amd64 --load -t dobedub-studio:${IMAGE_TAG} .
```

Apple Silicon Mac에서 기본 `docker build`를 사용하면 ARM64 이미지가 만들어질 수 있습니다. 현재 ECS Fargate 서비스는 `linux/amd64`이므로, ECR에 직접 올릴 때도 반드시 `--platform linux/amd64`를 지정합니다.

`.dockerignore`는 로컬 SQLite DB, 업로드 이미지, 생성 영상, 리포트, `.env`를 이미지에 포함하지 않도록 구성되어야 합니다. 운영에 필요한 기본 파일은 `data/segment-defaults.json`만 포함합니다.

## ECR 푸시

```bash
AWS_REGION=ap-northeast-2
AWS_ACCOUNT_ID=<account-id>
ECR_REPOSITORY=dobedub-app

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

aws ecr create-repository --repository-name "$ECR_REPOSITORY" --region "$AWS_REGION" || true

IMAGE_TAG=$(git rev-parse --short HEAD)
docker buildx build --platform linux/amd64 --push \
  -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:${IMAGE_TAG}" .
```

## ECS 업데이트 개요

1. 테스트를 통과한 immutable image를 `dobedub-app` ECR repository에 push합니다.
2. 기존 task definition에서 새 revision을 만들고 image만 교체합니다. `AUTH_TRUST_PROXY_HEADERS`는 추가하지 않습니다.
3. 새 revision은 기존 RDS secret, RunPod secrets, EFS `/data/outputs` volume, `STORAGE_BACKEND=local`, `RUN_SERVER_AUTO_MIGRATE=0`을 유지합니다.
4. 서비스 업데이트 전에 동일 image/revision으로 `python3 scripts/upgrade_database.py --check`를 실행합니다.
5. pending일 때만 `python3 scripts/upgrade_database.py --if-needed` one-off task를 성공시킵니다.
6. 그 다음에만 `dobedub-app` 서비스를 새 revision으로 업데이트합니다.
7. ALB target health, `/api/health`, 로그인/RBAC, Prompt Catalog/Builder, EFS 파일 저장을 확인한 뒤 배포 완료로 판정합니다.

## 운영 저장소 주의

현재 운영 파일 경로는 EFS mount `/data/outputs`입니다. 컨테이너 자체의 `/app/data`는 영속 저장소가 아니므로 운영 asset 경로로 사용하지 않습니다. `WORKFLOW_SEED_DIR=/app/workflows`는 이미지에 포함된 기본 workflow 원본 전용이며, 실제 Admin 등록/수정 workflow와 paramconfig는 `WORKFLOWS_DIR=/data/outputs/dobedub-studio/workflows`에 저장합니다. 앱 시작 시 기본본은 존재하지 않는 파일만 EFS에 복사하며, 운영 파일은 이후 이미지 배포로 덮어쓰지 않습니다.

## 운영 배포 기록

운영 계정 ID, ECR URI, task definition ARN, secret ARN 등은 공개 저장소에 기록하지 않습니다.
배포 이력은 AWS ECS console, CloudTrail, 또는 내부 운영 문서에서 관리합니다.
