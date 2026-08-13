# DOBEDUB STUDIO ECS Express 배포 Runbook

이 문서는 다른 운영자 또는 AI가 `DOBEDUB STUDIO`를 같은 방식으로 안전하게 ECS Express에 배포할 수 있도록 만든 단일 실행 기준 문서다. 실제 운영 배포에서 검증한 **ECR immutable image -> 기존 task definition 복제 -> 조건부 RDS migration -> ECS Canary 배포 -> 운영 검증** 순서를 따른다.

보조 자료는 [AWS ECS 배포 가이드](./aws-ecs-deployment.md), [ECS 운영 배포 체크리스트](./ecs-production-deployment-checklist.md)다. 이 문서가 실제 명령과 판단 순서의 기준이다.

## 1. 운영 구성과 배포 원칙

| 구분 | 현재 운영 기준 |
| --- | --- |
| AWS Region | `ap-northeast-2` |
| ECS Cluster / Service | `default` / `dobedub-app` |
| Task definition family | `default-dobedub-app` |
| ECR repository | `dobedub-app` |
| Runtime | ECS Fargate `linux/amd64`, container port `7860` |
| Database | RDS MySQL, SQLAlchemy URL `mysql+pymysql://...` |
| Asset storage | EFS mounted at `/data/outputs`, `STORAGE_BACKEND=local` |
| Deployment strategy | ECS Express Canary, 신규 task health check 후 이전 revision drain |
| DB migration | 앱 기동과 분리. schema 변경 시에만 one-off task 실행 |

### 반드시 지킬 원칙

1. 이미지는 Git commit short SHA를 tag로 쓰는 immutable image로 배포한다. `latest`를 사용하지 않는다.
2. 새 task definition은 **현재 운영 revision을 복제하고 Main 컨테이너 image만 교체**한다. 콘솔에서 새 definition을 처음부터 만들지 않는다.
3. RDS, EFS, RunPod, Secret ARN, task role, execution role, log configuration, port mapping은 복제 과정에서 보존한다.
4. `RUN_SERVER_AUTO_MIGRATE=0`을 유지한다. DB schema 변경이 있을 때만 migration one-off task를 실행한다.
5. `AUTH_TRUST_PROXY_HEADERS`는 운영 task definition에 넣지 않는다. 인증은 JWT Bearer token과 DB 기반 권한만 사용한다.
6. 로컬 SQLite의 users, Prompt Catalog, task history, assets는 RDS/EFS로 자동 복사되지 않는다. 운영 데이터 이관은 별도 승인 작업이다.
7. Canary 배포 중에는 이전 revision을 수동 중지하지 않는다. ECS가 health check와 draining을 관리한다.

## 2. 사전 조건

### 2.1 실행 환경

- 이 저장소의 `main` 최신 상태
- Docker Desktop/buildx, AWS CLI v2, `jq`, Python 3 설치
- AWS CLI 자격 증명은 운영 계정에서 ECR/ECS/EC2/ELB 조회 및 ECS update 권한을 가져야 한다.
- Docker가 `linux/amd64` 이미지를 빌드할 수 있어야 한다.
- 운영 Secret 값은 읽거나 문서/채팅/commit에 기록하지 않는다.

```bash
cd "/Users/changkyuneun/Documents/New project/comfyui-video-studio-app-v4"
aws sts get-caller-identity
docker buildx version
jq --version
```

### 2.2 배포 대상 기본 변수

아래는 shell 세션에만 설정한다. 실제 계정 ID는 `aws sts get-caller-identity` 결과에서 가져온다.

```bash
export AWS_REGION=ap-northeast-2
export ECS_CLUSTER=default
export ECS_SERVICE=dobedub-app
export TASK_FAMILY=default-dobedub-app
export ECR_REPOSITORY=dobedub-app
export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
export IMAGE_TAG="$(git rev-parse --short HEAD)"
```

현재 서비스와 primary task definition을 확인한다.

```bash
aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query 'services[0].{status:status,desired:desiredCount,running:runningCount,taskDefinition:taskDefinition,deployments:deployments[*].{status:status,rollout:rolloutState,taskDefinition:taskDefinition}}' \
  --output json
```

`status=ACTIVE`, 기존 primary rollout이 `COMPLETED`, running count가 desired count와 일치할 때만 시작한다. 기존 배포가 진행 중이면 완료 또는 롤백될 때까지 새 배포를 시작하지 않는다.

## 3. 변경 분류와 배포 결정

