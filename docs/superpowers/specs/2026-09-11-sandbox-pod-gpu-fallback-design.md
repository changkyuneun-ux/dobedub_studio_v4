# Sandbox Pod 다중 보유·선택 실행 및 GPU fallback 설계

- 작성일: 2026-09-11 (v2 — 다중 파드 선택 반영, 2026-09-12 이름 규칙 추가)
- 대상 화면: 스튜디오 → ADMIN → **Sandbox Pod** (`admin.sandbox`)
- 대상 코드: `backend/app/services/sandbox_pod_service.py`, `backend/app/api/v1/sandbox_pod.py`, `backend/app/core/config.py`, `backend/app/db/models.py`(설정 1건), `frontend/src/screens/adminScreens.tsx`(Sandbox 패널), `frontend/src/api/client.ts`
- 관련 문서: `docs/aws-ecs-deployment.md` §1 환경변수, `runpod mcp/운영가이드-RunPod-ComfyUI-Wan.md`

## 1. 배경 — 2026-09-11 장애 2건

**09:20 KST** 관리자 페이지 Sandbox Pod 카드에서 **Start** 클릭 →
`Sandbox Pod API HTTP 500: {"error":"create pod: There are no instances currently available","status":500}`
표시, Pod 상태 카드 전 항목 공백, HTTP Services에는 이미 정지된 `s2lqjdfpdoyqa0` URL이 남음.

**17:05–17:13 KST** 복구된 파드 `caiuvooekq9qqw`(RTX 5090, RAM 60 GB)가 컨테이너 RAM OOM으로 RunPod에 의해 강제 정지. 재시작 시도 시 EU-RO-1 5090 재고 0으로 "Your Pod's GPUs are no longer available". 콘솔의 *Automatically migrate*도 동일 GPU를 요구하므로 실패. 운영자가 RTX PRO 6000 WK(96 GB VRAM, RAM 262 GB) 파드 `3i50u1x4pyz0vr`를 같은 볼륨에 신규 생성해 복구.

원인 (코드 추적):

1. `_resolve_pod()`가 볼륨 `18jhx6rxjd`에 붙은 파드 중 하나를 골라 **단일 파드** 전제로 동작. RUNNING이 2개면 오류, 전부 EXITED면 최근 것 하나.
2. `start_sandbox_pod()`는 EXITED/TERMINATED이면 `/pods/{id}/start`를 시도하지 않고 곧바로 `_deploy_sandbox_pod()` → `POST /pods`.
3. 생성 요청의 `gpuTypeIds`가 `["NVIDIA GeForce RTX 5090"]` 단일값. 볼륨이 EU-RO-1에 있어 파드도 EU-RO-1에만 생성 가능한데 5090 재고 0 → 500.
4. `_request()`가 `RuntimeError`로 변환 → API 502 → 프론트는 배너만 띄우고 이전 상태 값을 지움.

즉 **(a) 파드가 여러 개인 운영 형태를 지원하지 않고, (b) 정지된 파드 재기동 시도가 없으며, (c) 신규 생성은 GPU 한 종류에 고정**되어 재고 부족이 곧바로 사용자 오류가 된다.

## 2. 목적

### 2.1 운영 모델 (A안): 파드 여러 개 보유, 한 번에 하나만 실행

같은 네트워크 볼륨 `18jhx6rxjd`에 GPU가 다른 파드를 여러 개 붙여 두고, 관리자가 화면에서 **어느 파드를 켤지 선택**한다. 실행 중인 파드는 항상 **최대 1개**(서버가 강제). 정지된 파드는 GPU 요금 없이 컨테이너 디스크 보관료(150 GB ≈ $15/월)만 발생한다.

현재 보유 파드 (2026-09-11 기준):

| Pod ID | GPU | VRAM / RAM | 시간당 | 용도 |
|---|---|---|---|---|
| `caiuvooekq9qqw` | RTX 5090 | 32 GB / 60 GB | $0.99 | 기본. 재고 부족 시 기동 불가할 수 있음 |
| `3i50u1x4pyz0vr` | RTX PRO 6000 Blackwell WK | 96 GB / 262 GB | $2.19 | 대용량·OOM 회피용. Jupyter 비밀번호 있음 |

