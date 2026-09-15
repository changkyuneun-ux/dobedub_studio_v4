export type HealthResponse = {
  ok: boolean;
  backend?: string;
  status?: string;
  progress?: number;
  elapsedSeconds?: number;
  system?: SystemStatusResponse;
  legacy?: SystemStatusResponse;
};

export type SystemStatusResponse = {
  ok: boolean;
  checkedAt?: string;
  checkedAtUtc?: string | null;
  checkedAtKst?: string | null;
  checkedAtSourceTimezone?: string | null;
  executionMode?: string;
  dryRun?: boolean;
  runpod?: {
    configured?: boolean;
    endpointId?: string;
    baseUrl?: string;
  };
  promptLlm?: {
    provider?: string;
    configured?: boolean;
    endpointId?: string;
    endpointUrl?: string;
    model?: string;
    runpodInputMode?: string;
    timeout?: number;
    apiKeyConfigured?: boolean;
  };
  workflows?: {
    dir?: string;
    exists?: boolean;
    count?: number;
    items?: string[];
  };
  segmentDefaults?: {
    workflowCount?: number;
    matchedCount?: number;
    missingWorkflows?: string[];
    bundledPath?: { path?: string; exists?: boolean };
    runtimePath?: { path?: string; exists?: boolean };
  };
  metadata?: {
    manifest?: { exists?: boolean; path?: string };
    workflowWidgetMap?: { exists?: boolean; path?: string };
    models?: { exists?: boolean; path?: string };
  };
  database?: {
    persistenceBackend?: string;
    configured?: boolean;
    engine?: string;
    url?: string;
    migration?: string;
  };
  assetStorage?: {
    backend?: string;
    s3BucketConfigured?: boolean;
    s3Prefix?: string;
  };
  storage?: {
    dataDir?: { path?: string; writable?: boolean };
    outputsDir?: { path?: string; writable?: boolean };
  };
};

export type RunpodConnectionResponse = {
  ok: boolean;
  message?: string;
  workers?: {
    idle?: number;
    running?: number;
  };
  jobs?: {
    inQueue?: number;
    inProgress?: number;
  };
};

export type WorkflowItem = {
  id: string;
  name?: string;
  label?: string;
  mode?: string;
  segmentCount?: number;
  keyframeCount?: number;
};

export type ResolutionTier = "sd" | "hd";

export type AdminUser = {
  id: string;
  name: string;
  email?: string | null;
  role: "SUPER_ADMIN" | "ADMIN" | "OPERATOR" | "VIEWER" | string;
  permissions?: string[];
  rolePermissionCodes?: string[];
  extraPermissionCodes?: string[];
  effectivePermissionCodes?: string[];
  isActive?: boolean;
  lastLoginAt?: string | null;
  lastLoginAtUtc?: string | null;
  lastLoginAtKst?: string | null;
  createdAt?: string | null;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
  updatedAt?: string | null;
  updatedAtUtc?: string | null;
  updatedAtKst?: string | null;
};

export type PermissionGovernance = {
  roles: Array<{
    id: number;
    code: string;
    name: string;
    description?: string | null;
    level: number;
    isSystem: boolean;
    isActive: boolean;
    sortOrder: number;
    permissionCodes: string[];
  }>;
  permissions: Array<{
    id: number;
    code: string;
    domain: string;
    action: string;
    name: string;
    description?: string | null;
    isSystem: boolean;
    isActive: boolean;
    sortOrder: number;
  }>;
  resources: Array<{
    id: number;
    resourceType: string;
    resourceKey: string;
    label: string;
    requiredPermissionCode: string;
    routePath?: string | null;
    method?: string | null;
    isActive: boolean;
    sortOrder: number;
  }>;
};

export type AdminWorkflow = WorkflowItem & {
  active?: boolean;
  status?: string;
  description?: string;
  registeredAt?: string | null;
  registeredAtUtc?: string | null;
  registeredAtKst?: string | null;
  updatedAt?: string | null;
  updatedAtUtc?: string | null;
  updatedAtKst?: string | null;
  fileExists?: boolean;
  paramConfigExists?: boolean;
  paramConfigGenerated?: boolean;
  metadataExists?: boolean;
  metadataNodeCount?: number | null;
  metadataSubgraphCount?: number | null;
};

export type AdminUsersResponse = {
  items: AdminUser[];
  user?: AdminUser;
  permissionGovernance?: PermissionGovernance;
};

export type AdminWorkflowsResponse = {
  items: AdminWorkflow[];
  registryPath?: string;
  registeredWorkflowId?: string;
  paramConfigGenerated?: boolean;
  paramConfigJson?: Record<string, unknown>;
  segmentDefaultsUpdated?: boolean;
  segmentDefaults?: Record<string, unknown>;
  metadataUpdated?: boolean;
  metadataManifest?: Record<string, unknown>;
};

export type SandboxPodAttempt = {
  stage: "stop" | "start" | "switch" | "create" | string;
  ok: boolean;
  at?: string;
  podId?: string;
  podName?: string | null;
  gpuTypeId?: string;
  error?: string;
  skipped?: string;
};

export type SandboxPodHttpService = {
  internalPort: number;
  url: string;
  label?: string;
  authRequired?: boolean;
};

export type SandboxPodSummary = {
  podId: string;
  name?: string | null;
  gpuTypeId?: string | null;
  gpuLabel?: string;
  gpuTier?: "primary" | "fallback" | "unknown";
  vramGb?: number | null;
  ramGb?: number | null;
  pricePerHr?: number | null;
  // 2026-09-13: RunPod 카탈로그 재고 등급(NONE/LOW/MEDIUM/HIGH). 카탈로그 미조회 시 null —
  // "이 파드 자체가 지금 가용한지"가 아니라 "같은 GPU를 새로 만들면 얼마나 쉽게 뜨는지"의 참고 정보.
  gpuStockLevel?: "NONE" | "LOW" | "MEDIUM" | "HIGH" | string | null;
  desiredStatus?: string;
  runtimeStatus?: string;
  lastStartedAt?: string | null;
  lastStartedAtUtc?: string | null;
  lastStartedAtKst?: string | null;
  httpServices: SandboxPodHttpService[];
};

export type SandboxPodSettings = {
  selectedPodId?: string | null;
  autoSwitchOnStartFailure: boolean;
  podPriority: string[];
  replaceSameGpuPods?: boolean;
};

export type SandboxPodStartFailure = {
  message: string;
  attempts?: SandboxPodAttempt[];
  retryAfterSeconds?: number;
  runningPodIds?: string[];
};

export type SandboxPodStatus = {
  configured: boolean;
  message?: string;
  podId?: string | null;
  // Multi-pod (spec 2026-09-11): every Pod on the Sandbox volume plus the
  // selection / single-running invariant state. Legacy single-Pod fields
  // above/below describe the active Pod.
  pods?: SandboxPodSummary[];
  selectedPodId?: string | null;
  selectedPodMissing?: boolean;
  activePodId?: string | null;
  activePodName?: string | null;
  conflict?: boolean;
  conflictPodIds?: string[];
  settings?: SandboxPodSettings;
  attempts?: SandboxPodAttempt[];
  switched?: boolean;
  createdBy?: string | null;
  gpuTypeId?: string | null;
  gpuTier?: "primary" | "fallback" | "unknown";
  stoppedPodId?: string;
  terminatedPodId?: string;
  terminatedPodName?: string | null;
  podName?: string | null;
  resolvedBy?: string;
  desiredStatus?: string;
  runtimeStatus?: string;
  lastStartedAt?: string | null;
  lastStartedAtUtc?: string | null;
  lastStartedAtKst?: string | null;
  lastStatusChange?: string | null;
  lastStatusChangeUtc?: string | null;
  lastStatusChangeKst?: string | null;
  lastLifecycleEvent?: string | null;
  checkedAt?: string | null;
  checkedAtUtc?: string | null;
  checkedAtKst?: string | null;
  locked?: boolean;
  httpServices: SandboxPodHttpService[];
  systemStatus?: {
    available: boolean;
    mode?: "live" | "configuration" | "unavailable" | "pending";
    uptimeSeconds?: number | null;
    cpuPercent?: number | null;
    memoryPercent?: number | null;
    gpuCount?: number | null;
    gpuType?: string | null;
    memoryInGb?: number | null;
    gpus: Array<{
      id?: string;
      gpuUtilPercent?: number | null;
      memoryUtilPercent?: number | null;
    }>;
    storage?: {
      containerDiskInGb?: number | null;
      volumeInGb?: number | null;
      networkVolumeId?: string | null;
    };
    message?: string;
  };
};

// 2단계 로딩 2단계(GET /api/admin/sandbox-pod/live): 표시 파드의 8188 준비 상태·runtime
// 지표와 파드별 runtimeStatus만. 목록·설정은 sandboxPodStatus({ live: false })가 담당.
export type SandboxPodLive = {
  configured: boolean;
  podId?: string | null;
  desiredStatus?: string;
  runtimeStatus?: string | null;
  systemStatus?: SandboxPodStatus["systemStatus"] | null;
  message?: string | null;
  pods: Array<{ podId: string; runtimeStatus: string }>;
  checkedAt?: string | null;
  checkedAtUtc?: string | null;
  checkedAtKst?: string | null;
};

