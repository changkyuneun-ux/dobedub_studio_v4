# Webtoon Cut Server Pipeline ECR Deployment Reference

> 목적: 이미지 컷 관리 서버 업로드/S3 컷 분리 버전을 ECR/ECS에 배포할 때 참조하는 운영 가이드다. 이 문서는 절차 문서이며, 작성 시점에는 실제 빌드·푸시·ECS 배포를 수행하지 않았다.

## 1. 배포 전 필수 확인

- 배포 대상 브랜치가 승인된 브랜치인지 확인한다.
- `docs/superpowers/plans/2026-09-15-server-webtoon-cut-pipeline.md`의 Global Constraints를 재확인한다.
- 신규 Alembic revision `20260915_0039`가 운영 DB에 적용 가능한지 staging에서 검증한다.
- Docker 이미지에 다음이 포함되는지 확인한다.
  - `poppler-utils`
  - `poppler-data`
  - `opencv-python-headless`
  - `numpy`
  - `boto3`
- ECS task role에 S3 권한이 있는지 확인한다.
  - source 원본 read/write
  - cut output read/write
  - manifest/summary/debug/download ZIP read/write
  - delete는 retention/cleanup 정책 범위에만 허용
  - 운영 `S3_PREFIX=prod` 기준 최소 object scope:
    - `arn:aws:s3:::dobedub-studio/prod/uploads/*`
    - `arn:aws:s3:::dobedub-studio/prod/webtoon-cut/*`
  - 기존 batch/request-batch 전용 policy만 있으면 `webtoon-cut` 결과 저장이 `S3 403`으로 실패한다.

## 2. 필수 환경 변수

운영 task definition에는 최소 아래 값이 필요하다.

```bash
PERSISTENCE_BACKEND=db
DATABASE_URL=<rds-url>
STORAGE_BACKEND=s3
S3_BUCKET=<bucket-name>
S3_PREFIX=dobedub-studio
RUN_SERVER_AUTO_MIGRATE=0
```

운영 기존 task definition에서 `S3_PREFIX=prod`를 사용 중이면 이 값을 유지한다. 배포 스크립트나 수동 task definition 갱신 시 예시값으로 덮어쓰지 않는다.

권장:

```bash
OBSERVABILITY_ENABLED=1
OBSERVABILITY_ENVIRONMENT=production
RUNPOD_DRY_RUN=0
```

주의:

- `RUN_SERVER_AUTO_MIGRATE=1`로 운영에서 자동 마이그레이션하지 않는다.
- DB migration은 배포 전 별도 one-off task 또는 승인된 migration job으로 실행한다.
- S3 bucket은 public access block을 유지한다.

## 3. 로컬 이미지 빌드 검증

```bash
docker build -t dobedub-studio:webtoon-cut .
```

검증 포인트:

- `apt-get install poppler-utils poppler-data` 단계 성공
- `poppler-data`에 포함된 Adobe-Korea1 CMap이 설치되어 한글 CID 폰트 PDF가 빈 텍스트로 렌더링되지 않는지 확인
- `pip install -r backend/requirements.txt` 성공
- `npm run build` 성공
- 이미지가 `scripts/run_server.py`로 기동 가능한지 확인

## 4. ECR 로그인 및 태깅

```bash
AWS_REGION=<region>
AWS_ACCOUNT_ID=<account-id>
ECR_REPOSITORY=<repository-name>
IMAGE_TAG=webtoon-cut-$(date +%Y%m%d-%H%M)

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker tag dobedub-studio:webtoon-cut \
  "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"
```

## 5. ECR push

```bash
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY:$IMAGE_TAG"
```

push 후 확인:

```bash
aws ecr describe-images \
  --repository-name "$ECR_REPOSITORY" \
  --image-ids imageTag="$IMAGE_TAG" \
  --region "$AWS_REGION"
```

## 6. DB migration

ECS 서비스 업데이트 전에 migration을 먼저 실행한다.

```bash
alembic upgrade head
```

검증 SQL:

```sql
select table_name
from information_schema.tables
where table_name in (
  'webtoon_cut_jobs',
  'webtoon_cut_sources',
  'webtoon_cut_units',
  'webtoon_cut_outputs',
  'webtoon_cut_downloads'
);
```

## 7. ECS task definition 업데이트

새 이미지 태그로 task definition revision을 생성한다.

확인 항목:

- CPU/Memory가 PDF 300dpi 렌더링과 OpenCV 처리에 충분한지 확인
- `/tmp` 사용량이 PDF page chunk 처리에 충분한지 확인
- task role S3 권한 확인
- security group egress가 S3, RDS, RunPod/Grok API에 필요한 범위만 허용되는지 확인

## 8. ECS 서비스 업데이트

```bash
aws ecs update-service \
  --cluster <cluster-name> \
  --service <service-name> \
  --task-definition <task-definition-family>:<revision> \
  --region "$AWS_REGION"
```

진행 확인:

```bash
aws ecs wait services-stable \
  --cluster <cluster-name> \
  --services <service-name> \
  --region "$AWS_REGION"
```

## 9. 배포 후 smoke test

1. 로그인
2. 이미지 컷 관리 메뉴 진입
3. 작은 JPG 파일 업로드
4. 작업 요청
5. 진행 중 job 상태가 유지되는지 확인
6. 컷 분할 이력에서 리스트 조회
7. 썸네일 preview 표시
8. 필터 결과 전체 선택
9. Grok 프롬프트 화면으로 보내기
10. Batch 처리 화면으로 보내기
11. 작업 취소 버튼이 active job에서만 표시되는지 확인

## 10. CloudWatch 확인

검색 키워드:

```text
webtoon-cut-monitor
Webtoon cut worker cycle failed
pdftoppm
pdfinfo
opencv
Asset access denied
```

알람 후보:

- `webtoon_cut_jobs.status = failed` 급증
- worker exception 로그 증가
- ALB 5xx 증가
- ECS task memory utilization 85% 이상 지속
- S3 403/404 증가

## 11. 롤백

롤백은 task definition revision을 이전 안정 버전으로 되돌린다.

주의:

- migration으로 생성된 신규 테이블은 기존 서비스에 영향이 없으므로 즉시 drop하지 않는다.
- 신규 기능 사용 중 생성된 S3 object는 retention 정책에 따라 정리한다.
- 이미 생성된 `webtoon_cut_image` asset이 I2V 입력으로 연결된 경우 삭제하지 않는다.
