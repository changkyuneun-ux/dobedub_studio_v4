from __future__ import annotations

from pathlib import Path


def test_prompt_management_sends_workflow_scoped_image_pairs() -> None:
    source = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")

    assert "createImagePromptBatch" in source
    assert "workflowId" in source
    assert "assetId: upload.assetId" in source
    assert "requestedFrames: upload.requestedFrames" in source
    assert "negativePrompt" in source
    assert "retryImagePromptDraft" in source


def test_prompt_management_uses_workflow_default_negative_for_blank_workspace() -> None:
    source = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")

    assert "current.trim()" in source
    assert "nextSchema.segments?.[0]?.defaultNegativePrompt" in source
    assert "setNegativePrompt(\"\")" in source


def test_runpod_request_management_only_enqueues_selected_ready_drafts() -> None:
    source = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")

    assert "runpodRequestQueue({ workerId:" in source
    assert "item.canSubmit" in source
    assert '"kind": "PROMPT_DRAFT"' in Path("backend/app/services/runpod_request_batch_service.py").read_text(encoding="utf-8")
    assert "createRunpodRequestBatch" in source
    assert "promptDraftId: draft.promptDraftId!" in source
    assert "groupedByWorker" in source
    assert "runpodConnection" in source
    assert "다중 keyframe 다음 단계" in source


def test_request_management_exposes_worker_and_workflow_filters_to_the_operator() -> None:
    source = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")

    assert "작업자" in source
    assert "전체 작업자" in source
    assert "워크플로우" in source
    assert "workflowFilter" in source
    assert "PARTIAL_FAILED" in source


def test_runpod_request_filters_start_with_all_for_managers() -> None:
    source = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")

    assert 'const ALL_WORKERS_FILTER = "all";' in source
    assert 'const ALL_WORKFLOWS_FILTER = "";' in source
    assert "canManageRequests ? ALL_WORKERS_FILTER : user.id" in source
    assert "useState(ALL_WORKFLOWS_FILTER)" in source


def test_runpod_request_filters_do_not_block_selection_or_submission_for_all_workers() -> None:
    source = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")

    assert "GROK CONFIGURED" in source
    assert 'disabled={!selected.length || busy}' in source
    assert 'disabled={!supported || !editable}' in source
    assert "groupedByWorker" in source
    assert "작업자별 요청 묶음" in source


def test_prompt_management_can_delete_unsubmitted_uploads() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")

    assert "deleteUnsubmittedUpload" in client
    assert "deleteUpload" in screen
    assert "업로드 이미지 삭제" in screen
    prompt_mapping = screen.split("Image Prompt Mapping", 1)[1]
    assert "deleteImagePromptDraft" not in prompt_mapping
    assert "deletePromptRow" not in prompt_mapping
    assert "프롬프트 항목 삭제" not in prompt_mapping


def test_prompt_management_preserves_upload_targets_when_workflow_changes() -> None:
    source = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")
    select_workflow = source.split("function selectWorkflow(id: string)", 1)[1].split("async function refreshActivePromptGenerationBatches", 1)[0]

    assert "setWorkflowId(id)" in select_workflow
    assert "setUploads([])" not in select_workflow
    assert "setDrafts({})" in select_workflow
    assert "setActiveBatchPage(1)" in select_workflow


def test_batch_management_preserves_zip_and_cut_targets_when_workflow_changes() -> None:
    source = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")
    workflow_select = source.split("<select value={workflowId}", 1)[1].split("</select>", 1)[0]

    assert "setWorkflowId(event.target.value)" in workflow_select
    assert "setSelectedZipFile(null)" not in workflow_select
    assert "setWebtoonCutInput(null)" not in workflow_select


def test_batch_history_labels_prompt_completion_and_uses_prompt_success_as_video_denominator() -> None:
    source = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")
    history_table = source.split("v3-batch-history-table", 1)[1].split("v3-batch-history-pagination", 1)[0]

    assert "<th>프롬프트 완료</th>" in history_table
    assert "<th>이미지 완료</th>" not in history_table
    assert "{job.promptCompletedCount} / {job.totalImages}" in history_table
    assert "{job.videoCompletedCount} / {job.promptCompletedCount}" in history_table
    assert "{job.videoCompletedCount} / {job.totalImages}" not in history_table


def test_batch_history_status_ignores_failures_and_uses_only_lifecycle_states() -> None:
    source = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")
    result_label = source.split("function batchResultLabel", 1)[1].split("function batchResultTone", 1)[0]
    result_tone = source.split("function batchResultTone", 1)[1].split("function metricPill", 1)[0]

    assert "failedCount" not in result_label
    assert "부분 실패" not in result_label
    assert "(job.cancelledCount || 0) > 0" in result_label
    assert 'return "취소";' in result_label
    assert 'return normalized === "COMPLETE" ? "완료" : "진행 중";' in result_label
    assert "failedCount" not in result_tone
    assert 'return normalized === "COMPLETE" ? "complete" : "incomplete";' in result_tone


