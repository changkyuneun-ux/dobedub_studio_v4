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
    assert "deleteUpload" in screen
    assert "업로드 이미지 삭제" in screen


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

    assert "apiClient.promptHistory({ page, generationStatus: generationFilter, runpodStatus: runpodFilter })" in source
    assert "apiClient.runpodHistory({ page: runpodPage, workflowId: runpodWorkflowFilter, resultStatus: runpodResultFilter, workerId: runpodWorkerFilter, dateFrom: runpodDateFrom, dateTo: runpodDateTo })" in source
    assert "v3-runpod-history-toolbar" in source
    assert "v3-runpod-history-actions" in source
    assert "runpodResponse?.filename" in source
    assert "promptHistory" in source
    assert "runpodHistory" in source


def test_runpod_history_supports_selected_bulk_download_and_delete() -> None:
    source = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "selectedRunpodTaskIds" in source
    assert "선택 다운로드" in source
    assert "선택 삭제" in source
    assert "onRequestBulkDelete" in source


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
    assert '{ key: "assets", label: "컬렉션 관리", permission: "history:read" }' in generate_nav


def test_assets_sidebar_uses_collection_filters_with_uncategorized_count() -> None:
    shell = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    screen = Path("frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")

    assert "assetsUncategorizedTotal" in shell
    assert "apiClient.assets({ page: 1, pageSize: 1, uncategorized: true })" in shell
    assert "uncategorizedTotal={assetsUncategorizedTotal}" in shell
    assert 'headerTitle={`컬렉션 관리 · 전체 ${total}개`}' in screen
    assert 'COLLECTION · {collections.length}' in screen
    assert '<div className="v3-segment-nav-head"><span>미분류</span><span>{uncategorizedTotal}</span></div>' in screen
    assert "collections.map((c) => (" in screen
    assert "onCollectionFilterChange(c.id)" in screen
