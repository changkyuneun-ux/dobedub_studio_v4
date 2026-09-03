# 1순위 착수 계획 - Grok 이미지 이해 기반 Positive Prompt와 WAN I2V 실행 Workspace

- 작성일: 2026-08-31
- 상태: **구현 전 승인용 계획 및 UI 아티팩트**
- 대상: `Workspace`의 이미지 로드, 프롬프트 설정, 즉시 실행 요청
- 관련 화면 목업: [Grok Vision Workspace 목업](2026-08-31-grok-vision-prompt-workspace-mockup.html)
- 관련 관리자 목업: [Grok 작업 지시 문서 관리 목업](2026-08-31-grok-instruction-admin-mockup.html)
- 초기 JSON 아티팩트: [Grok WAN I2V 작업 지시 세트](2026-08-31-grok-wan-i2v-instruction-set.example.json)
- 선행 문서: [우선순위 재편 로드맵](2026-08-31-priority-roadmap.md), [품질·템플릿 거버넌스](2026-08-30-quality-and-template-governance-design.md)

## 1. 목적과 범위

이 착수 항목은 사용자가 노드 파라미터를 직접 조절해 WAN 결과를 불안정하게 만드는 현재 흐름을 정리한다. Grok은 업로드 이미지를 이해해 제공된 WAN I2V 규칙 Markdown 기준의 영문 Positive Prompt만 반환한다. Studio는 이 **생성된 프롬프트와 원본 이미지 asset을 같은 슬롯·세그먼트에 페어링**하고, 최종 RunPod Serverless 요청에 함께 넣는다. Grok은 영상을 생성하거나 RunPod 워크플로우를 실행하지 않는다.

이번 범위에서 사용자가 선택하는 실행 값은 **영상 길이** 하나뿐이다.

| 구분 | 정책 |
|---|---|
| Positive Prompt | Grok Vision 생성 후 사용자가 직접 편집 가능 |
| Negative Prompt | 워크플로우 기본값을 초기값으로 노출. Workspace에서 직접 수정·기본값 복원 가능 |
| 입력 해상도 | 업로드 자산의 가로·세로를 읽어 WAN 노드에 서버가 주입 |
| length | `49 (약 3초)`, `81 (약 5초, 기본)`, `161 (약 10초)` |
| FPS | `16` 고정, UI에서 변경 불가 |
| Seed | 서버가 실행 시 자동 생성, 결과/Task History에만 기록 |
| 그 외 노드 값 | 워크플로우/paramconfig 기본값 유지, 사용자 UI 제거 |

이 문서는 RunPod 성능·큐·배치 개선을 대체하지 않는다. 다만 이후 배치·멀티 Task 확장의 입력 계약을 안정화하는 첫 단계다.

## 2. 기존 계획에서 달라지는 결정

[2026-08-31 우선순위 재편 로드맵](2026-08-31-priority-roadmap.md)의 P5는 Qwen과 Grok의 병행을 가정했다. 이번 착수 범위에서는 **사용자용 Positive Prompt 생성 경로를 Grok Vision으로 전환**한다.

1. `프롬프트 생성 · Qwen`, Qwen 상태 문구, Qwen 전용 사용자 UI는 Grok 기준으로 교체한다.
2. Qwen 호출 코드는 첫 배포 직후의 장애 복구를 위해 서버 내부에만 비활성 fallback으로 남길 수 있으나, 일반 사용자 흐름과 상태 화면에서 선택·노출하지 않는다.
3. 시스템 프롬프트는 기존 `prompt_system_prompts`와 버전 테이블을 재사용하되, 신규 코드(예: `grok_wan_i2v_vision`)와 provider/model 정보를 분리해 관리한다.
4. 첨부된 네 규칙 문서는 `grok_wan_i2v_vision` 시스템 프롬프트의 최초 기준 본문으로 등록한다. `규칙_00_유형판정`은 라우터, `규칙_01_배경_이미지`·`규칙_02_정적_캐릭터`·`규칙_03_동적_이미지`는 상호 배타적인 생성 분기다.

