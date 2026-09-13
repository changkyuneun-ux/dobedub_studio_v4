# WAN 2.2 해상도·프레임 요건 반영 수정계획

> **For agentic workers:** REQUIRED SUB-SKILL: 이 계획을 구현할 때는 `superpowers:executing-plans`를 사용하고, 구현 완료 전 `superpowers:verification-before-completion`으로 검증 결과를 확인한다. 사용자가 명시적으로 병렬/하위 에이전트 수행을 요청한 경우에만 `superpowers:subagent-driven-development`를 사용한다.

**Goal:** `/Users/changkyuneun/runpod mcp/ECS-반영요건-해상도-프레임.md` 문서 기준으로, ECS가 WAN 2.2 RunPod 워커에 전달하는 workflow를 안정적으로 패치하도록 수정한다. 기존 구현 상태는 고려하지 않고, 문서 요건을 충족하는 최종 구조를 기준으로 한다.

**Architecture:** 요청 화면/배치 화면에서 선택된 `resolutionTier`와 duration을 API payload에 포함한다. 백엔드는 입력 이미지 메타데이터를 기준으로 WAN 크기를 계산하고, workflow JSON을 `class_type` 중심으로 탐색해 `WanImageToVideo`, `LoadImage`, `CLIPTextEncode` 값을 패치한다. RunPod 응답의 `generation[]`은 ECS 로그와 DB/API 응답에 보존한다.

**Tech Stack:** React/TypeScript frontend, FastAPI/Python backend, SQLAlchemy/SQLite or production DB, pytest, Vitest 또는 기존 frontend test runner, AWS ECS/Fargate, S3, RunPod Serverless.

**Primary Spec:** `/Users/changkyuneun/runpod mcp/ECS-반영요건-해상도-프레임.md`

## 반영 기준

- RunPod endpoint: `ykf5itlew8az50`
- RunPod worker: `v1.1.1-guard` 이상
- Worker guard env:
  - `WAN_MAX_PIXELS=921600`
  - `WAN_MAX_FRAMES=81`
  - `WAN_MAX_TOTAL_FRAMES=162`
- ECS의 해상도 정책:
  - `sd`: `409600` pixels
  - `hd`: `921600` pixels
- 기본 tier: `sd`
- WAN width/height는 16의 배수여야 한다.
- 입력 이미지 원본 해상도를 `WanImageToVideo` node에 그대로 넣지 않는다.
- 원본보다 업스케일하지 않는다.
- aspect ratio는 유지하고 crop은 16배수 보정으로 인한 최소 수준만 허용한다.
- `length=161` 단일 노드는 금지한다.
- 5초 요청: 단일 `WanImageToVideo.length=81`
- 10초 요청: `wan22_10s_chain.json`, `WanImageToVideo` 2개 각각 `length=81`, total `162`
- `batch_size=1` 고정
- workflow template은 flat API JSON만 사용한다.
- UI export/subgraph template은 사용하지 않는다.
- node id 하드코딩 금지. `class_type`과 입력 구조로 찾는다.
- `LoadImage.inputs.image`는 `images[].name`과 일치해야 한다.
- RunPod success/error manifest의 `generation[]`은 ECS 로그 및 DB/API 응답에 보존해야 한다.

## 대상 파일

- `backend/app/services/workflow_patch_service.py`
  - WAN 크기 계산
  - workflow node 탐색/패치
  - 프레임/총 프레임/batch size guard
  - 제출 직전 patch summary 및 `WanImageToVideo` 값 로그 생성
- `backend/app/services/studio_api_service.py`
  - 요청 payload에서 `resolutionTier` 수신/기본값 처리
  - S3 input image payload와 workflow patch 연결
  - RunPod submit 직전 로그 강화
- `backend/app/services/runpod_request_batch_service.py`
  - 일반 요청 관리/RunPod request batch의 `resolutionTier`, duration 전달
  - request history에 patch summary와 RunPod generation 보존
- `backend/app/services/batch_job_service.py`
  - 배치 작업에서도 동일한 `resolutionTier`, duration, image name 계약 적용
