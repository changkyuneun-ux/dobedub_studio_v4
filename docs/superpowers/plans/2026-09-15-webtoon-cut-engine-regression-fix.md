# Webtoon Cut Engine Regression Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Branch:** `feat/cut-server`

**Goal:** ECS 운영 중인 웹툰 컷 분리에서 발생한 두 가지 회귀 — (1) 말풍선 텍스트 소실, (2) 패널 분리 누락 — 를 유발한 커밋을 되돌리고, 회귀를 정답으로 고정한 테스트를 바로잡는다.

**Scope:** 서버 Python 엔진(`webtoon_panel_engine`), 해당 테스트, 프론트 TypeScript 포팅 엔진(`gridSplitEngine.ts`), parity 테스트.

**Not in scope:** 컷 검출 알고리즘의 신규 개선, S3/DB/naming 정책, UI 레이아웃.

---

## 1. 증상

운영 환경(ECS)에서 두 가지가 동시에 보고되었다.

1. **말풍선 텍스트가 사라진다.** 컷 이미지에서 프레임 밖으로 살짝 튀어나온 말풍선과 그 안의 대사가 잘려 나간다.
2. **패널 분리가 제대로 안 된다.** 한 페이지에서 잡아야 할 컷을 못 잡고, 일부 페이지는 컷을 하나도 못 찾아 `fullpage` 폴백으로 떨어진다.

---

## 2. 원인 분석

두 증상은 **서로 다른 커밋에서 발생한 별개의 회귀**다. 둘 다 2026-09-15 오후에 들어갔다.

### 2.1 서버 엔진 버전 변천

`backend/app/services/webtoon_panel_engine/grid_split.py` 의 이력:

| 커밋 | 시각 | 엔진 | 함수 수 | 비고 |
|---|---|---|---|---|
| `eae2b07` | 12:58 | v3 (438줄) | 12 | 서버 파이프라인 최초 도입 |
| `7798bb5` | 14:48 | **v4 (514줄)** | 16 | v3 + 말풍선 보존 |
| `b46eeca` | 15:39 | v3 (438줄) | 12 | ← **회귀 1**: 말풍선 보존 삭제 |
| `ac186e5` | 16:20 | **v1 (312줄)** | 7 | ← **회귀 2**: 엔진 다운그레이드 |

현재 `HEAD`(= `ac186e5`)가 운영 중인 엔진은 **v1**이며, 이는 세 계열 중 검출 성능이 가장 낮다.

### 2.2 회귀 1 — 말풍선 텍스트 소실 (`b46eeca`, "fix webtoon cut engine rendering fidelity")

이 커밋은 말풍선 보존을 담당하던 함수 4개를 삭제하고 `_refine_to_border` 를 축소했다.

```diff
- def _overlap_len(a0, a1, b0, b1):
- def _axis_gap(a0, a1, b0, b1):
- def _is_near_border_protrusion(candidate, core, max_gap):
- def _expand_to_nearby_ink(img, region, search_region, pad_frac=0.06):
- def _refine_to_border(img, leaf, pad_frac=0.06, min_keep_ratio=0.55, include_nearby_ink=True):
+ def _refine_to_border(img, leaf, pad_frac=0.03, min_keep_ratio=0.55):
```

삭제된 `_expand_to_nearby_ink` 의 docstring이 이번 증상을 그대로 기술하고 있다.

> 컷 테두리 가까이 돌출된 말풍선/텍스트 잉크를 최종 crop에 포함한다. 컷 여부 판정은 사각 테두리 기준으로 유지하되, 저장 crop만 주변 잉크와 합집합으로 확장한다. 말풍선이 프레임 밖으로 살짝 튀어나온 페이지에서 텍스트가 잘리는 것을 막기 위한 보정이다.

`pad_frac` 이 0.06 → 0.03 으로 절반이 된 것도 같은 방향으로 작용한다.

**재현.** 저장소 테스트와 동일한 합성 이미지(컷 테두리 상단 `y=120`, 그 위로 돌출된 말풍선 `y≈25~105`)에 각 엔진의 `_refine_to_border` 를 직접 호출한 결과:

| 엔진 | 반환된 crop 상단 `y` | 말풍선 |
|---|---|---|
| v1 (현재 운영) | 117 | 잘림 |
| v3 | 117 | 잘림 |
| v4 | **23** | 보존 |

v1과 v3는 테두리선 위치에서 자르므로 돌출부가 통째로 버려진다. v4만 인접 잉크까지 확장한다.

