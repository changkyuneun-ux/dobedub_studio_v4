# 프롬프트 이력 수동 수정 및 즉시 RunPod 제출 설계

## 목적

프롬프트 생성 이력에서 원본 이미지를 확대 확인하고, 실패한 Positive Prompt를 작성자 또는 관리자가 직접 수정·저장할 수 있게 한다. 유효한 수동 프롬프트가 저장되면 프롬프트 생성 상태를 성공으로 전환하고, 같은 서버 요청 안에서 기존 RunPod 제출 파이프라인에 작업을 등록한다.

## 범위

- 프롬프트 생성 이력의 이미지 미리보기
- 실패한 Positive Prompt의 수동 편집과 저장
- 작성자 및 `jobs:manage` 관리자의 수정 권한
- 빈 Grok 결과의 실패 상태 통일
- 수동 저장 직후 RunPod 로컬 제출 큐 등록
- 중복 제출 및 실행 중 작업 변경 방지
- 프롬프트 생성 이력의 표시 문구와 상태 갱신

RunPod 외부 API 호출 방식, 워크플로우 JSON/Param Config, 배치 생성 규칙, 작업 제한 정책, 디스패처 동작은 변경하지 않는다.

## 용어와 상태

- `FAILED`: Grok 오류 또는 비어 있는 Positive Prompt 때문에 자동 생성에 실패한 상태다.
- `MANUAL_REQUIRED`: 기존 데이터 호환을 위해 읽을 수는 있지만, 신규 생성에는 사용하지 않는다. 화면과 필터에서는 `FAILED`로 취급한다.
- `READY`: 유효한 Positive Prompt가 확정된 상태다. 화면에는 `SUCCESS`로 표시한다.
- `PENDING_SUBMIT`: 불변 RunPod 요청 스냅샷 또는 WorkflowTask가 생성되어 기존 디스패처를 기다리는 상태다.

허용 상태 전이는 `FAILED | MANUAL_REQUIRED -> READY -> PENDING_SUBMIT`이다. 공백 문자열은 유효한 프롬프트가 아니며 상태를 전환하지 않는다.

## 사용자 경험

### 이미지 미리보기

프롬프트 이력의 이미지 셀을 버튼으로 만든다. 썸네일 또는 파일명을 누르면 기존 보호 자산 URL(`/api/files/{assetId}`)과 `ProtectedAssetPreview`를 사용하는 모달이 열린다. 배경 클릭, 닫기 버튼, Escape로 닫을 수 있다. 이미지 클릭은 행 선택 이벤트로 전파하지 않는다.

### Positive Prompt 편집

편집 가능한 Positive Prompt 셀을 누르면 모달이 열린다. 모달은 원 작업자, 파일명, 현재 생성 상태, 기존 실패 사유, 편집 textarea를 표시한다. 작성자 본인 또는 `jobs:manage` 관리자이면서 `prompts:build` 권한이 있는 경우에만 저장 버튼을 사용할 수 있다.

다음 항목은 편집할 수 없다.

- `GENERATING` 등 생성 진행 중인 초안
- 이미 삭제되지 않은 RunPod 요청 항목이나 WorkflowTask가 연결된 초안
- 현재 사용자에게 소유권 또는 관리자 권한이 없는 초안

저장 중에는 버튼을 비활성화한다. 성공 응답을 받으면 목록 행과 현재 선택 상세 정보를 응답 데이터로 동시에 교체한다. 전체 페이지 재조회에 의존하지 않는다.

### 표시 문구

- 표 헤더 `생성 결과`를 `프롬프트 생성`으로 변경한다.
- `READY`는 `SUCCESS`로 표시한다.
- `FAILED` 및 기존 `MANUAL_REQUIRED`는 `FAILED`로 표시한다.
- 생성 상태 필터는 `성공`과 `실패`로 표시하되 실패 필터는 두 저장 상태를 모두 조회한다.
- 자동 제출이 확정되면 RunPod 열은 `요청 대기`로 갱신한다.
- 관리자가 타 작업자의 프롬프트를 수정하면 모달에 관리자 수정임을 명시한다.

## 권한 모델

기존 `PATCH /api/prompts/image-drafts/{draft_id}`를 확장한다.

- 엔드포인트 접근에는 `prompts:build`가 필요하다.
- 작성자 본인은 자신의 초안을 수정할 수 있다.
- `jobs:manage` 사용자는 다른 작성자의 초안도 수정할 수 있다.
- 그 외 타 사용자 수정은 HTTP 403이다.
- 존재하지 않는 초안은 HTTP 404다.
- 상태 또는 RunPod 연결 때문에 수정할 수 없으면 HTTP 409다.
- 공백 Positive Prompt 등 입력 오류는 HTTP 400이다.

서비스 계층은 `actor_id`와 `can_manage`를 모두 받아 소유권을 검증한다. UI 가시성은 편의를 위한 것이며 권한의 최종 기준은 서버다.

## 저장 및 즉시 제출 흐름

클라이언트는 Positive Prompt 저장을 한 번만 요청한다. 브라우저가 저장 후 별도 제출 API를 호출하지 않는다.

1. 서버가 초안을 잠금 조회한다.
2. 권한, 상태, 기존 RunPod 연결 여부를 검증한다.
3. 공백이 아닌 Positive Prompt를 기록하고 `READY`로 전환한다.
4. 실패 메시지와 수동 필요 경고를 정리한다.
5. Batch 항목이면 `promotion_status=PENDING`으로 복구하고 기존 Batch 설정을 사용한다.
6. 독립 항목이면 기존 RunPod request batch 서비스로 불변 요청 항목을 만든다.
7. 기존 작업 생성 경로로 `PENDING_SUBMIT` WorkflowTask를 만든다.
8. 생성된 요청/작업 식별자와 최신 초안 payload를 응답한다.

