import type { DirectoryPort, FilePort, WritablePort } from "../filesystem";

export type MemoryNode = Uint8Array | MemoryDirectoryTree;

export type MemoryDirectoryTree = {
  [name: string]: MemoryNode;
};

class MemoryWritable implements WritablePort {
  private chunks: Uint8Array[] = [];

  constructor(private readonly closeCallback: (bytes: Uint8Array) => void) {}

  async write(data: Blob | BufferSource | string) {
    if (typeof data === "string") {
      this.chunks.push(new TextEncoder().encode(data));
    } else if (data instanceof Blob) {
      this.chunks.push(new Uint8Array(await data.arrayBuffer()));
    } else if (data instanceof ArrayBuffer) {
      this.chunks.push(new Uint8Array(data));
    } else {
      this.chunks.push(new Uint8Array(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)));
    }
  }

  async close() {
    const total = this.chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
    const bytes = new Uint8Array(total);
    let offset = 0;
    this.chunks.forEach((chunk) => {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    });
    this.closeCallback(bytes);
  }
}

class MemoryFile implements FilePort {
  readonly kind = "file" as const;

  constructor(readonly name: string, private bytesValue: Uint8Array) {}

  async getFile() {
    const arrayBuffer = new ArrayBuffer(this.bytesValue.byteLength);
    new Uint8Array(arrayBuffer).set(this.bytesValue);
    return new File([arrayBuffer], this.name);
  }

  async createWritable() {
    return new MemoryWritable((bytes) => {
      this.bytesValue = bytes;
    });
  }
}

export class MemoryDirectory implements DirectoryPort {
  readonly kind = "directory" as const;
  private entriesByName = new Map<string, MemoryFile | MemoryDirectory>();

  constructor(readonly name: string, tree: MemoryDirectoryTree) {
    Object.entries(tree).forEach(([entryName, node]) => {
      this.entriesByName.set(
        entryName,
        node instanceof Uint8Array ? new MemoryFile(entryName, node) : new MemoryDirectory(entryName, node)
      );
    });
  }

  async *entries() {
    yield* this.entriesByName.values();
  }

  async getFileHandle(name: string, options?: { create?: boolean }) {
    const existing = this.entriesByName.get(name);
    if (existing?.kind === "file") return existing;
    if (!options?.create) throw new Error(`missing file: ${name}`);
    const file = new MemoryFile(name, new Uint8Array());
    this.entriesByName.set(name, file);
    return file;
  }

  async getDirectoryHandle(name: string, options?: { create?: boolean }) {
    const existing = this.entriesByName.get(name);
    if (existing?.kind === "directory") return existing;
    if (!options?.create) throw new Error(`missing directory: ${name}`);
    const directory = new MemoryDirectory(name, {});
    this.entriesByName.set(name, directory);
    return directory;
  }

  async removeEntry(name: string) {
    this.entriesByName.delete(name);
  }

  files() {
    return [...this.entriesByName.keys()].sort((left, right) => left.localeCompare(right, "ko"));
  }
}

export function memoryDirectory(tree: MemoryDirectoryTree) {
  return new MemoryDirectory("root", tree);
}

export function bytes(length: number) {
  return new Uint8Array(length).fill(1);
}

export function validPng(width: number, height: number) {
  const bytes = new Uint8Array(33);
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], 0);
  bytes.set([0x00, 0x00, 0x00, 0x0d], 8);
  bytes.set([0x49, 0x48, 0x44, 0x52], 12);
  writeUint32(bytes, 16, width);
  writeUint32(bytes, 20, height);
  return bytes;
}

function writeUint32(bytes: Uint8Array, offset: number, value: number) {
  bytes[offset] = (value >>> 24) & 0xff;
  bytes[offset + 1] = (value >>> 16) & 0xff;
  bytes[offset + 2] = (value >>> 8) & 0xff;
  bytes[offset + 3] = value & 0xff;
}
