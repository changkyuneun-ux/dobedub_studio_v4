#!/usr/bin/env python3
"""Static and HTTP smoke checks for the v4 React workspace."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_FILES = [
    "frontend/package.json",
    "frontend/index.html",
    "frontend/src/main.tsx",
    "frontend/src/router.ts",
    "frontend/src/StudioShell.tsx",
    "frontend/src/auth-session.ts",
    "frontend/src/screens/accessScreens.tsx",
    "frontend/src/screens/createScreens.tsx",
    "frontend/src/api/client.ts",
]


def main() -> None:
    missing = [path for path in REQUIRED_FILES if not (PROJECT_ROOT / path).exists()]
    assert not missing, f"Missing frontend files: {missing}"

    package_json = json.loads((PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    assert package_json["scripts"]["build"]
    assert "react" in package_json["dependencies"]
    assert "vite" in package_json["dependencies"]

    main_tsx = (PROJECT_ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
    auth_session = (PROJECT_ROOT / "frontend/src/auth-session.ts").read_text(encoding="utf-8")
    router = (PROJECT_ROOT / "frontend/src/router.ts").read_text(encoding="utf-8")
    studio_shell = (PROJECT_ROOT / "frontend/src/StudioShell.tsx").read_text(encoding="utf-8")
    access_screens = (PROJECT_ROOT / "frontend/src/screens/accessScreens.tsx").read_text(encoding="utf-8")
    create_screens = (PROJECT_ROOT / "frontend/src/screens/createScreens.tsx").read_text(encoding="utf-8")
    api_client = (PROJECT_ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    frontend_source = "\n".join(path.read_text(encoding="utf-8") for path in (PROJECT_ROOT / "frontend/src").rglob("*.tsx"))

    # v4 routes and common shell
    for path in [
        "/studio/access/login",
        "/studio/create/load",
        "/studio/create/prompt",
        "/studio/create/confirm",
        "/studio/review/history",
        "/studio/review/reuse",
        "/studio/review/assets",
        "/studio/admin/task-policy",
    ]:
        assert path in router, path
    assert '"create.progress"' not in router
    assert '"create.result"' not in router
    assert "RETIRED_CREATE_ROUTE_REDIRECTS" in router
    assert '"review.history"' in router
    assert "<StudioShell" in main_tsx

    # Same-tab refresh restores a valid session. Explicit logout still removes it.
    assert "RESTORE_LOGIN_SESSION_ON_REFRESH = true" in auth_session
    assert "export function loadAuthSession" in auth_session
    assert "Date.parse(parsed.expiresAt) <= Date.now()" in auth_session
    assert "pagehide" not in main_tsx
    assert "beforeunload" not in main_tsx
    assert "function handleLogout" in main_tsx
    assert "clearLoginSession();" in main_tsx

    # Manual anchors must not navigate the parent SPA from srcDoc iframe.
    assert "function handleManualLoad" in access_screens
    assert "target.nodeType !== 1" in access_screens
    assert "event.preventDefault();" in access_screens
    assert "event.stopPropagation();" in access_screens
    assert "section.scrollIntoView" in access_screens
    assert 'sandbox="allow-same-origin"' in access_screens
    assert 'sandbox="allow-scripts"' not in access_screens

    # A submitted task moves to History; the browser does not wait on a progress/result route.
    assert "Task History에서 진행 상태를 확인하세요" in studio_shell
    assert 'onNavigate("review.history")' in studio_shell
    assert "async function cancelHistoryTask" in studio_shell
    assert "onCancelTask" in studio_shell
    assert "workflowSelectionLocked = running" in studio_shell
    assert "Task History" in create_screens

    # Confirmations must use the app-owned v4 dialog rather than a browser-native prompt.
    for native_dialog in ("window.confirm(", "window.alert(", "window.prompt("):
        assert native_dialog not in frontend_source, native_dialog
    assert "v3-confirm-dialog" in studio_shell
    assert "Negative Prompt" in create_screens
    assert "출력 설정" in create_screens

    # Prompt Library must apply to the segment that opened it, without replacing images/config.
    assert "type PromptReuseTarget" in studio_shell
    assert "setPromptReuseTarget" in studio_shell
    assert "function applyReusablePrompt" in studio_shell
    assert "setSegments((items) => items.map" in studio_shell
    assert "targetSegmentName" in studio_shell
    assert "targetSegmentName" in frontend_source
    assert "프롬프트 재사용" in create_screens
    assert "selectedSegment?.positivePrompt" in create_screens
    assert '"적용됨"' in create_screens

    # Keyframe upload supports both file selection and image drag-and-drop.
    assert "onDrop={(event)" in create_screens
    assert "event.dataTransfer.files" in create_screens
    assert "파일 선택 또는 끌어놓기" in create_screens
    assert "is-dragging" in create_screens

    # A single-image workflow has no end keyframe; never invent a KF 2 placeholder.
    workflow_helpers = (PROJECT_ROOT / "frontend/src/helpers/workflow.ts").read_text(encoding="utf-8")
    assert "segment.endImageIndex ?? segment.startImageIndex ?? index + 1" in workflow_helpers
    assert "const hasEndKeyframe = keyframes.length > 1" in create_screens

    review_screens = (PROJECT_ROOT / "frontend/src/screens/reviewScreens.tsx").read_text(encoding="utf-8")
    styles_css = (PROJECT_ROOT / "frontend/src/styles.css").read_text(encoding="utf-8")
    assert "v3-collection-management" in review_screens
    assert "컬렉션 관리" in review_screens
    assert "새 컬렉션 이름" in review_screens
    assert ".v3-collection-management" in styles_css

    # API surface used by the v4 routes.
    for endpoint in [
        "/api/auth/login",
        "/api/auth/session",
        "/api/workflows",
        "/api/jobs",
        "/api/history",
        "/api/prompts/catalog",
        "/api/prompts/generate",
        "/api/admin/task-execution-policy",
        "/manual",
    ]:
        assert endpoint in api_client, endpoint

    with tempfile.TemporaryDirectory(prefix="dobedub-frontend-smoke-") as tmp:
        tmp_path = Path(tmp)
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'frontend-smoke.db'}"
        os.environ["PERSISTENCE_BACKEND"] = "db"
        os.environ["STUDIO_DATA_DIR"] = str(tmp_path / "data")
        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")

        from fastapi.testclient import TestClient
        from backend.app.main import create_app

        client = TestClient(create_app())
        for path in [
            "/studio/access/login",
            "/studio/create/load",
            "/studio/create/prompt",
            "/studio/create/confirm",
            "/studio/review/history",
            "/studio/admin/task-policy",
            "/studio/access/manual",
        ]:
            response = client.get(path)
            assert response.status_code == 200, path
            assert '<div id="root">' in response.text

        login_response = client.post("/api/auth/login", json={"id": "dobedub", "password": "password"})
        assert login_response.status_code == 200, login_response.text
        token = login_response.json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/auth/session", headers=headers).status_code == 200
        assert client.get("/manual", headers=headers).status_code == 200

    print("OK frontend smoke check passed")


if __name__ == "__main__":
    main()