실제 RunPod 외부 API 전송은 현재 디스패처가 처리한다. 저장 응답 전에 보장해야 하는 것은 외부 완료가 아니라 로컬 내구성 큐의 `PENDING_SUBMIT` 등록이다.

## Batch와 독립 초안

### Batch 초안

`batch_job_id`가 있는 초안은 기존 `promote_ready_batch_drafts` 계열 경로를 사용한다. Batch의 작업자, workflow ID, requested frames, resolution tier, Batch ID를 그대로 계승한다. 기존 Batch 취소 상태이면 자동 제출을 거절한다.

### 독립 초안

`batch_job_id`가 없는 초안은 기존 `create_runpod_request_batch` 및 작업 materialization 경로를 사용한다. 다음 값을 초안에서 복사해 불변 스냅샷으로 저장한다.

- 작성자/작업자
- asset ID
- workflow ID
- Positive/Negative Prompt
- requested frames
- resolution tier `sd`

관리자가 수정하더라도 생성되는 RunPod 작업의 소유자는 원 작성자이며, 관리자는 `submitted_by` 감사 정보에 기록한다.

## 중복 및 동시성

서버는 저장 전에 해당 초안과 연결된 삭제되지 않은 `RunpodRequestItem` 또는 `WorkflowTask`를 조회한다. 이미 존재하면 수정과 재제출을 거절한다.

동시에 같은 초안을 저장하는 요청은 행 잠금과 DB 유일성/조건부 갱신으로 하나만 성공시킨다. 두 번째 요청은 HTTP 409를 반환한다. 프런트 버튼 비활성화만으로 중복을 방지하지 않는다.

## 빈 Grok 결과 처리

Grok 호출이 정상 응답했더라도 `positive_prompt`가 공백이면 신규 초안 상태를 `FAILED`로 저장한다. 실패 메시지는 수동 입력이 필요하다는 사용자용 문구를 기록한다. 시도 레코드도 `FAILED`로 기록한다. 기존 `MANUAL_REQUIRED` 레코드는 마이그레이션하지 않고 조회·필터·수동 저장 단계에서 실패와 동일하게 처리한다.

## 원자성과 오류 처리

프롬프트 저장과 로컬 제출 준비는 서버가 조정한다. 사용자 입력을 잃지 않기 위해 다음 정책을 사용한다.

- 초안 저장이 실패하면 아무 상태도 변경하지 않는다.
- 초안 저장은 성공했지만 요청 스냅샷 또는 WorkflowTask 생성이 실패하면 초안은 `READY`로 유지한다.
- 제출 실패 사유를 `promotion_status=FAILED` 또는 요청 항목 실패 상태에 기록한다.
- API는 `promptSaved=true`, `runpodQueued=false`, 오류 메시지와 최신 초안 payload를 반환한다.
- UI는 `프롬프트 저장 완료 · RunPod 요청 실패`를 표시하고 기존 재제출 경로를 제공한다.

성공 응답은 다음 논리 필드를 포함한다.

```json
{
  "draft": { "draftId": "...", "status": "READY", "positivePrompt": "..." },
  "promptSaved": true,
  "runpodQueued": true,
  "runpodTaskId": "...",
  "runpodStatus": "PENDING_SUBMIT",
  "submissionError": null
}
```

## 기존 시스템과의 호환성

- 기존 프롬프트 관리 화면의 `updateImagePromptDraft` 호출 형식은 유지한다.
- 기존 정상 `READY` 초안 편집 기능은 자동 제출 동작과 분리한다. 프롬프트 이력의 실패 복구 요청에만 `submitImmediately=true`를 보낸다.
- RunPod 요청 스냅샷 생성 이후 원본 초안 변경으로 기존 작업 payload를 수정하지 않는다.
- Batch/Grok 처리 카운터는 기존 집계 함수를 통해 갱신한다.
- 프롬프트 생성 이력 페이지 크기, 필터, 키보드 행 이동은 유지한다.

## 테스트 기준

백엔드 테스트는 다음을 고정한다.

- 빈 Grok 결과가 신규 `FAILED` 초안과 실패 시도를 생성한다.
- 작성자가 자신의 실패 초안을 저장하고 `READY`로 전환한다.
- 관리자가 다른 작업자의 실패 초안을 저장한다.
- 일반 사용자의 타 작업자 수정은 403이다.
- 빈 Prompt, 생성 중, 취소 Batch, 기존 RunPod 연결 항목을 거절한다.
- 기존 `MANUAL_REQUIRED`도 수동 저장 후 `READY`가 된다.
- Batch 설정을 계승한 `PENDING_SUBMIT` 작업이 정확히 1건 생성된다.
- 독립 초안의 요청 스냅샷과 `PENDING_SUBMIT` 작업이 정확히 1건 생성된다.
- 동시/반복 저장은 중복 작업을 만들지 않는다.
- 제출 생성 실패 시 Prompt는 보존되고 오류 상태가 반환된다.
- 기존 Batch, Grok, RunPod 요청 테스트가 계속 통과한다.

프런트 계약 테스트는 다음을 고정한다.

- 이미지 셀 클릭 시 행 클릭과 분리된 미리보기 모달이 열린다.
- 편집 가능 조건과 관리자 안내가 표시된다.
- 저장 요청에 `submitImmediately=true`가 포함된다.
- 응답으로 목록 행과 선택 상세가 함께 갱신된다.
- `프롬프트 생성`, `SUCCESS`, `FAILED`, `요청 대기` 문구가 정확하다.
- 저장/제출 실패 메시지를 구분한다.

최종 검증은 `./scripts/verify.sh`를 실행한다.
