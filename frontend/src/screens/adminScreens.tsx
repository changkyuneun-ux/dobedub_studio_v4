import React, { useEffect, useRef, useState } from "react";
import {
  apiClient,
  SystemStatusResponse,
  RunpodConnectionResponse,
  WorkflowItem,
  AdminUser,
  PermissionGovernance,
  AdminWorkflow,
  TaskExecutionPolicy,
  SandboxPodStatus,
  MetadataStatusResponse,
  WorkflowWidgetMetadata,
  ModelMetadataResponse,
  PromptSystemPromptResponse,
  SystemPromptVersion
} from "../api/client";
import { StudioRoute } from "../router";
import {
  User,
  canUse
} from "../auth";
import { AppShell } from "../components/AppShell";
import { AuditLogTable } from "../components/AuditLogTable";
import { formatTimestamp, qwenStatusLabel } from "../helpers/format";
import {
  adminPermissionsFromText,
  adminPermissionOptions,
  adminRoleOptions,
  adminRolePermissionCodes,
  adminPermissionLabel
} from "../helpers/adminForms";
import { recordText } from "../helpers/workflow";
import { shellNavigate, shellNavigateAdmin } from "../helpers/navigation";

// E-04 · 7a "시스템 프롬프트" — design_handoff_dobedub_v3/4 Admin.dc.html의
// 프롬프트 카탈로그 그룹 화면. 로직은 신규가 아니다 - 2b(Create2bScreen)의
// systemPrompt 패널이 쓰던 것과 완전히 같은 상태(promptSystemPrompt/
// promptSystemPromptText)·핸들러(loadPromptSystemPrompt/savePromptSystemPrompt)를
// 그대로 재사용한다. `prompt_system_prompts`가 code당 1건만 저장하는 전역 레코드라
// (B-08 미착수 - 버전 이력 없음) 2b에서 고쳐도 여기 반영되고 그 반대도 마찬가지다 -
// 두 화면이 같은 데이터를 보는 것이 의도된 동작이다. 버전 이력 UI(B-08)는 아직
// 없지만 A-04 감사 로그(AuditLogTable)로 누가/언제 바꿨는지는 확인할 수 있다.
//
// 조회는 prompts:build 권한(백엔드 GET 요건과 동일), 저장은 prompt-catalog:write
// 권한이 있어야 버튼이 활성화된다(백엔드 PUT 요건과 동일).
//
// B-07 · SYSTEM 그룹 표기: design_handoff는 카탈로그를 POSITIVE·NEGATIVE·SYSTEM
// 3그룹으로 보이지만 이는 **화면 묶음일 뿐 DB 스코프가 아니다.** DB(prompt_scopes)에는
// POSITIVE 계열·NEGATIVE 계열 두 스코프만 있고, 이 SYSTEM 탭이 다루는 시스템 지시문은
// prompt_scopes/prompt_category_groups 계층이 아니라 별도 테이블 prompt_system_prompts에
// code당 1건으로 저장된다. 그래서 이 화면은 스코프→그룹→서브카테고리 트리 없이 지시문
// 한 건만 편집하고, POSITIVE/NEGATIVE 트리를 그리는 PromptCatalogAdminPanelV3(4e/3d/4b)와
// 완전히 분리된 별도 컴포넌트다.
export function Create7aScreen({
  user,
  onGoTo,
  loading,
  systemPrompt,
  value,
  versions,
  onChange,
  onReload,
  onSave,
  onRevert
}: {
  user: User | null;
  onGoTo: (route: StudioRoute) => void;
  loading: boolean;
  systemPrompt: PromptSystemPromptResponse | null;
  value: string;
  // B-08: 최신순 버전 이력. 첫 항목이 현재 값이며, 나머지로 되돌릴 수 있다.
  versions: SystemPromptVersion[];
  onChange: (value: string) => void;
  onReload: () => void;
  onSave: () => void;
  onRevert: (promptText: string) => void;
}) {
  const canSave = canUse(user, "prompt-catalog:write");
  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminCatalog"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 프롬프트 카탈로그"
      headerTitle="시스템 프롬프트"
      headerActions={<button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.catalogHierarchy")}>카탈로그 계층 보기</button>}
      sidebarFooter={<p className="v3-muted-text">4b Negative 기본값은 이관 예정입니다.</p>}
    >
      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">{systemPrompt?.name || "Qwen WAN I2V Positive Prompt Composer"}</div>
          <span className="v3-card-header-meta">{systemPrompt?.provider || "runpod_vllm"}</span>
        </div>
        <div className="v3-system-prompt-body">
          <p className="v3-muted-text">Code {systemPrompt?.code || "qwen_wan_i2v_positive"} · Model {systemPrompt?.modelFamily || "qwen"}</p>
          <p className="v3-muted-text">이 값은 RunPod vLLM/Qwen prompt generation의 system prompt로 사용됩니다. Negative prompt는 앱의 기본값과 선택 키워드로 별도 관리됩니다.</p>
          <textarea
            className="v3-system-prompt-textarea"
            style={{ minHeight: 320 }}
            value={value}
            spellCheck={false}
            disabled={!canSave}
            onChange={(event) => onChange(event.target.value)}
          />
          {!canSave ? <p className="v3-inline-notice">저장 권한(prompt-catalog:write)이 없어 읽기 전용입니다.</p> : null}
          <div className="v3-inline-actions">
            <button className="v3-secondary-button" type="button" disabled={loading} onClick={onReload}>Reload</button>
            <button className="v3-primary-button" type="button" disabled={loading || !canSave || !value.trim()} onClick={onSave}>Save System Prompt</button>
          </div>
        </div>
      </div>
      {/* B-08: 버전 이력 + 되돌리기. 첫 항목(최신)이 현재 값이라 되돌리기 버튼을 주지
          않고 "현재"로 표시하고, 나머지 버전은 그 텍스트로 되돌릴 수 있다. */}
      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">버전 되돌리기</div>
          <span className="v3-card-header-meta">{versions.length} versions</span>
        </div>
        <div style={{ padding: "0 16px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
          {!versions.length ? (
            <p className="v3-muted-text">저장 이력이 없습니다. 저장하면 이 자리에 버전이 쌓이고, 이전 버전으로 되돌릴 수 있습니다.</p>
          ) : versions.map((version, index) => (
            <div className="v3-summary-card" key={version.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12 }}>
                  {index === 0 ? "현재 버전" : `버전 #${version.id}`} · {formatTimestamp(version.createdAtKst || version.createdAt, version.createdAtUtc).replace(/\n/g, " ")}
                  {version.createdBy ? ` · ${version.createdBy}` : ""}
                </div>
                <div className="v3-muted-text" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{version.promptText}</div>
              </div>
              <button
                className="v3-secondary-button"
                type="button"
                disabled={loading || !canSave || index === 0}
                onClick={() => onRevert(version.promptText)}
              >
                {index === 0 ? "현재" : "되돌리기"}
              </button>
            </div>
          ))}
        </div>
      </div>
      <AuditLogTable targetType="prompt_system_prompt" pageSize={5} title="변경 이력" />
    </AppShell>
  );
}

// E-04 · 6c "System Status" — 구버전 StatusModal/StatusCard와 동일한 데이터·판정
// 로직(ok 여부 계산식)을 그대로 옮겼다. 카드 6장(Execution/ComfyUI RunPod/Qwen
// Prompt LLM/Workflows/Segment Defaults/Metadata/Storage)은 모두 실제 헬스체크
// 응답 필드이고 새로 지어낸 값이 없다.
export function Create6cScreen({
  user,
  onGoTo,
  status,
  connection,
  loading,
  notice,
  onRefresh,
  onTestRunpod
}: {
  user: User | null;
  onGoTo: (route: StudioRoute) => void;
  status: SystemStatusResponse | null;
  connection: RunpodConnectionResponse | null;
  loading: boolean;
  notice: string;
  onRefresh: () => void;
  onTestRunpod: () => void;
}) {
  const segmentDefaults = status?.segmentDefaults || {};
  const metadata = status?.metadata || {};
  const workflows = status?.workflows || {};
  const storage = status?.storage || {};
  const defaultsOk = Boolean((segmentDefaults.workflowCount || 0) > 0 && segmentDefaults.matchedCount === segmentDefaults.workflowCount);
  const metadataOk = Boolean(metadata.manifest?.exists && metadata.workflowWidgetMap?.exists && metadata.models?.exists);
  const cards: Array<{ title: string; value: string; detail: string; ok: boolean }> = [
    {
      title: "Execution",
      value: status?.dryRun ? "Dry-run mode" : "RunPod live mode",
      detail: status?.dryRun ? "Actual RunPod calls are disabled." : "Jobs will be submitted to RunPod.",
      ok: Boolean(status?.ok && !status?.dryRun)
    },
    {
      title: "ComfyUI RunPod",
      value: status?.runpod?.configured ? "ONLINE" : "CHECK",
      detail: `Endpoint: ${status?.runpod?.endpointId || "-"}\nBase: ${status?.runpod?.baseUrl || "-"}`,
      ok: Boolean(status?.runpod?.configured)
    },
    {
      title: "Qwen Prompt LLM",
      value: qwenStatusLabel(status?.promptLlm, ""),
      detail: `Provider: ${status?.promptLlm?.provider || "mock"}\nModel: ${status?.promptLlm?.model || "-"}\nAPI key: ${status?.promptLlm?.apiKeyConfigured ? "Configured" : "Not configured"}`,
      ok: Boolean(status?.promptLlm?.configured && status?.promptLlm?.apiKeyConfigured && status?.promptLlm?.provider !== "mock")
    },
    {
      title: "Workflows",
      value: `${workflows.count || 0} files`,
      detail: `${workflows.dir || "-"}\n${(workflows.items || []).slice(0, 6).join(", ") || "No workflow files found."}`,
      ok: Boolean(workflows.exists && (workflows.count || 0) > 0)
    },
    {
      title: "Segment Defaults",
      value: `${segmentDefaults.matchedCount || 0}/${segmentDefaults.workflowCount || 0} matched`,
      detail: defaultsOk ? "All workflow defaults are available." : `Missing: ${(segmentDefaults.missingWorkflows || []).join(", ") || "-"}`,
      ok: defaultsOk
    },
    {
      title: "Metadata",
      value: metadataOk ? "Ready" : "Check files",
      detail: `Manifest: ${metadata.manifest?.exists ? "OK" : "Missing"}\nWidget map: ${metadata.workflowWidgetMap?.exists ? "OK" : "Missing"}\nModels: ${metadata.models?.exists ? "OK" : "Missing"}`,
      ok: metadataOk
    },
    {
      title: "Storage",
      value: storage.outputsDir?.writable ? "Writable" : "Check path",
      detail: `Data: ${storage.dataDir?.path || "-"}\nOutputs: ${storage.outputsDir?.path || "-"}`,
      ok: Boolean(storage.dataDir?.writable && storage.outputsDir?.writable)
    }
  ];

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem=""
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="ADMIN · SYSTEM STATUS"
      headerTitle="System Status"
      headerActions={
        <>
          <button className="v3-secondary-button" type="button" disabled={loading} onClick={onTestRunpod}>Test ComfyUI</button>
          <button className="v3-primary-button" type="button" disabled={loading} onClick={onRefresh}>Refresh</button>
        </>
      }
      sidebarFooter={<p className="v3-muted-text">Last checked: {formatTimestamp(status?.checkedAtKst || status?.checkedAt, status?.checkedAtUtc).replace(/\n/g, " ")}</p>}
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      {connection ? <p className={`v3-inline-notice ${connection.ok ? "" : "is-warning"}`}>{connection.message || "ComfyUI RunPod checked."}</p> : null}
      <div className="v3-status-card-grid">
        {cards.map((card) => (
          <div className={`v3-card v3-status-card ${card.ok ? "is-ok" : "is-alert"}`} key={card.title}>
            <div className="v3-card-header">
              <div className="v3-card-header-title">{card.title}</div>
              <span className={`v3-status-badge ${card.ok ? "is-ready" : "is-pending"}`}>{card.value}</span>
            </div>
            <p className="v3-status-card-detail">{card.detail}</p>
          </div>
        ))}
      </div>
    </AppShell>
  );
}

