# Light-background Webtoon Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing `dark-webtoon` contract while automatically splitting both light and dark borderless webtoon backgrounds and filtering only demonstrably small fragments.

**Architecture:** The deployed Python engine remains authoritative and chooses `light` or `dark` by measuring uniform full-width rows. The dormant browser TypeScript engine receives the same constants, signatures, inequalities, filtering, and golden tests so the two implementations cannot silently diverge. The worker carries the measured `bg_mode` through runtime stats into existing job JSON metadata without a database migration.

**Tech Stack:** Python 3.12, NumPy, OpenCV, FastAPI worker pipeline, SQLAlchemy JSON metadata, React/TypeScript, Vitest, pytest, ECS Fargate/ECR.

**Spec:** `/Users/changkyuneun/webtoon Pannel/docs/두비덥스튜디오-밝은배경-배포가이드.md`

## Global Constraints

- Keep `WebtoonCutSplitMode`, API copies, `SPLIT_MODES`, runtime routing, and `DetectorMode` unchanged; the internal value remains `dark-webtoon`.
- Do not modify `grid_split.py`, `backend/requirements.txt`, `Dockerfile`, or Alembic migrations.
- Do not mutate production RDS data from application code.
- Preserve `order_reading_sequence` in both Python and TypeScript; the upstream Python file does not contain the repository's later reading-order integration.
- Add constants exactly: `LIGHT_BG_MIN = 200`, `SMALL_SIDE_RATIO = 0.12`, `SMALL_AREA_RATIO = 0.02`.
- Add optional `mode='dark'`/`mode = "dark"` parameters at the end of existing signatures.
- Small-fragment rejection uses both conditions with AND, after blank checks.
- No commit, push, image build, task registration, migration, or deployment until the user gives a separate explicit instruction after reviewing the implementation.
- Deployment must clone the then-current PRIMARY task definition and replace only the `Main` image.

---

## Current-state Baseline

- Local branch: `main`, clean worktree, `origin/main...main = 0 behind / 2 ahead`.
- Local HEAD: `3e03f87 feat(batch): add selective cancellation for pending work`; it contains `f4c49d7`.
- Production PRIMARY observed on 2026-09-18: `arn:aws:ecs:ap-northeast-2:471112500555:task-definition/default-dobedub-app:170`, image tag `3e03f87`, rollout `COMPLETED`, desired/running/pending `1/1/0`.
- Current synthetic backend evidence: a 720×3000 white background with three panels returns one full-page box and `{'noise': 0, 'blank': 0, 'vmax': 12}`; the equivalent black background returns the expected three boxes.
- Existing focused baseline: Python panel/worker tests pass (`14 passed, 1 skipped`); frontend webtoon-cut suite passes (`20 files, 79 tests`).
- The server pipeline is authoritative. The TypeScript engine is reached only through the browser detector/test path, not the current server job screen, but leaving it stale has caused prior regressions.

## File Map

**Modify**

- `backend/app/services/webtoon_panel_engine/dark_bg_split.py` — background estimation, mode-aware gutter tests, small-fragment filtering, stats output.
- `backend/app/services/webtoon_panel_engine/runtime.py` — carry split stats in `RenderedUnitResult` without changing split-mode routing.
- `backend/app/services/webtoon_cut_worker.py` — merge observed `bg_mode` into the existing job `metadata_json` using a copied dict so SQLAlchemy persists it.
- `backend/tests/test_webtoon_cut_worker.py` — prove metadata propagation and preserve current worker behavior.
- `frontend/src/features/webtoon-cut/darkBgSplitEngine.ts` — exact TypeScript parity with the Python engine.
- `frontend/src/features/webtoon-cut/darkBgSplitEngine.test.ts` — light/dark/small-fragment golden cases.
- `frontend/src/screens/webtoonCutScreen.tsx` — label-only copy change.
- `backend/tests/test_frontend_webtoon_cut_contract.py` — update the label contract.

**Create**

- `backend/tests/test_webtoon_dark_bg_split.py` — CI-safe synthetic Python golden tests independent of local PDFs.

**Explicitly unchanged**

- `backend/app/services/webtoon_panel_engine/grid_split.py`
- `frontend/src/features/webtoon-cut/types.ts`
- `frontend/src/api/client.ts`
- `backend/app/services/webtoon_cut_service.py` split-mode set/normalizer
- `backend/requirements.txt`, `Dockerfile`, `backend/app/db/migrations/**`

---

### Task 1: Capture dark-background regression baselines before editing

**Files:**
- Read: production job metadata/source assets and `/Users/changkyuneun/webtoon Pannel` dark-webtoon samples
- Write temporary evidence only: `/tmp/dobedub-light-bg-baseline/`

