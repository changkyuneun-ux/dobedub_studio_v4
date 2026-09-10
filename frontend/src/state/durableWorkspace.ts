import { GrokImagePromptDraftResponse, PromptGenerationBatchResponse, ResolutionTier, UploadResponse } from "../api/client";

export type PromptUploadItem = UploadResponse & { requestedFrames: number };

export type PromptWorkspaceSnapshot = {
  workflowId: string;
  uploads: PromptUploadItem[];
  drafts: Record<string, GrokImagePromptDraftResponse>;
  negativePrompt: string;
  batchId?: string;
};

export type RunpodWorkspaceSnapshot = {
  selectedDraftIds: string[];
  workflowOverrides: Record<string, string>;
  qualityOverrides: Record<string, ResolutionTier>;
  requestBatchId?: string;
};

const prefix = "dobedub.v4.durable-workspace";

function load<T>(key: string, fallback: T): T {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) as T : fallback;
  } catch {
    return fallback;
  }
}

function save<T>(key: string, value: T) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The server remains canonical; a full browser storage is only a UX fallback.
  }
}

export function loadPromptWorkspace(userId: string): PromptWorkspaceSnapshot {
  return load(`${prefix}.prompt.${userId}`, {
    workflowId: "", uploads: [], drafts: {}, negativePrompt: "", batchId: undefined
  });
}

export function savePromptWorkspace(userId: string, snapshot: PromptWorkspaceSnapshot) {
  save(`${prefix}.prompt.${userId}`, snapshot);
}

export function loadRunpodWorkspace(userId: string): RunpodWorkspaceSnapshot {
  return load(`${prefix}.runpod.${userId}`, {
    selectedDraftIds: [], workflowOverrides: {}, qualityOverrides: {}, requestBatchId: undefined
  });
}

export function saveRunpodWorkspace(userId: string, snapshot: RunpodWorkspaceSnapshot) {
  save(`${prefix}.runpod.${userId}`, snapshot);
}

export function promptWorkspaceFromBatch(batch: PromptGenerationBatchResponse): Pick<PromptWorkspaceSnapshot, "workflowId" | "drafts" | "batchId"> {
  return {
    workflowId: batch.workflowId,
    drafts: Object.fromEntries(batch.items.map((item) => [item.assetId, item])),
    batchId: batch.id
  };
}
