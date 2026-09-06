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
    assert "deleteImagePromptDraft" in client
    assert "deleteUpload" in screen
    assert "deletePromptRow" in screen
    assert "업로드 이미지 삭제" in screen
    assert "draft ? void deletePromptRow(draft) : void deleteUpload(upload)" in screen


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


def test_task_history_consumes_dedicated_prompt_and_runpod_contracts() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "apiClient.promptHistory({ page, generationStatus: generationFilter, runpodStatus: runpodFilter, batchId: batchFilter })" in source
    assert "apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, runDate: runpodRunDate, batchId: selectedBatchJobId })" in source
    assert "v3-runpod-history-toolbar" in source
    assert "v3-runpod-history-actions" in source
    assert "runpodResponse?.filename" in source
    assert "promptHistory" in source
    assert "runpodHistory" in source
    assert "실행일 시작" not in source
    assert "실행일 종료" not in source
    assert "실행일<input type=\"date\" value={runpodRunDate}" in source
    assert "}, [historyTab, runpodPage, runpodWorkflowFilter, runpodResultFilter, runpodWorkerFilter, runpodRunDate, selectedBatchJobId]);" in source


def test_runpod_history_batch_zip_uses_selected_batch_candidate_not_search_text() -> None:
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "batchJobCandidates" in client
    assert "selectedBatchJob" in source
    assert "setSelectedBatchJob(null)" in source
    assert "apiClient.batchJobZip(selectedBatchJob.id)" in source
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


def test_batch_job_creation_uses_zip_upload_studio_confirm_modal_and_ten_second_default() -> None:
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
    assert "DEFAULT_REQUESTED_FRAMES = 161" in source
    assert "161f · 10초" in source
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

    assert 'headerEyebrow="GENERATE · BATCH JOB MANAGEMENT"' in screen
    assert 'headerTitle="Batch 처리"' in screen
    assert "Batch 생성" in screen
    assert "진행 중 Batch" in screen
    assert "프롬프트 생성" in screen
    assert "RunPod 영상 생성" in screen
    assert "Batch 작업 이력" in screen
    assert "작업 ZIP" in screen
    assert "ZIP 파일 선택" in screen
    assert "지시문 연결됨" in screen
    assert "길이 (프레임 수)" in screen
    assert "161f · 10초" in screen
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
