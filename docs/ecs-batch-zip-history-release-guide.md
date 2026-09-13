# ECS Batch ZIP/History Release Guide

이 문서는 Batch ZIP 업로드/다운로드 구조 변경과 작업 이력 API 변경을 ECS에 배포하기 전 최종 점검하기 위한 가이드다. 기준 커밋은 `cdd021d Refine batch output zip and history navigation` 이후의 배포 대상 코드다.

## 1. 배포 전 Git 상태

배포 이미지는 반드시 의도한 commit에서 만들어야 한다.

```bash
cd "/Users/changkyuneun/Documents/New project/comfyui-video-studio-app-v4"
git status --short
git log -1 --oneline
```

기대값:

- `git status --short`가 비어 있어야 한다.
- `git log -1 --oneline`이 배포할 commit을 가리켜야 한다.
- `.env`, SQLite DB, uploads/outputs, `dist`, `node_modules`는 배포 commit에 포함하지 않는다.

## 2. 이번 릴리스 핵심 변경

### DB schema

이번 릴리스에는 Alembic migration이 포함된다.

정확한 파일명:

```text
backend/app/db/migrations/versions/20260906_0034_batch_source_zip_name.py
```

주의: `260906_0034_batch_source_zip_name.py`가 아니라 `20260906_0034_batch_source_zip_name.py`다.

변경 내용:

- `batch_jobs.source_zip_file_name` nullable `String(512)` 컬럼 추가
- 기존 batch row, prompt draft, workflow task, asset 데이터는 수정하지 않음
- downgrade는 컬럼 drop만 수행하므로 운영 rollback 시 별도 승인 없이 실행하지 않는다

### Backend API/service

- `POST /api/batch-jobs/zip`
  - ZIP 파일을 서버에 업로드한다.
  - ZIP 내부 `.jpg`, `.jpeg`, `.png`, `.webp`만 batch 대상이다.
  - `Thumbs.db`, `.DS_Store`, `__MACOSX`, AppleDouble 파일은 제외된다.
  - ZIP 파일명은 `sourceZipFileName`, 내부 상대경로는 prompt draft raw metadata로 보존된다.

- `GET /api/batch-jobs/{batch_job_id}/download`
  - 다운로드 파일명은 `업로드ZIP명_output.zip`이다.
  - ZIP 내부 결과는 `업로드ZIP명_output/원본하위폴더_output/원본파일명.mp4` 구조로 내려간다.
  - 원본 상대경로가 없는 과거 데이터는 기존 `output/*.mp4` fallback을 유지한다.

- `GET /api/batch-jobs/search`
  - 작업 이력 RunPod 탭의 Batch ID 리스트 박스 후보 API다.
  - 검색 대상은 Batch ID, 작업자명, 업로드 ZIP 파일명이다.
  - macOS 한글 파일명의 NFC/NFD 차이를 흡수해 부분 검색어로 후보를 반환해야 한다.
  - 검색어 자체를 다운로드 API의 batch id로 사용하지 않고, 사용자가 후보에서 선택한 정확한 batch id만 다운로드에 사용한다.

- `GET /api/batch-jobs`
  - Batch 처리 화면의 Batch 작업 이력 API다.
  - page size는 서버에서 5건으로 고정한다.
  - 프론트의 Batch 처리 이력 범위/총 페이지 계산도 5건 기준이어야 한다.

- `GET /api/history/prompts`
  - 프롬프트 이력 전용 API다.
  - page size는 서버에서 10건으로 고정한다.
  - 클라이언트가 `pageSize=20`, `pageSize=50`, `pageSize=200`을 보내도 응답 `pageSize`는 10이어야 한다.

- `GET /api/history/runpod`
  - RunPod 이력 전용 API다.
  - page size는 서버에서 10건으로 고정한다.
  - `workflowId`, `resultStatus`, `workerId`, `runDate`, `batchId` 필터가 기존 계약대로 동작해야 한다.

### Frontend

- 사이드 메뉴 순서:
  1. `작업 이력`
  2. `Batch 처리`
  3. `Grok 프롬프트 생성`
  4. `Runpod ComfyUI 요청`
  5. `Collection 관리`

- `작업 이력` 탭 순서:
  1. `RunPod 이력`
  2. `프롬프트 이력`

- 작업 이력의 RunPod/프롬프트 탭은 10건 단위로 조회하고 표시한다.

