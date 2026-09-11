import { describe, expect, it, vi } from "vitest";
import { createWebtoonCutJobStore } from "./jobStore";

describe("webtoon cut job store", () => {
  it("keeps an active job when its screen subscriber detaches", async () => {
    const controller = fakeController();
    const store = createWebtoonCutJobStore(controller);
    const unsubscribe = store.subscribe(() => undefined);

    await store.start({ jobId: "job" });
    unsubscribe();

    expect(store.getSnapshot().status).toBe("running");
    expect(controller.dispose).not.toHaveBeenCalled();
  });
});

function fakeController() {
  return {
    start: vi.fn(async () => undefined),
    pause: vi.fn(async () => undefined),
    dispose: vi.fn(),
    subscribe: vi.fn(() => () => undefined)
  };
}