### 2.3 회귀 2 — 패널 분리 누락 (`ac186e5`, "Fix webtoon cut split baseline and thumbnails")

엔진이 v3 → v1 로 교체되며 156줄이 삭제됐다. v1에는 v3/v4가 가진 다음 판별 로직이 전혀 없다.

- `_has_gutter` — 그림 속 검은 직선(머리카락·창틀·효과선)을 컷 테두리로 오인하지 않게 거터 유무를 확인
- `_line_thickness` / `estimate_border_thickness` — 페이지별 인쇄 테두리 굵기를 추정해 그림선과 구분
- `_region_border_score` / `_looks_like_panel` — 장식 요소를 컷으로 오검출하지 않게 검증

**실측.** 과학사 2권 16~60쪽(45쪽)을 각 엔진으로 처리한 결과:

| 엔진 | 총 컷 | 0컷 페이지 | 총 출력 픽셀 |
|---|---|---|---|
| **v1 (현재 운영)** | **173** | **4** | **144 M** |
| v3 | 214 | 1 | 193 M |
| **v4** | **214** | **1** | **204 M** |

현재 운영 엔진은 v4 대비 **컷 19% 적고 출력 내용 29% 적다.**

v4는 v3와 컷 수·0컷 페이지 수가 완전히 같고 **출력 면적만 5.7% 크다.** 이 차이가 곧 되살아난 말풍선·돌출 텍스트다. 즉 v4는 v3 대비 검출 성능 손실 없이 내용 보존만 개선한다.

단일 페이지 확인(2권 16쪽, 육안 확인한 실제 컷 수 = 4):

| 엔진 | 검출 | 크기 |
|---|---|---|
| v1 | 2 | `(957,968) (848,967)` |
| v3 | 4 | `(872,1037) (938,1072) (957,968) (848,967)` |
| v4 | 4 | `(942,1037) (1019,1103) (1032,968) (928,967)` |

### 2.4 회귀를 고정한 테스트 (가장 먼저 풀어야 할 매듭)

두 회귀 커밋은 **테스트를 퇴화된 동작에 맞춰 수정했다.** 엔진만 되돌리면 CI가 실패하므로 테스트를 함께 바로잡아야 한다.

**(a) 말풍선 테스트가 반대로 뒤집혔다.** `b46eeca` 가 테스트 이름과 단언을 모두 반전시켰다.

```python
# b46eeca 이전 — 말풍선을 포함하는 것이 정답
def test_refine_to_border_preserves_nearby_speech_bubble_protrusion():
    assert refined[1] <= 30

# 현재 — 말풍선을 제외하는 것이 정답이라고 명시
def test_refine_to_border_keeps_crop_on_panel_border_instead_of_nearby_speech_bubble():
    assert 100 <= refined[1] <= 130
```

**(b) 잘못된 기준값이 회귀 테스트로 굳었다.** `ac186e5` 가 추가한 테스트는 2권 16쪽의 정답을 2컷으로 못박는다.

```python
assert len(result.cuts) == 2
assert [...] == [(1, 957, 968), (2, 848, 967)]
```

이 두 값은 **v1을 실행해 얻은 출력과 정확히 일치한다.** 해당 페이지의 실제 컷은 육안 확인 결과 4개다. 참조 PDF 경로(`/Users/changkyuneun/Downloads/과학사 100 원본/`)가 개발 머신에 실재하므로 이 테스트는 skip되지 않고 실행되며, 회귀를 능동적으로 잠근다.

### 2.5 영향 범위 — 두 경로 모두 결함

| 경로 | 호출 흐름 | 현재 상태 |
|---|---|---|
| **서버 (ECS 운영)** | `webtoon_cut_worker.py:113` → `webtoon_panel_engine` → `grid_split.py` | **v1** — 회귀 1·2 모두 해당 |
| **프론트 (브라우저)** | `runner.ts:83` → `detector.ts:8` → `gridDetector.ts` → `gridSplitEngine.ts` | **v3 포팅** — 회귀 1만 해당 |

프론트 TS 엔진은 `hasGutter`·`lineThickness`·`estimateBorderThickness`·`looksLikePanel` 을 모두 갖춘 **v3의 완전한 포팅**이므로 패널 검출은 정상이다. 다만 v4의 말풍선 보존이 포팅되지 않았고 `padFrac` 도 0.03이라 **텍스트 소실은 동일하게 발생한다.**

### 2.6 원인이 아닌 것

