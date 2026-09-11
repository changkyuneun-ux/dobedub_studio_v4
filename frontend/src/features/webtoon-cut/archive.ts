import { AsyncUnzipInflate, Unzip, UnzipPassThrough } from "fflate";
import { ARCHIVE_LIMITS, SUPPORTED_ARCHIVE_EXTENSIONS, SUPPORTED_DOCUMENT_EXTENSIONS, SUPPORTED_IMAGE_EXTENSIONS } from "./constants";
import { fileExtension, normalizeForComparison } from "./naming";
import type { InputKind, SourceFingerprint } from "./types";

export type ZipEntryMeta = {
  name: string;
  originalSize: number;
  compressedSize: number;
  directory?: boolean;
};

export type ValidatedZipEntryMeta = ZipEntryMeta & {
  normalizedName: string;
  extension: string;
  kind: Exclude<InputKind, "directory">;
};

export type ArchiveSourceEntry = {
  kind: Exclude<InputKind, "directory">;
  relativePath: string;
  fileName: string;
  extension: string;
  file: File;
  fingerprint: SourceFingerprint;
};

const IMAGE_EXTENSIONS = new Set<string>(SUPPORTED_IMAGE_EXTENSIONS);
const DOCUMENT_EXTENSIONS = new Set<string>(SUPPORTED_DOCUMENT_EXTENSIONS);
const ARCHIVE_EXTENSIONS = new Set<string>(SUPPORTED_ARCHIVE_EXTENSIONS);

export function validateArchiveEntry(entry: ZipEntryMeta): ValidatedZipEntryMeta | null {
  const normalizedName = normalizeArchivePath(entry.name);
  if (entry.directory || normalizedName.endsWith("/")) return null;

  assertSafeArchivePath(normalizedName);
  if (shouldSkipArchivePath(normalizedName)) return null;

  const extension = fileExtension(normalizedName);
  const kind = archiveKindForExtension(extension);
  if (!kind) return null;

  if (entry.originalSize > ARCHIVE_LIMITS.maxEntryBytes) {
    throw archiveError("archive_entry_too_large", `ZIP 항목이 한도를 초과했습니다: ${normalizedName}`);
  }

  const compressedSize = entry.compressedSize;
  if (entry.originalSize > 0 && compressedSize <= 0) {
    throw archiveError("archive_compression_ratio", `ZIP 항목의 압축비를 확인할 수 없습니다: ${normalizedName}`);
  }

  if (entry.originalSize > 0 && entry.originalSize / compressedSize > ARCHIVE_LIMITS.maxCompressionRatio) {
    throw archiveError("archive_compression_ratio", `ZIP 항목 압축비가 한도를 초과했습니다: ${normalizedName}`);
  }

  return {
    ...entry,
    name: normalizedName,
    normalizedName,
    extension,
    kind
  };
}

export async function* iterateArchive(file: File, signal: AbortSignal): AsyncIterable<ArchiveSourceEntry> {
  const queue: ArchiveSourceEntry[] = [];
  let streamEnded = false;
  let activeEntries = 0;
  let acceptedEntries = 0;
  let expandedBytes = 0;
  let pendingError: unknown = null;
  let wake: (() => void) | null = null;

  const wakeConsumer = () => {
    wake?.();
    wake = null;
  };

  const unzip = new Unzip((zipFile) => {
    try {
      const validated = validateArchiveEntry({
        name: zipFile.name,
        originalSize: zipFile.originalSize ?? 0,
        compressedSize: zipFile.size ?? 0,
        directory: zipFile.name.endsWith("/")
      });
      if (!validated) return;

      acceptedEntries += 1;
      expandedBytes += validated.originalSize;
      if (acceptedEntries > ARCHIVE_LIMITS.maxEntries) {
        throw archiveError("archive_too_many_entries", "ZIP 항목 수가 한도를 초과했습니다.");
      }
      if (expandedBytes > ARCHIVE_LIMITS.maxExpandedBytes) {
        throw archiveError("archive_too_large", "ZIP 압축 해제 예상 합계가 한도를 초과했습니다.");
      }

      activeEntries += 1;
      const chunks: Uint8Array[] = [];
      let decompressedBytes = 0;

      zipFile.ondata = (error, chunk, final) => {
        if (error) {
          pendingError = error;
          activeEntries -= 1;
          wakeConsumer();
          return;
        }

        if (chunk.byteLength) {
          decompressedBytes += chunk.byteLength;
          if (decompressedBytes > ARCHIVE_LIMITS.maxEntryBytes) {
            pendingError = archiveError("archive_entry_too_large", `ZIP 항목이 한도를 초과했습니다: ${validated.normalizedName}`);
            zipFile.terminate?.();
            activeEntries -= 1;
            wakeConsumer();
            return;
          }
          chunks.push(chunk);
        }

        if (final) {
          const bytes = concatBytes(chunks, decompressedBytes);
          const fileName = validated.normalizedName.split("/").pop() || validated.normalizedName;
          const archiveFile = new File([bytes.buffer], fileName, {
            type: mimeTypeForExtension(validated.extension),
            lastModified: file.lastModified
          });
          queue.push({
            kind: validated.kind,
            relativePath: validated.normalizedName,
            fileName,
            extension: validated.extension,
            file: archiveFile,
            fingerprint: {
              name: fileName,
              size: archiveFile.size,
              lastModified: archiveFile.lastModified
            }
          });
          activeEntries -= 1;
          wakeConsumer();
        }
      };

      zipFile.start();
    } catch (error) {
      pendingError = error;
      wakeConsumer();
    }
  });

  unzip.register(UnzipPassThrough);
  unzip.register(AsyncUnzipInflate);

  void (async () => {
    try {
      const reader = file.stream().getReader();
      while (true) {
        if (signal.aborted) throw signal.reason || new DOMException("Aborted", "AbortError");
        const { value, done } = await reader.read();
        if (done) break;
        unzip.push(value);
      }
      unzip.push(new Uint8Array(), true);
      streamEnded = true;
      wakeConsumer();
    } catch (error) {
      pendingError = error;
      streamEnded = true;
      wakeConsumer();
    }
  })();

  while (!streamEnded || activeEntries > 0 || queue.length > 0) {
    if (pendingError) throw pendingError;
    const next = queue.shift();
    if (next) {
      yield next;
      continue;
    }
    await new Promise<void>((resolve) => {
      wake = resolve;
    });
  }

  if (pendingError) throw pendingError;
}