- `backend/app/services/task_tracking_service.py`
  - RunPod status/manifest에서 `generation[]` 추출 및 API 응답 보존
- `backend/app/models.py`
  - 기존 JSON/status 컬럼으로 보존 불가능한 경우에만 최소 migration 검토
- `frontend/src/screens/runpodRequestScreen.tsx`
  - 일반 요청 관리 화면의 `resolutionTier` 선택 및 payload 반영
- `frontend/src/screens/batchJobScreen.tsx`
  - 배치 요청 화면의 `resolutionTier` 선택 및 payload 반영
- `frontend/src/api/client.ts`
  - API 타입에 `resolutionTier`, `generation` 반영
- `workflows/wan22_default_81.json`
  - flat API JSON 검증 및 기본 5초 workflow로 등록
- `workflows/wan22_10s_chain.json`
  - 정확한 flat API JSON 원본이 있는 경우에만 추가/등록한다. 원본이 없으면 구현 단계에서 임의 생성하지 않고 차단한다.
- `backend/tests/test_wan_resolution_policy.py`
- `backend/tests/test_wan_workflow_patch_service.py`
- `backend/tests/test_runpod_request_payload.py`
- `backend/tests/test_runpod_generation_persistence.py`
- frontend 테스트 파일은 기존 테스트 구조에 맞춰 추가한다.

## 구현 작업

### 1. WAN 해상도 정책을 테스트로 고정

- [ ] `backend/tests/test_wan_resolution_policy.py`를 추가한다.
- [ ] 아래 함수를 요구사항 그대로 테스트한다.

```python
WAN_PIXEL_BUDGET = {"sd": 409_600, "hd": 921_600}
WAN_MULT = 16

def fit_wan_size(img_w: int, img_h: int, tier: str = "sd") -> tuple[int, int]:
    budget = WAN_PIXEL_BUDGET[tier]
    s = min(1.0, (budget / (img_w * img_h)) ** 0.5)
    w = max(WAN_MULT, int(img_w * s) // WAN_MULT * WAN_MULT)
    h = max(WAN_MULT, int(img_h * s) // WAN_MULT * WAN_MULT)
    while w * h > budget:
        if w >= h:
            w -= WAN_MULT
        else:
            h -= WAN_MULT
    return w, h
```

- [ ] 다음 케이스를 exact assertion으로 고정한다.
  - `1090x2040`, `sd` → `464x864`, `400896`
  - `1090x2040`, `hd` → `688x1312`, `902656`
  - `1920x1080`, `sd` → `848x480`, `407040`
  - `1920x1080`, `hd` → `1280x720`, `921600`
  - `1000x1000`, `sd` → `640x640`, `409600`
  - `1000x1000`, `hd` → `960x960`, `921600`
  - `800x4000`, `sd` → `272x1424`, `387328`
  - `800x4000`, `hd` → `416x2144`, `891904`
  - `3000x1000`, `sd` → `1104x368`, `406272`
  - `3000x1000`, `hd` → `1648x544`, `896512`
  - `500x600`, `sd` → `496x592`, `293632`
  - `500x600`, `hd` → `496x592`, `293632`
- [ ] invalid tier는 `ValueError` 또는 기존 API validation error로 실패하게 한다.
- [ ] zero/negative width/height는 validation error로 실패하게 한다.

### 2. `resolutionTier` API 계약 정의

- [ ] 모든 RunPod 요청 payload에 optional `resolutionTier`를 추가한다.
- [ ] 허용값은 `"sd" | "hd"`로 제한한다.
- [ ] 누락 시 기본값은 `"sd"`이다.
- [ ] API response/history에는 실제 적용된 `resolutionTier`, `wanWidth`, `wanHeight`, `wanPixelBudget`을 포함한다.
- [ ] 기존 duration 또는 workflow 선택값과 충돌하지 않도록 `resolutionTier`는 해상도만 담당하게 한다.

### 3. workflow patch를 node id가 아닌 `class_type` 기반으로 재구성

