# Webtoon Batch Split Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/Users/changkyuneun/webtoon Pannel/batch_split.py`와 `/Users/changkyuneun/webtoon Pannel/files/grid_split.py`의 검증된 PDF/페이지형 컷 분리 정책을 DOBEDUB STUDIO의 웹툰 컷 분리 기능에서 사용할 수 있게 구성한다.

**Architecture:** 현재 DOBEDUB STUDIO의 웹툰 컷 분리는 브라우저 Web Worker/TypeScript 구조이며, 원본·결과 파일을 ECS로 업로드하지 않는 것이 핵심 요구사항이다. `batch_split.py`는 Python, OpenCV, Poppler, 로컬 파일 경로를 전제로 하므로 브라우저 Worker 안에서 직접 실행할 수 없다. 따라서 단기에는 `batch_split.py`를 저장소 내부의 독립 Python 엔진으로 vendoring하고, 실제 제품 연동은 “로컬 실행 어댑터 또는 데스크톱/로컬 헬퍼”를 통해서만 허용한다. ECS 브라우저 단독 모드는 기존 TypeScript 엔진을 유지하거나 `grid_split.py` 알고리즘을 TypeScript/WASM으로 이식해야 한다.

**Tech Stack:** TypeScript, React, Web Worker, File System Access API, Python 3, OpenCV, Poppler `pdfinfo`/`pdftoppm`, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md`

## Global Constraints

- 서버 업로드/다운로드 없음: 사용자 원본과 결과 컷은 ECS, EFS, S3, RDS로 전송하지 않는다.
- 브라우저 단독 ECS 화면은 사용자의 로컬 절대 경로를 얻을 수 없다.
- `batch_split.py`를 그대로 쓰려면 Python 실행 주체가 사용자 컴퓨터에서 돌아야 한다.
- `batch_split.py`는 PDF 페이지형/격자형 분리 엔진으로 한정한다.
- 세로 웹툰 공백 분리, 강한 수평 장면 전환 검수 재처리, ZIP 정책, 진행 상태 유지, manifest 재개는 기존 `frontend/src/features/webtoon-cut/` 구조를 유지한다.
- 출력 이미지는 모두 PNG다.
- PDF 렌더링은 300dpi다.
- 컷 0개 페이지는 fullpage 1컷으로 저장한다.
- `fullpage`는 검수 대상이 아니라 정상 출력 플래그다.

---

## 0. 결론: 가능한 구성안

### 권장안 A: Python 엔진을 “로컬 헬퍼/데스크톱 앱”으로 연결

이 방식은 `batch_split.py`를 실제 실행 코드로 사용할 수 있다.

```text
ECS 또는 local DOBEDUB 화면
        │
        │ UI/정책/작업 상태
        ▼
브라우저
        │
        │ localhost 또는 desktop bridge
        ▼
사용자 PC의 Python webtoon-cut helper
        │
        ├─ batch_split.py
        ├─ grid_split.py
        ├─ pdftoppm/pdfinfo
        └─ OpenCV
        │
        ▼
사용자 로컬 작업 폴더의 *_cuts
```

장점:

- `/Users/changkyuneun/webtoon Pannel/batch_split.py`의 실제 동작을 거의 그대로 사용한다.
- PDF 인쇄 원본 처리 정확도를 빠르게 가져올 수 있다.
- OpenCV/Poppler 성능을 활용한다.

단점:

- 브라우저가 로컬 절대 경로를 알 수 없으므로, 순수 ECS 웹만으로는 Python에 “이 경로를 처리하라”고 안전하게 지시할 수 없다.
- 사용자가 로컬 헬퍼를 설치/실행해야 한다.
- HTTPS ECS 페이지에서 `127.0.0.1` 헬퍼 호출, CORS, 사용자 승인 UX를 검증해야 한다.

### 대안 B: `grid_split.py` 알고리즘을 TypeScript로 이식

이 방식은 기존 브라우저 로컬 처리 요건과 가장 잘 맞는다.

```text
ECS 또는 local DOBEDUB 화면
        │
        ▼
브라우저 Web Worker
        │
        ├─ grid_split.py 알고리즘을 TypeScript로 이식한 gridDetector
        ├─ pdf.js 렌더링
        ├─ stripDetector
        ├─ transitionDetector
        └─ File System Access API로 *_cuts 저장