// 2026-09-13 로그인 랜딩 대시보드(GET /api/dashboard/summary) — 전역 API, 인증만 필요.
export type DashboardRange = "today" | "7d" | "30d";

export type DashboardRecentTask = {
  taskId: string;
  createdAt?: string | null;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
  user: { id?: string | null; name?: string | null };
  workflowId: string;
  workflowName: string;
  workerName?: string | null;
  status: string;
  statusKind: "completed" | "failed" | "queued" | "active" | "other";
  elapsedSeconds?: number | null;
  lastDispatchError?: string | null;
  batchJobId?: string | null;
};

export type DashboardAlert = { id: string; level: "warning" | "danger" | "info"; message: string; route?: StudioRouteLike | null };
type StudioRouteLike = string;

export type DashboardDailyVolume = {
  date: string;
  submitted: number;
  completed: number;
  failed: number;
  active: number;
  queued: number;
  other: number;
};

export type DashboardFilterOption = { id?: string | null; name: string };

// 2026-09-15: 컷 길이별(5초/10초) 서버리스 비용 배분 카드. UTC 캘린더일 기준(다른
// 카드의 KST 일자와 최대 ~9시간 어긋날 수 있음 - RunPod 청구가 UTC일 단위라 총액
// 정합성을 위해 UTC를 우선함). split이 없으면(null) 아직 5초/10초 구분 전
// (2026-09-10 UTC 이전) 날짜로, 전체 제출/완료/실패/비용만 표시한다.
export type DurationCostBucket = { count: number; costUsd: number };
export type DurationCostDay = {
  submitted: number;
  completed: number;
  failed: number;
  totalCostUsd: number;
  split: { fiveSec: DurationCostBucket; tenSec: DurationCostBucket; unclassified: DurationCostBucket } | null;
};
export type DurationCostSummary = {
  sinceUtc: string;
  untilUtc: string;
  fiveSec: DurationCostBucket & { costPerJobUsd?: number | null };
  tenSec: DurationCostBucket & { costPerJobUsd?: number | null };
  unclassified: DurationCostBucket & { costPerJobUsd?: number | null };
};
export type DashboardDurationCostBreakdown = {
  byDay: Record<string, DurationCostDay>;
  /** 구분 대상(09-10 UTC 이후) 날짜가 하나도 없으면 null */
  summary: DurationCostSummary | null;
};

export type DashboardSummary = {
  range: DashboardRange;
  since?: string | null;
  sinceKst?: string | null;
  until?: string | null;
  untilKst?: string | null;
  kpi: {
    submitted: number;
    submittedDeltaPercent?: number | null;
    completed: number;
    successRate?: number | null;
    active: number;
    queued: number;
    failed: number;
    failedDispatch: number;
    failedTimeout: number;
    avgElapsedSeconds?: number | null;
    avgDelaySeconds?: number | null;
    activeUsers: number;
    batchJobsInProgress: number;
  };
  recent: DashboardRecentTask[];
  // 2026-09-13 "최근 작업" 목록을 대체하는 일자별(KST) 작업량 그래프 데이터(범위 전체 기준, limit 영향 없음)
  dailyVolume: DashboardDailyVolume[];
  dailyVolumeFilters: { user?: string | null; workflow?: string | null; status?: string | null };
  filterOptions: { users: DashboardFilterOption[]; workflows: DashboardFilterOption[] };
  byUser: Array<{ userId?: string | null; name: string; submitted: number; failed: number }>;
  byWorkflow: Array<{ workflowId: string; workflowName: string; submitted: number; avgElapsedSeconds?: number | null }>;
  durationCostBreakdown: DashboardDurationCostBreakdown;
  system: {
    comfy: { configured: boolean; executionMode: string; dryRun: boolean };
    promptLlm: { configured: boolean; provider?: string | null; model?: string | null; timeoutSeconds?: number | null };
    grok: { configured: boolean; enabled: boolean; model?: string | null; timeoutSeconds?: number | null };
    workflows: { count?: number | null; activeCount?: number | null };
  };
  sandbox: {
    configured: boolean;
    activePodId?: string | null;
    activePodName?: string | null;
    desiredStatus?: string | null;
    gpuTier?: string | null;
    gpuTypeId?: string | null;
    podCount: number;
    runningCount: number;
    conflict: boolean;
    duplicateStoppedPodIds: string[];
    error?: string | null;
    /** 서버 캐시 없음 → 백그라운드 갱신 중(프론트가 잠시 후 재조회) */
    pending?: boolean;
    /** 캐시 만료분을 즉시 돌려주고 백그라운드 갱신 중 */
    stale?: boolean;
  };
  worker: { active: number; queued: number; maxActiveTasksTotal: number; maxActiveTasksPerUser: number };
  db: { alembicCurrent?: string | null; alembicHead?: string | null; migrationRequired: boolean; error?: string | null };
  alerts: DashboardAlert[];
  checkedAt?: string | null;
  checkedAtKst?: string | null;
};

export type ConfigControl = {
  key: string;
  param?: string;
  label: string;
  type: "int" | "float" | "string" | "text" | string;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  default?: string | number | null;
  randomizable?: boolean;
  options?: string[];
  description?: string;
};

export type WorkflowSegmentSchema = {
  index: number;
  nodeId?: string;
  subgraphName?: string;
  displayName?: string;
  startImageIndex?: number;
  endImageIndex?: number;
  defaultPositivePrompt?: string;
  defaultNegativePrompt?: string;
  config?: Record<string, string | number>;
  configControls?: ConfigControl[];
};

export type WorkflowSchema = {
  workflowId: string;
  name?: string;
  mode?: string;
  keyframeCount: number;
  segmentCount: number;
  segments: WorkflowSegmentSchema[];
};

export type SegmentDefaultsResponse = {
  workflowName?: string;
  segments?: Array<{
    id?: string;
    name?: string;
    config?: Record<string, string | number>;
  }>;
};

export type MetadataStatusResponse = {
  ok?: boolean;
  metadataDir?: string;
  manifest?: Record<string, unknown>;
};

export type WorkflowWidgetMetadata = {
  workflowId?: string;
  name?: string;
  nodeCount?: number;
  segments?: Array<Record<string, unknown>>;
  nodes?: Array<Record<string, unknown>>;
  models?: Record<string, string[]>;
};

export type ModelMetadataResponse = {
  manifest?: Record<string, unknown>;
  models?: Record<string, string[]>;
};

export type UploadResponse = {
  assetId: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  imageWidth?: number | null;
  imageHeight?: number | null;
  downloadUrl: string;
};

export type S3UploadScope =
  | { requestBatchId: string; requestItemId: string; jobId: string; promptBatchId?: string | null }
  | { batchJobId: string; requestItemId: string; jobId: string; promptBatchId?: string | null };

export type S3UploadPresignResponse = {
  assetId: string;
  fileName: string;
  mimeType: string;
  storageBackend: "s3";
  storageKey: string;
  uploadUrl: string;
  headers: Record<string, string>;
  expiresAt: string;
};

export type S3UploadCompleteResponse = UploadResponse & {
  storageBackend: "s3";
  storageKey: string;
  publicUrl?: string | null;
};

export type WebtoonCutUploadPresignResponse = {
  assetId: string;
  fileName: string;
  mimeType: string;
  storageBackend: "s3";
  storageKey: string;
  uploadUrl: string;
  headers: Record<string, string>;
};