#### 파드 이름 규칙 (2026-09-12 확정)

파드 이름은 RunPod 콘솔에서 **`dobedub_comfyUI_Sandbox_<GPU 표시명>`** 으로 고정하고, dobedub-studio는 이 이름을 **그대로 표시**한다(로컬 별칭 매핑 없음).

| Pod ID | RunPod 이름 |
|---|---|
| `caiuvooekq9qqw` | `dobedub_comfyUI_Sandbox_RTX 5090` |
| `3i50u1x4pyz0vr` | `dobedub_comfyUI_Sandbox_RTX PRO 6000` |

- 이름은 **표시용**이며 식별에는 쓰지 않는다. 식별은 볼륨 ID(§5.2), 선택 저장은 Pod ID(`selected_pod_id`). 파드가 migration으로 ID가 바뀌면 화면의 선택값은 "찾을 수 없음"으로 표시되고 관리자가 다시 고른다 — 이름은 RunPod가 migration 시 유지하므로 운영자는 같은 이름을 다시 고르면 된다.
- 접두사 `dobedub_comfyUI_Sandbox`는 유지한다(legacy `RUNPOD_SANDBOX_POD_NAME` prefix 매칭 호환).
- 서버가 자동 생성하는 파드(§5.3 ③④)도 같은 규칙으로 이름을 붙인다: `RUNPOD_SANDBOX_DEPLOY_NAME + "_" + <GPU 표시명>`. GPU 표시명은 RunPod 카탈로그 `displayName`(예: `RTX 5090`, `RTX PRO 6000 WK`, `RTX 4090`)을 쓴다. 따라서 `RUNPOD_SANDBOX_DEPLOY_NAME`은 접두사 역할만 하며 기본값 `dobedub_comfyUI_Sandbox` 유지.
- 화면의 파드 목록·상태 카드·전환 확인 대화상자·오류 배너·audit log의 사람이 읽는 문구는 모두 이 이름을 우선 사용하고 Pod ID는 보조로 표기한다(예: `dobedub_comfyUI_Sandbox_RTX 5090 (caiuvooekq9qqw)`).
- 이름은 매 조회마다 RunPod API에서 읽는다. 콘솔에서 바꾸면 다음 새로고침에 반영되며 앱 재배포가 필요 없다.

동시 실행은 하지 않는다. 두 ComfyUI가 같은 `/workspace/runpod-slim/ComfyUI`의 `user/`, 내부 SQLite, `filebrowser.db`, `output/`에 동시에 쓰면 손상 위험이 있기 때문이다. (동시 실행이 필요해지면 파드별 `--user-directory`/`--output-directory` 분리와 시작 스크립트 수정이 선행돼야 하며, 이 문서 범위 밖이다.)

### 2.2 기동 절차: 선택 → 전환 → start → create → GPU fallback

관리자가 파드를 선택하고 **Start**를 누르면 서버가 아래를 자동으로 밟는다.

```
⓪ 다른 파드가 RUNNING이면 먼저 stop (전환), 정지 확인까지 대기
① 선택한 파드가 EXITED이면 start 시도
   └ 실패(재고 없음/파드 소멸) →
② 관리자가 "대체 파드 자동 기동" 옵션을 켠 경우: 볼륨에 붙은 다른 EXITED 파드를 우선순위대로 start
   └ 전부 실패 →
③ 같은 템플릿·같은 볼륨·기본 GPU(5090)로 create
   └ 실패(no instances) →
④ fallback GPU 목록(RTX PRO 4500 → RTX PRO 6000 WK → RTX 4090 …) 순으로 create
   └ 모두 실패 →
⑤ 단계별 실패 사유를 담은 명확한 오류 응답 (이전 상태 유지)
```

각 단계의 시도·결과는 audit log와 응답 본문에 남겨, 운영자가 "왜 이 파드/GPU로 떴는지"를 화면에서 바로 알 수 있어야 한다.

## 3. 범위 밖

- Serverless 엔드포인트(`RUNPOD_ENDPOINT_ID`)의 GPU 풀 변경
- 파드 자동 정지(idle timeout) 및 비용 상한 — 후속 과제
- 파드 동시 실행(§2.1 참조)
- 다른 데이터센터로의 볼륨 이전 — 네트워크 볼륨은 DC에 고정되어 있어 fallback 후보에서 DC는 바꿀 수 없다
- Pod 재고 사전 예약(RunPod에 없음)