**Interfaces:**
- Consumes: current `detect_panels(gray) -> (boxes, stats)` at HEAD `3e03f87`
- Produces: JSON records containing source identity, dimensions, ordered boxes, cut count, and current stats for 3–5 dark-background inputs

- [ ] **Step 1: Create a private temporary evidence directory**

Run: `mktemp -d /tmp/dobedub-light-bg-baseline.XXXXXX`

Expected: a new path under `/tmp`; no repository or production storage writes.

- [ ] **Step 2: Select 3–5 existing dark-background source images**

Use original source images, not already-cropped panels or debug overlays. Prefer three different layouts, including a narrow valid panel near the documented minimum ratio. If production sources must be read, use read-only DB/API metadata and S3 `GetObject` into the temporary directory; do not update any job, asset, or metadata row.

- [ ] **Step 3: Record the current engine result**

For each source, run the current `detect_panels` and serialize ordered integer coordinates plus counts. Record SHA-256 of each source alongside the result so the post-change comparison uses identical bytes.

Expected: every baseline reports the existing dark behavior and `min(short_side / image_width) >= 0.158` for retained real cuts.

- [ ] **Step 4: Stop if suitable originals cannot be obtained**

Do not substitute generated samples for the required historical regression comparison. Report the missing originals and request the user's source location.

---

### Task 2: Add failing Python synthetic tests

**Files:**
- Create: `backend/tests/test_webtoon_dark_bg_split.py`

**Interfaces:**
- Consumes: `detect_panels(gray: np.ndarray) -> tuple[list[tuple[int,int,int,int]], dict]`
- Produces: exact golden coverage for `bg_mode`, light-background splitting, dark compatibility, and `small` filtering

- [ ] **Step 1: Add a 720×3000 white-background three-panel fixture**

Build the array entirely in the test with `np.full(..., 255)` and OpenCV rectangles containing dark ink. Use three non-overlapping panels with gaps wider than scaled `MIN_GAP_AT_1440`.

- [ ] **Step 2: Assert the current code fails the light test**

Run: `python3 -m pytest -q backend/tests/test_webtoon_dark_bg_split.py -k light`

Expected before implementation: FAIL because the engine returns one full-page box and lacks `stats['bg_mode']`.

- [ ] **Step 3: Add the equivalent black-background golden test**

Assert the exact three ordered coordinates and `stats['bg_mode'] == 'dark'`.

- [ ] **Step 4: Add the 82×43 fragment case**

Add a nonblank 82×43 object to the light fixture. Assert the same three retained coordinates, `stats['small'] == 1`, and no change to the panel count.

---

### Task 3: Port the upstream algorithm into the deployed Python engine

**Files:**
- Modify: `backend/app/services/webtoon_panel_engine/dark_bg_split.py`
- Test: `backend/tests/test_webtoon_dark_bg_split.py`

**Interfaces:**
- Produces: `estimate_background(gray) -> tuple[Literal['light','dark'], int]`
- Produces: mode-aware `is_gutter_line`, `_gutter_profile`, `content_runs`, and `xy_cut`
- Produces: stats keys `noise`, `blank`, `small`, `vmax`, `bg_mode`

- [ ] **Step 1: Add the three exact constants**

Add `LIGHT_BG_MIN = 200`, `SMALL_SIDE_RATIO = 0.12`, and `SMALL_AREA_RATIO = 0.02` without changing existing constant values.

- [ ] **Step 2: Add `estimate_background` exactly from spec §2**

The function measures uniform full-width rows, returns `('light', value - BG_MARGIN)` when the representative value is at least 200, otherwise delegates to `estimate_bg_max` and returns `('dark', threshold)`.

- [ ] **Step 3: Thread `mode='dark'` through the four functions**

Append the optional parameter to preserve positional callers. For `light`, use `line >= threshold`; for `dark`, retain `line <= threshold`. Pass mode through every recursive `xy_cut` call.

- [ ] **Step 4: Add the AND small-fragment filter after both blank checks**

Initialize `stats = {'noise': 0, 'blank': 0, 'small': 0}` and reject only when both the short-side and area conditions are below their thresholds.

- [ ] **Step 5: Update `detect_panels` without losing reading order**

Call `estimate_background`, pass mode to `xy_cut`, keep `order_reading_sequence`, and append `vmax` and `bg_mode` to stats.

- [ ] **Step 6: Run the focused Python tests**

Run: `python3 -m pytest -q backend/tests/test_webtoon_dark_bg_split.py backend/tests/test_webtoon_panel_grid_split.py`

Expected: new synthetic tests pass; the two optional local PDF goldens may skip only when their files are absent; all existing grid/dark routing tests remain green.

---