| 변경 내용 | migration one-off | 서비스 배포 |
| --- | --- | --- |
| Frontend, API, 서비스 로직, 문서 | 불필요 | 필요 |
| Alembic migration 파일 추가/변경 | 필요 여부를 check로 판정 | migration 성공 후 필요 |
| RDS data seed / 사용자 / 카탈로그 운영 데이터 변경 | 별도 data migration 승인 | 필요 시 별도 |
| EFS asset 이동/삭제 | 별도 storage 작업 | 보통 불필요 |
| Secret 값 변경 | DB schema와 무관 | 새 task definition 배포 필요 |

**중요:** migration 파일을 추가하지 않았더라도, 새 이미지로 `--check`를 실행해 RDS가 Alembic head와 일치하는지 확인한다. `migrationRequired=false`이면 migration task를 실행하지 않는다.

## 4. 배포 전 로컬 검증

다음은 최소 기준이다. 변경 영역에 맞춰 추가 smoke test를 선택한다.

```bash
npm run build
python3 scripts/fastapi_smoke_check.py
python3 scripts/frontend_smoke_check.py
python3 scripts/admin_smoke_check.py
python3 scripts/prompt_db_smoke_check.py
python3 scripts/rbac_permission_smoke_check.py
python3 scripts/workflow_persistence_smoke_check.py
git diff --check
git status --short
```

- 권한/사용자 변경: `rbac_permission_smoke_check.py`는 필수다.
- Prompt Builder/LLM 변경: `prompt_db_smoke_check.py`는 필수다.
- migration 변경: `python3 scripts/db_migration_smoke_check.py`를 추가한다.
- `git status --short`에 의도하지 않은 `.env`, SQLite DB, uploads/outputs, `node_modules`, build output이 있으면 정리 후 진행한다.

테스트가 통과한 commit만 `main`에 push한다.

```bash
git add <intended-files>
git commit -m "<change summary>"
git push origin main
export IMAGE_TAG="$(git rev-parse --short HEAD)"
```

## 5. ECR 이미지 빌드와 검증

Apple Silicon 개발 Mac에서도 ECS Fargate에 맞게 `linux/amd64`를 명시한다.

```bash
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

docker buildx build --platform linux/amd64 --push \
  -t "${ECR_URI}:${IMAGE_TAG}" .

aws ecr describe-images \
  --repository-name "$ECR_REPOSITORY" \
  --image-ids imageTag="$IMAGE_TAG" \
  --region "$AWS_REGION" \
  --query 'imageDetails[0].{digest:imageDigest,pushedAt:imagePushedAt,size:imageSizeInBytes}' \
  --output json
```

출력에 image digest와 pushedAt이 표시되어야 한다. 이미지가 없거나 arm64 image를 빌드했다면 여기서 중단한다.

## 6. 기존 Task Definition 복제

### 6.1 현재 primary revision을 다운로드

현재 revision을 기준으로 복제하면 EFS volume/access point, Secrets Manager reference, log configuration, 역할, port 등 운영 설정이 보존된다.

```bash
export CURRENT_TASK_DEFINITION="$(aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query 'services[0].taskDefinition' \
  --output text)"

aws ecs describe-task-definition \
  --task-definition "$CURRENT_TASK_DEFINITION" \
  --region "$AWS_REGION" \
  --query taskDefinition \
  --output json > /tmp/dobedub-current-task-definition.json
```

### 6.2 image만 교체한 새 revision JSON 생성

아래 command는 AWS 응답 전용 read-only field를 제거하고 `Main` 컨테이너의 image만 교체한다.

```bash
jq --arg image "${ECR_URI}:${IMAGE_TAG}" '
  del(
    .taskDefinitionArn,
    .revision,
    .status,
    .requiresAttributes,
    .compatibilities,
    .registeredAt,
    .registeredBy,
    .deregisteredAt
  )
  | .containerDefinitions |= map(
      if .name == "Main" then .image = $image else . end
    )
' /tmp/dobedub-current-task-definition.json > /tmp/dobedub-next-task-definition.json
```

등록 전에 핵심 설정이 유지되는지 검토한다.

```bash
jq '{
  family,
  cpu,
  memory,
  runtimePlatform,
  volumes,
  main: (.containerDefinitions[] | select(.name == "Main") | {
    image,
    portMappings,
    mountPoints,
    environment,
    secrets,
    logConfiguration
  })
}' /tmp/dobedub-next-task-definition.json
```

다음 값은 특히 유지되어야 한다.

