import { useEffect, useState } from "react";
import {
  HealthResponse,
  HistoryItem,
  AssetItem,
  CollectionSummary,
  TaskPromptReviewFlags,
  TaskPromptItem
} from "../api/client";
import { StudioRoute } from "../router";
import { User } from "../auth";
import { AppShell } from "../components/AppShell";
import {
  formatTimestamp,
  isSuccessStatus,
  isTerminalHistoryStatus
} from "../helpers/format";
import { positivePromptEntries, negativePromptEntries } from "../helpers/prompts";
import {
  historyInputImages,
  historyOutputAsset,
  configFromWanNodeSegment
} from "../helpers/workflow";
import { shellNavigate } from "../helpers/navigation";
import {
  useProtectedAssetUrl,
  ProtectedImage,
  ProtectedAssetPreview
} from "../components/ProtectedAssets";


// E-03 · 3a "작업 이력" — design_handoff_dobedub_v3/3 Review.dc.html의 첫 화면.
// 목록·페이지네이션·삭제는 B-01/C-03에서 이미 완성된 로직(loadHistoryPage,
// changeHistoryPageSize, deleteHistoryItem)을 그대로 재사용한다.
//
// 설계 원본과 다르게 뺀 것:
// - run id·프롬프트 검색, 날짜 범위, 워크플로 필터 칩, CSV 내보내기 — `GET
//   /api/history`가 page/pageSize만 받고 검색·필터·내보내기 파라미터가 없다.
// - 상태 필터(전체/완료/실패/진행 중/내 작업만)는 서버 필터가 아니라 **현재
//   불러온 페이지 안에서만** 클라이언트 필터링한다 - 128건 전체가 아니라 화면에
//   이미 있는 20/50건 중에서만 걸러진다는 뜻이라 이 화면에서만 유의미하다.
// - "소요" 컬럼 — HistoryItem에 소요 시간 필드가 없다.
// - 상세 패널의 "평가 4 · 재사용 등록됨" 같은 평가 요약 수치 — 이력 목록
//   응답에 평가 집계가 없다. 우측 패널 Prompt Review 아코디언에서 실제 값을 붙인다.
//
// 2026-08-11: 사용자 요청으로 별도 화면이던 Run 상세(3f/3c)를 폐지하고 그 내용
// (Overview/Assets/Node Config/Prompt Review)을 이 화면의 우측 패널 아코디언으로
// 흡수했다 - 목록에서 선택 즉시 상세를 볼 수 있어 화면 전환이 줄어든다.
export function Create3aScreen({
  user,
  health,
  onGoTo,
  history,
  page,
  pageCount,
  pageSize,
  total,
  loading,
  selectedTaskId,
  deleteTarget,
  deleteError,
  promptReviewItems,
  promptReviewLoading,
  promptReviewNotice,
  onSelect,
  onPageChange,
  onPageSizeChange,
  onDownload,
  onRework,
  onSavePromptReview,
  onSavePromptFeedback,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  canRework,
  canDelete,
  canReview,
  canGiveFeedback
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  history: HistoryItem[];
  page: number;
  pageCount: number;
  pageSize: 20 | 50;
  total: number;
  loading: boolean;
  selectedTaskId: string;
  deleteTarget: HistoryItem | null;
  // #4 오류 위치 규칙: 삭제(동작) 실패는 본문 상단이 아니라 삭제 모달의 버튼 근처에
  // 표시한다. modalNotice(StudioShell)를 그대로 받는다 - 이전엔 어디에도 렌더되지
  // 않아 삭제 실패가 사용자에게 전혀 보이지 않았다.
  deleteError: string;
  // 2026-08-11: 폐지된 Run 상세(3f/3c) 화면의 평가 데이터를 우측 패널
  // Prompt Review 아코디언이 그대로 흡수한다 - 저장 로직(B-02)은 동일.
  promptReviewItems: TaskPromptItem[];
  promptReviewLoading: boolean;
  promptReviewNotice: string;
  onSelect: (item: HistoryItem) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: 20 | 50) => void;
  onDownload: (item: HistoryItem) => void;
  onRework: (item: HistoryItem) => void;
  onSavePromptReview: (segmentIndex: number, payload: Record<string, unknown>) => void;
  onSavePromptFeedback: (outputId: string, payload: { rating?: number; notes?: string }) => void;
  onRequestDelete: (item: HistoryItem) => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  canRework: boolean;
  canDelete: boolean;
  canReview: boolean;
  canGiveFeedback: boolean;
}) {
  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "failed">("all");
  // 2026-08-11: 우측 패널 아코디언 펼침 상태 - Assets는 기본 펼침(결과물을 바로
  // 확인하는 빈도가 가장 높다는 판단), Node Config·Prompt Review는 기본 접힘.
  // 선택한 Run이 바뀌어도 사용자가 펼쳐둔 섹션은 유지한다(세션 내 UX 편의).
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    assets: true,
    nodeConfig: false,
    promptReview: false
  });
  const toggleSection = (key: string) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  const filteredHistory = history.filter((item) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "completed") return isSuccessStatus(item.status);
    if (statusFilter === "failed") return !isSuccessStatus(item.status) && Boolean(item.status);
    return true;
  });
  const selectedItem = history.find((item) => item.taskId === selectedTaskId) || history[0] || null;
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  const pageOffset = (page - 1) * pageSize;
  const completedCount = history.filter((item) => isSuccessStatus(item.status)).length;
  const failedCount = history.filter((item) => !isSuccessStatus(item.status) && item.status).length;
  const isFailedSelected = selectedItem ? !isSuccessStatus(selectedItem.status) && Boolean(selectedItem.status) : false;
  const output = selectedItem ? historyOutputAsset(selectedItem) : null;
  // 훅은 조건 없이 매 렌더 호출해야 한다(selectedItem이 null↔값 사이를 오갈 수
  // 있으므로 이 hook을 early return 뒤에 두지 않는다) - 3f 구버전의 실수를 반복하지 않음.
  const outputMediaUrl = useProtectedAssetUrl(output?.downloadUrl || output?.url || selectedItem?.outputUrl || "");
  const inputImages = selectedItem ? historyInputImages(selectedItem) : [];
  const nodeConfigSegments = selectedItem?.wanNodeConfig?.segments?.length
    ? selectedItem.wanNodeConfig.segments
    : selectedItem?.segments || [];

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="taskHistory"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="TASK HISTORY"
      headerTitle="작업 이력"
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>필터 · 현재 페이지 {history.length}건</div>
          {([
            ["all", "전체", history.length],
            ["completed", "완료", completedCount],
            ["failed", "실패", failedCount]
          ] as const).map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              className={`v3-segment-nav-item ${statusFilter === key ? "is-active" : ""}`}
              onClick={() => setStatusFilter(key)}
            >
              <div className="v3-segment-nav-head"><span>{label}</span><span>{count}</span></div>
            </button>
          ))}
        </div>
      }
      sidebarFooter={<p className="v3-muted-text">보관 기한 90일 · 한 페이지 {pageSize}건 · 이후 Assets만 유지</p>}
      rightPanel={
        selectedItem ? (
          <>
            <div className="v3-panel-title-row">
              <div className="v3-panel-title">RUN #{selectedItem.taskId.slice(0, 8)}</div>
              <span className={`v3-status-badge ${isSuccessStatus(selectedItem.status) ? "is-ready" : "is-pending"}`}>{selectedItem.status || "-"}</span>
            </div>

            {/* Overview - 항상 펼침. runpod_job_id는 _task_to_history_item()이
                내려주지만 타입 정의에 빠져 있던 필드였다(2026-08-11 client.ts에 추가). */}
            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>워크플로</span><strong>{selectedItem.workflowName || selectedItem.workflow || selectedItem.workflowId || "-"}</strong></div>
              <div className="v3-summary-row"><span>Task ID</span><strong style={{ fontFamily: "var(--v3-font-mono)", fontSize: 11 }}>{selectedItem.taskId}</strong></div>
              <div className="v3-summary-row"><span>runpod_job_id</span><strong style={{ fontFamily: "var(--v3-font-mono)", fontSize: 11 }}>{selectedItem.runpodJobId || "-"}</strong></div>
              <div className="v3-summary-row"><span>실행자 · 시각</span><strong>{selectedItem.workerName || selectedItem.user?.name || "-"} · {formatTimestamp(selectedItem.timestamp).replace("\n", " ")}</strong></div>
              <div className="v3-summary-row"><span>Segments · Seed</span><strong>{selectedItem.segmentCount || selectedItem.segments?.length || 1} · {selectedItem.generationSeed || selectedItem.seed || "-"}</strong></div>
            </div>

            <div className="v3-inline-actions">
              {isFailedSelected
                ? (canRework ? <button className="v3-primary-button v3-flex-button" type="button" onClick={() => onRework(selectedItem)}>전체 재실행</button> : null)
                : <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onDownload(selectedItem)}>Final 다운로드</button>}
              {!isFailedSelected && canRework ? <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onRework(selectedItem)}>재작업</button> : null}
            </div>

            {/* Assets */}
            <div className="v3-card">
              <button type="button" className="v3-card-header v3-accordion-header" aria-expanded={openSections.assets} onClick={() => toggleSection("assets")}>
                <div className="v3-card-header-title">Assets</div>
                <span className="v3-accordion-toggle">{openSections.assets ? "−" : "+"}</span>
              </button>
              {openSections.assets ? (
                <div className="v3-accordion-body">
                  {isFailedSelected ? (
                    <p className="v3-muted-text">이 작업은 결과물이 저장되지 않았습니다.</p>
                  ) : outputMediaUrl ? (
                    <div className="v3-result-video-frame" style={{ borderRadius: 8, marginBottom: 10 }}>
                      <video className="v3-result-video" src={outputMediaUrl} controls playsInline preload="metadata" />
                    </div>
                  ) : (
                    <p className="v3-muted-text">생성된 MP4 파일이 없습니다.</p>
                  )}
                  <div className="v3-label" style={{ padding: "6px 0 4px" }}>Input Images</div>
                  <div className="v3-segment-output-grid" style={{ padding: 0 }}>
                    {inputImages.length ? inputImages.map((image) => (
                      <div className="v3-kf-thumb" key={`${image.index}-${image.assetId}`} style={{ width: "auto", height: 60 }}>
                        {image.assetId ? <ProtectedImage src={`/api/files/${image.assetId}`} alt={image.fileName || `Input ${image.index}`} /> : <span>KF {image.index}</span>}
                      </div>
                    )) : <p className="v3-muted-text">저장된 입력 이미지가 없습니다.</p>}
                  </div>
                </div>
              ) : null}
            </div>

            {/* Node Config */}
            <div className="v3-card">
              <button type="button" className="v3-card-header v3-accordion-header" aria-expanded={openSections.nodeConfig} onClick={() => toggleSection("nodeConfig")}>
                <div className="v3-card-header-title">Node Config</div>
                <span className="v3-accordion-toggle">{openSections.nodeConfig ? "−" : "+"}</span>
              </button>
              {openSections.nodeConfig ? (
                <div className="v3-accordion-body">
                  {nodeConfigSegments.length ? nodeConfigSegments.map((segment, index) => {
                    const config = configFromWanNodeSegment(segment);
                    const entries = Object.entries(config);
                    return (
                      <div key={`${segment.index ?? index}-${segment.nodeId ?? ""}`} className="v3-summary-card" style={{ marginBottom: index < nodeConfigSegments.length - 1 ? 8 : 0 }}>
                        <div className="v3-label">{segment.displayName || `SEG ${(segment.index ?? index) + 1}`}</div>
                        {entries.length
                          ? entries.map(([key, value]) => (
                              <div className="v3-summary-row" key={key}><span>{key}</span><strong>{String(value)}</strong></div>
                            ))
                          : <p className="v3-muted-text">설정값이 없습니다.</p>}
                      </div>
                    );
                  }) : <p className="v3-muted-text">세그먼트 설정 정보가 없습니다.</p>}
                </div>
              ) : null}
            </div>

            {/* Prompt Review */}
            {!isFailedSelected && canReview ? (
              <div className="v3-card">
                <button type="button" className="v3-card-header v3-accordion-header" aria-expanded={openSections.promptReview} onClick={() => toggleSection("promptReview")}>
                  <div className="v3-card-header-title">
                    <span>Prompt Review</span>
                    <span className="v3-card-header-meta">{promptReviewItems.length} segment(s)</span>
                  </div>
                  <span className="v3-accordion-toggle">{openSections.promptReview ? "−" : "+"}</span>
                </button>
                {openSections.promptReview ? (
                  <div className="v3-accordion-body">
                    {promptReviewNotice ? <p className="v3-inline-notice">{promptReviewNotice}</p> : null}
                    {promptReviewLoading ? <p className="v3-muted-text">불러오는 중입니다...</p> : null}
                    <div className="v3-review-grid">
                      {promptReviewItems.map((prompt) => (
                        <V3PromptReviewGroup
                          key={`${prompt.taskId}-${prompt.segmentIndex}`}
                          prompt={prompt}
                          loading={promptReviewLoading}
                          canReview={canReview}
                          canGiveFeedback={canGiveFeedback}
                          onSave={onSavePromptReview}
                          onSaveFeedback={onSavePromptFeedback}
                        />
                      ))}
                      {!promptReviewLoading && !promptReviewItems.length ? <p className="v3-muted-text">저장된 작업 프롬프트가 없습니다.</p> : null}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </>
        ) : (
          <p className="v3-muted-text">왼쪽 목록에서 작업을 선택하세요.</p>
        )
      }
    >
      <div className="v3-card">
        <div className="v3-review-table-head" style={{ gridTemplateColumns: "40px 118px 90px minmax(0,1fr) minmax(0,1fr) 84px 56px" }}>
          <span>No</span><span>Timestamp</span><span>Worker</span><span>Positive Prompt</span><span>Negative Prompt</span><span>Status</span><span style={{ textAlign: "right" }}>삭제</span>
        </div>
        {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {!loading && !filteredHistory.length ? <p className="v3-muted-text" style={{ padding: 16 }}>표시할 작업이 없습니다.</p> : null}
        {filteredHistory.map((item) => {
          const isSelected = item.taskId === selectedTaskId;
          const promptSnippet = positivePromptEntries(item)[0]?.text || item.positivePrompt || item.prompt || "-";
          const negativeSnippet = negativePromptEntries(item)[0]?.text || item.negativePrompt || "-";
          const rowNo = pageOffset + history.findIndex((candidate) => candidate.taskId === item.taskId) + 1;
          return (
            <div
              key={item.taskId}
              className={`v3-review-table-row v3-history-row ${isSelected ? "is-selected" : ""}`}
              style={{ gridTemplateColumns: "40px 118px 90px minmax(0,1fr) minmax(0,1fr) 84px 56px", cursor: "pointer" }}
              onClick={() => onSelect(item)}
            >
              <span className="v3-review-seg-name">{rowNo}</span>
              <span style={{ color: "var(--v3-text-secondary)", fontSize: 11.5 }}>{formatTimestamp(item.timestamp).replace("\n", " ")}</span>
              <span style={{ fontSize: 12 }}>{item.workerName || item.user?.name || "-"}</span>
              <div className="v3-review-prompt" style={{ minWidth: 0 }}>{promptSnippet}</div>
              <div className="v3-review-prompt" style={{ minWidth: 0 }}>{negativeSnippet}</div>
              <span>
                <span className={`v3-status-badge ${isSuccessStatus(item.status) ? "is-ready" : "is-pending"}`}>{item.status || "-"}</span>
              </span>
              <span style={{ textAlign: "right" }}>
                {canDelete && isTerminalHistoryStatus(item.status) ? (
                  <button
                    className="v3-text-link-button"
                    style={{ color: "var(--v3-danger)" }}
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onRequestDelete(item);
                    }}
                  >
                    삭제
                  </button>
                ) : null}
              </span>
            </div>
          );
        })}
        <div className="v3-pagination">
          <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {total}</span>
          <div className="v3-pagination-controls">
            <button className="v3-page-button" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>이전</button>
            <span className="v3-page-button is-current">{page}</span>
            <button className="v3-page-button" type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>다음</button>
            <select className="v3-page-size-select" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value) as 20 | 50)}>
              <option value={20}>20건 / 페이지</option>
              <option value={50}>50건 / 페이지</option>
            </select>
          </div>
        </div>
      </div>

      {deleteTarget ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="v3DeleteHistoryTitle">
          <div className="v3-modal-panel">
            <div className="v3-label" style={{ color: "var(--v3-danger)" }}>HISTORY:DELETE</div>
            <h2 id="v3DeleteHistoryTitle" className="v3-modal-title">작업 내역 삭제</h2>
            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>작업</span><strong>#{deleteTarget.taskId.slice(0, 8)} · {deleteTarget.workflowName || deleteTarget.workflow || deleteTarget.workflowId || "-"}</strong></div>
              <div className="v3-summary-row"><span>실행</span><strong>{formatTimestamp(deleteTarget.timestamp).replace("\n", " ")} · {deleteTarget.workerName || deleteTarget.user?.name || "-"}</strong></div>
              <div className="v3-summary-row"><span>결과물</span><strong>{(deleteTarget.outputAssets || []).length || (deleteTarget.outputUrl ? 1 : 0)}건</strong></div>
            </div>
            <p className="v3-modal-body-text">이력에서 제거되면 이 작업의 프롬프트 평가와 재사용 등록도 함께 사라집니다. 결과물 파일은 Assets에 남습니다.</p>
            <div className="v3-warning-strip" style={{ background: "var(--v3-danger-bg)", margin: 0 }}>
              <span className="v3-warning-dot" style={{ background: "var(--v3-danger)" }} />
              <span style={{ color: "var(--v3-danger)" }}>되돌릴 수 없습니다</span>
            </div>
            {deleteError ? <p className="v3-inline-error" role="alert">{deleteError}</p> : null}
            <div className="v3-inline-actions">
              <button className="v3-secondary-button v3-flex-button" type="button" onClick={onCancelDelete}>취소</button>
              <button
                className="v3-danger-button v3-flex-button"
                style={{ background: "var(--v3-danger)", color: "#fff", borderColor: "var(--v3-danger)" }}
                type="button"
                disabled={!isTerminalHistoryStatus(deleteTarget.status)}
                onClick={onConfirmDelete}
              >
                삭제
              </button>
            </div>
            <p className="v3-muted-text">진행 중인 작업은 삭제할 수 없습니다 · 권한이 없으면 버튼이 보이지 않습니다</p>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}

