import { describe, expect, it } from "vitest";
import type { ZipEntryMeta } from "./archive";
import { validateArchiveEntry } from "./archive";

function entry(name: string, originalSize: number, compressedSize: number): ZipEntryMeta {
  return { name, originalSize, compressedSize, directory: false };
}

describe("webtoon cut ZIP safety", () => {
  it.each(["../escape.jpg", "/absolute.jpg", "C:/escape.jpg", "ok/../../escape.png"])(
    "rejects unsafe ZIP path %s",
    (name) => {
      expect(() => validateArchiveEntry(entry(name, 10, 10))).toThrow(/안전하지 않은 ZIP 경로/);
    }
  );

  it("ignores metadata and unsupported files", () => {
    expect(validateArchiveEntry(entry("__MACOSX/._page.jpg", 10, 10))).toBeNull();
    expect(validateArchiveEntry(entry("notes.txt", 10, 10))).toBeNull();
  });

  it("rejects an excessive compression ratio", () => {
    expect(() => validateArchiveEntry(entry("page.jpg", 201_000, 1_000))).toThrow(/압축비/);
  });
});
