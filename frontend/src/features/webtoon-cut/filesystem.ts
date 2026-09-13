import { SUPPORTED_ARCHIVE_EXTENSIONS, SUPPORTED_DOCUMENT_EXTENSIONS, SUPPORTED_IMAGE_EXTENSIONS } from "./constants";
import { fileExtension, normalizeForComparison } from "./naming";
import type { DiscoveredInput, InputKind, SourceFingerprint } from "./types";

export type WritablePort = {
  write(data: Blob | BufferSource | string): Promise<void>;
  close(): Promise<void>;
};

export type FilePort = {
  kind: "file";
  name: string;
  getFile(): Promise<File>;
  createWritable(): Promise<WritablePort>;
};

export type DirectoryPort = {
  kind: "directory";
  name: string;
  entries(): AsyncIterable<FilePort | DirectoryPort>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FilePort>;
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<DirectoryPort>;
  removeEntry?(name: string): Promise<void>;
};

type NativePermissionMode = { mode: "read" | "readwrite" };
type NativePermissionHandle = FileSystemDirectoryHandle & {
  queryPermission?: (descriptor?: NativePermissionMode) => Promise<PermissionState>;
  requestPermission?: (descriptor?: NativePermissionMode) => Promise<PermissionState>;
};

const SUPPORTED_EXTENSIONS = new Set<string>([
  ...SUPPORTED_IMAGE_EXTENSIONS,
  ...SUPPORTED_DOCUMENT_EXTENSIONS,
  ...SUPPORTED_ARCHIVE_EXTENSIONS
]);

export async function requestWorkingDirectory(): Promise<FileSystemDirectoryHandle> {
  if (!window.showDirectoryPicker) {
    throw new Error("이미지 컷 분할은 데스크톱 Chrome 또는 Edge의 디렉토리 쓰기 권한이 필요합니다.");
  }

  const handle = await window.showDirectoryPicker({ mode: "readwrite" });
  const permissionHandle = handle as NativePermissionHandle;
  const currentPermission = await permissionHandle.queryPermission?.({ mode: "readwrite" });
  if (currentPermission === "granted") return handle;

  const requestedPermission = await permissionHandle.requestPermission?.({ mode: "readwrite" });
  if (requestedPermission && requestedPermission !== "granted") {
    throw new Error("출력 폴더를 만들 수 있도록 디렉토리 쓰기 권한을 허용해야 합니다.");
  }

  return handle;
}

export async function discoverInputs(root: FileSystemDirectoryHandle | DirectoryPort): Promise<DiscoveredInput[]> {
  const directory = toDirectoryPort(root);
  const discovered: DiscoveredInput[] = [];
  await collectInputs(directory, "", discovered);
  return discovered.sort((left, right) => (
    normalizeForComparison(left.relativePath).localeCompare(normalizeForComparison(right.relativePath), "ko")
  ));
}

export async function writeAtomically(
  parent: FileSystemDirectoryHandle | DirectoryPort,
  name: string,
  bytes: Blob | Uint8Array | ArrayBuffer | string
): Promise<void> {
  const directory = toDirectoryPort(parent);
  const partialName = `${name}.partial`;
  const partialHandle = await directory.getFileHandle(partialName, { create: true });
  const partialWritable = await partialHandle.createWritable();
  await partialWritable.write(toWritableData(bytes));
  await partialWritable.close();

  const partialFile = await partialHandle.getFile();
  const finalHandle = await directory.getFileHandle(name, { create: true });
  const finalWritable = await finalHandle.createWritable();
  await finalWritable.write(partialFile);
  await finalWritable.close();

  await directory.removeEntry?.(partialName);
}

function toWritableData(bytes: Blob | Uint8Array | ArrayBuffer | string): Blob | ArrayBuffer | string {
  if (bytes instanceof Uint8Array) {
    const arrayBuffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(arrayBuffer).set(bytes);
    return arrayBuffer;
  }
  return bytes;
}

