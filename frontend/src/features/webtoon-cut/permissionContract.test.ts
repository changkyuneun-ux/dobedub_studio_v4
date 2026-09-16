// @ts-nocheck -- Source contract test runs in Node and inspects browser-only code.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("webtoon cut server pipeline permission contract", () => {
  it("does not request browser directory permissions when using S3 server processing", () => {
    const source = readFileSync(join(process.cwd(), "src/screens/webtoonCutScreen.tsx"), "utf8");

    expect(source).toContain("S3 업로드 · 서버 컷 분리 · I2V 입력 연결");
    expect(source).toContain("presignWebtoonCutUpload");
    expect(source).toContain("completeWebtoonCutUpload");
    expect(source).not.toContain("showDirectoryPicker");
  });
});