export const METADATA_TABS: Array<["summary" | "subgraphs" | "parameters" | "models" | "nodes", string]> = [
  ["summary", "Summary"],
  ["subgraphs", "Subgraphs"],
  ["parameters", "Parameters"],
  ["models", "Models"],
  ["nodes", "Nodes"]
];

// E-04 · 6d "메타데이터" 화면의 탭별 본문. 구버전 renderMetadataTab()과 데이터
// 로직(어떤 필드를 어떤 탭에서 보여줄지)은 완전히 동일하고, 마크업만 구버전
// dark-theme 클래스(metadata-card/metadata-node 등) 대신 v3-* 카드로 새로 짰다.
export function renderMetadataTabV3(
  activeTab: "summary" | "subgraphs" | "parameters" | "models" | "nodes",
  status: MetadataStatusResponse | null,
  metadata: WorkflowWidgetMetadata | null,
  modelMetadata: ModelMetadataResponse | null
) {
  if (!metadata && activeTab !== "models") {
    return <p className="v3-muted-text">Metadata가 없습니다.</p>;
  }
  if (activeTab === "summary") {
    const manifest = status?.manifest || {};
    return (
      <div className="v3-card">
        <div className="v3-summary-card" style={{ padding: 16 }}>
          <div className="v3-summary-row"><span>Workflow ID</span><strong>{metadata?.workflowId || "-"}</strong></div>
          <div className="v3-summary-row"><span>Node Count</span><strong>{metadata?.nodeCount ?? "-"}</strong></div>
          <div className="v3-summary-row"><span>Subgraphs</span><strong>{metadata?.segments?.length || 0}</strong></div>
          <div className="v3-summary-row"><span>Generated At</span><strong>{formatTimestamp(String(manifest.generatedAtKst || manifest.generatedAt || "-"), typeof manifest.generatedAtUtc === "string" ? manifest.generatedAtUtc : undefined).replace(/\n/g, " ")}</strong></div>
          <div className="v3-summary-row"><span>Object Info Snapshot</span><strong>{manifest.hasObjectInfoSnapshot ? "YES" : "NO"}</strong></div>
          <div className="v3-summary-row"><span>Fingerprint</span><strong>{String(manifest.fingerprint || "-").slice(0, 32)}</strong></div>
        </div>
      </div>
    );
  }
  if (activeTab === "subgraphs") {
    const segments = metadata?.segments || [];
    return segments.length ? (
      <div className="v3-reuse-grid">
        {segments.map((segment, index) => (
          <div className="v3-card" key={`${recordText(segment, "nodeId")}-${index}`}>
            <div className="v3-card-header">
              <div className="v3-card-header-title">{recordText(segment, "displayName") || `Subgraph_${index + 1}`}</div>
            </div>
            <div className="v3-summary-card" style={{ padding: 16 }}>
              <div className="v3-summary-row"><span>Node ID</span><strong>{recordText(segment, "nodeId") || "-"}</strong></div>
              <div className="v3-summary-row"><span>Class Type</span><strong>{recordText(segment, "classType") || "-"}</strong></div>
              <div className="v3-summary-row"><span>Positive Node</span><strong>{recordText(segment, "positiveNode") || "-"}</strong></div>
              <div className="v3-summary-row"><span>Negative Node</span><strong>{recordText(segment, "negativeNode") || "-"}</strong></div>
              <div className="v3-summary-row"><span>Start Image</span><strong>{recordText(segment, "startImageNode") || "-"}</strong></div>
              <div className="v3-summary-row"><span>End Image</span><strong>{recordText(segment, "endImageNode") || "-"}</strong></div>
            </div>
          </div>
        ))}
      </div>
    ) : <p className="v3-muted-text">Subgraph metadata가 없습니다.</p>;
  }
  if (activeTab === "parameters") {
    const segments = metadata?.segments || [];
    return segments.length ? (
      <>
        {segments.map((segment, index) => {
          const params = Array.isArray(segment.params) ? segment.params as Record<string, unknown>[] : [];
          return (
            <div className="v3-card" key={`${recordText(segment, "nodeId")}-${index}`} style={{ marginBottom: 14 }}>
              <div className="v3-card-header">
                <div className="v3-card-header-title">{recordText(segment, "displayName") || `Subgraph_${index + 1}`}</div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16 }}>
                {params.length ? params.map((param, paramIndex) => (
                  <div key={`${recordText(param, "param")}-${paramIndex}`}>
                    <div style={{ fontWeight: 600, fontSize: 12.5 }}>{recordText(param, "label") || recordText(param, "param") || "-"}</div>
                    <div className="v3-muted-text">{recordText(param, "param") || "-"} · default {recordText(param, "default") || "-"}</div>
                    <pre className="v3-payload-json">{JSON.stringify(param.targets || [], null, 2)}</pre>
                  </div>
                )) : <p className="v3-muted-text">No parameters.</p>}
              </div>
            </div>
          );
        })}
      </>
    ) : <p className="v3-muted-text">Parameter metadata가 없습니다.</p>;
  }
  if (activeTab === "models") {
    const modelGroups = metadata?.models || modelMetadata?.models || {};
    const entries = Object.entries(modelGroups);
    return entries.length ? (
      <div className="v3-reuse-grid">
        {entries.map(([group, values]) => (
          <div className="v3-card" key={group}>
            <div className="v3-card-header">
              <div className="v3-card-header-title">{group}</div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: 16 }}>
              {(values || []).map((value) => <div className="v3-muted-text" key={value}>{value}</div>)}
            </div>
          </div>
        ))}
      </div>
    ) : <p className="v3-muted-text">Model metadata가 없습니다.</p>;
  }
  const nodes = metadata?.nodes || [];
  return nodes.length ? (
    <div className="v3-card">
      {nodes.map((node, index) => (
        <details className="v3-checklist-item" style={{ display: "block", padding: 12 }} key={`${recordText(node, "nodeId")}-${index}`}>
          <summary style={{ cursor: "pointer" }}><strong>{recordText(node, "nodeId") || "-"}</strong> {recordText(node, "title") || recordText(node, "classType")}</summary>
          <p className="v3-muted-text">Class: {recordText(node, "classType") || "-"}</p>
          <pre className="v3-payload-json">{JSON.stringify({ inputs: node.inputs || [], links: node.links || [] }, null, 2)}</pre>
        </details>
      ))}
    </div>
  ) : <p className="v3-muted-text">Node metadata가 없습니다.</p>;
}