### Task 4: Preserve `bg_mode` in existing job metadata

**Files:**
- Modify: `backend/app/services/webtoon_panel_engine/dark_bg_split.py`
- Modify: `backend/app/services/webtoon_panel_engine/runtime.py`
- Modify: `backend/app/services/webtoon_cut_worker.py`
- Test: `backend/tests/test_webtoon_cut_worker.py`

**Interfaces:**
- `split_panels(..., stats_out: dict | None = None) -> list[str]` remains backward compatible; when provided, it updates the caller-owned dict with detection stats.
- `RenderedUnitResult.split_stats: dict[str, int | str]` defaults to an empty dict, keeping existing test constructors valid.
- Worker metadata records `bgMode` for a single observed mode and `bgModes` as a de-duplicated list for multi-unit ZIP/PDF jobs; conflicting page modes make `bgMode` equal `mixed`.

- [ ] **Step 1: Write worker tests before production changes**

Test a dark-webtoon result with `split_stats={'bg_mode': 'light'}` and assert `_store_result` replaces `job.metadata_json` with a copied dict containing `bgMode: 'light'` and `bgModes: ['light']`. Add a second stored unit with `dark` and assert `bgMode: 'mixed'`, `bgModes: ['light', 'dark']`.

- [ ] **Step 2: Add optional stats transport**

Keep every existing caller valid. Print/grid paths return empty stats. Full-page fallback retains the dark engine's detected stats rather than dropping them.

- [ ] **Step 3: Merge metadata without in-place JSON mutation**

Use `metadata = dict(job.metadata_json or {})`, construct a new list, assign it back to `job.metadata_json`, and commit within the existing `_store_result` transaction. Do not add columns or migrations.

- [ ] **Step 4: Run worker tests**

Run: `python3 -m pytest -q backend/tests/test_webtoon_cut_worker.py`

Expected: all worker tests pass, including metadata aggregation and existing output naming/counting tests.

---

### Task 5: Port exact parity to the dormant TypeScript engine

**Files:**
- Modify: `frontend/src/features/webtoon-cut/darkBgSplitEngine.ts`
- Modify: `frontend/src/features/webtoon-cut/darkBgSplitEngine.test.ts`

**Interfaces:**
- Produces: `estimateBackground(image) -> { mode: 'light' | 'dark'; threshold: number }`
- Extends `DarkBgSplitStats` with `small: number` and `bgMode: 'light' | 'dark'`
- Appends optional `mode: BackgroundMode = 'dark'` to `isGutterLine`, `contentRuns`, `xyCut`, and internal `gutterProfile`

- [ ] **Step 1: Add failing TypeScript golden cases**

Mirror the Python 720×3000 white, black, and 82×43 fragment cases. Assert exact coordinates, `bgMode`, and `small` count.

- [ ] **Step 2: Run the tests to confirm the new cases fail**

Run from `frontend/`: `npm run test:webtoon-cut -- --reporter=dot`

Expected before TS implementation: the new light/mode/small assertions fail while existing 79 tests stay green.

- [ ] **Step 3: Implement the same measurement and inequalities**

Use the exact constants and ordering from Python. Preserve `orderReadingSequence` after filtering.

- [ ] **Step 4: Run frontend tests**

Run from `frontend/`: `npm run test:webtoon-cut -- --reporter=dot`

Expected: all old and new tests pass with exact-coordinate assertions.

---

### Task 6: Change UI copy only

**Files:**
- Modify: `frontend/src/screens/webtoonCutScreen.tsx`
- Modify: `backend/tests/test_frontend_webtoon_cut_contract.py`

**Interfaces:**
- Keeps the radio value `dark-webtoon`
- Displays `웹툰 (테두리 없음)` in both the selector and `splitModeLabel`

- [ ] **Step 1: Update the contract assertion first**

Require `웹툰 (테두리 없음)` and reject the stale visible label `어두운 배경 웹툰`.

- [ ] **Step 2: Change only the two visible label occurrences**

Do not alter type unions, API values, service normalization, routing, or detector tags. Update the helper text from a dark-only description to a light/dark borderless-background description.

- [ ] **Step 3: Run the contract test and frontend build**

Run: `python3 -m pytest -q backend/tests/test_frontend_webtoon_cut_contract.py`

Run: `npm run build`

Expected: both pass.

---

### Task 7: Prove dark-background and print-mode non-regression

**Files:**
- Read: baseline JSON and identical source bytes from Task 1
- Temporary output only: `/tmp/dobedub-light-bg-after/`

**Interfaces:**
- Consumes: pre-change ordered boxes and source SHA-256
- Produces: coordinate-by-coordinate comparison evidence for 3–5 historical jobs

- [ ] **Step 1: Re-run the same dark inputs with the new Python engine**