export type WebtoonCutJobResponse = {
  jobId: string;
  status: string;
  inputKind: string;
  sourceAssetId: string;
  displayName: string;
  totalUnits: number;
  completedUnits: number;
  generatedCutCount: number;
  reviewRequiredCount: number;
  failedUnits: number;
  currentUnitLabel?: string | null;
  cancelRequestedAt?: string | null;
  createdBy?: string;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type WebtoonCutOutputItem = {
  outputId: string;
  jobId: string;
  assetId: string;
  viewUrl: string;
  downloadUrl: string;
  displayPath: string;
  pageNumber?: number | null;
  cutIndex: number;
  width?: number | null;
  height?: number | null;
  flags: string[];
  usedInPromptCount: number;
  usedInBatchCount: number;
  i2vResultCount: number;
  createdBy?: string;
};

export type WebtoonCutHandoffResponse = {
  target: "grok_prompt" | "batch";
  jobId: string;
  sourceDisplayName?: string;
  inputAssetIds: string[];
  sourceRelativePaths: string[];
  items: Array<{
    outputId: string;
    assetId: string;
    fileName: string;
    mimeType: string;
    sourceRelativePath: string;
    imageWidth?: number | null;
    imageHeight?: number | null;
    downloadUrl: string;
  }>;
};

export type WebtoonCutJobListResponse = {
  items: WebtoonCutJobResponse[];
  page: number;
  pageSize: number;
};

export type WebtoonCutOutputListResponse = {
  items: WebtoonCutOutputItem[];
  page: number;
  pageSize: number;
};

export type GrokImagePromptDraftResponse = {
  draftId: string;
  assetId: string;
  workflowId: string;
  promptBatchId?: string | null;
  batchJobId?: string | null;
  slotIndex: number;
  status: "READY" | "GENERATING" | "MANUAL_REQUIRED" | "FAILED" | string;
  provider: string;
  model: string;
  instructionVersion: string;
  createdBy?: string | null;
  createdByName?: string | null;
  positivePrompt: string;
  imageType: string;
  warnings: string[];
  error?: string | null;
  cached?: boolean;
  requestedFrames?: number | null;
  negativePrompt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  asset?: {
    assetId?: string;
    fileName?: string;
    mimeType?: string;
    sizeBytes?: number;
    imageWidth?: number | null;
    imageHeight?: number | null;
  } | null;
  runpodTaskId?: string | null;
  runpodStatus?: string | null;
  grokResponse?: {
    endpoint?: string | null;
    model?: string | null;
    latencyMs?: number | null;
    inputTokens?: number | null;
    outputTokens?: number | null;
  } | null;
};

export type PromptGenerationBatchResponse = {
  id: string;
  workflowId: string;
  status: string;
  totalCount: number;
  completedCount: number;
  failedCount: number;
  pendingCount: number;
  items: GrokImagePromptDraftResponse[];
};

export type BatchJobResponse = {
  id: string;
  workflowId: string;
  status: string;
  sourceDirName?: string | null;
  sourceZipFileName?: string | null;
  requestedFrames: number;
  resolutionTier?: ResolutionTier;
  durationSeconds: number;
  totalImages: number;
  promptCompletedCount: number;
  promptFailedCount: number;
  videoRequestedCount: number;
  videoCompletedCount: number;
  videoFailedCount: number;
  videoCancelledCount: number;
  promptWaiting: number;
  promptGenerating: number;
  runpodPendingSubmit: number;
  runpodQueued: number;
  runpodInProgress: number;
  promotionFailedCount: number;
  failedCount: number;
  cancelledCount: number;
  lastDownloadedAt?: string | null;
  createdBy?: string | null;
  createdByName?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type BatchJobListResponse = {
  items: BatchJobResponse[];
  page: number;
  pageSize: number;
  total: number;
  workers: Array<{ workerId: string; workerName: string }>;
};

export type BatchJobDetailItemResponse = {
  id: string;
  assetId?: string | null;
  sourceFileName: string;
  sourceRelativePath?: string | null;
  sourceZipFileName?: string | null;
  promptDraftId?: string | null;
  taskId?: string | null;
  promptStatus: string;
  runpodStatus: string;
  error?: string | null;
  retryKind: "prompt" | "promotion" | "runpod" | "none" | string;
  retryable: boolean;
  selectable: boolean;
  actionLabel: string;
  retryCount: number;
  nextRetryAt?: string | null;
  promotionStatus?: string | null;
  promotionAttempts?: number;
  promotionLastError?: string | null;
};

export type BatchJobDetailResponse = {
  batch: BatchJobResponse;
  items: BatchJobDetailItemResponse[];
  warnings: Array<Record<string, unknown>>;
};

export type BatchJobRetryResponse = {
  batchJobId: string;
  promptRetried: number;
  promotionRetried: number;
  runpodReworked: number;
  skipped: Array<{ id: string; reason: string }>;
  batch: BatchJobResponse;
};

export type RunpodHistoryReworkResponse = {
  scope: string;
  requested: number;
  reworked: number;
  taskIds: string[];
  skipped: Array<{ id: string; reason: string }>;
};

export type BatchJobCandidateListResponse = {
  items: BatchJobResponse[];
};

export type ActiveBatchJobListResponse = {
  items: BatchJobResponse[];
};

export type PromptDraftListResponse = {
  items: GrokImagePromptDraftResponse[];
  workerStats: Array<{
    workerId?: string | null;
    workerName?: string | null;
    total: number;
    pendingCount: number;
    generatingCount: number;
    readyCount: number;
    failedCount: number;
  }>;
  page: number;
  pageSize: number;
  total: number;
};

export type RunpodRequestItemResponse = {
  id: string;
  sequenceNo: number;
  promptDraftId?: string | null;
  assetId: string;
  asset?: UploadResponse | null;
  workflowId: string;
  positivePrompt: string;
  negativePrompt?: string | null;
  requestedFrames: number;
  resolutionTier?: ResolutionTier;
  status: string;
  taskId?: string | null;
  runpodJobId?: string | null;
  failureMessage?: string | null;
  workerId?: string | null;
  workerName?: string | null;
};

export type RunpodRequestBatchResponse = {
  id: string;
  workflowId: string;
  status: string;
  requestedCount: number;
  queuedCount: number;
  inProgressCount: number;
  completedCount: number;
  failedCount: number;
  cancelledCount: number;
  createdAt?: string | null;
  updatedAt?: string | null;
  createdBy?: string | null;
  createdByName?: string | null;
  submittedBy?: string | null;
  submittedByName?: string | null;
  items: RunpodRequestItemResponse[];
};

export type RunpodRequestDashboardResponse = {
  totals: {
    incomplete: number;
    requestReady: number;
    pendingSubmit: number;
    runpodQueued: number;
    inProgress: number;
    completed: number;
    failed: number;
  };
  workers: Array<{
    workerId?: string | null;
    workerName?: string | null;
    incomplete: number;
    requestReady: number;
    pendingSubmit: number;
    runpodQueued: number;
    inProgress: number;
    completed: number;
    failed: number;
  }>;
};

export type RunpodRequestQueueItemResponse = RunpodRequestItemResponse & {
  kind: "PROMPT_DRAFT" | "REQUEST_ITEM";
  requestBatchId?: string | null;
  promptBatchId?: string | null;
  canSubmit: boolean;
  updatedAt?: string | null;
};

export type RunpodRequestQueueResponse = {
  items: RunpodRequestQueueItemResponse[];
  page: number;
  pageSize: number;
  total: number;
};

export type GrokInstructionDocument = {
  id: string;
  code: string;
  title: string;
  role: "CORE" | "ROUTER" | "GUIDE" | string;
  contentMarkdown: string;
  source?: string | null;
  sortOrder: number;
  version: number;
  isActive: boolean;
};

export type GrokInstructionSetResponse = {
  items: GrokInstructionDocument[];
  instructionSet: Record<string, unknown>;
  item?: GrokInstructionDocument;
};

export type GrokInstructionPayload = Omit<GrokInstructionDocument, "id" | "version"> & {
  workflowId: string;
};

export type OutputAsset = {
  assetId?: string;
  fileName?: string;
  downloadUrl?: string;
  url?: string;
  mimeType?: string;
  kind?: string;
  outputRole?: string;
  segmentIndex?: number | null;
};

export type PromptEntry = {
  index?: number;
  text?: string;
  prompt?: string;
};

export type PromptTerm = {
  id: number;
  code: string;
  canonicalKey?: string;
  labelKo?: string;
  labelEn?: string;
  description?: string;
  promptText?: string;
  negativeText?: string;
  riskLevel?: string;
  metadata?: Record<string, unknown>;
  sortOrder?: number;
};

export type PromptCategory = {
  id: number;
  code: string;
  groupId?: number;
  groupCode?: string;
  groupNameKo?: string;
  groupNameEn?: string;
  groupSortOrder?: number;
  parentCategoryId?: number | null;
  scopeType?: string;
  nameKo?: string;
  nameEn?: string;
  description?: string;
  selectionMode?: "single" | "multi" | string;
  required?: boolean;
  maxSelectCount?: number | null;
  sortOrder?: number;
  terms: PromptTerm[];
};

export type PromptCategoryGroup = {
  id: number;
  code: string;
  scopeId?: number;
  scopeCode?: "POSITIVE" | "NEGATIVE" | string | null;
  scopeType?: "POSITIVE" | "NEGATIVE" | string | null;
  nameKo?: string;
  nameEn?: string;
  description?: string;
  sortOrder?: number;
  subcategories: PromptCategory[];
};

export type PromptCatalogResponse = {
  groups?: PromptCategoryGroup[];
  // B-06 3단계: 백엔드가 구형 "categories" 배열을 응답에서 완전히 제거했다("groups"가
  // 유일한 canonical 응답). 이 필드는 더 이상 서버에서 내려오지 않으므로 optional로
  // 남겨 하위 호환 코드가 있다면 방어적으로만 참조하게 한다.
  categories?: PromptCategory[];
  rules?: Array<Record<string, unknown>>;
  templates?: Array<Record<string, unknown>>;
  relations?: Array<Record<string, unknown>>;
};

export type PromptSystemPromptResponse = {
  id?: number;
  code: string;
  name: string;
  provider: string;
  modelFamily: string;
  promptText: string;
  isActive?: boolean;
  createdAt?: string | null;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
  updatedAt?: string | null;
  updatedAtUtc?: string | null;
  updatedAtKst?: string | null;
};

// B-08: 시스템 지시문 버전 이력(7a 되돌리기).
export type SystemPromptVersion = {
  id: number;
  code: string;
  name: string;
  provider: string;
  modelFamily: string;
  promptText: string;
  createdBy?: string | null;
  createdAt?: string | null;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
};

export type SystemPromptVersionsResponse = { items: SystemPromptVersion[] };

export type PromptSceneResponse = {
  requestId: string;
  outputId: string;
  provider?: string;
  workflowId?: string;
  segmentIndex?: number;
  language?: string;
  scene: Record<string, unknown>;
  constraints: Record<string, unknown>;
  positivePromptDraft: string;
  negativePromptDraft: string;
  usedTermIds: number[];
  modelProfile?: Record<string, unknown> | null;
  warnings?: Array<{ code?: string; message?: string; severity?: string }>;
};

export type PromptGenerateResponse = {
  requestId: string;
  outputId: string;
  provider: string;
  workflowId?: string;
  segmentIndex?: number;
  language?: string;
  scene: Record<string, unknown>;
  constraints: Record<string, unknown>;
  positivePrompt: string;
  negativePrompt: string;
  usedTermIds: number[];
  warnings?: Array<{ code?: string; message?: string; severity?: string }>;
};

export type PromptGenerationStatusResponse = {
  requestId: string;
  outputId?: string | null;
  provider: string;
  workflowId?: string;
  segmentIndex?: number;
  language?: string;
  scene: Record<string, unknown>;
  constraints: Record<string, unknown>;
  usedTermIds: number[];
  status: string;
  externalJobId?: string | null;
  failureMessage?: string | null;
  pollIntervalSeconds?: number;
  positivePrompt?: string;
  negativePrompt?: string;
  warnings?: Array<{ code?: string; message?: string; severity?: string }>;
};

export type InputImage = {
  index?: number;
  assetId?: string;
  fileName?: string;
  filename?: string;
  sizeBytes?: number | null;
  imageWidth?: number | null;
  imageHeight?: number | null;
};

export type HistorySegment = {
  index?: number;
  nodeId?: string;
  subgraphName?: string;
  displayName?: string;
  positivePrompt?: string;
  negativePrompt?: string;
  negativePromptAddition?: string;
  config?: Record<string, string | number>;
};

export type HistoryItem = {
  taskId: string;
  timestamp?: string;
  timestampUtc?: string | null;
  timestampKst?: string | null;
  completedAt?: string | null;
  completedAtUtc?: string | null;
  completedAtKst?: string | null;
  timeContext?: Record<string, unknown>;
  workflowId?: string;
  workflowName?: string;
  workflow?: string;
  promptDraftId?: string;
  promptBatchId?: string | null;
  batchJobId?: string | null;
  runpodResponse?: {
    filename?: string | null;
    delaySeconds?: number | string | null;
    executionSeconds?: number | string | null;
    jobId?: string | null;
  };
  // 2026-08-11: 백엔드 _task_to_history_item()이 이미 내려주고 있었지만 타입에는
  // 빠져 있던 필드 - 3a 우측 패널 Overview 섹션(runpod_job_id 노출)에서 사용.
  runpodJobId?: string;
  workerName?: string;
  user?: { id?: string; name?: string };
  status?: string;
  statusLabel?: string;
  lastDispatchError?: string | null;
  progress?: number;
  elapsedSeconds?: number;
  durationSeconds?: number;
  prompt?: string;
  positivePrompt?: string;
  negativePrompt?: string;
  positivePrompts?: PromptEntry[];
  negativePrompts?: PromptEntry[];
  segmentCount?: number;
  segments?: HistorySegment[];
  keyframes?: Array<{ index?: number; uploadId?: string; fileName?: string }>;
  configJson?: Record<string, string | number>;
  config?: Record<string, string | number> | string;
  wanNodeConfig?: {
    segments?: Array<HistorySegment & { params?: Array<{ uiKey?: string; value?: string | number }> }>;
  };
  fps?: number;
  seed?: number | string;
  generationSeed?: number | string;
  outputUrl?: string;
  outputFile?: string;
  outputAssets?: OutputAsset[];
  remoteOutputUrls?: string[];
  inputAssets?: string[];
  inputImages?: InputImage[];
};

export type RunpodHistoryStats = {
  total: number;
  completed: number;
  failed: number;
  cancelled: number;
  pendingSubmit: number;
  active: number;
};

export type HistoryResponse = {
  items: HistoryItem[];
  page: number;
  pageSize: number;
  total: number;
  stats?: RunpodHistoryStats;
};

// A-04: `GET /api/admin/audit-logs` 응답. `beforeJson`/`afterJson`은 스키마가
// 고정되지 않은 임의의 JSON이라 화면에서는 JSON.stringify로만 보여준다.
export type AuditLogItem = {
  id: number;
  actorId: string | null;
  action: string;
  targetType: string | null;
  targetId: string | null;
  beforeJson: Record<string, unknown> | null;
  afterJson: Record<string, unknown> | null;
  ip: string | null;
  createdAt: string;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
};

export type AuditLogResponse = {
  items: AuditLogItem[];
  page: number;
  pageSize: number;
  total: number;
};

// A-01/E-03(5a): `assets` 테이블을 그대로 노출한 목록 응답. `taskId`/`outputRole`은
// `task_output_assets` 조인 결과라 아직 어느 작업 출력에도 연결되지 않은 자산(예:
// 업로드만 되고 실행에 쓰이지 않은 입력 이미지)은 빈 문자열로 내려온다 - 화면에서
// 그 경우를 별도 처리해야 한다. 설계 mock(5a/5c)의 태그·공개범위(PRIVATE/SHARED)·
// 컬렉션 필드는 백엔드에 대응 컬럼이 전혀 없어(A-02 미착수) 이 타입에 포함하지
// 않는다 - 화면에서도 그리지 않는다.
// 2026-08-11: "Asset 관리" 통합 - assets가 이제 output 기준으로 내려온다
// (task_tracking_service.list_assets 참조). createdBy는 이 출력을 만든
// 작업의 제출자, inputAssets는 같은 작업의 입력 이미지들(종속 관계),
// collections는 이 자산이 담긴 컬렉션들(다대다이므로 여러 개일 수 있음).
export type AssetCollectionRef = { id: number; name: string };

export type AssetItem = {
  assetId: string;
  type: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  imageWidth?: number | null;
  imageHeight?: number | null;
  path?: string;
  storageBackend?: string;
  publicUrl?: string | null;
  createdAt?: string;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
  createdAtSourceTimezone?: string | null;
  downloadUrl: string;
  taskId?: string;
  outputRole?: string;
  segmentIndex?: number | null;
  workflowId?: string;
  createdBy?: string | null;
  inputAssets?: AssetItem[];
  collections?: AssetCollectionRef[];
};

export type AssetsResponse = {
  items: AssetItem[];
  page: number;
  pageSize: number;
  total: number;
};

// A-02: 자산 컬렉션(화면 5c). 태그·공개범위와 마찬가지로 컬렉션 자체에도 태그/공개
// 필드는 백엔드에 없다 - 이름·생성자·담긴 수(itemCount)만 다룬다.
export type CollectionSummary = {
  id: number;
  name: string;
  createdBy?: string | null;
  createdAt?: string;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
  itemCount: number;
};

export type CollectionItem = AssetItem & { sortOrder: number };

export type CollectionDetail = CollectionSummary & { items: CollectionItem[] };

export type CollectionsResponse = { items: CollectionSummary[] };

export type JobCreateResponse = {
  taskId: string;
  runpodJobId: string;
  status: string;
  statusLabel?: string;
  lastDispatchError?: string | null;
  generationSeed?: number | string;
};

export type TaskExecutionPolicy = {
  maxActiveTasksPerUser: number;
  maxActiveTasksTotal: number;
  activeForUser?: number;
  activeTotal?: number;
  updatedBy?: string | null;
  updatedAt?: string | null;
  updatedAtUtc?: string | null;
  updatedAtKst?: string | null;
};

export type JobStatusResponse = {
  taskId: string;
  runpodJobId: string;
  status: string;
  rawStatus?: string;
  elapsedSeconds?: number;
  progress?: number;
  workerSummary?: string;
  statusLabel?: string;
  lastDispatchError?: string | null;
  message?: string;
  outputUrl?: string;
  outputAssets?: OutputAsset[];
  generationSeed?: number | string;
  cancelRequested?: boolean;
};

export type TaskPromptReviewFlags = {
  originalPreserved?: boolean;
  naturalMotion?: boolean;
  noDistortion?: boolean;
  backgroundStable?: boolean;
  colorStable?: boolean;
  /** 이전 v4 리뷰 데이터 호환용. 저장 시에는 새 평가 사유로 정규화한다. */
  intentMatched?: boolean;
  identityPreserved?: boolean;
};

// B-02: task_prompts(quality_rating 등)는 "영상 결과 평가" 전용이고, 이 필드는
// "프롬프트 생성 품질" 평가(prompt_feedback, 역할이 분리된 별도 저장소)의 최신 값을
// 읽기 전용으로 담는다. 저장은 항상 apiClient.savePromptFeedback(POST /prompts/feedback)로만.
export type TaskPromptFeedback = {
  id: string;
  rating?: number | null;
  notes?: string | null;
  editedPositivePrompt?: string | null;
  editedNegativePrompt?: string | null;
  createdAt?: string | null;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
};

export type TaskModelReference = {
  bucket: string;
  nodeId?: string;
  nodeTitle?: string;
  classType?: string;
  field?: string;
  value: string;
};

export type TaskPromptItem = {
  id: number;
  taskId: string;
  workflowId: string;
  segmentIndex: number;
  createdBy?: string | null;
  modelProfileId?: string | null;
  modelName?: string | null;
  modelReferences?: TaskModelReference[];
  modelReferenceSource?: "submission_snapshot" | "metadata_json_plus_current_workflow" | "current_workflow_metadata" | "unavailable" | string;
  promptGenerationOutputId?: string | null;
  promptFeedback?: TaskPromptFeedback | null;
  positivePrompt: string;
  negativePrompt: string;
  inputAssetIds?: string[];
  outputAssetIds?: string[];
  inputAssets?: OutputAsset[];
  outputAssets?: OutputAsset[];
  qualityRating?: number | null;
  qualityComment?: string | null;
  reuseEligible?: boolean;
  reviewStatus?: "unreviewed" | "reviewed" | "rejected" | string;
  reviewFlags?: TaskPromptReviewFlags;
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  reviewedAtUtc?: string | null;
  reviewedAtKst?: string | null;
  reuseCount?: number;
  metadata?: Record<string, unknown>;
  createdAt?: string | null;
  createdAtUtc?: string | null;
  createdAtKst?: string | null;
  updatedAt?: string | null;
  updatedAtUtc?: string | null;
  updatedAtKst?: string | null;
};

export type TaskPromptResponse = {
  taskId: string;
  items: TaskPromptItem[];
};

// 2026-08-11: 4c 프롬프트 재사용에 서버사이드 페이지네이션 추가 - 이전에는
// `items`만 내려주고 전체 건수를 몰라 카드 그리드를 통째로 렌더링했다.
// `HistoryResponse`/`AuditLogResponse`와 동일한 {items,page,pageSize,total} 규격.
export type ReusablePromptResponse = {
  items: TaskPromptItem[];
  page: number;
  pageSize: number;
  total: number;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const SESSION_USER_STORAGE_KEY = "dobedub.react.user.db-auth.v1";

export type AuthSession = {
  user: AdminUser;
  accessToken: string;
  tokenType?: string;
  expiresAt?: string;
};

function sessionUserHeaders(path: string): Record<string, string> {
  if (path === "/api/auth/login" || typeof sessionStorage === "undefined") {
    return {};
  }
  try {
    const raw = sessionStorage.getItem(SESSION_USER_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as Partial<AuthSession>;
    if (parsed.accessToken) {
      return {
        Authorization: `${parsed.tokenType || "Bearer"} ${parsed.accessToken}`
      };
    }
    return {};
  } catch {
    return {};
  }
}

function friendlyApiErrorMessage(rawMessage: string, response: Response, path: string) {
  const trimmed = rawMessage.trim();
  const contentType = response.headers.get("content-type") || "";
  const looksHtml = /<html|<!doctype html|<body|<head/i.test(trimmed) || contentType.includes("text/html");
  const looksGatewayTimeout = /504\s+Gateway\s+Time-out/i.test(trimmed) || /Gateway\s+Time-out/i.test(trimmed);

  if (looksGatewayTimeout) {
    return `서버 응답이 지연되어 ${path} 요청이 시간 초과되었습니다. 잠시 후 다시 시도해주세요.`;
  }
  if (looksHtml) {
    return `서버가 HTML 오류 페이지를 반환했습니다. ${path} 요청을 다시 시도해주세요.`;
  }
  return trimmed || `Request failed: ${response.status}`;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...sessionUserHeaders(path),
      ...(init?.headers || {})
    },
    ...init
  });
  const rawMessage = await response.text();
  if (!response.ok) {
    let message = friendlyApiErrorMessage(rawMessage, response, path);
    let detail: unknown = undefined;
    try {
      const parsed = JSON.parse(rawMessage) as { detail?: unknown; message?: unknown; error?: unknown };
      detail = parsed.detail ?? parsed.message ?? parsed.error;
      if (typeof detail === "string" && detail.trim()) {
        message = detail.trim();
      } else if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
        // Structured failures (e.g. Sandbox Pod 409/503) carry a message plus
        // machine-readable fields; keep the object for callers that render it.
        message = (detail as { message: string }).message;
      }
    } catch {
      // Ignore non-JSON bodies and fall back to a safe, readable message.
    }
    throw new ApiError(message, response.status, detail);
  }

  if (!rawMessage.trim()) {
    return undefined as T;
  }

  try {
    return JSON.parse(rawMessage) as T;
  } catch {
    const message = friendlyApiErrorMessage(rawMessage, response, path);
    throw new Error(message);
  }
}