## 3. 로컬 사전 검증

배포 전 최소 검증:

```bash
python3.12 -m pytest backend/tests/test_batch_zip_service.py backend/tests/test_batch_job_service.py backend/tests/test_history_tab_api.py backend/tests/test_frontend_batch_management_contract.py -q
npm run build
git diff --check
```

기대값:

- pytest가 모두 통과한다.
- `npm run build`가 `tsc -b`와 `vite build`를 통과한다.
- `git diff --check` 출력이 없어야 한다.

Migration graph 검증:

```bash
python3 scripts/db_migration_smoke_check.py
```

기대값:

- 임시 SQLite DB에서 Alembic `upgrade head`가 성공한다.
- `migrationRequired=false` 상태까지 도달한다.

## 4. ECS 이미지 빌드 전 확인

배포 이미지에 migration 파일이 들어가는지 반드시 확인한다.

```bash
test -f backend/app/db/migrations/versions/20260906_0034_batch_source_zip_name.py
rg -n "revision = \"20260906_0034\"|source_zip_file_name" backend/app/db/migrations/versions/20260906_0034_batch_source_zip_name.py backend/app/db/models.py
```

기대값:

- migration 파일이 존재한다.
- `revision = "20260906_0034"`가 확인된다.
- `BatchJob` model에 `source_zip_file_name` 컬럼이 있다.

## 5. RDS Alembic Upgrade Gate

서비스 배포 전에 새 이미지와 동일한 task definition 환경으로 one-off migration check를 실행한다. 웹 서버 task 시작으로 migration을 대신하지 않는다.

운영 task definition 유지 조건:

- `RUN_SERVER_AUTO_MIGRATE=0`
- `PERSISTENCE_BACKEND=db`
- `DATABASE_URL`은 RDS MySQL secret 참조
- `DATABASE_SSL_CA=/app/certs/global-bundle.pem`
- `DATABASE_SSL_VERIFY_IDENTITY=1`
- EFS mount와 `/data/outputs` 설정 유지

one-off check command:

```text
python3 scripts/upgrade_database.py --check
```

판정:

- exit code `0`, `migrationRequired=false`: RDS가 이미 image head와 일치한다. migration 실행 없이 service 배포 가능.
- exit code `2`, `migrationRequired=true`: service 배포 전 아래 command로 migration one-off task를 한 번 실행한다.
- DB connection/SSL/security group 오류: 배포 중단. migration 필요 여부가 아니라 접속 실패다.

one-off migration command:

```text
python3 scripts/upgrade_database.py --if-needed
```

적용 후 재검증:

```text
python3 scripts/upgrade_database.py --check
```

기대값:

- exit code `0`
- `migrationRequired=false`
- `targetHeads`에 `20260906_0034`가 포함
- `currentHeads`가 `targetHeads`와 동일

가능하면 RDS에서 아래도 확인한다.

```sql
select version_num from alembic_version;
show columns from batch_jobs like 'source_zip_file_name';
```

기대값:

- `alembic_version.version_num = '20260906_0034'`
- `batch_jobs.source_zip_file_name` 컬럼 존재
- 컬럼은 nullable이며 기존 row를 강제로 갱신하지 않는다

## 6. Backend/Frontend API 전수 점검

### Batch ZIP 생성

점검 항목:

- ZIP 선택 후 확인 모달에 ZIP 파일명, workflow, 길이 정보가 표시되는지 확인
- `POST /api/batch-jobs/zip` 응답에 아래 값이 포함되는지 확인
  - `id`
  - `sourceDirName`
  - `sourceZipFileName`
  - `totalImages`
  - `requestedFrames`
  - `durationSeconds`
- `totalImages`가 ZIP 내부 처리 대상 이미지 수와 일치하는지 확인
- `.db`, `.DS_Store`, `__MACOSX` 파일이 batch 대상에 포함되지 않는지 확인

### Batch 상태/이력

점검 항목:

- Batch 처리 화면의 진행 중 Batch에서 prompt waiting/generating/completed/failed가 합산과 일치
- Grok 프롬프트가 완료되면 RunPod 요청관리 화면에 별도 단위작업 queue로 중복 생성되지 않음
- Batch 기반 RunPod task는 `작업 이력 > RunPod 이력`에 `batchJobId`와 함께 보임
- 동일 prompt draft에 workflow task가 중복 생성되지 않음

