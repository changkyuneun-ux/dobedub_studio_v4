# DOBEDUB STUDIO v4 ECS 배포 준비 체크리스트

이 문서는 v4 변경사항을 운영 ECS에 반영하기 전 사용하는 **릴리스 전용** 체크리스트다. 실제 명령은 [ECS Express 배포 Runbook](./ecs-express-deployment-runbook.md)을 따르고, 이 문서는 이번 릴리스의 DB 안전성·환경값·검증 범위를 먼저 고정한다.

## 1. 배포 범위와 데이터 보호 원칙

- 대상: `ap-northeast-2` / cluster `default` / service `dobedub-app` / family `default-dobedub-app`.
- 기준점: 확인 시점의 운영 primary revision은 `default-dobedub-app:47`이며, 배포 시작 직전에 다시 조회한다.
- 기존 RDS의 사용자, 역할·권한, Prompt Catalog, workflow, Task History, Prompt Review, asset metadata 행은 수정·삭제·초기화하지 않는다.
- EFS의 `/data/outputs/dobedub-studio/workflows`, `metadata`, `uploads`, `outputs`는 이미지 배포 대상이 아니다. 기존 파일을 삭제·복사·동기화하지 않는다.
- 로컬 SQLite와 로컬 catalog/users/assets를 운영 RDS/EFS로 이관하지 않는다.
- 금지 명령: `alembic downgrade`, `scripts/migrate_json_to_db.py`, catalog/user seed, EFS 정리 명령, 수동 `DELETE`/`UPDATE` SQL. 필요한 데이터 이관은 별도 승인 릴리스로 분리한다.

## 2. 이번 릴리스의 DB 변경 판정

| 항목 | 판정 |
| --- | --- |
| Alembic head | `20260813_0021` |
| v3/v4 history bridge | `20260813_0020_merge_v3_v4_histories` |
| 감사 로그 보존 migration | `20260812_0018_purge_login_audit_logs`는 보존형 no-op으로 전환 |
| 자산 컬렉션 migration | `20260811_0015_collections` |
| 컬렉션 신규 테이블 | `collections`, `collection_items` |
| Task Policy migration | `20260812_0019_task_execution_policy` |
| 정책 신규 테이블 | `task_execution_policies` |
| 입력 이미지 크기 migration | `20260813_0021_asset_image_dimensions` |
| 기존 asset 확장 | `assets.image_width`, `assets.image_height`를 NULL 허용으로 추가 |
| 기존 테이블 변경 | `prompt_terms.category_id`를 NULL 허용으로 완화. 기존 값·FK 행은 변경하지 않음 |
| 컬렉션 신규 데이터 | 없음. migration은 컬렉션 또는 item을 자동 생성하지 않음 |
| 정책 신규 데이터 | singleton 정책 행 1개: `id=1`, 사용자당 활성 Task `3`, 전체 활성 Task `10` |
| 기존 RDS 데이터 영향 | 기존 행 수정·삭제 없음 |

`20260811_0015_collections.py`는 자산 컬렉션과 컬렉션-asset 연결을 저장하기 위해 `collections`, `collection_items`를 추가한다. `collection_items`의 FK cascade는 **향후** 컬렉션 또는 asset 삭제 시의 연결 정리 규칙일 뿐, migration 실행 중에는 기존 asset/task를 삭제하거나 변경하지 않는다.

`20260812_0018_purge_login_audit_logs.py`는 과거의 `action='login'` 감사 로그 삭제를 수행하지 않는다. 운영 RDS의 기존 audit record를 보존하기 위해 no-op으로 유지하며, 감사 로그 정리는 이 릴리스의 migration 범위에서 제외한다.

운영 RDS는 v3 head `20260812_0013`을 사용하므로, `20260813_0020` merge node가 두 Alembic 계보를 연결한다. legacy marker와 merge node는 no-op이다. migration one-off task에는 `PRESERVE_EXISTING_CATALOG_DATA=1`을 주입하여 기존 Prompt Catalog 행을 backfill·갱신하지 않는다. `20260810_0013`은 신규 keyword 입력을 위해 `prompt_terms.category_id`만 nullable로 완화하며, 기존 `prompt_subcategories.legacy_category_id` 컬럼과 값을 보존한다.

`20260812_0019_task_execution_policy.py`는 멀티태스킹 정책을 저장하기 위해서만 필요하다. 이 migration은 새 테이블과 기본 정책 한 행을 생성한다. 기본 행도 운영 DB의 새 설정 데이터이므로, 배포 승인 시 이 생성까지 승인 대상으로 기록한다.

`20260813_0021_asset_image_dimensions.py`는 기존 asset 행을 backfill하거나 수정하지 않는다. 새로 업로드되는 입력 이미지부터 실제 높이와 너비를 기록할 수 있도록 `assets`에 NULL 허용 컬럼만 추가한다.

## 3. 로컬 사전 검증

- [ ] `npm run build`
- [ ] `python3 scripts/fastapi_smoke_check.py`
- [ ] `python3 scripts/frontend_smoke_check.py`
- [ ] `python3 scripts/rbac_permission_smoke_check.py`
- [ ] `python3 scripts/prompt_db_smoke_check.py`
- [ ] `python3 scripts/workflow_persistence_smoke_check.py`
- [ ] `python3 scripts/db_migration_smoke_check.py` - `collections`, `collection_items`, `task_execution_policies`와 정책 기본값 `3/10`까지 검증한다.
- [ ] `git diff --check`
- [ ] `.env`, `data/*.db`, uploads/outputs, `frontend/dist`, `node_modules`가 image/Git에 포함되지 않는지 확인한다.
- [ ] 이 릴리스에 포함할 파일만 commit한다. 이전 사용자 변경이나 미완료 실험 파일을 함께 배포하지 않는다.

