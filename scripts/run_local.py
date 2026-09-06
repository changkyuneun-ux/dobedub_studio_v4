#!/usr/bin/env python3
"""Run DOBEDUB STUDIO locally with the FastAPI app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
REQUIRED_MODULES = ("alembic", "uvicorn")
FRAMEWORK_PYTHON312 = Path("/Library/Frameworks/Python.framework/Versions/3.12/bin/python3")


def _required_modules_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in REQUIRED_MODULES)


def _candidate_has_required_modules(path: Path) -> bool:
    script = "; ".join(f"import {name}" for name in REQUIRED_MODULES)
    return subprocess.run(
        [str(path), "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _python_candidates() -> list[Path]:
    candidates: list[Path] = []
    for value in (
        os.environ.get("LOCAL_PYTHON"),
        shutil.which("python3.12"),
        str(FRAMEWORK_PYTHON312),
        shutil.which("python3"),
    ):
        if not value:
            continue
        path = Path(value)
        if path.exists() and path not in candidates:
            candidates.append(path)
    return candidates


def ensure_local_python_runtime() -> None:
    if _required_modules_available():
        return
    current = Path(sys.executable)
    for candidate in _python_candidates():
        if candidate == current:
            continue
        if _candidate_has_required_modules(candidate):
            os.execv(str(candidate), [str(candidate), *sys.argv])
            return
    missing = ", ".join(name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None)
    checked = ", ".join(str(path) for path in _python_candidates()) or "없음"
    raise RuntimeError(f"로컬 서버 실행에 필요한 Python 패키지가 없습니다: {missing}. 확인한 Python: {checked}")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def prepare_local_database() -> None:
    if os.environ.get("RUN_LOCAL_SKIP_DB_PREP", "0") == "1":
        return
    from alembic import command
    from alembic.config import Config

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    from backend.app.db.session import SessionLocal
    from backend.app.services.prompt_builder_service import apply_example_prompt_catalog, prompt_catalog

    with SessionLocal() as db:
        catalog = prompt_catalog(db)
        # B-06 3단계에서 prompt_catalog() 응답의 구형 "categories" 배열이 제거되어
        # 이 가드가 항상 참으로 평가되고 있었다(수정 전) - 로컬 재시작마다 관리자가
        # 편집한 카테고리/용어가 EXAMPLE_PROMPT_CATALOG 예시 데이터로 덮어써지는
        # 버그였다. "groups"가 유일한 canonical 응답이므로 이를 기준으로 판단한다.
        if not catalog.get("groups"):
            apply_example_prompt_catalog(db, force=False)


def main() -> None:
    ensure_local_python_runtime()
    import uvicorn

    load_env_file(PROJECT_ROOT / ".env")
    prepare_local_database()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8787"))
    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=os.environ.get("UVICORN_RELOAD", "0") == "1",
    )


if __name__ == "__main__":
    main()
