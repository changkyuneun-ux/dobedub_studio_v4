import { ENGINE_VERSION, MANIFEST_SCHEMA_VERSION, PAGE_POLICY, PDF_RENDER_SCALE, STRIP_POLICY, TRANSITION_POLICY } from "./constants";
import { detectCuts } from "./detector";
import { writeAtomically, type DirectoryPort } from "./filesystem";
import { fileStem, safeOutputName } from "./naming";
import { encodeCut, serializeSummary, verifyPngOutput } from "./artifacts";
import { buildSourceInventory, iterateSource, type SourceInputCollection, type SourceInputItem } from "./inputSources";
import type { InputKind, RunnerProgressEvent, SummaryRow, UnitLedgerEntry, WebtoonCutManifest, WebtoonCutSplitMode } from "./types";

export type RunnerJobRequest = {
  jobId: string;
  inputKind: InputKind;
  inputName: string;
  splitMode?: WebtoonCutSplitMode;
  inputs: SourceInputCollection | SourceInputItem[];
};

export type RunnerPorts = {
  output: DirectoryPort | FileSystemDirectoryHandle;
  onProgress?: (event: RunnerProgressEvent) => void;
};

export async function runWebtoonCutJob(request: RunnerJobRequest, ports: RunnerPorts, signal: AbortSignal): Promise<WebtoonCutManifest> {
  const inventory = await buildSourceInventory(request.inputs, signal);
  const manifest = createManifest(request, inventory.length);
  manifest.inventory = inventory;
  const previousManifest = await readExistingManifest(ports.output);
  const previousLedger = new Map(
    previousManifest?.engineVersion === manifest.engineVersion
      ? previousManifest.ledger.map((unit) => [unit.unitId, unit])
      : []
  );
  const summaryRows: SummaryRow[] = [];
  const inputs = Array.isArray(request.inputs) ? request.inputs : request.inputs.inputs;
  let completedUnitCount = 0;
  let generatedCutCount = 0;
  ports.onProgress?.({
    stage: "inventory",
    completed: 0,
    total: manifest.expectedUnitCount,
    generatedCuts: 0,
    message: `${manifest.expectedUnitCount}개 처리 단위를 확인했습니다.`
  });

  for (const input of inputs) {
    for await (const source of iterateSource(input, signal)) {
      if (signal.aborted) {
        return finalizeManifest(manifest, ports, summaryRows, "paused", completedUnitCount, generatedCutCount);
      }
      const startedAt = performance.now();
      const previous = previousLedger.get(source.unitId);
      if (previous && await completedOutputsExist(ports.output, previous)) {
        manifest.ledger.push(previous);
        manifest.generatedFiles.push(...previous.outputs.map((output) => output.path));
        summaryRows.push(...summaryRowsFromLedger(previous, Math.round(performance.now() - startedAt)));
        completedUnitCount += 1;
        generatedCutCount += previous.outputs.length;
        ports.onProgress?.({
          stage: "resume-skip",
          unitId: source.unitId,
          sourcePath: source.sourcePath,
          completed: completedUnitCount,
          total: manifest.expectedUnitCount,
          generatedCuts: generatedCutCount,
          message: "manifest와 PNG가 유효해 완료 단위를 건너뜁니다."
        });
        if (signal.aborted) {
          return finalizeManifest(manifest, ports, summaryRows, "paused", completedUnitCount, generatedCutCount);
        }
        continue;
      }

      ports.onProgress?.({
        stage: "render",
        unitId: source.unitId,
        sourcePath: source.sourcePath,
        completed: completedUnitCount,
        total: manifest.expectedUnitCount,
        generatedCuts: generatedCutCount,
        message: "페이지/이미지 렌더링 완료"
      });
      if (signal.aborted) {
        return finalizeManifest(manifest, ports, summaryRows, "paused", completedUnitCount, generatedCutCount);
      }
      const cuts = detectCuts(source.image, "auto", source.sourceKind === "pdf-page" ? "pdf" : "image", request.splitMode || "print");
      ports.onProgress?.({
        stage: "detect",
        unitId: source.unitId,
        sourcePath: source.sourcePath,
        completed: completedUnitCount,
        total: manifest.expectedUnitCount,
        generatedCuts: generatedCutCount,
        message: `${cuts.length}개 컷 후보 감지`
      });
      if (signal.aborted) {
        return finalizeManifest(manifest, ports, summaryRows, "paused", completedUnitCount, generatedCutCount);
      }
      const ledger: UnitLedgerEntry = {
        unitId: source.unitId,
        sourcePath: source.sourcePath,
        sourceKind: source.sourceKind,
        page: source.page,
        status: "completed",
        attempts: 1,
        flags: [],
        outputs: []
      };

      for (const cut of cuts) {
        const filename = outputFileName(source.sourcePath, source.page, cut.index);
        const blob = await encodeCut(source.image, cut);
        await writePathAtomically(ports.output, filename, blob);
        const width = cut.x1 - cut.x0;
        const height = cut.y1 - cut.y0;
        ledger.outputs.push({
          path: filename,
          width,
          height,
          x0: cut.x0,
          y0: cut.y0,
          x1: cut.x1,
          y1: cut.y1,
          mode: cut.mode,
          confidence: cut.confidence,
          flags: cut.flags
        });
        generatedCutCount += 1;
        ledger.flags = [...new Set([...ledger.flags, ...cut.flags])];
        summaryRows.push({
          unit_id: source.unitId,
          source_path: source.sourcePath,
          page: source.page ?? "",
          cut: cut.index,
          filename,
          mode: cut.mode,
          x0: cut.x0,
          y0: cut.y0,
          x1: cut.x1,
          y1: cut.y1,
          width,
          height,
          confidence: cut.confidence,
          flag: cut.flags.join(" "),
          elapsed_ms: Math.round(performance.now() - startedAt),
          status: "completed",
          error: ""
        });
      }
      ports.onProgress?.({
        stage: "write",
        unitId: source.unitId,
        sourcePath: source.sourcePath,
        completed: completedUnitCount,
        total: manifest.expectedUnitCount,
        generatedCuts: generatedCutCount,
        message: `${ledger.outputs.length}개 PNG 저장`
      });

      manifest.ledger.push(ledger);
      manifest.generatedFiles.push(...ledger.outputs.map((output) => output.path));
      completedUnitCount += 1;
      ports.onProgress?.({
        stage: "unit-complete",
        unitId: source.unitId,
        sourcePath: source.sourcePath,
        completed: completedUnitCount,
        total: manifest.expectedUnitCount,
        generatedCuts: generatedCutCount,
        message: "처리 단위 완료"
      });
      if (signal.aborted) {
        return finalizeManifest(manifest, ports, summaryRows, "paused", completedUnitCount, generatedCutCount);
      }
    }
  }

  return finalizeManifest(manifest, ports, summaryRows, null, completedUnitCount, generatedCutCount);
}