Assert each source hash matches Task 1. Compare ordered boxes as exact integer tuples, not only counts.

- [ ] **Step 2: Verify the documented ratio safety margin**

Report each retained cut's minimum short-side ratio and confirm no historical retained box is removed by the 0.12/0.02 AND filter.

- [ ] **Step 3: Run print-mode goldens unchanged**

Run: `python3 -m pytest -q backend/tests/test_webtoon_panel_grid_split.py`

Expected: print/grid exact count and coordinate/size expectations are unchanged; local PDF tests explicitly report pass or skip.

- [ ] **Step 4: Stop on any coordinate difference**

Do not weaken expected results or tune constants. Report the exact source, before/after coordinates, and filter stats for user review.

---

### Task 8: Full repository verification and scope audit

**Files:**
- Inspect only: Git diff and verification output

- [ ] **Step 1: Run static checks on the scope**

Run: `git diff --check`

Run: `git diff --name-only`

Expected: only the files listed in this plan are changed; forbidden files are absent.

- [ ] **Step 2: Run the required suite**

Run: `./scripts/verify.sh`

Expected: exit 0. Preserve the command summary and test totals in the implementation report.

- [ ] **Step 3: Confirm forbidden contracts remain byte-equivalent**

Run targeted diffs for `types.ts`, `frontend/src/api/client.ts`, `webtoon_cut_service.py` split-mode code, `grid_split.py`, `Dockerfile`, requirements, and migrations. Expected: no diff.

- [ ] **Step 4: Report without committing**

Report changed files, synthetic tests and outputs, historical regression evidence, full verify output, and remaining risks. Wait for explicit commit/deploy approval.

---

### Task 9: Deferred deployment procedure after explicit approval

**Files:**
- Read: `docs/ecs-express-deployment-runbook.md`
- Execute: `scripts/ecs_release.sh`

- [ ] **Step 1: Re-read and record the current PRIMARY immediately before deployment**

Current planning-time rollback target is `default-dobedub-app:170`, but never assume it is still current. Record the fresh ARN, image digest, rollout state, ALB health, and `/api/health` latency baseline.

- [ ] **Step 2: Commit only the reviewed files when explicitly authorized**

Use the resulting Git short SHA as the immutable ECR tag. Do not deploy a dirty worktree.

- [ ] **Step 3: Run release preflight, build, and register**

Run in order: `scripts/ecs_release.sh preflight`, `scripts/ecs_release.sh build`, `scripts/ecs_release.sh register`.

Expected: `linux/amd64`; new task definition clones the live revision and changes only `Main.image` plus the script's already-declared environment upserts.

- [ ] **Step 4: Enforce the migration exit-2 stop rule before invoking the helper migrate phase**

The current helper auto-applies when check returns 2, which conflicts with this release's guardrail. First run the runbook's one-off `python3 scripts/upgrade_database.py --check` against the newly registered revision. If exit code is 2, stop and report; do not invoke `scripts/ecs_release.sh migrate`. If it is 0, run `scripts/ecs_release.sh migrate` and require its check to remain 0.

- [ ] **Step 5: Deploy without manually stopping the old task**

Run: `scripts/ecs_release.sh deploy`

Wait for PRIMARY `COMPLETED`, one healthy new task, old revision drain managed by ECS, and ALB target `healthy`.

- [ ] **Step 6: Execute post-deploy evidence checks**

Require: `/api/health` `ok:true`; one light borderless webtoon job gives multiple cuts and persisted `bgMode=light`; one dark job matches its pre-deploy cut count/coordinates; one print PDF job matches current output; a large running job leaves `/api/health` under 1 second; CloudWatch contains no cv2/opencv errors.

- [ ] **Step 7: Roll back on an explicit trigger**

If tasks repeatedly restart, any dark job count/coordinates change, or `/api/health` p95 doubles, run `aws ecs update-service` with the recorded pre-deploy task definition. No Alembic rollback is needed because this change has no schema migration.

---

## Self-review

- Spec coverage: both requested algorithm changes, stats consumers, optional metadata, label-only UI change, TS parity, synthetic tests, historical regression, verification, deployment and rollback are mapped above.
- Scope conflicts resolved: no new split mode; Python reading-order enhancement is preserved; `ecs_release.sh migrate` auto-apply behavior is guarded by a separate check.
- Type consistency: Python uses `bg_mode` inside detector stats and persists API-independent job metadata as `bgMode`/`bgModes`; TypeScript exposes `bgMode` in its typed stats.
- Remaining prerequisite: historical regression Task 1 requires 3–5 original dark-background source images. If production read-only retrieval is not available, implementation must stop and request their paths rather than claiming regression coverage from derived crops.
