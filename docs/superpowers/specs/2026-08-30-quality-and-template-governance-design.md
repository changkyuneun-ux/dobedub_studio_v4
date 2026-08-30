# 결과 품질(B) · 워크플로우 템플릿 품질(C) 개선 설계

- 작성일: 2026-08-30
- 범위: B(결과 품질)와 C(템플릿 품질). 둘은 뿌리를 공유하므로 한 스펙으로 묶는다. A(성능)는 [2026-08-30-runpod-performance-design.md](2026-08-30-runpod-performance-design.md) 참조.
- 근거 데이터: 운영 RDS `workflow_tasks` 109건, `task_prompts` 111건, 운영 EFS `WORKFLOWS_DIR` 13개 워크플로우, 2026-08-06 ~ 2026-08-21

## 1. 공통 뿌리

paramconfig가 세 가지를 동시에 잘못하고 있다.

1. **위험한 노브를 연다** — 4-step distilled LoRA 분기에서 `cfg`를 12.0까지, `steps`를 50까지 노출한다.
2. **유용한 노브를 숨긴다** — `split_step`은 어느 템플릿에도 노출되지 않는다.
3. **선언한 범위를 지키지 않는다** — `min`/`max`가 서버에서 강제되지 않는다.

B의 증상과 C의 재생산이 모두 여기서 나온다. 따라서 개별 증상을 고치지 않고 이 구조를 고친다.

## 2. 측정 결과

### 2.1 사용자는 기본값을 거의 벗어나지 않는다 (n=109)

| 파라미터 | 최빈값 | 이탈 사례 | 선언 범위 |
|---|---|---|---|
| `steps` | 4 (97%) | 15, 6, 5 | 4→24 / 4→50 |
| `cfgScale` | 1 (97%) | **1.8 (2건), 3.9 (1건)** | 1.0→6.0 / 1→12.0 |
| `motionShift` | ≈5 (96%) | **1 (5건)** | min 2.0 |
| `frames` | 81 (62%) | **161 (28건, 26%)** | duration 최대 10초 |
| `fps` | 16 (95%) | 15 (5건) | 8→30 |

읽어야 할 것은 두 가지다.

**기본값을 벗어나지 않는데도 품질 불만이 있다** → 범위 문제가 아니라 기본값과 상한 자체의 문제다.

**이탈한 소수는 정확히 해로운 값에 착지했다** → 범위가 사용자를 잘못된 곳으로 안내하고 있다.

### 2.2 증상과 원인의 대응

사용자가 지목한 증상은 `naturalMotion`, `noDistortion`, `backgroundStable` 세 가지다. `intentMatched`는 지목되지 않았다 — **프롬프트 주입 경로와 LLM 생성 품질은 이 스펙의 범위가 아니다.**

| 증상 | 원인 | 영향 범위 |
|---|---|---|
| naturalMotion, backgroundStable | `frames=161`이 워크플로우 자체 기본값 81을 2배 초과. `duration_seconds` 상한 10초가 `floor(10×16+1)=161`을 만든다 | **26%** |
| noDistortion | `cfg` 1.8/3.9. 4-step distilled LoRA는 cfg=1.0이 전제 | 3건 |
| naturalMotion | `motionShift=1`. 선언 최소값 2.0 미만인데 통과 | 5건 |
| naturalMotion | `split_step`이 2로 고정. `steps` 변경 시 high/low noise 배분이 깨짐 | 3건 (미발현에 가까움) |

> 정정 기록: 초기에 `split_step` 고정을 B의 핵심으로 지목했으나, 운영에서 `steps`를 변경한 작업이 3건뿐이라 실제 영향은 가장 작다. 우선순위를 영향 범위 순으로 재배치했다.

### 2.3 범위가 서버에서 강제되지 않는다