## 4. ECS 환경 대조

새 task definition은 현재 primary revision을 복제하고 Main 컨테이너 image만 immutable image tag로 바꾼다. 다음 값이 유지되어야 한다.

| 구분 | 운영 기대값 |
| --- | --- |
| Database | `PERSISTENCE_BACKEND=db`, `DATABASE_URL`은 Secret, `DATABASE_SSL_CA=/app/certs/global-bundle.pem`, `DATABASE_SSL_VERIFY_IDENTITY=1` |
| Migration | `RUN_SERVER_AUTO_MIGRATE=0`, 권장 `RUN_SERVER_SKIP_ENV_LOAD=1` |
| EFS | volume mount `/data/outputs`, `STORAGE_BACKEND=local` |
| Runtime data | `STUDIO_DATA_DIR=/data/outputs/dobedub-studio`, `OUTPUTS_DIR=/data/outputs/dobedub-studio/outputs` |
| Workflow persistence | `WORKFLOW_SEED_DIR=/app/workflows`, `WORKFLOWS_DIR=/data/outputs/dobedub-studio/workflows`, `METADATA_DIR=/data/outputs/dobedub-studio/metadata` |
| RunPod | `RUNPOD_DRY_RUN=0`, API keys는 Secret, configured endpoints 유지 |
| Prompt LLM | `PROMPT_LLM_PROVIDER=runpod_vllm`, key는 Secret, native endpoint는 `PROMPT_LLM_RUNPOD_EXECUTION_MODE=async`, `PROMPT_LLM_SUBMIT_TIMEOUT=20`, `PROMPT_LLM_COLD_START_TIMEOUT=900`, `PROMPT_LLM_POLL_INTERVAL=3` 권장 |
| Monitoring | `TASK_MONITOR_INTERVAL_SECONDS=5` |
| Authentication | `AUTH_JWT_SECRET`은 Secret, `AUTH_TRUST_PROXY_HEADERS`는 미설정 |

- [ ] Docker image 안에 `/app/certs/global-bundle.pem`이 존재한다. 현재 소스의 `certs/global-bundle.pem`은 Dockerfile의 `COPY . .`에 포함된다.
- [ ] Secret ARN은 복제하되 secret value는 콘솔, 로그, commit, 채팅에 출력하지 않는다.
- [ ] 기존 운영 task definition의 EFS access point, task/execution role, log group, port `7860`, public ingress 관련 설정을 변경하지 않는다.

## 5. 조건부 migration gate

서비스 배포보다 먼저 **새 image를 사용한 one-off ECS task**를 같은 subnet/security group/EFS/secrets 환경에서 실행한다.

1. `python3 scripts/upgrade_database.py --check`를 실행한다.
2. 종료 코드 `0` / `migrationRequired=false`: RDS head가 image head와 같다. apply task를 실행하지 않고 서비스 배포 단계로 간다.
3. 종료 코드 `2` / `migrationRequired=true`: pending migration이 있다. `currentHeads`와 `targetHeads`를 기록하고, pending 범위가 section 2의 v3/v4 bridge, 컬렉션/Task Policy migration과 일치할 때만 `PRESERVE_EXISTING_CATALOG_DATA=1 python3 scripts/upgrade_database.py --if-needed`를 한 번 실행한다.
4. 기타 종료 코드: RDS 연결, TLS CA, secret, security group 또는 image 오류다. **service update를 금지**하고 원인을 먼저 해결한다.
5. apply exit code가 `0`이면 같은 revision으로 `--check`를 재실행해 `migrationRequired=false`를 확인한다.

`--if-needed`는 Alembic `upgrade head`만 수행한다. migration check/apply 어느 경우에도 기존 application data를 export/import/seed하지 않는다.

## 6. 배포 후 확인 기준

- [ ] Canary 배포가 `COMPLETED`, 신규 target이 `healthy`, 기존 task는 ECS가 drain하도록 둔다.
- [ ] `/api/health`에서 MySQL engine, EFS writable, workflow count, RunPod/Qwen configured 상태를 확인한다.
- [ ] 로그인/로그아웃/새로고침 세션, RBAC 메뉴 숨김, Task Policy 권한을 확인한다.
- [ ] Prompt Catalog, Prompt Builder, Prompt Reuse, Task History를 확인한다.
- [ ] 이미지 업로드, task 제출, 상태 모니터, 완료 영상 preview/download가 EFS metadata와 함께 정상인지 확인한다.
- [ ] CloudWatch에 migration, RDS SSL, EFS, prompt LLM 관련 반복 예외가 없는지 확인한다.

## 7. 롤백 경계

- 서비스 코드/이미지 문제: 직전 healthy task definition으로 service만 rollback한다.
- migration 적용 후: 자동 schema downgrade를 하지 않는다. 새 migration은 기존 행을 바꾸지 않지만, down도 별도 승인·백업·영향 분석 후에만 검토한다.
- EFS와 RDS 운영 데이터는 rollback 과정에서 조작하지 않는다.

## 8. 배포 기록

아래 값만 운영 기록에 남긴다. 비밀값은 기록하지 않는다.

```text
배포 일시(KST):
Git commit / ECR immutable tag:
image digest:
이전 / 신규 task definition:
migration check 결과(current head, target head, exit code):
migration apply task ARN(실행한 경우만):
Canary 완료 시각:
health / 로그인 / task 생성 / EFS 검증 결과:
```