def test_prompt_management_submits_canonical_selected_workflow_id() -> None:
    source = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")
    generate_all = source.split("async function generateAll()", 1)[1].split("function updateVisibleDraft", 1)[0]

    assert "const targetWorkflowId = selectedWorkflow?.id || \"\";" in generate_all
    assert "if (!targetWorkflowId || !uploads.length) return;" in generate_all
    assert "workflowId: targetWorkflowId" in generate_all
    assert "workflowId," not in generate_all


def test_prompt_management_displays_exact_workflow_id_to_avoid_duplicate_label_confusion() -> None:
    source = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")
    workflow_card = source.split("v3-prompt-workflow-option", 1)[1].split("v3-prompt-workflow-callout", 1)[0]

    assert "<small>{workflow.id} · {workflow.keyframeCount || 1} kf" in workflow_card


def test_prompt_history_uses_worker_names_without_worker_generation_stats() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "createdByName?: string | null" in client
    assert "setWorkerStats(response.workerStats" not in source
    assert "사용자별 생성 통계" not in source
    assert "item.createdByName || item.createdBy" in source


def test_prompt_and_runpod_management_follow_the_desktop_operational_layout() -> None:
    prompt_screen = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")
    runpod_screen = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")

    assert "Prompt Workflow" in prompt_screen
    assert "Image Upload" in prompt_screen
    assert "Prompt Generation Dashboard" in prompt_screen
    assert "Image Prompt Mapping" in prompt_screen
    assert "Built-in Negative Prompt" in prompt_screen
    assert "onDrop" in prompt_screen

    assert "RunPod Progress Dashboard" in runpod_screen
    assert "Incomplete RunPod Requests" in runpod_screen
    assert "Request Handling" in runpod_screen
    assert "RunPod 요청" in runpod_screen
    assert "selected.length" in runpod_screen
    assert "updateImagePromptDraft" in runpod_screen


def test_batch_job_creation_exposes_editable_negative_prompt_and_submits_it() -> None:
    screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "Built-in Negative Prompt" in screen
    assert "batchNegativePrompt" in screen
    assert "setBatchNegativePrompt" in screen
    assert "negativePrompt: batchNegativePrompt" in screen
    assert 'formData.set("negativePrompt"' in client
    assert "negativePrompt?: string" in client


def test_batch_job_creation_requires_workflow_grok_instruction_status() -> None:
    screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")

    assert "grokInstructionStatus(workflowId)" in screen
    assert "instructionStatus?.configured" in screen
    assert "지시문 없음" in screen
    assert "활성 프롬프트 지시문이 없습니다" in screen
    assert "관리자 > 프롬프트 생성 지시 관리" in screen
    assert "const batchInputReady = Boolean(selectedZipFile || webtoonCutInput?.items.length);" in screen
    assert "disabled={busy || !batchInputReady || !instructionStatus?.configured}" in screen


def test_task_history_consumes_dedicated_prompt_and_runpod_contracts() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "apiClient.promptHistory({ page, generationStatus: generationFilter, runpodStatus: runpodFilter, batchId: selectedPromptBatchJobId })" in source
    assert "apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId, jobId: runpodJobSearch.trim() })" in source
    # 2026-09-13 식별성 지침: 툴바 → ①조회 조건 카드(드롭다운 overflow 허용) + ②선택 작업 바
    assert "v3-history-step-card is-overflow-visible" in source
    assert "v3-selection-bar" in source
    assert "runpodResponse?.filename" in source
    assert "promptHistory" in source
    assert "runpodHistory" in source
    assert "실행일 시작" not in source
    assert "실행일 종료" not in source
    assert "실행일<input type=\"date\" value={runpodRunDate}" in source
    assert "}, [historyTab, runpodPage, runpodWorkflowFilter, runpodResultFilter, runpodWorkerFilter, runpodRunDate, selectedBatchJobId, runpodJobSearch]);" in source


def test_prompt_history_exposes_batch_id_and_uses_selected_batch_candidate_filter() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")
    prompt_history = source.split("function PromptGrokResponseDetail", 1)[0].split("function PromptGenerationHistory", 1)[1]

    assert "selectedPromptBatchJob" in prompt_history
    assert "promptBatchCandidates" in prompt_history
    assert "apiClient.batchJobCandidates({ query, limit: 10 })" in prompt_history
    assert "batchId: selectedPromptBatchJobId" in prompt_history
    assert "Batch ID / 작업자명 검색" in prompt_history
    assert "<span>No</span><span>작업자</span><span>KST 생성일</span><span>워크플로우</span><span>Batch ID</span><span>이미지</span>" in prompt_history
    assert "item.batchJobId || item.promptBatchId || \"\"" in prompt_history
    assert "v3-prompt-history-batch-id" in prompt_history
    assert "batchId: batchFilter" not in prompt_history
    assert ".v3-prompt-history-batch-id" in css