## 4. 채택한 접근

**볼륨 기준으로 파드 목록을 노출하고 관리자가 대상을 고르게 하되, "실행 중 1개" 불변식은 서버가 강제한다. 기동은 REST v1 `POST /pods`에 GPU 하나씩 넣는 서버 측 단계형 재시도(start → 다른 파드 start → create 기본 → create fallback)로 처리한다.**

검토한 대안:

| 안 | 내용 | 판단 |
|---|---|---|
| A. `gpuTypeIds`에 후보 전체 + `gpuTypePriority:"availability"` | 요청 1회, 코드 최소 | 단독으로는 부족 — 우선순위가 보장되지 않고 어떤 GPU로 떴는지 응답을 봐야 앎 |
| B. 서버 측 루프: 후보를 하나씩 순차 create | 우선순위 보장, 단계별 사유 기록 | 채택. 최대 N회(기본 4) 요청, 각 실패는 즉시 500이라 지연은 수 초 |
| C. 프론트 재시도 UI | 백엔드 변경 최소 | 기각 — 자동화 목적에 어긋남 |
| D. REST v2 이관 | v2는 `gpu.id` 단일값 | 지금 이관하지 않음. GPU 후보 선택을 별도 함수로 분리해 v2 이관 시 재사용 |
| E. 파드 선택을 환경변수 `RUNPOD_SANDBOX_POD_ID`로 고정 | 코드 변경 없음 | 기각 — 전환마다 재배포 필요. 선택값은 DB 설정으로 |

## 5. 요구사항

### 5.1 설정

환경변수 (신규):

| 변수 | 기본값 | 설명 |
|---|---|---|
| `RUNPOD_SANDBOX_GPU_TYPE_ID` | (기존) `NVIDIA GeForce RTX 5090` | create 시 1순위 GPU |
| `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS` | `NVIDIA RTX PRO 4500 Blackwell,NVIDIA RTX PRO 6000 Blackwell Workstation Edition,NVIDIA GeForce RTX 4090` | 쉼표 구분, 순서 = 우선순위. 빈 값이면 fallback 없음 |
| `RUNPOD_SANDBOX_START_RETRY_COUNT` | `1` | 선택 파드 `start` 재시도 횟수 |
| `RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS` | `2` | create 단계 간 대기 |
| `RUNPOD_SANDBOX_MIN_VRAM_GB` | `24` | fallback 후보 중 이 값 미만 GPU 제외 |
| `RUNPOD_SANDBOX_STOP_WAIT_SECONDS` | `60` | 전환 시 이전 파드 EXITED 확인 최대 대기 |

DB 설정 (신규, `task_execution_policies`와 같은 단일 행 설정 패턴):

| 키 | 타입 | 설명 |
|---|---|---|
| `sandbox_pod.selected_pod_id` | str | 관리자가 마지막으로 선택한 파드. 없으면 RUNNING 파드 → 최근 EXITED 파드 순 |
| `sandbox_pod.auto_switch_on_start_failure` | bool (기본 true) | 선택 파드 start 실패 시 §2.2 ② 단계(다른 파드 start) 수행 여부 |
| `sandbox_pod.pod_priority` | list[str] | ② 단계 순서. 비어 있으면 `가격 오름차순` |

`Settings`에 `sandbox_pod_gpu_fallback_type_ids: list[str]`, `sandbox_pod_start_retry_count`, `sandbox_pod_create_attempt_delay_seconds`, `sandbox_pod_min_vram_gb`, `sandbox_pod_stop_wait_seconds` 추가. `docs/aws-ecs-deployment.md` §1 표와 `.env.example`에 반영. `RUNPOD_SANDBOX_POD_ID`(legacy 단일 선택)는 유지하되 DB 선택값이 있으면 무시.

### 5.2 파드 목록 해석 (`_resolve_pods`, 기존 `_resolve_pod` 대체)

**식별자 역할 분리 원칙** — 환경변수는 모두 유지하되 쓰임을 나눈다:

