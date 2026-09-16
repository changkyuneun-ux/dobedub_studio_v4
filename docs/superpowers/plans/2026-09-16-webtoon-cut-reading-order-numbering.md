# Webtoon Cut Reading Order Numbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every generated webtoon cut filename and `cut_index` follows visual reading order: top-to-bottom, and within the same visual row left-to-right.

**Architecture:** Add a small canonical reading-order utility in both backend and frontend webtoon-cut code paths, then apply it after detection and before assigning final indexes/file names. The detector geometry itself must not change; only ordering and index assignment are normalized at the boundary where cuts become persisted outputs.

**Tech Stack:** Python/FastAPI backend, OpenCV-backed server cut engine, React/Vite/Vitest frontend local cut engine, Pytest.

**Spec:** User request from 2026-09-16: separated cut numbering must match image position order, top-to-bottom, and when multiple cuts exist in one horizontal area, left-to-right.

## Global Constraints

- Do not change actual panel detection/cropping geometry unless a test proves ordering cannot be fixed without it.
- Do not change backend database schema, Alembic migrations, Docker dependencies, S3 storage layout, or API response shape.
- Keep existing naming policy: `001-01.png`, `001-02.png`, etc. Only ensure the numeric suffix maps to visual order.
- For ZIP inputs containing multiple numbered source images, each source image keeps its own local cut sequence. Example: `001.jpg`, `002.jpg` must produce `001/001-01.png`, `001/001-02.png`, ... then `002/002-01.png`, `002/002-02.png`, not a global sequence such as `001-01`, `002-02`, `003-03` and not an interleaved listing such as `001-01`, `002-01`, `001-02`.
- Must cover both server pipeline (`backend/app/services/webtoon_panel_engine`) and browser-local pipeline (`frontend/src/features/webtoon-cut`) because both can generate numbered cut outputs.
- Reading order definition:
  - Primary order: visual row top-to-bottom.
  - Within a row: left-to-right.
  - Row grouping must tolerate panels with slightly different `y0` values but similar vertical center/overlap.
  - Staggered/overlapping panels should still be deterministic and not randomly change between runs.
- Output `cut_index`, output file name, DB `WebtoonCutOutput.cut_index`, manifest `outputs[*].path`, and summary CSV `cut` must all agree within the same source image/page. History queries, selected-cut downloads, and I2V handoff payloads must order outputs by canonical display path so ZIP image sources are grouped by original image sequence before their local cut sequence.
- Add failing tests before production edits.
- Run focused tests first, then `./scripts/verify.sh`.
- Commit/deploy only when explicitly requested after implementation.

---

## Current Code Map

- Backend detection/runtime:
  - `backend/app/services/webtoon_panel_engine/runtime.py`
    - Calls `split_panels(...)`
    - Receives saved `panel_XX.png` paths
    - Assigns `CutResult.cut_index`
    - Moves panel files to `panel-XX.png`
  - `backend/app/services/webtoon_panel_engine/grid_split.py`
    - Already has an inline “읽기 순서 정렬” block near the end.
    - Risk: ordering logic is local to grid split only.
  - `backend/app/services/webtoon_panel_engine/dark_bg_split.py`
    - Currently writes panels in `detect_panels(...)` return order.
    - Risk: recursive `xy_cut` can return spatially valid boxes in an order that is not guaranteed as a formal contract.
  - `backend/app/services/webtoon_cut_worker.py`
    - Stores `CutResult.cut_index` into S3 relative path and DB.
  - `backend/app/services/webtoon_cut_naming.py`
    - Converts `cut_index` into filename suffix.

- Frontend local detection/runtime:
  - `frontend/src/features/webtoon-cut/gridSplitEngine.ts`
    - Exports `orderReadingSequence(regions)`.
  - `frontend/src/features/webtoon-cut/gridDetector.ts`
    - Applies `orderReadingSequence(...)` before assigning `DetectedCut.index`.
  - `frontend/src/features/webtoon-cut/darkBgSplitEngine.ts`
    - `detectPanels(...)` returns filtered boxes without explicitly applying shared reading order.
  - `frontend/src/features/webtoon-cut/detector.ts`
    - Dark mode maps returned boxes directly to `DetectedCut.index`.
  - `frontend/src/features/webtoon-cut/runner.ts`
    - Uses `cut.index` to generate output filename and summary CSV.

---

### Task 1: Backend Canonical Reading Order Utility