// E-04 · 6d "메타데이터" — 구버전 MetadataModal과 동일한 상태/핸들러
// (metadataStatus/workflowMetadata/modelMetadata, loadMetadata)를 재사용한다.
export function Create6dScreen({
  user,
  onGoTo,
  workflows,
  workflowId,
  activeTab,
  status,
  metadata,
  models,
  loading,
  notice,
  onWorkflowChange,
  onTabChange,
  onRebuild
}: {
  user: User | null;
  onGoTo: (route: StudioRoute) => void;
  workflows: WorkflowItem[];
  workflowId: string;
  activeTab: "summary" | "subgraphs" | "parameters" | "models" | "nodes";
  status: MetadataStatusResponse | null;
  metadata: WorkflowWidgetMetadata | null;
  models: ModelMetadataResponse | null;
  loading: boolean;
  notice: string;
  onWorkflowChange: (workflowId: string) => void;
  onTabChange: (tab: "summary" | "subgraphs" | "parameters" | "models" | "nodes") => void;
  onRebuild: () => void;
}) {
  return (
    <AppShell
      user={user}
      area="generate"
      activeItem=""
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="ADMIN · METADATA"
      headerTitle="Workflow Metadata"
      headerActions={
        <>
          <select className="v3-page-size-select" value={workflowId} onChange={(event) => onWorkflowChange(event.target.value)}>
            {workflows.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>{workflow.name || workflow.label || workflow.id}</option>
            ))}
          </select>
          <button className="v3-primary-button" type="button" disabled={loading} onClick={onRebuild}>
            {loading ? "Rebuilding..." : "Rebuild Metadata"}
          </button>
        </>
      }
      sidebarExtra={
        <div className="v3-step-tracker v3-sidebar-context-menu">
          {/* 2026-08-12: 사용자 요청 - sidebarExtra 표준화, 라벨 없던 화면에 추가 */}
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>METADATA · {METADATA_TABS.length}</div>
          {METADATA_TABS.map(([tab, label]) => (
            <button
              key={tab}
              type="button"
              className={`v3-segment-nav-item ${activeTab === tab ? "is-active" : ""}`}
              onClick={() => onTabChange(tab)}
            >
              <div className="v3-segment-nav-head"><span>{label}</span></div>
            </button>
          ))}
        </div>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      {loading && !metadata ? <p className="v3-muted-text">Metadata를 불러오는 중입니다.</p> : renderMetadataTabV3(activeTab, status, metadata, models)}
    </AppShell>
  );
}

function formatSandboxPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value)}%` : "-";
}

function formatSandboxUptime(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "-";
  const totalSeconds = Math.floor(value);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatSandboxCapacity(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${value} GB` : "-";
}

