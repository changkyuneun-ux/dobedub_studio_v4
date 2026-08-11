// styles imported via main.tsx (Vite entry) - not needed again here.
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  apiClient,
  HealthResponse,
  SystemStatusResponse,
  RunpodConnectionResponse,
  WorkflowItem,
  AdminUser,
  PermissionGovernance,
  AdminWorkflow,
  ConfigControl,
  WorkflowSchema,
  MetadataStatusResponse,
  WorkflowWidgetMetadata,
  ModelMetadataResponse,
  OutputAsset,
  PromptEntry,
  PromptCatalogResponse,
  PromptSystemPromptResponse,
  SystemPromptVersion,
  PromptSceneResponse,
  PromptGenerateResponse,
  HistoryItem,
  AssetItem,
  CollectionSummary,
  CollectionDetail,
  JobStatusResponse,
  TaskPromptItem
} from "./api/client";
import { StudioRoute } from "./router";
import {
  User,
  canUse
} from "./auth";
import {
  isSuccessStatus,
  fileUrlWithMode,
  sleep
} from "./helpers/format";
import {
  promptText,
  combinePromptText,
  formatPromptList
} from "./helpers/prompts";
import {
  promptCatalogHasTerms,
  findPromptTermCategory
} from "./helpers/promptCatalog";
import {
  canUseAdminConsole,
  adminUserFormFrom,
  adminPermissionsFromText,
  adminPermissionsToText,
  adminRolePermissionCodes
} from "./helpers/adminForms";
import {
  SegmentState,
  KeyframeState,
  createSegmentsFromSchema,
  createSegmentsFromHistory,
  createKeyframe,
  createKeyframes,
  createKeyframesFromHistory,
  releaseKeyframePreviews,
  fileToDataUrl,
  workflowIdFromHistoryItem,
  openOutputAsset,
  downloadProtectedAsset,
  selectedOutputAsset,
  finalOutputAsset,
  previewSegmentDetailRows
} from "./helpers/workflow";
import { AccessDeniedScreen, ManualScreen } from "./screens/accessScreens";
import { useProtectedAssetUrl } from "./components/ProtectedAssets";
import {
  Create2aScreen,
  Create2bScreen,
  Create2eScreen,
  Create2fScreen,
  Create2cScreen,
  Create2dScreen
} from "./screens/createScreens";
import {
  Create3aScreen,
  Create3RunDetailScreen,
  Create4cScreen,
  Create5aScreen,
  Create5cScreen
} from "./screens/reviewScreens";
import {
  Create7aScreen,
  Create6cScreen,
  Create6dScreen,
  Create5bScreen,
  Create3bScreen,
  Create7bScreen,
  Create3eScreen,
  Create7cScreen,
  Create4aScreen,
  Create4dScreen,
  AdminAuditLogScreen
} from "./screens/adminScreens";
import { PromptCatalogAdminPanelV3 } from "./screens/PromptCatalogAdminPanelV3";

// 권한 가드 버그 수정: 이전에는 route === "history"/"status"/"metadata"/"manual" 값만
// 보고 모달을 열어, 사이드바에 메뉴가 숨겨져 있어도 주소창에 직접 경로를 입력하면
// 권한 없이 데이터를 조회할 수 있었다. admin만 canUseAdminConsole 체크가 있었지만
// 그마저도 조용히 studio로 되돌릴 뿐 사용자에게 이유를 보여주지 않았다.
// design_handoff_dobedub_v3/README.md: "권한이 없는 메뉴는 사이드바에서 숨깁니다.
// 직접 URL 진입만 7g의 403 화면에 도달합니다." — E-05에서 정식 7g 화면
// (screens/accessScreens.tsx의 AccessDeniedScreen)을 구현해, 직접 URL 진입 시
// 아래 deniedRoute 계산으로 그 화면을 본문에 그린다.
export const ROUTE_REQUIRED_PERMISSION: Partial<Record<StudioRoute, string>> = {
  "review.history": "history:read",
  "review.assets": "history:read",
  "review.collections": "history:read",
  "admin.systemPrompt": "prompts:build",
  "admin.sandbox": "sandbox:read",
  "admin.roles": "roles:read",
  "admin.resourceMap": "roles:read",
  "admin.users": "users:read",
  "admin.userDetail": "users:read",
  "admin.workflows": "workflows:read",
  "admin.workflowRegister": "workflows:write",
  "admin.catalogHierarchy": "prompt-catalog:read",
  "admin.catalogTerms": "prompt-catalog:read",
  "admin.negativeDefaults": "prompt-catalog:read",
  "admin.status": "system:read",
  "admin.metadata": "metadata:read",
  "admin.auditLog": "roles:read",
  "access.manual": "manual:read"
};

export function routeAccessGranted(user: User | null, route: StudioRoute): boolean {
  const requiredPermission = ROUTE_REQUIRED_PERMISSION[route];
  if (!requiredPermission) {
    return true;
  }
  return canUse(user, requiredPermission);
}

export const ROUTE_LABEL: Partial<Record<StudioRoute, string>> = {
  "review.history": "Task History",
  "review.assets": "Assets",
  "review.collections": "Collections",
  "admin.systemPrompt": "System Prompt",
  "admin.sandbox": "Sandbox Pod",
  "admin.roles": "역할 & 권한",
  "admin.resourceMap": "기능 리소스 매핑",
  "admin.users": "사용자",
  "admin.userDetail": "사용자 상세",
  "admin.workflows": "워크플로 정의",
  "admin.workflowRegister": "워크플로 등록",
  "admin.catalogHierarchy": "카탈로그 계층",
  "admin.catalogTerms": "용어 관리",
  "admin.negativeDefaults": "Negative 기본값",
  "admin.status": "Check Status",
  "admin.metadata": "Metadata View",
  "admin.auditLog": "감사 로그",
  "access.manual": "User Manual"
};