**Files:**
- Create: `backend/app/services/webtoon_panel_engine/reading_order.py`
- Test: `backend/tests/test_webtoon_panel_reading_order.py`

**Interfaces:**
- Produces:
  - `type Box = tuple[int, int, int, int]`
  - `def order_reading_sequence(boxes: Iterable[Box]) -> list[Box]`
- Consumes: plain `(x0, y0, x1, y1)` boxes from grid/dark split modules.

- [ ] **Step 1: Write failing utility tests**

Create `backend/tests/test_webtoon_panel_reading_order.py`:

```python
from __future__ import annotations


def test_reading_order_sorts_vertical_stack_top_to_bottom():
    from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

    boxes = [
        (30, 420, 230, 520),
        (20, 40, 220, 140),
        (25, 230, 225, 330),
    ]

    assert order_reading_sequence(boxes) == [
        (20, 40, 220, 140),
        (25, 230, 225, 330),
        (30, 420, 230, 520),
    ]


def test_reading_order_sorts_same_row_left_to_right_before_next_row():
    from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

    boxes = [
        (500, 470, 850, 900),   # bottom-right, should be 5
        (80, 40, 420, 180),     # top-left, should be 1
        (460, 40, 800, 180),    # top-right, should be 2
        (70, 220, 820, 380),    # middle full-width, should be 3
        (70, 470, 420, 900),    # bottom-left, should be 4
    ]

    assert order_reading_sequence(boxes) == [
        (80, 40, 420, 180),
        (460, 40, 800, 180),
        (70, 220, 820, 380),
        (70, 470, 420, 900),
        (500, 470, 850, 900),
    ]


def test_reading_order_groups_slightly_staggered_same_row_by_vertical_overlap():
    from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

    boxes = [
        (260, 70, 470, 240),
        (20, 40, 230, 210),
        (25, 300, 460, 440),
    ]

    assert order_reading_sequence(boxes) == [
        (20, 40, 230, 210),
        (260, 70, 470, 240),
        (25, 300, 460, 440),
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest backend/tests/test_webtoon_panel_reading_order.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `order_reading_sequence`.

- [ ] **Step 3: Implement the backend utility**

Create `backend/app/services/webtoon_panel_engine/reading_order.py`:

```python
from __future__ import annotations

from typing import Iterable, TypeAlias

Box: TypeAlias = tuple[int, int, int, int]


def order_reading_sequence(boxes: Iterable[Box]) -> list[Box]:
    """Return boxes in visual reading order: rows top-to-bottom, each row left-to-right."""
    sorted_boxes = sorted(list(boxes), key=lambda box: (box[1], box[0], box[3], box[2]))
    rows: list[list[Box]] = []
    for box in sorted_boxes:
        placed = False
        for row in rows:
            if _same_visual_row(box, row):
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])

    ordered: list[Box] = []
    rows.sort(key=lambda row: min(box[1] for box in row))
    for row in rows:
        row.sort(key=lambda box: (box[0], box[1], box[2], box[3]))
        ordered.extend(row)
    return ordered


def _same_visual_row(box: Box, row: list[Box]) -> bool:
    row_y0 = min(item[1] for item in row)
    row_y1 = max(item[3] for item in row)
    box_y0, box_y1 = box[1], box[3]
    overlap = max(0, min(box_y1, row_y1) - max(box_y0, row_y0))
    box_height = max(1, box_y1 - box_y0)
    row_height = max(1, row_y1 - row_y0)
    center_delta = abs(((box_y0 + box_y1) / 2) - ((row_y0 + row_y1) / 2))
    return overlap >= min(box_height, row_height) * 0.35 or center_delta < min(box_height, row_height) * 0.5
