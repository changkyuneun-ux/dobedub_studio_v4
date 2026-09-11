import type { DiscoveredInput } from "./types";

const FORBIDDEN_COMPONENT_CHARACTERS = /[\\/:\u0000-\u001f\u007f]/g;
const TRAILING_DOTS_OR_SPACES = /[. ]+$/g;

export function normalizeForComparison(name: string): string {
  return name.normalize("NFC");
}

export function safeOutputName(raw: string): string {
  const normalized = normalizeForComparison(raw).replace(FORBIDDEN_COMPONENT_CHARACTERS, "_").replace(TRAILING_DOTS_OR_SPACES, "");
  return normalized || "unnamed";
}

export function fileStem(fileName: string): string {
  const baseName = fileName.split("/").pop()?.split("\\").pop() || fileName;
  const dotIndex = baseName.lastIndexOf(".");
  return dotIndex > 0 ? baseName.slice(0, dotIndex) : baseName;
}

export function fileExtension(fileName: string): string {
  const baseName = fileName.split("/").pop()?.split("\\").pop() || fileName;
  const dotIndex = baseName.lastIndexOf(".");
  return dotIndex >= 0 ? baseName.slice(dotIndex + 1).toLowerCase() : "";
}

export function disambiguateSiblingStems(fileNames: string[]): string[] {
  const safeStems = fileNames.map((name) => safeOutputName(fileStem(name)));
  const stemCounts = new Map<string, number>();
  safeStems.forEach((stem) => {
    const key = normalizeForComparison(stem);
    stemCounts.set(key, (stemCounts.get(key) || 0) + 1);
  });

  return fileNames.map((name, index) => {
    const stem = safeStems[index];
    const key = normalizeForComparison(stem);
    if ((stemCounts.get(key) || 0) <= 1) return stem;
    const extension = safeOutputName(fileExtension(name) || "file");
    return `${stem}__${extension}`;
  });
}

export function planOutputPath(input: DiscoveredInput, collisions: Set<string>): string[] {
  const parentParts = parentPathParts(input.relativePath).map(safeOutputName);
  const stem = uniqueComponent(`${safeOutputName(fileStem(input.fileName))}_cuts`, collisions);
  return [...parentParts, stem];
}

export function planArchiveEntryPath(zipFileName: string, entryRelativePath: string, collisions: Set<string>): string[] {
  const archiveRoot = `${safeOutputName(fileStem(zipFileName))}_cuts`;
  const parents = parentPathParts(entryRelativePath).map(safeOutputName);
  const stem = uniqueComponent(safeOutputName(fileStem(entryRelativePath)), collisions);
  return [archiveRoot, ...parents, stem];
}

export function uniqueComponent(component: string, collisions: Set<string>): string {
  const safe = safeOutputName(component);
  const normalized = normalizeForComparison(safe);
  if (!collisions.has(normalized)) {
    collisions.add(normalized);
    return safe;
  }

  let suffix = 2;
  while (collisions.has(normalizeForComparison(`${safe}__${suffix}`))) {
    suffix += 1;
  }
  const unique = `${safe}__${suffix}`;
  collisions.add(normalizeForComparison(unique));
  return unique;
}

function parentPathParts(relativePath: string): string[] {
  const parts = normalizeForComparison(relativePath).split(/[\\/]+/).filter(Boolean);
  return parts.slice(0, -1);
}
