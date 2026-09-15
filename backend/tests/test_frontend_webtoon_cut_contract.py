from __future__ import annotations

from pathlib import Path


def test_webtoon_cut_is_top_level_image_cut_route_with_server_pipeline() -> None:
    router = Path("frontend/src/router.ts").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    studio = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    navigation = Path("frontend/src/helpers/navigation.ts").read_text(encoding="utf-8")
    backend_api = "\n".join(path.read_text(encoding="utf-8") for path in Path("backend/app/api").rglob("*.py"))

    assert '"webtoonCuts"' in router
    assert '"webtoonCuts.split": "/studio/webtoon-cuts/split"' in router
    assert '"webtoonCuts.history": "/studio/webtoon-cuts/history"' in router
    assert 'local: { label: "IMAGE CUT"' in shell
    assert 'generate: { label: "GENERATE"' in shell
    assert 'label: "이미지 컷 관리", items: LOCAL_NAV_ITEMS' in shell
    assert shell.index('label: "이미지 컷 관리", items: LOCAL_NAV_ITEMS') < shell.index('label: "GENERATE", items: GENERATE_NAV_ITEMS')
    assert '{ key: "webtoonCutSplit", label: "컷 분할 처리", permission: "jobs:run" }' in shell
    assert '{ key: "webtoonCutHistory", label: "컷 분할 이력", permission: "jobs:run" }' in shell
    assert 'className="v3-sidebar-area"' not in shell
    generate_nav = shell.split("const GENERATE_NAV_ITEMS", 1)[1].split("];", 1)[0]
    assert "webtoonCut" not in generate_nav
    assert 'key === "webtoonCutSplit"' in navigation
    assert 'key === "webtoonCutHistory"' in navigation
    assert '"webtoonCuts.split": "jobs:run"' in studio
    assert '"webtoonCuts.history": "jobs:run"' in studio
    assert "WebtoonCutScreen" in studio
    assert 'prefix="/webtoon-cuts"' in backend_api
    assert '@router.post("/uploads/presign"' in backend_api
    assert '@router.post("/jobs"' in backend_api
    assert '@router.get("/jobs"' in backend_api


def test_webtoon_cut_screen_uses_s3_server_pipeline_and_cancelable_jobs() -> None:
    source = Path("frontend/src/screens/webtoonCutScreen.tsx").read_text(encoding="utf-8")

    assert "S3 업로드 · 서버 컷 분리 · I2V 입력 연결" in source
    assert "동일 파일명도 기존 결과를 덮어쓰지 않고 새 작업으로 생성됩니다." in source
    assert "기존 취소/실패 작업과 S3 산출물은 이력에 보존됩니다." in source
    assert "presignWebtoonCutUpload" in source
    assert "completeWebtoonCutUpload" in source
    assert "createWebtoonCutJob" in source
    assert "cancelWebtoonCutJob" in source
    assert '{isRunning ? "작업 취소" : "작업 요청"}' in source
    assert "PDF · ZIP · JPG · PNG · WEBP · GIF" in source
    assert 'accept=".jpg,.jpeg,.png,.webp,.gif,.pdf,.zip,image/jpeg,image/png,image/webp,image/gif,application/pdf,application/zip,application/x-zip-compressed"' in source
    assert "showDirectoryPicker" not in source
    assert "v3-tab-row" not in source
    assert "v3-tab-button" not in source


def test_webtoon_cut_history_uses_list_preview_filter_select_all_and_worker_filter() -> None:
    source = Path("frontend/src/screens/webtoonCutScreen.tsx").read_text(encoding="utf-8")
    client = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert 'type ViewMode = "list" | "grid"' in source
    assert "jobStatusFilter" in source
    assert "jobsPage" in source
    assert "outputsPage" in source
    assert "작업 상태" in source
    assert '<option value="cancelled">취소</option>' in source
    assert '<option value="failed">실패</option>' in source
    assert "리스트" in source
    assert "그리드" in source
    assert "필터 결과 전체 선택" in source
    assert "검수제외 전체 선택" not in source
    assert "작업자" in source
    assert "createdBy" in source
    assert "workerFilter" in source
    assert 'params.createdBy' in client
    assert 'query.set("createdBy", params.createdBy)' in client
    assert "이전" in source
    assert "다음" in source
    assert "previewOutput" in source
    assert "usedState" in source


def test_webtoon_cut_handoff_persists_selection_for_prompt_and_batch_screens() -> None:
    cut_screen = Path("frontend/src/screens/webtoonCutScreen.tsx").read_text(encoding="utf-8")
    prompt_screen = Path("frontend/src/screens/promptManagementScreen.tsx").read_text(encoding="utf-8")
    batch_screen = Path("frontend/src/screens/batchJobScreen.tsx").read_text(encoding="utf-8")
    workspace = Path("frontend/src/state/durableWorkspace.ts").read_text(encoding="utf-8")

    assert "saveWebtoonCutHandoff" in cut_screen
    assert "handoffWebtoonCutsToGrok" in cut_screen
    assert "handoffWebtoonCutsToBatch" in cut_screen
    assert "loadWebtoonCutHandoff(user.id, \"grok_prompt\")" in prompt_screen
    assert "loadWebtoonCutHandoff(user.id, \"batch\")" in batch_screen
    assert "createBatchJob({" in batch_screen
    assert "WebtoonCutHandoffSnapshot" in workspace