```

- [ ] **Step 4: Run backend utility tests**

Run:

```bash
python3 -m pytest backend/tests/test_webtoon_panel_reading_order.py -q
```

Expected: PASS.

---

### Task 2: Apply Backend Ordering Before File Naming

**Files:**
- Modify: `backend/app/services/webtoon_panel_engine/runtime.py`
- Modify: `backend/app/services/webtoon_panel_engine/dark_bg_split.py`
- Modify: `backend/app/services/webtoon_panel_engine/grid_split.py`
- Test: `backend/tests/test_webtoon_panel_grid_split.py`

**Interfaces:**
- Consumes: `order_reading_sequence(boxes)` from Task 1.
- Produces: `RenderedUnitResult.cuts` whose `cut_index` values always match visual order.

- [ ] **Step 1: Add failing runtime-level tests**

Append to `backend/tests/test_webtoon_panel_grid_split.py`:

```python
def test_runtime_reindexes_split_outputs_by_visual_reading_order(tmp_path, monkeypatch):
    from backend.app.services.webtoon_panel_engine import dark_bg_split
    from backend.app.services.webtoon_panel_engine.runtime import process_image_file

    source = tmp_path / "source.png"
    image = np.full((520, 900, 3), 20, dtype=np.uint8)
    cv2.imwrite(str(source), image)

    def write_panel(out_dir: str, name: str, shape: tuple[int, int]) -> str:
        path = Path(out_dir) / name
        height, width = shape
        cv2.imwrite(str(path), np.full((height, width, 3), 180, dtype=np.uint8))
        return str(path)

    def fake_split_panels(image_path: str, out_dir: str, debug: bool = False):
        assert Path(image_path).name == "source.png"
        return [
            write_panel(out_dir, "panel_05__x500_y470.png", (430, 350)),
            write_panel(out_dir, "panel_01__x080_y040.png", (140, 340)),
            write_panel(out_dir, "panel_02__x460_y040.png", (140, 340)),
            write_panel(out_dir, "panel_03__x070_y220.png", (160, 750)),
            write_panel(out_dir, "panel_04__x070_y470.png", (430, 350)),
        ]

    monkeypatch.setattr(dark_bg_split, "split_panels", fake_split_panels, raising=False)

    result = process_image_file(source, output_dir=tmp_path / "out", split_mode="dark-webtoon")

    assert [cut.cut_index for cut in result.cuts] == [1, 2, 3, 4, 5]
    assert [cut.path.name for cut in result.cuts] == [
        "panel-01.png",
        "panel-02.png",
        "panel-03.png",
        "panel-04.png",
        "panel-05.png",
    ]
