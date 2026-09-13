type ControllerLike = {
  start(request: unknown): Promise<void>;
  pause(): Promise<void>;
  dispose(): void;
  subscribe(listener: (event: unknown) => void): () => void;
};

export type WebtoonCutStoreSnapshot = {
  status: "idle" | "running" | "paused" | "completed" | "failed";
};

export function createWebtoonCutJobStore(controller: ControllerLike) {
  let snapshot: WebtoonCutStoreSnapshot = { status: "idle" };
  const listeners = new Set<() => void>();
  const unsubscribeController = controller.subscribe(() => undefined);

  function emit() {
    listeners.forEach((listener) => listener());
  }

  return {
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot() {
      return snapshot;
    },
    async start(request: unknown) {
      snapshot = { status: "running" };
      emit();
      await controller.start(request);
    },
    async pause() {
      await controller.pause();
      snapshot = { status: "paused" };
      emit();
    },
    disposeForSessionEnd() {
      unsubscribeController();
      controller.dispose();
      snapshot = { status: "idle" };
      listeners.clear();
    }
  };
}