[workflow_patch_service.py:201-211](../../../backend/app/services/workflow_patch_service.py#L201-L211)의 `apply_node_config_to_workflow()`는 `param_spec`에서 `default`만 읽고 `min`/`max`/`step`/`options`를 검사하지 않는다. 브라우저가 유일한 게이트다.

`motionShift=1`(선언 최소 2.0 미만)이 5건 통과한 것이 실증이다. **paramconfig를 고쳐도 이 구멍이 남으면 무의미하다.**

### 2.4 품질 평가 채널은 있으나 비어 있다

```
task_prompts (영상 결과 평가)   : 111건 중 평가 2건 (1.8%), 둘 다 5점
prompt_feedback (프롬프트 품질) : 0건
```

평가 축(`noDistortion`, `intentMatched`, `naturalMotion`, `backgroundStable`), 저장소, API, 화면이 모두 존재한다. 쓰이지 않을 뿐이다. 실행 1위 `1-images.json` 33건 중 평가는 0건이다.

**A와 같은 패턴이다.** A는 계측이 없어 원인을 몰랐고 B는 평가가 없어 무엇이 나쁜지 모른다. 수집률을 올리지 않으면 이 스펙의 개선 효과도 검증할 수 없다.

### 2.5 검증되지 않은 워크플로우가 기본 활성

```
workflow-registry.json 등록 : 6개
운영 WORKFLOWS_DIR 워크플로우 : 13개
→ 7개는 등록·검증 이력 없음
```

[admin_service.py:219-221](../../../backend/app/services/admin_service.py#L219-L221):

```python
def is_workflow_active(workflow_id: str) -> bool:
    item = workflow_registry_item(workflow_id)
    return bool(item.get("active", True))   # 미등록이면 True
```

`register_admin_workflow()`를 거치지 않은 워크플로우는 `validate_workflow_registration_payload()`도 통과한 적이 없는데 자동으로 활성화된다. **실행 1위 `1-images.json`(33건)이 이 경우다.** 검증 파이프라인은 admin 업로드 경로에만 존재하고 seed 경로는 그냥 통과한다.

### 2.6 생성기가 함정을 복제한다

| paramconfig | steps | cfg | split_step |
|---|---|---|---|
| 1~6-images | 4 → 24 | 1.0 → 6.0 | 미노출 |
| Blowbang1 / Pickme_Workflow | 4 → 50 | 1 → 12.0 | 미노출 |
| **Wan22_default / Pickme_v3 / Pickme_v5** | 4 → 50 | 1 → 12.0 | 미노출 |
| video_wan2_2_flf2v | 20 → 50 | 4 → 12.0 | 미노출 |

굵게 표시한 셋은 리포지토리에 없는, admin으로 새로 등록된 템플릿이다. `generate_param_config()`가 `ComfySwitchNode` 분기를 이해하지 못해 **등록할 때마다 같은 함정을 재생산한다.**

## 3. 설계

### 3.1 설계 원칙: 생성기를 fail-closed로 뒤집는다

현재 `generate_param_config()`는 안전한 범위를 증명할 수 없는 파라미터에도 범위를 **지어낸다**(4→50). 이것이 C의 핵심 결함이다.

원칙을 뒤집는다: **증명할 수 없으면 잠근다.** 생성기는 스위치 분기를 거치거나 distilled LoRA 경로에 연결된 파라미터를 `locked: true`로 표시하고 `default`만 남긴다. 사람이 검토해 범위를 명시하고 잠금을 풀기 전까지 사용자에게 편집 불가로 보인다.

이 원칙 하나가 B의 cfg/shift 문제와 C의 재생산 문제를 동시에 닫는다.

### 3.2 B — 결과 품질

**B-1. 서버측 범위 강제 (키스톤)**
`apply_node_config_to_workflow()`에서 값을 노드에 주입하기 전에 `param_spec`의 `min`/`max`/`options`를 검사한다. 위반 시 `ValueError`를 던진다 — [jobs.py:29](../../../backend/app/api/v1/jobs.py#L29)가 이미 HTTP 400으로 변환한다.

- **클램프가 아니라 거부**한다. 조용한 보정은 사용자 의도를 숨긴다.
- `locked: true`인 파라미터는 `default` 외의 값을 거부한다.
- `step`(16의 배수 등)은 기존 `validate_segment_resolution()`이 담당하므로 중복 구현하지 않는다.

이 변경 하나로 B-2·B-3이 코드 수정 없이 데이터 수정만으로 실효화된다.

**B-2. paramconfig 값 교정 (데이터)**
distilled LoRA 분기를 쓰는 템플릿에서 `cfg_scale`을 `min=max=default=1.0`으로, `steps`를 LoRA의 스텝 수로 고정한다. `motion_shift`는 이미 `min=2.0`이므로 값 변경 없이 B-1만으로 강제된다.

대상은 운영 EFS의 13개 paramconfig다. 리포지토리 사본과 운영 EFS 사본을 **모두** 고쳐야 한다 — 앱 시작 시 기본본은 존재하지 않는 파일만 복사하므로 리포지토리만 고치면 운영에 반영되지 않는다.

**B-3. duration 경고 (기능 유지)**
`frames > 81`일 때 생성 화면에 품질 저하 경고를 표시한다. **차단하지 않는다.**

> 결정 근거: 운영 26%가 이 영역을 쓰고 있어 차단은 기존 워크플로를 깨뜨린다. 사용자가 기능 유지를 선택했다.
> **남는 위험**: 81프레임 초과 구간의 `naturalMotion`/`backgroundStable` 저하는 이 스펙으로 해결되지 않는다. 근본 해결에는 context window 또는 세그먼트 이어붙이기가 필요하며 별도 과제다.

**B-4. split_step 파생**
`split_step`을 2 고정에서 `steps`로부터 파생(`round(steps/2)`)하도록 바꾼다. 영향 범위가 가장 작으므로(3건) **B-1~B-3 이후에 착수한다.**

**B-5. 평가 수집률 개선**
현재 1.8%로는 이 스펙의 효과를 검증할 수 없다. 작업 완료 시점에 평가 진입 동선을 만들고, 미평가 작업을 이력 화면에서 구분 표시한다.

경계: 평가를 **강제하지 않는다**. 강제는 무성의한 5점을 만들어 데이터를 오염시킨다.

### 3.3 C — 템플릿 품질

**C-1. 미등록 워크플로우를 비활성으로**
`is_workflow_active()`의 기본값을 `True` → `False`로 바꾼다. 검증을 통과한 적 없는 워크플로우가 사용자에게 노출되지 않는다.

**선행 조건**: 이 변경만 먼저 배포하면 현재 활성 워크플로우 7개가 즉시 사라진다. C-2를 먼저 끝내고 함께 배포한다.

**C-2. seed 경로도 검증 통과**
`bootstrap_workflow_store()`가 seed에서 복사한 워크플로우도 등록·검증 파이프라인을 통과시켜 레지스트리에 기록한다. C-1의 선행 조건이다.

**C-3. 생성기의 스위치 분기 인식**
`generate_param_config()`가 `ComfySwitchNode`를 추적해, 스위치를 거치는 파라미터를 3.1 원칙대로 `locked: true`로 표시한다. 비활성 분기의 노드는 아예 노출하지 않는다.

경계: 어느 분기가 "옳은지" 판단하지 않는다. 생성기는 **불확실성을 표시할 뿐** 값을 정하지 않는다.

**C-4. object_info 대조 검증**
`validate_workflow_registration_payload()`가 현재 확인하는 것은 노드가 dict인지, `class_type`이 있는지, `LoadImage`/`SaveVideo` 존재 여부뿐이다. 여기에 워커의 실제 능력 대조를 추가한다 — 미설치 `class_type`, 볼륨에 없는 모델 파일을 **등록 시점에** 잡는다.

전제: `metadata_loader`에 `object_info` 스냅샷 경로가 이미 있으나 현재 `hasObjectInfoSnapshot: false`다. 서버리스 워커에서 `object_info`를 받아 스냅샷하는 단계가 선행되어야 한다.

**우선순위가 가장 낮다.** C-1~C-3 없이 이것만 하면 검증은 강해지되 검증을 우회하는 경로(seed, 미등록 기본 활성)가 그대로 남는다.

## 4. 구현 순서

의존 관계상 이 순서를 지킨다.

```
1. B-1 (서버측 강제)        ← 키스톤. 단독으로 배포 가능
2. B-2 (paramconfig 교정)   ← B-1이 있어야 효과 발생
3. B-3 (duration 경고)      ← 독립
4. C-2 → C-1 (검증 통과 후 기본 비활성)  ← 반드시 함께 배포
5. C-3 (생성기 fail-closed)
6. B-5 (평가 수집률)
7. B-4 (split_step 파생)
8. C-4 (object_info 대조)
```

## 5. 검증 기준

B의 효과는 평가 데이터로만 검증할 수 있고, 그 데이터는 B-5가 만든다. 따라서 검증은 2단계다.

**1단계 — 즉시 확인 가능 (B-1·B-2·C-1~C-3 배포 직후)**

| 지표 | 현재 | 목표 |
|---|---|---|
| 선언 범위를 벗어난 값의 제출 성공 | 통과함 (shift=1, 5건) | 0건 (HTTP 400) |
| 레지스트리 미등록 활성 워크플로우 | 7개 | 0개 |
| 신규 등록 템플릿의 `locked` 미표시 스위치 파라미터 | 전부 | 0개 |

**2단계 — 평가 30건 이상 축적 후**

| 지표 | 현재 | 목표 |
|---|---|---|
| 결과 평가 수집률 | 1.8% (2/111) | > 30% |
| `naturalMotion` 위반 비율 | 측정 불가 | 기준선 확보 후 설정 |
| `noDistortion` 위반 비율 | 측정 불가 | 기준선 확보 후 설정 |

2단계 목표를 지금 숫자로 못 박지 않는다 — 기준선이 없는 상태에서 정한 목표치는 근거가 없다.

## 6. 테스트

- **B-1**: `min` 미만, `max` 초과, `options` 밖의 값, `locked` 파라미터의 비기본값 → 각각 `ValueError`. 범위 내 값과 `default` 생략 시 기존 동작 회귀 없음.
- **B-2**: 교정된 paramconfig로 `cfg=1.8` 제출 시 거부. `cfg=1.0` 통과.
- **B-3**: `frames=161`에 경고 표시, 제출은 성공.
- **C-1/C-2**: seed 워크플로우가 부트스트랩 후 레지스트리에 기록되고 활성. 레지스트리에 없는 임의 파일은 비활성.
- **C-3**: `ComfySwitchNode`를 거치는 파라미터가 `locked: true`로 생성. 비활성 분기 노드 미노출. `1-images.json`을 입력으로 회귀 테스트.

기존 `backend/tests/` 패턴을 따른다.

## 7. 범위 밖

- **프롬프트 생성 품질** — `intentMatched`가 증상으로 지목되지 않았다. `prompt_feedback` 0건도 이 스펙에서 다루지 않는다.
- **81프레임 초과 구간의 품질** — B-3 결정에 따라 남는 위험으로 수용. context window / 세그먼트 이어붙이기는 별도 과제.
- **샌드박스와 서버리스의 컨테이너 이미지 통일** — C-4의 전제이자 A의 Phase 2와 겹치는 아키텍처 결정. 별도로 다룬다.

## 8. 열린 항목

- `motionShift=1`이 어떤 경로로 들어왔는지 특정하지 못했다. 프론트 검증 누락인지, 구버전 paramconfig인지, API 직접 호출인지. B-1이 결과적으로 막지만 원인은 미확인이다.
- distilled LoRA 분기를 생성기가 자동 판별하는 휴리스틱(lora 파일명 패턴 등)은 C-3에서 시도하되, 판별 실패 시 `locked`로 남기는 것이 안전 기본값이다.
