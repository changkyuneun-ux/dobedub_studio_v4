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

  it("repairs UTF-8 ZIP names that were decoded as Latin-1 mojibake", () => {
    const mojibake = "과학사 100 원본.jpg"
      .split("")
      .map((char) => new TextEncoder().encode(char))
      .flatMap((bytes) => [...bytes].map((byte) => String.fromCharCode(byte)))
      .join("");

    expect(validateArchiveEntry(entry(mojibake, 10, 10))).toMatchObject({
      normalizedName: "과학사 100 원본.jpg",
      extension: "jpg"
    });
  });

  it("repairs mojibake names before deriving Korean output directories", () => {
    const sourceName = "수영복 입은 형수님_019화_002.jpg";
    const mojibake = sourceName
      .split("")
      .map((char) => new TextEncoder().encode(char))
      .flatMap((bytes) => [...bytes].map((byte) => String.fromCharCode(byte)))
      .join("");

    expect(validateArchiveEntry(entry(mojibake, 10, 10))?.normalizedName).toBe(sourceName);
  });

  it("repairs EUC-KR ZIP names that were decoded as Latin-1 mojibake", () => {
    const mojibake = "°úÇÐ»ç_3±Ç_³»Áö_ÀÎ¼â¿ë_¼öÁ¤.pdf";

    expect(validateArchiveEntry(entry(mojibake, 10, 10))?.normalizedName).toBe("과학사_3권_내지_인쇄용_수정.pdf");
  });
});