- [ ] `workflow_patch_service.py`에서 `WanImageToVideo` node 전체를 수집한다.
- [ ] 모든 `WanImageToVideo.inputs.width`와 `height`에 `fit_wan_size()` 결과를 넣는다.
- [ ] 모든 `WanImageToVideo.inputs.batch_size`는 `1`로 고정한다.
- [ ] 단일 5초 workflow는 `WanImageToVideo.length=81`로 설정한다.
- [ ] 10초 chain workflow는 `WanImageToVideo` 2개를 요구하고 각각 `length=81`로 설정한다.
- [ ] workflow 내 `WanImageToVideo.length` 합계가 `162`를 넘으면 요청 생성 단계에서 실패시킨다.
- [ ] 단일 `length=161`이 발견되면 요청 생성 단계에서 실패시킨다.
- [ ] patch 결과에는 각 `WanImageToVideo` node의 `nodeId`, `width`, `height`, `length`, `batch_size`, `pixelCount`, `tier`를 포함한다.
- [ ] 제출 직전 기존 `runpodPayloadNode98` 성격의 로그를 확장해 전체 `WanImageToVideo` node 값을 남긴다.

### 4. 이미지 입력 계약을 S3 기반으로 고정

- [ ] ECS payload는 `images[]`에 최소한 `{ "name": "...", "s3Uri": "s3://..." }`를 포함한다.
- [ ] `LoadImage.inputs.image`는 해당 image의 `name`과 정확히 같게 설정한다.
- [ ] `images[].name`이 없으면 S3 URI basename을 사용한다.
- [ ] 동일 workflow에 `LoadImage`가 여러 개 있으면 현재 요청의 주 입력 이미지와 매핑되는 node만 패치한다. 매핑 불가능하면 명시적으로 실패시킨다.
- [ ] base64 inline image는 호환 경로로만 유지하고, 신규 요청 기본 경로는 S3 URI로 한다.

### 5. prompt patch를 class/type 기준으로 고정

- [ ] `CLIPTextEncode` node 중 positive prompt 대상 node를 구조적으로 식별한다.
- [ ] positive node 판단 기준은 기존 workflow metadata 또는 연결 그래프 기준으로 둔다.
- [ ] 식별 실패 시 첫 `CLIPTextEncode`에 임의 주입하지 않고 실패시킨다.
- [ ] `CLIPTextEncode(positive).inputs.text`에 요청 prompt를 넣는다.
- [ ] negative prompt는 요청값이 있는 경우에만 대응 node에 넣고, 없으면 template 기본값을 보존한다.

### 6. 5초/10초 workflow 선택 정책 구현

- [ ] 요청 duration이 5초이면 `wan22_default_81.json`을 선택한다.
- [ ] 요청 duration이 10초이면 `wan22_10s_chain.json`을 선택한다.
- [ ] `wan22_10s_chain.json`이 저장소에 없거나 flat API JSON이 아니면 요청 생성 단계에서 명확한 에러를 반환한다.
- [ ] 10초 workflow는 `WanImageToVideo` node가 2개가 아니면 실패시킨다.
- [ ] 10초 workflow에서 두 번째 node가 첫 번째 결과를 이어받는 구조인지 검증한다. 단순히 node 수만 맞으면 통과시키지 않는다.

### 7. RunPod `generation[]` 보존

- [ ] RunPod status/manifest response에서 `generation[]` 경로를 추출한다.
- [ ] 가능한 경로:
  - `response["generation"]`
  - `response["output"]["generation"]`
  - manifest JSON 내부 `generation`
- [ ] success와 error 모두에서 `generation[]`이 있으면 삭제하지 않는다.
- [ ] ECS 로그에 `generation[]` 전체 또는 민감정보를 제외한 요약을 남긴다.
- [ ] request history API에 `generation[]`을 포함한다.
- [ ] UI history에서 `generation[].width`, `height`, `length`, `nodeId`, `pixelCount`를 확인할 수 있게 한다.

### 8. frontend 요청 화면 반영

- [ ] 일반 요청 관리 화면에 해상도 tier 선택을 추가한다.
  - 기본값: `sd`
  - 선택지: `sd`, `hd`