xAI 공식 문서는 이미지 입력 가능한 모델이 `/v1/responses` 또는 Chat Completions에서 이미지 URL 혹은 data URL을 받을 수 있고, JPEG/PNG와 이미지당 20 MiB 제한을 안내한다. 이 제약을 서버 검증에 그대로 반영한다. [xAI Image Understanding](https://docs.x.ai/developers/model-capabilities/images/understanding), [xAI Models](https://docs.x.ai/developers/models)

### 2.1 규칙 문서의 시스템 프롬프트 반영 방식

Grok에는 네 문서를 단순히 이어 붙이지 않는다. 먼저 `규칙_00_유형판정`으로 입력 이미지 하나를 아래 셋 중 하나로 **단일 분류**한 뒤, 대응하는 하위 규칙 하나만 적용한다.

| 분류 코드 | 적용 규칙 | 서버 처리 |
|---|---|---|
| `outdoor_background` | 배경 이미지 규칙 | 날씨·환경 단서에 근거한 30~70단어 영상 프롬프트 생성 |
| `indoor_background` | 배경 이미지 규칙의 예외 | 자동 프롬프트 미생성. `직접 입력 필요`로 표시하고 실행 차단 |
| `static_character` | 정적 캐릭터 규칙 | 인물의 idle 동작 1개와 종속 동작 최대 1개로 50~90단어 생성 |
| `dynamic_image` | 동적 이미지 규칙 | 이미지에 이미 보이는 주 동작 1개와 종속 동작 최대 1개로 생성 |

공통 제약은 모든 생성 분기에 강제한다. 새 인물·사물·배경·그래픽 추가 금지, 외형·의상·배경 재나열 금지, 입·호흡·발화·표정 변화 관련 묘사 금지, `No camera movement`, 스타일 구문 1개, 마지막 문장 `smooth movement.`를 포함한다. Grok의 분석 문장과 분류 근거는 UI의 상태 정보와 Task 추적 정보에만 쓰며, ComfyUI에 전달하는 Positive Prompt에는 포함하지 않는다.

## 3. 목표 사용자 흐름

```text
워크플로우 선택
  -> 키프레임 슬롯에 이미지 업로드
  -> 자산의 원본 해상도 읽기
  -> WAN 적용 해상도 계산·검증
  -> Grok 이미지 이해 API에 이미지 + 유형 판정 라우터 + 분기 규칙 전달
  -> 슬롯별 유형·근거·Positive Prompt 초안 반환
  -> 이미지 옆에서 초안 검토·직접 편집·재생성
  -> 이미지-Positive/Negative Prompt 페어링 확인
  -> 길이(49/81/161)만 선택
  -> Studio가 원본 이미지 asset + 최종 Positive Prompt를 동일 세그먼트에 페어링
  -> 서버 제출 검증
  -> 서버가 이미지, Positive/Negative Prompt, 해상도, 16 FPS, 자동 Seed, workflow 기본값을 RunPod payload에 반영해 즉시 실행 요청
```

### 3.1 이미지와 세그먼트의 기본 매핑 규칙

1. 슬롯마다 `image_prompt` 초안 하나를 만든다.
2. 세그먼트는 기본적으로 **시작 키프레임 슬롯의 Positive Prompt**를 사용한다.
3. 끝 키프레임이 있는 전환 세그먼트는 시작 이미지 프롬프트를 기본값으로 쓰되, 두 이미지가 서로 다른 대상일 경우에만 사용자가 세그먼트 편집 화면에서 문장을 합치거나 직접 편집한다.
4. 실행 시 최종 세그먼트 Positive Prompt와 그 출처 슬롯 ID를 Task에 함께 저장한다.

이 규칙은 1 이미지/1 세그먼트 워크플로우에서는 즉시 명확하다. 여러 키프레임의 프롬프트를 자동으로 **합성**할지, 시작 이미지 문장만 기본 적용할지는 품질에 큰 영향을 주므로, 첫 구현은 2번의 보수적 기본값으로 고정한다.

## 4. 화면 변경 설계

### 4.1 STEP 1 - 이미지 로드

현재 `Keyframe Slots`의 카드형 업로드는 유지한다. 단, 이미지 업로드가 끝난 슬롯의 오른쪽에 `Grok Positive Prompt` 패널을 붙인다. 이 패널의 결과는 해당 이미지 슬롯에만 귀속된다.

- 왼쪽: 썸네일, asset ID, 파일명, 원본 `W × H`, WAN 적용 `W × H`, 교체/삭제.
- 오른쪽: `업로드 대기 → 분석 요청 중 → 유형 판정 → 초안 완료 → 직접 입력 필요 → 오류` 상태, 영문 Positive Prompt 편집 영역, `재생성` 버튼.
- 다중 슬롯일 때도 각 행은 `SLOT 01 -> Positive Prompt`처럼 한 쌍으로 유지한다.
- 이미지가 없는 슬롯에는 Grok 요청을 만들지 않는다.
- 업로드가 서버에 정상 저장되면 해당 슬롯만 자동 분석한다. 최초 분석용 별도 버튼은 두지 않는다.
- 이미지가 모두 채워졌지만 프롬프트가 없는 경우, 실행 버튼은 “프롬프트 생성 또는 직접 입력 필요” 상태를 보여 준다.
- `실내 배경`은 규칙상 자동 생성하지 않는다. 슬롯에는 판정 근거와 함께 `직접 입력 필요`를 명시하고, 사용자가 Positive Prompt를 직접 입력하기 전에는 다음 단계로 진행하지 못하게 한다.

Grok 호출은 **업로드 성공 직후 자동 실행**을 기본으로 한다. 사용자가 이미지를 교체하면 이전 초안을 즉시 `STALE` 처리하고 새 asset에 대해서만 한 번 재요청한다. 화면 새로고침, Task History 재진입, 이전 Task 재작업 로드는 기존 저장 초안을 다시 사용하며 자동 재호출하지 않는다. `재생성`은 사용자가 명시적으로 요청할 때만 새 호출을 만들고, 호출 중에는 비활성화한다.

### 4.1.1 자동 생성 상태와 비용 보호

| 상태 | 진입 조건 | UI와 실행 정책 |
|---|---|---|
| `UPLOADING` | 파일 전송 중 | 슬롯만 표시하고 Grok 요청 없음 |
| `PROMPT_GENERATING` | asset 저장 완료 후 자동 요청 | 로딩 상태와 취소 불가 안내. 동일 asset의 중복 요청 차단 |
| `READY` | 규칙 검증을 통과한 초안 수신 | Positive Prompt 직접 편집 및 `재생성` 가능 |
| `MANUAL_REQUIRED` | `indoor_background` 등 자동 문장 미생성 규칙 | 판정 근거와 직접 입력 안내. Positive 입력 전 실행 차단 |
| `PROMPT_FAILED` | timeout, 429, 5xx, 형식 오류 | 업로드와 기존 편집값은 유지하고 `재생성`만 제공 |
| `STALE` | 업로드 이미지 교체 또는 지시 문서 버전 변경 | 이전 결과를 실행에 사용하지 않고 새 결과가 올 때까지 대기 |

- 중복 방지 키는 `asset_id + instruction_set_version + grok_model + request_profile`로 구성한다.
- 자동 재시도는 일시적 네트워크 오류, 429, 5xx에만 최대 2회로 제한한다. 이미지 교체, 브라우저 새로고침, 화면 재진입은 재시도 횟수를 늘리지 않는다.
- 자동 분석 실패는 이미지 업로드 실패가 아니다. 사용자는 기존/직접 입력 Positive Prompt로 계속 작업할 수 있다.

### 4.2 Workspace 실행 설정

현재의 Keyword Builder, 카탈로그 트리, Qwen 생성 버튼, System Prompt 탭, Wan Node Config 슬라이더를 일반 사용자 화면에서 제거한다.

- 입력 이미지 옆의 동일 패널에서 Positive Prompt와 Negative Prompt를 모두 편집한다. RunPod 요청에는 이미지와 두 최종 문장이 함께 전달된다.
- Positive Prompt는 직접 편집 가능하며, `원본 이미지로 재생성` 버튼은 연결된 슬롯의 Grok 이미지 이해 API를 다시 호출한다.
- Negative Prompt는 workflow 기본값을 초기값으로 표시한다. 사용자는 수정할 수 있고, `기본값 복원`으로 해당 workflow 기본값으로 되돌릴 수 있다.
- 길이 선택은 같은 Workspace의 상단 고정 영역에 `49 / 81 / 161` 3개 segmented control로 둔다. 기본 선택은 `81 (약 5초)`이다.
- `FPS 16`, `Seed 자동 생성`, `workflow 기본 설정 적용`은 설정 카드로 노출하되 편집 컨트롤은 두지 않는다.
- `RunPod에 실행 요청` 버튼은 별도 실행 전 확인 페이지를 거치지 않는다. 클릭 시 서버가 이미지 수, 프롬프트 입력, 해상도 target, task 정책을 검증한 뒤 즉시 Job을 생성한다. 오류는 현재 Workspace에 인라인으로 표시한다.
- 세그먼트 적용 미리보기와 payload 미리보기는 Workspace에서 제거한다. 실제 적용값, 실행 시각, seed, 상태는 Task History 상세에서 확인한다.

### 4.3 관리자 - Grok 작업 지시 문서 관리

관리자 메뉴에 `Prompt Instructions`를 추가한다. 이는 기존 Prompt Catalog와 분리된 관리 대상이다. Catalog는 사용자가 고르는 키워드 사전이고, 작업 지시 문서는 Grok이 이미지를 판정하고 WAN I2V Positive Prompt를 작성하는 규칙 원문이다.

- 좌측 목록: 지시 문서의 순서, 이름, 역할(`CORE`, `ROUTER`, `GUIDE`), 활성 상태, 버전.
- 우측 편집기: 제목, 역할, 우선순위, 활성 여부, Markdown 본문을 수정하고 저장한다.
- `작업 지시 문서 추가`: 빈 문서를 추가한 뒤 역할·우선순위·본문을 입력한다. 삭제는 현재 활성 instruction set에 포함되지 않은 문서만 허용한다.
- `JSON 미리보기`: 현재 활성 문서를 우선순위와 파일 순서대로 조합한 읽기 전용 JSON을 표시한다.
- `저장`은 Draft 버전을 만들고, `활성 버전 적용`은 해당 set의 새 버전을 발행한다. 실행 중인 Task에는 기존 버전을 유지하고, 새 프롬프트 생성부터 새 버전을 사용한다.

최초 세트는 아래 다섯 문서다.

| 순서 | 역할 | 문서 | 책임 |
|---:|---|---|---|
| 10 | `CORE` | Wan2.2 i2v 프롬프트 변환기 | 사용자 지시 우선, 파일별 오름차순 처리, 출력 원칙 |
| 20 | `ROUTER` | 규칙 00 · 유형 판정 | 이미지별 단일 유형 판정 및 분기 선택 |
| 30 | `GUIDE` | 규칙 01 · 배경 이미지 | 배경/실내 예외/실외 날씨 모션 |
| 40 | `GUIDE` | 규칙 02 · 정적 캐릭터 | IDLE 동작과 표정·종속 모션 제한 |
| 50 | `GUIDE` | 규칙 03 · 동적 이미지 | 원화에 있는 동작 하나의 단순화 |

`CORE`가 상세 문서와 충돌하면 우선한다. 다만 API 응답 JSON 계약은 앱이 보장하는 외부 인터페이스이므로, 관리자 본문과 별도로 고정된 시스템 envelope에서 강제한다. 이로써 문서를 자유롭게 편집해도 슬롯 매핑 파싱이 깨지지 않는다.

## 5. 백엔드·데이터 계약

### 5.1 Grok 이미지 이해 Prompt provider

새 서비스 책임은 “이미지와 시스템 프롬프트를 받아 Positive Prompt 하나를 반환”하는 것으로 한정한다. Grok 응답은 Studio 내부의 슬롯 초안이며, RunPod에는 Studio가 원본 이미지와 함께 최종 선택·편집된 문장만 전달한다.

```text
input asset bytes + metadata
  + 활성 작업 지시 세트(JSON의 CORE/ROUTER/GUIDE Markdown)
  + workflow / segment context
  -> xAI Responses API
  -> strict JSON validation
  -> 슬롯 번호 오름차순의 prompt draft 목록
  -> Studio pairs { sourceAssetId, positivePrompt } for the segment
  -> RunPod workflow request with original image asset + final segment prompt
```

- 호출은 서버에서 수행한다. 브라우저는 Grok API key, 이미지 data URL, 시스템 프롬프트 원문에 직접 접근하지 않는다. Grok에 분석용으로 전달된 이미지는 RunPod에 보낼 원본 asset을 대체하지 않는다.
- 이미지 asset은 EFS/스토리지에서 읽고, JPEG/PNG, 20 MiB 이하를 검사한다. 그 외 형식은 서버가 허용 형식으로 안전 변환하거나 명확히 거부한다.
- 결과 형식은 자유 문장 대신 최소 JSON 계약으로 강제한다.

```json
{
  "instructionSetVersion": 1,
  "items": [
    {
      "slotIndex": 1,
      "classification": "outdoor_background | indoor_background | static_character | dynamic_image",
      "classificationReason": "short internal trace",
      "positivePrompt": "English WAN I2V prompt only, or null for indoor_background",
      "warnings": ["manual_input_required"]
    }
  ]
}
```

- JSON 파싱 실패, 슬롯 누락·중복·순서 오류, 분류 누락, 과도한 길이, 금지된 메타 지시는 오류로 처리한다. 단 `indoor_background`의 빈 Positive Prompt는 정상적인 `manual_input_required` 상태이며, 자동으로 Qwen 문장으로 대체하지 않는다.
- 재시도는 네트워크/429/5xx에만 제한적으로 수행하고, 사용자 요청 ID와 중복 방지 키로 중복 호출을 막는다. 업로드 직후 요청은 UI 응답을 막지 않는 서버 작업으로 처리하며, 슬롯 상태를 조회해 결과를 반영한다.

### 5.2 환경 변수 및 비밀값

새 이름으로 Grok 경로를 Qwen 설정과 분리한다. 값은 `.env.example`에 이름만, ECS에는 Secrets Manager 참조로 넣는다.

```dotenv
# Required
GROK_ENABLED=1
GROK_API_KEY=                     # Secret: never commit or expose to the browser
GROK_BASE_URL=https://api.x.ai/v1
GROK_MODEL=                       # xAI console에서 확인한 이미지 입력 가능 모델 ID

# Automatic upload-to-prompt orchestration
GROK_AUTO_GENERATE_ON_UPLOAD=1
GROK_MAX_CONCURRENT_REQUESTS=2
GROK_MAX_RETRIES=2
GROK_RETRY_BACKOFF_SECONDS=2

# Request and input limits
GROK_CONNECT_TIMEOUT_SECONDS=10
GROK_REQUEST_TIMEOUT_SECONDS=120
GROK_MAX_IMAGE_BYTES=20971520
GROK_MAX_OUTPUT_TOKENS=600
GROK_TEMPERATURE=0.2
```

`GROK_API_KEY`와 모델 ID는 백엔드만 읽는다. 로컬은 프로젝트 루트의 `.env`에 실제 key를 넣고, `.env.example`에는 빈 값만 둔다. ECS 운영은 `GROK_API_KEY`를 AWS Secrets Manager의 별도 Secret으로 저장한 뒤 Task Definition의 `valueFrom`으로 연결한다. 프런트엔드 번들, Git, 브라우저 네트워크 응답에는 어떤 경우에도 key를 포함하지 않는다.

모델명은 구현 직전 xAI 콘솔에서 조직에 허용된 이미지 입력 모델로 확정한다. 별칭 모델은 자동 변경 위험이 있으므로, 운영 품질 비교 기간에는 날짜가 붙은 고정 모델 ID를 우선 사용한다.

현재 v4의 `PROMPT_LLM_*`는 Qwen/RunPod provider 설정이다. Grok으로 전환할 때 이 값을 덮어쓰지 않고 `GROK_*` 설정과 별도 `grok_prompt_client`를 추가한다. 전환 검증이 끝난 뒤에만 Workspace의 provider 선택을 Grok으로 고정하고, 기존 Qwen 경로는 롤백 기간 동안 유지한다.

### 5.3 작업 기록

프롬프트 생성 전에는 Workspace 상태가 `slotIndex`를 키로 초안을 보관한다. 제출이 성공하면 최종값만 Task에 영속화한다.

`task_prompts.metadata_json`에는 아래 추적 정보를 추가한다. 기존 Task를 수정하지 않으며, 새 Task에만 기록한다.

```json
{
  "sourceAssetId": "asset_...",
  "sourceSlotIndex": 1,
  "promptSource": "grok_vision",
  "imageClassification": "static_character",
  "imageClassificationReason": "main subject is present without visible action cues",
  "generationRule": "static_character_v1",
  "provider": "xai",
  "model": "configured-model-id",
  "instructionSetCode": "grok_wan_i2v_transformer",
  "instructionSetVersion": 1,
  "instructionDocumentVersions": { "core": 1, "rule_00": 1, "rule_02": 1 },
  "inputImage": { "width": 720, "height": 1280 },
  "appliedWanResolution": { "width": 720, "height": 1280 },
  "frames": 81,
  "fps": 16,
  "seedPolicy": "server_generated"
}
```

이미지별 초안과 세그먼트 최종 프롬프트가 1:N으로 갈라지는 고급 합성 기능이 필요해지면, 그때 `task_input_prompt_mappings` 별도 테이블을 추가한다. 첫 구현에서 스키마를 미리 크게 확장하지 않는다.

## 6. WAN 파라미터 주입 규칙

### 6.1 해상도

업로드 완료 시 이미 저장하는 `assets.image_width`, `assets.image_height`를 신뢰하되, 실행 직전 파일을 다시 읽어 누락·불일치를 검증한다. 모든 workflow에는 metadata/paramconfig에 해상도 입력 target이 명시돼 있어야 한다.

1. 원본 가로·세로를 읽는다.
2. 워크플로우가 선언한 WAN 허용 종횡비와 픽셀 예산 범위 안에서 값을 계산한다.
3. 노드 요구에 맞게 16의 배수로 스냅한다.
4. 계산된 `width`, `height`를 metadata가 지정한 실제 노드 입력에만 패치한다.
5. target이 없거나 검증에 실패하면 workflow 기본값으로 조용히 대체하지 않고, **제출 전 차단**한다.

UI에는 원본과 적용값이 함께 보인다. 예: `원본 720 × 1280 -> WAN 적용 720 × 1280`.

### 6.2 length, FPS, seed

| 사용자 선택 | 내부 frames | UI 표시 | 서버 동작 |
|---|---:|---|---|
| 49 | 약 3초 | `49 · 3초` | 해당 workflow의 frames target에 49 주입 |
| 81 | 약 5초 | `81 · 5초 · 기본` | 기본 선택 및 frames target에 81 주입 |
| 161 | 약 10초 | `161 · 10초` | frames target에 161 주입, 실행 전 비용/시간 안내 |

- `FPS=16`은 서버가 항상 최종 FPS target에 주입한다. workflow가 해당 target을 선언하지 않으면 등록/활성화 단계에서 실패 처리한다.
- seed는 요청 시점에 서버가 안전한 범위의 정수를 만들어 patch하고, 실제 사용값을 Task 결과에 기록한다. UI에는 입력란을 두지 않는다.
- steps, cfg, motion shift, VAE/codec, 모델 선택 등 나머지 값은 workflow 기본값을 건드리지 않는다.

## 7. 구현 순서와 검증

| 순서 | 작업 | 완료 기준 |
|---:|---|---|
| 0 | 제공 규칙 MD, Grok 모델 ID, 해상도 규칙 확정 | 4개 규칙을 버전 있는 시스템 프롬프트로 등록하고 허용 해상도 기준을 고정 |
| 1 | Grok client 및 작업 지시 JSON 세트/관리 API 추가 | JPEG/PNG 1장에 유형 판정과 strict JSON Positive Prompt 반환, key 미노출 |
| 2 | asset 저장 후 자동 생성 오케스트레이터 추가 | 슬롯별 상태, 중복 방지 키, 이미지 교체 무효화, 제한 재시도가 동작 |
| 3 | asset 기반 이미지 전달·크기 검증·해상도 계산 추가 | 업로드 이미지 3종의 원본/적용 해상도와 오류가 일관됨 |
| 4 | workflow metadata target 검증 및 서버측 patch | 49/81/161, width/height, FPS=16, auto seed가 실제 exported workflow에 반영됨 |
| 5 | Workspace 단일 화면 UI 축소·이미지/Positive/Negative Prompt 매핑 | 다중 슬롯에서도 각 이미지와 두 프롬프트가 혼동 없이 표시되고 즉시 제출 가능 |
| 5-1 | 관리자 Prompt Instructions 화면 | 지시 문서 추가·수정·저장·활성 버전 적용과 JSON 미리보기가 가능 |
| 6 | Task metadata·History 표시 및 회귀 테스트 | Task에서 프롬프트 출처, 모델, 해상도, frames, FPS, seed를 조회 가능 |
| 7 | 운영 Secret 등록·staging 검증 | Grok 성공/429/5xx/빈 응답/비지원 이미지에서 올바른 사용자 안내 |

### 필수 테스트 시나리오

1. 1-image workflow: 업로드 완료 → Grok 자동 생성 → 직접 편집 → 81 frames 제출.
2. 3-image workflow: 각 슬롯에 서로 다른 Prompt가 생성되고, SEG 01/02의 기본 매핑이 올바름.
3. 이미지를 업로드하지 않은 경우: Grok 생성과 Run이 차단되고 i2v 안내가 표시됨.
4. `49`, `81`, `161` 각각: 실제 patched workflow의 frames 값과 결과 metadata가 일치함.
5. 세로, 가로, 극단적 비율 이미지: 원본·적용 해상도 표기 및 fail-closed 검증.
6. Grok timeout/429/JSON 오류: 사용자 편집 중인 문장과 이미지가 지워지지 않으며 재시도 버튼만 활성화됨.
7. Negative Prompt 수정·기본값 복원: 최종 편집값이 RunPod payload와 Task 기록에 반영되고 복원 시 workflow 기본값으로 정확히 돌아감.
8. 별도 확인 화면 없이 실행 요청: 서버 검증 통과 후 Job이 생성되고 실패 시 Workspace에 오류가 표시됨.
9. 기존 workflow: 노드 기본값이 길이·해상도·FPS·Seed 외에는 변하지 않음.
10. 실외 배경, 실내 배경, 정적 캐릭터, 동적 이미지: 정확히 하나의 규칙만 적용되고, 실내 배경은 `직접 입력 필요`로 전환됨.
11. 생성 프롬프트: 금지된 얼굴·입·발화 묘사, 새 객체, 카메라 이동, 복수 주 동작이 포함되지 않음.
12. 업로드 후 새로고침/화면 이탈/Task History 왕복: 동일 asset과 instruction set version에 대해 추가 Grok 호출 없이 저장 초안을 재표시함.
13. 동일 이미지를 두 번 빠르게 교체: 마지막 asset의 결과만 `READY`가 되고 이전 응답은 `STALE`로 폐기됨.

## 8. 위험과 대응

| 위험 | 대응 |
|---|---|
| Grok 모델이 이미지 입력을 지원하지 않거나 조직 권한이 없음 | 배포 전 실제 key로 smoke test를 통과한 모델 ID만 운영 Secret에 등록 |
| 이미지가 외부 AI API로 전달됨 | 생성 버튼 인접 안내, 서버 전송만 허용, asset URL 공개 금지, 로그에 base64 기록 금지 |
| 모델이 장면에 없는 내용을 과도하게 추가 | 시스템 프롬프트에 원본 보존·추가 객체 금지·주 동작 1개·No camera movement 규칙을 명시하고, 결과를 사용자가 편집 후 적용 |
| 실내 배경에 동작 프롬프트가 생성됨 | 분류 결과가 `indoor_background`이면 프롬프트 생성 대신 직접 입력 상태를 반환하고 제출을 차단 |
| 원본 크기를 그대로 넣어 WAN 규칙 위반 | 서버가 16 배수·픽셀 예산·workflow target을 검증하고 실패 시 제출 차단 |
| template마다 frames/FPS/해상도 node가 다름 | metadata registration 단계에서 target을 추출·검증. 누락 workflow는 활성화 불가 |
| 자동 이미지 분석이 호출 비용을 급증시킴 | 업로드 성공 1회당 1회 요청, 슬롯별 중복 방지 키·저장 초안·제한 재시도·동시 요청 제한 적용. 새로고침/재진입은 재호출하지 않음 |

## 9. 구현 전 확인이 필요한 한 가지

1. **해상도 정책**: 업로드 원본이 16의 배수/허용 픽셀 예산을 벗어날 때, 자동 보정(권장)과 제출 차단 중 어떤 정책을 확정할지 필요하다. 이 계획은 원본 비율을 최대한 보존한 자동 보정 후 UI에 적용값을 공개하는 안을 기본으로 둔다.

## 10. 이번 요청에서 제외하는 것

- RunPod Worker/GPU/큐/배치 설정 변경
- Prompt Library 재사용·평가 구조 개편
- 워크플로우 템플릿 자체의 모델 교체
- 다중 이미지 프롬프트를 LLM이 자동 합성하는 고급 세그먼트 문장 생성
- 코드, DB migration, `.env`, ECS Secret 또는 배포 변경