export const PROMPT_REVIEW_FLAGS: Array<[keyof TaskPromptReviewFlags, string]> = [
  ["intentMatched", "프롬프트 의도 반영"],
  ["identityPreserved", "이미지 정체성 유지"],
  ["naturalMotion", "움직임 자연스러움"],
  ["noDistortion", "왜곡/깨짐 없음"],
  ["backgroundStable", "배경 안정성"]
];

// 3f 전용 v3 평가 카드. 구버전 PromptReviewCard/PromptFeedbackCard(E-06에서 제거)와
// 저장 로직은 동일(B-02: task_prompts ↔ prompt_feedback 역할 분리)하되 v3 토큰으로
// 다시 그렸다. PROMPT_REVIEW_FLAGS는 원래 그 구버전 카드들 사이에 정의돼 있었지만
// 이 v3 카드도 함께 쓰는 공유 상수라 E-06에서 살아남아 이 근처로 옮겨왔다.
export function V3PromptReviewGroup({
  prompt,
  loading,
  canReview,
  canGiveFeedback,
  onSave,
  onSaveFeedback
}: {
  prompt: TaskPromptItem;
  loading: boolean;
  canReview: boolean;
  canGiveFeedback: boolean;
  onSave: (segmentIndex: number, payload: Record<string, unknown>) => void;
  onSaveFeedback: (outputId: string, payload: { rating?: number; notes?: string }) => void;
}) {
  const [rating, setRating] = useState(String(prompt.qualityRating || ""));
  const [reuseEligible, setReuseEligible] = useState(Boolean(prompt.reuseEligible));
  const [flags, setFlags] = useState<TaskPromptReviewFlags>(prompt.reviewFlags || {});
  const [comment, setComment] = useState(prompt.qualityComment || "");
  const existingFeedback = prompt.promptFeedback || null;
  const [feedbackRating, setFeedbackRating] = useState(String(existingFeedback?.rating || ""));
  const [feedbackNotes, setFeedbackNotes] = useState(existingFeedback?.notes || "");

  useEffect(() => {
    setRating(String(prompt.qualityRating || ""));
    setReuseEligible(Boolean(prompt.reuseEligible));
    setFlags(prompt.reviewFlags || {});
    setComment(prompt.qualityComment || "");
    setFeedbackRating(String(existingFeedback?.rating || ""));
    setFeedbackNotes(existingFeedback?.notes || "");
  }, [prompt.id]);

  const hasReuseReason = Object.values(flags).some(Boolean);
  const saveDisabled = loading || !canReview || (reuseEligible && !hasReuseReason);

  return (
    <div className="v3-review-card">
      <div className="v3-card-header">
        <span className="v3-label">SEG {prompt.segmentIndex}</span>
        <span className="v3-card-header-meta">{rating ? "reviewed" : "unreviewed"}</span>
      </div>
      <div className="v3-prompt-text-block">{prompt.positivePrompt || "-"}</div>
      <div className="v3-rating-row">
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            className={`v3-rating-pill ${String(value) === rating ? "is-selected" : ""}`}
            onClick={() => setRating(String(value))}
          >
            {value}
          </button>
        ))}
      </div>
      <div className="v3-term-chip-row">
        {PROMPT_REVIEW_FLAGS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`v3-term-chip ${flags[key] ? "is-selected" : ""}`}
            onClick={() => setFlags((current) => ({ ...current, [key]: !current[key] }))}
          >
            {label}
          </button>
        ))}
      </div>
      <label className="v3-checklist-item is-done" style={{ cursor: "pointer" }}>
        <input type="checkbox" checked={reuseEligible} onChange={(event) => setReuseEligible(event.target.checked)} style={{ marginRight: 4 }} />
        재사용 가능 — Prompt Library에 등록
      </label>
      {reuseEligible && !hasReuseReason ? <p className="v3-inline-notice">재사용 가능으로 저장하려면 사유를 하나 이상 선택하세요.</p> : null}
      <textarea className="v3-scene-textarea" rows={2} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="품질 판단, 재사용 조건, 보완점" />
      <button
        className="v3-primary-button"
        type="button"
        disabled={saveDisabled}
        onClick={() => onSave(prompt.segmentIndex, { qualityRating: rating, qualityComment: comment, reuseEligible, reviewFlags: flags })}
      >
        평가 저장 · 재사용 등록
      </button>

      {prompt.promptGenerationOutputId ? (
        <div className="v3-feedback-block">
          <div className="v3-label">프롬프트 생성 품질 · {prompt.modelName || "Qwen"}</div>
          <div className="v3-rating-row">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                key={value}
                type="button"
                className={`v3-rating-pill ${String(value) === feedbackRating ? "is-selected" : ""}`}
                disabled={!canGiveFeedback}
                onClick={() => setFeedbackRating(String(value))}
              >
                {value}
              </button>
            ))}
          </div>
          <textarea className="v3-scene-textarea" rows={2} disabled={!canGiveFeedback} value={feedbackNotes} onChange={(event) => setFeedbackNotes(event.target.value)} placeholder="생성된 프롬프트 자체의 품질 메모" />
          <button
            className="v3-secondary-button"
            type="button"
            disabled={loading || !canGiveFeedback}
            onClick={() => onSaveFeedback(prompt.promptGenerationOutputId as string, { rating: feedbackRating ? Number(feedbackRating) : undefined, notes: feedbackNotes.trim() || undefined })}
          >
            프롬프트 품질 평가 저장
          </button>
        </div>
      ) : null}
    </div>
  );
}