| 변수 | 파드 찾기 | 파드 생성 |
|---|---|---|
| `RUNPOD_SANDBOX_NETWORK_VOLUME_ID` | **유일 식별자** (파드 ID·이름이 migration으로 바뀌어도 불변) | 필수 |
| `RUNPOD_SANDBOX_TEMPLATE_ID` | 사용하지 않음 (볼륨 selector가 없을 때만 legacy 필터) | **필수** — 새 파드 사양 |
| `RUNPOD_SANDBOX_GPU_TYPE_ID` 등 | 사용하지 않음 | 필수 |

템플릿 ID는 파드를 특정하지 못한다: 같은 템플릿으로 다른 볼륨에 만든 파드도 통과하고, 콘솔·REST v2·Pod migration 경로로 만든 파드는 `template`이 null이라 탈락한다(2026-09-11 `3i50u1x4pyz0vr` 사례). "파드 ID가 바뀌는 문제"는 볼륨 ID가 해결하며, 템플릿 ID는 `_deploy_sandbox_pod`에서 동일 사양의 파드를 다시 만드는 데 쓰인다.

> **적용 완료 (2026-09-11, 0단계)**: `sandbox_pod_service._resolve_pod`의 템플릿 필터를 `if template_id and not volume_id:`로 변경, `resolved_by` 표기 동일 조정. 테스트 `SandboxPodResolutionTests` 3건 추가(볼륨 일치 + template null 파드 선택 / 템플릿만 설정 시 기존 동작 유지 / 전부 EXITED면 최근 파드). 이 패치만으로 현재 관리자 페이지가 `3i50u1x4pyz0vr`를 인식한다.

- `GET /pods?includeNetworkVolume=true`에서 `RUNPOD_SANDBOX_NETWORK_VOLUME_ID`(필수) 일치 파드를 **전부** 반환.
- TERMINATED는 제외. 각 파드에 `gpuTypeId`, `vramGb`, `ramGb`, `pricePerHr`, `desiredStatus`, `lastStartedAt`, `httpServices`를 붙인다(`_present_pod` 재사용).
- **불변식 검사**: RUNNING/STARTING 파드가 2개 이상이면 응답에 `conflict: true`와 해당 ID를 넣고, 화면은 경고 배너와 "나머지 정지" 버튼을 보여준다. start/create는 conflict 상태에서 거부(409).
- 기존 `sandbox_pod_status()`는 `pods[]` + `selectedPodId` + `activePodId`(RUNNING인 것)를 반환하도록 확장. 기존 단일 필드(`podId`, `desiredStatus`, `httpServices` …)는 `activePodId` 기준으로 그대로 채워 하위 호환을 유지한다.

### 5.3 기동 절차 (`start_sandbox_pod(pod_id: str | None)`)

```
pods = _resolve_pods()
target = pods[pod_id] if pod_id else pods[selected_pod_id] or 최근 EXITED
if conflict: 409

⓪ 전환
   running = [p for p in pods if p.status in ACTIVE and p.id != target.id]
   for p in running: POST /pods/{p.id}/stop
   poll GET /pods/{p.id} until EXITED (최대 STOP_WAIT_SECONDS) — 타임아웃이면 중단, 409 "이전 파드 정지 대기 중"

① 선택 파드 start
   if target.status == RUNNING: 그대로 반환(멱등)
   POST /pods/{target.id}/start, 최대 START_RETRY_COUNT+1 회
   성공 → 3초 후 GET /pods/{id} 재조회. desiredStatus RUNNING & runtime != null 이면 완료
   실패(5xx / "no instances" / "not available" / 404) 또는 재조회 후 여전히 EXITED → ②

② 대체 파드 start  (auto_switch_on_start_failure == true 일 때만)
   candidates = pod_priority 순서(없으면 pricePerHr 오름차순)의 다른 EXITED 파드
   각 후보에 ① 과 동일 절차. 성공 시 selected_pod_id를 그 파드로 갱신하고 attempts에 "switched" 기록
   전부 실패 → ③

③ create 기본 GPU / ④ create fallback GPU
   후보 = [GPU_TYPE_ID] + FALLBACK_TYPE_IDS, VRAM < MIN_VRAM_GB 는 skipped:"vram"
   각 후보: POST /pods {name: <이름 규칙>, templateId, networkVolumeId, gpuTypeIds:[후보], gpuCount}
     ※ REST v1 PodCreateInput은 알 수 없는 키를 400 "Extra input keys provided in request body"로 거부한다.
       startJupyter/startSsh는 REST v2·GraphQL 전용이므로 v1 본문에 넣지 않는다 (2026-09-12 장애).
     성공 → selected_pod_id = 새 파드, resolvedBy="create:<후보>"
     5xx / "no instances" → 다음 후보 (delay 후)
     400·401·403·422 → 즉시 중단 (설정/권한 오류)
   전부 실패 → SandboxPodUnavailable(attempts) → API 503

stop_sandbox_pod(pod_id: str | None): 지정 파드(없으면 activePodId) stop. 다른 파드에 영향 없음.
```

