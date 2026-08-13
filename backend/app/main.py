from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect

from backend.app.api.manual import router as manual_router
from backend.app.api.web import router as web_router
from backend.app.api.v1.admin import router as admin_router
from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.assets import router as assets_router
from backend.app.api.v1.collections import router as collections_router
from backend.app.api.v1.configs import router as configs_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.history import router as history_router
from backend.app.api.v1.jobs import router as jobs_router
from backend.app.api.v1.metadata import router as metadata_router
from backend.app.api.v1.prompts import router as prompts_router
from backend.app.api.v1.reports import router as reports_router
from backend.app.api.v1.sandbox_pod import router as sandbox_pod_router
from backend.app.api.v1.segment_defaults import router as segment_defaults_router
from backend.app.api.v1.system import router as system_router
from backend.app.api.v1.workflows import router as workflows_router
from backend.app.core.config import get_settings
from backend.app.db.session import engine
from backend.app.services.prompt_builder_service import monitor_active_prompt_generations
from backend.app.services.studio_api_service import ensure_storage_dirs, monitor_active_jobs
from backend.app.services.workflow_storage_service import bootstrap_workflow_store


LOGGER = logging.getLogger(__name__)


def _ensure_database_schema() -> None:
    if os.environ.get("RUN_SERVER_AUTO_MIGRATE", "0") != "1":
        return

    try:
        table_names = set(inspect(engine).get_table_names())
    except Exception as exc:
        raise RuntimeError("Database is not reachable or DATABASE_URL is invalid") from exc

    if "users" in table_names:
        return

    from alembic import command
    from alembic.config import Config

    config = Config(str(get_settings().project_root / "alembic.ini"))
    LOGGER.info("users table missing: running alembic upgrade head for first-time schema bootstrap.")
    command.upgrade(config, "head")


@asynccontextmanager
async def _lifecycle(_: FastAPI):
    settings = get_settings()
    workflow_store = bootstrap_workflow_store(
        settings.workflow_seed_dir,
        settings.workflows_dir,
        settings.data_dir,
    )
    LOGGER.info(
        "Workflow store initialized: created=%s updated=%s preserved=%s",
        len(workflow_store["created"]),
        len(workflow_store["updated"]),
        len(workflow_store["preserved"]),
    )
    _ensure_database_schema()
    async def monitor_loop() -> None:
        while True:
            try:
                result = await asyncio.to_thread(monitor_active_jobs)
                if result["failures"]:
                    LOGGER.warning("Task monitor could not refresh tasks: %s", result["failures"])
                prompt_result = await asyncio.to_thread(monitor_active_prompt_generations)
                if prompt_result["failures"]:
                    LOGGER.warning("Prompt monitor could not refresh requests: %s", prompt_result["failures"])
            except Exception:
                LOGGER.exception("Task monitor cycle failed")
            await asyncio.sleep(settings.task_monitor_interval_seconds)

    monitor_task = asyncio.create_task(monitor_loop(), name="task-status-monitor")
    try:
        yield
    finally:
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_storage_dirs()
    app = FastAPI(
        title=settings.app_name,
        docs_url="/api-docs",
        redoc_url="/api-redoc",
        lifespan=_lifecycle,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def no_cache_studio_assets(request, call_next):
        response = await call_next(request)
        path = request.url.path
        # Vite build의 hash 파일은 내용이 바뀌면 URL도 바뀐다. 운영에서 매 화면
        # 진입마다 JS/CSS를 다시 검증하지 않도록 장기 캐시한다.
        if path.startswith("/studio/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/docs/manual-assets/"):
            # 매뉴얼 캡처는 iframe 진입 시 필요한 항목만 lazy load하며, 같은 파일은
            # 짧은 기간 재사용해 EFS 정적 파일 재검증을 줄인다.
            response.headers["Cache-Control"] = "public, max-age=3600"
        elif path.startswith("/studio"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    api_routers = [
        health_router,
        admin_router,
        auth_router,
        assets_router,
        collections_router,
        workflows_router,
        segment_defaults_router,
        metadata_router,
        prompts_router,
        jobs_router,
        history_router,
        configs_router,
        reports_router,
        system_router,
        sandbox_pod_router,
    ]
    for prefix in (settings.api_prefix, "/api"):
        for router in api_routers:
            app.include_router(router, prefix=prefix)
    app.include_router(manual_router)
    docs_dir = settings.project_root / "docs"
    if docs_dir.exists():
        app.mount("/docs", StaticFiles(directory=str(docs_dir)), name="studio-docs")
    src_dir = settings.project_root / "src"
    if src_dir.exists():
        app.mount("/src", StaticFiles(directory=str(src_dir)), name="studio-src")
    frontend_assets_dir = settings.project_root / "frontend" / "dist" / "assets"
    if frontend_assets_dir.exists():
        app.mount("/studio/assets", StaticFiles(directory=str(frontend_assets_dir)), name="studio-react-assets")
    app.include_router(web_router)
    return app


app = create_app()