- EFS mount point: `/data/outputs`
- `PERSISTENCE_BACKEND=db`
- `STORAGE_BACKEND=local`
- `STUDIO_DATA_DIR=/data/outputs/dobedub-studio`
- `OUTPUTS_DIR=/data/outputs/dobedub-studio/outputs`
- `WORKFLOW_SEED_DIR=/app/workflows`
- `WORKFLOWS_DIR=/data/outputs/dobedub-studio/workflows`
- `METADATA_DIR=/data/outputs/dobedub-studio/metadata`
- `RUN_SERVER_AUTO_MIGRATE=0`
- `RUNPOD_DRY_RUN=0`
- `DATABASE_SSL_CA=/app/certs/global-bundle.pem`
- `DATABASE_SSL_VERIFY_IDENTITY=1`
- secret references: `DATABASE_URL`, `AUTH_JWT_SECRET`, `RUNPOD_API_KEY`, `PROMPT_LLM_API_KEY`, `RUNPOD_SANDBOX_POD_API_KEY`
- `AUTH_TRUST_PROXY_HEADERS`가 **없음**

### 6.2.1 Workflow 영속 저장소 규칙

`/app/workflows`는 Docker image에 들어 있는 기본 workflow seed 전용이다. Admin Console에서 등록하거나 수정한 workflow JSON과 `.paramconfig.json`은 반드시 EFS 경로에 둔다.

```text
WORKFLOW_SEED_DIR=/app/workflows
WORKFLOWS_DIR=/data/outputs/dobedub-studio/workflows
METADATA_DIR=/data/outputs/dobedub-studio/metadata
```

앱 시작 시 seed 경로의 파일은 EFS runtime 경로에 없는 경우에만 복사된다. 과거 seed와 동일했던 파일만 새로운 image의 seed로 갱신할 수 있고, Admin이 수정하거나 신규 등록한 파일은 절대 덮어쓰거나 삭제하지 않는다. 이 세 환경변수 중 하나라도 `/app/...` runtime 경로를 가리키면 ECS image 교체 때 workflow 등록 정보가 유실될 수 있으므로 배포 전 필수 확인 항목으로 취급한다.

### 6.3 새 revision 등록

```bash
export NEW_TASK_DEFINITION="$(aws ecs register-task-definition \
  --region "$AWS_REGION" \
  --cli-input-json file:///tmp/dobedub-next-task-definition.json \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)"

echo "$NEW_TASK_DEFINITION"
```

이 시점에는 아직 ECS service를 업데이트하지 않는다. 먼저 section 7의 migration gate를 통과한다.

## 7. 조건부 RDS Migration Gate

### 7.1 one-off task의 네트워크 설정 확보

one-off task는 service task와 같은 VPC subnet/security group에서 실행해야 RDS 및 EFS에 접근할 수 있다. 현재 service task의 ENI에서 값을 조회한다.

```bash
export LIVE_TASK_ARN="$(aws ecs list-tasks \
  --cluster "$ECS_CLUSTER" \
  --service-name "$ECS_SERVICE" \
  --desired-status RUNNING \
  --region "$AWS_REGION" \
  --query 'taskArns[0]' \
  --output text)"

export ENI_ID="$(aws ecs describe-tasks \
  --cluster "$ECS_CLUSTER" \
  --tasks "$LIVE_TASK_ARN" \
  --region "$AWS_REGION" \
  --query 'tasks[0].attachments[?type==`ElasticNetworkInterface`].details[?name==`networkInterfaceId`].value | [0]' \
  --output text)"

aws ec2 describe-network-interfaces \
  --network-interface-ids "$ENI_ID" \
  --region "$AWS_REGION" \
  --query 'NetworkInterfaces[0].{subnet:SubnetId,securityGroups:Groups[*].GroupId}' \
  --output json
```

위 출력의 subnet 및 security group을 아래 `NETWORK_CONFIGURATION`에 넣는다. public IP 설정도 현재 ECS service와 동일하게 유지한다. 일반적으로 private subnet이면 `DISABLED`다.

```bash
export SUBNET_ID=<current-service-subnet-id>
export SECURITY_GROUP_ID=<current-service-security-group-id>
export NETWORK_CONFIGURATION="awsvpcConfiguration={subnets=[${SUBNET_ID}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=DISABLED}"
```

### 7.2 Check task 실행

새 image/revision으로 RDS migration 상태만 검사한다. `--check`는 schema가 뒤처졌을 때 exit code `2`를 반환하는 정상적인 pending 신호다.