function normalizeArchivePath(path: string): string {
  return normalizeForComparison(repairMojibakePath(path).replace(/\\/g, "/"));
}

function repairMojibakePath(path: string): string {
  if (!looksLikeMojibake(path)) return path;
  const bytes = Uint8Array.from(path, (char) => char.charCodeAt(0) & 0xff);
  const candidates = ["utf-8", "euc-kr"]
    .map((encoding) => decodeMojibakeCandidate(bytes, encoding))
    .filter((candidate): candidate is string => Boolean(candidate));
  return candidates.reduce((best, candidate) => (
    readabilityScore(candidate) > readabilityScore(best) ? candidate : best
  ), path);
}

function decodeMojibakeCandidate(bytes: Uint8Array, encoding: string): string | null {
  try {
    return new TextDecoder(encoding, { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

function looksLikeMojibake(value: string): boolean {
  return /[ÃÂÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ][\u0080-\u00bf]/.test(value)
    || /[êëìíîï][\u0080-\u00bf]/i.test(value)
    || /[°±²³´µ¶·¸¹º»¼½¾¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]{3,}/.test(value);
}

function readabilityScore(value: string): number {
  const hangul = (value.match(/[가-힣]/g) || []).length;
  const mojibakeMarkers = (value.match(/[°±²³´µ¶·¸¹º»¼½¾¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]/g) || []).length;
  return hangul * 10 - mojibakeMarkers;
}

function assertSafeArchivePath(path: string) {
  if (path.startsWith("/") || /^[a-zA-Z]:\//.test(path)) {
    throw archiveError("unsafe_archive_path", `안전하지 않은 ZIP 경로입니다: ${path}`);
  }

  const parts = path.split("/");
  if (parts.some((part) => part === "..")) {
    throw archiveError("unsafe_archive_path", `안전하지 않은 ZIP 경로입니다: ${path}`);
  }
}

function shouldSkipArchivePath(path: string) {
  const parts = path.split("/").filter(Boolean);
  return parts.some((part) => (
    part === "__MACOSX" ||
    part === ".DS_Store" ||
    part.startsWith("._") ||
    part.startsWith(".") ||
    part.endsWith("_cuts")
  ));
}

function archiveKindForExtension(extension: string): Exclude<InputKind, "directory"> | null {
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (DOCUMENT_EXTENSIONS.has(extension)) return "pdf";
  if (ARCHIVE_EXTENSIONS.has(extension)) return "zip";
  return null;
}

function archiveError(code: string, message: string) {
  return Object.assign(new Error(message), { code });
}

function concatBytes(chunks: Uint8Array[], length: number) {
  const bytes = new Uint8Array(length);
  let offset = 0;
  chunks.forEach((chunk) => {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  });
  return bytes;
}

function mimeTypeForExtension(extension: string) {
  if (extension === "jpg" || extension === "jpeg") return "image/jpeg";
  if (extension === "png") return "image/png";
  if (extension === "webp") return "image/webp";
  if (extension === "pdf") return "application/pdf";
  if (extension === "zip") return "application/zip";
  return "application/octet-stream";
}
