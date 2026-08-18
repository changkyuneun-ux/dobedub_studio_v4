# DOBEDUB STUDIO ECS 운영 배포 체크리스트

이 문서는 `ap-northeast-2`의 ECS cluster `default`, service `dobedub-app` 배포 시 사용하는 실행 체크리스트다. 현재 운영 구성은 RDS MySQL + EFS local storage이며, S3 backend는 사용하지 않는다.

## 1. 배포 전 코드 기준

- [ ] 로컬 작업 디렉터리가 의도한 commit 상태인지 확인한다. `.env`, SQLite DB, uploads/outputs, `node_modules`, build 산출물은 Git에 포함하지 않는다.
- [ ] `npm run build`를 통과한다.
- [ ] `python3 scripts/fastapi_smoke_check.py`를 통과한다.
- [ ] `python3 scripts/frontend_smoke_check.py`를 통과한다.
- [ ] 권한 관련 변경이 있으면 `python3 scripts/rbac_permission_smoke_check.py`를 통과한다.
- [ ] Alembic migration 파일이 추가·변경된 경우 로컬에서 `python3 scripts/db_migration_smoke_check.py`를 통과한다.
- [ ] 운영 RDS가 `20260811_0015_collections`보다 뒤처졌다면 이번 one-off migration에서 `collections`, `collection_items`가 함께 생성됨을 승인한다. 이 migration은 기존 asset/task 행을 수정하거나 컬렉션 데이터를 seed하지 않는다.
- [ ] 이번 릴리스에 `20260812_0019_task_execution_policy.py`가 포함되면, 변경 범위가 `task_execution_policies` 신규 테이블과 기본 정책 행 `(id=1, 사용자당 3건, 전체 10건)`뿐인지 검토·승인한다. 기존 `users`, catalog, workflow, task, asset 행을 변경하지 않는다.
- [ ] local DB의 catalog, users, task history는 운영 RDS로 자동 이전되지 않는다는 점을 확인한다. 데이터 이관은 별도 승인 작업이다.

## 2. 이미지와 task definition

- [ ] `linux/amd64`로 immutable tag 이미지를 ECR `dobedub-app`에 push한다.
- [ ] ECS task definition family `default-dobedub-app`의 새 revision을 만든다.
- [ ] image만 새 immutable tag로 교체하고, task role/execution role, log group, port `7860`, EFS volume과 mount `/data/outputs`는 유지한다.
- [ ] 환경값을 확인한다: `PERSISTENCE_BACKEND=db`, `STORAGE_BACKEND=local`, `STUDIO_DATA_DIR=/data/outputs/dobedub-studio`, `OUTPUTS_DIR=/data/outputs/dobedub-studio/outputs`, `WORKFLOW_SEED_DIR=/app/workflows`, `WORKFLOWS_DIR=/data/outputs/dobedub-studio/workflows`, `METADATA_DIR=/data/outputs/dobedub-studio/metadata`, `RUN_SERVER_AUTO_MIGRATE=0`, `RUNPOD_DRY_RUN=0`.
- [ ] `RUN_SERVER_SKIP_ENV_LOAD=1`, `TASK_MONITOR_INTERVAL_SECONDS=5`, `PROMPT_LLM_COLD_START_RETRY_DELAYS_SECONDS=5,10,20,30,30`을 명시하거나, 이미지 기본값을 사용한다는 운영 판단을 기록한다.
- [ ] 관측성은 `OBSERVABILITY_ENABLED=1`, `OBSERVABILITY_ENVIRONMENT=production`, `OBSERVABILITY_SLOW_REQUEST_MS=500`으로 유지한다. 이 변경은 DB migration 대상이 아니다.
- [ ] `DATABASE_URL`, `RUNPOD_API_KEY`, `PROMPT_LLM_API_KEY`, `AUTH_JWT_SECRET`는 Secrets Manager 참조인지 확인한다.
- [ ] Sandbox Pod 운영을 사용하는 경우 `RUNPOD_SANDBOX_POD_API_KEY`도 Secrets Manager 참조인지 확인하고, `RUNPOD_SANDBOX_NETWORK_VOLUME_ID`, `RUNPOD_SANDBOX_TEMPLATE_ID`, GPU type/count를 현재 RunPod Sandbox 구성과 일치시킨다.
- [ ] `DATABASE_SSL_CA=/app/certs/global-bundle.pem`, `DATABASE_SSL_VERIFY_IDENTITY=1`을 확인한다.
- [ ] `AUTH_TRUST_PROXY_HEADERS` 환경변수가 task definition에 없는지 확인한다. 인증은 JWT bearer token만 사용한다.

## 3. 조건부 RDS migration gate

- [ ] 새 task definition을 service에 연결하기 전에, 동일 revision·RDS secret·EFS·security group으로 one-off task를 실행한다.
- [ ] command override: `python3 scripts/upgrade_database.py --check`
- [ ] 종료 코드 `0`과 `migrationRequired=false`이면 schema 변경이 없다. migration one-off task를 실행하지 않는다.
- [ ] 종료 코드 `2`와 `migrationRequired=true`이면 schema 변경이 있다. 아래 command로 one-off task를 한 번 실행한다.

```text
python3 scripts/upgrade_database.py --if-needed
```

- [ ] `--if-needed` task가 exit code `0`으로 끝났는지 확인한다. 실패 시 service 배포를 중단한다.
- [ ] migration 적용 후 동일 task definition으로 `--check`를 한 번 더 실행해 exit code `0`, `migrationRequired=false`, target head `20260812_0019`를 확인한다.
- [ ] RDS 접속 오류, CA 오류, security group 오류는 migration 필요 여부가 아니라 배포 차단 오류로 처리한다.

## 4. ECS service 배포

- [ ] `dobedub-app` service를 새 task definition revision으로 update한다.
- [ ] ECS Express/Canary deployment가 진행 중인 동안 이전 revision을 수동 중지하지 않는다.
- [ ] 신규 task가 running이고 ALB target health가 `healthy`인지 확인한다.
- [ ] deployment가 `COMPLETED`가 되고 이전 task가 drain된 것을 확인한다.

## 5. 운영 기능 검증

- [ ] `GET /api/health`가 200이며 database engine이 `mysql+pymysql`, storage가 writable로 표시되는지 확인한다.
- [ ] 로그인 성공, 로그아웃, 비활성 사용자 차단, 일반 사용자 Admin 메뉴 차단을 확인한다.
- [ ] Prompt Catalog 표시, Prompt Builder 열기, Prompt Reuse 조회를 확인한다.
- [ ] workflow 선택, 이미지 업로드, RunPod status 조회를 확인한다.
- [ ] 생성 결과가 EFS에 저장되고 preview/download가 가능한지 확인한다.
- [ ] CloudWatch에 startup exception, migration exception, `500` 반복이 없는지 확인한다.

## 6. 롤백과 기록

- [ ] 기능 또는 health check 실패 시 직전 healthy task definition revision으로 service를 rollback한다.
- [ ] migration이 이미 완료된 경우 schema rollback은 service rollback과 별도 판단한다. migration down은 데이터 손실 위험을 검토한 뒤에만 실행한다.
- [ ] 배포 image tag, task definition revision, migration check 결과, one-off task ARN, 배포 완료 시각, 검증 결과를 운영 기록에 남긴다.
