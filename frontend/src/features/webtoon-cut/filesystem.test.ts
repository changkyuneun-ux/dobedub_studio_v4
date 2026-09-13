import { describe, expect, it } from "vitest";
import type { DirectoryPort, FilePort, WritablePort } from "./filesystem";
import { discoverInputs, writeAtomically } from "./filesystem";

type MemoryNode = Uint8Array | MemoryDirectoryTree;

type MemoryDirectoryTree = {
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

  constructor(readonly name: string, private bytes: Uint8Array) {}

  async getFile() {
    const arrayBuffer = new ArrayBuffer(this.bytes.byteLength);
    new Uint8Array(arrayBuffer).set(this.bytes);
    return new File([arrayBuffer], this.name);
  }

  async createWritable() {
    return new MemoryWritable((bytes) => {
      this.bytes = bytes;
    });
  }
}

class MemoryDirectory implements DirectoryPort {
  readonly kind = "directory" as const;
  private entriesByName = new Map<string, MemoryFile | MemoryDirectory>();

  constructor(readonly name: string, tree: Record<string, MemoryNode>) {
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

function memoryDirectory(tree: Record<string, MemoryNode>) {
  return new MemoryDirectory("root", tree);
}

function bytes(length: number) {
  return new Uint8Array(length).fill(1);
}

describe("webtoon cut filesystem boundary", () => {
  it("excludes hidden metadata and generated output trees", async () => {
    const root = memoryDirectory({
      "page.jpg": bytes(1),
      ".DS_Store": bytes(1),
      "._page.jpg": bytes(1),
      "page_cuts": { "page-01.png": bytes(1) }
    });

    expect((await discoverInputs(root)).map((item) => item.relativePath)).toEqual(["page.jpg"]);
  });

  it("renames a complete partial write and leaves no partial file", async () => {
    const root = memoryDirectory({});

    await writeAtomically(root, "page-01.png", bytes(3));

    expect(root.files()).toEqual(["page-01.png"]);
  });

});

// 2026-09-13 회귀: 브라우저의 실제 FileSystemDirectoryHandle은 entries()가
// [name, handle] 튜플을 내놓고 values()가 핸들을 내놓는다. 이전 isDirectoryPort는
// entries 존재만 보고 네이티브 핸들을 DirectoryPort로 오인해 폴더 선택이 무반응이었다.
describe("discoverInputs with a native-like FileSystemDirectoryHandle", () => {
  function nativeFile(name: string) {
    return {
      kind: "file" as const,
      name,
      async getFile() {
        return new File([new Uint8Array([1, 2, 3])], name);
      },
      async createWritable() {
        throw new Error("not used");
      }
    };
  }

  function nativeDirectory(name: string, children: Array<ReturnType<typeof nativeFile> | NativeDirectoryLike>): NativeDirectoryLike {
    return {
      kind: "directory" as const,
      name,
      async *entries() {
        for (const child of children) yield [child.name, child] as const;
      },
      async *values() {
        for (const child of children) yield child;
      },
      async *keys() {
        for (const child of children) yield child.name;
      },
      async getFileHandle() {
        throw new Error("not used");
      },
      async getDirectoryHandle() {
        throw new Error("not used");
      }
    };
  }

  type NativeDirectoryLike = {
    kind: "directory";
    name: string;
    entries(): AsyncIterable<readonly [string, unknown]>;
    values(): AsyncIterable<unknown>;
    keys(): AsyncIterable<string>;
    getFileHandle(): Promise<unknown>;
    getDirectoryHandle(): Promise<unknown>;
  };

  it("wraps the native handle instead of iterating [name, handle] tuples", async () => {
    const root = nativeDirectory("수영복", [
      nativeFile("001.png"),
      nativeDirectory("chapter2", [nativeFile("002.jpg"), nativeFile("notes.txt")])
    ]);
    const discovered = await discoverInputs(root as unknown as FileSystemDirectoryHandle);
    expect(discovered.map((entry) => entry.relativePath)).toEqual(["001.png", "chapter2/002.jpg"]);
    expect(discovered.every((entry) => typeof (entry.handle as { getFile?: unknown } | undefined)?.getFile === "function")).toBe(true);
  });
});