export function StudioShell({
  user,
  health,
  route,
  onNavigate
}: {
  user: User;
  health: HealthResponse | null;
  route: StudioRoute;
  onNavigate: (route: StudioRoute) => void;
}) {
  const skipWorkflowLoadRef = useRef(false);
  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  // B-01: 백엔드 기본값(20)·설계(3a 페이지 20건)와 통일. 사용자가 20/50 중
  // 고르면 이 값을 그대로 apiClient.history에 명시 전송한다.
  const [historyPageSize, setHistoryPageSize] = useState<20 | 50>(20);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedHistoryTaskId, setSelectedHistoryTaskId] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<HistoryItem | null>(null);
  // E-03(5a): 3a와 동일한 20/50 페이지네이션 패턴을 그대로 따른다.
  const [assets, setAssets] = useState<AssetItem[]>([]);
  const [assetsPage, setAssetsPage] = useState(1);
  const [assetsPageSize, setAssetsPageSize] = useState<20 | 50>(20);
  const [assetsTotal, setAssetsTotal] = useState(0);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetsNotice, setAssetsNotice] = useState("");
  const [assetsTypeFilter, setAssetsTypeFilter] = useState("");
  const [selectedAssetId, setSelectedAssetId] = useState("");
  // A-02 · 5c 컬렉션 상태.
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState<number | null>(null);
  const [collectionDetail, setCollectionDetail] = useState<CollectionDetail | null>(null);
  const [collectionsLoading, setCollectionsLoading] = useState(false);
  const [collectionsNotice, setCollectionsNotice] = useState("");
  const [collectionCreateName, setCollectionCreateName] = useState("");
  // E-04(4a/4d): 구버전 AdminConsoleModal Workflows 탭의 상태를 그대로 옮겨왔다.
  // Create flow가 쓰는 `workflows`(WorkflowItem[], apiClient.workflows())와는 다른
  // 관리자 전용 목록(AdminWorkflow[], apiClient.adminWorkflows() - active/
  // fileExists/paramConfigExists 등 관리 필드 포함)이라 이름을 분리했다.
  const [adminWorkflowItems, setAdminWorkflowItems] = useState<AdminWorkflow[]>([]);
  const [selectedAdminWorkflowId, setSelectedAdminWorkflowId] = useState("");
  const [adminWorkflowForm, setAdminWorkflowForm] = useState<Record<string, string>>({
    workflowId: "",
    description: "",
    workflowJson: "",
    paramConfigJson: ""
  });
  const [adminWorkflowsLoading, setAdminWorkflowsLoading] = useState(false);
  const [adminWorkflowsNotice, setAdminWorkflowsNotice] = useState("");
  // E-04(3e/7c): 구버전 AdminConsoleModal Users 탭의 상태를 그대로 옮겨왔다. 4a/4d와
  // 같은 이유로 StudioShell에 둔다 - 목록(3e)과 상세(7c)를 오갈 때 다시 불러오지
  // 않기 위해서다. permissionGovernance는 apiClient.adminUsers() 응답에 이미
  // 포함돼 있어(admin_service.list_admin_users) 별도 요청 없이 재사용한다.
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([]);
  const [adminUserGovernance, setAdminUserGovernance] = useState<PermissionGovernance | null>(null);
  const [selectedAdminUserId, setSelectedAdminUserId] = useState("");
  const [adminUserForm, setAdminUserForm] = useState<Record<string, string>>(() => adminUserFormFrom(null));
  const [adminUserPasswordReset, setAdminUserPasswordReset] = useState("");
  const [adminUsersLoading, setAdminUsersLoading] = useState(false);
  const [adminUsersNotice, setAdminUsersNotice] = useState("");
  // #4 오류 위치 규칙: 7c 사용자 동작(저장·비번 재설정·비활성화) 실패는 상단 공통
  // notice가 아니라 해당 버튼 근처에 표시한다. 성공 안내는 기존대로 adminUsersNotice.
  const [adminUsersError, setAdminUsersError] = useState("");
  const [modalNotice, setModalNotice] = useState("");
  const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(null);
  const [runpodConnection, setRunpodConnection] = useState<RunpodConnectionResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusNotice, setStatusNotice] = useState("");
  const [manualHtml, setManualHtml] = useState("");
  const [manualLoading, setManualLoading] = useState(false);
  const [manualError, setManualError] = useState("");
  const [metadataWorkflowId, setMetadataWorkflowId] = useState("");
  const [metadataTab, setMetadataTab] = useState<"summary" | "subgraphs" | "parameters" | "models" | "nodes">("summary");
  const [metadataStatus, setMetadataStatus] = useState<MetadataStatusResponse | null>(null);
  const [workflowMetadata, setWorkflowMetadata] = useState<WorkflowWidgetMetadata | null>(null);
  const [modelMetadata, setModelMetadata] = useState<ModelMetadataResponse | null>(null);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [metadataNotice, setMetadataNotice] = useState("");
  const [promptCatalog, setPromptCatalog] = useState<PromptCatalogResponse | null>(null);
  const [promptSystemPrompt, setPromptSystemPrompt] = useState<PromptSystemPromptResponse | null>(null);
  const [promptSystemPromptText, setPromptSystemPromptText] = useState("");
  // B-08: 시스템 지시문 버전 이력(7a 되돌리기).
  const [systemPromptVersions, setSystemPromptVersions] = useState<SystemPromptVersion[]>([]);
  const [promptBuilderPanel, setPromptBuilderPanel] = useState<"keywords" | "systemPrompt">("keywords");
  const [promptSelectedTermIds, setPromptSelectedTermIds] = useState<number[]>([]);
  const [promptScene, setPromptScene] = useState<PromptSceneResponse | null>(null);
  const [promptGenerated, setPromptGenerated] = useState<PromptGenerateResponse | null>(null);
  const [promptSceneDescription, setPromptSceneDescription] = useState("");
  const [promptBuilderLoading, setPromptBuilderLoading] = useState(false);
  const [promptBuilderNotice, setPromptBuilderNotice] = useState("");
  const [promptReviewItems, setPromptReviewItems] = useState<TaskPromptItem[]>([]);
  const [promptReviewLoading, setPromptReviewLoading] = useState(false);
  const [promptReviewNotice, setPromptReviewNotice] = useState("");
  const [promptReuseKeyword, setPromptReuseKeyword] = useState("");
  const [promptReuseItems, setPromptReuseItems] = useState<TaskPromptItem[]>([]);
  const [promptReuseLoading, setPromptReuseLoading] = useState(false);
  const [promptReuseNotice, setPromptReuseNotice] = useState("");
  // 2026-08-11: 카드 그리드 → 리스트 전환과 함께 서버사이드 페이지네이션 추가
  // (고정 20건/페이지 - "최대 20개 이내" 요건). 3a(historyPage 등)와 동일한 패턴.
  const [promptReusePage, setPromptReusePage] = useState(1);
  const [promptReusePageSize] = useState<20>(20);
  const [promptReuseTotal, setPromptReuseTotal] = useState(0);
  const [selectedWorkflow, setSelectedWorkflow] = useState("");
  const [schema, setSchema] = useState<WorkflowSchema | null>(null);
  const [segments, setSegments] = useState<SegmentState[]>([]);
  const [selectedSegmentIndex, setSelectedSegmentIndex] = useState(1);
  const [keyframes, setKeyframes] = useState<KeyframeState[]>([]);
  const [running, setRunning] = useState(false);
  const [cancelRequested, setCancelRequested] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState("");
  const [progress, setProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [logText, setLogText] = useState("");
  const [latestJob, setLatestJob] = useState<JobStatusResponse | null>(null);
  const [outputAssets, setOutputAssets] = useState<OutputAsset[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  // A-03 · 1안(2026-08-11 결정): 알림은 폴링 결과를 클라이언트 토스트로만 처리한다.
  // notifications 테이블·읽음 상태·6e 알림 센터 화면은 만들지 않는다(화면을 떠나면
  // 소실되는 휘발성 알림). 작업이 종료(완료/취소/실패)될 때 아래 showToast로 띄운다.
  const toastIdRef = useRef(0);
  const [toast, setToast] = useState<{ id: number; message: string; tone: "success" | "danger" | "neutral" } | null>(null);
  const workflowSelectionLocked = running || cancelRequested;

  function showToast(message: string, tone: "success" | "danger" | "neutral") {
    toastIdRef.current += 1;
    setToast({ id: toastIdRef.current, message, tone });
  }

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast((current) => (current?.id === toast.id ? null : current)), 6000);
    return () => window.clearTimeout(timer);
  }, [toast?.id]);

  async function loadWorkflowIntoState(workflowId: string, options?: { preserveNotice?: boolean }) {
    setError("");
    const nextSchema = await apiClient.workflowSchema(workflowId);
    releaseKeyframePreviews(keyframes);
    setSchema(nextSchema);
    setSegments(createSegmentsFromSchema(nextSchema));
    setSelectedSegmentIndex(1);
    setKeyframes(createKeyframes(nextSchema.keyframeCount || 1));
    setPromptSceneDescription("");
    setPromptScene(null);
    setPromptGenerated(null);
    resetRunState();
    if (!options?.preserveNotice) {
      setNotice("");
    }
    return nextSchema;
  }

  async function loadHistoryPage(page = historyPage, pageSize = historyPageSize) {
    setHistoryLoading(true);
    setModalNotice("");
    try {
      const response = await apiClient.history(page, pageSize);
      const items = response.items || [];
      setHistory(items);
      setHistoryPage(response.page || page);
      setHistoryTotal(response.total || 0);
      setSelectedHistoryTaskId((current) => {
        if (current && items.some((item) => item.taskId === current)) {
          return current;
        }
        return items[0]?.taskId || "";
      });
    } catch (error) {
      setModalNotice(error instanceof Error ? error.message : "작업 이력을 불러오지 못했습니다.");
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadAssetsPage(page = assetsPage, pageSize = assetsPageSize, type = assetsTypeFilter) {
    setAssetsLoading(true);
    setAssetsNotice("");
    try {
      const response = await apiClient.assets({ page, pageSize, type });
      const items = response.items || [];
      setAssets(items);
      setAssetsPage(response.page || page);
      setAssetsTotal(response.total || 0);
      setSelectedAssetId((current) => {
        if (current && items.some((item) => item.assetId === current)) {
          return current;
        }
        return items[0]?.assetId || "";
      });
    } catch (error) {
      setAssetsNotice(error instanceof Error ? error.message : "자산 목록을 불러오지 못했습니다.");
    } finally {
      setAssetsLoading(false);
    }
  }

  function changeAssetsTypeFilter(type: string) {
    setAssetsTypeFilter(type);
    void loadAssetsPage(1, assetsPageSize, type);
  }

  // A-02 · 5c 컬렉션 로더/핸들러.
  async function loadCollections(selectId?: number) {
    setCollectionsLoading(true);
    setCollectionsNotice("");
    try {
      const response = await apiClient.collections();
      const items = response.items || [];
      setCollections(items);
      const nextId = selectId ?? selectedCollectionId ?? items[0]?.id ?? null;
      setSelectedCollectionId(nextId);
      if (nextId != null) {
        await loadCollectionDetail(nextId);
      } else {
        setCollectionDetail(null);
      }
    } catch (error) {
      setCollectionsNotice(error instanceof Error ? error.message : "컬렉션을 불러오지 못했습니다.");
    } finally {
      setCollectionsLoading(false);
    }
  }

  async function loadCollectionDetail(id: number) {
    try {
      setCollectionDetail(await apiClient.collection(id));
    } catch (error) {
      setCollectionsNotice(error instanceof Error ? error.message : "컬렉션 상세를 불러오지 못했습니다.");
    }
  }

  function selectCollection(id: number) {
    setSelectedCollectionId(id);
    void loadCollectionDetail(id);
  }

  async function createCollection() {
    const name = collectionCreateName.trim();
    if (!name) {
      return;
    }
    setCollectionsNotice("");
    try {
      const created = await apiClient.createCollection(name);
      setCollectionCreateName("");
      await loadCollections(created.id);
      setCollectionsNotice(`컬렉션 "${created.name}"을(를) 만들었습니다.`);
    } catch (error) {
      setCollectionsNotice(error instanceof Error ? error.message : "컬렉션 생성에 실패했습니다.");
    }
  }

  async function addAssetToCollection(assetId: string) {
    if (selectedCollectionId == null) {
      return;
    }
    setCollectionsNotice("");
    try {
      const detail = await apiClient.addCollectionItem(selectedCollectionId, assetId);
      setCollectionDetail(detail);
      // 목록의 itemCount도 갱신되도록 요약을 다시 불러온다(상세 선택은 유지).
      const response = await apiClient.collections();
      setCollections(response.items || []);
    } catch (error) {
      setCollectionsNotice(error instanceof Error ? error.message : "자산을 담지 못했습니다.");
    }
  }

  function changeAssetsPageSize(pageSize: 20 | 50) {
    setAssetsPageSize(pageSize);
    void loadAssetsPage(1, pageSize, assetsTypeFilter);
  }

  // B-01: 페이지 크기를 바꾸면 현재 페이지 번호 기준이 달라지므로 1페이지로
  // 되돌아가 새 크기로 다시 불러온다.
  function changeHistoryPageSize(pageSize: 20 | 50) {
    setHistoryPageSize(pageSize);
    void loadHistoryPage(1, pageSize);
  }

  async function loadPromptReview(taskId: string) {
    if (!taskId) {
      setPromptReviewItems([]);
      return;
    }
    setPromptReviewLoading(true);
    setPromptReviewNotice("");
    try {
      const response = await apiClient.jobPrompts(taskId);
      setPromptReviewItems(response.items || []);
    } catch (error) {
      setPromptReviewItems([]);
      setPromptReviewNotice(error instanceof Error ? error.message : "작업 프롬프트 정보를 불러오지 못했습니다.");
    } finally {
      setPromptReviewLoading(false);
    }
  }

  async function savePromptReview(segmentIndex: number, payload: Record<string, unknown>) {
    if (!selectedHistoryTaskId) {
      return;
    }
    setPromptReviewLoading(true);
    setPromptReviewNotice("");
    try {
      const updated = await apiClient.updateJobPromptReview(selectedHistoryTaskId, segmentIndex, payload);
      setPromptReviewItems((items) => items.map((item) => item.segmentIndex === segmentIndex ? updated : item));
      setPromptReviewNotice("프롬프트 리뷰 정보를 저장했습니다.");
    } catch (error) {
      setPromptReviewNotice(error instanceof Error ? error.message : "프롬프트 리뷰 저장에 실패했습니다.");
    } finally {
      setPromptReviewLoading(false);
    }
  }

  // B-02: task_prompts 기반 "영상 결과 평가"(savePromptReview, 위)와 역할이 분리된
  // "프롬프트 생성 품질" 평가 저장 경로. 3f Run 상세 화면에서만 호출되며,
  // prompt_feedback.taskId를 항상 채워 두 기록을 연결한다(완료 기준).
  // 응답이 outputId 하나 기준의 부분 정보만 담고 있어(id/outputId/taskId/rating),
  // 전체 목록 상태를 신뢰성 있게 갱신하려고 프롬프트 리뷰 전체를 재조회한다.
  async function savePromptFeedback(outputId: string, payload: { rating?: number; notes?: string }) {
    if (!selectedHistoryTaskId || !outputId) {
      return;
    }
    setPromptReviewLoading(true);
    setPromptReviewNotice("");
    try {
      await apiClient.savePromptFeedback({
        outputId,
        taskId: selectedHistoryTaskId,
        rating: payload.rating,
        notes: payload.notes
      });
      await loadPromptReview(selectedHistoryTaskId);
      setPromptReviewNotice("프롬프트 생성 품질 평가를 저장했습니다.");
    } catch (error) {
      setPromptReviewNotice(error instanceof Error ? error.message : "프롬프트 생성 품질 평가 저장에 실패했습니다.");
    } finally {
      setPromptReviewLoading(false);
    }
  }

  // E-03: 4c가 생긴 뒤로 새 화면(2b, 3a)에서는 전체 화면(review.reuse)으로
  // 이동한다. E-06: 구버전 create.workspace 안의 "Prompt Reuse" 버튼과 그 버튼이
  // 쓰던 모달 방식(openPromptReuse/promptReuseOpen/PromptReuseModal)은 제거됐다.
  async function goToPromptReuseScreen() {
    setPromptReuseNotice("");
    await searchPromptReuse(promptReuseKeyword, 1);
    onNavigate("review.reuse");
  }

  // page를 생략하면(새 검색어로 Search 버튼을 누른 경우) 1페이지로 리셋한다 -
  // 이전 검색의 마지막 페이지에 머물러 있다가 새 검색 결과가 그보다 적으면
  // 빈 페이지가 뜨는 상황을 막는다. 페이지 이동(onPageChange)에서만 명시적으로
  // page를 넘긴다.
  async function searchPromptReuse(keyword = promptReuseKeyword, page?: number) {
    const targetPage = page ?? 1;
    setPromptReuseLoading(true);
    setPromptReuseNotice("");
    try {
      const response = await apiClient.reusablePrompts({
        keyword: keyword.trim(),
        reuseEligible: true,
        page: targetPage,
        pageSize: promptReusePageSize
      });
      setPromptReuseItems(response.items || []);
      setPromptReusePage(response.page || targetPage);
      setPromptReuseTotal(response.total || 0);
      if (!(response.items || []).length) {
        setPromptReuseNotice("검색 조건에 맞는 재사용 프롬프트가 없습니다.");
      }
    } catch (error) {
      setPromptReuseItems([]);
      setPromptReuseTotal(0);
      setPromptReuseNotice(error instanceof Error ? error.message : "재사용 프롬프트 검색에 실패했습니다.");
    } finally {
      setPromptReuseLoading(false);
    }
  }

  function applyReusablePrompt(prompt: TaskPromptItem) {
    applyPromptSceneToSegment({
      positivePrompt: prompt.positivePrompt,
      negativePrompt: prompt.negativePrompt,
      negativePromptAddition: "",
      source: `Prompt Reuse #${prompt.id}`
    });
  }

  async function loadSystemStatus() {
    setStatusLoading(true);
    setStatusNotice("");
    try {
      setSystemStatus(await apiClient.systemStatus());
    } catch (error) {
      setStatusNotice(error instanceof Error ? error.message : "시스템 상태를 불러오지 못했습니다.");
    } finally {
      setStatusLoading(false);
    }
  }

  async function testRunpodConnection() {
    setStatusLoading(true);
    setStatusNotice("Checking ComfyUI RunPod endpoint...");
    try {
      const response = await apiClient.runpodConnection();
      setRunpodConnection(response);
      const workers = response.workers || {};
      const jobs = response.jobs || {};
      setStatusNotice(`${response.message || "ComfyUI RunPod checked."} Workers idle/running: ${workers.idle ?? 0}/${workers.running ?? 0}, Queue: ${jobs.inQueue ?? 0}`);
    } catch (error) {
      setRunpodConnection(null);
      setStatusNotice(error instanceof Error ? error.message : "ComfyUI RunPod 연결 확인에 실패했습니다.");
    } finally {
      setStatusLoading(false);
    }
  }

  async function loadManual() {
    setManualLoading(true);
    setManualError("");
    try {
      setManualHtml(await apiClient.manualHtml());
    } catch (error) {
      setManualHtml("");
      setManualError(error instanceof Error ? error.message : "사용자 매뉴얼을 불러오지 못했습니다.");
    } finally {
      setManualLoading(false);
    }
  }

  async function loadMetadata(workflowId = metadataWorkflowId || selectedWorkflow || workflows[0]?.id || "") {
    if (!workflowId) {
      setMetadataNotice("조회할 워크플로우가 없습니다.");
      return;
    }
    setMetadataLoading(true);
    setMetadataNotice("");
    setMetadataWorkflowId(workflowId);
    try {
      const [status, metadata, models] = await Promise.all([
        apiClient.metadataStatus(),
        apiClient.workflowWidgetMetadata(workflowId),
        apiClient.metadataModels()
      ]);
      setMetadataStatus(status);
      setWorkflowMetadata(metadata);
      setModelMetadata(models);
    } catch (error) {
      setMetadataStatus(null);
      setWorkflowMetadata(null);
      setModelMetadata(null);
      setMetadataNotice(error instanceof Error ? error.message : "Metadata를 불러오지 못했습니다.");
    } finally {
      setMetadataLoading(false);
    }
  }

  async function rebuildMetadata() {
    setMetadataLoading(true);
    setMetadataNotice("Metadata를 재생성하고 있습니다.");
    try {
      await apiClient.rebuildMetadata();
      await loadMetadata(metadataWorkflowId || selectedWorkflow);
      setMetadataNotice("Metadata를 재생성했습니다.");
    } catch (error) {
      setMetadataNotice(error instanceof Error ? error.message : "Metadata 재생성에 실패했습니다.");
    } finally {
      setMetadataLoading(false);
    }
  }

  async function loadPromptCatalog(successNotice = "") {
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const catalog = await apiClient.promptCatalog();
      setPromptCatalog(catalog);
      if (!promptCatalogHasTerms(catalog)) {
        setPromptBuilderNotice("Prompt catalog가 비어 있습니다. Admin Console에서 카테고리와 key word를 등록하세요.");
      } else if (successNotice) {
        setPromptBuilderNotice(successNotice);
      }
    } catch (error) {
      setPromptCatalog(null);
      setPromptBuilderNotice(error instanceof Error ? error.message : "Prompt catalog를 불러오지 못했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function refreshPromptBuilder() {
    setPromptBuilderPanel("keywords");
    setPromptSelectedTermIds([]);
    setPromptScene(null);
    setPromptGenerated(null);
    setPromptSceneDescription("");
    await loadPromptCatalog("빌더 화면을 초기화하고 카탈로그를 새로고침했습니다.");
  }

  async function loadPromptSystemPrompt() {
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const response = await apiClient.promptSystemPrompt();
      setPromptSystemPrompt(response);
      setPromptSystemPromptText(response.promptText || "");
      await loadSystemPromptVersions(response.code);
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "System Prompt를 불러오지 못했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  // B-08: 버전 이력 로드. 실패해도 편집 화면 자체는 막지 않는다(이력만 비게 둔다).
  async function loadSystemPromptVersions(code?: string) {
    try {
      const response = await apiClient.systemPromptVersions(code);
      setSystemPromptVersions(response.items || []);
    } catch {
      setSystemPromptVersions([]);
    }
  }

  // B-08: promptText를 명시적으로 받아 저장한다. 되돌리기는 옛 버전 텍스트로 이 함수를
  // 부른다(저장 경로가 하나뿐이라 새 버전이 하나 더 쌓이며 감사 로그도 그대로 남는다).
  async function savePromptSystemPrompt(overrideText?: string) {
    const promptText = overrideText ?? promptSystemPromptText;
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const response = await apiClient.savePromptSystemPrompt({
        code: promptSystemPrompt?.code || "qwen_wan_i2v_positive",
        name: promptSystemPrompt?.name || "Qwen WAN I2V Positive Prompt Composer",
        provider: promptSystemPrompt?.provider || "runpod_vllm",
        modelFamily: promptSystemPrompt?.modelFamily || "qwen",
        promptText
      });
      setPromptSystemPrompt(response);
      setPromptSystemPromptText(response.promptText || "");
      await loadSystemPromptVersions(response.code);
      setPromptBuilderNotice(overrideText !== undefined ? "선택한 버전으로 되돌렸습니다." : "System Prompt를 저장했습니다.");
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "System Prompt 저장에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function savePromptCategory(payload: Record<string, unknown>, categoryId?: number) {
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const catalog = await apiClient.savePromptCategory(payload, categoryId);
      setPromptCatalog(catalog);
      setPromptBuilderNotice("Prompt category를 저장했습니다.");
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "Prompt category 저장에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function savePromptCategoryGroup(payload: Record<string, unknown>, groupId?: number) {
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const catalog = await apiClient.savePromptCategoryGroup(payload, groupId);
      setPromptCatalog(catalog);
      setPromptBuilderNotice("카테고리를 저장했습니다.");
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "카테고리 저장에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function deactivatePromptCategoryGroup(groupId: number) {
    if (!window.confirm("카테고리와 하위 서브 카테고리, key word 연결을 비활성화합니다. 기존 이력은 유지됩니다. 진행하시겠습니까?")) {
      return;
    }
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const catalog = await apiClient.deactivatePromptCategoryGroup(groupId);
      setPromptCatalog(catalog);
      setPromptBuilderNotice("카테고리를 비활성화했습니다.");
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "카테고리 비활성화에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function deactivatePromptCategory(categoryId: number) {
    if (!window.confirm("카테고리와 포함된 key word를 비활성화합니다. 기존 이력은 유지됩니다. 진행하시겠습니까?")) {
      return;
    }
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const catalog = await apiClient.deactivatePromptCategory(categoryId);
      setPromptCatalog(catalog);
      setPromptBuilderNotice("Prompt category를 비활성화했습니다.");
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "Prompt category 비활성화에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function savePromptTerm(payload: Record<string, unknown>, termId?: number) {
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const catalog = await apiClient.savePromptTerm(payload, termId);
      setPromptCatalog(catalog);
      setPromptBuilderNotice("Key word를 저장했습니다.");
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "Key word 저장에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function deactivatePromptTerm(termId: number) {
    if (!window.confirm("선택한 key word를 비활성화합니다. 기존 이력은 유지됩니다. 진행하시겠습니까?")) {
      return;
    }
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const catalog = await apiClient.deactivatePromptTerm(termId);
      setPromptCatalog(catalog);
      setPromptBuilderNotice("Key word를 비활성화했습니다.");
    } catch (error) {
      setPromptBuilderNotice(error instanceof Error ? error.message : "Key word 비활성화에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  async function buildPromptSceneRequest(): Promise<PromptSceneResponse | null> {
    if (!selectedSegment) {
      setPromptBuilderNotice("선택된 서브그래프가 없습니다.");
      return null;
    }
    return apiClient.buildPromptScene({
      workflowId: selectedWorkflow,
      segmentIndex: selectedSegment.index,
      termIds: promptSelectedTermIds,
      language: "ko",
      description: promptSceneDescription.trim(),
      constraints: {
        i2v_mode: true,
        preserve_identity: true,
        avoid_new_objects: true
      }
    });
  }

  async function generatePromptDraft() {
    if (!selectedSegment) {
      setPromptBuilderNotice("선택된 서브그래프가 없습니다.");
      return;
    }
    setPromptBuilderLoading(true);
    setPromptBuilderNotice("");
    try {
      const sceneForGeneration = promptScene || await buildPromptSceneRequest();
      if (!sceneForGeneration) {
        return;
      }
      if (!promptScene) {
        setPromptScene(sceneForGeneration);
      }
      const generated = await apiClient.generatePrompt({
        workflowId: selectedWorkflow,
        segmentIndex: selectedSegment.index,
        scene: sceneForGeneration.scene,
        constraints: sceneForGeneration.constraints,
        termIds: sceneForGeneration.usedTermIds,
        language: "ko"
      });
      setPromptGenerated(generated);
      setPromptBuilderNotice(`${promptScene ? "" : "Scene JSON 자동 생성 후 "}Prompt generation 완료 (${generated.provider}).`);
    } catch (error) {
      setPromptGenerated(null);
      setPromptBuilderNotice(error instanceof Error ? error.message : "Prompt generation에 실패했습니다.");
    } finally {
      setPromptBuilderLoading(false);
    }
  }

  function togglePromptTerm(termId: number) {
    const category = findPromptTermCategory(promptCatalog, termId);
    setPromptScene(null);
    setPromptGenerated(null);
    const sameCategoryTermIds = new Set((category?.terms || []).map((term) => term.id));
    setPromptSelectedTermIds((items) => {
      if (items.includes(termId)) {
        return items.filter((item) => item !== termId);
      }
      if (category?.selectionMode === "single") {
        return [...items.filter((item) => !sameCategoryTermIds.has(item)), termId];
      }
      if (category?.maxSelectCount) {
        const selectedInCategory = items.filter((item) => sameCategoryTermIds.has(item));
        if (selectedInCategory.length >= category.maxSelectCount) {
          return items;
        }
      }
      return [...items, termId];
    });
    if (category?.maxSelectCount && category.selectionMode !== "single") {
      const selectedInCategory = promptSelectedTermIds.filter((item) => sameCategoryTermIds.has(item));
      if (!promptSelectedTermIds.includes(termId) && selectedInCategory.length >= category.maxSelectCount) {
        setPromptBuilderNotice(`${category.nameKo || category.code}는 최대 ${category.maxSelectCount}개까지 선택할 수 있습니다.`);
      }
    }
  }

  function clearPromptBuilderSelection(termIds?: number[]) {
    if (termIds?.length) {
      const removeIds = new Set(termIds);
      setPromptSelectedTermIds((items) => items.filter((item) => !removeIds.has(item)));
    } else {
      setPromptSelectedTermIds([]);
    }
    setPromptScene(null);
    setPromptGenerated(null);
    setPromptBuilderNotice("선택한 key word를 초기화했습니다.");
  }

  function applyPromptSceneToSegment(promptOverride?: {
    positivePrompt?: string;
    negativePrompt?: string;
    negativePromptAddition?: string;
    source?: string;
  }) {
    if (!selectedSegment) {
      return;
    }
    const positivePrompt = promptOverride?.positivePrompt ?? promptGenerated?.positivePrompt ?? promptScene?.positivePromptDraft ?? "";
    const negativePromptAddition = promptOverride?.negativePromptAddition ?? promptGenerated?.negativePrompt ?? promptScene?.negativePromptDraft ?? "";
    updateSegment(selectedSegment.index, (segment) => ({
      ...segment,
      positivePrompt,
      defaultNegativePrompt: segment.defaultNegativePrompt || segment.negativePrompt,
      negativePrompt: promptOverride?.negativePrompt ?? combinePromptText(segment.defaultNegativePrompt || segment.negativePrompt, negativePromptAddition),
      negativePromptAddition: promptOverride?.negativePrompt ?? combinePromptText(segment.defaultNegativePrompt || segment.negativePrompt, negativePromptAddition)
    }));
    setNotice(`${selectedSegment.displayName}에 ${promptOverride?.source || (promptGenerated ? "Generated Prompt" : "Prompt Builder")} 결과를 적용했습니다.`);
  }

  async function loadWorkflows(preferredWorkflowId?: string) {
    const workflowResponse = await apiClient.workflows();
    setWorkflows(workflowResponse || []);
    if (workflowSelectionLocked) {
      return;
    }
    const defaultWorkflow = (workflowResponse || []).find((workflow) => workflow.id === preferredWorkflowId)
      || (workflowResponse || []).find((workflow) => workflow.id === selectedWorkflow)
      || (workflowResponse || []).find((workflow) => workflow.id === "1-images.json")
      || (workflowResponse || [])[0];
    setSelectedWorkflow(defaultWorkflow?.id || "");
  }

  async function loadAdminWorkflows() {
    setAdminWorkflowsLoading(true);
    setAdminWorkflowsNotice("");
    try {
      const response = await apiClient.adminWorkflows();
      const items = response.items || [];
      setAdminWorkflowItems(items);
      setSelectedAdminWorkflowId((current) => (current && items.some((item) => item.id === current)) ? current : items[0]?.id || "");
    } catch (error) {
      setAdminWorkflowsNotice(error instanceof Error ? error.message : "워크플로 목록을 불러오지 못했습니다.");
    } finally {
      setAdminWorkflowsLoading(false);
    }
  }

  async function saveAdminWorkflow() {
    setAdminWorkflowsLoading(true);
    setAdminWorkflowsNotice("");
    try {
      const workflowJson = JSON.parse(adminWorkflowForm.workflowJson || "{}");
      const paramConfigJson = adminWorkflowForm.paramConfigJson.trim() ? JSON.parse(adminWorkflowForm.paramConfigJson) : undefined;
      const response = await apiClient.registerAdminWorkflow({
        workflowId: adminWorkflowForm.workflowId,
        description: adminWorkflowForm.description,
        workflowJson,
        paramConfigJson,
        active: false
      });
      setAdminWorkflowItems(response.items || []);
      const savedWorkflowId = response.registeredWorkflowId || (adminWorkflowForm.workflowId.endsWith(".json") ? adminWorkflowForm.workflowId : `${adminWorkflowForm.workflowId}.json`);
      setSelectedAdminWorkflowId(savedWorkflowId);
      if (response.paramConfigJson) {
        setAdminWorkflowForm((current) => ({
          ...current,
          workflowId: savedWorkflowId,
          paramConfigJson: JSON.stringify(response.paramConfigJson, null, 2)
        }));
      }
      setAdminWorkflowsNotice(response.paramConfigGenerated
        ? "워크플로우를 등록하고 Param Config, 세그먼트 기본값, Metadata를 자동 갱신했습니다."
        : "워크플로우를 등록하고 세그먼트 기본값과 Metadata를 갱신했습니다. 검토 후 활성화하세요.");
      void loadWorkflows();
      onNavigate("admin.workflows");
    } catch (error) {
      setAdminWorkflowsNotice(error instanceof Error ? error.message : "Workflow register failed");
    } finally {
      setAdminWorkflowsLoading(false);
    }
  }

  async function loadAdminWorkflowFile(event: React.ChangeEvent<HTMLInputElement>, target: "workflowJson" | "paramConfigJson") {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setAdminWorkflowsNotice("");
    try {
      const text = await file.text();
      JSON.parse(text);
      setAdminWorkflowForm((current) => ({
        ...current,
        workflowId: target === "workflowJson" && !current.workflowId ? file.name : current.workflowId,
        [target]: text
      }));
      setSelectedAdminWorkflowId("");
      setAdminWorkflowsNotice(target === "workflowJson" ? "워크플로우 JSON을 불러왔습니다. 내용을 확인 후 저장하세요." : "Param Config JSON을 불러왔습니다.");
    } catch (error) {
      setAdminWorkflowsNotice(error instanceof Error ? error.message : "JSON file load failed");
    }
  }

  function startNewAdminWorkflowRegistration() {
    setSelectedAdminWorkflowId("");
    setAdminWorkflowForm({ workflowId: "", description: "", workflowJson: "", paramConfigJson: "" });
    setAdminWorkflowsNotice("워크플로우 JSON 파일을 불러온 뒤 저장하세요.");
    onNavigate("admin.workflowRegister");
  }

  async function setAdminWorkflowActive(workflowId: string, active: boolean) {
    setAdminWorkflowsLoading(true);
    setAdminWorkflowsNotice("");
    try {
      const response = active
        ? await apiClient.activateAdminWorkflow(workflowId)
        : await apiClient.deactivateAdminWorkflow(workflowId);
      setAdminWorkflowItems(response.items || []);
      setAdminWorkflowsNotice(active ? "워크플로우를 활성화했습니다." : "워크플로우를 비활성화했습니다.");
      void loadWorkflows(active ? workflowId : undefined);
    } catch (error) {
      setAdminWorkflowsNotice(error instanceof Error ? error.message : "Workflow status update failed");
    } finally {
      setAdminWorkflowsLoading(false);
    }
  }

  async function loadAdminUsers() {
    setAdminUsersLoading(true);
    setAdminUsersNotice("");
    try {
      const response = await apiClient.adminUsers();
      const items = response.items || [];
      setAdminUsers(items);
      setAdminUserGovernance(response.permissionGovernance || null);
      setSelectedAdminUserId((current) => (current && items.some((item) => item.id === current)) ? current : "");
    } catch (error) {
      setAdminUsersNotice(error instanceof Error ? error.message : "사용자 목록을 불러오지 못했습니다.");
    } finally {
      setAdminUsersLoading(false);
    }
  }

  function selectAdminUser(userId: string) {
    setSelectedAdminUserId(userId);
    setAdminUserForm(adminUserFormFrom(adminUsers.find((item) => item.id === userId) || null));
    setAdminUserPasswordReset("");
    setAdminUsersNotice("");
    onNavigate("admin.userDetail");
  }

  function startNewAdminUserRegistration() {
    setSelectedAdminUserId("");
    setAdminUserForm(adminUserFormFrom(null));
    setAdminUserPasswordReset("");
    setAdminUsersNotice("");
    onNavigate("admin.userDetail");
  }

  function changeAdminUserRole(role: string) {
    setAdminUserForm((current) => ({
      ...current,
      role,
      permissions: adminPermissionsToText(adminPermissionsFromText(current.permissions).filter((permission) => !adminRolePermissionCodes(adminUserGovernance, role).includes(permission)))
    }));
  }

  function toggleAdminUserPermission(permission: string) {
    const rolePermissions = adminRolePermissionCodes(adminUserGovernance, adminUserForm.role);
    if (rolePermissions.includes(permission)) {
      return;
    }
    setAdminUserForm((current) => {
      const currentPermissions = adminPermissionsFromText(current.permissions);
      const next = currentPermissions.includes(permission)
        ? currentPermissions.filter((item) => item !== permission)
        : [...currentPermissions, permission];
      return { ...current, permissions: adminPermissionsToText(next) };
    });
  }

  // 신규 사용자는 초기 비밀번호를 이 저장 경로로 함께 보낸다. 기존 사용자의
  // 비밀번호 변경은 resetSelectedAdminUserPassword()의 전용 엔드포인트로만
  // 이뤄지므로, 여기서는 selectedAdminUserId가 있을 때 password를 보내지 않는다.
  async function saveAdminUserDetail() {
    setAdminUsersLoading(true);
    setAdminUsersNotice("");
    setAdminUsersError("");
    try {
      const payload: Record<string, unknown> = {
        id: adminUserForm.id,
        name: adminUserForm.name,
        role: adminUserForm.role,
        permissions: adminPermissionsFromText(adminUserForm.permissions),
        isActive: adminUserForm.isActive === "true"
      };
      if (!selectedAdminUserId) {
        payload.password = adminUserForm.password;
      }
      const response = await apiClient.saveAdminUser(payload, selectedAdminUserId || undefined);
      setAdminUsers(response.items || []);
      setSelectedAdminUserId(response.user?.id || adminUserForm.id);
      setAdminUsersNotice("사용자 정보를 저장했습니다.");
    } catch (error) {
      setAdminUsersError(error instanceof Error ? error.message : "User save failed");
    } finally {
      setAdminUsersLoading(false);
    }
  }

  // client.ts에 정의만 돼 있고 어디서도 호출되지 않던 엔드포인트를 처음 연결한다.
  async function resetSelectedAdminUserPassword() {
    if (!selectedAdminUserId || !adminUserPasswordReset) {
      return;
    }
    setAdminUsersLoading(true);
    setAdminUsersNotice("");
    setAdminUsersError("");
    try {
      await apiClient.resetAdminUserPassword(selectedAdminUserId, adminUserPasswordReset);
      setAdminUserPasswordReset("");
      setAdminUsersNotice("비밀번호를 재설정했습니다.");
    } catch (error) {
      setAdminUsersError(error instanceof Error ? error.message : "Password reset failed");
    } finally {
      setAdminUsersLoading(false);
    }
  }

  async function deactivateSelectedAdminUser() {
    if (!selectedAdminUserId) {
      return;
    }
    setAdminUsersLoading(true);
    setAdminUsersNotice("");
    setAdminUsersError("");
    try {
      const response = await apiClient.deactivateAdminUser(selectedAdminUserId);
      setAdminUsers(response.items || []);
      setAdminUserForm((current) => ({ ...current, isActive: "false" }));
      setAdminUsersNotice("사용자를 비활성화했습니다.");
    } catch (error) {
      setAdminUsersError(error instanceof Error ? error.message : "User deactivate failed");
    } finally {
      setAdminUsersLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    Promise.all([apiClient.workflows(), apiClient.history(1, historyPageSize)])
      .then(([workflowResponse, historyResponse]) => {
        if (!active) {
          return;
        }
        setWorkflows(workflowResponse || []);
        const defaultWorkflow = (workflowResponse || []).find((workflow) => workflow.id === "1-images.json") || (workflowResponse || [])[0];
        setSelectedWorkflow(defaultWorkflow?.id || "");
        setHistory(historyResponse.items || []);
        setHistoryTotal(historyResponse.total || 0);
        setSelectedHistoryTaskId(historyResponse.items?.[0]?.taskId || "");
      })
      .catch((error: Error) => {
        if (active) {
          setError(error.message);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedWorkflow) {
      return;
    }
    if (skipWorkflowLoadRef.current) {
      skipWorkflowLoadRef.current = false;
      return;
    }
    let active = true;
    setError("");
    loadWorkflowIntoState(selectedWorkflow)
      .then((nextSchema) => {
        if (!active) {
          return;
        }
        setSchema(nextSchema);
      })
      .catch((error: Error) => {
        if (active) {
          setError(error.message);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedWorkflow]);

  useEffect(() => {
    const granted = routeAccessGranted(user, route);
    // E-04: admin.status(6c)·admin.metadata(6d)는 전체 화면(Create6cScreen/
    // Create6dScreen)이라 모달을 자동으로 여닫지 않는다. E-05: 매뉴얼(access.manual,
    // 6b)도 ManualScreen 전체 화면으로 전환돼 더 이상 모달이 아니다 - 라우트 화면
    // 스위치에서 직접 렌더한다. E-06에서 구버전 모달들은 모두 제거됨.
    // E-05: 접근 거부 판정은 렌더 시점에 직접 계산해 7g AccessDeniedScreen을 본문으로
    // 그린다(아래 deniedRoute). 별도 상태로 들고 있으면 라우트 화면이 먼저 마운트돼
    // 권한 없는 API를 호출하는 깜빡임이 생겨, 여기서는 데이터 로딩만 막는다.
    if (!granted) {
      return;
    }

    if (route === "review.history") {
      void loadHistoryPage(1);
    }
    if (route === "review.assets") {
      void loadAssetsPage(1);
    }
    if (route === "review.collections") {
      // 우측 "자산 추가" 패널이 쓸 최근 자산 목록도 함께 불러온다(assets 상태 재사용).
      void loadCollections();
      void loadAssetsPage(1);
    }
    if (route === "admin.systemPrompt" && !promptSystemPrompt) {
      void loadPromptSystemPrompt();
    }
    if (route === "admin.workflows" && !adminWorkflowItems.length) {
      void loadAdminWorkflows();
    }
    if ((route === "admin.users" || route === "admin.userDetail") && !adminUsers.length) {
      void loadAdminUsers();
    }
    if ((route === "admin.catalogHierarchy" || route === "admin.catalogTerms" || route === "admin.negativeDefaults") && !promptCatalog && !promptBuilderLoading) {
      void loadPromptCatalog();
    }
    if (route === "admin.status") {
      void loadSystemStatus();
    }
    if (route === "access.manual" && !manualHtml) {
      void loadManual();
    }
    if (route === "admin.metadata") {
      const workflowId = selectedWorkflow || workflows[0]?.id || "";
      if (!workflowId) {
        return;
      }
      setMetadataWorkflowId(workflowId);
      void loadMetadata(workflowId);
    }
  }, [route, selectedWorkflow, workflows.length, user, promptSystemPrompt, adminWorkflowItems.length, adminUsers.length, promptCatalog, promptBuilderLoading]);

  // E-02 · 2c → 2d: generateVideo()는 create.confirm(2f)의 onRun에서 호출되고
  // 완료(성공/실패/취소)까지 내부적으로 기다린다(pollJob). running이 false로
  // 바뀌는 시점이 곧 종료 시점이므로, 진행 화면(create.progress)에 있는 동안 이
  // 전환이 일어나면 결과 화면(create.result)으로 자동 이동한다.
  useEffect(() => {
    if (route === "create.progress" && !running && latestJob) {
      onNavigate("create.result");
    }
  }, [running, latestJob, route]);

  // E-03: 3f(Run 상세 · 완료)의 평가 패널은 세그먼트별 task_prompts를 보여준다.
  useEffect(() => {
    if (route === "review.runDetail" && selectedHistoryTaskId) {
      void loadPromptReview(selectedHistoryTaskId);
    }
  }, [route, selectedHistoryTaskId]);

  useEffect(() => {
    return () => releaseKeyframePreviews(keyframes);
  }, []);

  const selected = useMemo(
    () => workflows.find((workflow) => workflow.id === selectedWorkflow),
    [workflows, selectedWorkflow]
  );
  const selectedSegment = useMemo(
    () => segments.find((segment) => segment.index === selectedSegmentIndex) || segments[0],
    [segments, selectedSegmentIndex]
  );
  const activeImageIndexes = useMemo(() => {
    if (!selectedSegment) {
      return new Set<number>();
    }
    return new Set([selectedSegment.startImageIndex, selectedSegment.endImageIndex].filter(Boolean));
  }, [selectedSegment]);

  function updateSegment(index: number, updater: (segment: SegmentState) => SegmentState) {
    setSegments((items) => items.map((segment) => (segment.index === index ? updater(segment) : segment)));
  }

  function updateSelectedPrompt(field: "positivePrompt" | "negativePrompt", value: string) {
    if (!selectedSegment) {
      return;
    }
    updateSegment(selectedSegment.index, (segment) => ({ ...segment, [field]: value }));
  }

  function updateConfigValue(key: string, value: string, control?: ConfigControl) {
    if (!selectedSegment) {
      return;
    }
    const resolvedValue = ["string", "text"].includes(control?.type || "") ? value : Number(value);
    updateSegment(selectedSegment.index, (segment) => ({
      ...segment,
      config: {
        ...segment.config,
        [key]: Number.isNaN(resolvedValue) ? value : resolvedValue
      }
    }));
  }

  async function resetSegmentConfigsToDefaults() {
    if (!selectedWorkflow) {
      setNotice("워크플로우를 먼저 선택하세요.");
      return;
    }
    try {
      const defaults = await apiClient.workflowSegmentDefaults(selectedWorkflow);
      const defaultSegments = defaults.segments || [];
      if (!defaultSegments.length) {
        setNotice("현재 워크플로우의 세그먼트 기본값이 없습니다.");
        return;
      }
      setSegments((items) => items.map((segment, index) => {
        const source = defaultSegments[index] || defaultSegments[0] || {};
        const { seed: _seed, Seed: _legacySeed, ...currentConfig } = segment.config;
        const { seed: _defaultSeed, Seed: _legacyDefaultSeed, ...defaultConfig } = source.config || {};
        return {
          ...segment,
          config: {
            ...currentConfig,
            ...defaultConfig
          }
        };
      }));
      setNotice("세그먼트 설정을 워크플로우 기본값으로 초기화했습니다.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "세그먼트 기본값을 불러오지 못했습니다.");
    }
  }

  // E-02 · 2e: design_handoff의 "SEG 01 값 복사"에 대응하는 백엔드 API는 없다(그런
  // 엔드포인트를 만든 적이 없음). seed를 제외한 config는 순수 클라이언트 상태이므로
  // 새 API 없이 첫 세그먼트의 값을 현재 세그먼트로 복사하는 것으로 충분하다 - 서버에
  // 저장되는 값이 아니라 제출 시점에 job payload에 실리는 값이기 때문.
  function copyFirstSegmentConfig(targetIndex: number) {
    const source = segments.find((segment) => segment.index === segments[0]?.index);
    if (!source || source.index === targetIndex) {
      return;
    }
    const { seed: _seed, Seed: _legacySeed, ...sourceConfig } = source.config;
    updateSegment(targetIndex, (segment) => ({
      ...segment,
      config: {
        ...segment.config,
        ...sourceConfig
      }
    }));
    setNotice(`SEG ${String(source.index).padStart(2, "0")} 설정값을 복사했습니다.`);
  }

  async function applySelectedFiles(startIndex: number, files: FileList | null) {
    const selectedFiles = Array.from(files || []);
    if (!selectedFiles.length) {
      return;
    }
    setNotice("이미지 미리보기를 준비하고 업로드를 시작합니다.");
    for (const [offset, file] of selectedFiles.entries()) {
      const targetIndex = startIndex + offset;
      if (targetIndex > keyframes.length) {
        continue;
      }
      const previewUrl = URL.createObjectURL(file);
      setKeyframes((items) =>
        items.map((keyframe) => {
          if (keyframe.index !== targetIndex) {
            return keyframe;
          }
          if (keyframe.previewUrl.startsWith("blob:")) {
            URL.revokeObjectURL(keyframe.previewUrl);
          }
          return {
            ...keyframe,
            file,
            upload: null,
            previewUrl,
            metaText: `${Math.round(file.size / 1024)}KB · pending upload`,
            uploading: true,
            error: ""
          };
        })
      );
      try {
        const upload = await apiClient.upload({
          fileName: file.name,
          mimeType: file.type || "application/octet-stream",
          dataUrl: await fileToDataUrl(file)
        });
        setKeyframes((items) =>
          items.map((keyframe) =>
            keyframe.index === targetIndex
              ? {
                  ...keyframe,
                  upload,
                  uploading: false,
                  metaText: `${upload.fileName} · ${(upload.sizeBytes / 1024 / 1024).toFixed(1)}MB · uploaded`,
                  error: ""
                }
              : keyframe
          )
        );
        setNotice("이미지 업로드가 완료되었습니다.");
      } catch (error) {
        setKeyframes((items) =>
          items.map((keyframe) =>
            keyframe.index === targetIndex
              ? {
                  ...keyframe,
                  uploading: false,
                  error: error instanceof Error ? error.message : "Upload failed"
                }
              : keyframe
          )
        );
        setNotice("일부 이미지 업로드에 실패했습니다.");
      }
    }
  }

  function clearKeyframe(index: number) {
    setKeyframes((items) =>
      items.map((keyframe) => {
        if (keyframe.index !== index) {
          return keyframe;
        }
        if (keyframe.previewUrl.startsWith("blob:")) {
          URL.revokeObjectURL(keyframe.previewUrl);
        }
        return createKeyframe(index);
      })
    );
  }

  const jobPayloadPreview = useMemo(
    () => ({
      workflowId: selectedWorkflow,
      user,
      keyframes: keyframes.map((keyframe) => ({
        index: keyframe.index,
        uploadId: keyframe.upload?.assetId || null,
        fileName: keyframe.upload?.fileName || keyframe.file?.name || `keyframe-${keyframe.index}.png`
      })),
      segments: segments.map((segment) => ({
        index: segment.index,
        nodeId: segment.nodeId,
        subgraphName: segment.subgraphName,
        displayName: segment.displayName,
        positivePrompt: segment.positivePrompt,
        negativePromptAddition: segment.negativePromptAddition || segment.negativePrompt,
        config: segment.config
      }))
    }),
    [keyframes, segments, selectedWorkflow, user]
  );
  const selectedOutput = useMemo(() => selectedOutputAsset(outputAssets, selectedSegmentIndex), [outputAssets, selectedSegmentIndex]);
  const finalOutput = useMemo(() => finalOutputAsset(outputAssets), [outputAssets]);
  const displayOutput = finalOutput || selectedOutput || (latestJob?.outputUrl ? { downloadUrl: latestJob.outputUrl, fileName: "generated output", outputRole: "final" } : null);
  const displayOutputRawUrl = displayOutput?.downloadUrl || displayOutput?.url || "";
  const displayOutputInlineUrl = displayOutputRawUrl ? fileUrlWithMode(displayOutputRawUrl, "inline") : "";
  const displayOutputDownloadUrl = displayOutputRawUrl ? fileUrlWithMode(displayOutputRawUrl, "download") : "";
  const displayOutputMediaUrl = useProtectedAssetUrl(displayOutputInlineUrl);
  const hasSuccessfulOutput = isSuccessStatus(latestJob?.status) && Boolean(displayOutputInlineUrl);
  const hasFailedJob = Boolean(latestJob && ["fail", "failed", "timed_out"].includes(latestJob.status.toLowerCase()));
  const segmentDetailRows = selectedSegment
    ? previewSegmentDetailRows(selectedWorkflow, selectedSegment, segments.length, selectedOutput, finalOutput)
    : [];
  const selectedHistory = useMemo(
    () => history.find((item) => item.taskId === selectedHistoryTaskId) || history[0] || null,
    [history, selectedHistoryTaskId]
  );
  const historyPageCount = Math.max(1, Math.ceil(historyTotal / historyPageSize));
  const assetsPageCount = Math.max(1, Math.ceil(assetsTotal / assetsPageSize));

  async function copyPromptList(prompts: PromptEntry[] | undefined) {
    const text = formatPromptList(prompts);
    if (!text) {
      setModalNotice("복사할 프롬프트가 없습니다.");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setModalNotice("프롬프트를 복사했습니다.");
  }

  async function deleteHistoryItem() {
    if (!deleteTarget?.taskId) {
      return;
    }
    setModalNotice("");
    try {
      await apiClient.deleteHistory(deleteTarget.taskId);
      setDeleteTarget(null);
      await loadHistoryPage(historyPage);
      setNotice("작업 내역과 연결된 asset을 삭제했습니다.");
    } catch (error) {
      setModalNotice(error instanceof Error ? error.message : "삭제에 실패했습니다.");
    }
  }

  async function applyHistoryRework(item: HistoryItem) {
    if (workflowSelectionLocked) {
      setModalNotice("생성 작업이 종료된 후 재작업 정보를 불러올 수 있습니다.");
      return;
    }
    const targetWorkflowId = workflowIdFromHistoryItem(item, workflows, selectedWorkflow);
    if (!targetWorkflowId) {
      setModalNotice("재작업에 사용할 워크플로우를 찾지 못했습니다.");
      return;
    }
    setModalNotice("");
    try {
      const nextSchema = await apiClient.workflowSchema(targetWorkflowId);
      const nextSegments = createSegmentsFromHistory(nextSchema, item);
      const nextKeyframes = createKeyframesFromHistory(nextSchema, item);
      releaseKeyframePreviews(keyframes);
      skipWorkflowLoadRef.current = targetWorkflowId !== selectedWorkflow;
      setSelectedWorkflow(targetWorkflowId);
      setSchema(nextSchema);
      setSegments(nextSegments);
      setSelectedSegmentIndex(1);
      setKeyframes(nextKeyframes);
      resetRunState();
      // Rework loads the run's keyframes/segments back into the create flow, so
      // send the user to its landing screen (2a) regardless of where they were.
      onNavigate("create.load");
      setNotice(`재작업 정보를 생성 화면에 불러왔습니다. 입력 이미지 ${nextKeyframes.filter((keyframe) => keyframe.upload?.assetId).length}개 로드됨.`);
    } catch (error) {
      setModalNotice(error instanceof Error ? error.message : "재작업 정보를 불러오지 못했습니다.");
    }
  }

  async function generateVideo() {
    if (running) {
      return;
    }
    const missing = keyframes.filter((keyframe) => !keyframe.upload?.assetId);
    if (missing.length) {
      setError("입력파일을 업로드하세요. 이 워크플로우는 i2v 전용입니다. t2i, t2v는 지원하지 않습니다.");
      return;
    }
    setRunning(true);
    setCancelRequested(false);
    setError("");
    setNotice("작업을 제출합니다.");
    setProgress(0);
    setElapsedSeconds(0);
    setOutputAssets([]);
    setLatestJob(null);
    setLogText("RUNPOD STATUS : QUEUED");
    try {
      const created = await apiClient.createJob(jobPayloadPreview);
      setCurrentTaskId(created.taskId);
      const finalJob = await pollJob(created.taskId);
      setLatestJob(finalJob);
      if (finalJob.status === "success") {
        setNotice("작업이 완료되었습니다.");
        setOutputAssets(finalJob.outputAssets || []);
        setSegments((items) => items.map((segment) => ({ ...segment, progress: 100 })));
        setHistory((await apiClient.history(1, historyPageSize)).items || []);
        showToast("작업이 완료되었습니다. 결과 화면에서 확인하세요.", "success");
      } else if (finalJob.status === "cancelled") {
        setNotice("작업이 취소되었습니다.");
        showToast("작업이 취소되었습니다.", "neutral");
      } else {
        setNotice(finalJob.message || "작업이 종료되었습니다.");
        setOutputAssets(finalJob.outputAssets || []);
        showToast(finalJob.message || "작업이 실패했습니다.", "danger");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Generate failed";
      setError(message);
      setLogText(`RUNPOD STATUS : FAILED`);
      showToast(message, "danger");
    } finally {
      setRunning(false);
      setCancelRequested(false);
    }
  }

  async function pollJob(taskId: string): Promise<JobStatusResponse> {
    let latest: JobStatusResponse | null = null;
    for (;;) {
      const job = await apiClient.jobStatus(taskId);
      latest = job;
      updateRunProgress(job);
      if (["success", "fail", "cancelled", "timed_out"].includes(job.status.toLowerCase())) {
        return job;
      }
      await sleep(900);
    }
  }

  function updateRunProgress(job: JobStatusResponse) {
    const nextProgress = Math.min(100, Math.max(0, Math.round(job.progress || 0)));
    setProgress(nextProgress);
    setElapsedSeconds(Math.round(job.elapsedSeconds || 0));
    setLogText(job.rawStatus ? `RUNPOD STATUS : ${job.rawStatus.toUpperCase()}` : job.message || job.status);
    setLatestJob(job);
    setSegments((items) => {
      const count = Math.max(1, items.length);
      const range = 100 / count;
      return items.map((segment, index) => {
        const start = index * range;
        const segmentProgress = ((nextProgress - start) / range) * 100;
        return { ...segment, progress: Math.min(100, Math.max(0, Math.round(segmentProgress))) };
      });
    });
  }

  async function cancelGeneration() {
    if (!running || !currentTaskId || cancelRequested) {
      return;
    }
    setCancelRequested(true);
    setNotice("취소 요청을 보냈습니다.");
    try {
      const job = await apiClient.cancelJob(currentTaskId);
      updateRunProgress(job);
      setLatestJob(job);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Cancel failed");
      setCancelRequested(false);
    }
  }

  function resetRunState() {
    setRunning(false);
    setCancelRequested(false);
    setCurrentTaskId("");
    setProgress(0);
    setElapsedSeconds(0);
    setLogText("");
    setLatestJob(null);
    setOutputAssets([]);
  }

  // E-05 · 7g: 권한 없는 라우트에 직접 URL로 진입한 경우 라우트 화면 대신 403
  // AccessDeniedScreen을 본문에 그린다. create.load/access.login은 가드 대상이 아니다.
  const deniedRoute =
    !routeAccessGranted(user, route) && route !== "create.load" && route !== "access.login"
      ? route
      : null;

  return (
    <>
    {deniedRoute ? (
      <AccessDeniedScreen
        user={user}
        route={deniedRoute}
        routeLabel={ROUTE_LABEL[deniedRoute] || deniedRoute}
        requiredPermission={ROUTE_REQUIRED_PERMISSION[deniedRoute] || ""}
        onGoTo={onNavigate}
      />
    ) : route === "access.manual" ? (
      <ManualScreen
        user={user}
        html={manualHtml}
        loading={manualLoading}
        error={manualError}
        onGoTo={onNavigate}
      />
    ) : route === "create.load" ? (
      <Create2aScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        workflows={workflows}
        selectedWorkflow={selectedWorkflow}
        workflowSelectionLocked={workflowSelectionLocked}
        onSelectWorkflow={(workflowId) => {
          if (workflowSelectionLocked) {
            setNotice("생성 중에는 워크플로우를 변경할 수 없습니다. 완료 또는 실패 후 다시 선택하세요.");
            return;
          }
          setSelectedWorkflow(workflowId);
        }}
        schema={schema}
        keyframes={keyframes}
        activeImageIndexes={activeImageIndexes}
        onUploadFiles={applySelectedFiles}
        onClearKeyframe={clearKeyframe}
        onNext={() => onNavigate("create.prompt")}
      />
    ) : route === "create.prompt" ? (
      <Create2bScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        workflowName={selected?.label || selected?.name || selectedWorkflow}
        segments={segments}
        selectedSegmentIndex={selectedSegmentIndex}
        onSelectSegment={setSelectedSegmentIndex}
        catalog={promptCatalog}
        loading={promptBuilderLoading}
        notice={promptBuilderNotice}
        selectedTermIds={promptSelectedTermIds}
        activePanel={promptBuilderPanel}
        systemPrompt={promptSystemPrompt}
        systemPromptText={promptSystemPromptText}
        scene={promptScene}
        generated={promptGenerated}
        sceneDescription={promptSceneDescription}
        baseNegativePrompt={selectedSegment?.defaultNegativePrompt || selectedSegment?.negativePrompt || ""}
        onReloadSystemPrompt={() => void loadPromptSystemPrompt()}
        onSaveSystemPrompt={() => void savePromptSystemPrompt()}
        onSystemPromptTextChange={setPromptSystemPromptText}
        onPanelChange={setPromptBuilderPanel}
        onToggleTerm={togglePromptTerm}
        onSceneDescriptionChange={(value) => {
          setPromptSceneDescription(value);
          setPromptScene(null);
          setPromptGenerated(null);
        }}
        onClearSelection={clearPromptBuilderSelection}
        onGenerate={() => void generatePromptDraft()}
        onApply={applyPromptSceneToSegment}
        onOpenPromptReuse={() => void goToPromptReuseScreen()}
        onNext={() => onNavigate("create.segments")}
      />
    ) : route === "create.segments" ? (
      <Create2eScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        workflowName={selected?.label || selected?.name || selectedWorkflow}
        segments={segments}
        selectedSegmentIndex={selectedSegmentIndex}
        onSelectSegment={setSelectedSegmentIndex}
        keyframes={keyframes}
        onUpdateConfigValue={updateConfigValue}
        onResetDefaults={() => void resetSegmentConfigsToDefaults()}
        onCopyFirstSegmentConfig={copyFirstSegmentConfig}
        onEditPrompt={() => onNavigate("create.prompt")}
        onNext={() => onNavigate("create.confirm")}
      />
    ) : route === "create.confirm" ? (
      <Create2fScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        selected={selected || null}
        selectedWorkflow={selectedWorkflow}
        keyframes={keyframes}
        segments={segments}
        jobPayloadPreview={jobPayloadPreview}
        running={running}
        onEditSegments={() => onNavigate("create.segments")}
        onRun={() => {
          onNavigate("create.progress");
          void generateVideo();
        }}
      />
    ) : route === "create.progress" ? (
      <Create2cScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        selected={selected || null}
        selectedWorkflow={selectedWorkflow}
        keyframes={keyframes}
        segments={segments}
        progress={progress}
        elapsedSeconds={elapsedSeconds}
        logText={logText}
        running={running}
        cancelRequested={cancelRequested}
        currentTaskId={currentTaskId}
        onCancel={() => void cancelGeneration()}
        onViewPayload={() => onNavigate("create.confirm")}
      />
    ) : route === "create.result" ? (
      <Create2dScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        selected={selected || null}
        selectedWorkflow={selectedWorkflow}
        keyframes={keyframes}
        segments={segments}
        latestJob={latestJob}
        outputAssets={outputAssets}
        displayOutput={displayOutput}
        displayOutputMediaUrl={displayOutputMediaUrl}
        displayOutputDownloadUrl={displayOutputDownloadUrl}
        hasSuccessfulOutput={hasSuccessfulOutput}
        hasFailedJob={hasFailedJob}
        elapsedSeconds={elapsedSeconds}
        onDownload={() => downloadProtectedAsset(displayOutputDownloadUrl, displayOutput?.fileName || "generated-output.mp4").catch((downloadError) => setError(downloadError instanceof Error ? downloadError.message : "영상 다운로드에 실패했습니다."))}
        onOpenHistory={() => onNavigate("review.history")}
        onNewRun={() => {
          resetRunState();
          onNavigate("create.load");
        }}
        onReviewSettings={() => onNavigate("create.confirm")}
      />
    ) : route === "review.history" ? (
      <Create3aScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        history={history}
        page={historyPage}
        pageCount={historyPageCount}
        pageSize={historyPageSize}
        total={historyTotal}
        loading={historyLoading}
        selectedTaskId={selectedHistoryTaskId}
        deleteTarget={deleteTarget}
        deleteError={modalNotice}
        onSelect={(item) => setSelectedHistoryTaskId(item.taskId)}
        onPageChange={(page) => void loadHistoryPage(page)}
        onPageSizeChange={changeHistoryPageSize}
        onDownload={(item) => openOutputAsset(item)}
        onRework={(item) => void applyHistoryRework(item)}
        onOpenDetail={(item) => {
          setSelectedHistoryTaskId(item.taskId);
          onNavigate("review.runDetail");
        }}
        onRequestDelete={(item) => { setModalNotice(""); setDeleteTarget(item); }}
        onCancelDelete={() => { setModalNotice(""); setDeleteTarget(null); }}
        onConfirmDelete={() => void deleteHistoryItem()}
        canRework={canUse(user, "jobs:run")}
        canDelete={canUse(user, "history:delete")}
      />
    ) : route === "review.runDetail" ? (
      <Create3RunDetailScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        item={history.find((run) => run.taskId === selectedHistoryTaskId) || null}
        history={history}
        promptReviewItems={promptReviewItems}
        promptReviewLoading={promptReviewLoading}
        promptReviewNotice={promptReviewNotice}
        onSelectRun={(run) => setSelectedHistoryTaskId(run.taskId)}
        onSavePromptReview={(segmentIndex, payload) => void savePromptReview(segmentIndex, payload)}
        onSavePromptFeedback={(outputId, payload) => void savePromptFeedback(outputId, payload)}
        onDownload={(item) => openOutputAsset(item)}
        onRework={(item) => void applyHistoryRework(item)}
        onBackToList={() => onNavigate("review.history")}
        canRework={canUse(user, "jobs:run")}
        canReview={canUse(user, "prompts:review")}
        canGiveFeedback={canUse(user, "prompts:review")}
      />
    ) : route === "review.reuse" ? (
      <Create4cScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        keyword={promptReuseKeyword}
        items={promptReuseItems}
        loading={promptReuseLoading}
        notice={promptReuseNotice}
        page={promptReusePage}
        pageSize={promptReusePageSize}
        total={promptReuseTotal}
        workflowName={selected?.label || selected?.name || selectedWorkflow}
        onKeywordChange={setPromptReuseKeyword}
        onSearch={() => void searchPromptReuse(promptReuseKeyword, 1)}
        onPageChange={(page) => void searchPromptReuse(promptReuseKeyword, page)}
        onApply={(prompt) => {
          applyReusablePrompt(prompt);
          onNavigate("create.prompt");
        }}
      />
    ) : route === "review.assets" ? (
      <Create5aScreen
        user={user}
        health={health}
        onGoTo={(nextRoute) => {
          if (nextRoute === "review.runDetail" && selectedAssetId) {
            const asset = assets.find((item) => item.assetId === selectedAssetId);
            if (asset?.taskId) {
              setSelectedHistoryTaskId(asset.taskId);
            }
          }
          onNavigate(nextRoute);
        }}
        items={assets}
        page={assetsPage}
        pageCount={assetsPageCount}
        pageSize={assetsPageSize}
        total={assetsTotal}
        loading={assetsLoading}
        notice={assetsNotice}
        typeFilter={assetsTypeFilter}
        selectedAssetId={selectedAssetId}
        onSelect={(item) => setSelectedAssetId(item.assetId)}
        onTypeFilterChange={changeAssetsTypeFilter}
        onPageChange={(page) => void loadAssetsPage(page)}
        onPageSizeChange={changeAssetsPageSize}
        onDownload={(item) => downloadProtectedAsset(item.downloadUrl, item.fileName).catch((downloadError) => setAssetsNotice(downloadError instanceof Error ? downloadError.message : "다운로드에 실패했습니다."))}
      />
    ) : route === "review.collections" ? (
      <Create5cScreen
        user={user}
        onGoTo={onNavigate}
        collections={collections}
        selectedCollectionId={selectedCollectionId}
        detail={collectionDetail}
        loading={collectionsLoading}
        notice={collectionsNotice}
        createName={collectionCreateName}
        recentAssets={assets}
        onSelectCollection={selectCollection}
        onCreateNameChange={setCollectionCreateName}
        onCreateCollection={() => void createCollection()}
        onAddAsset={(assetId) => void addAssetToCollection(assetId)}
        onDownload={(item) => downloadProtectedAsset(item.downloadUrl, item.fileName).catch((downloadError) => setCollectionsNotice(downloadError instanceof Error ? downloadError.message : "다운로드에 실패했습니다."))}
      />
    ) : route === "admin.systemPrompt" ? (
      <Create7aScreen
        user={user}
        onGoTo={onNavigate}
        loading={promptBuilderLoading}
        systemPrompt={promptSystemPrompt}
        value={promptSystemPromptText}
        onChange={setPromptSystemPromptText}
        versions={systemPromptVersions}
        onReload={() => void loadPromptSystemPrompt()}
        onSave={() => void savePromptSystemPrompt()}
        onRevert={(promptText) => void savePromptSystemPrompt(promptText)}
      />
    ) : route === "admin.status" ? (
      <Create6cScreen
        user={user}
        onGoTo={onNavigate}
        status={systemStatus}
        connection={runpodConnection}
        loading={statusLoading}
        notice={statusNotice}
        onRefresh={() => void loadSystemStatus()}
        onTestRunpod={() => void testRunpodConnection()}
      />
    ) : route === "admin.metadata" ? (
      <Create6dScreen
        user={user}
        onGoTo={onNavigate}
        workflows={workflows}
        workflowId={metadataWorkflowId}
        activeTab={metadataTab}
        status={metadataStatus}
        metadata={workflowMetadata}
        models={modelMetadata}
        loading={metadataLoading}
        notice={metadataNotice}
        onWorkflowChange={(workflowId) => void loadMetadata(workflowId)}
        onTabChange={setMetadataTab}
        onRebuild={() => void rebuildMetadata()}
      />
    ) : route === "admin.sandbox" ? (
      <Create5bScreen user={user} onGoTo={onNavigate} />
    ) : route === "admin.roles" ? (
      <Create3bScreen user={user} onGoTo={onNavigate} />
    ) : route === "admin.resourceMap" ? (
      <Create7bScreen user={user} onGoTo={onNavigate} />
    ) : route === "admin.users" ? (
      <Create3eScreen
        user={user}
        onGoTo={onNavigate}
        items={adminUsers}
        loading={adminUsersLoading}
        notice={adminUsersNotice}
        onSelectUser={selectAdminUser}
        onNewUser={startNewAdminUserRegistration}
      />
    ) : route === "admin.userDetail" ? (
      <Create7cScreen
        user={user}
        onGoTo={onNavigate}
        selectedUser={adminUsers.find((item) => item.id === selectedAdminUserId) || null}
        form={adminUserForm}
        governance={adminUserGovernance}
        loading={adminUsersLoading}
        notice={adminUsersNotice}
        actionError={adminUsersError}
        passwordResetValue={adminUserPasswordReset}
        onFieldChange={(field, value) => setAdminUserForm((current) => ({ ...current, [field]: value }))}
        onRoleChange={changeAdminUserRole}
        onTogglePermission={toggleAdminUserPermission}
        onSave={() => void saveAdminUserDetail()}
        onPasswordResetValueChange={setAdminUserPasswordReset}
        onResetPassword={() => void resetSelectedAdminUserPassword()}
        onDeactivate={() => void deactivateSelectedAdminUser()}
        onNewUser={startNewAdminUserRegistration}
      />
    ) : route === "admin.workflows" ? (
      <Create4aScreen
        user={user}
        onGoTo={onNavigate}
        items={adminWorkflowItems}
        selectedWorkflowId={selectedAdminWorkflowId}
        loading={adminWorkflowsLoading}
        notice={adminWorkflowsNotice}
        onSelect={setSelectedAdminWorkflowId}
        onNewWorkflow={startNewAdminWorkflowRegistration}
        onActivate={(workflowId) => void setAdminWorkflowActive(workflowId, true)}
        onDeactivate={(workflowId) => void setAdminWorkflowActive(workflowId, false)}
      />
    ) : route === "admin.workflowRegister" ? (
      <Create4dScreen
        user={user}
        onGoTo={onNavigate}
        form={adminWorkflowForm}
        loading={adminWorkflowsLoading}
        notice={adminWorkflowsNotice}
        onFieldChange={(field, value) => setAdminWorkflowForm((current) => ({ ...current, [field]: value }))}
        onLoadFile={(event, target) => void loadAdminWorkflowFile(event, target)}
        onSave={() => void saveAdminWorkflow()}
      />
    ) : route === "admin.catalogHierarchy" || route === "admin.catalogTerms" || route === "admin.negativeDefaults" ? (
      <PromptCatalogAdminPanelV3
        user={user}
        onGoTo={onNavigate}
        focus={route === "admin.catalogTerms" ? "terms" : route === "admin.negativeDefaults" ? "negativeDefaults" : "hierarchy"}
        catalog={promptCatalog}
        loading={promptBuilderLoading}
        notice={promptBuilderNotice}
        onSaveCategoryGroup={(payload, groupId) => void savePromptCategoryGroup(payload, groupId)}
        onDeactivateCategoryGroup={(groupId) => void deactivatePromptCategoryGroup(groupId)}
        onSaveCategory={(payload, categoryId) => void savePromptCategory(payload, categoryId)}
        onDeactivateCategory={(categoryId) => void deactivatePromptCategory(categoryId)}
        onSaveTerm={(payload, termId) => void savePromptTerm(payload, termId)}
        onDeactivateTerm={(termId) => void deactivatePromptTerm(termId)}
      />
    ) : route === "admin.auditLog" ? (
      <AdminAuditLogScreen user={user} onGoTo={onNavigate} />
    ) : (
      // E-06: 구버전 인라인 워크스페이스(studio-grid) JSX는 모든 StudioRoute 분기가
      // 채워지며 도달 불가능해진 죽은 코드였다(정리 대상). 위 분기 어디에도 걸리지
      // 않는 라우트는 이제 없지만, 타입상 남는 fallback은 2a(create.load)와 동일한
      // 화면으로 안전하게 보낸다.
      <Create2aScreen
        user={user}
        health={health}
        onGoTo={onNavigate}
        workflows={workflows}
        selectedWorkflow={selectedWorkflow}
        workflowSelectionLocked={workflowSelectionLocked}
        onSelectWorkflow={(workflowId) => {
          if (workflowSelectionLocked) {
            setNotice("생성 중에는 워크플로우를 변경할 수 없습니다. 완료 또는 실패 후 다시 선택하세요.");
            return;
          }
          setSelectedWorkflow(workflowId);
        }}
        schema={schema}
        keyframes={keyframes}
        activeImageIndexes={activeImageIndexes}
        onUploadFiles={applySelectedFiles}
        onClearKeyframe={clearKeyframe}
        onNext={() => onNavigate("create.prompt")}
      />
    )}
    {/* 2026-08-11: 구버전 ConfirmDeleteModal(전역 렌더) 제거 - Create3aScreen이
       deleteTarget을 받아 자체적으로 v3 스펙 삭제 확인창을 그리므로(reviewScreens.tsx
       213~243번째 줄), 여기서 또 렌더하면 3a에서 확인창이 두 개 겹쳐 떴다.
       E-05: 매뉴얼(6b)도 ManualScreen 전체 화면으로 전환돼 전역 모달 렌더가 없다. */}
    {/* A-03 · 1안: 작업 종료 알림 토스트. 어느 화면에 있든(진행 화면을 떠나도) 보이도록
       StudioShell 루트에 고정 렌더한다. 6초 후 자동 사라짐 + 수동 닫기. */}
    {toast ? (
      <div className={`v3-toast is-${toast.tone}`} role="status" aria-live="polite">
        <span className="v3-toast-dot" aria-hidden="true" />
        <span className="v3-toast-message">{toast.message}</span>
        <button className="v3-toast-close" type="button" aria-label="알림 닫기" onClick={() => setToast(null)}>×</button>
      </div>
    ) : null}
    </>
  );
}
