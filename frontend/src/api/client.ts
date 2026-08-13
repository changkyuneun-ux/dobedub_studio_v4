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
  createdAt?: string | null;
  updatedAt?: string | null;
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
  updatedAt?: string | null;
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

export type SandboxPodStatus = {
  configured: boolean;
  message?: string;
  podId?: string;
  podName?: string | null;
  resolvedBy?: string;
  desiredStatus?: string;
  runtimeStatus?: string;
  lastStartedAt?: string | null;
  lastStatusChange?: string | null;
  locked?: boolean;
  httpServices: Array<{
    internalPort: number;
    url: string;
    label?: string;
  }>;
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
  updatedAt?: string | null;
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
  workflowId?: string;
  workflowName?: string;
  workflow?: string;
  // 2026-08-11: 백엔드 _task_to_history_item()이 이미 내려주고 있었지만 타입에는
  // 빠져 있던 필드 - 3a 우측 패널 Overview 섹션(runpod_job_id 노출)에서 사용.
  runpodJobId?: string;
  workerName?: string;
  user?: { id?: string; name?: string };
  status?: string;
  progress?: number;
  elapsedSeconds?: number;
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

export type HistoryResponse = {
  items: HistoryItem[];
  page: number;
  pageSize: number;
  total: number;
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
  itemCount: number;
};

export type CollectionItem = AssetItem & { sortOrder: number };

export type CollectionDetail = CollectionSummary & { items: CollectionItem[] };

export type CollectionsResponse = { items: CollectionSummary[] };

export type JobCreateResponse = {
  taskId: string;
  runpodJobId: string;
  status: string;
  generationSeed?: number | string;
};

export type TaskExecutionPolicy = {
  maxActiveTasksPerUser: number;
  maxActiveTasksTotal: number;
  activeForUser?: number;
  activeTotal?: number;
  updatedBy?: string | null;
  updatedAt?: string | null;
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
  message?: string;
  outputUrl?: string;
  outputAssets?: OutputAsset[];
  generationSeed?: number | string;
  cancelRequested?: boolean;
};

export type TaskPromptReviewFlags = {
  intentMatched?: boolean;
  identityPreserved?: boolean;
  naturalMotion?: boolean;
  noDistortion?: boolean;
  backgroundStable?: boolean;
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
};

export type TaskPromptItem = {
  id: number;
  taskId: string;
  workflowId: string;
  segmentIndex: number;
  createdBy?: string | null;
  modelProfileId?: string | null;
  modelName?: string | null;
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
  reuseCount?: number;
  metadata?: Record<string, unknown>;
  createdAt?: string | null;
  updatedAt?: string | null;
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
    try {
      const parsed = JSON.parse(rawMessage) as { detail?: unknown; message?: unknown; error?: unknown };
      const detail = parsed.detail ?? parsed.message ?? parsed.error;
      if (typeof detail === "string" && detail.trim()) {
        message = detail.trim();
      }
    } catch {
      // Ignore non-JSON bodies and fall back to a safe, readable message.
    }
    throw new Error(message);
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
  upload: (payload: { fileName: string; mimeType: string; dataUrl: string }) =>
    requestJson<UploadResponse>("/api/uploads", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  createJob: (payload: unknown) =>
    requestJson<JobCreateResponse>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
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
  sandboxPodStatus: () => requestJson<SandboxPodStatus>("/api/admin/sandbox-pod"),
  startSandboxPod: () => requestJson<SandboxPodStatus>("/api/admin/sandbox-pod/start", { method: "POST" }),
  stopSandboxPod: () => requestJson<SandboxPodStatus>("/api/admin/sandbox-pod/stop", { method: "POST" }),
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