def test_runpod_history_batch_zip_uses_selected_batch_candidate_not_search_text() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "batchJobCandidates" in client
    assert "selectedBatchJob" in source
    assert "setSelectedBatchJob(null)" in source
    assert "apiClient.batchJobZip(selectedBatchJob.id, selectedRunpodTaskIds)" in source
    assert "disabled={!selectedBatchJob}" in source
    assert "v3-batch-candidate-list" in source
    assert "batchSearchText" in source
    assert "const batchId = runpodBatchFilter.trim()" not in source


def test_runpod_history_supports_selected_bulk_download_and_delete() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "selectedRunpodTaskIds" in source
    assert "선택 다운로드" in source
    assert "선택 삭제" in source
    assert "onRequestBulkDelete" in source
    assert "runpodHistorySelection" in source
    assert "현재 필터 전체 선택" in source
    assert "작업 ID" in source


def test_runpod_history_preview_columns_show_assets_instead_of_generic_view_text() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "<span>입력 이미지</span><span>생성 영상</span>" in source
    assert "<span>입력 View</span><span>결과 View</span>" not in source
    assert "v3-runpod-input-thumb-button" in source
    assert "<ProtectedImage src={`/api/files/${input.assetId}`}" in source
    assert "v3-runpod-output-link" in source
    assert "`${inputFileName} -> ${outputFileName}`" in source
    assert "setAssetPreview({ src: `/api/files/${input.assetId}`, isVideo: false" in source
    assert "setAssetPreview({ src: resultUrl, isVideo: true" in source
    assert ".v3-runpod-input-thumb-button" in css
    assert ".v3-runpod-output-link" in css


def test_runpod_history_shows_video_and_generation_times_before_download() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    table = source.split('<div className="v3-review-table-head v3-history-head" style={{ gridTemplateColumns: RUNPOD_HISTORY_GRID }}>', 1)[1].split("{selectedRunpodPromptItem ?", 1)[0]

    assert "durationSeconds?: number" in client
    assert "function formatRunpodHistoryTime" in source
    assert 'return `${minutes}:${seconds}`;' in source
    assert "<span>작업자</span><span>실행일</span>" in table
    assert "<span>Batch ID</span><span>Prompt ID</span><span>Studio Task</span><span>RunPod Job ID</span><span>결과</span>" in table
    assert "formatRunpodHistoryDate(item.timestampUtc || item.timestamp)" in table
    assert "<span>생성 영상</span><span>영상길이</span><span>생성시간</span><span>다운로드</span>" in table
    assert "{formatRunpodHistoryTime(item.durationSeconds)}</span>\n              <span>{formatRunpodHistoryTime(item.runpodResponse?.executionSeconds ?? item.elapsedSeconds)}</span>\n              <span>" in table


def test_runpod_history_prompt_modal_retry_and_column_contract() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    runpod_history = source.split("function RunpodHistoryPromptDetail", 1)[0] if "function RunpodHistoryPromptDetail" in source else source

    assert "reworkHistoryItem: (taskId: string)" in client
    assert "/api/history/${encodeURIComponent(taskId)}/rework" in client
    assert "regenerateHistoryItem: (taskId: string)" not in client
    assert "selectedRunpodPromptItem" in source
    assert "RunpodHistoryPromptDetail" in source
    assert "프롬프트 내용" in source
    assert "positivePromptEntries(item)" in source
    assert "negativePromptEntries(item)" in source
    assert "setSelectedRunpodPromptItem(item)" in source
    assert "reworkingRunpodTaskIds" in source
    assert "runpodRetryTaskIds" not in source
    assert "runpodRetryStatuses" not in source
    assert "runpodResultStatusLabel(item)" in source
    assert "const resultStatusLabel = runpodResultStatusLabel(item)" in source
    assert "apiClient.jobStatus(retryTaskId)" not in source
    assert "apiClient.reworkHistoryItem(item.taskId)" in source
    assert "재작업" in source
    assert "재생성" not in runpod_history
    assert "Batch ID / 작업자명 검색" in source
    assert "<span>ComfyUI Response</span>" not in runpod_history
    assert "v3-runpod-response-cell" not in runpod_history


def test_runpod_history_replay_actions_stay_on_runpod_history() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    toolbar = source.split('className="v3-selection-bar"', 1)[1].split('<div className="v3-card v3-runpod-history-table">', 1)[0]

    assert "reworkRunpodHistoryItems" in client
    assert "전체 재실행" not in source
    assert "선택 재실행" in toolbar
    assert "조회 오류 재실행" in toolbar
    assert "reworkSelectedRunpodItems" in source
    assert "reworkFilteredRunpodItems" in source
    assert "void reworkRunpodHistoryItem(item)" in source
    assert "onClick={() => onRework(selectedItem)}" not in source


