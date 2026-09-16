from __future__ import annotations

from backend.app.core.config import Settings


def test_webtoon_cut_monitor_has_dedicated_one_second_default():
    from backend.app.services.webtoon_cut_worker_runtime import _monitor_interval_seconds

    settings = Settings(task_monitor_interval_seconds=5)

    assert _monitor_interval_seconds(settings) == 1


def test_webtoon_cut_monitor_interval_can_be_overridden_without_changing_global_monitor():
    from backend.app.services.webtoon_cut_worker_runtime import _monitor_interval_seconds

    settings = Settings(task_monitor_interval_seconds=5, webtoon_cut_monitor_interval_seconds=2)

    assert _monitor_interval_seconds(settings) == 2