// E-04 · 5b "Sandbox Pod" — 구버전 AdminConsoleModal의 Sandbox 탭은 관리자
// 전용 상태(users/roles/workflows 등)를 전부 한 컴포넌트 안에 갖고 있어 그대로
// 재사용할 수 없다. 그 탭이 쓰던 sandboxPod/sandboxPodLoading/
// sandboxPodPendingAction 상태와 loadSandboxPod/controlSandboxPod 로직만 이
// 화면 자체의 상태로 옮겨 왔다 - 계산식·API 호출은 한 글자도 바꾸지 않았다.
export function Create5bScreen({ user, onGoTo }: { user: User; onGoTo: (route: StudioRoute) => void }) {
  const canControl = canUse(user, "sandbox:control");
  const [sandboxPod, setSandboxPod] = useState<SandboxPodStatus | null>(null);
  const [sandboxPodLoading, setSandboxPodLoading] = useState(false);
  const [sandboxPodPendingAction, setSandboxPodPendingAction] = useState<"start" | "stop" | null>(null);
  const [notice, setNotice] = useState("");
  const autoLoadAttempted = useRef(false);

  async function loadSandboxPod() {
    setSandboxPodLoading(true);
    setNotice("");
    try {
      setSandboxPod(await apiClient.sandboxPodStatus());
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Sandbox Pod status load failed");
    } finally {
      setSandboxPodLoading(false);
    }
  }

  async function controlSandboxPod(action: "start" | "stop") {
    setSandboxPodLoading(true);
    setNotice("");
    try {
      const response = action === "start" ? await apiClient.startSandboxPod() : await apiClient.stopSandboxPod();
      setSandboxPod(response);
      setNotice(response.message || (action === "start" ? "Sandbox Pod 시작을 요청했습니다." : "Sandbox Pod 중지를 요청했습니다."));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Sandbox Pod control failed");
    } finally {
      setSandboxPodLoading(false);
    }
  }

  useEffect(() => {
    if (!autoLoadAttempted.current) {
      autoLoadAttempted.current = true;
      void loadSandboxPod();
    }
  }, []);

  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminSandbox"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · SANDBOX POD"
      headerTitle="Sandbox Pod"
      headerActions={
        <>
          <button className="v3-secondary-button" type="button" disabled={sandboxPodLoading} onClick={() => void loadSandboxPod()}>Refresh Status</button>
          {canControl && ["EXITED", "TERMINATED"].includes(sandboxPod?.desiredStatus || "") ? (
            <button className="v3-primary-button" type="button" disabled={sandboxPodLoading || !sandboxPod || sandboxPod.configured === false} onClick={() => setSandboxPodPendingAction("start")}>Deploy Sandbox Pod</button>
          ) : null}
          {canControl ? (
            <button className="v3-danger-button" style={{ background: "var(--v3-danger)", color: "#fff", borderColor: "var(--v3-danger)" }} type="button" disabled={sandboxPodLoading || !sandboxPod || sandboxPod.configured === false || sandboxPod.desiredStatus === "EXITED" || sandboxPod.desiredStatus === "TERMINATED"} onClick={() => setSandboxPodPendingAction("stop")}>Stop Pod</button>
          ) : null}
        </>
      }
      sidebarFooter={<p className="v3-muted-text">일상적인 영상 생성용 Serverless와 분리된 전용 Pod입니다. 여기서는 Pod 상태와 노출된 HTTP 서비스만 관리합니다.</p>}
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">Pod 상태</div>
          <span className="v3-status-badge is-ready">{sandboxPod?.runtimeStatus || sandboxPod?.desiredStatus || "NOT CHECKED"}</span>
        </div>
        {!sandboxPod && sandboxPodLoading ? <p className="v3-muted-text" style={{ padding: 16 }}>Sandbox Pod 상태를 확인 중입니다.</p> : null}
        {sandboxPod ? (
          <div className="v3-summary-card" style={{ padding: 16 }}>
            <div className="v3-summary-row"><span>Pod ID</span><strong>{sandboxPod.podId || "-"}</strong></div>
            <div className="v3-summary-row"><span>Pod Name</span><strong>{sandboxPod.podName || "-"}</strong></div>
            <div className="v3-summary-row"><span>Resolved By</span><strong>{sandboxPod.resolvedBy || "Pod ID (legacy)"}</strong></div>
            <div className="v3-summary-row"><span>Status</span><strong>{sandboxPod.desiredStatus || "UNKNOWN"}</strong></div>
            <div className="v3-summary-row"><span>Service Status</span><strong>{sandboxPod.runtimeStatus || "NOT CHECKED"}</strong></div>
            <div className="v3-summary-row"><span>Last Started</span><strong>{formatTimestamp(sandboxPod.lastStartedAtKst || sandboxPod.lastStartedAt, sandboxPod.lastStartedAtUtc).replace(/\n/g, " ")}</strong></div>
            <div className="v3-summary-row"><span>Lifecycle Event Time</span><strong>{formatTimestamp(sandboxPod.lastStatusChangeKst || sandboxPod.lastStatusChange, sandboxPod.lastStatusChangeUtc).replace(/\n/g, " ")}</strong></div>
            <div className="v3-summary-row"><span>Last Lifecycle Event</span><strong>{sandboxPod.lastLifecycleEvent || "-"}</strong></div>
            <div className="v3-summary-row"><span>Status Checked</span><strong>{formatTimestamp(sandboxPod.checkedAtKst || sandboxPod.checkedAt, sandboxPod.checkedAtUtc).replace(/\n/g, " ")}</strong></div>
          </div>
        ) : null}
      </div>
      {sandboxPod ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">HTTP Services</div>
            <span className="v3-card-header-meta">{sandboxPod.httpServices.length}</span>
          </div>
          <div className="v3-sandbox-service-list">
            {sandboxPod.httpServices.length ? sandboxPod.httpServices.map((service) => (
              <a className="v3-sandbox-service-link" href={service.url} key={service.url} rel="noreferrer" target="_blank">
                <span className="v3-sandbox-service-name">{service.label || `HTTP ${service.internalPort}`}</span>
                <span className="v3-sandbox-service-port">HTTP {service.internalPort}</span>
                <span className="v3-sandbox-service-url">{service.url}</span>
              </a>
            )) : <p className="v3-muted-text">{sandboxPod.message || "노출된 HTTP 서비스가 없습니다."}</p>}
          </div>
        </div>
      ) : null}
      {sandboxPod ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">RunPod System Status</div>
            <span className="v3-card-header-meta">{sandboxPod.systemStatus?.mode === "live" ? "LIVE" : "CONFIGURATION"}</span>
          </div>
          {sandboxPod.systemStatus?.available ? (
            <div className="v3-sandbox-metric-grid">
              <div className="v3-sandbox-metric"><span>Uptime</span><strong>{formatSandboxUptime(sandboxPod.systemStatus.uptimeSeconds)}</strong></div>
              <div className="v3-sandbox-metric"><span>CPU</span><strong>{formatSandboxPercent(sandboxPod.systemStatus.cpuPercent)}</strong></div>
              <div className="v3-sandbox-metric"><span>Memory</span><strong>{formatSandboxPercent(sandboxPod.systemStatus.memoryPercent)}</strong></div>
              <div className="v3-sandbox-metric"><span>GPU</span><strong>{sandboxPod.systemStatus.gpus.length || sandboxPod.systemStatus.gpuCount || "-"}</strong></div>
              <div className="v3-sandbox-metric v3-sandbox-metric-wide">
                <span>GPU Utilization</span>
                <strong>{sandboxPod.systemStatus.gpus.length
                  ? sandboxPod.systemStatus.gpus.map((gpu, index) => `GPU ${index + 1} ${formatSandboxPercent(gpu.gpuUtilPercent)} / VRAM ${formatSandboxPercent(gpu.memoryUtilPercent)}`).join(" · ")
                  : "-"}
                </strong>
              </div>
              <div className="v3-sandbox-metric v3-sandbox-metric-wide">
                <span>Storage</span>
                <strong>Container {formatSandboxCapacity(sandboxPod.systemStatus.storage?.containerDiskInGb)} · Volume {formatSandboxCapacity(sandboxPod.systemStatus.storage?.volumeInGb)}</strong>
              </div>
            </div>
          ) : (
            <div className="v3-sandbox-metric-grid">
              <div className="v3-sandbox-metric"><span>GPU</span><strong>{sandboxPod.systemStatus?.gpuCount || "-"}</strong></div>
              <div className="v3-sandbox-metric"><span>Memory</span><strong>{formatSandboxCapacity(sandboxPod.systemStatus?.memoryInGb)}</strong></div>
              <div className="v3-sandbox-metric v3-sandbox-metric-wide"><span>GPU Type</span><strong>{sandboxPod.systemStatus?.gpuType || "-"}</strong></div>
              <div className="v3-sandbox-metric v3-sandbox-metric-wide"><span>Storage</span><strong>Container {formatSandboxCapacity(sandboxPod.systemStatus?.storage?.containerDiskInGb)} · Volume {formatSandboxCapacity(sandboxPod.systemStatus?.storage?.volumeInGb)}</strong></div>
              <p className="v3-muted-text v3-sandbox-status-message">{sandboxPod.systemStatus?.message || "RunPod 런타임 상태 정보가 아직 준비되지 않았습니다."}</p>
            </div>
          )}
        </div>
      ) : null}

      {sandboxPodPendingAction ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="v3SandboxConfirmTitle">
          <div className="v3-modal-panel">
            <div className="v3-label" style={{ color: sandboxPodPendingAction === "stop" ? "var(--v3-danger)" : undefined }}>SANDBOX:{sandboxPodPendingAction.toUpperCase()}</div>
            <h2 id="v3SandboxConfirmTitle" className="v3-modal-title">{sandboxPodPendingAction === "stop" ? "Sandbox Pod 중지" : "Sandbox Pod 배포"}</h2>
            <p className="v3-modal-body-text">
              {sandboxPodPendingAction === "stop"
                ? "Sandbox Pod를 중지하시겠습니까? HTTP 서비스가 즉시 사용할 수 없게 됩니다."
                : "새 Sandbox Pod를 배포하시겠습니까? GPU 할당이 시작되며 비용이 발생할 수 있습니다."}
            </p>
            <div className="v3-inline-actions">
              <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => setSandboxPodPendingAction(null)}>취소</button>
              <button
                className="v3-danger-button v3-flex-button"
                style={{ background: "var(--v3-danger)", color: "#fff", borderColor: "var(--v3-danger)" }}
                type="button"
                onClick={() => {
                  const action = sandboxPodPendingAction;
                  setSandboxPodPendingAction(null);
                  void controlSandboxPod(action);
                }}
              >
                {sandboxPodPendingAction === "stop" ? "중지" : "배포"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}