`ac186e5` 가 함께 넣은 프론트 변경(`RetryingCutThumbnail`, `frontend/src/screens/webtoonCutScreen.tsx`)은 58×48px 목록 썸네일의 로드 실패 재시도 로직이다. 출력 파일 자체에는 영향이 없으므로 **텍스트 소실과 무관하다.** 원인은 전적으로 crop 경계 계산에 있다.

`Dockerfile` 의 `poppler-utils poppler-data` 설치는 정상이며 되돌릴 필요가 없다.

---

## 3. 수정 계획

### Task 1 — 서버 엔진을 v4로 복원

- [ ] `backend/app/services/webtoon_panel_engine/grid_split.py` 를 `7798bb5` 시점 내용으로 복원한다.

  ```bash
  git show 7798bb5:backend/app/services/webtoon_panel_engine/grid_split.py \
    > backend/app/services/webtoon_panel_engine/grid_split.py
  ```

- [ ] 복원 확인: 다음 함수가 모두 존재해야 한다.
      `_overlap_len`, `_axis_gap`, `_is_near_border_protrusion`, `_expand_to_nearby_ink`,
      `_has_gutter`, `_line_thickness`, `estimate_border_thickness`,
      `_region_border_score`, `_looks_like_panel`

  ```bash
  grep -c "^def " backend/app/services/webtoon_panel_engine/grid_split.py   # 16 이어야 한다
  ```

- [ ] `_refine_to_border` 시그니처가 `pad_frac=0.06, min_keep_ratio=0.55, include_nearby_ink=True` 인지 확인한다.

`runtime.py` 와 `batch_split.py` 는 수정하지 않는다. 두 파일은 `split_panels` 시그니처에만 의존하며 v4에서도 동일하다.

### Task 2 — 말풍선 보존 테스트를 원복

- [ ] `backend/tests/test_webtoon_panel_grid_split.py` 10~21행을 다음으로 되돌린다.

  ```python
  def test_refine_to_border_preserves_nearby_speech_bubble_protrusion():
      from backend.app.services.webtoon_panel_engine.grid_split import _refine_to_border

      image = np.full((360, 520, 3), 255, dtype=np.uint8)
      cv2.rectangle(image, (120, 120), (460, 320), (0, 0, 0), 5)
      cv2.ellipse(image, (390, 65), (80, 40), 0, 0, 360, (0, 0, 0), 4)
      cv2.putText(image, "TEXT", (350, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

      refined, ok = _refine_to_border(image, (100, 40, 480, 330))

      assert ok is True
      assert refined[1] <= 30
  ```

  v4 기준 실제 반환값은 `23` 이다.

### Task 3 — 16쪽 기준값을 실제 정답으로 교정

- [ ] `backend/tests/test_webtoon_panel_grid_split.py` 48~65행의 단언을 **4컷** 기준으로 교체한다. v4 실행 결과:

  ```python
  assert result.mode == "grid"
  assert len(result.cuts) == 4
  assert [(cut.cut_index, cut.width, cut.height) for cut in result.cuts] == [
      (1, 942, 1037),
      (2, 1019, 1103),
      (3, 1032, 968),
      (4, 928, 967),
  ]
  ```

- [ ] 하드코딩된 개발 머신 절대경로를 제거한다. 현재 `/Users/changkyuneun/Downloads/과학사 100 원본/...` 를 직접 참조해 CI/ECS에서는 항상 skip되고 특정 개발 머신에서만 동작한다. 환경변수(`WEBTOON_REGRESSION_PDF`) 또는 저장소 내 축소 픽스처로 옮긴다.

> **주의:** 위 4개 크기 값은 이 계획을 작성하며 v4로 실측한 값이다. Task 1 복원 후 반드시 재실행해 실제 출력과 대조하고, 다르면 실제 값으로 갱신할 것. 값을 먼저 적어두고 코드를 맞추는 방향은 이번 회귀가 발생한 경로와 같다.

### Task 4 — 프론트 엔진에 말풍선 보존 포팅

- [ ] `frontend/src/features/webtoon-cut/gridSplitEngine.ts` 400행의 기본값을 바꾼다.

  ```diff
  - padFrac = 0.03,
  + padFrac = 0.06,
  ```

- [ ] 같은 파일에 `overlapLen`, `axisGap`, `isNearBorderProtrusion`, `expandToNearbyInk` 를 포팅한다.
      원본은 `git show 7798bb5:backend/app/services/webtoon_panel_engine/grid_split.py` 의 269~340행이다
      (`_overlap_len` 269행 ~ `_expand_to_nearby_ink` 끝. 이어지는 342행부터가 `_refine_to_border` 다).
      `labelComponents` 가 이미 있으므로 OpenCV `findContours` 대응은 그것으로 대체한다.

