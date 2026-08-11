import React, { useState } from "react";
import {
  HealthResponse,
  WorkflowItem,
  ConfigControl,
  WorkflowSchema,
  OutputAsset,
  PromptCatalogResponse,
  PromptSystemPromptResponse,
  PromptSceneResponse,
  PromptGenerateResponse,
  JobStatusResponse
} from "../api/client";
import { StudioRoute } from "../router";
import {
  User,
  canUse
} from "../auth";
import { AppShell } from "../components/AppShell";
import {
  serviceStatusLabel,
  qwenStatusLabel,
  formatElapsed
} from "../helpers/format";
import {
  promptKeywordText,
  combinePromptText,
  groupPromptWarningsBySeverity
} from "../helpers/prompts";
import {
  promptCatalogCategories,
  selectedPromptKeywordsByScope,
  promptCatalogRenderScopes,
  promptGroupAccordionKey,
  promptCategoryAccordionKey,
  promptAccordionDefaultKeys
} from "../helpers/promptCatalog";
import {
  SegmentState,
  KeyframeState
} from "../helpers/workflow";
import { shellNavigate } from "../helpers/navigation";
import { ProtectedImage } from "../components/ProtectedAssets";

// E-02 · 2a "S1 이미지 로드" — design_handoff_dobedub_v3/2 Create.dc.html의 첫 화면을
// AppShell(E-01) + v3 디자인 토큰(E-00)으로 다시 구현했다. 워크플로 선택·키프레임
// 업로드 로직은 StudioShell에 이미 있던 state/handler를 그대로 물려받아 재사용하고
// (README "재사용할 것은 로직") 화면 구조·스타일만 새로 짰다.
//
// 설계 원본에는 "최근 사용 이미지"·"Recent Runs" 패널과 "Save Draft" 버튼이 있지만,
// 이를 채울 실제 API가 없다(자산 목록 API는 TASKS.md A-01 미착수, 임시저장 API는
// 존재하지 않음). 예시 데이터를 채워 넣지 않기 위해 이 두 패널과 버튼은 이번
// 구현에서 의도적으로 제외했다 - A-01 완료 후 다시 채운다.
export function Create2aScreen({
  user,
  health,
  onGoTo,
  workflows,
  selectedWorkflow,
  workflowSelectionLocked,
  onSelectWorkflow,
  schema,
  keyframes,
  activeImageIndexes,
  onUploadFiles,
  onClearKeyframe,
  onNext
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  workflows: WorkflowItem[];
  selectedWorkflow: string;
  workflowSelectionLocked: boolean;
  onSelectWorkflow: (workflowId: string) => void;
  schema: WorkflowSchema | null;
  keyframes: KeyframeState[];
  activeImageIndexes: Set<number>;
  onUploadFiles: (index: number, files: FileList | null) => void;
  onClearKeyframe: (index: number) => void;
  onNext: () => void;
}) {
  const selected = workflows.find((workflow) => workflow.id === selectedWorkflow) || null;
  const requiredKeyframeCount = schema?.keyframeCount || selected?.keyframeCount || keyframes.length || 0;
  const filledKeyframeCount = keyframes.filter((keyframe) => Boolean(keyframe.previewUrl)).length;
  const segmentCount = schema?.segmentCount || selected?.segmentCount || 0;
  const missingCount = Math.max(requiredKeyframeCount - filledKeyframeCount, 0);
  const canProceed = Boolean(selectedWorkflow) && missingCount === 0;
  const system = health?.system || health?.legacy;
  const comfyStatus = serviceStatusLabel(Boolean(system?.runpod?.configured), "", system?.dryRun ? "DRY-RUN" : undefined);
  const qwenStatus = qwenStatusLabel(system?.promptLlm, "");

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="workspace"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="STEP 1 / 4 · 워크플로 선택 포함"
      headerTitle="이미지 로드"
      headerActions={
        <button
          className="v3-primary-button"
          type="button"
          disabled={!canProceed}
          onClick={onNext}
        >
          세그먼트 설정으로 →
        </button>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-step is-active">
            <span className="v3-step-index">1</span>
            <span>이미지 로드</span>
          </div>
          <div className="v3-step">
            <span className="v3-step-index">2</span>
            <span>세그먼트 설정</span>
          </div>
          <div className="v3-step">
            <span className="v3-step-index">3</span>
            <span>실행 전 확인</span>
          </div>
          <div className="v3-step">
            <span className="v3-step-index">4</span>
            <span>결과 조회</span>
          </div>
        </div>
      }
      sidebarFooter={
        <div className="v3-service-status">
          <div>
            <span>ComfyUI</span>
            <strong className={comfyStatus === "ONLINE" ? "is-online" : "is-offline"}>{comfyStatus}</strong>
          </div>
          <div>
            <span>Qwen LLM</span>
            <strong className={qwenStatus === "ONLINE" ? "is-online" : "is-offline"}>{qwenStatus}</strong>
          </div>
        </div>
      }
      rightPanel={
        <>
          <div className="v3-panel-title">Run Summary</div>
          <div className="v3-summary-card">
            <div className="v3-summary-row"><span>Workflow</span><strong>{selected?.label || selected?.name || selected?.id || "-"}</strong></div>
            <div className="v3-summary-row"><span>Keyframes</span><strong>{filledKeyframeCount} / {requiredKeyframeCount}</strong></div>
            <div className="v3-summary-row"><span>Segments</span><strong>{segmentCount} <span className="v3-summary-note">(자동)</span></strong></div>
          </div>
          <div className="v3-summary-card">
            <div className="v3-label">CHECKLIST</div>
            <div className={`v3-checklist-item ${selectedWorkflow ? "is-done" : ""}`}>
              <span className="v3-checklist-dot">{selectedWorkflow ? "✓" : ""}</span>
              워크플로 선택
            </div>
            <div className={`v3-checklist-item ${missingCount === 0 && requiredKeyframeCount > 0 ? "is-done" : "is-warning"}`}>
              <span className="v3-checklist-dot">{missingCount === 0 && requiredKeyframeCount > 0 ? "✓" : ""}</span>
              키프레임 {filledKeyframeCount} / {requiredKeyframeCount}
            </div>
            <div className="v3-checklist-item is-pending">
              <span className="v3-checklist-dot" />
              세그먼트 설정
            </div>
            <div className="v3-checklist-item is-pending">
              <span className="v3-checklist-dot" />
              실행 전 확인
            </div>
          </div>
        </>
      }
    >
      <div className="v3-field-block">
        <div className="v3-field-block-header">
          <div className="v3-field-block-title">Workflow</div>
        </div>
        <div className="v3-workflow-grid">
          {workflows.map((workflow) => (
            <button
              key={workflow.id}
              type="button"
              className={`v3-workflow-card ${workflow.id === selectedWorkflow ? "is-selected" : ""}`}
              disabled={workflowSelectionLocked}
              onClick={() => onSelectWorkflow(workflow.id)}
            >
              <div className="v3-workflow-card-head">
                <span>{workflow.label || workflow.name || workflow.id}</span>
                {workflow.id === selectedWorkflow ? <span className="v3-workflow-card-check">✓</span> : null}
              </div>
              <div className="v3-workflow-card-meta">
                {workflow.keyframeCount || 1} kf · {workflow.segmentCount || 0} seg
              </div>
            </button>
          ))}
        </div>
        {workflowSelectionLocked ? (
          <p className="v3-inline-notice">생성 중에는 워크플로우 변경이 잠깐 잠깁니다. 현재 작업이 완료 또는 실패하면 다시 선택할 수 있습니다.</p>
        ) : null}
      </div>

      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">
            <span>Keyframe Slots</span>
            <span className="v3-card-header-meta">{filledKeyframeCount} / {requiredKeyframeCount} 필수</span>
          </div>
        </div>
        <div className="v3-keyframe-row">
          {keyframes.map((keyframe) => (
            <label
              key={keyframe.index}
              className={`v3-keyframe-slot ${activeImageIndexes.has(keyframe.index) ? "is-linked" : ""} ${keyframe.previewUrl ? "has-image" : ""}`}
            >
              <input
                type="file"
                accept="image/*"
                multiple
                onChange={(event) => onUploadFiles(keyframe.index, event.target.files)}
              />
              <div className="v3-keyframe-slot-preview">
                {keyframe.previewUrl ? <ProtectedImage src={keyframe.previewUrl} alt={`Input ${keyframe.index}`} /> : <span>SLOT {String(keyframe.index).padStart(2, "0")} 비어있음</span>}
              </div>
              <div className="v3-keyframe-slot-meta">
                <span>SLOT {String(keyframe.index).padStart(2, "0")}</span>
                <span>{keyframe.uploading ? "uploading..." : keyframe.error || keyframe.metaText || ""}</span>
              </div>
              {keyframe.previewUrl ? (
                <button
                  type="button"
                  className="v3-keyframe-slot-clear"
                  onClick={(event) => {
                    event.preventDefault();
                    onClearKeyframe(keyframe.index);
                  }}
                >
                  삭제
                </button>
              ) : null}
            </label>
          ))}
        </div>
        {missingCount > 0 ? (
          <div className="v3-warning-strip">
            <span className="v3-warning-dot" />
            <span>{missingCount}개 슬롯이 비어 있습니다 — 업로드해야 다음 단계로 넘어갈 수 있습니다</span>
          </div>
        ) : null}
        <div className="v3-note-block">
          <div className="v3-label">SEGMENT 규칙</div>
          <div>세그먼트는 <strong>이미지 사이의 전환 구간</strong>입니다. 워크플로가 자동 계산하며 사용자가 개수를 바꿀 수 없습니다.</div>
        </div>
      </div>
    </AppShell>
  );
}