function TaskPolicySettings({ user }: { user: User }) {
  const canView = canUse(user, "roles:read");
  const canEdit = canUse(user, "roles:write");
  const [taskPolicy, setTaskPolicy] = useState<TaskExecutionPolicy | null>(null);
  const [taskPolicyDraft, setTaskPolicyDraft] = useState({ maxActiveTasksPerUser: "3", maxActiveTasksTotal: "10" });
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!canView) {
      return;
    }
    let active = true;
    setLoading(true);
    apiClient.taskExecutionPolicy()
      .then((policy) => {
        if (!active) return;
        setTaskPolicy(policy);
        setTaskPolicyDraft({
          maxActiveTasksPerUser: String(policy.maxActiveTasksPerUser),
          maxActiveTasksTotal: String(policy.maxActiveTasksTotal)
        });
      })
      .catch((error: Error) => active && setNotice(error.message))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [canView]);

  async function save() {
    setNotice("");
    try {
      const next = await apiClient.saveTaskExecutionPolicy({
        maxActiveTasksPerUser: Number(taskPolicyDraft.maxActiveTasksPerUser),
        maxActiveTasksTotal: Number(taskPolicyDraft.maxActiveTasksTotal)
      });
      setTaskPolicy(next);
      setTaskPolicyDraft({
        maxActiveTasksPerUser: String(next.maxActiveTasksPerUser),
        maxActiveTasksTotal: String(next.maxActiveTasksTotal)
      });
      setNotice("Task Policy를 저장했습니다. 이후 작업 제출부터 적용됩니다.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Task policy save failed");
    }
  }

  if (!canView) {
    return null;
  }

  return (
    <div className="v3-card">
      <div className="v3-card-header">
        <div className="v3-card-header-title">동시 실행 한도</div>
        <span className="v3-card-header-meta">기본값 3 / 10</span>
      </div>
      <div style={{ padding: "0 16px 16px" }}>
        <p className="v3-muted-text">Serverless 영상 생성에만 적용되는 제출 상한입니다. Sandbox Pod의 시작·중지, 이미 제출된 Task의 실행 여부와는 독립적입니다.</p>
        <div className="v3-task-policy-limit-grid">
          <label className="v3-task-policy-limit-card">사용자당 동시 활성 Task
            <input className="v3-search-input" type="number" min="1" max="100" value={taskPolicyDraft.maxActiveTasksPerUser} disabled={!canEdit || loading} onChange={(event) => setTaskPolicyDraft((current) => ({ ...current, maxActiveTasksPerUser: event.target.value }))} />
            <span>한 사용자가 동시에 제출·대기·실행할 수 있는 최대 수</span>
          </label>
          <label className="v3-task-policy-limit-card">전체 동시 활성 Task
            <input className="v3-search-input" type="number" min="1" max="100" value={taskPolicyDraft.maxActiveTasksTotal} disabled={!canEdit || loading} onChange={(event) => setTaskPolicyDraft((current) => ({ ...current, maxActiveTasksTotal: event.target.value }))} />
            <span>모든 사용자의 제출·대기·실행 Task를 합산한 최대 수</span>
          </label>
        </div>
        <p className="v3-muted-text" style={{ marginTop: 12 }}>한도 계산 대상: `QUEUED`, `IN_QUEUE`, `IN_PROGRESS`, `RUNNING` · 완료·실패·취소·시간초과 Task는 즉시 제외</p>
        {taskPolicy?.updatedAt ? <p className="v3-muted-text" style={{ marginTop: 10 }}>마지막 변경: {formatTimestamp(taskPolicy.updatedAtKst || taskPolicy.updatedAt, taskPolicy.updatedAtUtc).replace(/\n/g, " ")}{taskPolicy.updatedBy ? ` · ${taskPolicy.updatedBy}` : ""}</p> : null}
        {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      </div>
      <div className="v3-inline-actions" style={{ padding: "0 16px 16px" }}>
        <button className="v3-primary-button" type="button" disabled={!canEdit || loading} onClick={() => void save()}>Save Task Policy</button>
      </div>
    </div>
  );
}

export function TaskPolicyScreen({ user, onGoTo }: { user: User; onGoTo: (route: StudioRoute) => void }) {
  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminTaskPolicy"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · TASK POLICY"
      headerTitle="Task Policy"
      sidebarFooter={<p className="v3-muted-text">Serverless 작업 제출량을 제어하는 운영 정책입니다. Sandbox Pod의 시작·중지 상태와는 독립적으로 적용됩니다.</p>}
    >
      <TaskPolicySettings user={user} />
    </AppShell>
  );
}