async function collectInputs(directory: DirectoryPort, prefix: string, discovered: DiscoveredInput[]) {
  const entries: Array<FilePort | DirectoryPort> = [];
  for await (const entry of directory.entries()) {
    entries.push(entry);
  }

  entries.sort((left, right) => normalizeForComparison(left.name).localeCompare(normalizeForComparison(right.name), "ko"));

  for (const entry of entries) {
    if (shouldSkipEntry(entry.name)) continue;

    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.kind === "directory") {
      await collectInputs(entry, relativePath, discovered);
      continue;
    }

    const extension = fileExtension(entry.name);
    if (!SUPPORTED_EXTENSIONS.has(extension)) continue;

    const file = await entry.getFile();
    const kind = inputKindForExtension(extension);
    if (!kind) continue;

    discovered.push({
      kind,
      relativePath: normalizeForComparison(relativePath),
      fileName: entry.name,
      extension,
      fingerprint: fingerprintForFile(file),
      handle: entry
    });
  }
}

function inputKindForExtension(extension: string): Exclude<InputKind, "directory"> | null {
  if ((SUPPORTED_IMAGE_EXTENSIONS as readonly string[]).includes(extension)) return "image";
  if ((SUPPORTED_DOCUMENT_EXTENSIONS as readonly string[]).includes(extension)) return "pdf";
  if ((SUPPORTED_ARCHIVE_EXTENSIONS as readonly string[]).includes(extension)) return "zip";
  return null;
}

function shouldSkipEntry(name: string): boolean {
  const normalized = normalizeForComparison(name);
  return (
    normalized === "__MACOSX" ||
    normalized === ".DS_Store" ||
    normalized.startsWith("._") ||
    normalized.startsWith(".") ||
    normalized.endsWith("_cuts")
  );
}

function fingerprintForFile(file: File): SourceFingerprint {
  return {
    name: file.name,
    size: file.size,
    lastModified: file.lastModified
  };
}

function toDirectoryPort(directory: FileSystemDirectoryHandle | DirectoryPort): DirectoryPort {
  if (isDirectoryPort(directory)) return directory;
  return new BrowserDirectoryPort(directory);
}

function isDirectoryPort(directory: FileSystemDirectoryHandle | DirectoryPort): directory is DirectoryPort {
  // 2026-09-13: 브라우저의 실제 FileSystemDirectoryHandle도 entries()를 갖지만
  // [name, handle] 튜플을 내놓기 때문에 DirectoryPort로 오인하면 collectInputs가
  // entry.name=undefined로 순회하다 TypeError를 던진다(폴더 선택 무반응 버그).
  // 네이티브 핸들은 values()/keys()를 추가로 가지므로 이를 기준으로 구분한다.
  if (typeof globalThis.FileSystemDirectoryHandle !== "undefined" && directory instanceof globalThis.FileSystemDirectoryHandle) {
    return false;
  }
  const candidate = directory as DirectoryPort & { values?: unknown };
  return typeof candidate.entries === "function" && typeof candidate.values !== "function";
}

class BrowserFilePort implements FilePort {
  readonly kind = "file" as const;

  constructor(private readonly handle: FileSystemFileHandle) {}

  get name() {
    return this.handle.name;
  }

  getFile() {
    return this.handle.getFile();
  }

  async createWritable(): Promise<WritablePort> {
    return this.handle.createWritable();
  }
}

class BrowserDirectoryPort implements DirectoryPort {
  readonly kind = "directory" as const;

  constructor(private readonly handle: FileSystemDirectoryHandle) {}

  get name() {
    return this.handle.name;
  }

  async *entries(): AsyncIterable<FilePort | DirectoryPort> {
    for await (const child of this.handle.values()) {
      if (child.kind === "file") {
        yield new BrowserFilePort(child as FileSystemFileHandle);
      } else {
        yield new BrowserDirectoryPort(child as FileSystemDirectoryHandle);
      }
    }
  }

  async getFileHandle(name: string, options?: { create?: boolean }) {
    return new BrowserFilePort(await this.handle.getFileHandle(name, options));
  }

  async getDirectoryHandle(name: string, options?: { create?: boolean }) {
    return new BrowserDirectoryPort(await this.handle.getDirectoryHandle(name, options));
  }

  async removeEntry(name: string) {
    await this.handle.removeEntry(name);
  }
}