def test_runpod_history_right_panel_shows_filtered_statistics_dashboard() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "runpodHistoryStats" in source
    assert "runpodAppliedFilters" in source
    assert "runpodStatSegments" in source
    assert "stats?: RunpodHistoryStats" in client
    assert "response.stats || EMPTY_RUNPOD_HISTORY_STATS" in source
    assert "filteredHistory.reduce" not in source
    assert "RunPod 조회 통계" in source
    assert "왼쪽 조회 결과 요약" in source  # 2026-09-13 지침 §4: 패널이 무엇에 대한 것인지 헤더로 선언
    assert ") 기준 {runpodHistoryStats.total}건" in source
    assert "총건" in source
    assert "완료" in source
    assert "실패" in source
    assert "취소" in source
    assert "제출대기" in source
    assert "진행" in source
    assert "결과 구성" in source
    assert "적용된 필터" in source
    assert "재실행 기준" in source
    assert "조회 오류 재실행 대상" in source
    assert "진행/제출대기 자동 제외" in source
    assert "RUN #" not in source.split('rightPanel={', 1)[1].split('<div className="v3-scope-tabs"', 1)[0]
    assert ".v3-runpod-stat-bar" in css
    assert ".v3-filter-chip-list" in css


def test_batch_job_creation_uses_zip_upload_studio_confirm_modal_and_five_second_default() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "window.confirm" not in source
    assert "window.alert" not in source
    assert "webkitdirectory" not in source
    assert 'node.setAttribute("directory"' not in source
    assert "apiClient.upload" not in source
    assert "fileToDataUrl" not in source
    assert "createBatchJobFromZip" in client
    assert "FormData" in client
    assert '"/api/batch-jobs/zip"' in client
    assert '"Content-Type": "application/json"' not in client.split("function requestFormJson", 1)[1].split("export const apiClient", 1)[0]
    assert "ZIP 파일 선택" in source
    assert 'accept=".zip,application/zip,application/x-zip-compressed"' in source
    assert "confirmingBatch" in source
    assert "작업 요청 내역 확인" in source
    assert "워크플로우" in source
    assert "ZIP 파일명" in source
    assert "이미지수" not in source
    assert "길이" in source
    assert "진행하시겠습니까?" in source
    assert "setRequestedFrames(DEFAULT_REQUESTED_FRAMES)" in source
    assert "DEFAULT_REQUESTED_FRAMES = 81" in source
    assert "81f · 5초" in source
    assert "161f · 10초" not in source
    assert "개 이미지를 선택했습니다." not in source
    assert "selectedZipFile" in source
    assert "createBatchJobFromZip({" in source
    assert ".v3-batch-confirm-modal" in css


def test_prompt_history_removes_negative_prompt_column() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    prompt_history = source.split("function PromptGrokResponseDetail", 1)[0].split("function PromptGenerationHistory", 1)[1]

    assert "워크플로우 내장 Negative Prompt" not in prompt_history
    assert 'title={item.negativePrompt || ""}' not in prompt_history
    assert "{item.negativePrompt || \"-\"}" not in prompt_history


def test_prompt_history_supports_failed_prompt_repair_and_image_preview() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    prompt_history = source.split("function PromptGrokResponseDetail", 1)[0].split("function PromptGenerationHistory", 1)[1]

    assert "repairImagePromptDraft" in client
    assert "repairFailed: true" in client
    assert "setPreviewItem(item)" in prompt_history
    assert "<ProtectedAssetPreview" in prompt_history
    assert 'canUse(user, "jobs:manage")' in prompt_history
    assert "RunPod ComfyUI 요청 목록" in prompt_history
    assert "저장 및 RunPod 요청" not in prompt_history
    assert "프롬프트 생성</span>" in prompt_history
    assert 'generationLabel = normalizedStatus === "FAILED" || normalizedStatus === "MANUAL_REQUIRED" ? "FAILED"' in prompt_history


def test_prompt_history_allows_successful_prompt_editing_without_runpod_resubmission() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")
    prompt_history = source.split("function PromptGrokResponseDetail", 1)[0].split("function PromptGenerationHistory", 1)[1]

    assert "updateImagePromptDraft(editingItem.draftId" in prompt_history
    assert "const canEditPrompt" in prompt_history
    assert "disabled={!canEditPrompt}" in prompt_history
    assert "저장" in prompt_history
    assert "v3-prompt-edit-modal" in prompt_history
    assert "v3-prompt-edit-textarea" in prompt_history
    assert '<span>Positive Prompt</span><textarea' not in prompt_history
    assert 'const promptTone = normalizedStatus === "FAILED" || normalizedStatus === "MANUAL_REQUIRED" ? "is-failed" : generated ? "is-success" : ""' in prompt_history
    assert ".v3-prompt-edit-modal" in css
    assert "width: min(960px, calc(100vw - 32px))" in css
    assert ".v3-prompt-edit-textarea" in css
    assert ".v3-prompt-history-cell-button.is-success" in css
    assert ".v3-prompt-history-cell-button.is-failed" in css
    assert "text-decoration: none" in css


