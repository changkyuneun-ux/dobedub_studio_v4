#!/usr/bin/env node
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const fixtureRoot = process.env.WEBTOON_CUT_FIXTURE_ROOT;

if (!fixtureRoot) {
  console.log("SKIP: WEBTOON_CUT_FIXTURE_ROOT is not set");
  process.exit(0);
}

if (!existsSync(fixtureRoot)) {
  console.log(`SKIP: WEBTOON_CUT_FIXTURE_ROOT does not exist: ${fixtureRoot}`);
  process.exit(0);
}

const expectedSamples = [
  "진실의 방_001_009.jpg",
  "진실의 방_001_006.jpg",
  "진실의 방_001_006-07.jpg",
  "과학사 1.png"
];

const missing = expectedSamples.filter((name) => !existsSync(join(fixtureRoot, name)));
if (missing.length) {
  missing.forEach((name) => console.log(`SKIP: sample not found under WEBTOON_CUT_FIXTURE_ROOT: ${name}`));
  process.exit(0);
}

const scratch = mkdtempSync(join(tmpdir(), "webtoon-cut-golden-"));
try {
  console.log(`SKIP: golden image decoder is not configured for Node execution; scratch=${scratch}`);
  console.log("Unit coverage still locks detector thresholds. Run browser-local manual golden QA before release.");
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