```bash
export MIGRATION_CHECK_TASK="$(aws ecs run-task \
  --cluster "$ECS_CLUSTER" \
  --task-definition "$NEW_TASK_DEFINITION" \
  --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIGURATION" \
  --overrides '{"containerOverrides":[{"name":"Main","command":["python3","scripts/upgrade_database.py","--check"]}]}' \
  --region "$AWS_REGION" \
  --query 'tasks[0].taskArn' \
  --output text)"

aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER" --tasks "$MIGRATION_CHECK_TASK" --region "$AWS_REGION"
aws ecs describe-tasks \
  --cluster "$ECS_CLUSTER" \
  --tasks "$MIGRATION_CHECK_TASK" \
  --region "$AWS_REGION" \
  --query 'tasks[0].containers[0].{exitCode:exitCode,reason:reason,lastStatus:lastStatus}' \
  --output json
```

판정 규칙:

| 종료 코드 | 의미 | 다음 행동 |
| --- | --- | --- |
| `0` | `migrationRequired=false` | migration 생략, section 8로 진행 |
| `2` | `migrationRequired=true` | section 7.3 실행 |
| 그 외 | DB/CA/Secret/SG/EFS 또는 image 오류 | 배포 중단 후 원인 해결 |

CloudWatch Logs에서 JSON `migrationRequired`, `currentHeads`, `targetHeads`도 확인한다.

### 7.3 Pending인 경우에만 migration task 실행

```bash
export MIGRATION_APPLY_TASK="$(aws ecs run-task \
  --cluster "$ECS_CLUSTER" \
  --task-definition "$NEW_TASK_DEFINITION" \
  --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIGURATION" \
  --overrides '{"containerOverrides":[{"name":"Main","command":["python3","scripts/upgrade_database.py","--if-needed"]}]}' \
  --region "$AWS_REGION" \
  --query 'tasks[0].taskArn' \
  --output text)"

aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER" --tasks "$MIGRATION_APPLY_TASK" --region "$AWS_REGION"
aws ecs describe-tasks \
  --cluster "$ECS_CLUSTER" \
  --tasks "$MIGRATION_APPLY_TASK" \
  --region "$AWS_REGION" \
  --query 'tasks[0].containers[0].{exitCode:exitCode,reason:reason,lastStatus:lastStatus}' \
  --output json
```

`--if-needed` task의 exit code가 `0`일 때만 service 배포를 허용한다. schema down/rollback은 자동으로 수행하지 않는다.

## 8. ECS Express Canary 배포

### 8.1 서비스 업데이트

```bash
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$NEW_TASK_DEFINITION" \
  --region "$AWS_REGION" \
  --query 'service.deployments[*].{status:status,rollout:rolloutState,taskDefinition:taskDefinition,running:runningCount,pending:pendingCount}' \
  --output json
```

Express 서비스는 Canary 전략을 사용한다. 새 task가 먼저 기동되고 ALB target health를 통과한 뒤 Canary bake 시간이 지나면 기존 revision이 drain된다. 이 관찰 구간에는 새 배포를 추가로 시작하거나 이전 revision task를 수동 중지하지 않는다.

### 8.2 진행 상태 및 Target health 확인

```bash
aws ecs describe-services \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION" \
  --query 'services[0].{running:runningCount,pending:pendingCount,deployments:deployments[*].{status:status,rollout:rolloutState,taskDefinition:taskDefinition,running:runningCount,pending:pendingCount},events:events[0:5].[createdAt,message]}' \
  --output json
```

새 task ARN을 event에서 확인한 뒤 target group health를 확인한다. target group ARN은 service의 `loadBalancers` 정보 또는 ECS Express 리소스 화면에서 가져온다.

```bash
export TARGET_GROUP_ARN=<current-target-group-arn>
aws elbv2 describe-target-health \
  --target-group-arn "$TARGET_GROUP_ARN" \
  --region "$AWS_REGION" \
  --query 'TargetHealthDescriptions[*].{target:Target.Id,port:Target.Port,state:TargetHealth.State,reason:TargetHealth.Reason,description:TargetHealth.Description}' \
  --output json
```

완료 기준:

- 새 revision이 `PRIMARY`, `rollout=COMPLETED`
- 신규 task가 `RUNNING`
- ALB target state가 `healthy`
- 이전 revision이 목록에서 사라지거나 `DRAINING` 후 종료됨
- ECS service event에 `has reached a steady state`와 `deployment completed`가 표시됨

## 9. 운영 후 기능 검증

ECS Express의 공개 URL을 `SERVICE_URL`에 넣는다. URL은 ECS Express service의 Public ingress/Resource 화면에서 확인한다.

```bash
export SERVICE_URL='https://<ecs-express-public-domain>'
curl -fsS --max-time 20 "${SERVICE_URL}/api/health" | jq .
```