def test_prompt_history_requeues_edited_prompt_only_after_overwrite_confirmation() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    prompt_history = source.split("function PromptGrokResponseDetail", 1)[0].split("function PromptGenerationHistory", 1)[1]

    assert "requeueRunpodForPromptDraft" in client
    assert "/requeue-runpod" in client
    assert "item.requeueRequired" in prompt_history
    assert "재요청" in prompt_history
    assert "기존 영상이 있는 경우 덮어쓰기가 됩니다. 진행하시겠습니까?" in prompt_history
    assert "window.confirm" in prompt_history


def test_studio_workflow_default_reset_preserves_five_second_generation_length() -> None:
    source = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    reset_block = source.split("async function resetSegmentConfigsToDefaults", 1)[1].split("function copyFirstSegmentConfig", 1)[0]

    assert "normalizeGenerationLengthConfig" in reset_block


def test_runpod_retry_status_updates_result_column_not_download_action() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    download_cell = source.split("const reworkInFlight", 1)[1].split("<span style={{ textAlign: \"right\" }}", 1)[0]

    assert "const resultStatusLabel = runpodResultStatusLabel(item)" in source
    assert '<span className={`v3-status-badge ${resultStatusTone}`}>{resultStatusLabel}</span>' in source
    assert "runpodRetryButtonLabel(item, retryStatus)" not in download_cell
    assert "reworkInFlight" in download_cell
    assert "재작업" in download_cell
    assert "RunPod Queue" not in download_cell
    assert "진행 중" not in download_cell
    assert "제출 대기" not in download_cell


def test_task_history_tables_and_preview_panels_are_responsive() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "const RUNPOD_HISTORY_GRID = \"32px 36px minmax(" in source
    assert "minWidth: 1240" not in source
    assert "grid-template-columns: 42px 76px 98px 130px 112px minmax(190px, 1fr) minmax(170px, .75fr) 82px 96px 58px; min-width: 1230px;" not in css
    assert ".v3-runpod-history-table { min-width: 0; overflow-x: auto; }" in css
    assert ".v3-prompt-history-head, .v3-prompt-history-row" in css
    assert "minmax(0, 1fr)" in css
    assert ".v3-right-panel .v3-result-video-frame { min-width: 0; max-width: 100%; }" in css
    assert ".v3-right-panel .v3-segment-output-grid { grid-template-columns: repeat(auto-fit, minmax(72px, 1fr)); min-width: 0; }" in css
    assert ".v3-asset-preview-modal { max-height: min(80vh, 760px); max-width: min(900px, 90vw); overflow: auto; width: min(760px, calc(100vw - 32px)); }" in css


def test_instruction_admin_scopes_all_document_actions_to_the_selected_workflow() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/adminScreens.tsx").read_text(encoding="utf-8")

    assert "grokInstructions: (workflowId: string)" in client
    assert "?workflowId=${encodeURIComponent(workflowId)}" in client
    assert "deleteGrokInstruction" in client
    assert "apiClient.grokInstructions(selectedWorkflowId)" in screen
    assert "workflowId," in screen
    assert "apiClient.deleteGrokInstruction(selectedId, workflowId)" in screen


def test_instruction_admin_clears_the_editor_and_limits_copy_sources_to_configured_workflows() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/adminScreens.tsx").read_text(encoding="utf-8")

    assert "grokInstructionSourceWorkflows" in client
    assert "setSelectedId(null);" in screen
    assert "setForm(EMPTY_GROK_INSTRUCTION);" in screen
    assert "instructionSourceWorkflowIds.has(workflow.id)" in screen
    assert "<select aria-label=\"Target Workflow\"" in screen


def test_prompt_management_uses_one_aggregate_dashboard_and_paginates_active_batches() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")

    assert "activePromptGenerationBatches" in client
    assert "activePromptGenerationBatches" in screen
    assert "activePromptGenerationBatches(" in screen
    assert "setUploads([]);" in screen
    assert "setDrafts({});" in screen
    assert "PROMPT_BATCH_PROGRESS_PAGE_SIZE = 10" in screen
    assert "activeBatchDashboard" in screen
    assert "paginatedActivePromptGenerationBatches" in screen
    assert "v3-prompt-batch-progress-list" in screen
    assert "v3-prompt-batch-dashboard" in screen
    assert "activePromptGenerationBatches.map((activeBatch) => { const activeItems" not in screen
    assert "promptMappingRows" in screen
    assert "activePromptMappingRows" in screen
    assert "batchId: batch.id" in screen
    assert "promptMappingRows.length" in screen
    assert "is-error" in screen
    assert "promptDisplayStatus" in screen
    assert "promptDisplayStatus(draft?.status || \"WAITING\")" in screen
    assert "void refreshActivePromptGenerationBatches()" in screen