async function requestFormJson<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: sessionUserHeaders(path),
    body: formData
  });
  const rawMessage = await response.text();
  if (!response.ok) {
    let message = friendlyApiErrorMessage(rawMessage, response, path);
    let detail: unknown = undefined;
    try {
      const parsed = JSON.parse(rawMessage) as { detail?: unknown; message?: unknown; error?: unknown };
      detail = parsed.detail ?? parsed.message ?? parsed.error;
      if (typeof detail === "string" && detail.trim()) {
        message = detail.trim();
      } else if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
        // Structured failures (e.g. Sandbox Pod 409/503) carry a message plus
        // machine-readable fields; keep the object for callers that render it.
        message = (detail as { message: string }).message;
      }
    } catch {
      // Ignore non-JSON bodies and fall back to a safe, readable message.
    }
    throw new ApiError(message, response.status, detail);
  }
  if (!rawMessage.trim()) {
    return undefined as T;
  }
  try {
    return JSON.parse(rawMessage) as T;
  } catch {
    const message = friendlyApiErrorMessage(rawMessage, response, path);
    throw new Error(message);
  }
}

async function requestBlob(path: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: sessionUserHeaders(path)
  });
  if (!response.ok) {
    throw new Error(friendlyApiErrorMessage(await response.text(), response, path));
  }
  return response.blob();
}