- create로 생긴 파드는 `templateId`가 남지 않으므로(§5.2) 볼륨 ID로만 찾는다. 이름은 `RUNPOD_SANDBOX_DEPLOY_NAME + "_" + <GPU displayName>` (§2.1 이름 규칙).
- Jupyter·SSH 노출은 템플릿의 `ports`/`env`에서 온다. 자동 생성 파드에도 Jupyter 인증을 두려면 템플릿 `nh1d177m2w`의 env에 `JUPYTER_PASSWORD`를 설정한다(REST v1 create 본문의 `startJupyter`로는 불가). 파드 env에 `JUPYTER_PASSWORD`가 있으면 응답의 `httpServices[8888]`에 `authRequired: true`를 넣어 화면에 표시한다(토큰 값은 노출하지 않음).

### 5.4 API

| 메서드·경로 | 권한 | 변경 |
|---|---|---|
| `GET /api/admin/sandbox-pod` | `sandbox:read` | 응답에 `pods[]`, `selectedPodId`, `activePodId`, `conflict` 추가 |
| `POST /api/admin/sandbox-pod/select` `{podId}` | `sandbox:control` | 신규. `selected_pod_id` 저장만, 기동 안 함 |
| `POST /api/admin/sandbox-pod/start` `{podId?}` | `sandbox:control` | `podId` 생략 시 선택값. §5.3 수행. 전부 실패 시 503 |
| `POST /api/admin/sandbox-pod/stop` `{podId?}` | `sandbox:control` | `podId` 생략 시 `activePodId` |
| `PUT /api/admin/sandbox-pod/settings` `{autoSwitchOnStartFailure, podPriority}` | `sandbox:control` | 신규 |

응답 스키마 확장:

```jsonc
{
  "...기존 필드(activePodId 기준)...": "...",
  "selectedPodId": "caiuvooekq9qqw",
  "activePodId": "3i50u1x4pyz0vr",
  "conflict": false,
  "pods": [
    {"podId": "caiuvooekq9qqw", "name": "dobedub_comfyUI_Sandbox_RTX 5090", "gpuTypeId": "NVIDIA GeForce RTX 5090", "vramGb": 32, "ramGb": 60, "pricePerHr": 0.99, "desiredStatus": "EXITED", "lastStartedAt": "…", "httpServices": []},
    {"podId": "3i50u1x4pyz0vr", "name": "dobedub_comfyUI_Sandbox_RTX PRO 6000", "gpuTypeId": "NVIDIA RTX PRO 6000 Blackwell Workstation Edition", "vramGb": 96, "ramGb": 262, "pricePerHr": 2.19, "desiredStatus": "RUNNING", "runtimeStatus": "READY", "httpServices": [{"internalPort": 8188, "url": "…"}, {"internalPort": 8888, "url": "…", "authRequired": true}]}
  ],
  "settings": {"autoSwitchOnStartFailure": true, "podPriority": ["caiuvooekq9qqw", "3i50u1x4pyz0vr"]},
  "attempts": [
    {"stage": "stop",   "podId": "3i50u1x4pyz0vr", "ok": true,  "at": "…"},
    {"stage": "start",  "podId": "caiuvooekq9qqw", "ok": false, "error": "HTTP 500: no instances currently available", "at": "…"},
    {"stage": "switch", "podId": "3i50u1x4pyz0vr", "ok": true,  "at": "…"}
  ],
  "message": "선택한 RTX 5090 파드는 재고 부족으로 기동하지 못해 RTX PRO 6000 WK 파드를 대신 시작했습니다."
}
```