def test_runpod_request_queue_exposes_prompt_batch_identity_without_redundant_navigation() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")

    assert "promptBatchId?: string | null" in client
    assert "Prompt Batch ID" in screen
    assert "Item No." in screen
    assert "draft.promptBatchId" in screen
    assert "onGoTo(\"review.history\")" not in screen


def test_api_client_exposes_s3_upload_presign_and_complete() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "type S3UploadScope" in client
    assert "presignUpload" in client
    assert "\"/api/uploads/presign\"" in client
    assert "completeUpload" in client
    assert "\"/api/uploads/complete\"" in client


def test_runpod_request_queue_uses_fixed_ten_row_pages_and_shared_dashboard_scope() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")
    service = Path("backend/app/services/runpod_request_batch_service.py").read_text(encoding="utf-8")

    assert "runpodRequestQueue" in client
    assert "statusFilter?: string" in client
    assert "runpodRequestDashboard: ()" in client
    assert "const ALL_REQUEST_STATUS_FILTER = \"all\";" in screen
    assert "requestReady" in client
    assert "requestReady" in screen
    assert "pendingSubmit" in client
    assert "pendingSubmit" in screen
    assert "completed" in client
    assert "dashboard.completed" in screen
    assert "REQUEST READY" in screen
    assert "COMPLETED" in screen
    assert "REQUEST WAITING" not in screen
    assert "requestWaiting" not in screen
    assert "statusFilter" in screen
    assert "전체 상태" in screen
    assert "latestLoadRequestRef" in screen
    assert "apiClient.runpodRequestDashboard()" in screen
    assert "apiClient.runpodRequestDashboard({" not in screen
    assert "requestDashboard?.totals.incomplete, requestPage, workerFilter, workflowFilter, statusFilter" in screen
    assert "pageSize: 10" in screen
    assert "페이지당 10건" in screen
    assert "status_filter=status_filter" in service


def test_instruction_copy_source_uses_the_shared_workflow_select_style() -> None:
    screen = Path("frontend/src/screens/adminScreens.tsx").read_text(encoding="utf-8")

    assert "v3-grok-workflow-select-control" in screen


def test_generate_sidebar_labels_do_not_include_unit_task_suffix() -> None:
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")

    assert 'label: "Grok 프롬프트 생성"' in shell
    assert 'label: "Runpod ComfyUI 요청"' in shell
    assert "(단위작업)" not in shell


def test_admin_navigation_uses_the_korean_prompt_instruction_label() -> None:
    source = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")

    assert 'key: "adminGrokInstructions", label: "프롬프트 지시 관리"' in source


def test_prompt_library_menu_is_removed_from_generate_sidebar() -> None:
    source = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")

    nav_start = source.index("const GENERATE_NAV_ITEMS")
    nav_end = source.index("const ADMIN_NAV_ITEMS")
    generate_nav = source[nav_start:nav_end]

    assert "promptLibrary" not in generate_nav
    assert "Prompt Library" not in generate_nav
    assert '{ key: "assets", label: "Collection 관리", permission: "history:read" }' in generate_nav


def test_assets_collection_management_uses_body_filters_without_sidebar_buttons() -> None:
    shell = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "assetsUncategorizedTotal" in shell
    assert "assetsAllTotal" in shell
    assert "allTotal={assetsAllTotal}" in shell
    assert "apiClient.assets({ page: 1, pageSize: 1 })" in shell
    assert "apiClient.assets({ page: 1, pageSize: 1, uncategorized: true })" in shell
    assert "uncategorizedTotal={assetsUncategorizedTotal}" in shell
    assert 'headerTitle={`컬렉션 관리 · 전체 ${total}개`}' in screen
    create5a = screen.split("export function Create5aScreen", 1)[1]
    assert "sidebarExtra" not in create5a.split("<section className=\"v3-collection-management\"", 1)[0]
    assert "v3-sidebar-context-menu" not in create5a
    assert '<div className="v3-segment-nav-head"><span>미분류</span><span>{uncategorizedTotal}</span></div>' not in create5a
    assert "collections.map((c) => (" not in create5a
    assert "onCollectionFilterChange(c.id)" not in create5a
    assert "전체 목록" in screen
    assert "allTotal: number" in screen
    assert "v3-collection-filter-row" in screen
    assert "onCollectionFilterChange(collection.id)" in screen
    assert "event.stopPropagation(); onDeleteCollection(collection)" in screen


