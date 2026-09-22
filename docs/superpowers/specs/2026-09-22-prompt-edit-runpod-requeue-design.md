# 프롬프트 수정 후 RunPod 재요청 설계

## 목적

성공한 Positive Prompt를 수정한 작업은 자동으로 영상을 생성하지 않는다. 프롬프트 이력의 RunPod 컬럼에 `재요청` 상태를 표시하고, 사용자가 명시적으로 확인한 경우에만 기존 RunPod 작업을 다시 제출한다.

재요청은 새 작업을 만들지 않고 기존 작업을 갱신한다. 기존 영상은 새 영상 생성과 저장이 성공할 때까지 유지하며, 성공한 뒤에만 새 결과로 교체한다.

## 범위

- 프롬프트 이력에서 성공한 Positive Prompt 수정
- 수정된 프롬프트와 연결된 기존 Workflow Task의 재요청 필요 상태 계산
- 사용자 확인 후 기존 Workflow Task 재제출
- 기존 출력 보존 및 새 출력 성공 후 교체
- Prompt Draft, Workflow Task, Task Prompt, RunPod Request Item의 프롬프트 정보 동기화

다음 항목은 변경하지 않는다.

- 실패 프롬프트를 수동 입력한 뒤 ComfyUI 요청 가능 목록에서 처음 요청하는 흐름
- 폴더 Batch의 자동 프롬프트 생성 및 일반적인 신규 영상 요청 흐름
- 기존 RunPod 작업 이력 화면의 범용 재작업 기능
- Workflow JSON 및 Param Config 형식

## 사용자 흐름

### 프롬프트 수정

1. 사용자가 성공한 Positive Prompt 셀을 선택한다.
2. 수정 모달에서 프롬프트를 저장한다.
3. 연결된 종료 상태의 Workflow Task가 정확히 한 개이면 프롬프트 이력의 RunPod 컬럼을 `재요청`으로 표시한다.
4. 저장만으로 RunPod 요청을 생성하거나 제출하지 않는다.
5. 연결된 Task가 없으면 기존처럼 `미요청` 상태로 두고 RunPod ComfyUI 요청 목록에서 최초 요청을 처리한다.

### 재요청

1. 사용자가 RunPod 컬럼의 `재요청`을 선택한다.
2. 다음 확인창을 표시한다.

   `기존 영상이 있는 경우 덮어쓰기가 됩니다. 진행하시겠습니까?`

3. `취소`는 어떤 데이터도 변경하지 않는다.
4. `확인`은 기존 Workflow Task를 재사용하여 `PENDING_SUBMIT`으로 전환한다.
5. 디스패처가 같은 Task를 RunPod에 제출하며 새 RunPod Job ID와 실행 상태를 기록한다.
6. 새 영상 생성 및 애플리케이션 저장이 성공하면 기존 출력 연결을 새 출력으로 교체한다.
7. 제출, 생성 또는 저장이 실패하면 기존 출력 연결을 유지한다.

## 재요청 필요 상태

DB에 별도의 영구 상태 컬럼을 추가하지 않는다. 다음 조건으로 `requeueRequired`를 계산한다.

- Prompt Draft 상태가 `READY`
- 연결된 삭제되지 않은 Workflow Task가 정확히 한 개
- Task가 종료 상태
- Prompt Draft의 현재 Positive Prompt가 Task payload 또는 Task Prompt에 저장된 실행 프롬프트와 다름

이 계산 결과는 프롬프트 이력 API 응답에 포함한다. 화면은 `requeueRequired=true`일 때 RunPod 컬럼에 `재요청` 액션을 표시한다.

Task가 실행 중이면 수정 프롬프트는 저장할 수 있지만 재요청 액션은 비활성화하고 현재 RunPod 상태를 유지한다. 연결 Task가 둘 이상이면 데이터 충돌로 간주하고 재요청을 허용하지 않으며 API가 명확한 충돌 오류를 반환한다.

## 데이터 갱신

재요청 확인은 하나의 DB 트랜잭션에서 다음 정보를 갱신한다.

### 유지하는 식별자와 연결

- `WorkflowTask.id`
- `WorkflowTask.prompt_draft_id`
- `WorkflowTask.batch_job_id`
- `RunpodRequestItem.id` 및 `request_batch_id`
- 작업 사용자, 워크플로우, 입력 Asset 연결
- 기존 출력 Asset 연결: 새 결과 저장 성공 전까지 유지

### 갱신하는 정보