전부 실패한 경우 **503** + `{"detail": {"message": "EU-RO-1에 기동 가능한 파드·GPU가 없습니다.", "attempts": [...], "retryAfterSeconds": 300}}`.

### 5.5 프론트엔드 (Sandbox 패널)

- **파드 목록 테이블**: GPU · VRAM/RAM · 시간당 · 상태(RUNNING/EXITED 배지) · 마지막 실행 · 라디오 선택. 선택 변경 즉시 `POST /select`.
- **Start** 버튼은 선택 파드 기준. 다른 파드가 RUNNING이면 버튼 라벨을 "전환 후 시작"으로 바꾸고, 클릭 시 "현재 실행 중인 <GPU> 파드를 정지하고 <GPU> 파드를 시작합니다. 진행 중인 ComfyUI 작업은 중단됩니다." 확인 대화상자를 띄운다.
- **Stop** 버튼은 RUNNING 파드 행에만 표시.
- 상태 카드·HTTP Services는 `activePodId` 기준. Jupyter 항목에 `authRequired`면 "비밀번호 필요(RunPod 콘솔 env `JUPYTER_PASSWORD`)" 문구.
- 실패 시 **이전 상태 카드를 지우지 않는다.** 오류 배너에 `attempts`를 단계별로 렌더링: `stop 3i50… ✓ → start caiuv… ✗ 재고 없음 → switch 3i50… ✓`.
- `conflict: true`면 빨간 배너 "실행 중인 Sandbox Pod가 2개입니다. 볼륨 손상 위험" + "선택 파드만 남기고 정지" 버튼.
- 설정 영역: "선택 파드 기동 실패 시 다른 파드 자동 시작" 토글, 우선순위 드래그 정렬.
- 503의 `retryAfterSeconds` 동안 Start 비활성화 + 카운트다운.

### 5.6 Audit log

- `sandbox_pod.select` (before/after podId), `sandbox_pod.start` (`after`에 `attempts`, `activePodId`, `gpuTypeId`, `switched`, `createdBy`), `sandbox_pod.start_failed`, `sandbox_pod.stop` (podId), `sandbox_pod.settings_update`.

### 5.7 관측

- 단계마다 구조화 로그 `sandbox_pod.attempt {stage, podId, gpu, ok, error}`.
- EMF: `SandboxPodStartAttemptCount{stage,gpuTypeId,ok}`, `SandboxPodSwitchCount`, `SandboxPodFallbackCount`, `SandboxPodConflictCount`.

## 6. Fallback 후보 검증 (구현 전 확인, EU-RO-1 Secure Cloud)

2026-09-11 17:20 KST 조회 결과와 판단:

| GPU | VRAM | 재고 | 시간당 | CUDA 13.0 호스트 | 판단 |
|---|---|---|---|---|---|
| RTX 5090 | 32 GB | 없음 | $0.99 | — | 기본. 재고 변동 큼 |
| RTX PRO 4500 Blackwell | 32 GB | LOW | $0.72 | 있음 | fallback 1순위 — Blackwell이라 SageAttention 빌드 호환, 5090과 같은 VRAM, 더 저렴 |
| RTX PRO 6000 Blackwell WK | 96 GB | LOW | $2.19 | 있음 | fallback 2순위 — 2026-09-11 실사용 검증 완료(§9). 비용 높음 |
| RTX PRO 6000 Blackwell Server | 96 GB | LOW | $2.09 | 13.2만 | 호스트 CUDA 13.2 — 템플릿 `allowedCudaVersions`에 13.2 포함 여부 확인 후 추가 |
| RTX 4090 | 24 GB | LOW | $0.74 | 있음 | 3순위. Ada(sm_89)라 `--use-sage-attention`이 5090용 빌드와 불일치 → ComfyUI 기동 실패 가능. 24 GB VRAM. 아래 두 항목 해결 전에는 목록 끝에 두거나 제외 |
| L40S / H100 / A100 | — | 없음 | — | — | EU-RO-1 재고 없음 |

추가 확인 항목:

