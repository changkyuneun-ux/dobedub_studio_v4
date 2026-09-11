from __future__ import annotations

from pathlib import Path


def test_webtoon_cut_is_top_level_local_route_without_server_media_api() -> None:
    router = Path("frontend/src/router.ts").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    studio = Path("frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    navigation = Path("frontend/src/helpers/navigation.ts").read_text(encoding="utf-8")
    main = Path("frontend/src/main.tsx").read_text(encoding="utf-8")
    backend_api = "\n".join(path.read_text(encoding="utf-8") for path in Path("backend/app/api").rglob("*.py"))

    assert '"webtoonCuts"' in router
    assert '"webtoonCuts": "/studio/webtoon-cuts"' in router
    assert 'label: "LOCAL"' in shell
    assert 'label: "GENERATE"' in shell
    assert shell.index('label: "LOCAL"') < shell.index('label: "GENERATE"')
    assert '{ key: "webtoonCuts", label: "이미지 컷 분할", permission: "jobs:run" }' in shell
    generate_nav = shell.split("const GENERATE_NAV_ITEMS", 1)[1].split("];", 1)[0]
    assert "webtoonCuts" not in generate_nav
    assert 'key === "webtoonCuts"' in navigation
    assert '"webtoonCuts": "jobs:run"' in studio
    assert "WebtoonCutScreen" in studio
    assert '<WebtoonCutJobProvider key={user.id}' in main
    assert main.index('<WebtoonCutJobProvider key={user.id}') < main.index('<StudioShell')
    assert "</WebtoonCutJobProvider>" in main
    assert "/webtoon-cuts/upload" not in backend_api
    assert "/webtoon-cuts/download" not in backend_api


def test_webtoon_cut_screen_uses_browser_local_png_outputs_and_review_reprocess() -> None:
    source = Path("frontend/src/screens/webtoonCutScreen.tsx").read_text(encoding="utf-8")
    store = Path("frontend/src/features/webtoon-cut/webtoonCutStore.ts").read_text(encoding="utf-8")

    assert "showDirectoryPicker" in source
    assert "파일 또는 폴더 선택 / 끌어놓기" in source
    assert "작업 디렉토리 선택" not in source
    assert "manifest.json" in store
    assert "summary.csv" in store
    assert "_debug" in store
    assert "image/png" in store
    assert "continuous_sequence" in store
    assert "canvas.height > canvas.width * 3" in store
    assert "FULL_WIDTH_TRANSITION_RATIO = 0.95" in store
    assert "MIN_STRONG_TRANSITION_CUT_HEIGHT" in store
    assert "수평 장면 전환" in source
    assert "apiClient" not in source


def test_webtoon_cut_input_controls_allow_zip_file_selection_and_drop() -> None:
    source = Path("frontend/src/screens/webtoonCutScreen.tsx").read_text(encoding="utf-8")
    store = Path("frontend/src/features/webtoon-cut/webtoonCutStore.ts").read_text(encoding="utf-8")

    assert "chooseInputFiles" in source
    assert "chooseInputDirectory" in source
    assert ">파일 선택<" in source
    assert ">폴더 선택<" in source
    assert 'accept=".jpg,.jpeg,.png,.webp,.gif,.pdf,.zip,image/jpeg,image/png,image/webp,image/gif,application/pdf,application/zip,application/x-zip-compressed"' in source
    file_button_block = source.split("function chooseInputFiles", 1)[1].split("function chooseInputDirectory", 1)[0]
    assert "showDirectoryPicker" not in file_button_block
    assert "showOpenFilePicker" in file_button_block
    assert "fileInput.current?.click()" in file_button_block
    directory_button_block = source.split("function chooseInputDirectory", 1)[1].split("function connectDefaultWorkspace", 1)[0]
    assert 'showDirectoryPicker({ mode: "read" })' in directory_button_block
    assert "handleDroppedFileSystemHandle" in store
    assert "handle.kind === \"file\"" in store
    assert ".getFile()" in store


def test_webtoon_cut_supports_specified_raster_image_files() -> None:
    store = Path("frontend/src/features/webtoon-cut/webtoonCutStore.ts").read_text(encoding="utf-8")
    source = Path("frontend/src/screens/webtoonCutScreen.tsx").read_text(encoding="utf-8")

    assert '["jpg", "jpeg", "png", "webp", "gif"]' in store
    assert ".jpg,.jpeg,.png,.webp,.gif,.pdf,.zip" in source
    assert "PDF · JPG · PNG · WEBP · GIF · ZIP" in source


def test_webtoon_cut_does_not_prompt_for_output_directory_on_job_request() -> None:
    source = Path("frontend/src/screens/webtoonCutScreen.tsx").read_text(encoding="utf-8")
    store = Path("frontend/src/features/webtoon-cut/webtoonCutStore.ts").read_text(encoding="utf-8")
    filesystem = Path("frontend/src/features/webtoon-cut/filesystem.ts").read_text(encoding="utf-8")

    assert "requestDefaultWebtoonWorkspace" not in store
    assert "requestDefaultWebtoonWorkspace" not in filesystem
    assert 'disabled={!snapshot.totalUnits || !snapshot.outputReady}' in source
    assert 'snapshot.status === "running" ? webtoonCutJobStore.cancelRunningJob() : void webtoonCutJobStore.processSelectedInputs()' in source
    assert '{snapshot.status === "running" ? "작업 중단" : "작업 요청"}' in source
    assert "작업 요청 시 출력 폴더를 다시 묻지 않습니다" in source
    assert "작업 폴더 연결" in source
    assert "시스템 폴더가 아닌 별도 작업 폴더" in source
    assert "webtoon-cut 기본 작업 폴더" not in source


def test_webtoon_cut_provider_does_not_depend_on_react_default_import() -> None:
    store = Path("frontend/src/features/webtoon-cut/webtoonCutStore.ts").read_text(encoding="utf-8")

    assert 'import React' not in store
    assert "React.createElement" not in store
    assert "createElement(Fragment, null, children)" in store
