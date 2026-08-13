import {
  apiClient,
  WorkflowSchema,
  HistoryItem,
  HistorySegment,
  ConfigControl,
  UploadResponse,
  WorkflowItem,
  InputImage,
  OutputAsset
} from "../api/client";
import { positivePromptEntries, negativePromptEntries, promptForSegment } from "./prompts";
import { fileUrlWithMode } from "./format";

export type SegmentState = {
  index: number;
  nodeId: string;
  subgraphName: string;
  displayName: string;
  startImageIndex: number;
  endImageIndex: number;
  progress: number;
  positivePrompt: string;
  defaultNegativePrompt: string;
  negativePrompt: string;
  negativePromptAddition: string;
  config: Record<string, string | number>;
  configControls: ConfigControl[];
};

export type KeyframeState = {
  index: number;
  file: File | null;
  upload: UploadResponse | null;
  previewUrl: string;
  metaText: string;
  uploading: boolean;
  error: string;
};

export function createSegmentsFromSchema(schema: WorkflowSchema): SegmentState[] {
  return (schema.segments || []).map((segment, index) => ({
    index: segment.index || index + 1,
    nodeId: segment.nodeId || "",
    subgraphName: segment.subgraphName || "Subgraph",
    displayName: segment.displayName || `${segment.subgraphName || "Subgraph"}_${segment.index || index + 1}`,
    // 단일 이미지 I2V workflow는 endImageIndex를 null로 전달한다. `||`를 쓰면
    // 이 의도된 빈값이 KF 2로 바뀌어 실행 전 확인에 가짜 끝 프레임이 생긴다.
    startImageIndex: Number(segment.startImageIndex ?? index + 1),
    endImageIndex: Number(segment.endImageIndex ?? segment.startImageIndex ?? index + 1),
    progress: 0,
    positivePrompt: segment.defaultPositivePrompt || "",
    defaultNegativePrompt: segment.defaultNegativePrompt || "",
    negativePrompt: segment.defaultNegativePrompt || "",
    negativePromptAddition: "",
    config: segment.config || {},
    configControls: segment.configControls || []
  }));
}

export function createSegmentsFromHistory(schema: WorkflowSchema, item: HistoryItem): SegmentState[] {
  const baseSegments = createSegmentsFromSchema(schema);
  const sourceSegments = item.segments || [];
  const wanSegments = item.wanNodeConfig?.segments || [];
  return baseSegments.map((segment, index) => {
    const source = sourceSegments[index] || sourceSegments.find((candidate) => Number(candidate.index) === segment.index) || {};
    const wanSource = wanSegments[index] || wanSegments.find((candidate) => Number(candidate.index) === segment.index) || {};
    const positive = promptForSegment(positivePromptEntries(item), segment.index) || source.positivePrompt || item.prompt || segment.positivePrompt;
    const negative =
      promptForSegment(negativePromptEntries(item), segment.index) ||
      source.negativePromptAddition ||
      source.negativePrompt ||
      item.negativePrompt ||
      segment.negativePrompt;
    const { seed: _baseSeed, Seed: _legacyBaseSeed, ...baseConfig } = segment.config;
    const { seed: _historySeed, Seed: _legacyHistorySeed, ...historyConfig } = item.configJson || {};
    const { seed: _sourceSeed, Seed: _legacySourceSeed, ...sourceConfig } = source.config || {};
    const wanConfig = configFromWanNodeSegment(wanSource);
    const { seed: _wanSeed, Seed: _legacyWanSeed, ...wanConfigWithoutSeed } = wanConfig;
    return {
      ...segment,
      positivePrompt: positive,
      defaultNegativePrompt: segment.defaultNegativePrompt,
      negativePrompt: negative,
      negativePromptAddition: source.negativePromptAddition || negative,
      config: {
        ...baseConfig,
        ...historyConfig,
        ...sourceConfig,
        ...wanConfigWithoutSeed
      }
    };
  });
}