```

This test intentionally forces an unsorted source list. If the runtime cannot infer geometry from returned files, the implementation must instead ensure `split_panels(...)` returns ordered paths. If this test design is too synthetic for current interfaces, replace it with engine-level tests in the next step and keep runtime reindexing as a sanity check.

- [ ] **Step 2: Add engine-level dark background ordering test**

Append to `backend/tests/test_webtoon_panel_grid_split.py`:

```python
def test_dark_background_split_names_panels_by_reading_order(tmp_path):
    from backend.app.services.webtoon_panel_engine.dark_bg_split import split_panels

    source = tmp_path / "dark-layout.png"
    image = np.full((960, 900, 3), 20, dtype=np.uint8)
    panels = [
        ((80, 40), (420, 180)),
        ((460, 40), (800, 180)),
        ((70, 220), (820, 380)),
        ((70, 470), (420, 900)),
        ((500, 470), (850, 900)),
    ]
    for index, (a, b) in enumerate(panels, start=1):
        cv2.rectangle(image, a, b, (235, 235, 235), -1)
        cv2.putText(image, str(index), (a[0] + 30, a[1] + 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    cv2.imwrite(str(source), image)

    saved = split_panels(str(source), str(tmp_path / "out"), debug=True)

    assert [Path(path).name for path in saved] == [
        "panel_01.png",
        "panel_02.png",
        "panel_03.png",
        "panel_04.png",
        "panel_05.png",
    ]
```

- [ ] **Step 3: Run targeted tests and verify failure if current dark ordering is not guaranteed**

Run:

```bash
python3 -m pytest backend/tests/test_webtoon_panel_grid_split.py::test_dark_background_split_names_panels_by_reading_order -q
```

Expected before implementation: PASS or FAIL depending on current recursive order. If it passes, keep the test as a contract test and still implement explicit ordering to remove hidden dependency on recursion order.

- [ ] **Step 4: Apply `order_reading_sequence` in backend engines**

Modify `backend/app/services/webtoon_panel_engine/dark_bg_split.py`:

```python
from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence
```

Then in `split_panels(...)`, immediately after `boxes, _ = detect_panels(gray)`:

```python
    boxes = order_reading_sequence(tuple(map(int, box)) for box in boxes)
```

Modify `backend/app/services/webtoon_panel_engine/grid_split.py` to replace its inline final ordering block with:

```python
    from backend.app.services.webtoon_panel_engine.reading_order import order_reading_sequence

    ordered = order_reading_sequence(regions)
```

Do not change the `regions` detection/filter/refine logic.

- [ ] **Step 5: Keep runtime sequential renaming as final guard**

Modify `backend/app/services/webtoon_panel_engine/runtime.py` to ensure runtime always treats the ordered list as the single source of truth:

```python
        saved = [Path(path) for path in split_panels(str(image_path), str(panel_tmp), debug=True)]
```

No interface change is required if engines return ordered paths. Keep this runtime loop:

```python
        for index, source in enumerate(saved, start=1):
            target = output_dir / f"panel-{index:02d}.png"
            ...
            cuts.append(CutResult(path=target, cut_index=index, width=width, height=height, flags=cut_flags))
```

If runtime-level test from Step 1 cannot be made reliable because filenames do not encode geometry, remove that synthetic test and rely on engine-level tests plus worker storage tests.

- [ ] **Step 6: Add worker storage contract test**

Append to `backend/tests/test_webtoon_cut_worker.py`:

```python
def test_store_result_uses_cut_index_for_visual_ordered_output_names(db_session, tmp_path, monkeypatch):
    from backend.app.services import webtoon_cut_worker

    db_session.add(_running_job("wcut_order_test"))
    db_session.commit()

    first = tmp_path / "panel-01.png"
    second = tmp_path / "panel-02.png"
    first.write_bytes(b"png1")
    second.write_bytes(b"png2")

    result = RenderedUnitResult(
        page_number=7,
        cuts=[
            CutResult(path=first, cut_index=1, width=100, height=100, flags=[]),
            CutResult(path=second, cut_index=2, width=100, height=100, flags=[]),
        ],
        debug_overlay_path=None,
        mode="dark_bg",
        flags=[],
    )

    monkeypatch.setattr(webtoon_cut_worker, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(webtoon_cut_worker, "s3_asset_storage", lambda: _FakeStorage())

    webtoon_cut_worker._store_result("wcut_order_test", result, source_stem="source")

    outputs = db_session.query(WebtoonCutOutput).filter_by(job_id="wcut_order_test").order_by(WebtoonCutOutput.cut_index).all()
    assert [output.display_path for output in outputs] == [
        "source/007-01.png",
        "source/007-02.png",
    ]
```

Adjust imports if `WebtoonCutOutput`, `CutResult`, or `RenderedUnitResult` are already imported in the test file.

- [ ] **Step 7: Run backend focused tests**

Run:

```bash
python3 -m pytest \
  backend/tests/test_webtoon_panel_reading_order.py \
  backend/tests/test_webtoon_panel_grid_split.py \
  backend/tests/test_webtoon_cut_worker.py \
  -q
```

Expected: PASS.

---

### Task 3: Frontend Canonical Reading Order Utility

**Files:**
- Create: `frontend/src/features/webtoon-cut/readingOrder.ts`
- Modify: `frontend/src/features/webtoon-cut/gridSplitEngine.ts`
- Modify: `frontend/src/features/webtoon-cut/darkBgSplitEngine.ts`
- Modify: `frontend/src/features/webtoon-cut/gridDetector.ts`
- Modify: `frontend/src/features/webtoon-cut/detector.ts`
- Test: `frontend/src/features/webtoon-cut/readingOrder.test.ts`
- Test: `frontend/src/features/webtoon-cut/darkBgSplitEngine.test.ts`
- Test: `frontend/src/features/webtoon-cut/gridDetector.test.ts`

**Interfaces:**
- Produces:
  - `export function orderReadingSequence<T extends PixelRegion>(regions: readonly T[]): T[]`
- Consumes: `PixelRegion` from `types.ts`.

- [ ] **Step 1: Write frontend reading-order tests**

Create `frontend/src/features/webtoon-cut/readingOrder.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { orderReadingSequence } from "./readingOrder";
import type { PixelRegion } from "./types";

describe("webtoon cut reading order", () => {
  it("sorts vertical stack top-to-bottom", () => {
    const boxes: PixelRegion[] = [
      { x0: 30, y0: 420, x1: 230, y1: 520 },
      { x0: 20, y0: 40, x1: 220, y1: 140 },
      { x0: 25, y0: 230, x1: 225, y1: 330 }
    ];

    expect(orderReadingSequence(boxes)).toEqual([
      { x0: 20, y0: 40, x1: 220, y1: 140 },
      { x0: 25, y0: 230, x1: 225, y1: 330 },
      { x0: 30, y0: 420, x1: 230, y1: 520 }
    ]);
  });

  it("sorts same visual row left-to-right before lower rows", () => {
    const boxes: PixelRegion[] = [
      { x0: 500, y0: 470, x1: 850, y1: 900 },
      { x0: 80, y0: 40, x1: 420, y1: 180 },
      { x0: 460, y0: 40, x1: 800, y1: 180 },
      { x0: 70, y0: 220, x1: 820, y1: 380 },
      { x0: 70, y0: 470, x1: 420, y1: 900 }
    ];

    expect(orderReadingSequence(boxes)).toEqual([
      { x0: 80, y0: 40, x1: 420, y1: 180 },
      { x0: 460, y0: 40, x1: 800, y1: 180 },
      { x0: 70, y0: 220, x1: 820, y1: 380 },
      { x0: 70, y0: 470, x1: 420, y1: 900 },
      { x0: 500, y0: 470, x1: 850, y1: 900 }
    ]);
  });

  it("groups slightly staggered same-row panels by overlap/center tolerance", () => {
    const boxes: PixelRegion[] = [
      { x0: 260, y0: 70, x1: 470, y1: 240 },
      { x0: 20, y0: 40, x1: 230, y1: 210 },
      { x0: 25, y0: 300, x1: 460, y1: 440 }
    ];

    expect(orderReadingSequence(boxes)).toEqual([
      { x0: 20, y0: 40, x1: 230, y1: 210 },
      { x0: 260, y0: 70, x1: 470, y1: 240 },
      { x0: 25, y0: 300, x1: 460, y1: 440 }
    ]);
  });
});
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
npm --prefix frontend test -- src/features/webtoon-cut/readingOrder.test.ts
```

Expected: FAIL with missing module/function.

- [ ] **Step 3: Implement frontend utility**

Create `frontend/src/features/webtoon-cut/readingOrder.ts`:

```ts
import type { PixelRegion } from "./types";

export function orderReadingSequence<T extends PixelRegion>(regions: readonly T[]): T[] {
  const sorted = [...regions].sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0 || a.y1 - b.y1 || a.x1 - b.x1);
  const rows: T[][] = [];
  for (const region of sorted) {
    let placed = false;
    for (const row of rows) {
      if (sameVisualRow(region, row)) {
        row.push(region);
        placed = true;
        break;
      }
    }
    if (!placed) rows.push([region]);
  }
  rows.sort((a, b) => Math.min(...a.map((item) => item.y0)) - Math.min(...b.map((item) => item.y0)));
  return rows.flatMap((row) => row.sort((a, b) => a.x0 - b.x0 || a.y0 - b.y0 || a.x1 - b.x1 || a.y1 - b.y1));
}

function sameVisualRow(region: PixelRegion, row: readonly PixelRegion[]) {
  const rowY0 = Math.min(...row.map((item) => item.y0));
  const rowY1 = Math.max(...row.map((item) => item.y1));
  const overlap = Math.max(0, Math.min(region.y1, rowY1) - Math.max(region.y0, rowY0));
  const regionHeight = Math.max(1, region.y1 - region.y0);
  const rowHeight = Math.max(1, rowY1 - rowY0);
  const centerDelta = Math.abs((region.y0 + region.y1) / 2 - (rowY0 + rowY1) / 2);
  return overlap >= Math.min(regionHeight, rowHeight) * 0.35 || centerDelta < Math.min(regionHeight, rowHeight) * 0.5;
}
```

- [ ] **Step 4: Replace old grid export with shared utility**

Modify `frontend/src/features/webtoon-cut/gridSplitEngine.ts`:

```ts
import { orderReadingSequence } from "./readingOrder";
export { orderReadingSequence };
```

Remove the old local `orderReadingSequence` implementation at the bottom of `gridSplitEngine.ts`.

Modify `frontend/src/features/webtoon-cut/gridDetector.ts` to import from `readingOrder` instead of `gridSplitEngine`:

```ts
import { orderReadingSequence } from "./readingOrder";
import { detectGridRegions, pageMargin } from "./gridSplitEngine";
```

- [ ] **Step 5: Apply ordering in dark background frontend path**

Modify `frontend/src/features/webtoon-cut/darkBgSplitEngine.ts`:

```ts
import { orderReadingSequence } from "./readingOrder";
```

In `detectPanels(...)`, change:

```ts
    boxes: filtered.boxes,
```

to:

```ts
    boxes: orderReadingSequence(filtered.boxes),
```

This ensures `detector.ts` can continue assigning `index + 1` from the returned order.

- [ ] **Step 6: Add frontend dark-mode layout test matching user example**

Append to `frontend/src/features/webtoon-cut/darkBgSplitEngine.test.ts`:

```ts
  it("orders mixed dark webtoon layout top-to-bottom and left-to-right within each row", () => {
    const image = blankImage(900, 960, [20, 20, 20]);
    drawPanel(image, { x0: 80, y0: 40, x1: 420, y1: 180 });
    drawPanel(image, { x0: 460, y0: 40, x1: 800, y1: 180 });
    drawPanel(image, { x0: 70, y0: 220, x1: 820, y1: 380 });
    drawPanel(image, { x0: 70, y0: 470, x1: 420, y1: 900 });
    drawPanel(image, { x0: 500, y0: 470, x1: 850, y1: 900 });

    const cuts = detectCuts(image, "auto", "image", "dark-webtoon");

    expect(cuts.map(({ index, x0, y0, x1, y1 }) => [index, x0, y0, x1, y1])).toEqual([
      [1, 80, 40, 420, 180],
      [2, 460, 40, 800, 180],
      [3, 70, 220, 820, 380],
      [4, 70, 470, 420, 900],
      [5, 500, 470, 850, 900]
    ]);
  });
```

- [ ] **Step 7: Run frontend focused tests**

Run:

```bash
npm --prefix frontend test -- \
  src/features/webtoon-cut/readingOrder.test.ts \
  src/features/webtoon-cut/darkBgSplitEngine.test.ts \
  src/features/webtoon-cut/gridDetector.test.ts
```

Expected: PASS.

---

### Task 4: End-to-End Filename/Manifest Contracts

**Files:**
- Modify: `frontend/src/features/webtoon-cut/runner.test.ts`
- Modify: `backend/tests/test_webtoon_panel_grid_split.py`
- Modify: `backend/tests/test_webtoon_cut_worker.py`

**Interfaces:**
- Consumes:
  - Frontend `runWebtoonCutJob(...)`
  - Backend `process_image_file(...)`
  - Backend `output_relative_path(...)` through `_store_result(...)`
- Produces: regression evidence that visual order and file names agree.

- [ ] **Step 1: Add frontend runner filename-order test**

Append to `frontend/src/features/webtoon-cut/runner.test.ts`:

```ts
it("writes dark webtoon output filenames in visual reading order", async () => {
  const image = blankImage(900, 960, [20, 20, 20]);
  drawDarkPanel(image, { x0: 80, y0: 40, x1: 420, y1: 180 });
  drawDarkPanel(image, { x0: 460, y0: 40, x1: 800, y1: 180 });
  drawDarkPanel(image, { x0: 70, y0: 220, x1: 820, y1: 380 });
  drawDarkPanel(image, { x0: 70, y0: 470, x1: 420, y1: 900 });
  drawDarkPanel(image, { x0: 500, y0: 470, x1: 850, y1: 900 });

  const output = memoryDirectory({});
  const result = await runWebtoonCutJob(
    {
      jobId: "job_reading_order",
      inputKind: "image",
      inputName: "layout.png",
      splitMode: "dark-webtoon",
      inputs: [
        {
          kind: "image",
          relativePath: "layout.png",
          fileName: "layout.png",
          extension: ".png",
          testImage: image
        }
      ]
    },
    { output },
    neverAborted()
  );

  expect(result.generatedFiles).toEqual([
    "layout/layout-01.png",
    "layout/layout-02.png",
    "layout/layout-03.png",
    "layout/layout-04.png",
    "layout/layout-05.png"
  ]);
});
```

If `drawDarkPanel` does not exist in `runner.test.ts`, add a local helper using the same pixel-fill approach already used by other tests in that file.

- [ ] **Step 2: Run frontend runner test**

Run:

```bash
npm --prefix frontend test -- src/features/webtoon-cut/runner.test.ts
```

Expected: PASS.

- [ ] **Step 3: Add backend output naming order test using actual dark split**

Append to `backend/tests/test_webtoon_panel_grid_split.py`:

```python
def test_process_image_file_dark_mode_returns_cut_indexes_in_visual_order(tmp_path):
    from backend.app.services.webtoon_panel_engine.runtime import process_image_file

    source = tmp_path / "dark-layout.png"
    image = np.full((960, 900, 3), 20, dtype=np.uint8)
    panels = [
        ((80, 40), (420, 180)),
        ((460, 40), (800, 180)),
        ((70, 220), (820, 380)),
        ((70, 470), (420, 900)),
        ((500, 470), (850, 900)),
    ]
    for index, (a, b) in enumerate(panels, start=1):
        cv2.rectangle(image, a, b, (235, 235, 235), -1)
        cv2.putText(image, str(index), (a[0] + 30, a[1] + 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    cv2.imwrite(str(source), image)

    result = process_image_file(source, output_dir=tmp_path / "out", split_mode="dark-webtoon")

    assert [cut.cut_index for cut in result.cuts] == [1, 2, 3, 4, 5]
    assert [cut.path.name for cut in result.cuts] == [
        "panel-01.png",
        "panel-02.png",
        "panel-03.png",
        "panel-04.png",
        "panel-05.png",
    ]
```

- [ ] **Step 4: Run backend end-to-end tests**

Run:

```bash
python3 -m pytest backend/tests/test_webtoon_panel_grid_split.py backend/tests/test_webtoon_cut_worker.py -q
```

Expected: PASS.

---

### Task 5: Full Verification and Release Notes

**Files:**
- No production file changes expected beyond Tasks 1-4.

**Interfaces:**
- Consumes all previous task outputs.
- Produces verified implementation ready for user-directed commit/deploy.

- [ ] **Step 1: Run full repository verification**

Run:

```bash
./scripts/verify.sh
```

Expected: exit code `0`.

- [ ] **Step 2: Inspect diff for accidental scope creep**

Run:

```bash
git diff --stat
git diff -- backend/app/services/webtoon_panel_engine frontend/src/features/webtoon-cut backend/tests/test_webtoon_panel_grid_split.py backend/tests/test_webtoon_cut_worker.py
git status --short
```

Expected:

- No backend schema/migration changes.
- No Dockerfile or dependency changes.
- No S3/API contract changes.
- Changes are limited to reading-order utilities, ordering application, and tests.

- [ ] **Step 3: Manual acceptance checklist**

Verify these statements before reporting completion:

- A vertical stack names cuts `01`, `02`, `03` from top to bottom.
- A row with two panels names the left panel before the right panel.
- A mixed layout like the user’s screenshot names top-left `01`, top-right `02`, middle full-width `03`, lower-left `04`, lower-right `05`.
- Server dark-webtoon mode and frontend dark-webtoon mode use the same rule.
- Existing print/grid mode still passes its current parity tests.
- Existing output path format is unchanged.

- [ ] **Step 4: Commit only if explicitly requested**

If the user asks for commit:

```bash
git add \
  backend/app/services/webtoon_panel_engine/reading_order.py \
  backend/app/services/webtoon_panel_engine/dark_bg_split.py \
  backend/app/services/webtoon_panel_engine/grid_split.py \
  backend/tests/test_webtoon_panel_reading_order.py \
  backend/tests/test_webtoon_panel_grid_split.py \
  backend/tests/test_webtoon_cut_worker.py \
  frontend/src/features/webtoon-cut/readingOrder.ts \
  frontend/src/features/webtoon-cut/readingOrder.test.ts \
  frontend/src/features/webtoon-cut/gridSplitEngine.ts \
  frontend/src/features/webtoon-cut/gridDetector.ts \
  frontend/src/features/webtoon-cut/darkBgSplitEngine.ts \
  frontend/src/features/webtoon-cut/darkBgSplitEngine.test.ts \
  frontend/src/features/webtoon-cut/runner.test.ts
git commit -m "fix(webtoon-cut): enforce visual reading order numbering"
```

---

## Self-Review

- Spec coverage:
  - Top-to-bottom ordering: Task 1, Task 3 tests.
  - Left-to-right within the same area: Task 1, Task 3, Task 4 tests.
  - File naming tied to order: Task 2 worker contract, Task 4 runner contract.
  - Both print/grid and dark-webtoon modes: Task 2 and Task 3 apply common ordering to grid and dark paths.
- Placeholder scan:
  - No `TBD`, `TODO`, or “write appropriate tests” placeholders remain.
- Type consistency:
  - Backend `Box` is `(x0, y0, x1, y1)`.
  - Frontend utility accepts `PixelRegion`.
  - Existing `cut_index` and `DetectedCut.index` semantics are preserved.