// E-04 · 3b/7b — 구버전 AdminConsoleModal의 Permissions 탭 하나가 역할×권한
// 매트릭스(3b)와 기능 리소스 매핑 표(7b)를 함께 그리고 있었다. design_handoff는
// 이 둘을 별도 화면 id로 나누므로(3b/7b) 화면도 둘로 쪼갰다 - 둘 다 같은
// PermissionGovernance 데이터(GET /api/admin/permissions)를 각자 독립적으로
// 불러온다(작은 데이터라 화면당 한 번씩 다시 부르는 비용이 적고, 두 화면이 서로
// 상태를 공유할 이유도 없다).
export function useAdminPermissionGovernance() {
  const [governance, setGovernance] = useState<PermissionGovernance | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");

  async function load() {
    setLoading(true);
    setNotice("");
    try {
      setGovernance(await apiClient.adminPermissions());
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "권한 정보를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return { governance, setGovernance, loading, notice, setNotice, reload: load };
}

export function Create3bScreen({ user, onGoTo }: { user: User; onGoTo: (route: StudioRoute) => void }) {
  const { governance, setGovernance, loading, notice, setNotice } = useAdminPermissionGovernance();
  const [selectedRoleCode, setSelectedRoleCode] = useState("");
  const [rolePermissionDraft, setRolePermissionDraft] = useState<string[]>([]);
  const roles = adminRoleOptions(governance);
  const selectedRole = roles.find((item) => item.code === selectedRoleCode) || roles[0] || null;
  const canEdit = canUse(user, "roles:write");

  useEffect(() => {
    if (!roles.length) {
      return;
    }
    const nextRole = roles.find((item) => item.code === selectedRoleCode) || roles[0];
    if (nextRole.code !== selectedRoleCode) {
      setSelectedRoleCode(nextRole.code);
    }
    setRolePermissionDraft([...(nextRole.permissionCodes || [])]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [governance]);

  function toggleRolePermission(permission: string) {
    if (selectedRole?.code === "SUPER_ADMIN" && permission === "admin:*") {
      return;
    }
    setRolePermissionDraft((current) => current.includes(permission)
      ? current.filter((item) => item !== permission)
      : [...current, permission]);
  }

  async function saveRolePermissions() {
    if (!selectedRole) {
      return;
    }
    setNotice("");
    try {
      const response = await apiClient.saveAdminRolePermissions(selectedRole.code, rolePermissionDraft);
      setGovernance(response);
      setNotice(`${selectedRole.code} 권한 구성을 저장했습니다.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Role permission save failed");
    }
  }

  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminRoles"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 역할 & 권한"
      headerTitle="역할×권한 매트릭스"
      headerActions={
        <button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.resourceMap")}>기능 리소스 매핑 보기</button>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>ROLES · {roles.length}</div>
          {roles.map((role) => (
            <button
              key={role.code}
              type="button"
              className={`v3-segment-nav-item ${selectedRole?.code === role.code ? "is-active" : ""}`}
              onClick={() => {
                setSelectedRoleCode(role.code);
                setRolePermissionDraft([...(role.permissionCodes || [])]);
              }}
            >
              <div className="v3-segment-nav-head"><span>{role.code}</span><span className={`v3-status-badge ${role.isActive ? "is-ready" : "is-pending"}`}>{role.isActive ? "ACTIVE" : "INACTIVE"}</span></div>
            </button>
          ))}
        </div>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      {loading && !governance ? (
        <p className="v3-muted-text">역할·권한 정보를 불러오는 중입니다.</p>
      ) : selectedRole ? (
        <>
          <div className="v3-card">
            <div className="v3-card-header">
              <div className="v3-card-header-title">{selectedRole.code}</div>
              <span className="v3-card-header-meta">{rolePermissionDraft.length} permission(s) · {canEdit ? "Editable" : "Read only"}</span>
            </div>
            <div style={{ padding: "0 16px 16px" }}>
              <p className="v3-muted-text">{selectedRole.description || selectedRole.name}</p>
              <div className="v3-term-chip-row">
                {/* 2026-08-11 버그 수정: rolePermissionDraft가 정확히 "admin:*" 하나만
                    담고 있는 경우(SUPER_ADMIN), 그 아래 개별 권한(sandbox:read 등)은
                    배열에 실제로 없어 전부 "미체크"로 보였다 - 관리자가 슈퍼 어드민으로
                    승격해도 권한이 반영 안 된 것처럼 오판하게 만든 원인. admin:*
                    와일드카드가 있으면 나머지 항목도 포함된 것으로 표시·잠금한다. */}
                {(() => {
                  const hasWildcard = rolePermissionDraft.includes("admin:*");
                  return adminPermissionOptions(governance).map((item) => {
                    const selected = hasWildcard || rolePermissionDraft.includes(item.value);
                    const locked = (selectedRole.code === "SUPER_ADMIN" && item.value === "admin:*")
                      || (hasWildcard && item.value !== "admin:*");
                    const title = hasWildcard && item.value !== "admin:*"
                      ? `${item.description || item.value} · admin:* 와일드카드에 포함됨`
                      : item.description;
                    return (
                      <button
                        key={item.value}
                        type="button"
                        className={`v3-term-chip ${selected ? "is-selected" : ""}`}
                        disabled={!canEdit || locked}
                        onClick={() => toggleRolePermission(item.value)}
                        title={title}
                      >
                        {item.value}
                      </button>
                    );
                  });
                })()}
              </div>
              <p className="v3-muted-text" style={{ marginTop: 10 }}>Role 권한은 해당 Role 사용자 전체에 적용됩니다. 사용자별 예외 권한은 3e/7c(사용자 상세)에서 관리합니다.</p>
            </div>
            <div className="v3-inline-actions" style={{ padding: "0 16px 16px" }}>
              <button className="v3-primary-button" type="button" disabled={loading || !canEdit} onClick={() => void saveRolePermissions()}>Save Role Permissions</button>
            </div>
          </div>
        </>
      ) : <p className="v3-muted-text">등록된 Role이 없습니다. 권한 정보를 불러오지 못했다면 상단 새로고침 후 다시 시도하세요.</p>}
      <AuditLogTable targetType="role" pageSize={5} title="변경 기록" />
    </AppShell>
  );
}

export function Create7bScreen({ user, onGoTo }: { user: User; onGoTo: (route: StudioRoute) => void }) {
  const { governance, loading, notice } = useAdminPermissionGovernance();
  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminRoles"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 역할 & 권한"
      headerTitle="기능 리소스 매핑"
      headerActions={
        <button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.roles")}>역할×권한 매트릭스로</button>
      }
      sidebarFooter={<p className="v3-muted-text">D-01: 미연결 API(reports/configs)는 여기 표시되지 않습니다 - SCREEN 행을 만들지 않기로 결정됨.</p>}
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      {loading && !governance ? <p className="v3-muted-text">불러오는 중입니다...</p> : null}
      <div className="v3-card">
        <div className="v3-review-table-head" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
          <span>RESOURCE TYPE</span><span>RESOURCE KEY</span><span>REQUIRED PERMISSION</span>
        </div>
        {(governance?.resources || []).map((resource) => (
          <div className="v3-review-table-row" style={{ gridTemplateColumns: "1fr 1fr 1fr" }} key={resource.resourceKey}>
            <span>{resource.resourceType}</span>
            <span className="v3-review-config">{resource.resourceKey}</span>
            <span>{resource.requiredPermissionCode}</span>
          </div>
        ))}
        {!loading && !(governance?.resources || []).length ? <p className="v3-muted-text" style={{ padding: 16 }}>등록된 리소스 매핑이 없습니다.</p> : null}
      </div>
    </AppShell>
  );
}

// E-04 · 3e "사용자 목록" — 구버전 AdminConsoleModal Users 탭의 왼쪽 사용자
// 목록을 독립 화면으로 뺐다. 상세/등록 폼은 7c로 분리했고, 상태(users 목록·선택된
// 사용자·폼 값)는 4a/4d와 같은 이유로 StudioShell에 있다 - 3e↔7c를 오갈 때 목록을
// 다시 불러오지 않기 위해서다.
export function Create3eScreen({
  user,
  onGoTo,
  items,
  loading,
  notice,
  onSelectUser,
  onNewUser
}: {
  user: User;
  onGoTo: (route: StudioRoute) => void;
  items: AdminUser[];
  loading: boolean;
  notice: string;
  onSelectUser: (userId: string) => void;
  onNewUser: () => void;
}) {
  const canWrite = canUse(user, "users:write");
  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminUsers"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 사용자"
      headerTitle={`사용자 ${items.length}명`}
      headerActions={canWrite ? <button className="v3-primary-button" type="button" onClick={onNewUser}>New User</button> : undefined}
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-card">
        <div className="v3-review-table-head" style={{ gridTemplateColumns: "1.2fr 1fr 1fr 1fr" }}>
          <span>NAME</span><span>ID</span><span>ROLE</span><span>STATE</span>
        </div>
        {items.map((item) => (
          <button
            className="v3-review-table-row"
            style={{ gridTemplateColumns: "1.2fr 1fr 1fr 1fr", width: "100%", textAlign: "left", background: "none", border: "none", borderTop: "1px solid var(--v3-border)", cursor: "pointer" }}
            type="button"
            key={item.id}
            onClick={() => onSelectUser(item.id)}
          >
            <span>{item.name || item.id}</span>
            <span className="v3-review-config">{item.id}</span>
            <span>{item.role}</span>
            <span className={`v3-status-badge ${item.isActive === false ? "is-pending" : "is-ready"}`}>{item.isActive === false ? "INACTIVE" : "ACTIVE"}</span>
          </button>
        ))}
        {!loading && !items.length ? <p className="v3-muted-text" style={{ padding: 16 }}>등록된 사용자가 없습니다.</p> : null}
        {loading && !items.length ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
      </div>
    </AppShell>
  );
}

// E-04 · 7c "사용자 상세/등록" — 구버전 AdminConsoleModal Users 탭의 상세 폼
// (ID/Name/Password/Role/State, Role Guide, Role Default Permissions, Extra
// Permissions, Effective Permissions) 로직을 그대로 옮겼다. 두 가지를 새로
// 추가했다 - client.ts에 이미 정의돼 있었지만 어디서도 호출되지 않던
// resetAdminUserPassword/deactivateAdminUser를 각각 별도 액션(비밀번호 재설정
// 입력창, 비활성화 버튼)으로 처음 연결했다. 기존 Save User는 이름/역할/State/
// 예외 권한만 저장하고(신규 생성 시엔 초기 비밀번호도 함께 저장), 기존 사용자의
// 비밀번호 변경은 이제 전용 엔드포인트로만 이뤄진다 - 두 경로가 같은 값을 다르게
// 덮어쓰는 경합을 없애기 위해서다.
export function Create7cScreen({
  user,
  onGoTo,
  selectedUser,
  form,
  governance,
  loading,
  notice,
  actionError,
  passwordResetValue,
  onFieldChange,
  onRoleChange,
  onTogglePermission,
  onSave,
  onPasswordResetValueChange,
  onResetPassword,
  onDeactivate,
  onNewUser
}: {
  user: User;
  onGoTo: (route: StudioRoute) => void;
  selectedUser: AdminUser | null;
  form: Record<string, string>;
  governance: PermissionGovernance | null;
  loading: boolean;
  notice: string;
  // #4 오류 위치 규칙: 저장·비번 재설정·비활성화 동작 실패는 상단 notice가 아니라
  // 동작 버튼 근처(Save User 위)에 표시. 성공 안내만 상단 notice로 남긴다.
  actionError: string;
  passwordResetValue: string;
  onFieldChange: (field: "id" | "name" | "password" | "isActive", value: string) => void;
  onRoleChange: (role: string) => void;
  onTogglePermission: (permission: string) => void;
  onSave: () => void;
  onPasswordResetValueChange: (value: string) => void;
  onResetPassword: () => void;
  onDeactivate: () => void;
  onNewUser: () => void;
}) {
  const canWrite = canUse(user, "users:write");
  const isDefaultAdmin = selectedUser?.id === "dobedub";
  const rolePermissions = adminRolePermissionCodes(governance, form.role);
  const extraPermissions = adminPermissionsFromText(form.permissions);
  const effectivePermissions = Array.from(new Set([...rolePermissions, ...extraPermissions]));
  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminUsers"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 사용자"
      headerTitle={selectedUser ? "사용자 상세" : "사용자 등록"}
      headerActions={
        <>
          <button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.users")}>목록으로</button>
          {canWrite ? <button className="v3-secondary-button" type="button" onClick={onNewUser}>New User</button> : null}
        </>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">{selectedUser ? selectedUser.name || selectedUser.id : "신규 사용자"}</div>
          <span className={`v3-status-badge ${selectedUser?.isActive === false ? "is-pending" : "is-ready"}`}>{selectedUser?.isActive === false ? "INACTIVE" : selectedUser ? "ACTIVE" : "NEW"}</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 16 }}>
          <div className="v3-reuse-grid">
            <label className="v3-checklist-item" style={{ display: "block" }}>ID
              <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={form.id} disabled={Boolean(selectedUser)} onChange={(event) => onFieldChange("id", event.target.value)} />
            </label>
            <label className="v3-checklist-item" style={{ display: "block" }}>Name
              <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={form.name} onChange={(event) => onFieldChange("name", event.target.value)} />
            </label>
            {!selectedUser ? (
              <label className="v3-checklist-item" style={{ display: "block" }}>초기 비밀번호
                <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} type="password" value={form.password} onChange={(event) => onFieldChange("password", event.target.value)} />
              </label>
            ) : null}
            <label className="v3-checklist-item" style={{ display: "block" }}>Role
              <select className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={form.role} onChange={(event) => onRoleChange(event.target.value)}>
                {adminRoleOptions(governance).map((role) => <option value={role.code} key={role.code}>{role.code}</option>)}
              </select>
            </label>
            <label className="v3-checklist-item" style={{ display: "block" }}>State
              <select className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={isDefaultAdmin ? "true" : form.isActive} disabled={isDefaultAdmin} onChange={(event) => onFieldChange("isActive", event.target.value)}>
                <option value="true">ACTIVE</option>
                <option value="false">INACTIVE</option>
              </select>
            </label>
          </div>
          {isDefaultAdmin ? <p className="v3-muted-text">기본 SUPER_ADMIN 계정은 시스템 잠금 방지를 위해 비활성화할 수 없습니다.</p> : null}
          {actionError ? <p className="v3-inline-error" role="alert">{actionError}</p> : null}
          <div className="v3-inline-actions">
            <button className="v3-primary-button" type="button" disabled={loading || !canWrite || !form.id || !form.name} onClick={onSave}>Save User</button>
          </div>
        </div>
      </div>

      <div className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Role Default Permissions</div><span className="v3-card-header-meta">{rolePermissions.length}</span></div>
        <div className="v3-term-chip-row" style={{ padding: 16 }}>
          {rolePermissions.map((permission) => (
            <span className="v3-term-chip is-selected" key={permission} title={adminPermissionLabel(governance, permission)}>{permission}</span>
          ))}
          {!rolePermissions.length ? <p className="v3-muted-text">선택한 role의 기본 권한이 없습니다.</p> : null}
        </div>
      </div>

      <div className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Extra Permissions</div><span className="v3-card-header-meta">{extraPermissions.length} selected</span></div>
        <div className="v3-term-chip-row" style={{ padding: 16 }}>
          {adminPermissionOptions(governance).map((item) => {
            const isRolePermission = rolePermissions.includes(item.value);
            const selected = extraPermissions.includes(item.value);
            return (
              <button
                key={item.value}
                type="button"
                className={`v3-term-chip ${selected ? "is-selected" : ""}`}
                disabled={!canWrite || isRolePermission}
                onClick={() => onTogglePermission(item.value)}
                title={isRolePermission ? "Role 기본 권한" : `${item.label} · ${item.description}`}
              >
                {item.value}
              </button>
            );
          })}
        </div>
        <p className="v3-muted-text" style={{ padding: "0 16px 16px" }}>Role 기본 권한은 여기서 중복 선택하지 않습니다. 사용자 예외 권한만 추가로 선택합니다.</p>
      </div>

      <div className="v3-card">
        <div className="v3-card-header"><div className="v3-card-header-title">Effective Permissions</div><span className="v3-card-header-meta">{effectivePermissions.length}</span></div>
        <div className="v3-term-chip-row" style={{ padding: 16 }}>
          {effectivePermissions.map((permission) => (
            <span className="v3-term-chip is-selected" key={permission}>{permission}</span>
          ))}
        </div>
      </div>

      {selectedUser ? (
        <div className="v3-card">
          <div className="v3-card-header"><div className="v3-card-header-title">비밀번호 재설정</div></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16 }}>
            <label className="v3-checklist-item" style={{ display: "block" }}>새 비밀번호
              <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} type="password" value={passwordResetValue} onChange={(event) => onPasswordResetValueChange(event.target.value)} />
            </label>
            <div className="v3-inline-actions">
              <button className="v3-secondary-button" type="button" disabled={loading || !canWrite || !passwordResetValue} onClick={onResetPassword}>비밀번호 재설정</button>
            </div>
          </div>
        </div>
      ) : null}

      {selectedUser && !isDefaultAdmin && selectedUser.isActive !== false ? (
        <div className="v3-card">
          <div className="v3-card-header"><div className="v3-card-header-title" style={{ color: "var(--v3-danger)" }}>사용자 비활성화</div></div>
          <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            <p className="v3-muted-text">비활성화된 사용자는 로그인할 수 없습니다. 다시 활성화하려면 State를 ACTIVE로 바꾸고 Save User를 누르세요.</p>
            <div className="v3-inline-actions">
              <button className="v3-secondary-button" type="button" disabled={loading || !canWrite} onClick={onDeactivate}>사용자 비활성화</button>
            </div>
          </div>
        </div>
      ) : null}

      {/* 2026-08-12: 사용자 요청으로 감사 로그가 "어드민 정보 수정사항"만 남기도록
          범위를 좁히면서 action="login" 기록 자체가 중단됐다(auth.py). 여기 있던
          "접근 이력"(AuditLogTable actorId=selectedUser.id action="login")은 더
          이상 채워질 데이터가 없어 항상 빈 상태로만 보이게 되므로 섹션째 제거했다. */}
    </AppShell>
  );
}

// E-04 · 4a "워크플로 정의" 목록/조회/활성화 — 구버전 AdminConsoleModal Workflows
// 탭의 목록·상세·활성화 로직을 그대로 옮겼다(등록 폼은 4d로 분리). 상태는
// StudioShell에 있다(adminWorkflowItems 등) - 4a↔4d를 오갈 때 같은 목록을
// 다시 불러오지 않고 유지하기 위해서다.
//
// 설계 원본과 다르게 뺀 것 — "백업 이력"(4a 사이드바의 워크플로별 변경/백업 기록)은
// A-04(감사 로그) 미착수라 대응 데이터가 없다. `registeredAt`/`updatedAt` 단일
// 시각만 있고 이력 목록이 아니므로, 상세 카드에 그 두 필드만 보여주고 "이력" 자체는
// 그리지 않는다.
export function Create4aScreen({
  user,
  onGoTo,
  items,
  selectedWorkflowId,
  loading,
  notice,
  onSelect,
  onNewWorkflow,
  onActivate,
  onDeactivate
}: {
  user: User;
  onGoTo: (route: StudioRoute) => void;
  items: AdminWorkflow[];
  selectedWorkflowId: string;
  loading: boolean;
  notice: string;
  onSelect: (workflowId: string) => void;
  onNewWorkflow: () => void;
  onActivate: (workflowId: string) => void;
  onDeactivate: (workflowId: string) => void;
}) {
  const selected = items.find((item) => item.id === selectedWorkflowId) || null;
  const canWrite = canUse(user, "workflows:write");
  const canActivate = canUse(user, "workflows:activate");
  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminWorkflows"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 워크플로 정의"
      headerTitle={`워크플로 ${items.length}개`}
      headerActions={canWrite ? <button className="v3-primary-button" type="button" onClick={onNewWorkflow}>New Workflow</button> : undefined}
      sidebarExtra={
        <div className="v3-step-tracker">
          {/* 2026-08-12: 사용자 요청 - sidebarExtra 표준화, 라벨 없던 화면에 추가 */}
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>WORKFLOWS · {items.length}</div>
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`v3-segment-nav-item ${selectedWorkflowId === item.id ? "is-active" : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <div className="v3-segment-nav-head"><span>{item.label || item.name || item.id}</span><span className={`v3-status-badge ${item.active ? "is-ready" : "is-pending"}`}>{item.active ? "ACTIVE" : "INACTIVE"}</span></div>
            </button>
          ))}
        </div>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      {selected ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">워크플로 상세</div>
            <span className={`v3-status-badge ${selected.active ? "is-ready" : "is-pending"}`}>{selected.active ? "ACTIVE" : "INACTIVE"}</span>
          </div>
          <div className="v3-summary-card" style={{ padding: 16 }}>
            <div className="v3-summary-row"><span>Workflow ID</span><strong>{selected.id}</strong></div>
            <div className="v3-summary-row"><span>Name</span><strong>{selected.label || selected.name || "-"}</strong></div>
            <div className="v3-summary-row"><span>Mode</span><strong>{selected.mode || "-"}</strong></div>
            <div className="v3-summary-row"><span>Input Images</span><strong>{selected.keyframeCount || 0}</strong></div>
            <div className="v3-summary-row"><span>Subgraphs</span><strong>{selected.segmentCount || 0}</strong></div>
            <div className="v3-summary-row"><span>Workflow File</span><strong>{selected.fileExists ? "EXISTS" : "MISSING"}</strong></div>
            <div className="v3-summary-row"><span>Param Config</span><strong>{selected.paramConfigExists ? "EXISTS" : "MISSING"}</strong></div>
            <div className="v3-summary-row"><span>Param Config Source</span><strong>{selected.paramConfigGenerated ? "AUTO-GENERATED" : selected.paramConfigExists ? "UPLOADED / EXISTING" : "-"}</strong></div>
            <div className="v3-summary-row"><span>Metadata</span><strong>{selected.metadataExists ? `READY · ${selected.metadataNodeCount ?? "-"} nodes · ${selected.metadataSubgraphCount ?? "-"} subgraphs` : "MISSING"}</strong></div>
            <div className="v3-summary-row"><span>Description</span><strong>{selected.description || "-"}</strong></div>
            <div className="v3-summary-row"><span>Registered At</span><strong>{formatTimestamp(selected.registeredAtKst || selected.registeredAt, selected.registeredAtUtc).replace(/\n/g, " ")}</strong></div>
            <div className="v3-summary-row"><span>Updated At</span><strong>{formatTimestamp(selected.updatedAtKst || selected.updatedAt, selected.updatedAtUtc).replace(/\n/g, " ")}</strong></div>
          </div>
          <div className="v3-inline-actions" style={{ padding: "0 16px 16px" }}>
            {canActivate ? <button className="v3-primary-button" type="button" disabled={loading || selected.active} onClick={() => onActivate(selected.id)}>Activate</button> : null}
            {canActivate ? <button className="v3-secondary-button" type="button" disabled={loading || !selected.active} onClick={() => onDeactivate(selected.id)}>Deactivate</button> : null}
            {canWrite ? <button className="v3-secondary-button" type="button" onClick={onNewWorkflow}>New Workflow</button> : null}
          </div>
        </div>
      ) : (
        <p className="v3-muted-text">{loading ? "불러오는 중입니다..." : "왼쪽에서 워크플로를 선택하거나 새로 등록하세요."}</p>
      )}
    </AppShell>
  );
}

// E-04 · 4d "워크플로 등록/갱신" — 구버전 AdminConsoleModal Workflows 탭에서
// selectedAdminWorkflow가 없을 때(New Workflow) 보여주던 폼과 동일한 로직이다.
// 저장 성공 시 4a로 돌아간다(onSave가 StudioShell에서 onNavigate("admin.workflows")까지
// 처리).
export function Create4dScreen({
  user,
  onGoTo,
  form,
  loading,
  notice,
  onFieldChange,
  onLoadFile,
  onSave
}: {
  user: User;
  onGoTo: (route: StudioRoute) => void;
  form: Record<string, string>;
  loading: boolean;
  notice: string;
  onFieldChange: (field: "workflowId" | "description", value: string) => void;
  onLoadFile: (event: React.ChangeEvent<HTMLInputElement>, target: "workflowJson" | "paramConfigJson") => void;
  onSave: () => void;
}) {
  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminWorkflows"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 워크플로 정의"
      headerTitle="워크플로 등록"
      headerActions={<button className="v3-secondary-button" type="button" onClick={() => onGoTo("admin.workflows")}>목록으로</button>}
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">Load &amp; Save</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 16 }}>
          <div className="v3-reuse-grid">
            <label className="v3-checklist-item" style={{ display: "block", cursor: "pointer" }}>
              <div>Workflow JSON 불러오기</div>
              <input type="file" accept="application/json,.json" style={{ marginTop: 6 }} onChange={(event) => onLoadFile(event, "workflowJson")} />
              <div className="v3-muted-text" style={{ marginTop: 6 }}>{form.workflowJson ? form.workflowId || "loaded workflow" : "파일 선택"}</div>
            </label>
            <label className="v3-checklist-item" style={{ display: "block", cursor: "pointer" }}>
              <div>Param Config JSON 불러오기</div>
              <input type="file" accept="application/json,.json" style={{ marginTop: 6 }} onChange={(event) => onLoadFile(event, "paramConfigJson")} />
              <div className="v3-muted-text" style={{ marginTop: 6 }}>{form.paramConfigJson ? "loaded/generated param config" : "비우면 자동 생성"}</div>
            </label>
          </div>
          <label className="v3-checklist-item" style={{ display: "block" }}>
            Workflow ID
            <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={form.workflowId} placeholder="new-workflow.json" onChange={(event) => onFieldChange("workflowId", event.target.value)} />
          </label>
          <label className="v3-checklist-item" style={{ display: "block" }}>
            Description
            <input className="v3-search-input" style={{ width: "100%", marginTop: 6 }} value={form.description} onChange={(event) => onFieldChange("description", event.target.value)} />
          </label>
          <div className="v3-summary-card">
            <div className="v3-summary-row"><span>Workflow JSON</span><strong>{form.workflowJson ? "LOADED" : "NOT LOADED"}</strong></div>
            <div className="v3-summary-row"><span>Param Config JSON</span><strong>{form.paramConfigJson ? "LOADED" : "AUTO-GENERATE ON SAVE"}</strong></div>
            <div className="v3-summary-row"><span>Segment Defaults</span><strong>저장 시 자동 생성/갱신</strong></div>
            <div className="v3-summary-row"><span>Metadata</span><strong>저장 시 자동 갱신</strong></div>
          </div>
          <details className="v3-checklist-item">
            <summary style={{ cursor: "pointer" }}>Loaded JSON Preview</summary>
            <pre className="v3-payload-json">{form.workflowJson || "Workflow JSON 파일을 불러오세요."}</pre>
          </details>
          <div className="v3-inline-actions">
            <button className="v3-primary-button" type="button" disabled={loading || !canUse(user, "workflows:write") || !form.workflowId || !form.workflowJson} onClick={onSave}>Save Workflow</button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

// A-04 · 감사 로그 — design_handoff에는 없던 신규 화면. `GET /api/admin/audit-logs`를
// 필터 없이 조회하는 전체 목록 뷰다. action/targetType은 자유 텍스트 입력이고(백엔드가
// 값 목록을 내려주지 않아 하드코딩된 드롭다운을 만들지 않는다 - TASKS.md 참고),
// 4c(프롬프트 재사용)의 검색창처럼 입력 즉시가 아니라 Search 클릭/Enter 시점에만
// 적용해 타이핑마다 재조회하지 않는다. 목록·페이지네이션 자체는 AuditLogTable이
// 담당한다(page/pageSize/필터 변경 시 재조회하는 로직은 그 컴포넌트 안에 있음).
export function AdminAuditLogScreen({ user, onGoTo }: { user: User; onGoTo: (route: StudioRoute) => void }) {
  const [actionDraft, setActionDraft] = useState("");
  const [targetTypeDraft, setTargetTypeDraft] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [targetTypeFilter, setTargetTypeFilter] = useState("");

  function applyFilters() {
    setActionFilter(actionDraft.trim());
    setTargetTypeFilter(targetTypeDraft.trim());
  }

  return (
    <AppShell
      user={user}
      area="admin"
      activeItem="adminAuditLog"
      onNavigate={(key) => shellNavigateAdmin(key, onGoTo)}
      headerEyebrow="ADMIN · 감사 로그"
      headerTitle="감사 로그"
      headerActions={
        <>
          <input
            className="v3-search-input"
            value={actionDraft}
            onChange={(event) => setActionDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") applyFilters();
            }}
            placeholder="action (예: role.permissions.update)"
          />
          <input
            className="v3-search-input"
            value={targetTypeDraft}
            onChange={(event) => setTargetTypeDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") applyFilters();
            }}
            placeholder="targetType (예: role)"
          />
          <button className="v3-primary-button" type="button" onClick={applyFilters}>Search</button>
        </>
      }
    >
      <AuditLogTable action={actionFilter || undefined} targetType={targetTypeFilter || undefined} pageSize={20} title="감사 로그" />
    </AppShell>
  );
}