export function configFromWanNodeSegment(segment: HistorySegment & { params?: Array<{ uiKey?: string; value?: string | number }> }) {
  const config: Record<string, string | number> = { ...(segment?.config || {}) };
  (segment?.params || []).forEach((param) => {
    if (param.uiKey && param.value !== undefined && param.value !== null) {
      config[param.uiKey] = param.value;
    }
  });
  return config;
}

export function createKeyframe(index: number): KeyframeState {
  return {
    index,
    file: null,
    upload: null,
    previewUrl: "",
    metaText: "Image: 1024x1024",
    uploading: false,
    error: ""
  };
}

export function createKeyframes(count: number): KeyframeState[] {
  return Array.from({ length: Math.max(1, count || 1) }, (_, index) => createKeyframe(index + 1));
}

export function createKeyframesFromHistory(schema: WorkflowSchema, item: HistoryItem): KeyframeState[] {
  const images = historyInputImages(item);
  return createKeyframes(schema.keyframeCount || images.length || 1).map((keyframe) => {
    const image = images.find((candidate) => Number(candidate.index) === keyframe.index) || images[keyframe.index - 1];
    if (!image?.assetId) {
      return keyframe;
    }
    const fileName = image.fileName || image.filename || `history-image-${keyframe.index}.png`;
    return {
      ...keyframe,
      file: null,
      upload: {
        assetId: image.assetId,
        fileName,
        mimeType: "image/*",
        sizeBytes: 0,
        downloadUrl: `/api/files/${image.assetId}`
      },
      previewUrl: `/api/files/${image.assetId}`,
      metaText: `${image.assetId} (${fileName})`,
      uploading: false,
      error: ""
    };
  });
}

export function releaseKeyframePreviews(items: KeyframeState[]) {
  items.forEach((keyframe) => {
    if (keyframe.previewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(keyframe.previewUrl);
    }
  });
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

export function formatConfigValue(value: string | number | null, type = "float") {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return String(value ?? "");
  }
  return type === "int" ? String(Math.round(number)) : String(Number(number.toFixed(2)));
}

export function recordText(record: Record<string, unknown>, key: string) {
  const value = record[key];
  if (value === undefined || value === null) {
    return "";
  }
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : JSON.stringify(value);
}

export function workflowIdFromHistoryItem(item: HistoryItem, workflows: WorkflowItem[], fallbackWorkflowId: string) {
  const candidates = [item.workflowId, item.workflowName, item.workflow].filter(Boolean).map(String);
  const exact = candidates.find((candidate) => workflows.some((workflow) => workflow.id === candidate));
  if (exact) {
    return exact;
  }
  const keyText = candidates.join(" ");
  const keyMatch = keyText.match(/(\d+)\s*[-_]?key/i);
  if (keyMatch) {
    const workflowId = `${keyMatch[1]}-images.json`;
    if (workflows.some((workflow) => workflow.id === workflowId)) {
      return workflowId;
    }
  }
  const imageCount = historyInputImages(item).length || item.keyframes?.length;
  if (imageCount) {
    const workflowId = `${imageCount}-images.json`;
    if (workflows.some((workflow) => workflow.id === workflowId)) {
      return workflowId;
    }
  }
  return fallbackWorkflowId;
}

export function historyInputImages(item: HistoryItem): InputImage[] {
  if (item.inputImages?.length) {
    return item.inputImages.map((image, index) => ({
      index: Number(image.index || index + 1),
      assetId: image.assetId || "",
      fileName: image.fileName || image.filename || "-"
    }));
  }
  const inputAssets = item.inputAssets || [];
  const keyframes = item.keyframes || [];
  const count = Math.max(inputAssets.length, keyframes.length);
  return Array.from({ length: count }, (_, index) => {
    const keyframe = keyframes[index] || {};
    return {
      index: Number(keyframe.index || index + 1),
      assetId: keyframe.uploadId || inputAssets[index] || "",
      fileName: keyframe.fileName || "-"
    };
  }).filter((image) => image.assetId || image.fileName !== "-");
}