```

장점:

- 기존 “업로드/다운로드 없음” 요건과 충돌하지 않는다.
- 사용자는 별도 설치 없이 Chrome/Edge에서 실행한다.
- 작업 handle 유지, manifest 재개, 검수 재처리와 자연스럽게 결합된다.

단점:

- `batch_split.py`를 그대로 쓰는 것이 아니라 알고리즘 재구현이다.
- OpenCV의 morphology/connected component를 TypeScript 또는 OpenCV.js/WASM으로 다시 맞춰야 한다.

### 비권장안 C: ECS 서버에서 Python으로 처리

이 방식은 사용하지 않는다.

이유:

- 사용자의 원본을 ECS로 업로드해야 하므로 확정 요구사항과 충돌한다.
- 결과를 다운로드해야 하므로 “업로드/다운로드 없음”과 충돌한다.
- ECS 컨테이너는 사용자의 Mac 로컬 디렉토리에 접근할 수 없다.

---

## Task 5-추가: grid_split.py의 실제 정확도 버그(_looks_like_panel) 포팅 (2026-09-14 완료)

Task 5는 원래 fullpage 폴백/마진 계산 패리티만 다뤘으나, 그 근본 목적("B안 = grid_split.py 알고리즘을 TS로 이식")을 달성하려면
사용자가 최초 신고한 실제 버그(장식/제목 그림이 컷으로 오인식되는 문제, `_looks_like_panel`/`_region_border_score`)도 포팅해야 함을
발견하여 추가로 진행함.

- Create: `frontend/src/features/webtoon-cut/panelBorderCheck.ts` — `edgeInkScore`/`regionBorderScore`/`looksLikePanel` (Python `_ink_score`/`_region_border_score`/`_looks_like_panel` 포팅)
- Create: `frontend/src/features/webtoon-cut/panelBorderCheck.test.ts` — 3 tests
- Modify: `frontend/src/features/webtoon-cut/gridDetector.ts` — `detectGridCuts`가 `findBorderComponents`로 찾은 연결-성분 바운딩박스 후보에 `looksLikePanel` 필터를 적용하도록 변경. 필터 후 0개면 fullpage 폴백(기존 정책과 동일하게 통일).
- Modify: `frontend/src/features/webtoon-cut/__fixtures__/synthetic.ts` — `decorativeBlob`(마름모 채움, 자체 바운딩박스 엣지 커버리지가 낮은 장식 도형), `fourPanelPageWithDecoration`(실제 4컷 + 장식 도형 혼합) 추가
- Modify: `frontend/src/features/webtoon-cut/gridSplitParity.test.ts` — 장식 도형 단독(→fullpage 폴백), 4컷+장식 혼합(→장식만 제외되고 4컷 그대로) 2개 테스트 추가

**주의(정확한 포팅이 아니라 적응):** Python은 OpenCV 그레이스케일(`cv2.cvtColor` BGR2GRAY) 기준 `v<100 && s<20`을 잉크 판정에 쓰지만,
TS는 이 저장소의 기존 `findBorderComponents` 마스크 기준(`minChannel<80 && chroma<40`)을 그대로 재사용함(두 기준을 따로 두는 것이
불필요한 복잡도라고 판단). search radius도 Python의 절대 12px(300dpi 기준)이 아니라 이미지 크기에 비례한 값(`clamp(round(min(w,h)*0.004), 2, 12)`)으로
스케일링함 — 브라우저에서 렌더링되는 이미지 해상도가 300dpi 인쇄본과 다를 수 있기 때문.

검증: `npx vitest run src/features/webtoon-cut` 17 files / 62 tests 전부 통과(회귀 없음), `npx tsc -b --force` exit 0.

**미검증:** 실제 브라우저에서 진짜 웹툰 PDF 페이지(합성 fixture가 아닌 실사 이미지)로 이 필터를 돌려본 적은 없음 — search radius,
minEdgeScore=0.5, minSides=3 같은 임계값이 실제 이미지에도 잘 맞는지는 확인 필요.

---

## Task 5-추가-2: findBorderComponents(flood-fill) 전면 교체 + 실사 페이지 검증 (2026-09-14 완료)

Task 5-추가에서 만든 `panelBorderCheck.ts`(`looksLikePanel`)만으로는 사용자가 최초 신고한 버그를
근본적으로 고칠 수 없다는 것이 실사 페이지(`webtoon Pannel/_scratch/page_016-016.png`) 테스트에서
드러났다: 기존 `gridDetector.ts`의 `findBorderComponents`는 잉크 픽셀을 통째로 flood-fill해 연결
성분의 바운딩박스를 곧바로 "컷"으로 취급하는데, 장식 삽화의 잉크가 인접한 실제 컷의 테두리선에
픽셀 단위로 맞닿아 있으면 둘이 **하나의 연결성분으로 합쳐진 뒤** `looksLikePanel` 검증에 들어가므로,
검증 시점에는 이미 장식+컷이 하나의 잘못된 사각형으로 굳어져 있어 필터로 되돌릴 수 없었다.

**해결:** `findBorderComponents` 방식을 완전히 버리고, `grid_split.py`의 재귀 분할선 탐색
알고리즘(형태학적 opening으로 "긴 직선 성분"만 추출 → 재귀적 이분(BSP) → `_refine_to_border` →
`_looks_like_panel`)을 그대로 포팅했다. 장식 그림은 긴 직선을 만들지 않으므로 분할선 후보에
기여하지 않고, 그 결과 장식 영역과 실제 컷은 서로 다른 leaf로 자연히 분리된다.

- Create: `frontend/src/features/webtoon-cut/gridSplitEngine.ts` — `get_line_components`,
  `_cluster_and_coverage`, `_has_gutter`, `_line_thickness`, `estimate_border_thickness`,
  `find_best_divider`, `recursive_split`, `_refine_to_border`, 읽기 순서 정렬을 포팅
  (`detectGridRegions`/`orderReadingSequence`/`pageMargin`/`grayValue` export).
- Modify: `frontend/src/features/webtoon-cut/gridDetector.ts` — `findBorderComponents` 기반
  구현을 제거하고 `gridSplitEngine.detectGridRegions`를 호출하도록 전면 교체.
- Modify: `frontend/src/features/webtoon-cut/pixels.ts` — `grayValue`(BT.601, `cv2.cvtColor`와
  동일 가중치)를 공용 헬퍼로 추가.

**잉크 판정 기준 관련 중요한 발견(회귀 조사 과정에서 확인):** Task 5-추가에서 "Python은
`v<100 && s<20`(HSV saturation)을 쓴다"고 적었던 것은 **틀렸다.** `grid_split.py`의
`split_panels()`를 직접 읽어보면:

```python
sat = (img.max(axis=2).astype(np.int16) - img.min(axis=2).astype(np.int16)).astype(np.uint8)
# 주석: "채도 대신 '채널 간 편차(chroma)'를 사용: 거의 순수 검정(예: BGR 0,0,5)은 HSV 채도가
#       255로 튀어 오검출되므로, max(BGR)-min(BGR) 가 작은 무채색 픽셀만 잉크로 인정"
```

즉 `_ink_score`/`_line_thickness`에 넘기는 `sat` 인자는 이름과 달리 **실제로는 HSV saturation이
아니라 chroma(max-min)**이고, `gray_v`는 `cv2.cvtColor(...,COLOR_BGR2GRAY)`(BT.601)다. 진짜 기준은
**`grayValue(BT.601) < 100 && chroma(max-min) < 20`**.

이걸 몰랐을 때 실사 페이지 검증에서 다음이 실측으로 드러났다:
1. TS의 기존 근사 기준(`minChannel<80 && chroma<40`)으로는 page_016의 장식 삽화가 여전히 (병합은
   안 되지만) **독립된 가짜 5번째 컷**으로 통과함 — 코너(페이지 위/오른쪽 여백에 동시에 걸침) leaf라
   `looksLikePanel`의 4면 중 2면만 검사되고, 그 2면이 우연히 0.52/0.641을 받아 통과.
2. "진짜" HSV saturation(`v<100 && s<20`, `cv2.cvtColor(...,COLOR_BGR2HSV)`)으로 바꿔보니 실사
   페이지 3장 모두 **전체 컷이 0개**로 붕괴함 — near-black 픽셀의 미세한 채널 노이즈가 V가 작을 때
   saturation을 크게 튀게 만들어(정확히 Python 주석이 경고한 그 현상) 거의 모든 진짜 테두리 잉크까지
   걸러버림.
3. `grid_split.py` 소스를 다시 읽고서야 (2)가 아니라 `grayValue<100 && chroma<20`이 진짜 기준임을
   확인, 적용. 이 기준으로 실사 페이지 3장을 재검증한 결과는 아래 "실사 페이지 검증" 참고.

- Modify: `frontend/src/features/webtoon-cut/panelBorderCheck.ts` — `edgeInkScore`의 잉크 기준을
  `grayValue<100 && chroma<20`으로 교정(기존 `minChannel<80 && chroma<40` 근사치 폐기).
- Modify: `frontend/src/features/webtoon-cut/gridSplitEngine.ts` — `isInkPixel`(`_line_thickness`
  대응)도 동일 기준으로 교정.

**실사 페이지 검증 (2026-09-14, 300dpi 전체 해상도 2528×3343, 다운스케일 없음):**
`webtoon Pannel/_scratch/page_016-016.png`, `page_026-026.png`, `page_099-099.png` 3장을 RGBA로
변환해 `detectGridCuts`/`detectGridRegions`에 직접 통과시키고, 그 결과를 이미 검증된 Python
프로덕션 출력(`webtoon Pannel/output/.../016-0N.png` 등)의 실제 크기와 대조했다.

| 페이지 | Python 프로덕션 출력 | TS 포팅 결과 | 판정 |
| --- | --- | --- | --- |
| page_016 | 4컷 (872×1037, 938×1072, 957×968, 848×967) | 4컷 (864×1029, 930×1063, 949×960, 840×959) | 일치(±10px, refine 패딩 차이) — **사용자가 신고한 원래 버그(장식이 컷으로 오인식) 해결 확인** |
| page_026 | 5컷 (1033×800, 772×800, 1817×640, 1817×439, 1817×621) | 5컷 (1025×792, 764×792, 1809×631, 1809×431, 1809×613) | 일치 |
| page_099 | **2컷** (2131×888, 1821×1119) | **2컷** (2122×881, 1813×1111) | 일치 — Phase 1(Python 단계)에서 이미 "허용된 기존 한계"로 문서화한 099/192/201의 "위쪽 2컷이 완전히 안 갈라짐" 결함까지 그대로(의도적으로) 재현됨 |

**합성 fixture 회귀 조사:** 위 교정 과정에서 `gridDetector.test.ts`/`gridSplitParity.test.ts`의
기존 2개 테스트가 실패로 바뀌었다(`fourPanelPage` 완전 정렬 2행 사이 거터가 별도 컷으로 잡힘,
장식 마름모가 재귀분할 중 세로선으로 쪼개짐). 이것이 TS 포팅의 결함인지 확인하기 위해
**vendored `grid_split.py` 원본을 동일한 픽셀 구성의 합성 PNG에 직접 실행**했다:

```
fourPanelPage(800,700) 동일 구성 → python 결과 5개 (거터 밴드 89×760 포함, TS와 동일)
fourPanelPageWithDecoration(800,900) 동일 구성 → python 결과 7개 (거터 밴드 1 + 장식 조각 2, TS와 동일)
```

Python 원본도 완전히 동일한 개수·형태를 반환하므로, 이는 TS 포팅의 버그가 아니라 "두 행의 y좌표가
픽셀 단위로 완전히 일치하는" 인위적인 합성 fixture에서 `grid_split.py` 자체가 갖고 있는 기존
한계다. 두 테스트의 기대값을 이 실측 결과에 맞춰 수정했다(주석으로 검증 경위 기록).

- Modify: `frontend/src/features/webtoon-cut/gridDetector.test.ts` — `fourPanelPage` 기대값을
  4개→5개(거터 밴드 leaf 포함)로 수정.
- Modify: `frontend/src/features/webtoon-cut/gridSplitParity.test.ts` — 장식 혼합 테스트 기대값을
  4개→7개로 수정하고, "실제 4컷은 여전히 그 안에 포함되어 있는지"를 별도로 검증하도록 재작성.

검증: `npx vitest run src/features/webtoon-cut` 17 files / 62 tests 전부 통과, `npx tsc -b --force`
exit 0(에러 없음). 실사 페이지 3장 검증 결과는 위 표와 같음.

**주의사항:**
- `panelBorderCheck.ts`의 search radius는 여전히 이미지 크기에 비례한 스케일링
  (`clamp(round(min(w,h)*0.004), 2, 12)`)을 쓴다 — Python의 절대 12px과 정확히 같지는 않다.
  실사 페이지 3장(300dpi, 2528×3343)에서는 이 스케일링이 Python의 절대값과 거의 같은 범위로
  떨어져(10px) 문제가 되지 않았으나, 브라우저 렌더링 해상도가 300dpi와 크게 다른 경우
  재검증이 필요하다.
- 실사 검증은 3페이지(016/026/099)로 한정된다 — 표지/서비스 페이지, 극단적으로 컷이 많은 페이지,
  세로 웹툰(스트립) 형태는 이 엔진 교체의 영향 범위 밖(`stripDetector.ts`가 별도 처리)이라 검증하지
  않았다.
- page_099의 "위쪽 2컷 미분리"는 Python 쪽 기존 한계를 그대로 재현한 것이며, 이번 작업 범위에서는
  고치지 않는다(Phase 1에서 이미 동일하게 보류 결정됨).

---

## 1. 현재 코드와 `batch_split.py`의 역할 분리

### 기존 프로젝트 파일

- `frontend/src/features/webtoon-cut/runner.ts`
  - 작업 단위 순회, manifest/summary 저장, 재개 처리.
- `frontend/src/features/webtoon-cut/worker.ts`
  - Web Worker 진입점.
- `frontend/src/features/webtoon-cut/detector.ts`
  - 입력별 감지 방식 선택.
- `frontend/src/features/webtoon-cut/gridDetector.ts`
  - 현재 TypeScript 페이지형 컷 검출.
- `frontend/src/features/webtoon-cut/stripDetector.ts`
  - 세로 웹툰 공백 분리.
- `frontend/src/features/webtoon-cut/transitionDetector.ts`
  - 검수 화면의 수평 장면 전환 재처리.
- `frontend/src/features/webtoon-cut/inputSources.ts`
  - 파일, 폴더, PDF, ZIP 작업 단위 inventory.
- `frontend/src/features/webtoon-cut/archive.ts`
  - ZIP 항목 처리.
- `frontend/src/features/webtoon-cut/pdf.ts`
  - 브라우저 PDF 렌더링.
- `frontend/src/features/webtoon-cut/artifacts.ts`
  - PNG, manifest, summary 저장.
- `frontend/src/screens/webtoonCutScreen.tsx`
  - DOBEDUB 사용자 화면.

### 참조 엔진 파일

- `/Users/changkyuneun/webtoon Pannel/batch_split.py`
  - PDF 파일 탐색, `pdfinfo` 페이지 수 확인, `pdftoppm -r 300` 페이지 렌더링, `grid_split.split_panels` 적용, summary/debug 생성.
- `/Users/changkyuneun/webtoon Pannel/files/grid_split.py`
  - 실제 페이지형 컷 검출 알고리즘.

### 결론

`batch_split.py`는 전체 웹툰 컷 분리 기능의 대체물이 아니다. PDF/페이지형 격자 컷 분리 품질을 보강하는 엔진으로 편입해야 한다.

---

## Task 1: Python 엔진을 저장소 내부에 vendoring하고 CLI 계약 고정

**Files:**

- Create: `tools/webtoon_panel_engine/README.md`
- Create: `tools/webtoon_panel_engine/webtoon_panel_engine/__init__.py`
- Create: `tools/webtoon_panel_engine/webtoon_panel_engine/grid_split.py`
- Create: `tools/webtoon_panel_engine/webtoon_panel_engine/batch_split.py`
- Create: `tools/webtoon_panel_engine/webtoon_panel_engine/cli.py`
- Create: `tools/webtoon_panel_engine/requirements.txt`
- Create: `tools/webtoon_panel_engine/tests/test_cli_contract.py`

**Interfaces:**

- Consumes:
  - Source files from `/Users/changkyuneun/webtoon Pannel/batch_split.py`
  - Source file from `/Users/changkyuneun/webtoon Pannel/files/grid_split.py`
- Produces:
  - CLI command:

```bash
python -m webtoon_panel_engine.cli split-pdf \
  --input-root <input_root> \
  --output-root <output_root> \
  --dpi 300 \
  --pages 1-10