async function finalizeManifest(
  manifest: WebtoonCutManifest,
  ports: RunnerPorts,
  summaryRows: SummaryRow[],
  forcedStatus: "paused" | null,
  completedUnitCount: number,
  generatedCutCount: number
) {
  await writeAtomically(ports.output, "summary.csv", serializeSummary(summaryRows));
  const reviewRequired = manifest.ledger.some((unit) => unit.flags.includes("review_required"));
  manifest.status = forcedStatus || (reviewRequired ? "completed_with_review" : "completed");
  manifest.updatedAt = new Date().toISOString();
  manifest.completedAt = forcedStatus ? null : manifest.updatedAt;
  manifest.totals = {
    expectedUnitCount: manifest.expectedUnitCount,
    completedUnitCount: manifest.ledger.filter((unit) => unit.status === "completed").length,
    errorUnitCount: manifest.ledger.filter((unit) => unit.status === "error").length,
    reviewRequiredUnitCount: manifest.ledger.filter((unit) => unit.flags.includes("review_required")).length,
    generatedCutCount: manifest.ledger.reduce((sum, unit) => sum + unit.outputs.length, 0),
    flags: countFlags(manifest.ledger)
  };
  await writeAtomically(ports.output, "manifest.json", JSON.stringify(manifest, null, 2));
  ports.onProgress?.({
    stage: "manifest",
    completed: completedUnitCount,
    total: manifest.expectedUnitCount,
    generatedCuts: generatedCutCount,
    message: forcedStatus ? "중단 시점까지의 manifest.json과 summary.csv 저장 완료" : "manifest.json과 summary.csv 저장 완료"
  });
  return manifest;
}