`/api/health` 응답에서 아래를 확인한다.

- `ok: true`
- `system.database.engine: mysql+pymysql`
- `system.storage.dataDir.writable: true`
- `system.storage.outputsDir.writable: true`
- `system.workflows.count`가 기대값과 일치
- `system.runpod.configured: true`
- `system.promptLlm.configured: true`

브라우저에서는 아래를 확인한다.

1. 로그인, 로그아웃, 새로고침 후 세션 처리
2. 일반 사용자에게 Admin 메뉴/기능이 노출되지 않는지, SUPER_ADMIN 권한 변경이 재로그인 또는 세션 갱신 뒤 반영되는지
3. Prompt Catalog, Prompt Builder, Prompt Reuse가 열리는지
4. Prompt Builder의 Generate Prompt가 응답을 반환하는지
5. workflow 선택, i2v 입력 이미지 업로드 검증, RunPod status 확인
6. 영상 생성 후 task history, preview, download가 가능한지
7. 입력 image와 결과 video asset이 EFS에 저장되는지
8. Sandbox Pod 권한 사용자는 Admin의 Sandbox Pod 상태 조회/Start/Stop이 가능한지

CloudWatch Logs에서 startup exception, RDS connection error, `401` 반복, `500` 반복, prompt LLM response error를 확인한다.

## 10. 실패 시 진단과 롤백

### 10.1 배포 상태별 진단

| 증상 | 우선 확인 | 조치 |
| --- | --- | --- |
| task가 시작 직후 종료 | ECS stopped reason, container log | image, env/secret ARN, entrypoint 확인 |
| target health `unhealthy` | `/api/health`, container log, security group | port 7860, ALB health path, RDS/EFS startup 오류 확인 |
| migration task 실패 | exit code, CloudWatch, RDS SG/CA/secret | service update 금지, DB 연결부터 해결 |
| 로그인 500 | `DATABASE_URL`, users schema, JWT secret | RDS schema migration/secret/CA 확인 |
| Catalog 빈 화면 | RDS reference data와 `/api/prompts/catalog` 응답 | 운영 data seed는 자동 이관되지 않음을 확인 |
| output 저장/다운로드 실패 | EFS mount, writable health, asset metadata | EFS access point/permissions와 `/data/outputs` 확인 |
| Prompt 생성 502 | `PROMPT_LLM_*`, RunPod endpoint/log | endpoint/API key/모델 응답 형식 확인 |

### 10.2 서비스 코드 롤백

DB migration이 없거나 새 schema가 구 코드와 호환되는 경우에만 직전 healthy task definition으로 rollback한다.

```bash
export PREVIOUS_TASK_DEFINITION=<previous-healthy-task-definition-arn-or-family:revision>

aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$PREVIOUS_TASK_DEFINITION" \
  --region "$AWS_REGION"
```

스키마 migration까지 완료된 경우에는 service code rollback과 DB rollback을 분리해서 판단한다. Alembic `downgrade`는 데이터 손실 위험이 있으므로 별도 승인과 백업 없이 실행하지 않는다.

## 11. 이번 운영 배포 기준 기록 예시

배포 기록에는 secret 값이 아닌 식별 정보만 남긴다.

```text
Date/time: 2026-08-10 KST
Git commit / image tag: a27ced5
ECR image digest: sha256:653db69cb4f34969be0258fd9543a128a7d7069e16793deb7aeacd8be12e041d
ECS task definition: default-dobedub-app:43
Migration gate: not required (no schema change)
Deployment: ECS Express Canary completed
Health: RDS MySQL, EFS writable, RunPod and Prompt LLM configured
```

## 12. AI 실행 지침

다른 AI가 이 runbook을 따를 때의 최소 행동 규칙이다.

1. 먼저 `git status`, AWS identity, 기존 ECS deployment 상태를 조회한다.
2. schema 변경 여부를 Git diff와 Alembic migration 파일로 판단하고, 불확실하면 `--check` one-off task로 확인한다.
3. 현재 primary task definition을 복제하여 image만 바꾼다. Secret, EFS, RDS, RunPod 설정을 재작성하지 않는다.
4. migration pending 상태가 아니면 migration apply task를 실행하지 않는다.
5. ECS Canary가 `COMPLETED` 되기 전에는 배포 성공을 선언하지 않는다.
6. `/api/health`, ALB target health, CloudWatch, 로그인과 주요 UI 기능을 확인한 뒤 결과를 운영 기록에 남긴다.
7. password, API key, DATABASE_URL 원문, secret ARN의 secret value는 채팅/commit/log에 출력하지 않는다.
