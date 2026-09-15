from __future__ import annotations

import asyncio
import logging

from backend.app.core.config import get_settings
from backend.app.services.webtoon_cut_worker import process_next_pending_job


LOGGER = logging.getLogger(__name__)


async def monitor_webtoon_cut_jobs() -> None:
    settings = get_settings()
    interval = max(1, int(getattr(settings, "task_monitor_interval_seconds", 5) or 5))
    while True:
        try:
            await asyncio.to_thread(process_next_pending_job)
        except Exception:
            LOGGER.exception("Webtoon cut worker cycle failed")
        await asyncio.sleep(interval)