### Batch ZIP 다운로드

점검 항목:

- 다운로드 버튼이 완료된 batch에 표시됨
- 응답 header `Content-Disposition`에 UTF-8 `filename*`가 포함됨
- 예: `2권 08-10화.zip` 업로드 시 다운로드 파일명은 `2권 08-10화_output.zip`
- 압축 해제 후 구조는 아래처럼 원본 하위 폴더별 `_output` suffix가 붙음

```text
2권 08-10화_output/
  2권 08화_output/
    2_8_001.mp4
  2권 09화_output/
    2_9_001.mp4
  2권 10화_output/
    2_10_001.mp4
```

### 작업 이력 API

점검 항목:

- `GET /api/batch-jobs/search?query=장균` 응답에 해당 작업자의 batch 후보가 표시되는지 확인
- Batch ID 검색어 입력만으로는 `배치 ZIP`이 활성화되지 않고, 후보 리스트에서 batch를 선택해야 활성화되는지 확인
- 후보 선택 후 row checkbox를 모두 해제해도 `배치 ZIP` 다운로드가 가능한지 확인
- `GET /api/history/runpod?page=1&pageSize=20` 응답의 `pageSize`가 10인지 확인
- `GET /api/history/prompts?page=1&pageSize=20` 응답의 `pageSize`가 10인지 확인
- RunPod 이력 탭에서 10건 단위로 다음/이전 페이지가 동작
- 프롬프트 이력 탭에서 10건 단위로 다음/이전 페이지가 동작
- 필터 변경 시 첫 페이지로 돌아가고, 첫 행 자동 선택/상세 패널 표시가 유지됨

## 7. ECS Service 배포 순서

1. 로컬 검증 통과 commit을 기준으로 immutable image tag를 만든다.
2. ECR에 `linux/amd64` image를 push한다.
3. 현재 운영 task definition revision을 복제한다.
4. `Main` container image만 새 tag로 교체한다.
5. CPU/memory, role, secret, EFS, log group, port, environment를 기존 운영 revision과 비교한다.
6. 새 revision으로 one-off migration check를 실행한다.
7. 필요 시 one-off migration을 실행한다.
8. migration 재검증이 통과한 뒤 ECS service를 새 task definition으로 update한다.
9. ECS deployment가 `COMPLETED`가 될 때까지 이전 task를 수동 중지하지 않는다.

## 8. 배포 후 운영 확인

필수 확인:

- `GET /` -> `200`
- `GET /api/health` -> `200`
- 로그인 가능
- `Batch 처리` 메뉴 표시
- `작업 이력` 메뉴가 첫 번째로 표시
- `Grok 프롬프트 생성`, `Runpod ComfyUI 요청` 메뉴명에 `(단위작업)` 문구가 없음
- `작업 이력` 진입 시 `RunPod 이력` 탭이 먼저 표시
- RunPod/프롬프트 이력이 10건 단위로 조회됨
- 새 ZIP batch 요청이 생성되고 Batch ID가 `작업자_업로드ZIP명_yymmdd` 규칙을 따름
- CloudWatch Logs에 migration error, DB column error, history API 500이 반복되지 않음

## 9. 실패 시 중단 기준

아래 중 하나라도 발생하면 service 배포를 중단하거나 직전 healthy revision으로 rollback한다.

- `upgrade_database.py --check`가 DB 접속 오류로 실패
- `--if-needed` migration task exit code가 0이 아님
- migration 후 `currentHeads`가 `20260906_0034`에 도달하지 않음
- `batch_jobs.source_zip_file_name` 컬럼이 없음
- `/api/history/prompts` 또는 `/api/history/runpod`가 500을 반환
- Batch ZIP 다운로드가 `source_zip_file_name` 관련 예외로 실패
- ECS health check가 실패하거나 deployment가 `COMPLETED`에 도달하지 않음

## 10. 기록해야 할 배포 메모

배포 완료 후 아래를 남긴다.

```text
- Git commit:
- ECR image tag:
- ECS task definition revision:
- Alembic before currentHeads:
- Alembic targetHeads:
- Alembic after currentHeads:
- Migration one-off task ARN:
- ECS deployment result:
- /api/health result:
- 작업 이력 pageSize 확인:
- Batch ZIP 다운로드 확인:
```
