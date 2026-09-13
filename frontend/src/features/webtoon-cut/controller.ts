import { runWebtoonCutJob, type RunnerJobRequest, type RunnerPorts } from "./runner";
import type { WebtoonCutManifest } from "./types";

export type WebtoonCutControllerEvent =
  | { type: "running"; jobId: string }
  | { type: "completed"; manifest: WebtoonCutManifest }
  | { type: "failed"; error: unknown };

export class WebtoonCutController {
  private listeners = new Set<(event: WebtoonCutControllerEvent) => void>();
  private abortController: AbortController | null = null;

  constructor(private readonly ports: RunnerPorts) {}

  subscribe(listener: (event: WebtoonCutControllerEvent) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async start(request: RunnerJobRequest) {
    this.abortController = new AbortController();
    this.emit({ type: "running", jobId: request.jobId });
    try {
      const manifest = await runWebtoonCutJob(request, this.ports, this.abortController.signal);
      this.emit({ type: "completed", manifest });
    } catch (error) {
      this.emit({ type: "failed", error });
      throw error;
    }
  }

  async pause() {
    this.abortController?.abort(new DOMException("Paused", "AbortError"));
  }

  dispose() {
    this.abortController?.abort(new DOMException("Disposed", "AbortError"));
    this.listeners.clear();
  }

  private emit(event: WebtoonCutControllerEvent) {
    this.listeners.forEach((listener) => listener(event));
  }
}