- `WorkflowTask.payload_json`의 해당 segment Positive Prompt
- 연결된 `TaskPrompt.positive_prompt`
- 연결된 `RunpodRequestItem.positive_prompt`
- Task 실행 상태, progress, dispatch claim/attempt/error 필드
- RunPod 제출 및 상태 스냅샷
- 새 제출 성공 후 `runpod_job_id`
- 재요청 수행자와 시각을 payload의 감사 메타데이터에 기록

재요청 시점에는 기존 `TaskOutputAsset` 연결과 Task Prompt의 기존 `output_asset_ids`를 삭제하지 않는다.

## 출력 교체

기존 Task ID를 재사용하므로 S3 출력 Asset ID도 현재 규칙대로 Task ID와 출력 순번을 기준으로 안정적으로 생성한다.

새 RunPod 결과가 `COMPLETED`이고 출력 저장까지 성공한 경우에만 다음 순서로 교체한다.

1. 새 출력 Asset을 등록 또는 갱신한다.
2. Task의 출력 Asset 연결을 새 결과 목록으로 교체한다.
3. Task Prompt의 `output_asset_ids`를 새 결과로 갱신한다.
4. 새 결과가 정상 조회되는 상태로 DB commit한다.

출력 저장이 실패하면 Task는 실패 원인을 기록하되 기존 `TaskOutputAsset` 및 기존 영상 조회 연결은 유지한다. 새 결과로 교체한 뒤 더 이상 참조되지 않는 이전 저장 객체의 물리 삭제는 이번 범위에 포함하지 않는다.

## API

프롬프트 수정 API 응답에는 다음 파생 필드를 추가한다.

- `requeueRequired`
- `requeueTaskId`
- `requeueBlockedReason`

프롬프트 이력 전용 재요청 API를 추가한다.

`POST /api/prompts/image-drafts/{draft_id}/requeue-runpod`

권한:

- 원래 작업자
- `jobs:manage` 권한이 있는 관리자

응답은 유지된 Task ID, `PENDING_SUBMIT` 상태 및 기존 출력 보존 여부를 반환한다. 실행 중, 연결 누락, 다중 Task 연결, 권한 부족은 각각 409, 404 또는 403으로 구분한다.

## 화면

- `requeueRequired=true`: RunPod 컬럼에 빨간 오류 상태가 아닌 별도의 `재요청` 버튼 표시
- 버튼 선택 시 확인/취소 모달 표시
- 확인 중 중복 클릭 방지
- 성공 시 행의 RunPod 상태를 `제출 대기`로 갱신
- 실패 시 기존 행과 영상 링크를 유지하고 오류 메시지 표시
- 키보드 행 이동과 이미지/프롬프트 셀 동작은 유지

## 테스트

### 백엔드

1. 성공 프롬프트 수정 후 `requeueRequired=true`, 자동 RunPod 작업 미생성
2. 재요청 확인 시 기존 Task ID와 연결 식별자 유지
3. Task payload, Task Prompt, Request Item의 Positive Prompt 동기화
4. 재요청 직후 기존 출력 연결 유지
5. 새 결과 저장 성공 후 출력 연결 교체
6. 새 결과 저장 실패 시 기존 출력 연결 유지
7. 취소에 해당하는 미호출 상태에서는 DB 변경 없음
8. 실행 중 Task, 다중 Task, 권한 없는 사용자 차단
9. Task 미연결 프롬프트는 `미요청` 유지

### 프런트엔드

1. 수정된 연결 Task의 RunPod 컬럼에 `재요청` 표시
2. 정확한 경고 문구와 확인/취소 버튼 표시
3. 취소 시 API 미호출
4. 확인 시 재요청 API 한 번만 호출
5. 성공 시 `제출 대기` 표시
6. 정상/실패 프롬프트 색상 및 편집 모달 회귀 확인

## 배포와 롤백

스키마 변경 없이 API, 서비스 로직, 프런트엔드만 변경한다. 전체 검증 후 기존 ECS 런북에 따라 immutable Git SHA 이미지로 배포한다.

롤백은 배포 직전 PRIMARY Task Definition으로 ECS service를 되돌린다. DB 스키마 변경이 없으므로 Alembic 롤백은 필요 없다. 재요청으로 이미 갱신된 Task는 기존 Task ID를 유지하므로 이전 애플리케이션에서도 일반 `PENDING_SUBMIT` 또는 종료 작업으로 조회할 수 있다.
