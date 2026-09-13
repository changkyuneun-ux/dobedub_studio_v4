import { runWebtoonCutJob } from "./runner";
import type { WorkerRequest, WorkerEvent } from "./types";
import type { RunnerJobRequest } from "./runner";

let activeController: AbortController | null = null;
let activeJobId = "";

self.addEventListener("message", async (event: MessageEvent<WorkerRequest>) => {
  const request = event.data;
  if (request.type === "pause") {
    if (!activeJobId || activeJobId === request.jobId) {
      activeController?.abort(new DOMException("중단 요청", "AbortError"));
    }
    return;
  }
  if (request.type !== "start") return;
  const { outputRoot, ...runnerRequest } = request.request;
  const controller = new AbortController();
  activeController = controller;
  activeJobId = request.request.jobId;
  try {
    const manifest = await runWebtoonCutJob(
      runnerRequest as RunnerJobRequest,
      {
        output: outputRoot,
        onProgress: (progress) => {
          self.postMessage({
            type: "progress",
            jobId: request.request.jobId,
            ...progress
          } satisfies WorkerEvent);
        }
      },
      controller.signal
    );
    if (manifest.status === "paused") {
      self.postMessage({
        type: "paused",
        jobId: request.request.jobId,
        manifest
      } satisfies WorkerEvent);
    } else {
      self.postMessage({
        type: "completed",
        jobId: request.request.jobId,
        outcome: terminalOutcome(manifest.status),
        manifest,
        reviewUnitIds: [],
        unresolvedUnitIds: []
      } satisfies WorkerEvent);
    }
  } catch (error) {
    self.postMessage({
      type: "failed",
      jobId: request.request.jobId,
      code: typeof error === "object" && error && "code" in error ? String(error.code) : "worker_error",
      message: error instanceof Error ? error.message : "컷 분할 Worker 오류가 발생했습니다."
    } satisfies WorkerEvent);
  } finally {
    if (activeController === controller) {
      activeController = null;
      activeJobId = "";
    }
  }
});

function terminalOutcome(status: string): "completed" | "completed_with_review" | "completed_with_errors" {
  if (status === "completed" || status === "completed_with_review" || status === "completed_with_errors") return status;
  return "completed_with_errors";
}