export const apiClient = {
  assetBlob: (path: string) => requestBlob(path),
  logout: async () => {
    const response = await fetch(`${API_BASE}/auth/logout`, { method: "POST" });
    if (!response.ok) {
      throw new Error(friendlyApiErrorMessage(await response.text(), response, "/api/auth/logout"));
    }
  },
  health: () => requestJson<HealthResponse>("/api/health"),
  systemStatus: () => requestJson<SystemStatusResponse>("/api/system/status"),
  runpodConnection: () => requestJson<RunpodConnectionResponse>("/api/runpod/connection"),
  workflows: () => requestJson<WorkflowItem[]>("/api/workflows"),
  workflowSchema: (workflowId: string) => requestJson<WorkflowSchema>(`/api/workflows/${encodeURIComponent(workflowId)}/schema`),
  workflowSegmentDefaults: (workflowId: string) =>
    requestJson<SegmentDefaultsResponse>(`/api/segment-defaults/${encodeURIComponent(workflowId)}`),
  workflowWidgetMetadata: (workflowId: string) =>
    requestJson<WorkflowWidgetMetadata>(`/api/workflows/${encodeURIComponent(workflowId)}/widget-metadata`),
  metadataStatus: () => requestJson<MetadataStatusResponse>("/api/metadata/status"),
  metadataModels: () => requestJson<ModelMetadataResponse>("/api/metadata/models"),
  rebuildMetadata: () =>
    requestJson<{ ok?: boolean; manifest?: Record<string, unknown> }>("/api/metadata/rebuild", {
      method: "POST"
    }),
  manualHtml: async () => {
    const response = await fetch(`${API_BASE}/manual`, {
      headers: sessionUserHeaders("/manual")
    });
    if (!response.ok) {
      throw new Error(await response.text() || `Request failed: ${response.status}`);
    }
    return response.text();
  },
  // B-01: 기본값 20(3a 설계 기준). 프론트는 항상 사용자가 고른 값(20/50)을
  // 명시 전송하므로 이 기본값은 호출부가 실수로 pageSize를 생략했을 때의
  // 안전망일 뿐이다.
  history: (page = 1, pageSize = 20) => requestJson<HistoryResponse>(`/api/history?page=${page}&pageSize=${pageSize}`),
  // Task History is intentionally split into two fixed 10-row contracts. Keeping
  // these endpoints separate prevents prompt-generation history from inheriting
  // RunPod pagination and sorting behavior.
  promptHistory: (params: { page?: number; generationStatus?: string; runpodStatus?: string; batchId?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page || 1));
    query.set("pageSize", "10");
    if (params.generationStatus) query.set("generationStatus", params.generationStatus);
    if (params.runpodStatus) query.set("runpodStatus", params.runpodStatus);
    if (params.batchId) query.set("batchId", params.batchId);
    return requestJson<PromptDraftListResponse>(`/api/history/prompts?${query.toString()}`);
  },
  runpodHistory: (params: { page?: number; workflowId?: string; resultStatus?: string; workerId?: string; runDate?: string; batchId?: string; jobId?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page || 1));
    query.set("pageSize", "10");
    if (params.workflowId) query.set("workflowId", params.workflowId);
    if (params.resultStatus) query.set("resultStatus", params.resultStatus);
    if (params.workerId) query.set("workerId", params.workerId);
    if (params.runDate) query.set("runDate", params.runDate);
    if (params.batchId) query.set("batchId", params.batchId);
    if (params.jobId) query.set("jobId", params.jobId);
    return requestJson<HistoryResponse>(`/api/history/runpod?${query.toString()}`);
  },
  runpodHistorySelection: (params: { workflowId?: string; resultStatus?: string; workerId?: string; runDate?: string; batchId?: string; jobId?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.workflowId) query.set("workflowId", params.workflowId);
    if (params.resultStatus) query.set("resultStatus", params.resultStatus);
    if (params.workerId) query.set("workerId", params.workerId);
    if (params.runDate) query.set("runDate", params.runDate);
    if (params.batchId) query.set("batchId", params.batchId);
    if (params.jobId) query.set("jobId", params.jobId);
    return requestJson<{ taskIds: string[]; truncated: boolean }>(`/api/history/runpod/selection?${query.toString()}`);
  },
  // A-01/E-03(5a): type/workflowId는 선택 필터. 빈 문자열은 쿼리에서 생략한다.
  // 2026-08-11: Asset 관리 통합 - collectionId/uncategorized 필터 추가(사이드바
  // 컬렉션 선택에 대응).
  assets: (params: { page?: number; pageSize?: number; type?: string; workflowId?: string; collectionId?: number; uncategorized?: boolean } = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page || 1));
    query.set("pageSize", String(params.pageSize || 20));
    if (params.type) query.set("type", params.type);
    if (params.workflowId) query.set("workflowId", params.workflowId);
    if (params.collectionId) query.set("collectionId", String(params.collectionId));
    if (params.uncategorized) query.set("uncategorized", "true");
    return requestJson<AssetsResponse>(`/api/assets?${query.toString()}`);
  },
  // A-02(5c): 자산 컬렉션. 모두 history:read로 보호.
  collections: () => requestJson<CollectionsResponse>("/api/collections"),
  createCollection: (name: string) =>
    requestJson<CollectionSummary>("/api/collections", { method: "POST", body: JSON.stringify({ name }) }),
  deleteCollection: (id: number) =>
    requestJson<void>(`/api/collections/${id}`, { method: "DELETE" }),
  collection: (id: number) => requestJson<CollectionDetail>(`/api/collections/${id}`),
  addCollectionItem: (id: number, assetId: string) =>
    requestJson<CollectionDetail>(`/api/collections/${id}/items`, { method: "POST", body: JSON.stringify({ assetId }) }),
  // 2026-08-11: Asset 관리 통합 - 컬렉션 칩에서 자산을 뺄 때 사용.
  removeCollectionItem: (id: number, assetId: string) =>
    requestJson<CollectionDetail>(`/api/collections/${id}/items/${encodeURIComponent(assetId)}`, { method: "DELETE" }),
  promptCatalog: () => requestJson<PromptCatalogResponse>("/api/prompts/catalog"),
  promptSystemPrompt: () => requestJson<PromptSystemPromptResponse>("/api/prompts/system-prompt"),
  // B-08: 시스템 지시문 버전 이력.
  systemPromptVersions: (code?: string) =>
    requestJson<SystemPromptVersionsResponse>(`/api/prompts/system-prompt/versions${code ? `?code=${encodeURIComponent(code)}` : ""}`),
  savePromptSystemPrompt: (payload: Record<string, unknown>) =>
    requestJson<PromptSystemPromptResponse>("/api/prompts/system-prompt", {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  promptSceneSchema: () => requestJson<Record<string, unknown>>("/api/prompts/scene-schema"),
  savePromptCategoryGroup: (payload: Record<string, unknown>, groupId?: number) =>
    requestJson<PromptCatalogResponse>(groupId ? `/api/prompts/category-groups/${groupId}` : "/api/prompts/category-groups", {
      method: groupId ? "PUT" : "POST",
      body: JSON.stringify(payload)
    }),
  deactivatePromptCategoryGroup: (groupId: number) =>
    requestJson<PromptCatalogResponse>(`/api/prompts/category-groups/${groupId}/deactivate`, {
      method: "POST"
    }),
  savePromptCategory: (payload: Record<string, unknown>, categoryId?: number) =>
    requestJson<PromptCatalogResponse>(categoryId ? `/api/prompts/categories/${categoryId}` : "/api/prompts/categories", {
      method: categoryId ? "PUT" : "POST",
      body: JSON.stringify(payload)
    }),
  deactivatePromptCategory: (categoryId: number) =>
    requestJson<PromptCatalogResponse>(`/api/prompts/categories/${categoryId}/deactivate`, {
      method: "POST"
    }),
  savePromptTerm: (payload: Record<string, unknown>, termId?: number) =>
    requestJson<PromptCatalogResponse>(termId ? `/api/prompts/terms/${termId}` : "/api/prompts/terms", {
      method: termId ? "PUT" : "POST",
      body: JSON.stringify(payload)
    }),
  deactivatePromptTerm: (termId: number) =>
    requestJson<PromptCatalogResponse>(`/api/prompts/terms/${termId}/deactivate`, {
      method: "POST"
    }),
  buildPromptScene: (payload: {
    workflowId: string;
    segmentIndex: number;
    termIds: number[];
    description?: string;
    constraints?: Record<string, unknown>;
    language?: string;
  }) =>
    requestJson<PromptSceneResponse>("/api/prompts/scene", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  generatePrompt: (payload: {
    workflowId: string;
    segmentIndex: number;
    scene: Record<string, unknown>;
    constraints?: Record<string, unknown>;
    termIds?: number[];
    provider?: string;
    language?: string;
  }) =>
    requestJson<PromptGenerateResponse | PromptGenerationStatusResponse>("/api/prompts/generate", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  generateImagePromptDraft: (payload: {
    assetId: string;
    workflowId: string;
    slotIndex: number;
    regenerate?: boolean;
  }) =>
    requestJson<GrokImagePromptDraftResponse>("/api/prompts/image-drafts/generate", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createImagePromptBatch: (payload: {
    workflowId: string;
    items: Array<{ assetId: string; slotIndex: number; requestedFrames?: number; negativePrompt?: string; sourceRelativePath?: string }>;
  }) =>
    requestJson<PromptGenerationBatchResponse>("/api/prompts/image-drafts/batches", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  promptGenerationBatch: (batchId: string) =>
    requestJson<PromptGenerationBatchResponse>(`/api/prompts/image-drafts/batches/${encodeURIComponent(batchId)}`),
  activePromptGenerationBatch: () =>
    requestJson<{ item: PromptGenerationBatchResponse | null }>("/api/prompts/image-drafts/batches/active"),
  activePromptGenerationBatches: () =>
    requestJson<{ items: PromptGenerationBatchResponse[] }>("/api/prompts/image-drafts/batches/active-list"),
  imagePromptDrafts: (params: { workerId?: string; workflowId?: string; status?: string; page?: number; pageSize?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.workerId) query.set("workerId", params.workerId);
    if (params.workflowId) query.set("workflowId", params.workflowId);
    if (params.status) query.set("status", params.status);
    query.set("page", String(params.page || 1));
    query.set("pageSize", String(params.pageSize || 50));
    return requestJson<PromptDraftListResponse>(`/api/prompts/image-drafts?${query.toString()}`);
  },
  updateImagePromptDraft: (draftId: string, payload: { positivePrompt?: string; negativePrompt?: string; requestedFrames?: number }) =>
    requestJson<GrokImagePromptDraftResponse>(`/api/prompts/image-drafts/${encodeURIComponent(draftId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  retryImagePromptDraft: (draftId: string) =>
    requestJson<GrokImagePromptDraftResponse>(`/api/prompts/image-drafts/${encodeURIComponent(draftId)}/retry`, { method: "POST" }),
  grokInstructions: (workflowId: string) =>
    requestJson<GrokInstructionSetResponse>(`/api/admin/grok-instructions?workflowId=${encodeURIComponent(workflowId)}`),
  grokInstructionSourceWorkflows: () =>
    requestJson<{ workflowIds: string[] }>("/api/admin/grok-instructions/sources"),
  grokInstructionStatus: (workflowId: string) =>
    requestJson<{ workflowId: string; configured: boolean; count: number }>(`/api/prompts/image-drafts/instruction-status?workflowId=${encodeURIComponent(workflowId)}`),
  createGrokInstruction: (payload: GrokInstructionPayload) =>
    requestJson<GrokInstructionSetResponse>("/api/admin/grok-instructions", { method: "POST", body: JSON.stringify(payload) }),
  updateGrokInstruction: (documentId: string, payload: GrokInstructionPayload) =>
    requestJson<GrokInstructionSetResponse>(`/api/admin/grok-instructions/${encodeURIComponent(documentId)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteGrokInstruction: (documentId: string, workflowId: string) =>
    requestJson<GrokInstructionSetResponse>(`/api/admin/grok-instructions/${encodeURIComponent(documentId)}?workflowId=${encodeURIComponent(workflowId)}`, { method: "DELETE" }),
  importGrokInstructionMarkdown: (payload: {
    workflowId: string;
    fileName: string;
    contentMarkdown: string;
    title?: string;
    code?: string;
    role?: "CORE" | "ROUTER" | "GUIDE";
    sortOrder?: number;
    isActive?: boolean;
  }) =>
    requestJson<GrokInstructionSetResponse>("/api/admin/grok-instructions/import-markdown", { method: "POST", body: JSON.stringify(payload) }),
  copyGrokInstructions: (payload: { sourceWorkflowId: string; targetWorkflowId: string }) =>
    requestJson<GrokInstructionSetResponse & { copiedFromWorkflowId?: string }>("/api/admin/grok-instructions/copy", { method: "POST", body: JSON.stringify(payload) }),
  promptGenerationStatus: (requestId: string) =>
    requestJson<PromptGenerationStatusResponse>(`/api/prompts/generate/${encodeURIComponent(requestId)}`),
  savePromptFeedback: (payload: {
    outputId: string;
    taskId: string;
    rating?: number;
    editedPositivePrompt?: string;
    editedNegativePrompt?: string;
    notes?: string;
  }) =>
    requestJson<{ id: string; outputId: string; taskId: string; rating?: number }>("/api/prompts/feedback", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  deleteHistory: (taskId: string) =>
    requestJson<{ ok?: boolean; deleted?: boolean }>(`/api/history/${encodeURIComponent(taskId)}/delete`, {
      method: "POST"
    }),
  reworkHistoryItem: (taskId: string) =>
    requestJson<{ taskId: string; sourceTaskId: string; runpodJobId?: string; status: string; statusLabel?: string; lastDispatchError?: string | null; generationSeed?: number | string | null }>(
      `/api/history/${encodeURIComponent(taskId)}/rework`,
      { method: "POST" }
    ),
  reworkRunpodHistoryItems: (payload: {
    scope: "selected" | "query";
    taskIds?: string[];
    batchId?: string;
    workflowId?: string;
    resultStatus?: string;
    workerId?: string;
    runDate?: string;
  }) =>
    requestJson<RunpodHistoryReworkResponse>("/api/history/runpod/rework", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  upload: (payload: { fileName: string; mimeType: string; dataUrl: string }) =>
    requestJson<UploadResponse>("/api/uploads", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  presignUpload: (payload: S3UploadScope & { fileName: string; mimeType: string }) =>
    requestJson<S3UploadPresignResponse>("/api/uploads/presign", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  completeUpload: (payload: S3UploadScope & { assetId: string; fileName: string; mimeType: string; storageKey: string; sizeBytes: number }) =>
    requestJson<S3UploadCompleteResponse>("/api/uploads/complete", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  deleteUnsubmittedUpload: (assetId: string) =>
    requestJson<{ assetId: string; deleted: boolean }>(`/api/uploads/${encodeURIComponent(assetId)}`, {
      method: "DELETE"
    }),
  presignWebtoonCutUpload: (payload: { fileName: string; mimeType: string; sizeBytes: number }) =>
    requestJson<WebtoonCutUploadPresignResponse>("/api/webtoon-cuts/uploads/presign", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  completeWebtoonCutUpload: (payload: { assetId: string; fileName: string; mimeType: string; storageKey: string; sizeBytes: number }) =>
    requestJson<S3UploadCompleteResponse>("/api/webtoon-cuts/uploads/complete", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createWebtoonCutJob: (payload: { assetId: string; inputKind: string; metadata?: Record<string, unknown> }) =>
    requestJson<WebtoonCutJobResponse>("/api/webtoon-cuts/jobs", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  webtoonCutJobs: (params: { status?: string; inputKind?: string; query?: string; createdBy?: string; page?: number; pageSize?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.inputKind) query.set("inputKind", params.inputKind);
    if (params.query) query.set("query", params.query);
    if (params.createdBy) query.set("createdBy", params.createdBy);
    query.set("page", String(params.page || 1));
    query.set("pageSize", String(params.pageSize || 20));
    return requestJson<WebtoonCutJobListResponse>(`/api/webtoon-cuts/jobs?${query.toString()}`);
  },
  cancelWebtoonCutJob: (jobId: string) =>
    requestJson<WebtoonCutJobResponse>(`/api/webtoon-cuts/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST"
    }),
  deleteWebtoonCutJob: (jobId: string) =>
    requestJson<{ deleted: boolean; jobId: string }>(`/api/webtoon-cuts/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE"
    }),
  webtoonCutOutputs: (jobId: string, params: { usedState?: string; flags?: string; query?: string; page?: number; pageSize?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.usedState) query.set("usedState", params.usedState);
    if (params.flags) query.set("flags", params.flags);
    if (params.query) query.set("query", params.query);
    query.set("page", String(params.page || 1));
    query.set("pageSize", String(params.pageSize || 50));
    return requestJson<WebtoonCutOutputListResponse>(`/api/webtoon-cuts/jobs/${encodeURIComponent(jobId)}/outputs?${query.toString()}`);
  },
  handoffWebtoonCutsToGrok: (jobId: string, outputIds: string[]) =>
    requestJson<WebtoonCutHandoffResponse>(`/api/webtoon-cuts/jobs/${encodeURIComponent(jobId)}/handoff/grok`, {
      method: "POST",
      body: JSON.stringify({ outputIds })
    }),
  handoffWebtoonCutsToBatch: (jobId: string, outputIds: string[]) =>
    requestJson<WebtoonCutHandoffResponse>(`/api/webtoon-cuts/jobs/${encodeURIComponent(jobId)}/handoff/batch`, {
      method: "POST",
      body: JSON.stringify({ outputIds })
    }),
  downloadWebtoonCutOutputsZip: (jobId: string, outputIds: string[]) => {
    const query = new URLSearchParams();
    outputIds.forEach((outputId) => query.append("outputIds", outputId));
    return requestBlob(`/api/webtoon-cuts/jobs/${encodeURIComponent(jobId)}/download?${query.toString()}`);
  },
  createBatchJob: (payload: { workflowId: string; sourceKind?: "webtoon_cut" | "asset_list"; sourceDirName?: string; sourceZipFileName?: string; requestedFrames?: number; resolutionTier?: ResolutionTier; negativePrompt?: string; items: Array<{ assetId: string; fileName?: string; relativePath?: string; requestItemId?: string }> }) =>
    requestJson<BatchJobResponse>("/api/batch-jobs", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createBatchJobFromZip: (payload: { workflowId: string; requestedFrames?: number; resolutionTier?: ResolutionTier; negativePrompt?: string; file: File }) => {
    const formData = new FormData();
    formData.set("workflowId", payload.workflowId);
    formData.set("requestedFrames", String(payload.requestedFrames || 81));
    formData.set("resolutionTier", payload.resolutionTier || "sd");
    formData.set("negativePrompt", payload.negativePrompt || "");
    formData.set("file", payload.file);
    return requestFormJson<BatchJobResponse>("/api/batch-jobs/zip", formData);
  },
  activeBatchJobs: () => requestJson<ActiveBatchJobListResponse>("/api/batch-jobs/active"),
  batchJobDetail: (batchJobId: string) =>
    requestJson<BatchJobDetailResponse>(`/api/batch-jobs/${encodeURIComponent(batchJobId)}`),
  retryFailedBatchItems: (batchJobId: string) =>
    requestJson<BatchJobRetryResponse>(`/api/batch-jobs/${encodeURIComponent(batchJobId)}/retry-failed`, {
      method: "POST",
      body: JSON.stringify({ stage: "all" })
    }),
  retrySelectedBatchItems: (batchJobId: string, payload: { draftIds?: string[]; taskIds?: string[] }) =>
    requestJson<BatchJobRetryResponse>(`/api/batch-jobs/${encodeURIComponent(batchJobId)}/items/retry`, {
      method: "POST",
      body: JSON.stringify({ stage: "all", draftIds: payload.draftIds || [], taskIds: payload.taskIds || [] })
    }),
  batchJobCandidates: (params: { query: string; limit?: number }) => {
    const query = new URLSearchParams();
    query.set("query", params.query);
    query.set("limit", String(params.limit || 10));
    return requestJson<BatchJobCandidateListResponse>(`/api/batch-jobs/search?${query.toString()}`);
  },
  batchJobs: (params: { page?: number; dateFrom?: string; dateTo?: string; workerId?: string; status?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page || 1));
    if (params.dateFrom) query.set("dateFrom", params.dateFrom);
    if (params.dateTo) query.set("dateTo", params.dateTo);
    if (params.workerId) query.set("workerId", params.workerId);
    if (params.status) query.set("status", params.status);
    return requestJson<BatchJobListResponse>(`/api/batch-jobs?${query.toString()}`);
  },
  batchJobZip: (batchJobId: string, taskIds?: string[]) => {
    const query = new URLSearchParams();
    (taskIds || []).forEach((taskId) => query.append("taskIds", taskId));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return requestBlob(`/api/batch-jobs/${encodeURIComponent(batchJobId)}/download${suffix}`);
  },
  createJob: (payload: unknown) =>
    requestJson<JobCreateResponse>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createJobFromPromptDraft: (promptDraftId: string) =>
    requestJson<JobCreateResponse>("/api/jobs/from-prompt-draft", {
      method: "POST",
      body: JSON.stringify({ promptDraftId })
    }),
  createRunpodRequestBatch: (payload: { workerId?: string; items: Array<{ promptDraftId: string; workflowId?: string; requestedFrames?: number; resolutionTier?: ResolutionTier }> }) =>
    requestJson<RunpodRequestBatchResponse>("/api/jobs/request-batches", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  runpodRequestBatch: (batchId: string) =>
    requestJson<RunpodRequestBatchResponse>(`/api/jobs/request-batches/${encodeURIComponent(batchId)}`),
  activeRunpodRequestBatch: (workerId?: string) =>
    requestJson<{ item: RunpodRequestBatchResponse | null }>(`/api/jobs/request-batches/active${workerId ? `?workerId=${encodeURIComponent(workerId)}` : ""}`),
  runpodRequestDashboard: () =>
    requestJson<RunpodRequestDashboardResponse>("/api/jobs/request-batches/dashboard"),
  runpodRequestQueue: (params: { workerId?: string; workflowId?: string; statusFilter?: string; page?: number; pageSize?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.workerId) query.set("workerId", params.workerId);
    if (params.workflowId) query.set("workflowId", params.workflowId);
    if (params.statusFilter) query.set("statusFilter", params.statusFilter);
    query.set("page", String(params.page || 1));
    query.set("pageSize", String(params.pageSize || 10));
    return requestJson<RunpodRequestQueueResponse>(`/api/jobs/request-batches/queue?${query.toString()}`);
  },
  jobStatus: (taskId: string) => requestJson<JobStatusResponse>(`/api/jobs/${encodeURIComponent(taskId)}`),
  jobPrompts: (taskId: string) => requestJson<TaskPromptResponse>(`/api/jobs/${encodeURIComponent(taskId)}/prompts`),
  updateJobPromptReview: (taskId: string, segmentIndex: number, payload: Record<string, unknown>) =>
    requestJson<TaskPromptItem>(`/api/jobs/${encodeURIComponent(taskId)}/prompts/${segmentIndex}/review`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  reusablePrompts: (params: { keyword?: string; workflowId?: string; minRating?: number; reviewedOnly?: boolean; reuseEligible?: boolean; page?: number; pageSize?: number }) => {
    const search = new URLSearchParams();
    if (params.keyword) search.set("keyword", params.keyword);
    if (params.workflowId) search.set("workflowId", params.workflowId);
    if (params.minRating) search.set("minRating", String(params.minRating));
    if (params.reviewedOnly) search.set("reviewedOnly", "true");
    if (typeof params.reuseEligible === "boolean") search.set("reuseEligible", String(params.reuseEligible));
    search.set("page", String(params.page || 1));
    search.set("pageSize", String(params.pageSize || 20));
    return requestJson<ReusablePromptResponse>(`/api/prompts/reusable?${search.toString()}`);
  },
  cancelJob: (taskId: string) =>
    requestJson<JobStatusResponse>(`/api/jobs/${encodeURIComponent(taskId)}/cancel`, {
      method: "POST"
    }),
  adminUsers: () => requestJson<AdminUsersResponse>("/api/admin/users"),
  adminPermissions: () => requestJson<PermissionGovernance>("/api/admin/permissions"),
  taskExecutionPolicy: () => requestJson<TaskExecutionPolicy>("/api/admin/task-execution-policy"),
  saveTaskExecutionPolicy: (payload: Pick<TaskExecutionPolicy, "maxActiveTasksPerUser" | "maxActiveTasksTotal">) =>
    requestJson<TaskExecutionPolicy>("/api/admin/task-execution-policy", {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  saveAdminRolePermissions: (roleCode: string, permissionCodes: string[]) =>
    requestJson<PermissionGovernance>(`/api/admin/roles/${encodeURIComponent(roleCode)}/permissions`, {
      method: "PUT",
      body: JSON.stringify({ permissionCodes })
    }),
  saveAdminUser: (payload: Record<string, unknown>, userId?: string) =>
    requestJson<AdminUsersResponse>(userId ? `/api/admin/users/${encodeURIComponent(userId)}` : "/api/admin/users", {
      method: userId ? "PUT" : "POST",
      body: JSON.stringify(payload)
    }),
  deactivateAdminUser: (userId: string) =>
    requestJson<AdminUsersResponse>(`/api/admin/users/${encodeURIComponent(userId)}/deactivate`, {
      method: "POST"
    }),
  resetAdminUserPassword: (userId: string, password: string) =>
    requestJson<{ user: AdminUser }>(`/api/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ password })
    }),
  adminWorkflows: () => requestJson<AdminWorkflowsResponse>("/api/admin/workflows"),
  registerAdminWorkflow: (payload: Record<string, unknown>) =>
    requestJson<AdminWorkflowsResponse>("/api/admin/workflows", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  activateAdminWorkflow: (workflowId: string) =>
    requestJson<AdminWorkflowsResponse>(`/api/admin/workflows/${encodeURIComponent(workflowId)}/activate`, {
      method: "POST"
    }),
  deactivateAdminWorkflow: (workflowId: string) =>
    requestJson<AdminWorkflowsResponse>(`/api/admin/workflows/${encodeURIComponent(workflowId)}/deactivate`, {
      method: "POST"
    }),
  dashboardSummary: (
    range: DashboardRange,
    limit = 20,
    filters?: { user?: string; workflow?: string; status?: string }
  ) => {
    const params = new URLSearchParams({ range, limit: String(limit) });
    if (filters?.user) params.set("user", filters.user);
    if (filters?.workflow) params.set("workflow", filters.workflow);
    if (filters?.status) params.set("status", filters.status);
    return requestJson<DashboardSummary>(`/api/dashboard/summary?${params.toString()}`);
  },
  sandboxPodStatus: (options?: { live?: boolean }) =>
    requestJson<SandboxPodStatus>(options?.live === false ? "/api/admin/sandbox-pod?live=false" : "/api/admin/sandbox-pod"),
  sandboxPodLive: () => requestJson<SandboxPodLive>("/api/admin/sandbox-pod/live"),
  selectSandboxPod: (podId: string) =>
    requestJson<SandboxPodStatus>("/api/admin/sandbox-pod/select", { method: "POST", body: JSON.stringify({ podId }) }),
  startSandboxPod: (podId?: string | null) =>
    requestJson<SandboxPodStatus>("/api/admin/sandbox-pod/start", {
      method: "POST",
      body: JSON.stringify(podId ? { podId } : {})
    }),
  stopSandboxPod: (podId?: string | null) =>
    requestJson<SandboxPodStatus>("/api/admin/sandbox-pod/stop", {
      method: "POST",
      body: JSON.stringify(podId ? { podId } : {})
    }),
  terminateSandboxPod: (podId: string) =>
    requestJson<SandboxPodStatus>("/api/admin/sandbox-pod/terminate", { method: "POST", body: JSON.stringify({ podId }) }),
  updateSandboxPodSettings: (payload: { autoSwitchOnStartFailure: boolean; podPriority: string[]; replaceSameGpuPods?: boolean }) =>
    requestJson<SandboxPodSettings>("/api/admin/sandbox-pod/settings", { method: "PUT", body: JSON.stringify(payload) }),
  login: (payload: { id: string; password: string }) =>
    requestJson<AuthSession>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  currentSession: () => requestJson<{ user: AdminUser }>("/api/auth/session"),
  // A-06: 무중단 세션 연장. 유효한 토큰으로 호출하면 새 만료시각의 토큰을 재발급받는다.
  refreshSession: () => requestJson<AuthSession>("/api/auth/refresh", { method: "POST" }),
  adminAuditLogs: (params: { page?: number; pageSize?: number; action?: string; targetType?: string; targetId?: string; actorId?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("page", String(params.page || 1));
    query.set("pageSize", String(params.pageSize || 20));
    if (params.action) query.set("action", params.action);
    if (params.targetType) query.set("targetType", params.targetType);
    if (params.targetId) query.set("targetId", params.targetId);
    if (params.actorId) query.set("actorId", params.actorId);
    return requestJson<AuditLogResponse>(`/api/admin/audit-logs?${query.toString()}`);
  }
};