// E-03 · 4c "프롬프트 재사용" — design_handoff_dobedub_v3/3 Review.dc.html의
// 세 번째 화면. 검색·목록·적용 로직은 기존 searchPromptReuse/applyReusablePrompt를
// 그대로 재사용하고(`GET /api/prompts/reusable`), 화면만 새로 짰다.
// 2026-08-11: 카드 그리드 → 리스트로 전환 + 서버사이드 페이지네이션(고정
// 20건/페이지) 추가. 3a 작업 이력(Create3aScreen)이 쓰는
// `.v3-review-table-head/-row` + `.v3-pagination` 패턴을 그대로 재사용한다 -
// 카드 하나가 담던 정보(워크플로·세그먼트, Rating, 프롬프트 본문, 사유 칩,
// Task ID, Model, 적용 버튼)를 한 줄로 압축했다. 프롬프트 본문은 한 줄
// 말줄임(`title` 속성으로 전체 텍스트는 hover 시 노출)으로 바꿨다 - 여러 줄
// 카드 본문을 표 행에 그대로 넣으면 행 높이가 들쭉날쭉해진다.
export function Create4cScreen({
  user,
  health,
  onGoTo,
  keyword,
  items,
  loading,
  notice,
  page,
  pageSize,
  total,
  workflowName,
  onKeywordChange,
  onSearch,
  onPageChange,
  onApply
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  keyword: string;
  items: TaskPromptItem[];
  loading: boolean;
  notice: string;
  page: number;
  pageSize: number;
  total: number;
  workflowName: string;
  onKeywordChange: (value: string) => void;
  onSearch: () => void;
  onPageChange: (page: number) => void;
  onApply: (prompt: TaskPromptItem) => void;
}) {
  function reviewReasons(prompt: TaskPromptItem) {
    const flags = prompt.reviewFlags || {};
    return PROMPT_REVIEW_FLAGS.filter(([key]) => Boolean(flags[key])).map(([, label]) => label);
  }

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  // 2026-08-11: 사용자 요청 - 정보 항목을 워크플로/시작·다음 이미지/포지티브·
  // 네거티브 프롬프트/사유/코멘트/레이팅/생성자/모델명 9개로 재구성. "적용"은
  // 한 번 컬럼을 없애고 행 클릭으로 대체했다가, 사용자 요청으로 다시 버튼
  // 컬럼으로 복구했다.
  const gridColumns = "108px 172px minmax(0,1.3fr) minmax(0,1fr) 108px 130px 54px 88px 108px 64px";

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="promptLibrary"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={`대상 워크플로 · ${workflowName || "-"}`}
      headerTitle="프롬프트 재사용"
      headerActions={
        <>
          <input
            className="v3-search-input"
            value={keyword}
            onChange={(event) => onKeywordChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSearch();
            }}
            placeholder="프롬프트, 코멘트, 재사용 사유, task 검색"
          />
          <button className="v3-primary-button" type="button" disabled={loading} onClick={onSearch}>
            {loading ? "Searching..." : "Search"}
          </button>
        </>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-card" style={{ overflowX: "auto" }}>
        <div className="v3-review-table-head" style={{ gridTemplateColumns: gridColumns, minWidth: 980 }}>
          <span>워크플로</span><span>시작 → 다음 이미지</span><span>프롬프트 (Positive)</span><span>프롬프트 (Negative)</span><span>사유</span><span>코멘트</span><span>레이팅</span><span>생성자</span><span>모델명</span><span style={{ textAlign: "right" }}>적용</span>
        </div>
        {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {!loading && !items.length ? (
          <p className="v3-muted-text" style={{ padding: 16 }}>재사용 가능으로 등록된 프롬프트가 없습니다. Task History에서 작업을 선택해 Prompt Review 아코디언에서 평가·재사용 등록을 먼저 진행하세요.</p>
        ) : null}
        {!loading && items.map((prompt) => {
          const reasons = reviewReasons(prompt);
          const startAsset = (prompt.inputAssets || [])[0];
          const endAsset = (prompt.inputAssets || [])[1];
          return (
            <div
              className="v3-review-table-row"
              style={{ gridTemplateColumns: gridColumns, minWidth: 980 }}
              key={prompt.id}
            >
              <span className="v3-review-seg-name">{prompt.workflowId}<br /><span className="v3-muted-text">Segment {prompt.segmentIndex}</span></span>
              <span className="v3-kf-pair v3-kf-pair-sm">
                <span className="v3-kf-thumb v3-kf-thumb-sm">
                  {startAsset?.assetId ? <ProtectedImage src={`/api/files/${startAsset.assetId}`} alt="시작 이미지" /> : <span>-</span>}
                </span>
                <span className="v3-kf-arrow">→</span>
                <span className="v3-kf-thumb v3-kf-thumb-sm">
                  {endAsset?.assetId ? <ProtectedImage src={`/api/files/${endAsset.assetId}`} alt="다음 이미지" /> : <span>-</span>}
                </span>
              </span>
              <span className="v3-reuse-prompt-cell">
                {prompt.positivePrompt || "-"}
              </span>
              <span className="v3-reuse-prompt-cell">
                {prompt.negativePrompt || "-"}
              </span>
              <span>
                {reasons.length ? (
                  <span className="v3-term-chip-row">
                    <span className="v3-term-chip is-selected">{reasons[0]}</span>
                    {reasons.length > 1 ? <span className="v3-muted-text">+{reasons.length - 1}</span> : null}
                  </span>
                ) : (
                  <span className="v3-muted-text">사유 없음</span>
                )}
              </span>
              <span
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={prompt.qualityComment || "-"}
              >
                {prompt.qualityComment || "-"}
              </span>
              <span>
                <span className="v3-status-badge is-ready">{prompt.qualityRating || "-"}</span>
              </span>
              <span style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={prompt.createdBy || "-"}>
                {prompt.createdBy || "-"}
              </span>
              <span style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={prompt.modelName || prompt.modelProfileId || "-"}>
                {prompt.modelName || prompt.modelProfileId || "-"}
              </span>
              <span style={{ textAlign: "right" }}>
                <button className="v3-text-link-button" type="button" onClick={() => onApply(prompt)}>적용</button>
              </span>
            </div>
          );
        })}
        {total > pageSize ? (
          <div className="v3-pagination">
            <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {total}</span>
            <div className="v3-pagination-controls">
              <button className="v3-page-button" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>이전</button>
              <span className="v3-page-button is-current">{page}</span>
              <button className="v3-page-button" type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>다음</button>
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}

// E-03 · 5a "Asset 관리" — design_handoff_dobedub_v3/3 Review.dc.html의 자산
// 그리드(5a)와 컬렉션(5c) 두 화면이었던 것을 2026-08-11 사용자 요청으로 하나로
// 합쳤다: "asset을 output 기준으로 관리, asset은 output에 input 이미지가
// 종속되는 구조로 변경, asset과 collection을 Asset 관리로 통합, Asset 하위
// 카테고리에 collection(미분류 포함)을 가지며 각 하위 카테고리는 목록기반
// 정보구조로 구성"(첨부 목업 참조). 백엔드도 함께 바뀌었다 - `GET /api/assets`가
// 이제 `assets` 테이블 전체가 아니라 `task_output_assets`에 연결된 출력 자산만
// 최상위로 내려주고(`list_assets`, task_tracking_service.py), 같은 작업의
// 입력 이미지는 각 출력 행 안에 `inputAssets`로 종속되어 함께 온다. 한 번도
// 출력으로 이어지지 못한 입력 전용 업로드(중단된 작업의 키프레임 등)는 사용자
// 결정에 따라 이 화면에서 제외한다(출력 자산 목록이 원래 대상이 아님).
//
// 설계 원본과 다르게 뺀 것 — 전부 대응 백엔드가 없어서 뺐다(가짜 데이터 금지 원칙):
// - 태그(#가을 #야외 등), 공개 범위(PRIVATE/SHARED 토글) — `assets` 테이블에 대응
//   컬럼이 없음.
// - 저장 용량 진행 바("184/500 GB") — 총 한도 값을 내려주는 API가 없음.
// - "업로드" 버튼 — 업로드는 `2a` 키프레임 슬롯에서만 발생하는 것이 현재 흐름.
// - 정렬 드롭다운 — API가 `created_at desc` 고정 정렬만 지원.
// 컬렉션 소속은 다대다로 유지(사용자 선택 - 자산 하나가 여러 컬렉션에 동시에 속할
// 수 있음) — 그래서 "Collection" 열은 단일 선택 대신 칩 목록 + 추가/제거로 구현.
export function Create5aScreen({
  user,
  health,
  onGoTo,
  items,
  page,
  pageCount,
  pageSize,
  total,
  loading,
  notice,
  collections,
  collectionFilter,
  createName,
  onCollectionFilterChange,
  onCreateNameChange,
  onCreateCollection,
  onAddToCollection,
  onRemoveFromCollection,
  onPageChange,
  onPageSizeChange,
  onDownload
}: {
  user: User | null;
  health: HealthResponse | null;
  onGoTo: (route: StudioRoute) => void;
  items: AssetItem[];
  page: number;
  pageCount: number;
  pageSize: 20 | 50;
  total: number;
  loading: boolean;
  notice: string;
  collections: CollectionSummary[];
  collectionFilter: number | "uncategorized" | "";
  createName: string;
  onCollectionFilterChange: (value: number | "uncategorized" | "") => void;
  onCreateNameChange: (value: string) => void;
  onCreateCollection: () => void;
  onAddToCollection: (assetId: string, collectionId: number) => void;
  onRemoveFromCollection: (assetId: string, collectionId: number) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: 20 | 50) => void;
  onDownload: (item: AssetItem) => void;
}) {
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  // 2026-08-12: "미리보기" 버튼이 기능 없이 정적 썸네일/배지만 보여주고 있었다는
  // 지적 + 위치를 앞으로 옮겨달라는 요청 - Asset ID 바로 다음(Collection·Asset
  // 이름·생성일·생성자보다 앞)으로 옮기고, 클릭하면 큰 미리보기 모달을 연다
  // (이미지는 확대 이미지, 영상 출력은 controls 있는 <video>로 재생 - 목록
  // 썸네일에서는 <img>가 영상을 못 그려 배지만 보이던 문제도 여기서 해소됨).
  const gridColumns = "168px 108px 62px minmax(0,1fr) 96px 88px 176px 68px";
  const [previewItem, setPreviewItem] = useState<AssetItem | null>(null);
  const previewIsImage = previewItem ? (previewItem.mimeType || "").startsWith("image/") : false;

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="assets"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="ASSETS"
      headerTitle={`Asset 관리 · 전체 ${total}개`}
      headerActions={
        <>
          <input
            className="v3-search-input"
            value={createName}
            placeholder="새 컬렉션 이름"
            onChange={(event) => onCreateNameChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && createName.trim()) {
                onCreateCollection();
              }
            }}
          />
          <button className="v3-secondary-button" type="button" disabled={!createName.trim()} onClick={onCreateCollection}>＋ 컬렉션 만들기</button>
        </>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>Collection · {collections.length}</div>
          <button
            type="button"
            className={`v3-segment-nav-item ${collectionFilter === "" ? "is-active" : ""}`}
            onClick={() => onCollectionFilterChange("")}
          >
            <div className="v3-segment-nav-head"><span>전체</span></div>
          </button>
          <button
            type="button"
            className={`v3-segment-nav-item ${collectionFilter === "uncategorized" ? "is-active" : ""}`}
            onClick={() => onCollectionFilterChange("uncategorized")}
          >
            <div className="v3-segment-nav-head"><span>미분류</span></div>
          </button>
          {loading && !collections.length ? <p className="v3-muted-text" style={{ padding: "4px 10px" }}>불러오는 중입니다...</p> : null}
          {collections.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`v3-segment-nav-item ${collectionFilter === c.id ? "is-active" : ""}`}
              onClick={() => onCollectionFilterChange(c.id)}
            >
              <div className="v3-segment-nav-head"><span>{c.name}</span><span>{c.itemCount}</span></div>
            </button>
          ))}
        </div>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-card" style={{ overflowX: "auto" }}>
        <div className="v3-review-table-head" style={{ gridTemplateColumns: gridColumns, minWidth: 900 }}>
          <span>Collection</span><span>Asset ID</span><span>미리보기</span><span>Asset 이름</span><span>생성일</span><span>생성자</span><span>입력 이미지</span><span style={{ textAlign: "right" }}>다운로드</span>
        </div>
        {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {!loading && !items.length ? <p className="v3-muted-text" style={{ padding: 16 }}>표시할 자산이 없습니다.</p> : null}
        {!loading && items.map((item) => {
          const itemCollectionIds = new Set((item.collections || []).map((c) => c.id));
          const availableToAdd = collections.filter((c) => !itemCollectionIds.has(c.id));
          const isImage = (item.mimeType || "").startsWith("image/");
          return (
            <div className="v3-review-table-row" style={{ gridTemplateColumns: gridColumns, minWidth: 900 }} key={item.assetId}>
              <span>
                <div className="v3-asset-collection-chips">
                  {(item.collections || []).length ? (item.collections || []).map((c) => (
                    <span className="v3-asset-collection-chip" key={c.id}>
                      {c.name}
                      <button
                        type="button"
                        className="v3-asset-collection-chip-remove"
                        title={`${c.name}에서 빼기`}
                        onClick={() => onRemoveFromCollection(item.assetId, c.id)}
                      >
                        ×
                      </button>
                    </span>
                  )) : <span className="v3-muted-text">미분류</span>}
                </div>
                {availableToAdd.length ? (
                  <select
                    className="v3-asset-collection-add"
                    value=""
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      if (value) onAddToCollection(item.assetId, value);
                      event.target.value = "";
                    }}
                  >
                    <option value="">+ 컬렉션에 담기</option>
                    {availableToAdd.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                ) : null}
              </span>
              <span className="v3-review-seg-name" title={item.assetId}>{item.assetId.slice(0, 12)}</span>
              <span>
                <button
                  type="button"
                  className="v3-kf-thumb v3-kf-thumb-sm v3-asset-preview-trigger"
                  title="미리보기"
                  onClick={() => setPreviewItem(item)}
                >
                  {isImage ? <ProtectedImage src={`/api/files/${item.assetId}`} alt={item.fileName} /> : <span>{(item.type || item.mimeType || "FILE").toUpperCase().slice(0, 4)}</span>}
                </button>
              </span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.fileName}>
                {item.fileName}
              </span>
              <span style={{ fontSize: 11.5 }}>{item.createdAt || "-"}</span>
              <span style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.createdBy || "-"}>
                {item.createdBy || "-"}
              </span>
              <span className="v3-asset-input-row">
                {(item.inputAssets || []).length ? (item.inputAssets || []).map((input) => (
                  <span className="v3-kf-thumb v3-kf-thumb-sm" key={input.assetId} title={input.fileName}>
                    <ProtectedImage src={`/api/files/${input.assetId}`} alt={input.fileName} />
                  </span>
                )) : <span className="v3-muted-text">-</span>}
              </span>
              <span style={{ textAlign: "right" }}>
                <button className="v3-text-link-button" type="button" onClick={() => onDownload(item)}>다운로드</button>
              </span>
            </div>
          );
        })}
      </div>
      <div className="v3-pagination">
        <span className="v3-pagination-meta">{pageStart}–{pageEnd} / {total}</span>
        <div className="v3-pagination-controls">
          <button className="v3-page-button" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>이전</button>
          <span className="v3-page-button is-current">{page}</span>
          <button className="v3-page-button" type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>다음</button>
          <select className="v3-page-size-select" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value) as 20 | 50)}>
            <option value={20}>20건 / 페이지</option>
            <option value={50}>50건 / 페이지</option>
          </select>
        </div>
      </div>
      {previewItem ? (
        <div className="v3-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="v3AssetPreviewTitle" onClick={() => setPreviewItem(null)}>
          <div className="v3-modal-panel v3-modal-panel-media" onClick={(event) => event.stopPropagation()}>
            <div className="v3-modal-media-head">
              <h2 id="v3AssetPreviewTitle" className="v3-modal-title" title={previewItem.assetId}>{previewItem.fileName}</h2>
              <button className="v3-icon-button" type="button" onClick={() => setPreviewItem(null)} aria-label="닫기">×</button>
            </div>
            <div className="v3-modal-media-body">
              <ProtectedAssetPreview src={`/api/files/${previewItem.assetId}`} isVideo={!previewIsImage} alt={previewItem.fileName} />
            </div>
            <div className="v3-modal-media-actions">
              <button className="v3-secondary-button" type="button" onClick={() => onDownload(previewItem)}>다운로드</button>
            </div>
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}
