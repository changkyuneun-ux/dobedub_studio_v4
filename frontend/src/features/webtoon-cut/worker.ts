import { runWebtoonCutJob } from "./runner";
import type { WorkerRequest, WorkerEvent } from "./types";
import type { RunnerJobRequest } from "./runner";

self.addEventListener("message", async (event: MessageEvent<WorkerRequest>) => {
  const request = event.data;
  if (request.type !== "start") return;
  const { outputRoot, ...runnerRequest } = request.request;
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
      new AbortController().signal
    );
    self.postMessage({
      type: "completed",
      jobId: request.request.jobId,
      outcome: terminalOutcome(manifest.status),
      manifest,
      reviewUnitIds: [],
      unresolvedUnitIds: []
    } satisfies WorkerEvent);
  } catch (error) {
    self.postMessage({
      type: "failed",
      jobId: request.request.jobId,
      code: typeof error === "object" && error && "code" in error ? String(error.code) : "worker_error",
      message: error instanceof Error ? error.message : "컷 분할 Worker 오류가 발생했습니다."
    } satisfies WorkerEvent);
  }
});

function terminalOutcome(status: string): "completed" | "completed_with_review" | "completed_with_errors" {
  if (status === "completed" || status === "completed_with_review" || status === "completed_with_errors") return status;
  return "completed_with_errors";
}
