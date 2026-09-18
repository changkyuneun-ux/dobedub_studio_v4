import { describe, expect, it } from "vitest";

import { formatKstTimestamp, formatTimestamp } from "./format";

describe("KST timestamp formatting", () => {
  it("converts an explicit UTC timestamp to KST without seconds", () => {
    expect(formatKstTimestamp("2026-09-18T00:30:59Z")).toBe("2026-09-18:09:30");
  });

  it("treats a naive database timestamp as UTC", () => {
    expect(formatKstTimestamp("2026-09-18T15:05:42")).toBe("2026-09-19:00:05");
  });

  it("keeps an API-provided KST timestamp in KST", () => {
    expect(formatKstTimestamp("2026-09-18 09:30:59 KST")).toBe("2026-09-18:09:30");
  });

  it("uses the explicit UTC companion instead of displaying both zones", () => {
    expect(formatTimestamp("2026-09-18 09:30:59 KST", "2026-09-18T00:30:59Z")).toBe("2026-09-18:09:30");
  });
});
