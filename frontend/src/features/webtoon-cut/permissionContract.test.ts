// @ts-nocheck -- Source contract test runs in Node and inspects browser-only code.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("webtoon cut browser permission contract", () => {
  it("requests read-only permission for input folder selection and readwrite only for work folder connection", () => {
    const source = readFileSync(join(process.cwd(), "src/screens/webtoonCutScreen.tsx"), "utf8");

    expect(source).toContain("showDirectoryPicker({ mode: \"read\" })");
    expect(source).toContain("showDirectoryPicker({ mode: \"readwrite\" })");
    expect(source.indexOf("async function chooseInputDirectory")).toBeLessThan(source.indexOf("showDirectoryPicker({ mode: \"read\" })"));
    expect(source.indexOf("async function connectDefaultWorkspace")).toBeLessThan(source.indexOf("showDirectoryPicker({ mode: \"readwrite\" })"));
  });
});