function createManifest(request: RunnerJobRequest, expectedUnitCount: number): WebtoonCutManifest {
  const now = new Date().toISOString();
  return {
    schemaVersion: MANIFEST_SCHEMA_VERSION,
    engineVersion: ENGINE_VERSION,
    jobId: request.jobId,
    status: "running",
    inputKind: request.inputKind,
    inputName: request.inputName,
    outputRoot: `${safeOutputName(fileStem(request.inputName))}_cuts`,
    expectedUnitCount,
    createdAt: now,
    updatedAt: now,
    completedAt: null,
    options: {
      mode: "auto",
      splitMode: request.splitMode || "print",
      pdfScale: PDF_RENDER_SCALE,
      outputFormat: "png",
      pagePolicy: PAGE_POLICY,
      stripPolicy: STRIP_POLICY,
      transitionPolicy: TRANSITION_POLICY
    },
    inputs: [],
    inventory: [],
    ledger: [],
    generatedFiles: [],
    totals: {
      expectedUnitCount,
      completedUnitCount: 0,
      errorUnitCount: 0,
      reviewRequiredUnitCount: 0,
      generatedCutCount: 0,
      flags: {}
    }
  };
}

export function outputFileName(sourcePath: string, page: number | null, cutIndex: number) {
  const parts = sourcePath.normalize("NFC").split("/").filter(Boolean).map(safeOutputName);
  const fileName = parts.pop() || sourcePath;
  const sourceStem = safeOutputName(fileStem(fileName));
  const parents = parts.length ? `${parts.join("/")}/` : "";
  const sourceDirectory = `${parents}${sourceStem}/`;
  if (page !== null) return `${sourceDirectory}${String(page).padStart(3, "0")}-${String(cutIndex).padStart(2, "0")}.png`;
  return `${sourceDirectory}${sourceStem}-${String(cutIndex).padStart(2, "0")}.png`;
}

async function writePathAtomically(root: DirectoryPort | FileSystemDirectoryHandle, path: string, blob: Blob) {
  const parts = path.split("/").filter(Boolean);
  const fileName = parts.pop();
  if (!fileName) throw new Error("출력 파일명이 비어 있습니다.");
  let directory = root;
  for (const part of parts) {
    directory = await directory.getDirectoryHandle(part, { create: true });
  }
  await writeAtomically(directory, fileName, blob);
}

function countFlags(ledger: UnitLedgerEntry[]) {
  const counts: Record<string, number> = {};
  ledger.forEach((unit) => {
    unit.flags.forEach((flag) => {
      counts[flag] = (counts[flag] || 0) + 1;
    });
  });
  return counts;
}

export async function readExistingManifest(root: DirectoryPort | FileSystemDirectoryHandle): Promise<WebtoonCutManifest | null> {
  try {
    const handle = await root.getFileHandle("manifest.json");
    const file = await handle.getFile();
    const parsed = JSON.parse(await file.text()) as WebtoonCutManifest;
    return Array.isArray(parsed.ledger) ? parsed : null;
  } catch {
    return null;
  }
}

async function completedOutputsExist(root: DirectoryPort | FileSystemDirectoryHandle, unit: UnitLedgerEntry) {
  if (unit.status !== "completed" || !unit.outputs.length) return false;
  const results = await Promise.all(unit.outputs.map(async (output) => {
    try {
      const file = await readFileByPath(root, output.path);
      return verifyPngOutput(file, output);
    } catch {
      return false;
    }
  }));
  return results.every(Boolean);
}

async function readFileByPath(root: DirectoryPort | FileSystemDirectoryHandle, path: string) {
  const parts = path.split("/").filter(Boolean);
  const fileName = parts.pop();
  if (!fileName) throw new Error("출력 파일명이 비어 있습니다.");
  let directory = root;
  for (const part of parts) {
    directory = await directory.getDirectoryHandle(part);
  }
  const handle = await directory.getFileHandle(fileName);
  return handle.getFile();
}

function summaryRowsFromLedger(unit: UnitLedgerEntry, elapsedMs: number): SummaryRow[] {
  return unit.outputs.map((output, index) => ({
    unit_id: unit.unitId,
    source_path: unit.sourcePath,
    page: unit.page ?? "",
    cut: index + 1,
    filename: output.path,
    mode: output.mode || "",
    x0: output.x0 ?? "",
    y0: output.y0 ?? "",
    x1: output.x1 ?? "",
    y1: output.y1 ?? "",
    width: output.width,
    height: output.height,
    confidence: output.confidence ?? "",
    flag: output.flags?.join(" ") || "",
    elapsed_ms: elapsedMs,
    status: unit.status,
    error: unit.error || ""
  }));
}
