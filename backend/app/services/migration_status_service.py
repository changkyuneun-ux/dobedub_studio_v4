"""Alembic head/current comparison for the dashboard (spec 2026-09-13 §3.2 WORKFLOWS · DB tile).

Mirrors ``scripts/upgrade_database.py::migration_state`` but never raises: the
dashboard must render even when the revision check fails.
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings

_CACHE_TTL_SECONDS = 600.0  # 2026-09-13 성능: 리비전은 런타임 중 바뀌지 않는다(배포 시 프로세스 재시작)
_cache: dict[str, object] = {"at": 0.0, "value": None}


def migration_status(session: Session, *, use_cache: bool = True) -> dict:
    now = time.monotonic()
    cached = _cache.get("value")
    if use_cache and cached is not None and now - float(_cache.get("at") or 0.0) < _CACHE_TTL_SECONDS:
        return dict(cached)  # type: ignore[arg-type]
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        config = Config(str(get_settings().project_root / "alembic.ini"))
        target_heads = sorted(ScriptDirectory.from_config(config).get_heads())
        connection = session.connection()
        current_heads = sorted(MigrationContext.configure(connection).get_current_heads())
        value = {
            "alembicCurrent": current_heads[0] if current_heads else None,
            "alembicHead": target_heads[0] if target_heads else None,
            "migrationRequired": current_heads != target_heads,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - dashboard must not fail on revision lookup
        value = {"alembicCurrent": None, "alembicHead": None, "migrationRequired": False, "error": f"{type(exc).__name__}: {exc}"}
    _cache["at"] = now
    _cache["value"] = value
    return dict(value)