export function historyOutputAsset(item: HistoryItem): OutputAsset | null {
  const assets = item.outputAssets || [];
  return (
    assets.find((asset) => asset.outputRole === "final") ||
    assets.find((asset) => !asset.segmentIndex) ||
    assets[0] ||
    (item.outputUrl ? { downloadUrl: item.outputUrl, fileName: item.outputFile || "remote output", outputRole: "final" } : null)
  );
}

export function selectedOutputAsset(assets: OutputAsset[], selectedSegmentIndex: number): OutputAsset | null {
  return (
    assets.find((asset) => asset.outputRole === "segment" && Number(asset.segmentIndex) === selectedSegmentIndex) ||
    assets.find((asset) => asset.outputRole === "final") ||
    assets[0] ||
    null
  );
}

export function finalOutputAsset(assets: OutputAsset[]): OutputAsset | null {
  return (
    assets.find((asset) => asset.outputRole === "final") ||
    assets.find((asset) => !asset.segmentIndex) ||
    assets[0] ||
    null
  );
}

export async function openOutputAsset(item: HistoryItem) {
  const output = historyOutputAsset(item);
  const rawUrl = output?.downloadUrl || output?.url || item.outputUrl || "";
  if (!rawUrl) {
    return;
  }
  await downloadProtectedAsset(fileUrlWithMode(rawUrl, "download"), output?.fileName || item.outputFile || "generated-output.mp4");
}

export async function downloadProtectedAsset(rawUrl: string, fileName: string): Promise<void> {
  if (!rawUrl) {
    throw new Error("다운로드할 영상이 없습니다.");
  }
  if (!rawUrl.startsWith("/api/files/")) {
    window.open(rawUrl, "_blank", "noopener");
    return;
  }
  const blob = await apiClient.assetBlob(rawUrl);
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName || "generated-output.mp4";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export function previewSegmentDetailRows(
  workflowId: string,
  segment: SegmentState,
  segmentCount: number,
  selectedOutput: OutputAsset | null,
  finalOutput: OutputAsset | null
): Array<[string, string]> {
  const config = segment.config || {};
  const segmentOutput =
    selectedOutput?.outputRole === "segment" || selectedOutput?.segmentIndex
      ? selectedOutput.fileName || selectedOutput.assetId || "Segment output"
      : finalOutput
        ? "Not saved separately"
        : "Waiting for generated video";
  return [
    ["Workflow", workflowToken(workflowId)],
    ["View Subgraph", `${segment.displayName || `Subgraph_${segment.index}`} / ${segmentCount || 1}`],
    ["Frames", config.durationSeconds ? `${formatConfigValue(config.durationSeconds, "int")}s` : formatConfigValue(config.frames, "int")],
    ["Steps / CFG", `${formatConfigValue(config.steps, "int")} / ${formatConfigValue(config.cfgScale, "float")}`],
    ["Motion", formatConfigValue(config.motionShift, "float")],
    ["Subgraph Output", segmentOutput],
    ["Final Output", finalOutput?.fileName || finalOutput?.assetId || "-"]
  ];
}

export function workflowToken(workflowId: string) {
  const match = String(workflowId || "").match(/(\d+)\s*[-_]?images/i);
  return match ? `${match[1]}-images` : String(workflowId || "workflow").replace(/\.json$/, "");
}

export function segmentTitleParts(displayName: string) {
  const value = String(displayName || "Subgraph").trim();
  const match = value.match(/^(.*?)\s*(\([^)]*\))?(_\d+)?$/);
  if (!match) {
    return [value];
  }
  const main = match[1]?.trim();
  const detail = `${match[2] || ""}${match[3] || ""}`.trim();
  return [main, detail].filter(Boolean);
}
