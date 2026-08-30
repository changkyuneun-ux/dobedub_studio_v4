# 워크플로우 파라미터 강제 (B-1 ~ B-4) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** paramconfig가 선언한 파라미터 제약을 서버가 실제로 강제하게 하고, 잘못 선언된 값(cfg 상한, shift 하한, 비네이티브 해상도)을 교정한다.

**Architecture:** 순수 검증 함수 하나를 새로 만들고(`validate_param_value`), 기존 패치 경로 한 곳에서 호출한다. 나머지는 데이터(paramconfig JSON) 수정과 프론트 경고 표시다. 코드 변경 표면을 최소로 유지하고 정책은 데이터에 둔다.

**Tech Stack:** Python 3.12, unittest, FastAPI, React + TypeScript (Vite)

## Global Constraints

- **클램프가 아니라 거부한다.** 범위를 벗어난 값은 조용히 보정하지 않고 `ValueError`를 던진다. [jobs.py:29](../../../backend/app/api/v1/jobs.py#L29)가 이미 HTTP 400으로 변환한다.
- **`step`(16의 배수) 검사는 새로 만들지 않는다.** 기존 `validate_segment_resolution()`이 담당한다.
- **duration은 차단하지 않는다.** 81프레임 초과는 경고만 표시한다. 상한 유지가 결정된 사안이다.
- **paramconfig는 리포지토리와 운영 EFS 양쪽을 고쳐야 한다.** 앱 시작 시 기본본은 존재하지 않는 파일만 복사하므로 리포지토리만 고치면 운영에 반영되지 않는다.
- distilled LoRA(cfg 1.0 고정) 대상은 `1-images` ~ `6-images`, `Blowbang1`, `Pickme_Workflow`이다. **`video_wan2_2_14B_flf2v_2-images-1`은 LoRA를 쓰지 않으므로 제외한다**(steps 20 / cfg 4가 정상값).
- 테스트 실행은 리포지토리 루트에서 `python3 -m unittest backend.tests.<module> -v`.

## 사전 확인 (완료됨)

- 전체 paramconfig에서 `default`가 자기 `min`/`max`/`options`를 위반하는 사례 **0건**. 따라서 Task 1~2를 먼저 배포해도 기존 정상 제출이 깨지지 않는다.
- `options` 키는 paramconfig 스키마에 이미 존재한다. `locked` 키는 새로 도입한다.

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `backend/app/services/workflow_patch_service.py` | 파라미터 검증 함수 추가, 패치 경로에서 호출 | 수정 |
| `backend/tests/test_workflow_param_validation.py` | 검증 함수 단위 테스트 | 신규 |
| `backend/tests/test_paramconfig_contract.py` | paramconfig 데이터 계약 테스트 | 신규 |
| `workflows/*.paramconfig.json` | cfg 1.0 고정, shift 하한 5.0, 해상도 프리셋 | 수정 (데이터) |
| `frontend/src/screens/createScreens.tsx` | 81프레임 초과 경고 | 수정 |

---

### Task 1: 파라미터 제약 검증 함수

순수 함수로 먼저 만든다. 이 태스크만으로는 동작이 바뀌지 않는다.

**Files:**
- Modify: `backend/app/services/workflow_patch_service.py` (상수 블록 및 `validate_segment_resolution` 위)
- Test: `backend/tests/test_workflow_param_validation.py` (신규)

**Interfaces:**
- Produces: `validate_param_value(param_name: str, param_spec: dict, value, segment_index: int) -> None` — 위반 시 `ValueError`, 통과 시 `None`.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_workflow_param_validation.py` 를 새로 만든다.

```python
from __future__ import annotations

import unittest

from backend.app.services.workflow_patch_service import validate_param_value


class ValidateParamValueTests(unittest.TestCase):
    def test_accepts_value_inside_declared_range(self) -> None:
        spec = {"type": "float", "min": 2.0, "max": 10.0, "default": 5.0}

        self.assertIsNone(validate_param_value("motion_shift", spec, 5.0, 1))

    def test_rejects_value_below_minimum(self) -> None:
        spec = {"type": "float", "min": 5.0, "max": 10.0, "default": 5.0}

        with self.assertRaises(ValueError) as ctx:
            validate_param_value("motion_shift", spec, 1, 1)

        self.assertIn("motion_shift", str(ctx.exception))

    def test_rejects_value_above_maximum(self) -> None:
        spec = {"type": "int", "min": 1, "max": 24, "default": 4}

        with self.assertRaises(ValueError):
            validate_param_value("steps", spec, 50, 2)

    def test_rejects_non_numeric_value_for_bounded_param(self) -> None:
        spec = {"type": "int", "min": 1, "max": 24, "default": 4}

        with self.assertRaises(ValueError):
            validate_param_value("steps", spec, "빠르게", 1)

    def test_accepts_value_in_options(self) -> None:
        spec = {"type": "string", "options": ["auto", "mp4"], "default": "auto"}

        self.assertIsNone(validate_param_value("video_format", spec, "mp4", 1))

    def test_rejects_value_outside_options(self) -> None:
        spec = {"type": "string", "options": ["auto", "mp4"], "default": "auto"}

        with self.assertRaises(ValueError):
            validate_param_value("video_format", spec, "mkv", 1)

    def test_locked_param_accepts_only_its_default(self) -> None:
        spec = {"type": "float", "locked": True, "default": 1.0}

        self.assertIsNone(validate_param_value("cfg_scale", spec, 1.0, 1))
        with self.assertRaises(ValueError):
            validate_param_value("cfg_scale", spec, 1.8, 1)

    def test_locked_param_tolerates_float_representation_noise(self) -> None:
        """워크플로우 JSON에는 5.000000000000001 같은 값이 실제로 들어 있다."""
        spec = {"type": "float", "locked": True, "default": 5.0}

        self.assertIsNone(validate_param_value("motion_shift", spec, 5.000000000000001, 1))

    def test_passes_when_spec_declares_no_constraint(self) -> None:
        spec = {"type": "int", "default": 8}

        self.assertIsNone(validate_param_value("bit_depth", spec, 14, 1))

    def test_message_names_the_segment(self) -> None:
        spec = {"type": "int", "min": 1, "max": 24, "default": 4}

        with self.assertRaises(ValueError) as ctx:
            validate_param_value("steps", spec, 99, 3)

        self.assertIn("3", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python3 -m unittest backend.tests.test_workflow_param_validation -v
```

Expected: `ImportError: cannot import name 'validate_param_value'`

- [ ] **Step 3: 최소 구현**

`backend/app/services/workflow_patch_service.py`의 상수 블록(`MAX_RESOLUTION_PIXELS = 1_048_576` 아래)에 추가한다.

```python
FLOAT_EQUALITY_TOLERANCE = 1e-9


def _numeric_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _matches_locked_default(value, default) -> bool:
    numeric_value = _numeric_or_none(value)
    numeric_default = _numeric_or_none(default)
    if numeric_value is not None and numeric_default is not None:
        return abs(numeric_value - numeric_default) <= FLOAT_EQUALITY_TOLERANCE
    return value == default


def validate_param_value(param_name: str, param_spec: dict, value, segment_index: int) -> None:
    """Reject a browser-supplied value that violates the paramconfig contract.

    범위를 벗어난 값은 클램프하지 않고 거부한다. 조용히 보정하면 사용자가
    의도한 값과 실제 실행값이 달라지고, 결과 품질 문제의 원인을 추적할 수 없다.
    """
    if param_spec.get("locked"):
        if not _matches_locked_default(value, param_spec.get("default")):
            raise ValueError(
                f"Segment {segment_index} {param_name} is locked to "
                f"{param_spec.get('default')} and cannot be changed."
            )
        return

    options = param_spec.get("options") or []
    if options:
        if value not in options:
            raise ValueError(
                f"Segment {segment_index} {param_name} must be one of {options}."
            )
        return

    minimum = param_spec.get("min")
    maximum = param_spec.get("max")
    if minimum is None and maximum is None:
        return

    numeric = _numeric_or_none(value)
    if numeric is None:
        raise ValueError(f"Segment {segment_index} {param_name} must be a number.")
    if minimum is not None and numeric < float(minimum):
        raise ValueError(
            f"Segment {segment_index} {param_name} must be at least {minimum}."
        )
    if maximum is not None and numeric > float(maximum):
        raise ValueError(
            f"Segment {segment_index} {param_name} must not exceed {maximum}."
        )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python3 -m unittest backend.tests.test_workflow_param_validation -v
```

Expected: `Ran 10 tests` / `OK`

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/workflow_patch_service.py backend/tests/test_workflow_param_validation.py
git commit -m "feat: add paramconfig constraint validator"
```

---

### Task 2: 패치 경로에 검증 결선

Task 1의 함수를 실제 제출 경로에 연결한다. **여기서부터 동작이 바뀐다.**

**Files:**
- Modify: `backend/app/services/workflow_patch_service.py:185-219` (`apply_node_config_to_workflow`)
- Test: `backend/tests/test_workflow_param_validation.py` (테스트 추가)

**Interfaces:**
- Consumes: `validate_param_value(param_name, param_spec, value, segment_index)` (Task 1)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_workflow_param_validation.py` 하단, `if __name__ == "__main__":` 위에 클래스를 추가한다.

```python
import json
import tempfile
from pathlib import Path

from backend.app.services.workflow_patch_service import apply_node_config_to_workflow


def _write_fixture(directory: Path) -> None:
    """min/max가 선언된 파라미터 하나를 가진 최소 워크플로우 한 쌍."""
    (directory / "fixture.json").write_text(json.dumps({
        "10": {"class_type": "ModelSamplingSD3", "inputs": {"shift": 5.0}},
    }), encoding="utf-8")
    (directory / "fixture.paramconfig.json").write_text(json.dumps({
        "workflow": "fixture.json",
        "segments": [{
            "segment_index": 1,
            "params": {
                "motion_shift": {
                    "targets": [{"node": "10", "field": "shift"}],
                    "type": "float", "min": 5.0, "max": 10.0, "default": 5.0,
                },
            },
        }],
    }), encoding="utf-8")


class ApplyNodeConfigValidationTests(unittest.TestCase):
    def test_applies_value_inside_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_fixture(directory)
            workflow = json.loads((directory / "fixture.json").read_text(encoding="utf-8"))

            applied = apply_node_config_to_workflow(
                workflow, "fixture.json", [{"config": {"motionShift": 8.0}}], directory
            )

            self.assertEqual(workflow["10"]["inputs"]["shift"], 8.0)
            self.assertEqual(applied[0]["param"], "motion_shift")

    def test_rejects_value_below_declared_minimum(self) -> None:
        """운영에서 shift=1이 5건 통과한 회귀를 막는다."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_fixture(directory)
            workflow = json.loads((directory / "fixture.json").read_text(encoding="utf-8"))

            with self.assertRaises(ValueError):
                apply_node_config_to_workflow(
                    workflow, "fixture.json", [{"config": {"motionShift": 1}}], directory
                )

            self.assertEqual(workflow["10"]["inputs"]["shift"], 5.0, "거부된 값은 주입되지 않아야 한다")

    def test_omitted_value_leaves_workflow_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_fixture(directory)
            workflow = json.loads((directory / "fixture.json").read_text(encoding="utf-8"))

            applied = apply_node_config_to_workflow(
                workflow, "fixture.json", [{"config": {}}], directory
            )

            self.assertEqual(workflow["10"]["inputs"]["shift"], 5.0)
            self.assertEqual(applied, [])
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python3 -m unittest backend.tests.test_workflow_param_validation.ApplyNodeConfigValidationTests -v
```

Expected: `test_rejects_value_below_declared_minimum` FAIL — `ValueError` 미발생

> `test_applies_value_inside_range`와 `test_omitted_value_leaves_workflow_untouched`는 현재 코드로도 통과한다. 회귀 방지용이다.

- [ ] **Step 3: 최소 구현**

`backend/app/services/workflow_patch_service.py`의 `apply_node_config_to_workflow` 안, `if value is None: continue` 바로 다음 줄에 한 줄을 추가한다.

```python
            value = node_config.get(param_name, param_spec.get("default"))
            if value is None:
                continue
            validate_param_value(param_name, param_spec, value, index + 1)
            for target in param_spec.get("targets") or []:
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python3 -m unittest backend.tests.test_workflow_param_validation -v
```

Expected: `Ran 13 tests` / `OK`

- [ ] **Step 5: 기존 테스트 회귀 확인**

```bash
python3 -m unittest backend.tests.test_admin_workflow_id backend.tests.test_sandbox_pod_service backend.tests.test_asset_streaming backend.tests.test_observability -v
```

Expected: 전부 `OK`

- [ ] **Step 6: 커밋**

```bash
git add backend/app/services/workflow_patch_service.py backend/tests/test_workflow_param_validation.py
git commit -m "feat: enforce paramconfig ranges on job submission"
```

---

### Task 3: paramconfig 값 교정

코드가 아니라 데이터를 고친다. Task 2가 먼저 있어야 효과가 난다.

**Files:**
- Modify: `workflows/1-images.paramconfig.json` ~ `workflows/6-images.paramconfig.json`
- Modify: `workflows/Blowbang1.paramconfig.json`, `workflows/Pickme_Workflow.paramconfig.json`
- Test: `backend/tests/test_paramconfig_contract.py` (신규)

**Interfaces:**
- Consumes: `validate_param_value` (Task 1) — `locked` 키 의미론

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_paramconfig_contract.py` 를 새로 만든다.

```python
from __future__ import annotations

import json
import unittest
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"

# distilled LoRA(lightx2v 4-step)를 쓰는 템플릿. cfg는 1.0이 전제다.
# video_wan2_2_14B_flf2v_2-images-1은 LoRA를 쓰지 않으므로 제외한다.
DISTILLED_WORKFLOWS = [
    "1-images", "2-images", "3-images", "4-images", "5-images", "6-images",
    "Blowbang1", "Pickme_Workflow",
]

MIN_MOTION_SHIFT = 5.0


def _segment_params(stem: str) -> list[dict]:
    path = WORKFLOWS_DIR / f"{stem}.paramconfig.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [(segment.get("params") or {}) for segment in (data.get("segments") or [])]


class ParamConfigContractTests(unittest.TestCase):
    def test_distilled_workflows_lock_cfg_to_one(self) -> None:
        for stem in DISTILLED_WORKFLOWS:
            for index, params in enumerate(_segment_params(stem), start=1):
                spec = params.get("cfg_scale")
                if spec is None:
                    continue
                with self.subTest(workflow=stem, segment=index):
                    self.assertTrue(spec.get("locked"), "cfg_scale must be locked")
                    self.assertEqual(float(spec["default"]), 1.0)

    def test_motion_shift_minimum_is_five(self) -> None:
        for stem in DISTILLED_WORKFLOWS:
            for index, params in enumerate(_segment_params(stem), start=1):
                spec = params.get("motion_shift")
                if spec is None:
                    continue
                with self.subTest(workflow=stem, segment=index):
                    self.assertGreaterEqual(float(spec["min"]), MIN_MOTION_SHIFT)

    def test_every_default_satisfies_its_own_constraints(self) -> None:
        """생성기나 수동 편집이 자기모순인 paramconfig를 만드는 것을 막는다."""
        for path in sorted(WORKFLOWS_DIR.glob("*.paramconfig.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for index, segment in enumerate(data.get("segments") or [], start=1):
                for name, spec in (segment.get("params") or {}).items():
                    default = spec.get("default")
                    if default is None:
                        continue
                    with self.subTest(file=path.name, segment=index, param=name):
                        options = spec.get("options") or []
                        if options:
                            self.assertIn(default, options)
                            continue
                        if spec.get("min") is not None:
                            self.assertGreaterEqual(float(default), float(spec["min"]))
                        if spec.get("max") is not None:
                            self.assertLessEqual(float(default), float(spec["max"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python3 -m unittest backend.tests.test_paramconfig_contract -v
```

Expected: `test_distilled_workflows_lock_cfg_to_one` FAIL (`cfg_scale must be locked`), `test_motion_shift_minimum_is_five` FAIL (min 2.0 < 5.0). `test_every_default_satisfies_its_own_constraints`는 PASS.

- [ ] **Step 3: paramconfig 8개 수정**

8개 파일 각각에서 `cfg_scale`과 `motion_shift` 스펙을 아래처럼 바꾼다. `targets`는 파일마다 다르므로 **그대로 두고 나머지 키만 교체한다.**

`cfg_scale` — `min`/`max`를 지우고 `locked`와 `default`를 넣는다:

```json
    "cfg_scale": {
      "targets": [ ... 기존 값 그대로 ... ],
      "type": "float",
      "default": 1.0,
      "locked": true,
      "note": "4-step distilled LoRA는 cfg=1.0이 전제다. 값을 올리면 채도 뭉개짐과 왜곡이 발생한다."
    },
```

`motion_shift` — `min`만 5.0으로 올린다:

```json
    "motion_shift": {
      "targets": [ ... 기존 값 그대로 ... ],
      "type": "float",
      "min": 5.0,
      "max": 10.0,
      "default": 5.0,
      "sync": true
    },
```

> `default`가 `5.000000000000001`인 파일이 있다. 그대로 두어도 `min` 검사를 통과하므로 굳이 바꾸지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

```bash
python3 -m unittest backend.tests.test_paramconfig_contract -v
```

Expected: `Ran 3 tests` / `OK`

- [ ] **Step 5: 실제 거부 동작 확인**

```bash
python3 -c "
import json
from pathlib import Path
from backend.app.services.workflow_patch_service import apply_node_config_to_workflow
wf = json.loads(Path('workflows/1-images.json').read_text(encoding='utf-8'))
for label, config in (('cfg 1.8', {'cfgScale': 1.8}), ('shift 1', {'motionShift': 1}), ('정상', {'cfgScale': 1.0, 'motionShift': 5.0})):
    try:
        apply_node_config_to_workflow(wf, '1-images.json', [{'config': config}], Path('workflows'))
        print(f'{label}: 통과')
    except ValueError as exc:
        print(f'{label}: 거부 - {exc}')
"
```

Expected:
```
cfg 1.8: 거부 - Segment 1 cfg_scale is locked to 1.0 and cannot be changed.
shift 1: 거부 - Segment 1 motion_shift must be at least 5.0.
정상: 통과
```

- [ ] **Step 6: 커밋**

```bash
git add workflows/*.paramconfig.json backend/tests/test_paramconfig_contract.py
git commit -m "fix: lock cfg to 1.0 and raise motion_shift floor for distilled workflows"
```

---

### Task 4: Wan 네이티브 해상도 프리셋

해상도 조합을 템플릿별로 제한한다. **전역 강제가 아니라 paramconfig가 선언한 템플릿에만 적용**해, 프리셋이 없는 템플릿은 기존 동작을 유지한다.

**Files:**
- Modify: `backend/app/services/workflow_patch_service.py:132-156` (`validate_segment_resolution`), `:200` (호출부)
- Modify: `workflows/1-images.paramconfig.json` ~ `workflows/6-images.paramconfig.json`, `workflows/Blowbang1.paramconfig.json`, `workflows/Pickme_Workflow.paramconfig.json`
- Test: `backend/tests/test_workflow_param_validation.py` (테스트 추가)

**Interfaces:**
- Produces: `validate_segment_resolution(params, node_config, segment_index, presets=None)` — `presets`는 `[[width, height], ...]` 또는 `None`.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_workflow_param_validation.py` 하단에 추가한다.

```python
from backend.app.services.workflow_patch_service import validate_segment_resolution

PRESETS = [[1280, 720], [720, 1280], [832, 480], [480, 832]]
DIMENSION_SPEC = {
    "width": {"type": "int", "min": 256, "max": 1280, "default": 1280},
    "height": {"type": "int", "min": 256, "max": 1280, "default": 720},
}


class ResolutionPresetTests(unittest.TestCase):
    def test_accepts_preset_pair(self) -> None:
        validate_segment_resolution(DIMENSION_SPEC, {"width": 720, "height": 1280}, 1, PRESETS)

    def test_rejects_non_preset_pair(self) -> None:
        """720x720 정사각은 Wan 학습 비율이 아니다."""
        with self.assertRaises(ValueError) as ctx:
            validate_segment_resolution(DIMENSION_SPEC, {"width": 720, "height": 720}, 1, PRESETS)

        self.assertIn("720", str(ctx.exception))

    def test_without_presets_keeps_existing_behaviour(self) -> None:
        validate_segment_resolution(DIMENSION_SPEC, {"width": 720, "height": 720}, 1, None)

    def test_preset_check_runs_after_dimension_checks(self) -> None:
        """16의 배수가 아닌 값은 프리셋 검사 전에 기존 규칙이 먼저 잡는다."""
        with self.assertRaises(ValueError) as ctx:
            validate_segment_resolution(DIMENSION_SPEC, {"width": 723, "height": 720}, 1, PRESETS)

        self.assertIn("multiple", str(ctx.exception))
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python3 -m unittest backend.tests.test_workflow_param_validation.ResolutionPresetTests -v
```

Expected: `TypeError: validate_segment_resolution() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: 최소 구현**

`validate_segment_resolution`의 시그니처와 말미를 바꾼다. 함수 본문 앞부분(치수별 검사)은 그대로 둔다.

```python
def validate_segment_resolution(
    params: dict,
    node_config: dict,
    segment_index: int,
    presets: list | None = None,
) -> None:
    """Validate the direct width/height controls before patching a workflow."""
```

기존 마지막 블록 뒤에 프리셋 검사를 덧붙인다.

```python
    if len(dimensions) == 2 and dimensions["width"] * dimensions["height"] > MAX_RESOLUTION_PIXELS:
        raise ValueError(
            f"Segment {segment_index} resolution must not exceed {MAX_RESOLUTION_PIXELS:,} pixels."
        )

    if presets and len(dimensions) == 2:
        allowed = {(int(width), int(height)) for width, height in presets}
        actual = (dimensions["width"], dimensions["height"])
        if actual not in allowed:
            readable = ", ".join(f"{width}×{height}" for width, height in sorted(allowed))
            raise ValueError(
                f"Segment {segment_index} resolution {actual[0]}×{actual[1]} is not a "
                f"supported preset. Use one of: {readable}."
            )
```

호출부(`apply_node_config_to_workflow` 안)에서 세그먼트 스펙의 프리셋을 넘긴다.

```python
        validate_segment_resolution(
            params, node_config, index + 1, segment_spec.get("resolution_presets")
        )
```

> `segment_spec`은 같은 루프 안에 이미 `segment_spec = specs[index] if index < len(specs) else {}`로 존재한다.

- [ ] **Step 4: 테스트 통과 확인**

```bash
python3 -m unittest backend.tests.test_workflow_param_validation -v
```

Expected: `Ran 17 tests` / `OK`

- [ ] **Step 5: paramconfig 8개에 프리셋 선언**

Task 3에서 고친 같은 8개 파일의 각 `segments[]` 항목에 `params`와 나란히 키를 추가한다.

```json
    {
      "segment_index": 1,
      "resolution_presets": [[1280, 720], [720, 1280], [832, 480], [480, 832]],
      "params": { ... }
    }
```

- [ ] **Step 6: 실제 거부 동작 확인**

```bash
python3 -c "
import json
from pathlib import Path
from backend.app.services.workflow_patch_service import apply_node_config_to_workflow
wf = json.loads(Path('workflows/1-images.json').read_text(encoding='utf-8'))
for label, config in ((' 720x720', {'width':720,'height':720}), ('1280x720', {'width':1280,'height':720})):
    try:
        apply_node_config_to_workflow(wf, '1-images.json', [{'config': config}], Path('workflows'))
        print(f'{label}: 통과')
    except ValueError as exc:
        print(f'{label}: 거부 - {exc}')
"
```

Expected:
```
 720x720: 거부 - Segment 1 resolution 720×720 is not a supported preset. Use one of: 480×832, 720×1280, 832×480, 1280×720.
1280x720: 통과
```

- [ ] **Step 7: 커밋**

```bash
git add backend/app/services/workflow_patch_service.py backend/tests/test_workflow_param_validation.py workflows/*.paramconfig.json
git commit -m "feat: restrict resolution to Wan native presets per workflow"
```

---

### Task 5: 81프레임 초과 경고 (프론트)

**차단하지 않는다.** 경고만 표시한다.

**Files:**
- Modify: `frontend/src/screens/createScreens.tsx` (`RunSummaryScreen`, `estimatedSeconds` 계산 직후 및 rightPanel)

**Interfaces:**
- Consumes: 기존 `configValue(segment, keys)` 헬퍼와 `segments` 상태.

- [ ] **Step 1: 상수와 계산 추가**

`estimatedSeconds` 선언 바로 다음에 추가한다. `configValue`가 이미 정의된 위치라야 한다.

```tsx
  // 2026-08-30: Wan 2.2 i2v의 학습 윈도우는 81프레임(16fps 기준 5초)이다.
  // 초과분은 후반부 모션이 뭉개지고 배경이 표류한다. 상한 유지가 결정된
  // 사안이므로 차단하지 않고 경고만 표시한다.
  const NATIVE_FRAME_WINDOW = 81;
  const overLengthSegments = segments.filter(
    (segment) => Number(configValue(segment, ["frames", "FRAMES"])) > NATIVE_FRAME_WINDOW
  );
```

- [ ] **Step 2: 경고 렌더링 추가**

`rightPanel`의 `<p className="v3-muted-text">제출 후에는 ...</p>` 바로 위에 넣는다.

```tsx
          {overLengthSegments.length > 0 ? (
            <p className="v3-inline-notice">
              세그먼트 {overLengthSegments.length}개가 {NATIVE_FRAME_WINDOW}프레임을 넘습니다.
              모델 학습 구간을 벗어나 후반부 움직임과 배경이 불안정해질 수 있습니다. 실행은 가능합니다.
            </p>
          ) : null}
```

- [ ] **Step 3: 빌드 및 타입 확인**

```bash
npm run build
```

Expected: 오류 없이 빌드 완료

- [ ] **Step 4: 화면 확인**

```bash
npm run local
```

`http://127.0.0.1:8790` 에서 `1-images` 워크플로우를 선택하고 duration을 10초로 설정한 뒤 실행 전 확인 화면으로 이동한다.

Expected: 우측 실행 패널에 경고 문구가 보이고, `Run` 버튼은 **여전히 활성 상태**여야 한다.

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/screens/createScreens.tsx
git commit -m "feat: warn when segment exceeds the 81-frame native window"
```

---

## 배포 시 필수 작업

리포지토리 수정만으로는 운영에 반영되지 않는다.

- [ ] 운영 EFS `/data/outputs/dobedub-studio/workflows/` 의 paramconfig를 같은 내용으로 교체한다. 대상은 Task 3·4에서 고친 8개에 더해 **EFS에만 존재하는 4개** — `Wan22_default`, `Pickme_Workflow_v2`, `Pickme_Workflow_v3`, `Pickme_Workflow_v5` — 도 포함한다. 이 넷은 리포지토리에 없으므로 같은 규칙(cfg locked 1.0, motion_shift min 5.0, resolution_presets)을 직접 적용해야 한다.
- [ ] 교체 후 `GET /api/workflows/<id>/schema`로 각 워크플로우의 파라미터 범위가 바뀌었는지 확인한다.
- [ ] 저장된 config 스냅샷 중 새 제약을 위반하는 것이 있으면 사용자에게 안내한다. 운영 실측 기준 `720×720`(가장 흔한 조합)과 `cfg 1.8`/`3.9`, `shift 1`이 이제 거부된다.

## Self-Review 결과

- **스펙 커버리지**: B-1(Task 1·2), B-2(Task 3), B-3(Task 4), B-4(Task 5) 전부 대응. B-5·B-6·B-7과 C 트랙은 이 계획의 범위 밖이며 별도 계획으로 작성한다.
- **타입 일관성**: `validate_param_value`는 Task 1에서 정의한 4-인자 시그니처를 Task 2가 그대로 쓴다. `validate_segment_resolution`은 Task 4에서 4번째 인자를 기본값 `None`으로 추가하므로 기존 호출이 깨지지 않는다.
- **알려진 영향**: Task 4는 운영에서 가장 많이 쓰이는 `720×720`을 거부하게 만든다. 의도된 변경이지만 배포 전 사용자 공지가 필요하다 — 위 체크리스트에 포함했다.