def test_batch_job_screen_follows_the_approved_management_mockup() -> None:
    screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")

    assert "const PAGE_SIZE = 5;" in screen
    assert "const PAGE_SIZE = 10;" not in screen
    assert "openRecoveryModal(job)" in screen
    dashboard_section = screen.split("<strong>진행 중 Batch</strong>", 1)[1].split("<strong>Batch 작업 이력</strong>", 1)[0]
    assert 'onGoTo("review.history")' not in dashboard_section
    assert 'onClick={() => onGoTo("review.history")}' not in dashboard_section
    assert "재처리 관리" in screen
    assert "상태 새로고침" in screen
    assert "선택 항목 재처리" in screen
    assert "전체 실패 재처리" in screen
    assert "job.failedCount > 0" in screen
    assert "retryFailedBatchItems" in Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "retrySelectedBatchItems" in Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "batchJobDetail" in Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert 'headerEyebrow="GENERATE · BATCH JOB MANAGEMENT"' in screen
    assert 'headerTitle="Batch 처리"' in screen
    assert "Batch 생성" in screen
    assert "진행 중 Batch" in screen
    assert "프롬프트 생성" in screen
    assert "RunPod 영상 생성" in screen
    assert "Batch 작업 이력" in screen
    assert "작업 입력" in screen
    assert "ZIP 파일 선택" in screen
    assert "지시문 연결됨" in screen
    assert "길이 (프레임 수)" in screen
    assert "81f · 5초" in screen
    assert "161f · 10초" not in screen
    assert "FRAME_OPTIONS = [49, 81]" in screen
    assert "FRAME_OPTIONS = [49, 81, 161]" not in screen
    assert "[49, 81, 161]" not in Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")
    assert "[49, 81, 161]" not in Path("frontend/src/screens/grokWorkspaceScreen.tsx").read_text(encoding="utf-8")
    assert "[49, 81, 161]" not in Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    assert "작업 요청" in screen
    assert "Pending Submit" in screen
    assert "ZIP 다운로드" in screen
    assert "zip 파일명" in screen
    assert "이미지 디렉토리" not in screen
    assert "시작일" not in screen
    assert "종료일" not in screen
    assert "실행일" in screen
    assert "dateFrom: historyDate" in screen
    assert "dateTo: historyDate" in screen
    assert "job.sourceZipFileName || job.sourceDirName || \"-\"" in screen
    assert "1 /" in screen
    assert "v3-batch-layout-grid" in screen
    assert "v3-batch-folder-card" in screen
    assert "v3-batch-length-segmented" in screen
    assert "제거" not in screen
    assert "Batch Generations" not in screen
    assert "Incomplete Dashboard" not in screen


def test_batch_history_is_visible_to_every_authenticated_user_but_mutations_stay_gated() -> None:
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    studio_shell = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")

    batch_nav = shell.split('key: "batchJobs"', 1)[1].split("}", 1)[0]
    assert "permission" not in batch_nav
    assert '"create.batchJobs": ["prompts:build", "jobs:run"]' not in studio_shell
    assert 'const canOperateBatch = canUse(user, "prompts:build") && canUse(user, "jobs:run");' in screen
    assert "{canOperateBatch ? (" in screen
    assert "Batch 생성 권한이 없어 조회 전용으로 표시됩니다." in screen


def test_batch_job_screen_labels_81_frame_chain_workflows_as_ten_seconds() -> None:
    screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")

    assert "TEN_SECOND_CHAIN_WORKFLOW_IDS" in screen
    assert "81f x 2 · 10초" in screen
    assert "formatFrameDuration(job.requestedFrames, job.workflowId)" in screen


def test_batch_recovery_modal_lists_only_error_items_with_ten_row_pages() -> None:
    screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")

    assert "const RECOVERY_PAGE_SIZE = 10;" in screen
    assert "isRecoveryErrorItem" in screen
    assert "recoveryErrorItems" in screen
    assert "paginatedRecoveryItems" in screen
    assert "recoveryItems.map((item)" not in screen
    assert "paginatedRecoveryItems.map((item)" in screen
    assert "오류건 내역" in screen
    assert "recoveryFirstItemIndex" in screen
    assert "recoveryLastItemIndex" in screen
    assert "recoveryTotalPages" in screen


def test_batch_recovery_modal_previews_source_images_from_asset_ids() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "assetId?: string | null" in client
    assert "ProtectedImage" in screen
    assert "recoveryPreview" in screen
    assert "setRecoveryPreview({ src: `/api/files/${item.assetId}`" in screen
    assert "v3-batch-recovery-file-preview" in screen
    assert "v3-batch-recovery-preview-modal" in screen
    assert ".v3-batch-recovery-file-preview" in css
    assert ".v3-batch-recovery-preview-modal" in css


def test_batch_recovery_modal_uses_defined_light_theme_tokens() -> None:
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    token_block = css.split("/* 경계선 */", 1)[0]
    modal_panel = css.split(".v3-modal-panel {", 1)[1].split("}", 1)[0]
    recovery_title = css.split(".v3-batch-recovery-title h2 {", 1)[1].split("}", 1)[0]
    recovery_metric_label = css.split(".v3-batch-recovery-metrics small {", 1)[1].split("}", 1)[0]
    recovery_metric_value = css.split(".v3-batch-recovery-metrics strong {", 1)[1].split("}", 1)[0]

    assert "--v3-bg-canvas:" in token_block
    assert "--v3-bg-muted:" in token_block
    assert "--v3-text-heading:" in token_block
    assert "--v3-text-muted:" in token_block
    assert "color: var(--v3-text-body);" in modal_panel
    assert "color: var(--v3-text-body);" in recovery_title
    assert "color: var(--v3-text-label);" in recovery_metric_label
    assert "color: var(--v3-text-body);" in recovery_metric_value