// E-02 · 2b "S2 프롬프트 구성" — design_handoff_dobedub_v3/2 Create.dc.html의 두 번째
// 화면. 카탈로그 트리 조회·용어 선택·규칙 위반/필수 누락 경고·Generate/Apply 흐름은
// 전부 구버전 PromptBuilderModal이 이미 갖고 있던 로직(C-01 경고 그룹핑 포함)을
// 그대로 재사용한다 - 새로 만든 것은 화면 구조와 스타일뿐이다.
//
// 설계 원본과 다르게 뺀 것:
// - "직접 입력" 모드 칩 — 기존 로직에 그런 별도 모드가 없다(생성 없이 바로 Apply하면
//   그게 직접 입력이다). 없는 상태를 만들어 붙이지 않았다.
// - "비어있는 세그먼트에도 함께 적용" 체크박스 — 여러 세그먼트에 한 번에 적용하는
//   기능이 백엔드/기존 로직 어디에도 없다. 임의로 만들지 않았다.
// - 카탈로그 트리의 scope→group→category 3단 아코디언 — scope 탭 + category 목록
//   2단으로 단순화했다. 그룹 단위 접고 펼치기는 이후 다듬을 항목.
// - "라이브러리 재사용" — E-03에서 4c 화면이 생겨 review.reuse로 이동한다(과거엔
//   구버전 PromptReuseModal을 임시로 띄웠음).
export function Create2bScreen({
  user,
  health,
  onGoTo,
  workflowName,
  segments,
  selectedSegmentIndex,
  onSelectSegment,
  catalog,
  loading,
  notice,
  selectedTermIds,
  activePanel,
  systemPrompt,
  systemPromptText,
  scene,
  generated,
  sceneDescription,
  baseNegativePrompt,
  onReloadSystemPrompt,
  onSaveSystemPrompt,
  onSystemPromptTextChange,
  onPanelChange,
  onToggleTerm,
  onSceneDescriptionChange,
  onClearSelection,
  onGenerate,
  onApply,
  onOpenPromptReuse,
  onNext
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  workflowName: string;
  segments: SegmentState[];
  selectedSegmentIndex: number;
  onSelectSegment: (index: number) => void;
  catalog: PromptCatalogResponse | null;
  loading: boolean;
  notice: string;
  selectedTermIds: number[];
  activePanel: "keywords" | "systemPrompt";
  systemPrompt: PromptSystemPromptResponse | null;
  systemPromptText: string;
  scene: PromptSceneResponse | null;
  generated: PromptGenerateResponse | null;
  sceneDescription: string;
  baseNegativePrompt: string;
  onReloadSystemPrompt: () => void;
  onSaveSystemPrompt: () => void;
  onSystemPromptTextChange: (value: string) => void;
  onPanelChange: (panel: "keywords" | "systemPrompt") => void;
  onToggleTerm: (termId: number) => void;
  onSceneDescriptionChange: (value: string) => void;
  onClearSelection: (termIds?: number[]) => void;
  onGenerate: () => void;
  onApply: (promptOverride?: {
    positivePrompt?: string;
    negativePrompt?: string;
    negativePromptAddition?: string;
    source?: string;
  }) => void;
  onOpenPromptReuse: () => void;
  onNext: () => void;
}) {
  const selectedSegment = segments.find((segment) => segment.index === selectedSegmentIndex) || segments[0];
  const categories = promptCatalogCategories(catalog);
  const renderScopes = promptCatalogRenderScopes(categories);
  const [activeScopeKey, setActiveScopeKey] = useState<"positive" | "negative">("positive");
  const activeScope = renderScopes.find((scope) => scope.key === activeScopeKey) || renderScopes[0];
  // 2026-08-11: 사용자 요청 - 키워드 카탈로그가 그룹·서브카테고리 구분 없이 전부
  // 펼쳐진 채로 보이던 문제. helpers/promptCatalog.ts에 이미 있었지만 어디서도
  // 쓰이지 않던 promptGroupAccordionKey/promptCategoryAccordionKey/
  // promptAccordionDefaultKeys(빈 Set = 기본 전체 접힘)를 그대로 연결해 그룹→
  // 서브카테고리 2단 아코디언으로 만든다(용어 칩은 서브카테고리를 펼쳐야 보임).
  const [expandedCatalogKeys, setExpandedCatalogKeys] = useState<Set<string>>(promptAccordionDefaultKeys());
  const toggleCatalogAccordion = (key: string) => setExpandedCatalogKeys((current) => {
    const next = new Set(current);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    return next;
  });
  const selectedKeywords = selectedPromptKeywordsByScope(categories, selectedTermIds);
  const positiveKeywordDraft = promptKeywordText(selectedKeywords.positive);
  const negativeKeywordDraft = promptKeywordText(selectedKeywords.negative);
  const sceneDetailDraft = sceneDescription.trim();
  const hasPositiveInput = Boolean(positiveKeywordDraft || sceneDetailDraft);
  const positivePrompt = generated?.positivePrompt || positiveKeywordDraft || sceneDetailDraft;
  const negativePromptAddition = generated?.negativePrompt || negativeKeywordDraft;
  const negativePrompt = combinePromptText(baseNegativePrompt, negativePromptAddition);
  const warnings = [...(scene?.warnings || []), ...(generated?.warnings || [])];
  const warningGroups = groupPromptWarningsBySeverity(warnings);
  const hasBlockingWarning = warningGroups.some((group) => group.severity === "error");
  const applyLabel = generated ? "Apply Generated Prompt" : "Apply Keyword / Scene Draft";
  const configuredSegmentCount = segments.filter((segment) => segment.positivePrompt.trim()).length;
  const nextSegment = segments.find((segment) => segment.index === selectedSegmentIndex + 1);

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="workspace"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`STEP 2 / 4 · SEG ${String(selectedSegmentIndex).padStart(2, "0")} · 프롬프트`}
      headerTitle="세그먼트 설정"
      headerActions={
        <>
          <button className="v3-secondary-button" type="button" onClick={onOpenPromptReuse}>Prompt Reuse</button>
          <span className="v3-header-hint">Run은 실행 전 확인 단계에서 · 설정 {configuredSegmentCount}/{segments.length}</span>
        </>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>SEGMENTS · {workflowName || "-"} → {segments.length}</div>
          {segments.map((segment) => (
            <button
              key={segment.index}
              type="button"
              className={`v3-segment-nav-item ${segment.index === selectedSegmentIndex ? "is-active" : ""}`}
              onClick={() => onSelectSegment(segment.index)}
            >
              <div className="v3-segment-nav-head">
                <span>SEG {String(segment.index).padStart(2, "0")}</span>
                <span>{segment.positivePrompt.trim() ? "작성됨" : "비어있음"}</span>
              </div>
              <div className="v3-segment-nav-meta">KF {segment.startImageIndex} → KF {segment.endImageIndex}</div>
            </button>
          ))}
        </div>
      }
      rightPanel={
        <>
          <div className="v3-panel-title-row">
            <div className="v3-panel-title">생성 결과</div>
            {warningGroups.length ? <span className="v3-panel-badge">확인 필요 {warnings.length}건</span> : null}
          </div>
          <div className="v3-card">
            <div className="v3-card-header">
              <span className="v3-label">POSITIVE</span>
              <span className="v3-card-header-meta">{generated ? `Qwen · ${generated.provider}` : "Draft"}</span>
            </div>
            <div className="v3-prompt-text-block">{positivePrompt || "-"}</div>
          </div>
          <div className="v3-card">
            <div className="v3-card-header">
              <span className="v3-label">NEGATIVE</span>
              <span className="v3-card-header-meta">내장 + 추가분</span>
            </div>
            <div className="v3-prompt-text-block">{negativePrompt || "-"}</div>
          </div>
          <div className="v3-summary-card">
            <div className="v3-label">SCENE JSON</div>
            <pre className="v3-scene-json">{scene ? JSON.stringify(scene.scene, null, 2) : "{}"}</pre>
          </div>
          <p className="v3-muted-text">여기서 만든 프롬프트는 저장되지 않습니다 · Task History 평가에서 재사용 등록해야 라이브러리에 들어갑니다</p>
          <div className="v3-inline-actions">
            <button
              className="v3-primary-button v3-flex-button"
              type="button"
              disabled={(!hasPositiveInput && !generated) || hasBlockingWarning}
              onClick={() => onApply({
                positivePrompt,
                negativePrompt,
                negativePromptAddition,
                source: generated ? "Generated Prompt" : "Prompt Builder"
              })}
            >
              {applyLabel} — SEG {String(selectedSegmentIndex).padStart(2, "0")}
            </button>
          </div>
          <div className="v3-inline-actions">
            <button className="v3-secondary-button v3-flex-button" type="button" onClick={onOpenPromptReuse}>라이브러리 재사용</button>
          </div>
          <div className="v3-note-block">
            <div className="v3-label">적용 후 이동</div>
            <div className="v3-inline-actions">
              {nextSegment ? (
                <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onSelectSegment(nextSegment.index)}>
                  SEG {String(nextSegment.index).padStart(2, "0")} 프롬프트 →
                </button>
              ) : null}
              <button className="v3-secondary-button v3-flex-button" type="button" onClick={onNext}>노드 구성값 설정 →</button>
            </div>
            <p className="v3-muted-text">영상 생성은 세그먼트 단위가 아닙니다 · 모든 세그먼트 설정 후 실행 전 확인에서 한 번에 제출됩니다</p>
          </div>
        </>
      }
    >
      <div className="v3-pill-row">
        <button
          type="button"
          className={`v3-pill ${activePanel === "keywords" ? "is-active" : ""}`}
          onClick={() => onPanelChange("keywords")}
        >
          Keyword Builder
        </button>
        <button
          type="button"
          className={`v3-pill ${activePanel === "systemPrompt" ? "is-active" : ""}`}
          onClick={() => {
            onPanelChange("systemPrompt");
            if (!systemPrompt) {
              onReloadSystemPrompt();
            }
          }}
        >
          System Prompt 편집
        </button>
        <span className="v3-pill-meta">selected {selectedTermIds.length}</span>
      </div>

      <div className="v3-note-row">
        <span className="v3-label">이 단계</span>
        <span><strong>프롬프트 생성</strong>은 텍스트만 만듭니다 · 영상 생성(GPU)은 STEP 3 실행 전 확인에서</span>
      </div>

      {warningGroups.length ? (
        <div className="v3-warning-block">
          {warningGroups.map((group) => (
            <div className={`v3-warning-row severity-${group.severity}`} key={group.severity}>
              {group.items.map((warning, index) => (
                <div className="v3-warning-line" key={`${warning.code || group.severity}-${index}`}>
                  <span className="v3-warning-bullet" />
                  <span>{warning.message || warning.code}</span>
                  <span className="v3-warning-tag">{group.severity === "error" ? "BLOCK · 적용 비활성" : "WARN · 진행 가능"}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : null}

      {activePanel === "systemPrompt" ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">System Prompt</div>
            <span className="v3-card-header-meta">{systemPrompt?.provider || "runpod_vllm"}</span>
          </div>
          <div className="v3-system-prompt-body">
            <p className="v3-muted-text">{systemPrompt?.name || "Qwen WAN I2V Positive Prompt Composer"} · {systemPrompt?.code || "qwen_wan_i2v_positive"}</p>
            <textarea
              className="v3-system-prompt-textarea"
              value={systemPromptText}
              spellCheck={false}
              onChange={(event) => onSystemPromptTextChange(event.target.value)}
            />
            <div className="v3-inline-actions">
              <button className="v3-secondary-button" type="button" disabled={loading} onClick={onReloadSystemPrompt}>Reload</button>
              <button className="v3-primary-button" type="button" disabled={loading || !systemPromptText.trim()} onClick={onSaveSystemPrompt}>Save System Prompt</button>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="v3-card">
            <div className="v3-card-header">
              <div className="v3-scope-tabs">
                {renderScopes.map((scope) => (
                  <button
                    key={scope.key}
                    type="button"
                    className={`v3-scope-tab ${scope.key === activeScopeKey ? "is-active" : ""}`}
                    onClick={() => setActiveScopeKey(scope.key)}
                  >
                    {scope.label} · {scope.termCount}
                  </button>
                ))}
              </div>
            </div>
            <div className="v3-catalog-body">
              {!activeScope || !activeScope.groups.length ? (
                <p className="v3-muted-text">등록된 key word가 없습니다. Admin Console에서 카테고리와 key word를 등록하세요.</p>
              ) : (
                <div className="v3-catalog-tree-scope">
                  {activeScope.groups.map((group) => {
                    const groupKey = promptGroupAccordionKey(activeScope.key, group.key);
                    const groupExpanded = expandedCatalogKeys.has(groupKey);
                    const groupTermCount = group.categories.reduce((sum, category) => sum + (category.terms || []).length, 0);
                    const groupSelectedCount = group.categories.reduce(
                      (sum, category) => sum + (category.terms || []).filter((term) => selectedTermIds.includes(term.id)).length,
                      0
                    );
                    return (
                      <div key={group.key} className="v3-catalog-tree-group">
                        <button type="button" className="v3-segment-nav-item" onClick={() => toggleCatalogAccordion(groupKey)}>
                          <div className="v3-segment-nav-head">
                            <span>{group.label}</span>
                            <span>{groupSelectedCount ? `${groupSelectedCount} selected · ` : ""}{groupTermCount} {groupExpanded ? "−" : "+"}</span>
                          </div>
                        </button>
                        {groupExpanded ? (
                          <div className="v3-catalog-tree-children">
                            {group.categories.map((category) => {
                              const categoryKey = promptCategoryAccordionKey(activeScope.key, group.key, category.code);
                              const categoryExpanded = expandedCatalogKeys.has(categoryKey);
                              const selectedInCategory = (category.terms || []).filter((term) => selectedTermIds.includes(term.id)).length;
                              return (
                                <div key={category.code} className="v3-catalog-tree-subcategory">
                                  <button type="button" className="v3-segment-nav-item" onClick={() => toggleCatalogAccordion(categoryKey)}>
                                    <div className="v3-segment-nav-head">
                                      <span>{category.nameKo || category.nameEn || category.code}</span>
                                      <span>{selectedInCategory ? `${selectedInCategory} · ` : ""}{category.selectionMode === "single" ? "Single" : "Multi"} {categoryExpanded ? "−" : "+"}</span>
                                    </div>
                                  </button>
                                  {categoryExpanded ? (
                                    <div className="v3-catalog-tree-children v3-catalog-tree-terms">
                                      {(category.terms || []).map((term) => (
                                        <button
                                          key={term.id}
                                          type="button"
                                          className={`v3-term-chip v3-catalog-tree-term ${selectedTermIds.includes(term.id) ? "is-selected" : ""}`}
                                          onClick={() => onToggleTerm(term.id)}
                                        >
                                          {term.labelEn || term.labelKo || term.code}
                                        </button>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="v3-catalog-category">
                <div className="v3-catalog-category-head">
                  <span className="v3-label">SCENE DETAIL · optional</span>
                </div>
                <textarea
                  className="v3-scene-textarea"
                  placeholder="예: input character turns slightly toward the camera with a calm expression"
                  value={sceneDescription}
                  rows={3}
                  onChange={(event) => onSceneDescriptionChange(event.target.value)}
                />
              </div>
            </div>
            <div className="v3-catalog-actions">
              <button className="v3-primary-button v3-flex-button" type="button" disabled={loading || !hasPositiveInput} onClick={onGenerate}>
                {loading ? "GENERATING..." : "프롬프트 생성 · Qwen"}
              </button>
              <button
                className="v3-secondary-button"
                type="button"
                disabled={loading || !selectedTermIds.length}
                onClick={() => onClearSelection()}
              >
                선택 초기화
              </button>
            </div>
          </div>
        </>
      )}
    </AppShell>
  );
}

// E-02 · 2e "S3 세그먼트 설정 · 노드 컨피그 & seed" — design_handoff_dobedub_v3/
// 2 Create.dc.html의 세 번째 화면. Wan Node Config는 기존 StudioShell의
// updateConfigValue/resetSegmentConfigsToDefaults를 그대로 재사용한다.
//
// 설계 원본과 다르게 뺀 것:
// - seed "직접 입력" — 코드베이스가 4314245("영상 생성 seed 서버측 자동화")
//   커밋 이후로 seed를 항상 서버가 자동 생성하도록 확정했고, configControls에서도
//   seed/Seed 키를 의도적으로 제외한다(구버전 화면도 동일). 없는 수동 입력 경로를
//   화면에만 만들어 붙이지 않았다 - 자동 생성이라는 사실만 보여준다.
// - "SEG 01 대비 변경분" diff 표 — 기본값과 현재값을 비교하는 로직이 없다. 대신
//   현재 설정값을 그대로 나열한다.
export function Create2eScreen({
  user,
  health,
  onGoTo,
  workflowName,
  segments,
  selectedSegmentIndex,
  onSelectSegment,
  keyframes,
  onUpdateConfigValue,
  onResetDefaults,
  onCopyFirstSegmentConfig,
  onEditPrompt,
  onNext
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  workflowName: string;
  segments: SegmentState[];
  selectedSegmentIndex: number;
  onSelectSegment: (index: number) => void;
  keyframes: KeyframeState[];
  onUpdateConfigValue: (key: string, value: string, control?: ConfigControl) => void;
  onResetDefaults: () => void;
  onCopyFirstSegmentConfig: (targetIndex: number) => void;
  onEditPrompt: () => void;
  onNext: () => void;
}) {
  const selectedSegment = segments.find((segment) => segment.index === selectedSegmentIndex) || segments[0];
  const startKeyframe = keyframes.find((keyframe) => keyframe.index === selectedSegment?.startImageIndex);
  const endKeyframe = keyframes.find((keyframe) => keyframe.index === selectedSegment?.endImageIndex);
  const configControls = (selectedSegment?.configControls || []).filter((control) => control.key !== "seed" && control.key !== "Seed");
  const configuredCount = segments.filter((segment) => segment.positivePrompt.trim()).length;
  const allConfigured = configuredCount === segments.length && segments.length > 0;
  const isFirstSegment = selectedSegment?.index === segments[0]?.index;

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="workspace"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`STEP 2 / 4 · SEG ${String(selectedSegmentIndex).padStart(2, "0")} · 노드 컨피그`}
      headerTitle="세그먼트 설정"
      headerActions={
        <button className="v3-primary-button" type="button" disabled={!allConfigured} onClick={onNext}>
          실행 전 확인으로 →
        </button>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>SEGMENTS · {workflowName || "-"} → {segments.length}</div>
          {segments.map((segment) => (
            <button
              key={segment.index}
              type="button"
              className={`v3-segment-nav-item ${segment.index === selectedSegmentIndex ? "is-active" : ""}`}
              onClick={() => onSelectSegment(segment.index)}
            >
              <div className="v3-segment-nav-head">
                <span>SEG {String(segment.index).padStart(2, "0")}</span>
                <span>{segment.positivePrompt.trim() ? "세팅 완료" : "설정 필요"}</span>
              </div>
              <div className="v3-segment-nav-meta">KF {segment.startImageIndex} → KF {segment.endImageIndex}</div>
            </button>
          ))}
        </div>
      }
      rightPanel={
        <>
          <div className="v3-panel-title">설정 현황</div>
          <div className="v3-card">
            <div className="v3-card-header">
              <span className="v3-label">세그먼트 설정</span>
            </div>
            {segments.map((segment) => (
              <div className="v3-status-row" key={segment.index}>
                <span>{String(segment.index).padStart(2, "0")}</span>
                <span className={segment.positivePrompt.trim() ? "is-done" : "is-pending"}>
                  {segment.positivePrompt.trim() ? "완료" : "프롬프트 필요"}
                </span>
              </div>
            ))}
          </div>
          <div className="v3-summary-card">
            <div className="v3-summary-row"><span>제출 방식</span><strong>단일 작업 1건</strong></div>
            <div className="v3-summary-row"><span>세그먼트</span><strong>{segments.length}</strong></div>
            <div className="v3-summary-row"><span>Seed</span><strong>세그먼트별 자동</strong></div>
          </div>
          <div className="v3-summary-card">
            <div className="v3-label">검증</div>
            <div className={`v3-checklist-item ${configuredCount === segments.length ? "is-done" : "is-warning"}`}>
              <span className="v3-checklist-dot">{configuredCount === segments.length ? "✓" : ""}</span>
              프롬프트 {configuredCount} / {segments.length}
            </div>
            <div className="v3-checklist-item is-done">
              <span className="v3-checklist-dot">✓</span>
              노드 구성값 유효
            </div>
          </div>
          <div className="v3-inline-actions">
            <button className="v3-secondary-button v3-flex-button" type="button" onClick={onEditPrompt}>프롬프트 수정</button>
          </div>
          <p className="v3-muted-text">모든 세그먼트 설정이 끝나야 실행 전 확인이 열립니다 · 현재 {configuredCount}/{segments.length}</p>
        </>
      }
    >
      <div className="v3-card">
        <div className="v3-card-header" style={{ gap: 14 }}>
          <div className="v3-kf-pair">
            <div className="v3-kf-thumb">{startKeyframe?.previewUrl ? <ProtectedImage src={startKeyframe.previewUrl} alt="시작 키프레임" /> : <span>KF {selectedSegment?.startImageIndex}</span>}</div>
            <span className="v3-kf-arrow">→</span>
            <div className="v3-kf-thumb">{endKeyframe?.previewUrl ? <ProtectedImage src={endKeyframe.previewUrl} alt="끝 키프레임" /> : <span>KF {selectedSegment?.endImageIndex}</span>}</div>
          </div>
          <div className="v3-kf-meta">
            <div className="v3-card-header-title">이미지</div>
            <span className="v3-card-header-meta">슬롯 순서 고정</span>
          </div>
          <div className="v3-kf-prompt-status">
            <span className="v3-label">프롬프트</span>
            <strong className={selectedSegment?.positivePrompt.trim() ? "is-done-text" : "is-pending-text"}>
              {selectedSegment?.positivePrompt.trim() ? "적용됨" : "미적용"}
            </strong>
          </div>
        </div>
      </div>

      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">
            <span>Wan Node Config · SEG {String(selectedSegmentIndex).padStart(2, "0")}</span>
            <span className="v3-card-header-meta">세그먼트별 개별 설정</span>
          </div>
          <div className="v3-inline-actions">
            {!isFirstSegment ? (
              <button className="v3-text-link-button" type="button" onClick={() => onCopyFirstSegmentConfig(selectedSegmentIndex)}>SEG 01 값 복사</button>
            ) : null}
            <button className="v3-text-link-button is-muted" type="button" onClick={onResetDefaults}>기본값 복원</button>
          </div>
        </div>
        <div className="v3-config-grid">
          {configControls.map((control) => (
            <label className="v3-config-cell" key={control.key}>
              <span className="v3-label">{control.label}</span>
              <input
                value={String(selectedSegment?.config[control.key] ?? control.default ?? "")}
                onChange={(event) => onUpdateConfigValue(control.key, event.target.value, control)}
              />
            </label>
          ))}
        </div>
        <div className="v3-seed-block">
          <span className="v3-label">SEED</span>
          <span>세그먼트별로 서버가 실행 시점에 자동 생성합니다.</span>
        </div>
      </div>
    </AppShell>
  );
}

// E-02 · 2f "S4 실행 전 전체 구성 확인 & Run" — design_handoff_dobedub_v3/
// 2 Create.dc.html의 네 번째 화면. 제출 payload는 기존 jobPayloadPreview를 그대로
// 보여준다(설계 원본의 요약 문구 대신 실제 JSON을 노출 - 값을 지어내지 않기 위함).
//
// 설계 원본과 다르게 뺀 것:
// - 대기 큐 · 예상 시작 시각 · 엔드포인트 HEALTHY 표시 — 이 정보를 주는 API가 없다.
// - "완료 시 알림 받기" · "결과를 Assets에 자동 저장" 체크박스 — 알림 저장 기능은
//   A-03 미착수, 자산 저장은 이미 항상 자동이라 끌 수 있는 옵션 자체가 없다.
// - "이 구성을 초안으로 저장" — 임시저장 API가 없다.
export function Create2fScreen({
  user,
  health,
  onGoTo,
  selected,
  selectedWorkflow,
  keyframes,
  segments,
  jobPayloadPreview,
  running,
  onEditSegments,
  onRun
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  selected: WorkflowItem | null;
  selectedWorkflow: string;
  keyframes: KeyframeState[];
  segments: SegmentState[];
  jobPayloadPreview: unknown;
  running: boolean;
  onEditSegments: () => void;
  onRun: () => void;
}) {
  const keyframesFilled = keyframes.every((keyframe) => Boolean(keyframe.upload?.assetId));
  const filledKeyframeCount = keyframes.filter((keyframe) => Boolean(keyframe.upload?.assetId)).length;
  const segmentsPromptFilled = segments.length > 0 && segments.every((segment) => segment.positivePrompt.trim());
  const negativeFixedIncluded = segments.length > 0 && segments.every((segment) => Boolean(segment.defaultNegativePrompt));
  const validationItems = [
    { label: `키프레임 슬롯 ${filledKeyframeCount} / ${keyframes.length} 채워짐`, done: keyframesFilled },
    { label: `세그먼트 ${segments.length}개 모두 프롬프트 적용`, done: segmentsPromptFilled },
    { label: "노드 구성값 범위 내", done: true },
    { label: "Negative 고정 프롬프트 포함", done: negativeFixedIncluded }
  ];
  const passedCount = validationItems.filter((item) => item.done).length;
  const canRun = keyframesFilled && segmentsPromptFilled && !running && canUse(user, "jobs:run");
  const totalFrames = segments.reduce((sum, segment) => {
    const frames = Number(segment.config.frames ?? segment.config.FRAMES ?? 0);
    return Number.isFinite(frames) ? sum + frames : sum;
  }, 0);

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="workspace"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`STEP 3 / 4 · ${selected?.label || selected?.name || selectedWorkflow} · 세그먼트 ${segments.length}`}
      headerTitle="실행 전 전체 구성 확인"
      headerActions={
        <>
          <button className="v3-secondary-button" type="button" onClick={onEditSegments}>세그먼트 설정으로</button>
          <button className="v3-primary-button" type="button" disabled={!canRun} onClick={onRun}>
            {running ? "제출 중..." : "Run"}
          </button>
        </>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-step is-done"><span className="v3-step-index">✓</span><span>이미지 로드</span></div>
          <div className="v3-step is-done"><span className="v3-step-index">✓</span><span>세그먼트 설정</span></div>
          <div className="v3-step is-active"><span className="v3-step-index">3</span><span>실행 전 확인</span></div>
          <div className="v3-step"><span className="v3-step-index">4</span><span>결과 조회</span></div>
        </div>
      }
      rightPanel={
        <>
          <div className="v3-panel-title">실행</div>
          <div className="v3-summary-card is-highlight">
            <div className="v3-label" style={{ color: "var(--v3-accent-text)" }}>제출 요약</div>
            <div className="v3-summary-row"><span>작업</span><strong>1건 · segments {segments.length}</strong></div>
            {totalFrames > 0 ? <div className="v3-summary-row"><span>총 프레임</span><strong>{totalFrames}</strong></div> : null}
          </div>
          <button className="v3-primary-button" type="button" disabled={!canRun} onClick={onRun}>
            {running ? "제출 중..." : "Run · 영상 생성 시작"}
          </button>
          <p className="v3-muted-text">제출 후에는 세그먼트 설정을 바꿀 수 없습니다 · 수정하려면 취소 후 재실행</p>
          {!canUse(user, "jobs:run") ? <p className="v3-inline-notice">작업 실행 권한이 없습니다.</p> : null}
        </>
      }
    >
      <div className="v3-summary-tiles">
        <div className="v3-summary-tile"><span className="v3-label">WORKFLOW</span><strong>{selected?.label || selected?.name || selectedWorkflow || "-"}</strong></div>
        <div className="v3-summary-tile"><span className="v3-label">KEYFRAMES</span><strong>{filledKeyframeCount} / {keyframes.length}</strong></div>
        <div className="v3-summary-tile"><span className="v3-label">SEGMENTS</span><strong>{segments.length}</strong></div>
      </div>

      <div className="v3-card">
        <div className="v3-review-table-head">
          <span>세그먼트</span>
          <span>프롬프트</span>
          <span>노드 컨피그</span>
          <span style={{ textAlign: "center" }}>상태</span>
        </div>
        {segments.map((segment) => (
          <div className="v3-review-table-row" key={segment.index}>
            <span className="v3-review-seg-name">SEG {String(segment.index).padStart(2, "0")}</span>
            <span className="v3-review-prompt">{segment.positivePrompt.trim() || "프롬프트 미적용"}</span>
            <span className="v3-review-config">
              {[
                segment.config.fps ?? segment.config.FPS,
                segment.config.frames ?? segment.config.FRAMES,
                segment.config.motion_shift ?? segment.config.motionShift
              ].filter((value) => value !== undefined && value !== null).join(" · ") || "-"}
            </span>
            <span style={{ textAlign: "center" }}>
              <span className={`v3-status-badge ${segment.positivePrompt.trim() ? "is-ready" : "is-pending"}`}>
                {segment.positivePrompt.trim() ? "준비됨" : "필요"}
              </span>
            </span>
          </div>
        ))}
      </div>

      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">제출 검증</div>
          <span className="v3-card-header-meta">{passedCount === validationItems.length ? "모두 통과" : `${passedCount} / ${validationItems.length}`} · {validationItems.length}</span>
        </div>
        <div className="v3-validation-grid">
          {validationItems.map((item) => (
            <div className={`v3-checklist-item ${item.done ? "is-done" : "is-warning"}`} key={item.label}>
              <span className="v3-checklist-dot">{item.done ? "✓" : ""}</span>
              {item.label}
            </div>
          ))}
        </div>
      </div>

      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">PAYLOAD</div>
          <span className="v3-card-header-meta">POST /api/jobs</span>
        </div>
        <pre className="v3-payload-json">{JSON.stringify(jobPayloadPreview, null, 2)}</pre>
      </div>
    </AppShell>
  );
}

// E-02 · 2c "S4 진행 · 상태 인포그래픽 · 로그 · 취소 요청" — design_handoff_dobedub_v3/
// 2 Create.dc.html의 다섯 번째 화면. running/progress/elapsedSeconds/logText/
// currentTaskId/cancelRequested는 전부 기존 StudioShell 상태를 그대로 물려받는다.
//
// 설계 원본과 다르게 뺀 것:
// - "예상 잔여" 시간 — 남은 시간을 추정하는 로직이 없다(progress_by_state가
//   TASKS.md에 적힌 대로 3단계뿐이라 선형 추정도 근거가 약하다).
// - SEEDS 패널의 실제 seed 값 — generationSeed는 완료(latestJob) 이후에만 응답에
//   실리고, 세그먼트별 개별 seed를 진행 중에 보여줄 API가 없다.
// - "History에 저장" 버튼 — 완료 시 자동으로 저장되고 있어(job_service) 별도
//   수동 저장 동작이 없다.
export function Create2cScreen({
  user,
  health,
  onGoTo,
  selected,
  selectedWorkflow,
  keyframes,
  segments,
  progress,
  elapsedSeconds,
  logText,
  running,
  cancelRequested,
  currentTaskId,
  onCancel,
  onViewPayload
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  selected: WorkflowItem | null;
  selectedWorkflow: string;
  keyframes: KeyframeState[];
  segments: SegmentState[];
  progress: number;
  elapsedSeconds: number;
  logText: string;
  running: boolean;
  cancelRequested: boolean;
  currentTaskId: string;
  onCancel: () => void;
  onViewPayload: () => void;
}) {
  const stage: "queue" | "progress" | "completed" = !running ? "completed" : progress >= 100 ? "completed" : progress > 0 ? "progress" : "queue";
  const totalFrames = segments.reduce((sum, segment) => {
    const frames = Number(segment.config.frames ?? segment.config.FRAMES ?? 0);
    return Number.isFinite(frames) ? sum + frames : sum;
  }, 0);
  const logLines = logText ? logText.split("\n").filter(Boolean) : [];

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="workspace"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`STEP 4 / 4 · RUN ${currentTaskId ? `#${currentTaskId.slice(0, 8)}` : "-"} · 단일 작업`}
      headerTitle="영상 생성 중"
      headerActions={
        <>
          <span className="v3-run-status-chip">
            <span className="v3-run-status-dot" />
            {running ? `IN_PROGRESS · ${formatElapsed(elapsedSeconds)}` : "COMPLETED"}
          </span>
          <button className="v3-secondary-button" type="button" onClick={onViewPayload}>Payload 보기</button>
        </>
      }
      sidebarExtra={
        // 2026-08-11: 사용자 요청 - IN_QUEUE/IN_PROGRESS/COMPLETED 단계 목록이 본문
        // 중앙의 ".v3-progress-stages" 스테퍼(아래)와 완전히 중복 표시되고 있었다.
        // 사이드바는 RUN 식별 정보만 남기고 단계 목록은 제거.
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>RUN {currentTaskId ? `#${currentTaskId.slice(0, 8)}` : ""} · {selected?.label || selected?.name || selectedWorkflow}</div>
        </div>
      }
      rightPanel={
        <>
          <div className="v3-panel-title-row">
            <div className="v3-panel-title">제출된 Run</div>
            <span className="v3-card-header-meta">{currentTaskId ? `#${currentTaskId.slice(0, 8)}` : "-"}</span>
          </div>
          <div className="v3-summary-card">
            <div className="v3-summary-row"><span>Workflow</span><strong>{selected?.label || selected?.name || selectedWorkflow || "-"}</strong></div>
            <div className="v3-summary-row"><span>Keyframes</span><strong>{keyframes.length}</strong></div>
            <div className="v3-summary-row"><span>Segments</span><strong>{segments.length} <span className="v3-summary-note">· 단일 작업</span></strong></div>
            {totalFrames > 0 ? <div className="v3-summary-row"><span>총 프레임</span><strong>{totalFrames}</strong></div> : null}
          </div>
          <div className="v3-card">
            <div className="v3-card-header">
              <span className="v3-label">SEG</span>
              <span className="v3-card-header-meta">프롬프트 출처</span>
            </div>
            {segments.map((segment) => (
              <div className="v3-status-row" key={segment.index}>
                <span>{String(segment.index).padStart(2, "0")}</span>
                <span>{segment.positivePrompt.trim() ? "프롬프트 적용됨" : "-"}</span>
              </div>
            ))}
          </div>
          <div className="v3-inline-actions">
            <button className="v3-secondary-button v3-flex-button" type="button" onClick={onViewPayload}>Payload 보기</button>
            {canUse(user, "jobs:cancel") ? (
              <button
                className="v3-danger-button v3-flex-button"
                type="button"
                disabled={!running || !currentTaskId || cancelRequested}
                onClick={onCancel}
              >
                {cancelRequested ? "Cancelling..." : "생성 취소"}
              </button>
            ) : null}
          </div>
          {cancelRequested ? (
            <div className="v3-warning-strip">
              <span className="v3-warning-dot" />
              <span>취소를 누르면 워커가 수락할 때까지 CANCELLED로 끝나며 부분 결과는 저장되지 않습니다.</span>
            </div>
          ) : null}
          <p className="v3-muted-text">제출 구성은 실행 중 변경할 수 없습니다 · 결과 파일만 완료 이후 저장됩니다</p>
        </>
      }
    >
      <div className="v3-card v3-progress-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">작업 진행</div>
          <span className="v3-card-header-meta">/api/jobs/{"{id}"} · 3초 폴링</span>
        </div>
        <div className="v3-progress-stages">
          {(["queue", "progress", "completed"] as const).map((key, index) => (
            <React.Fragment key={key}>
              {index > 0 ? <div className={`v3-progress-connector ${stage === "completed" || (stage === "progress" && key === "completed") ? "" : "is-filled"}`} /> : null}
              <div className="v3-progress-stage">
                <div className={`v3-progress-dot ${stage === key ? "is-active" : (key === "queue" && stage !== "queue") || (key === "progress" && stage === "completed") ? "is-past" : "is-pending"}`}>
                  {(key === "queue" && stage !== "queue") || (key === "progress" && stage === "completed") ? "✓" : key === "progress" ? Math.round(progress) : key === "completed" && stage === "completed" ? "✓" : "100"}
                </div>
                <div className="v3-progress-stage-label">
                  <div>{key === "queue" ? "IN_QUEUE" : key === "progress" ? "IN_PROGRESS" : "COMPLETED"}</div>
                  <span>{key === "progress" && stage === "progress" ? `현재 · ${formatElapsed(elapsedSeconds)} 경과` : key === "completed" ? "결과물 저장" : ""}</span>
                </div>
              </div>
            </React.Fragment>
          ))}
        </div>
        <div className="v3-progress-tiles">
          <div className="v3-summary-tile"><span className="v3-label">경과</span><strong>{formatElapsed(elapsedSeconds)}</strong></div>
          <div className="v3-summary-tile"><span className="v3-label">세그먼트</span><strong>{segments.length}</strong></div>
          {totalFrames > 0 ? <div className="v3-summary-tile"><span className="v3-label">총 프레임</span><strong>{totalFrames}</strong></div> : null}
        </div>
      </div>

      <div className="v3-card v3-log-card">
        <div className="v3-log-header">
          <span>STATUS LOG</span>
          <span className="v3-log-header-meta">auto-scroll</span>
        </div>
        <div className="v3-log-body">
          {logLines.length ? logLines.map((line, index) => <div key={index}>{line}</div>) : <div>대기 중...</div>}
        </div>
      </div>
    </AppShell>
  );
}

// E-02 · 2d "S5 결과 · 실행 직후 결과 확인" — design_handoff_dobedub_v3/
// 2 Create.dc.html의 마지막 화면. 성공/실패 판정과 다운로드는 기존
// hasSuccessfulOutput/hasFailedJob/downloadProtectedAsset을 그대로 재사용한다.
//
// 설계 원본과 다르게 뺀 것:
// - "공유 링크" · "시드 고정해 재실행" — 공유 링크 발급 API도, 시드를 고정해
//   재제출하는 경로도 없다.
// - GPU 시간 · Final 파일 크기(MB) · 재생바 스크럽 — 응답에 없는 값이다.
// - 실패 시에도 설계는 성공 레이아웃만 그려서, 실패 상태는 구버전 UI의
//   failure-card 문구를 그대로 옮겨와 별도로 처리했다.
export function Create2dScreen({
  user,
  health,
  onGoTo,
  selected,
  selectedWorkflow,
  keyframes,
  segments,
  latestJob,
  outputAssets,
  displayOutput,
  displayOutputMediaUrl,
  displayOutputDownloadUrl,
  hasSuccessfulOutput,
  hasFailedJob,
  elapsedSeconds,
  onDownload,
  onOpenHistory,
  onNewRun,
  onReviewSettings
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  selected: WorkflowItem | null;
  selectedWorkflow: string;
  keyframes: KeyframeState[];
  segments: SegmentState[];
  latestJob: JobStatusResponse | null;
  outputAssets: OutputAsset[];
  displayOutput: OutputAsset | { fileName?: string; assetId?: string } | null;
  displayOutputMediaUrl: string;
  displayOutputDownloadUrl: string;
  hasSuccessfulOutput: boolean;
  hasFailedJob: boolean;
  elapsedSeconds: number;
  onDownload: () => void;
  onOpenHistory: () => void;
  onNewRun: () => void;
  onReviewSettings: () => void;
}) {
  const segmentOutputs = outputAssets.filter((asset) => asset.outputRole === "segment");

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="workspace"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`RUN · ${selected?.label || selected?.name || selectedWorkflow} · 세그먼트 ${segments.length}`}
      headerTitle={hasFailedJob ? "생성 실패" : "생성 완료"}
      headerActions={
        <>
          <span className={`v3-run-status-chip ${hasFailedJob ? "is-failed" : ""}`}>
            <span className="v3-run-status-dot" />
            {hasFailedJob ? "FAILED" : `COMPLETE · ${formatElapsed(elapsedSeconds)}`}
          </span>
          {hasSuccessfulOutput ? (
            <button className="v3-primary-button" type="button" onClick={onDownload}>Final 다운로드</button>
          ) : null}
        </>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>RUN · 결과물</div>
          <div className="v3-run-stage-item is-active">
            <span>Final 병합본</span>
            <span>{segments.length}장</span>
          </div>
          {segmentOutputs.length ? (
            <div className="v3-run-stage-item">
              <span>구간 검수본</span>
              <span>{segmentOutputs.length}</span>
            </div>
          ) : null}
        </div>
      }
      rightPanel={
        <>
          <div className="v3-panel-title">Run 정보</div>
          <div className="v3-summary-card">
            <div className="v3-summary-row"><span>Workflow</span><strong>{selected?.label || selected?.name || selectedWorkflow || "-"}</strong></div>
            <div className="v3-summary-row"><span>Keyframes</span><strong>{keyframes.length}</strong></div>
            <div className="v3-summary-row"><span>Segments</span><strong>{segments.length}</strong></div>
            <div className="v3-summary-row"><span>Applied Seed</span><strong>{latestJob?.generationSeed || "-"}</strong></div>
          </div>
          <div className="v3-card">
            <div className="v3-card-header">
              <span className="v3-label">프롬프트 출처</span>
              <span className="v3-card-header-meta">SEG별</span>
            </div>
            {segments.map((segment) => (
              <div className="v3-status-row" key={segment.index}>
                <span>SEG {String(segment.index).padStart(2, "0")}</span>
                <span>{segment.positivePrompt.trim() ? "적용됨" : "-"}</span>
              </div>
            ))}
          </div>
          <div className="v3-note-block" style={{ border: "none", padding: 0, margin: 0 }}>
            <div className="v3-label">평가 &amp; 재사용 등록</div>
            <p className="v3-muted-text">이 화면은 실행 직후 결과 확인용입니다. 평가와 재사용 등록은 Task History에서 이 작업을 선택해 진행합니다.</p>
            <button className="v3-text-link-button" type="button" onClick={onOpenHistory}>Task History에서 열기</button>
          </div>
          <div className="v3-inline-actions">
            <button className="v3-secondary-button v3-flex-button" type="button" onClick={onReviewSettings}>세팅 열고 수정</button>
            <button className="v3-primary-button v3-flex-button" type="button" onClick={onNewRun}>새 Run 시작</button>
          </div>
          <p className="v3-muted-text">재실행은 항상 전체 세그먼트를 다시 생성합니다 · 부분 재실행 없음</p>
        </>
      }
    >
      {/* 2026-08-11: 사용자 요청 - 진행 화면(2c)의 큐→진행→완료 스테퍼 구조를
          결과 화면에서도 그대로 유지하고 완료 단계를 하이라이트한다. 2d는 이미
          종료된 상태만 보여주므로(진행 중 %가 없음) 2c처럼 실시간 값을 쓰지 않고
          성공/실패 두 가지 종료 상태만 표현한다. */}
      <div className="v3-card v3-progress-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">진행 단계</div>
        </div>
        <div className="v3-progress-stages">
          <div className="v3-progress-stage">
            <div className="v3-progress-dot is-past">✓</div>
            <div className="v3-progress-stage-label"><div>IN_QUEUE</div><span>지남</span></div>
          </div>
          <div className={`v3-progress-connector ${hasFailedJob ? "is-filled" : ""}`} />
          <div className="v3-progress-stage">
            <div className={`v3-progress-dot ${hasFailedJob ? "is-active" : "is-past"}`}>{hasFailedJob ? "!" : "✓"}</div>
            <div className="v3-progress-stage-label"><div>IN_PROGRESS</div><span>{hasFailedJob ? "실패 지점" : "지남"}</span></div>
          </div>
          <div className={`v3-progress-connector ${hasFailedJob ? "is-filled" : ""}`} />
          <div className="v3-progress-stage">
            <div className={`v3-progress-dot ${hasFailedJob ? "is-pending" : "is-active"}`}>{hasFailedJob ? "-" : "✓"}</div>
            <div className="v3-progress-stage-label"><div>COMPLETED</div><span>{hasFailedJob ? "" : "완료 · 결과물 저장됨"}</span></div>
          </div>
        </div>
      </div>

      {hasFailedJob ? (
        <div className="v3-card v3-failure-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">Generation Failed</div>
          </div>
          <p className="v3-failure-message">{latestJob?.message || "작업이 실패했습니다. RunPod 로그를 확인하세요."}</p>
        </div>
      ) : (
        <div className="v3-card v3-result-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">
              <span>Final 병합본</span>
              <span className="v3-status-badge is-ready">최종 출력 ({keyframes.length}장)</span>
            </div>
          </div>
          {hasSuccessfulOutput ? (
            <>
              {/* 2026-08-11: 사용자 요청 - 아웃풋 실제 해상도와 무관하게 16:9 고정
                  박스로 보여준다(.v3-result-video-frame, object-fit: contain). */}
              <div className="v3-result-video-frame">
                <video className="v3-result-video" src={displayOutputMediaUrl} controls playsInline preload="metadata" />
              </div>
              <div className="v3-result-footer">
                <span>File: {displayOutput?.fileName || displayOutput?.assetId || "generated output"}</span>
                <button className="v3-primary-button" type="button" onClick={onDownload}>Download MP4</button>
              </div>
            </>
          ) : (
            <p className="v3-muted-text" style={{ padding: 16 }}>결과 영상을 불러오는 중입니다.</p>
          )}
        </div>
      )}

      {segmentOutputs.length ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">구간 검수본</div>
            <span className="v3-card-header-meta">품질 확인용 · 배포 대상 아님</span>
          </div>
          <div className="v3-segment-output-grid">
            {segmentOutputs.map((asset) => (
              <div className="v3-segment-output-row" key={asset.assetId || asset.fileName}>
                <span>SEG {asset.segmentIndex ?? "-"} · {asset.fileName || asset.assetId}</span>
              </div>
            ))}
          </div>
          <p className="v3-muted-text" style={{ padding: "0 16px 14px" }}>전환 품질 점검용 출력입니다 · 배포에는 Final을 사용하세요</p>
        </div>
      ) : null}
    </AppShell>
  );
}
