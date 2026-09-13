import { iterateArchive } from "./archive";
import { SUPPORTED_ARCHIVE_EXTENSIONS, SUPPORTED_DOCUMENT_EXTENSIONS, SUPPORTED_IMAGE_EXTENSIONS } from "./constants";
import { fileExtension, normalizeForComparison } from "./naming";
import { countPdfPages, iteratePdf, pdfUnitId } from "./pdf";
import type { DiscoveredInput, InputKind, SourceUnit, SourceUnitDescriptor } from "./types";

export type SourceInputItem = DiscoveredInput & {
  file?: File;
  testImage?: ImageData;
  testPdfPageCount?: number;
  testPdfPageCountError?: Error;
  archiveEntries?: SourceInputItem[];
};

export type SourceInputCollection = {
  inputs: SourceInputItem[];
};

const IMAGE_EXTENSIONS = new Set<string>(SUPPORTED_IMAGE_EXTENSIONS);
const DOCUMENT_EXTENSIONS = new Set<string>(SUPPORTED_DOCUMENT_EXTENSIONS);
const ARCHIVE_EXTENSIONS = new Set<string>(SUPPORTED_ARCHIVE_EXTENSIONS);

export function classifySourceName(name: string): Exclude<InputKind, "directory"> | null {
  const extension = fileExtension(name).toLowerCase();
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (DOCUMENT_EXTENSIONS.has(extension)) return "pdf";
  if (ARCHIVE_EXTENSIONS.has(extension)) return "zip";
  return null;
}

export async function buildSourceInventory(
  input: SourceInputCollection | SourceInputItem[] | DiscoveredInput[],
  signal: AbortSignal
): Promise<SourceUnitDescriptor[]> {
  try {
    const inventory: SourceUnitDescriptor[] = [];
    const seen = new Set<string>();
    const items = normalizeInputCollection(input);

    for (const item of items) {
      if (signal.aborted) throw signal.reason || new DOMException("Aborted", "AbortError");
      const kind = classifySourceName(item.relativePath) || item.kind;
      const normalizedPath = normalizeForComparison(item.relativePath);

      if (kind === "image") {
        addUnit(inventory, seen, {
          unitId: sourceUnitId("image", normalizedPath, null),
          sourcePath: normalizedPath,
          sourceKind: "image",
          page: null
        });
      } else if (kind === "pdf") {
        const pageCount = await resolvePdfPageCount(item as SourceInputItem);
        for (let page = 1; page <= pageCount; page += 1) {
          addUnit(inventory, seen, {
            unitId: sourceUnitId("pdf-page", normalizedPath, page),
            sourcePath: normalizedPath,
            sourceKind: "pdf-page",
            page
          });
        }
      } else if (kind === "zip") {
        const archiveItems = await resolveArchiveItems(item as SourceInputItem, signal);
        const archiveInventory = await buildSourceInventory({ inputs: archiveItems }, signal);
        archiveInventory.forEach((unit) => addUnit(inventory, seen, unit));
      }
    }

    return inventory;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    if (typeof error === "object" && error && "code" in error) throw error;
    throw Object.assign(new Error("입력 inventory를 완전히 확정하지 못했습니다."), {
      code: "inventory_error",
      cause: error
    });
  }
}

export async function* iterateSource(input: SourceInputItem, signal: AbortSignal): AsyncIterable<SourceUnit> {
  const kind = classifySourceName(input.relativePath) || input.kind;
  const normalizedPath = normalizeForComparison(input.relativePath);

  if (kind === "image") {
    const image = input.testImage || await decodeRasterFile(requiredFile(input));
    yield {
      unitId: sourceUnitId("image", normalizedPath, null),
      sourcePath: normalizedPath,
      sourceKind: "image",
      page: null,
      image,
      width: image.width,
      height: image.height
    };
    return;
  }

  if (kind === "pdf") {
    yield* iteratePdf(requiredFile(input), normalizedPath, signal);
    return;
  }

  if (kind === "zip") {
    for await (const archiveEntry of iterateArchive(requiredFile(input), signal)) {
      yield* iterateSource(archiveEntry, signal);
    }
  }
}

export function sourceUnitId(sourceKind: "image" | "pdf-page", normalizedRelativePath: string, page: number | null): string {
  const path = normalizeForComparison(normalizedRelativePath);
  if (sourceKind === "image") return `image:${path}`;
  return pdfUnitId(path, page || 0);
}

function normalizeInputCollection(input: SourceInputCollection | SourceInputItem[] | DiscoveredInput[]): SourceInputItem[] {
  const inputs = Array.isArray(input) ? input : input.inputs;
  return [...inputs].map((item) => ({
    ...item,
    relativePath: normalizeForComparison(item.relativePath),
    extension: (item.extension || fileExtension(item.relativePath)).toLowerCase()
  })).sort((left, right) => (
    normalizeForComparison(left.relativePath).localeCompare(normalizeForComparison(right.relativePath), "ko")
  ));
}

async function resolvePdfPageCount(input: SourceInputItem): Promise<number> {
  if (input.testPdfPageCountError) throw input.testPdfPageCountError;
  if (typeof input.testPdfPageCount === "number") return input.testPdfPageCount;
  return countPdfPages(requiredFile(input));
}

async function resolveArchiveItems(input: SourceInputItem, signal: AbortSignal): Promise<SourceInputItem[]> {
  if (input.archiveEntries) return input.archiveEntries;
  const entries: SourceInputItem[] = [];
  for await (const entry of iterateArchive(requiredFile(input), signal)) {
    entries.push(entry);
  }
  return entries;
}

function addUnit(inventory: SourceUnitDescriptor[], seen: Set<string>, unit: SourceUnitDescriptor) {
  if (seen.has(unit.unitId)) {
    throw Object.assign(new Error(`중복 작업 단위입니다: ${unit.unitId}`), { code: "inventory_error" });
  }
  seen.add(unit.unitId);
  inventory.push(unit);
}

function requiredFile(input: SourceInputItem): File {
  if (input.file) return input.file;
  throw Object.assign(new Error(`입력 파일을 읽을 수 없습니다: ${input.relativePath}`), { code: "inventory_error" });
}

async function decodeRasterFile(file: File): Promise<ImageData> {
  const bitmap = await createImageBitmap(file);
  try {
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("이미지 디코딩 컨텍스트를 만들 수 없습니다.");
    context.drawImage(bitmap, 0, 0);
    return context.getImageData(0, 0, canvas.width, canvas.height);
  } finally {
    bitmap.close();
  }
}