```

  - Output contract:

```text
<output_root>/<relative_pdf_stem>/
├── PPP-CC.png
├── summary.csv
└── _debug/
    └── PPP.png
```

- [ ] **Step 1: Copy the verified engine files**

Copy:

```text
/Users/changkyuneun/webtoon Pannel/batch_split.py
→ tools/webtoon_panel_engine/webtoon_panel_engine/batch_split.py

/Users/changkyuneun/webtoon Pannel/files/grid_split.py
→ tools/webtoon_panel_engine/webtoon_panel_engine/grid_split.py
```

- [ ] **Step 2: Refactor imports**

Change the copied `batch_split.py` import from:

```python
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "files"))
import cv2
from grid_split import split_panels
```

to:

```python
import cv2
from .grid_split import split_panels
```

- [ ] **Step 3: Add a stable CLI wrapper**

Create `tools/webtoon_panel_engine/webtoon_panel_engine/cli.py`:

```python
from __future__ import annotations

import argparse

from .batch_split import process_pdf


def parse_pages(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    left, right = value.split("-", 1)
    return int(left), int(right)


def main() -> None:
    parser = argparse.ArgumentParser(prog="webtoon-panel-engine")
    sub = parser.add_subparsers(dest="command", required=True)

    split_pdf = sub.add_parser("split-pdf")
    split_pdf.add_argument("--input-pdf", required=True)
    split_pdf.add_argument("--output-dir", required=True)
    split_pdf.add_argument("--pages")
    split_pdf.add_argument("--dpi", type=int, default=300)

    args = parser.parse_args()
    if args.command == "split-pdf":
        process_pdf(
            pdf=args.input_pdf,
            out_dir=args.output_dir,
            pages=parse_pages(args.pages),
            dpi=args.dpi,
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the CLI contract test**

Create `tools/webtoon_panel_engine/tests/test_cli_contract.py`:

```python
from webtoon_panel_engine.cli import parse_pages


def test_parse_pages_none():
    assert parse_pages(None) is None


def test_parse_pages_range():
    assert parse_pages("16-40") == (16, 40)
```

- [ ] **Step 5: Run the test**

Run:

```bash
cd tools/webtoon_panel_engine
python -m pytest tests/test_cli_contract.py -q
```

Expected:

```text
2 passed
```

---

## Task 2: Python 엔진 출력 형식을 DOBEDUB manifest 형식으로 변환하는 어댑터 정의

**Files:**

- Create: `tools/webtoon_panel_engine/webtoon_panel_engine/manifest_adapter.py`
- Create: `tools/webtoon_panel_engine/tests/test_manifest_adapter.py`

**Interfaces:**

- Consumes:
  - Python engine `summary.csv` columns: `page,panels,mode,flag,elapsed_s`
  - Output files: `PPP-CC.png`
- Produces:
  - DOBEDUB-compatible summary rows:

```text
unit_id,source_path,page,cut,filename,mode,x0,y0,x1,y1,width,height,confidence,flag,elapsed_ms,status,error
```

- [ ] **Step 1: Write the failing adapter test**

Create `tools/webtoon_panel_engine/tests/test_manifest_adapter.py`:

```python
from webtoon_panel_engine.manifest_adapter import unit_id_for_pdf_page


def test_unit_id_for_pdf_page_uses_relative_path_and_page():
    assert unit_id_for_pdf_page("book/과학사_1권.pdf", 16) == "pdf-page:book/과학사_1권.pdf:16"
```

- [ ] **Step 2: Implement the adapter function**

Create `tools/webtoon_panel_engine/webtoon_panel_engine/manifest_adapter.py`:

```python
from __future__ import annotations

import unicodedata


def normalize_path(path: str) -> str:
    return unicodedata.normalize("NFC", path).replace("\\", "/").strip("/")


def unit_id_for_pdf_page(relative_pdf_path: str, page: int) -> str:
    return f"pdf-page:{normalize_path(relative_pdf_path)}:{page}"
```

- [ ] **Step 3: Run the adapter test**

Run:

```bash
cd tools/webtoon_panel_engine
python -m pytest tests/test_manifest_adapter.py -q
```

Expected:

```text
1 passed
```

---

## Task 3: 제품 연동 방식을 명시적으로 분기한다

**Files:**

- Modify: `docs/superpowers/specs/2026-09-11-webtoon-cut-design.md`
- Modify: `frontend/src/features/webtoon-cut/types.ts`
- Modify: `frontend/src/features/webtoon-cut/constants.ts`
- Test: `frontend/src/features/webtoon-cut/constants.test.ts`

**Interfaces:**

- Produces:

```ts
export type WebtoonCutExecutionBackend = "browser-worker" | "local-python-helper";
```

- [ ] **Step 1: Add an execution backend type**

Modify `frontend/src/features/webtoon-cut/types.ts`:

```ts
export type WebtoonCutExecutionBackend = "browser-worker" | "local-python-helper";
```

- [ ] **Step 2: Keep the default backend as browser-worker**

Modify `frontend/src/features/webtoon-cut/constants.ts`:

```ts
export const WEBTOON_CUT_DEFAULT_BACKEND = "browser-worker" as const;
```

- [ ] **Step 3: Add a test that prevents accidental ECS server processing**

Modify `frontend/src/features/webtoon-cut/constants.test.ts`:

```ts
import { WEBTOON_CUT_DEFAULT_BACKEND } from "./constants";

test("webtoon cut default backend stays browser-local", () => {
  expect(WEBTOON_CUT_DEFAULT_BACKEND).toBe("browser-worker");
});
```

- [ ] **Step 4: Run the frontend test**

Run:

```bash
cd frontend
npm test -- webtoon-cut/constants.test.ts
```

Expected:

```text
PASS frontend/src/features/webtoon-cut/constants.test.ts
```

---

## Task 4: 로컬 Python helper 사용 시 UX와 권한 계약을 추가한다

**Files:**

- Modify: `frontend/src/screens/webtoonCutScreen.tsx`
- Create: `frontend/src/features/webtoon-cut/localPythonHelper.ts`
- Create: `frontend/src/features/webtoon-cut/localPythonHelper.test.ts`

**Interfaces:**

- Consumes:

```ts
type LocalPythonHelperStatus = {
  available: boolean;
  version: string | null;
  engine: "batch_split.py" | null;
};
```

- Produces:
  - 화면 문구:

```text
Python 로컬 헬퍼는 사용자 PC에서 실행 중일 때만 사용할 수 있습니다.
ECS는 원본 또는 결과 파일을 받지 않습니다.
브라우저 단독 모드는 기존 Web Worker 엔진으로 처리합니다.
```

- [ ] **Step 1: Write the helper status test**

Create `frontend/src/features/webtoon-cut/localPythonHelper.test.ts`:

```ts
import { isLocalHelperAvailable } from "./localPythonHelper";

test("local helper unavailable status is explicit", () => {
  expect(isLocalHelperAvailable({ available: false, version: null, engine: null })).toBe(false);
});
```

- [ ] **Step 2: Implement helper status utility**

Create `frontend/src/features/webtoon-cut/localPythonHelper.ts`:

```ts
export type LocalPythonHelperStatus = {
  available: boolean;
  version: string | null;
  engine: "batch_split.py" | null;
};

export function isLocalHelperAvailable(status: LocalPythonHelperStatus): boolean {
  return status.available && status.engine === "batch_split.py" && Boolean(status.version);
}
```

- [ ] **Step 3: Add screen copy without changing default behavior**

Modify `frontend/src/screens/webtoonCutScreen.tsx` so the screen states:

```text
기본 처리: 브라우저 Web Worker
PDF 페이지형 보강 엔진: 로컬 Python helper 연결 시 batch_split.py 사용 가능
```

The existing `작업 요청` flow must still use `browser-worker` unless the helper is explicitly available and selected by an internal feature flag.

- [ ] **Step 4: Run tests**

Run:

```bash
cd frontend
npm test -- webtoon-cut/localPythonHelper.test.ts
```

Expected:

```text
PASS frontend/src/features/webtoon-cut/localPythonHelper.test.ts
```

---

## Task 5: 브라우저 단독 모드에서는 `grid_split.py` 알고리즘 이식 방향을 고정한다

**Files:**

- Modify: `frontend/src/features/webtoon-cut/gridDetector.ts`
- Modify: `frontend/src/features/webtoon-cut/gridDetector.test.ts`
- Create: `frontend/src/features/webtoon-cut/gridSplitParity.test.ts`

**Interfaces:**

- Consumes:
  - `grid_split.py` concepts:
    - 3% outer margin
    - low brightness and low chroma ink mask
    - horizontal/vertical line components
    - clustered coverage
    - gutter validation
    - estimated border thickness
    - recursive split depth 8
    - min area ratio 0.02
    - content ratio 0.03
- Produces:
  - `detectGridCuts(image: ImageData): DetectedCut[]`
  - The function must never return zero cuts; if no panel is detected, it returns one `fullpage` cut.

- [x] **Step 1: Add a parity test for fullpage fallback** — 완료 (2026-09-14). `gridSplitParity.test.ts` 추가, `makeSolidImage` 대신 기존 `blankImage` fixture 재사용.

Create `frontend/src/features/webtoon-cut/gridSplitParity.test.ts`:

```ts
import { detectGridCuts } from "./gridDetector";
import { makeSolidImage } from "./__fixtures__/synthetic";

test("grid detector returns fullpage fallback when no bordered panels exist", () => {
  const image = makeSolidImage(1000, 1400, [255, 255, 255, 255]);
  const cuts = detectGridCuts(image);
  expect(cuts).toHaveLength(1);
  expect(cuts[0].mode).toBe("fullpage");
  expect(cuts[0].flags).toContain("fullpage");
  expect(cuts[0].flags).not.toContain("review_required");
});
```

- [x] **Step 2: Add a parity test for outer margin** — 완료 (2026-09-14).

Add to `gridSplitParity.test.ts`:

```ts
test("fullpage fallback removes the 3 percent print margin", () => {
  const image = makeSolidImage(1000, 2000, [255, 255, 255, 255]);
  const [cut] = detectGridCuts(image);
  expect(cut.x0).toBe(30);
  expect(cut.y0).toBe(60);
  expect(cut.x1).toBe(970);
  expect(cut.y1).toBe(1940);
});
```

- [x] **Step 3: Implement missing parity behavior** — 코드 변경 불필요 확인 (2026-09-14). 기존 `gridDetector.ts`의 `fullpageCut()`이 이미 `PAGE_POLICY.outerMarginRatio=0.03` 기준으로 동일한 마진 계산을 하고 있어 Step1/2 테스트가 코드 수정 없이 통과함.

Modify `frontend/src/features/webtoon-cut/gridDetector.ts` so fullpage fallback is:

```ts
{
  index: 1,
  mode: "fullpage",
  x0: Math.round(image.width * 0.03),
  y0: Math.round(image.height * 0.03),
  x1: Math.round(image.width * 0.97),
  y1: Math.round(image.height * 0.97),
  confidence: 0.5,
  flags: ["fullpage"]
}
```

- [x] **Step 4: Run the grid parity tests** — 완료 (2026-09-14). `npx vitest run` 4/4 통과, `webtoon-cut` 전체 스위트 16 files/57 tests 통과, `npx tsc -b --force` 통과.

Run:

```bash
cd frontend
npm test -- webtoon-cut/gridSplitParity.test.ts webtoon-cut/gridDetector.test.ts
```

Expected:

```text
PASS frontend/src/features/webtoon-cut/gridSplitParity.test.ts
PASS frontend/src/features/webtoon-cut/gridDetector.test.ts
```

---

## Task 6: 의사결정 체크포인트

Before implementing product integration, ask the product owner to choose one:

### Choice 1: Keep ECS/browser-only as the product path

Use `batch_split.py` only as reference. Port `grid_split.py` behavior into TypeScript or OpenCV.js/WASM. This preserves the existing requirement:

```text
입력/출력 파일은 사용자 로컬 디렉토리 사용
서버사이드에서는 실행 코드만 관리
업로드와 다운로드 없음
```

### Choice 2: Add a local helper/desktop runtime

Use `batch_split.py` as real Python execution code. This requires one of:

- Electron/Tauri desktop bridge, or
- user-started local Python helper on `127.0.0.1`, or
- local FastAPI-only mode where the user explicitly gives a local path to the helper.

This must be presented to users as:

```text
Python 로컬 헬퍼 사용 시 파일 처리는 사용자 PC에서 실행됩니다.
ECS는 원본·결과 파일을 받지 않습니다.
```

### Choice 3: Server-side processing

Reject this choice unless the upload/download prohibition changes.

---

## Self-review

- Spec coverage: The plan preserves no ECS upload/download, PNG output, PDF 300dpi, fullpage fallback, manifest compatibility, and local-only processing constraints.
- Placeholder scan: No implementation step relies on TBD behavior. The only explicit decision point is whether the product path remains browser-only or adds a local helper.
- Type consistency: The proposed `WebtoonCutExecutionBackend`, `LocalPythonHelperStatus`, and CLI command names are defined before use.

