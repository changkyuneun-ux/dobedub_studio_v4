import { useEffect, useState } from "react";
import {
  HealthResponse,
  HistoryItem,
  AssetItem,
  CollectionSummary,
  CollectionDetail,
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
import { positivePromptEntries } from "../helpers/prompts";
import {
  historyInputImages,
  historyOutputAsset
} from "../helpers/workflow";
import { shellNavigate } from "../helpers/navigation";
import {
  useProtectedAssetUrl,
  ProtectedImage
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
//   응답에 평가 집계가 없다. Run 상세(3f/3c, 다음 작업)에서 실제 값을 붙인다.
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
  onSelect,
  onPageChange,
  onPageSizeChange,
  onDownload,
  onRework,
  onOpenDetail,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
  canRework,
  canDelete
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
  onSelect: (item: HistoryItem) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: 20 | 50) => void;
  onDownload: (item: HistoryItem) => void;
  onRework: (item: HistoryItem) => void;
  onOpenDetail: (item: HistoryItem) => void;
  onRequestDelete: (item: HistoryItem) => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  canRework: boolean;
  canDelete: boolean;
}) {
  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "failed">("all");
  const filteredHistory = history.filter((item) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "completed") return isSuccessStatus(item.status);
    if (statusFilter === "failed") return !isSuccessStatus(item.status) && Boolean(item.status);
    return true;
  });
  const selectedItem = history.find((item) => item.taskId === selectedTaskId) || history[0] || null;
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);
  const completedCount = history.filter((item) => isSuccessStatus(item.status)).length;
  const failedCount = history.filter((item) => !isSuccessStatus(item.status) && item.status).length;

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
            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>워크플로</span><strong>{selectedItem.workflowName || selectedItem.workflow || selectedItem.workflowId || "-"} · {selectedItem.segmentCount || selectedItem.segments?.length || 1} seg</strong></div>
              <div className="v3-summary-row"><span>실행자 · 시각</span><strong>{selectedItem.workerName || selectedItem.user?.name || "-"} · {formatTimestamp(selectedItem.timestamp).replace("\n", " ")}</strong></div>
              <div className="v3-summary-row"><span>결과물</span><strong>{(selectedItem.outputAssets || []).length || (selectedItem.outputUrl ? 1 : 0)}건</strong></div>
            </div>
            <div className="v3-inline-actions">
              <button className="v3-primary-button v3-flex-button" type="button" onClick={() => onOpenDetail(selectedItem)}>Run 상세 열기</button>
            </div>
            <div className="v3-inline-actions">
              <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onDownload(selectedItem)}>Final 다운로드</button>
              {canRework ? <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onRework(selectedItem)}>재작업</button> : null}
            </div>
            <p className="v3-muted-text">프롬프트 · 구성값 · 평가 · 로그는 상세 화면에서 확인합니다</p>
          </>
        ) : (
          <p className="v3-muted-text">왼쪽 목록에서 작업을 선택하세요.</p>
        )
      }
    >
      <div className="v3-card">
        <div className="v3-review-table-head" style={{ gridTemplateColumns: "78px minmax(0,1fr) 84px 84px 56px" }}>
          <span>RUN</span><span>WORKFLOW · 프롬프트</span><span>세그먼트</span><span>상태</span><span style={{ textAlign: "right" }}>삭제</span>
        </div>
        {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {!loading && !filteredHistory.length ? <p className="v3-muted-text" style={{ padding: 16 }}>표시할 작업이 없습니다.</p> : null}
        {filteredHistory.map((item) => {
          const isSelected = item.taskId === selectedTaskId;
          const promptSnippet = positivePromptEntries(item)[0]?.text || item.positivePrompt || item.prompt || "-";
          return (
            <div
              key={item.taskId}
              className={`v3-review-table-row v3-history-row ${isSelected ? "is-selected" : ""}`}
              style={{ gridTemplateColumns: "78px minmax(0,1fr) 84px 84px 56px", cursor: "pointer" }}
              onClick={() => onSelect(item)}
            >
              <span className="v3-review-seg-name">#{item.taskId.slice(0, 8)}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 12.5 }}>{item.workflowName || item.workflow || item.workflowId || "-"}</div>
                <div className="v3-review-prompt">{promptSnippet}</div>
              </div>
              <span className="v3-review-config">{item.segmentCount || item.segments?.length || 1}</span>
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

// E-03 · 3f(완료)/3c(실패) "Run 상세" — design_handoff_dobedub_v3/3 Review.dc.html의
// 두 화면을 하나의 컴포넌트로 합쳤다. 완료/실패는 API가 이미 같은 HistoryItem.status로
// 구분해 주므로 화면을 둘로 쪼개지 않고 내부에서 분기한다. 평가 저장은 B-02 로직
// (savePromptReview → task_prompts, savePromptFeedback → prompt_feedback)을 그대로
// 재사용한다.
//
// 설계 원본과 다르게 뺀 것:
// - 3c의 "SEG 02 frames 81로 낮추고 재실행" · "80GB GPU로 재시도" — 오류를
//   segment/node 단위로 구조화해 돌려주는 API가 없고, GPU 프로필을 선택해 재시도하는
//   기능도 없다. 실제로 가능한 것은 "전체 재실행"(applyHistoryRework + 재제출)뿐이라
//   그것만 남겼다.
// - 3c의 ERROR TRACE(payload snapshot, node #, notification sent 로그) — HistoryItem에
//   없는 정보다. latestJob이 아닌 과거 항목이라 상세 로그 자체가 서버에 없다. 있는
//   값(item.status, 실패 시점 메시지가 있으면 그것)만 보여준다.
// - Final 파일 크기(MB)·해상도 — OutputAsset에 없는 필드다.
// - "관리자에게 보고" · "전체 로그 다운로드" — 대응하는 기능이 없다.
export function Create3RunDetailScreen({
  user,
  health,
  item,
  history,
  promptReviewItems,
  promptReviewLoading,
  promptReviewNotice,
  onSelectRun,
  onSavePromptReview,
  onSavePromptFeedback,
  onDownload,
  onRework,
  onBackToList,
  onGoTo,
  canRework,
  canReview,
  canGiveFeedback
}: {
  user: User | null;
  health: HealthResponse | null;
  item: HistoryItem | null;
  history: HistoryItem[];
  promptReviewItems: TaskPromptItem[];
  promptReviewLoading: boolean;
  promptReviewNotice: string;
  onSelectRun: (item: HistoryItem) => void;
  onSavePromptReview: (segmentIndex: number, payload: Record<string, unknown>) => void;
  onSavePromptFeedback: (outputId: string, payload: { rating?: number; notes?: string }) => void;
  onDownload: (item: HistoryItem) => void;
  onRework: (item: HistoryItem) => void;
  onBackToList: () => void;
  onGoTo: (route: StudioRoute) => void;
  canRework: boolean;
  canReview: boolean;
  canGiveFeedback: boolean;
}) {
  if (!item) {
    return (
      <AppShell user={user} area="generate" activeItem="taskHistory" onNavigate={(key) => shellNavigate(key, onGoTo)} headerTitle="Run 상세">
        <p className="v3-muted-text">선택된 작업이 없습니다. <button className="v3-text-link-button" type="button" onClick={onBackToList}>작업 이력으로</button></p>
      </AppShell>
    );
  }
  const isFailed = !isSuccessStatus(item.status) && Boolean(item.status);
  const output = historyOutputAsset(item);
  const outputMediaUrl = useProtectedAssetUrl(output?.downloadUrl || output?.url || item.outputUrl || "");
  const inputImages = historyInputImages(item);
  const otherRuns = history.filter((run) => run.taskId !== item.taskId).slice(0, 6);

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="taskHistory"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow={<><a className="v3-text-link-button" style={{ padding: 0 }} onClick={onBackToList}>← Task History</a> · RUN #{item.taskId.slice(0, 8)} · {item.workflowName || item.workflow || item.workflowId}</>}
      headerTitle="Run 상세"
      headerActions={
        <>
          <span className={`v3-run-status-chip ${isFailed ? "is-failed" : ""}`}>
            <span className="v3-run-status-dot" />
            {isFailed ? "FAILED" : (item.status || "COMPLETED").toUpperCase()}
          </span>
          {isFailed ? (
            <button className="v3-primary-button" type="button" disabled={!canRework} onClick={() => onRework(item)}>전체 재실행</button>
          ) : (
            <button className="v3-primary-button" type="button" onClick={() => onDownload(item)}>Final 다운로드</button>
          )}
        </>
      }
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>{isFailed ? "실패 목록에서 이동" : "완료 목록에서 이동"}</div>
          {otherRuns.map((run) => (
            <button key={run.taskId} type="button" className="v3-segment-nav-item" onClick={() => onSelectRun(run)}>
              <div className="v3-segment-nav-head">
                <span>#{run.taskId.slice(0, 8)}</span>
                <span>{formatTimestamp(run.timestamp).split("\n")[0]}</span>
              </div>
            </button>
          ))}
        </div>
      }
      rightPanel={
        <>
          <div className="v3-panel-title">Run 정보</div>
          <div className="v3-summary-card">
            <div className="v3-summary-row"><span>Workflow</span><strong>{item.workflowName || item.workflow || item.workflowId || "-"}</strong></div>
            <div className="v3-summary-row"><span>Segments</span><strong>{item.segmentCount || item.segments?.length || 1}</strong></div>
            <div className="v3-summary-row"><span>실행자</span><strong>{item.workerName || item.user?.name || "-"}</strong></div>
            <div className="v3-summary-row"><span>Seed</span><strong>{item.generationSeed || item.seed || "-"}</strong></div>
          </div>
          {isFailed ? (
            <div className="v3-summary-card">
              <div className="v3-label">평가 &amp; 재사용 등록</div>
              <p className="v3-muted-text">완료된 Run에서만 가능합니다. 이 작업은 결과물이 없어 평가 대상이 아닙니다.</p>
            </div>
          ) : null}
          <div className="v3-inline-actions">
            {canRework ? <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onRework(item)}>{isFailed ? "설정만 불러와 수정" : "이 설정으로 새 Run"}</button> : null}
          </div>
        </>
      }
    >
      {isFailed ? (
        <div className="v3-card v3-failure-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">오류</div>
          </div>
          <p className="v3-failure-message">이 작업은 COMPLETED에 도달하지 못했습니다. 결과물이 저장되지 않았고, 세그먼트 설정은 그대로 보존되어 있습니다. 부분 재실행은 지원하지 않으며, 재시도하려면 전체 세그먼트를 다시 제출해야 합니다.</p>
        </div>
      ) : (
        <div className="v3-card v3-result-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">
              <span>Final 병합본</span>
              <span className="v3-status-badge is-ready">최종 출력</span>
            </div>
          </div>
          {outputMediaUrl ? (
            <video className="v3-result-video" src={outputMediaUrl} controls playsInline preload="metadata" />
          ) : (
            <p className="v3-muted-text" style={{ padding: 16 }}>생성된 MP4 파일이 없습니다.</p>
          )}
          <div className="v3-result-footer">
            <span>File: {output?.fileName || item.outputFile || "-"}</span>
            <button className="v3-primary-button" type="button" onClick={() => onDownload(item)}>Download MP4</button>
          </div>
        </div>
      )}

      <div className="v3-card">
        <div className="v3-card-header">
          <div className="v3-card-header-title">Input Images</div>
        </div>
        <div className="v3-segment-output-grid" style={{ padding: "13px 16px" }}>
          {inputImages.length ? inputImages.map((image) => (
            <div className="v3-kf-thumb" key={`${image.index}-${image.assetId}`} style={{ width: "auto", height: 72 }}>
              {image.assetId ? <ProtectedImage src={`/api/files/${image.assetId}`} alt={image.fileName || `Input ${image.index}`} /> : <span>KF {image.index}</span>}
            </div>
          )) : <p className="v3-muted-text">저장된 입력 이미지가 없습니다.</p>}
        </div>
      </div>

      {!isFailed && canReview ? (
        <div className="v3-card">
          <div className="v3-card-header">
            <div className="v3-card-header-title">평가 &amp; 재사용 등록</div>
            <span className="v3-card-header-meta">{promptReviewItems.length} segment(s)</span>
          </div>
          {promptReviewNotice ? <p className="v3-inline-notice" style={{ padding: "0 16px" }}>{promptReviewNotice}</p> : null}
          {promptReviewLoading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
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
            {!promptReviewLoading && !promptReviewItems.length ? <p className="v3-muted-text" style={{ padding: 16 }}>저장된 작업 프롬프트가 없습니다.</p> : null}
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
  const gridColumns = "180px minmax(0,1fr) 160px 70px 150px 110px";

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
      <div className="v3-card">
        <div className="v3-review-table-head" style={{ gridTemplateColumns: gridColumns }}>
          <span>워크플로 · 세그먼트</span><span>프롬프트</span><span>사유</span><span>Rating</span><span>Task ID · Model</span><span style={{ textAlign: "right" }}>적용</span>
        </div>
        {loading ? <p className="v3-muted-text" style={{ padding: 16 }}>불러오는 중입니다...</p> : null}
        {!loading && !items.length ? (
          <p className="v3-muted-text" style={{ padding: 16 }}>재사용 가능으로 등록된 프롬프트가 없습니다. Task History의 Run 상세에서 평가·재사용 등록을 먼저 진행하세요.</p>
        ) : null}
        {!loading && items.map((prompt) => {
          const reasons = reviewReasons(prompt);
          return (
            <div className="v3-review-table-row" style={{ gridTemplateColumns: gridColumns }} key={prompt.id}>
              <span className="v3-review-seg-name">{prompt.workflowId} · Segment {prompt.segmentIndex}</span>
              <span
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={prompt.positivePrompt || "-"}
              >
                {prompt.positivePrompt || "-"}
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
              <span>
                <span className="v3-status-badge is-ready">{prompt.qualityRating || "-"}</span>
              </span>
              <span style={{ fontSize: 11.5 }}>
                #{prompt.taskId.slice(0, 8)}<br />
                <span className="v3-muted-text">{prompt.modelName || prompt.modelProfileId || "-"}</span>
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

// E-03 · 5a "자산" — design_handoff_dobedub_v3/3 Review.dc.html의 자산 그리드
// 화면. A-01(`GET /api/assets`)이 이제 실제로 존재해 이 화면을 만들 수 있게 됐다.
//
// 설계 원본과 다르게 뺀 것 — 전부 대응 백엔드가 없어서 뺐다(가짜 데이터 금지 원칙):
// - 컬렉션(5c, "가을 캠페인" 등 사이드바 그룹) — A-02(컬렉션 테이블/API) 자체가
//   저장소에 전혀 없음. "컬렉션에 추가" 버튼, 컬렉션 사이드바 트리 전부 제외.
// - 태그(#가을 #야외 등), 공개 범위(PRIVATE/SHARED 토글) — `assets` 테이블에 대응
//   컬럼이 없음(`asset_type`·`size_bytes`·`metadata_json`·`created_at`뿐).
// - 저장 용량 진행 바("184/500 GB") — 총 한도 값을 내려주는 API가 없음.
// - "업로드" 버튼(설계는 이 화면에서 바로 업로드) — 업로드는 `2a` 키프레임
//   슬롯에서만 발생하는 것이 현재 흐름이라 여기 별도 업로드 진입점을 만들지 않음.
// - 정렬 드롭다운("최근 업로드순" 외 옵션) — API가 `created_at desc` 고정 정렬만
//   지원. 옵션이 하나뿐이라 드롭다운 자체를 생략.
// 대신 있는 것 — 실제 `task_output_assets` 조인 결과인 taskId/outputRole/workflowId는
// 있으면 보여주고, 없으면(업로드만 되고 어떤 Run 출력에도 안 쓰인 자산) "미연결"로
// 표기한다.
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
  typeFilter,
  selectedAssetId,
  onSelect,
  onTypeFilterChange,
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
  typeFilter: string;
  selectedAssetId: string;
  onSelect: (item: AssetItem) => void;
  onTypeFilterChange: (type: string) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: 20 | 50) => void;
  onDownload: (item: AssetItem) => void;
}) {
  // 서버가 내려준 이번 페이지 항목들의 실제 asset_type만 필터 후보로 쓴다 —
  // 설계 mock의 "키프레임/세그먼트 영상/Final 영상" 같은 고정 분류가 실제 코드의
  // asset_type 값과 정확히 일치한다는 보장이 없어, 있는 값만으로 필터를 구성한다.
  const typesInPage = Array.from(new Set(items.map((item) => item.type).filter(Boolean)));
  const selectedItem = items.find((item) => item.assetId === selectedAssetId) || items[0] || null;
  const pageStart = total ? (page - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min(total, page * pageSize);

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="assets"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="ASSETS"
      headerTitle={`전체 ${total}개`}
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>종류</div>
          <button
            type="button"
            className={`v3-segment-nav-item ${!typeFilter ? "is-active" : ""}`}
            onClick={() => onTypeFilterChange("")}
          >
            <div className="v3-segment-nav-head"><span>전체</span></div>
          </button>
          {typesInPage.map((type) => (
            <button
              key={type}
              type="button"
              className={`v3-segment-nav-item ${typeFilter === type ? "is-active" : ""}`}
              onClick={() => onTypeFilterChange(type)}
            >
              <div className="v3-segment-nav-head"><span>{type}</span></div>
            </button>
          ))}
        </div>
      }
      sidebarFooter={
        <div className="v3-muted-text">
          <button className="v3-text-link-button" type="button" onClick={() => onGoTo("review.collections")}>컬렉션 보기 →</button>
          <p style={{ margin: "6px 0 0" }}>한 페이지 {pageSize}건 · 태그·공개범위는 아직 지원하지 않습니다</p>
        </div>
      }
      rightPanel={
        selectedItem ? (
          <>
            <div className="v3-panel-title-row">
              <div className="v3-panel-title">{selectedItem.fileName}</div>
              <span className="v3-status-badge is-ready">{selectedItem.type || "-"}</span>
            </div>
            <div className="v3-summary-card">
              <div className="v3-summary-row"><span>크기</span><strong>{(selectedItem.sizeBytes / 1024).toFixed(1)} KB</strong></div>
              <div className="v3-summary-row"><span>MIME</span><strong>{selectedItem.mimeType || "-"}</strong></div>
              <div className="v3-summary-row"><span>생성일</span><strong>{selectedItem.createdAt || "-"}</strong></div>
              <div className="v3-summary-row"><span>연결된 Run</span><strong>{selectedItem.taskId ? `#${selectedItem.taskId.slice(0, 8)} · ${selectedItem.outputRole || "-"}` : "미연결"}</strong></div>
              {selectedItem.workflowId ? <div className="v3-summary-row"><span>워크플로</span><strong>{selectedItem.workflowId}</strong></div> : null}
            </div>
            <div className="v3-inline-actions">
              <button className="v3-primary-button v3-flex-button" type="button" onClick={() => onDownload(selectedItem)}>다운로드</button>
              {selectedItem.taskId ? (
                <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onGoTo("review.runDetail")}>Run 상세 보기</button>
              ) : null}
            </div>
          </>
        ) : (
          <p className="v3-muted-text">왼쪽 목록에서 자산을 선택하세요.</p>
        )
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      <div className="v3-reuse-grid">
        {loading ? <p className="v3-muted-text">불러오는 중입니다...</p> : null}
        {!loading && !items.length ? <p className="v3-muted-text">표시할 자산이 없습니다.</p> : null}
        {items.map((item) => {
          const isSelected = item.assetId === selectedAssetId;
          return (
            <div
              key={item.assetId}
              className={`v3-card v3-reuse-card ${isSelected ? "is-selected" : ""}`}
              style={{ cursor: "pointer" }}
              onClick={() => onSelect(item)}
            >
              <div className="v3-card-header">
                <div className="v3-card-header-title">{item.type || "asset"}</div>
                <span className="v3-status-badge is-ready">{(item.sizeBytes / 1024).toFixed(0)} KB</span>
              </div>
              <div className="v3-reuse-body">
                <div style={{ fontWeight: 600, fontSize: 12.5, wordBreak: "break-all" }}>{item.fileName}</div>
                <div className="v3-summary-row"><span>연결</span><strong>{item.taskId ? `#${item.taskId.slice(0, 8)} · ${item.outputRole || "-"}` : "미연결"}</strong></div>
                <div className="v3-summary-row"><span>생성일</span><strong>{item.createdAt || "-"}</strong></div>
              </div>
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
    </AppShell>
  );
}

// A-02 · 5c 자산 컬렉션 — design_handoff_dobedub_v3/3 Review.dc.html의 5c.
// 사이드바에서 컬렉션을 고르거나 새로 만들고, 본문에 그 컬렉션에 담긴 자산을,
// 우측 패널에서 최근 자산을 담는다.
// 설계 원본과 다르게 뺀 것(더미 금지 - 대응 백엔드 컬럼/테이블 없음):
// - 자산 태그, 공개 범위(PRIVATE/SHARED) 필터/뱃지 - 5a와 동일하게 assets 테이블에
//   해당 컬럼이 없다.
// - 검색·정렬(담은 순 등)·그리드/목록 전환 - 목록 정렬은 서버가 sort_order 순으로만
//   내려주며 클라 정렬/검색 파라미터를 받지 않는다.
// - 소유자 표기는 컬렉션의 createdBy(로그인 id)만 있고 표시명 매핑이 없어 id 그대로.
export function Create5cScreen({
  user,
  onGoTo,
  collections,
  selectedCollectionId,
  detail,
  loading,
  notice,
  createName,
  recentAssets,
  onSelectCollection,
  onCreateNameChange,
  onCreateCollection,
  onAddAsset,
  onDownload
}: {
  user: User | null;
  onGoTo: (route: StudioRoute) => void;
  collections: CollectionSummary[];
  selectedCollectionId: number | null;
  detail: CollectionDetail | null;
  loading: boolean;
  notice: string;
  createName: string;
  recentAssets: AssetItem[];
  onSelectCollection: (id: number) => void;
  onCreateNameChange: (value: string) => void;
  onCreateCollection: () => void;
  onAddAsset: (assetId: string) => void;
  onDownload: (item: AssetItem) => void;
}) {
  const selected = collections.find((c) => c.id === selectedCollectionId) || null;
  const items = detail && detail.id === selectedCollectionId ? detail.items : [];
  const itemAssetIds = new Set(items.map((item) => item.assetId));

  return (
    <AppShell
      user={user}
      area="generate"
      activeItem="collections"
      onNavigate={(key) => shellNavigate(key, onGoTo)}
      headerEyebrow="ASSETS · 컬렉션"
      headerTitle={selected ? selected.name : "컬렉션"}
      headerActions={<button className="v3-secondary-button" type="button" onClick={() => onGoTo("review.assets")}>자산 목록으로</button>}
      sidebarExtra={
        <div className="v3-step-tracker">
          <div className="v3-label" style={{ padding: "0 10px 4px" }}>컬렉션 · {collections.length}</div>
          {loading && !collections.length ? <p className="v3-muted-text" style={{ padding: "4px 10px" }}>불러오는 중입니다...</p> : null}
          {!loading && !collections.length ? <p className="v3-muted-text" style={{ padding: "4px 10px" }}>컬렉션이 없습니다. 아래에서 만드세요.</p> : null}
          {collections.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`v3-segment-nav-item ${selectedCollectionId === c.id ? "is-active" : ""}`}
              onClick={() => onSelectCollection(c.id)}
            >
              <div className="v3-segment-nav-head"><span>{c.name}</span><span>{c.itemCount}</span></div>
            </button>
          ))}
          <div className="v3-collection-create">
            <input
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
          </div>
        </div>
      }
      rightPanel={
        selected ? (
          <>
            <div className="v3-panel-title">자산 추가</div>
            <p className="v3-muted-text">최근 자산을 "{selected.name}"에 담습니다.</p>
            {recentAssets.length ? recentAssets.map((asset) => {
              const added = itemAssetIds.has(asset.assetId);
              return (
                <div className="v3-summary-card" key={asset.assetId}>
                  <div style={{ fontWeight: 600, fontSize: 12, wordBreak: "break-all" }}>{asset.fileName}</div>
                  <div className="v3-summary-row"><span>연결</span><strong>{asset.taskId ? `#${asset.taskId.slice(0, 8)}` : "미연결"}</strong></div>
                  <button className="v3-secondary-button v3-flex-button" type="button" disabled={added} onClick={() => onAddAsset(asset.assetId)}>
                    {added ? "담김" : "담기"}
                  </button>
                </div>
              );
            }) : <p className="v3-muted-text">담을 자산이 없습니다.</p>}
          </>
        ) : <p className="v3-muted-text">왼쪽에서 컬렉션을 선택하거나 새로 만드세요.</p>
      }
    >
      {notice ? <p className="v3-inline-notice">{notice}</p> : null}
      {loading && !detail ? (
        <p className="v3-muted-text">불러오는 중입니다...</p>
      ) : !selected ? (
        <p className="v3-muted-text">컬렉션을 선택하거나 새로 만드세요.</p>
      ) : !items.length ? (
        <p className="v3-muted-text">이 컬렉션에 담긴 자산이 없습니다. 오른쪽 패널에서 자산을 담아보세요.</p>
      ) : (
        <div className="v3-reuse-grid">
          {items.map((item) => (
            <div className="v3-card v3-reuse-card" key={item.assetId}>
              <div className="v3-card-header">
                <div className="v3-card-header-title">{item.type || "asset"}</div>
                <span className="v3-status-badge is-ready">#{item.sortOrder}</span>
              </div>
              <div className="v3-reuse-body">
                <div style={{ fontWeight: 600, fontSize: 12.5, wordBreak: "break-all" }}>{item.fileName}</div>
                <div className="v3-summary-row"><span>연결</span><strong>{item.taskId ? `#${item.taskId.slice(0, 8)} · ${item.outputRole || "-"}` : "미연결"}</strong></div>
                <div className="v3-summary-row"><span>생성일</span><strong>{item.createdAt || "-"}</strong></div>
                <button className="v3-secondary-button v3-flex-button" type="button" onClick={() => onDownload(item)}>다운로드</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
}