- [ ] 배치 작업 화면에도 동일한 선택을 추가한다.
- [ ] 요청 payload에 `resolutionTier`를 포함한다.
- [ ] 5초/10초 선택 UI가 있다면 `length` 직접 입력이 아니라 duration 선택만 노출한다.
- [ ] UI에서 `161` 같은 raw frame length를 직접 전달하지 않게 한다.
- [ ] history/detail 영역에서 실제 제출된 `width`, `height`, `length`, `tier`를 표시한다.

### 9. acceptance test 구성

- [ ] SD 입력 크기 acceptance:
  - `1090x2040`
  - `1920x1080`
  - `1000x1000`
  - `800x4000`
  - `3000x1000`
  - `500x600`
- [ ] 각 SD 케이스에서 `generation[0].width * generation[0].height <= 409600` 검증.
- [ ] HD acceptance:
  - `1920x1080`: `1280x720`, `<=921600`
  - `1090x2040`: `688x1312`, `<=921600`
- [ ] 10초 chain SD:
  - `generation` 길이 2
  - 각 item `length=81`
  - 총 length 162
- [ ] 의도적으로 raw `1090x2040`을 `WanImageToVideo`에 넣는 workflow는 제출 전에 실패하거나 worker에서 1초 내 `workflow rejected`로 실패해야 한다.
- [ ] ECS DB/API response에 `generation[]`이 남는지 검증한다.

### 10. 배포 전 검증 명령

- [ ] backend unit test 실행

```bash
pytest backend/tests/test_wan_resolution_policy.py backend/tests/test_wan_workflow_patch_service.py backend/tests/test_runpod_request_payload.py backend/tests/test_runpod_generation_persistence.py
```

- [ ] 전체 backend test 실행

```bash
pytest backend/tests
```

- [ ] frontend test/typecheck 실행

```bash
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
```

- [ ] Docker image build

```bash
docker build -t dobedub-studio:wan22-resolution-frame .
```

- [ ] ECS task definition env 확인
  - RunPod endpoint가 `ykf5itlew8az50`인지 확인
  - S3 bucket/prefix env가 기존 운영값과 일치하는지 확인
  - worker guard env와 ECS budget 값이 불일치하지 않는지 확인

### 11. 배포 후 운영 검증

- [ ] SD 5초 일반 요청 1건 실행.
- [ ] HD 5초 일반 요청 1건 실행.
- [ ] SD 10초 chain 요청 1건 실행.
- [ ] 각 요청에서 다음을 확인한다.
  - RunPod request payload의 `LoadImage.inputs.image == images[].name`
  - 모든 `WanImageToVideo.width * height <= tier budget`
  - 모든 width/height가 16의 배수
  - 모든 `length <= 81`
  - total length `<=162`
  - `batch_size=1`
  - S3 input/output/manifest key가 정상 생성됨
  - ECS history에서 `generation[]` 확인 가능

## 구현 순서

1. 테스트를 먼저 추가해 해상도 계산과 frame guard를 고정한다.
2. backend patch service를 수정해 계산/검증/로그를 집중시킨다.
3. 일반 요청 관리와 batch job service에 `resolutionTier` 전달을 연결한다.
4. S3 image name과 `LoadImage` 계약을 고정한다.
5. RunPod `generation[]` 저장/조회 경로를 고정한다.
6. frontend에서 tier 선택과 제출 payload를 연결한다.
7. 10초 chain template 원본이 확인된 경우에만 등록한다.
8. 테스트, Docker build, ECS 배포 순서로 진행한다.

## 명시적 비범위

- 이 계획은 기존 코드에 이미 반영된 사항을 인정하거나 재사용한다고 가정하지 않는다.
- `wan22_10s_chain.json`의 정확한 flat API JSON 원본이 없으면 임의 생성하지 않는다.
- RunPod worker guard 자체 구현은 ECS 범위가 아니며, worker env와 manifest 계약을 소비하는 쪽만 반영한다.
- 해상도 정책을 3개 preset(`832x480`, `480x832`, `640x640`)으로 단순화하지 않는다. 문서의 pixel-budget 기반 fit 알고리즘을 기준으로 한다.
