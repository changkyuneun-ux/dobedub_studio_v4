import { verifyPngOutput } from "./artifacts";
import type { DirectoryPort } from "./filesystem";
import type { ReconciliationReport, SourceUnitDescriptor, UnitLedgerEntry, WebtoonCutManifest } from "./types";

export async function reconcileJob(
  inventory: SourceUnitDescriptor[],
  manifest: WebtoonCutManifest,
  outputRoot: DirectoryPort
): Promise<ReconciliationReport> {
  const ledgerByUnit = new Map(manifest.ledger.map((unit) => [unit.unitId, unit]));
  const missingUnitIds: string[] = [];
  const invalidOutputUnitIds: string[] = [];
  const errorUnitIds: string[] = [];
  const reviewUnitIds: string[] = [];
  let completedUnitCount = 0;

  for (const unit of inventory) {
    const ledger = ledgerByUnit.get(unit.unitId);
    if (!ledger) {
      missingUnitIds.push(unit.unitId);
      continue;
    }
    if (ledger.status === "error") {
      errorUnitIds.push(unit.unitId);
      continue;
    }
    if (ledger.flags.includes("review_required")) {
      reviewUnitIds.push(unit.unitId);
    }
    if (ledger.status !== "completed" || ledger.outputs.length === 0) {
      missingUnitIds.push(unit.unitId);
      continue;
    }
    const outputsValid = await Promise.all(ledger.outputs.map((output) => outputExists(outputRoot, output.path, output)));
    if (outputsValid.every(Boolean)) {
      completedUnitCount += 1;
    } else {
      invalidOutputUnitIds.push(unit.unitId);
      missingUnitIds.push(unit.unitId);
    }
  }

  return {
    expectedUnitCount: inventory.length,
    completedUnitCount,
    errorUnitIds,
    reviewUnitIds,
    missingUnitIds,
    invalidOutputUnitIds,
    canComplete: (
      inventory.length === completedUnitCount &&
      errorUnitIds.length === 0 &&
      missingUnitIds.length === 0 &&
      invalidOutputUnitIds.length === 0
    )
  };
}

export async function resumeDecision(unit: UnitLedgerEntry, outputRoot: DirectoryPort): Promise<{ action: "skip" | "reprocess"; reason: string }> {
  if (unit.status !== "completed" || unit.outputs.length === 0) {
    return { action: "reprocess", reason: "not_completed" };
  }
  const outputsValid = await Promise.all(unit.outputs.map((output) => outputExists(outputRoot, output.path, output)));
  return outputsValid.every(Boolean) ? { action: "skip", reason: "completed" } : { action: "reprocess", reason: "missing_output" };
}

export function canResume(manifest: WebtoonCutManifest, request: { engineVersion: string; options: unknown; fingerprints?: unknown }) {
  return manifest.engineVersion === request.engineVersion && JSON.stringify(manifest.options) === JSON.stringify(request.options);
}

async function outputExists(
  root: DirectoryPort,
  path: string,
  expectedSize: { width: number; height: number }
): Promise<boolean> {
  try {
    const file = await readFileByPath(root, path);
    return verifyPngOutput(file, expectedSize);
  } catch {
    return false;
  }
}

async function readFileByPath(root: DirectoryPort, path: string): Promise<File> {
  const parts = path.split("/").filter(Boolean);
  let directory = root;
  for (let index = 0; index < parts.length - 1; index += 1) {
    directory = await directory.getDirectoryHandle(parts[index]);
  }
  return (await directory.getFileHandle(parts[parts.length - 1])).getFile();
}