| 항목 | 내용 | 미충족 시 |
|---|---|---|
| SageAttention | `comfyui_args.txt`의 `--use-sage-attention`이 `/workspace/SageAttention`(5090 sm_120 빌드) 참조. Ada GPU에서 import 실패 시 기동 직후 종료 | 시작 스크립트에서 GPU compute capability를 보고 인자 제거, 또는 sm_89+sm_120 동시 빌드 |
| RAM OOM | 60 GB RAM 호스트에서 Wan 2.2 14B ×2 + Krea2 + Qwen3-VL 캐시 시 OOM 재현됨(2026-09-11) | 5090 파드용 `comfyui_args.txt`에 `--cache-none` 추가, 또는 create 시 `minRamPerGpu` 필터(REST v2) |
| 비용 | fallback이 더 비쌀 수 있음(PRO 6000) | 화면에 시간당 요금 상시 표시, 우선순위는 가격순 기본 |

## 7. 테스트

`backend/tests/test_sandbox_pod_service.py` (urlopen mock):

1. 볼륨에 EXITED 2개 → `pods[]` 2건, `activePodId` null, `selectedPodId`는 DB 값.
2. 선택 A(EXITED), B RUNNING → start(A): stop(B) → EXITED 대기 → start(A) 성공. attempts `[stop B, start A]`.
3. stop(B) 대기 타임아웃 → 409, start 호출 없음.
4. start(A) 500 "no instances" + autoSwitch on → start(B) 성공, `selected_pod_id`=B, attempts에 `switch`.
5. start(A) 실패 + autoSwitch off → create(5090) → create(PRO 4500) 성공, `gpuTier="fallback"`.
6. create(5090) 400 → 즉시 중단, 다음 후보 없음, ValueError.
7. 전 단계 실패 → 503, attempts 전체, audit `start_failed`.
8. RUNNING 2개 → `conflict: true`, start 409.
9. `FALLBACK_TYPE_IDS` 미설정 → create는 5090 1회만.
10. VRAM 필터: 16 GB 후보 skipped.

프론트 Vitest: 목록 렌더링·라디오 선택 → `/select` 호출, "전환 후 시작" 확인 대화상자, 실패 시 이전 상태 유지, conflict 배너.

## 8. 롤아웃

0. **(적용됨, 배포 대기)** `_resolve_pod` 템플릿 필터 완화 + 테스트 3건. 환경변수 변경 없음. 이 배포만으로 관리자 페이지가 현재 PRO 6000 파드를 인식하고 Start/Stop이 정상 동작한다.
1. 백엔드: `_resolve_pods` + `pods[]` 응답 확장만 배포(기존 필드 호환) → 화면에 목록이 보이는지 확인.
2. `/select`, `/settings`, 전환 로직 배포. `FALLBACK_TYPE_IDS`는 빈 값.
3. §6 검증 후 `RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS` 설정, `autoSwitchOnStartFailure` 기본 on.
4. 운영가이드에 "파드 선택·전환, 실패 시 자동 대체, fallback 배지, 5090 복귀" 절 추가. Jupyter 비밀번호 파드 안내 포함.

## 9. 운영 메모 (2026-09-11 시점)

- 실행 중: `3i50u1x4pyz0vr` (RTX PRO 6000 WK, $2.19/h) — ComfyUI v0.30.0, SageAttention 정상 로드, 커스텀 노드 전부 import 성공 확인. Jupyter 토큰 인증 있음.
- 정지: `caiuvooekq9qqw` (RTX 5090, $0.99/h, RAM 60 GB) — 5090 재고 회복 시 복귀 대상. 복귀 전 `--cache-none` 추가 권장.
- 제거됨: `s2lqjdfpdoyqa0`, `r1ks9kbquwsda4`.
- 파드 이름은 2026-09-12에 `dobedub_comfyUI_Sandbox_RTX 5090` / `dobedub_comfyUI_Sandbox_RTX PRO 6000`으로 고정(§2.1). 식별은 여전히 볼륨 ID + Pod ID. 현행 `_resolve_pod`는 RUNNING이 1개인 동안은 정상 동작하므로, 이 설계가 배포되기 전까지는 **반드시 한 파드만 켜 둔다**.
- 전환(현행 수동 절차): RunPod 콘솔 또는 MCP에서 실행 중 파드 `stop` → EXITED 확인 → 대상 파드 `start`. 5090 start 실패 시 재고 확인 후 재시도.
