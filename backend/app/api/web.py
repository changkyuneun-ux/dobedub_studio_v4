from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from backend.app.core.config import get_settings

router = APIRouter(tags=["web"])


def index_html_page() -> str:
    settings = get_settings()
    index_path = settings.project_root / "index.html"
    manual_path = settings.project_root / "docs" / "dobedub-studio-user-manual.md"
    if not index_path.exists():
        raise FileNotFoundError(index_path.name)
    body = index_path.read_text(encoding="utf-8")
    manual = manual_path.read_text(encoding="utf-8") if manual_path.exists() else ""
    manual = manual.replace("</script", "<\\/script")
    return body.replace("__MANUAL_MARKDOWN__", manual)


@router.get("/")
def index():
    # ECS Express health checks use the root path. Keep this endpoint successful
    # while letting interactive browsers enter the React studio route immediately.
    return HTMLResponse(
        """<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta http-equiv="refresh" content="0; url=/studio/app" />
    <title>DOBEDUB STUDIO</title>
    <script>window.location.replace('/studio/app');</script>
  </head>
  <body><a href="/studio/app">DOBEDUB STUDIO로 이동</a></body>
</html>"""
    )


@router.get("/index.html")
def index_html():
    return index()


def react_index_html() -> str:
    settings = get_settings()
    index_path = settings.project_root / "frontend" / "dist" / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return """<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>DOBEDUB STUDIO React</title>
    <style>
      body { margin: 0; background: #080b0f; color: #f8fafc; font-family: Arial, sans-serif; }
      main { display: grid; min-height: 100vh; place-items: center; padding: 24px; }
      section { background: #171b1f; border: 1px solid #3b82f6; border-radius: 10px; max-width: 680px; padding: 28px; }
      code { background: #0f1317; border: 1px solid #343a40; border-radius: 6px; display: block; margin-top: 12px; padding: 12px; }
    </style>
  </head>
  <body>
    <main>
      <section>
        <h1>DOBEDUB STUDIO React frontend</h1>
        <p>React 빌드 결과가 아직 없습니다. 로컬 개발은 Vite dev server로 실행합니다.</p>
        <code>cd frontend<br />npm install<br />npm run dev</code>
      </section>
    </main>
  </body>
</html>"""


def frontend_favicon_path():
    settings = get_settings()
    favicon_path = settings.project_root / "frontend" / "dist" / "favicon.png"
    if not favicon_path.exists():
        favicon_path = settings.project_root / "frontend" / "public" / "favicon.png"
    if not favicon_path.exists():
        raise HTTPException(status_code=404, detail="favicon not found")
    return favicon_path


@router.get("/favicon.png")
def favicon_root():
    return FileResponse(frontend_favicon_path(), media_type="image/png")


@router.get("/studio/favicon.png")
def favicon_studio():
    return FileResponse(frontend_favicon_path(), media_type="image/png")


@router.get("/studio", response_class=HTMLResponse)
def studio():
    return react_index_html()


@router.get("/studio/{path:path}", response_class=HTMLResponse)
def studio_fallback(path: str):
    return react_index_html()