def test_runpod_request_and_batch_zip_payload_include_resolution_tier() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    runpod_screen = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")
    batch_screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")

    assert 'export type ResolutionTier = "sd" | "hd";' in client
    assert "resolutionTier?: ResolutionTier" in client
    assert 'formData.set("resolutionTier", payload.resolutionTier || "sd");' in client
    assert "const [resolutionTier, setResolutionTier] = useState<ResolutionTier>(\"sd\");" in runpod_screen
    assert "resolutionTier" in runpod_screen.split("createRunpodRequestBatch", 1)[1]
    assert "const SD_PIXEL_LIMIT = 409_600;" in runpod_screen
    assert "function sourcePixelCount" in runpod_screen
    assert "function hdDisabledForItem" in runpod_screen
    assert "const hdDisabledForSelection" in runpod_screen
    assert 'disabled={tier.value === "hd" && hdDisabledForSelection}' in runpod_screen
    assert "const [qualityOverrides, setQualityOverrides] = useState<Record<string, ResolutionTier>>" in runpod_screen
    assert 'aria-label="Quality"' in runpod_screen
    assert 'disabled={tier.value === "hd" && hdDisabled}' in runpod_screen
    assert "setQualityOverrides" in runpod_screen
    assert "resolutionTierForDraft(draft)" in runpod_screen.split("createRunpodRequestBatch", 1)[1]
    assert "const [resolutionTier, setResolutionTier] = useState<ResolutionTier>(\"sd\");" in batch_screen
    assert "resolutionTier," in batch_screen.split("createBatchJobFromZip", 1)[1]
    assert "Quality" in runpod_screen
    assert "Quality" in batch_screen


def test_runpod_request_screen_renders_item_failure_message() -> None:
    runpod_screen = Path("frontend/src/screens/runpodRequestScreen.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    assert "draft.failureMessage" in runpod_screen
    assert "v3-runpod-failure-message" in runpod_screen
    assert ".v3-runpod-failure-message" in css


def test_runpod_history_identity_guideline_grid_overflow_and_counts() -> None:
    """2026-09-13 작업자 UI 식별성 지침 — ①16컬럼 그리드 정합성 ②카드 내 드롭다운 overflow ③액션별 선택 수량 바인딩."""
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/styles.css").read_text(encoding="utf-8")

    # ① head/row가 같은 RUNPOD_HISTORY_GRID(16컬럼)를 쓰고, 상태 바는 border-left로만 그린다(컬럼 추가 없음)
    grid = source.split("const RUNPOD_HISTORY_GRID = \"", 1)[1].split("\"", 1)[0]
    assert len(grid.split(") ")) + grid.count("px ") - grid.count("minmax(") >= 0  # sanity: parses
    assert grid.count("minmax(") + len([tok for tok in grid.replace(")", ") ").split() if tok.endswith("px") and "(" not in tok]) == 16
    assert source.count("style={{ gridTemplateColumns: RUNPOD_HISTORY_GRID") == 2
    assert ".v3-history-head, .v3-history-row { border-left: 3px solid transparent; }" in css
    assert "v3-history-row ${runpodRowToneClass(resultStatusTone)}" in source

    # ② Batch ID 후보 드롭다운이 카드 밖으로 나가야 하므로 필터 카드는 overflow:visible
    assert ".v3-card.is-overflow-visible { overflow: visible; }" in css
    filter_card = source.split('className="v3-card v3-history-step-card is-overflow-visible"', 1)[1].split('className="v3-selection-bar"', 1)[0]
    assert "v3-batch-candidate-list" in filter_card

    # ③ 액션별 개수 = 실제 처리 집합 (재실행·삭제=selectedRunpodItems, 다운로드=selectedDownloadItems, ZIP=selectedRunpodTaskIds)
    bar = source.split('className="v3-selection-bar"', 1)[1].split('<div className="v3-card v3-runpod-history-table">', 1)[0]
    assert "선택 재실행 ({selectedRunpodItems.length})" in bar and "onClick={reworkSelectedRunpodItems}" in bar
    assert "선택 삭제 ({selectedRunpodItems.length})" in bar and "onRequestBulkDelete(selectedRunpodItems)" in bar
    assert "선택 다운로드 ({selectedDownloadItems.length})" in bar and "selectedDownloadItems.forEach((item) => onDownload(item))" in bar
    assert "선택 ZIP ({selectedRunpodTaskIds.length})" in bar and "downloadSelectedBatchZip()" in bar
    assert "선택 {selectedRunpodTaskIds.length}건에 대한 작업" in bar