- [ ] 441행 `return { region: { x0: nx0, ... }, ok: true };` 직전에 확장을 적용한다.

  ```ts
  const expanded = includeNearbyInk
    ? expandToNearbyInk(image, { x0: nx0, y0: ny0, x1: nx1, y1: ny1 }, leaf, padFrac)
    : { x0: nx0, y0: ny0, x1: nx1, y1: ny1 };
  return { region: expanded, ok: true };
  ```

- [ ] 474행 호출부는 변경 불필요하다. `refineToBorder(image, r)` 가 기본값을 사용한다.

### Task 5 — 프론트 테스트 보강

- [ ] `frontend/src/features/webtoon-cut/gridSplitParity.test.ts` 에 Task 2의 Python 테스트와 **같은 픽셀 구성**으로 말풍선 보존 parity 테스트를 추가한다. 두 엔진이 같은 입력에 같은 경계를 내야 한다.
- [ ] `panelBorderCheck.test.ts` 가 `padFrac` 변경으로 깨지는지 확인하고, 깨진다면 원인을 먼저 규명한다. 단언만 바꿔 통과시키지 않는다.
- [ ] `gridSplitParity.test.ts` 44~52행 주석은 page_016 검증을 근거로 들고 있다. Task 3에서 기준값이 바뀌므로 함께 갱신한다.

### Task 6 — 검증

- [ ] `python3 -m compileall -q backend/app`
- [ ] `python3 -m pytest backend/tests -q`
- [ ] `npm --prefix frontend run test:webtoon-cut`
- [ ] `npm run build`
- [ ] `./scripts/verify.sh` (전체 스위트)
- [ ] 실사 회귀 확인: 과학사 2권 16~60쪽을 처리해 **총 214컷 / 0컷 페이지 1쪽** 이 나오는지 대조한다. v1 기준값은 173컷 / 4쪽이다.
- [ ] 산출된 컷 PNG에서 말풍선이 잘리지 않았는지 육안 확인한다. 16쪽처럼 프레임 밖으로 말풍선이 돌출한 페이지를 표본으로 쓴다.

### Task 7 — 배포

- [ ] ECR 이미지 재빌드 후 ECS 재배포. 절차는 `docs/ecr-webtoon-cut-deployment-guide.md` 를 따른다.
- [ ] 배포 후 실제 작업 1건을 돌려 컷 수와 말풍선 보존을 확인한다.
- [ ] 회귀 기간(2026-09-15 15:39 이후) 중 생성된 기존 작업 산출물은 잘린 컷을 포함한다. 재처리 여부를 결정한다.

---

## 4. 재발 방지

- [ ] 실사 회귀 테스트의 기준값은 **육안으로 확인한 정답**이어야 한다. 현재 엔진 출력을 그대로 기준값으로 붙여넣으면 회귀가 정답으로 굳는다. 이번 `ac186e5` 가 정확히 그 경로로 들어왔다.
- [ ] 테스트 이름이 요구사항을 서술하므로, 이름을 뒤집는 변경(`preserves_...` → `keeps_..._instead_of_...`)은 요구사항 변경으로 취급하고 근거를 커밋 메시지에 남긴다.
- [ ] `grid_split.py` 는 vendoring된 외부 엔진이다. 버전 교체 시 커밋 메시지에 **어느 버전에서 어느 버전으로** 바꾸는지와 그 근거를 명시한다. 현재 이력의 `fix ...` 메시지만으로는 v4→v3→v1 다운그레이드가 드러나지 않는다.

---

## 5. 참고 — 엔진 계열 대조표

| | v1 | v3 | v4 |
|---|---|---|---|
| 줄 수 | 312 | 438 | 514 |
| `def` 개수 | 7 | 12 | 16 |
| 거터 검증 (`_has_gutter`) | 없음 | 있음 | 있음 |
| 테두리 굵기 적응 | 없음 | 있음 | 있음 |
| 장식 오검출 방지 (`_looks_like_panel`) | 없음 | 있음 | 있음 |
| 말풍선 돌출 보존 | 없음 | 없음 | **있음** |
| `_refine_to_border` `pad_frac` | 0.03 | 0.03 | **0.06** |
| 2권 16~60쪽 총 컷 | 173 | 214 | 214 |
| 2권 16~60쪽 출력 픽셀 | 144 M | 193 M | 204 M |

복원 대상은 **v4** (`7798bb5`) 다.
