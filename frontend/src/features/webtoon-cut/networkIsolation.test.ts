// @ts-nocheck -- Vitest runs this source audit in Node; the app tsconfig intentionally targets the browser.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("webtoon cut network isolation", () => {
  it("contains no network transport in the feature implementation", () => {
    const root = existsSync(join(process.cwd(), "src/features/webtoon-cut"))
      ? join(process.cwd(), "src/features/webtoon-cut")
      : join(process.cwd(), "frontend/src/features/webtoon-cut");
    const source = readdirSync(root)
      .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
      .map((name) => readFileSync(join(root, name), "utf8"))
      .join("\n");

    expect(source).not.toMatch(/\b(fetch|XMLHttpRequest|WebSocket|sendBeacon)\b/);
  });
});
