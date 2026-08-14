from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.timezone_utils import (
    epoch_to_seoul_naive,
    format_seoul_datetime,
    now_seoul_naive,
    seoul_naive_to_epoch,
)
from backend.app.services.job_service import JobRuntime, create_job


def main() -> None:
    assert epoch_to_seoul_naive(0) == datetime(1970, 1, 1, 9, 0, 0)
    assert seoul_naive_to_epoch(datetime(1970, 1, 1, 9, 0, 0)) == 0
    assert format_seoul_datetime(datetime(2026, 8, 14, 9, 30, 0)) == "2026-08-14 09:30:00 KST"

    runtime = JobRuntime(
        jobs={},
        dry_run=True,
        prepare_workflow_for_job=lambda payload: ({}, [], {}),
        build_runpod_payload=lambda workflow, images: {},
        runpod_request=lambda method, path, payload: {},
        save_runpod_outputs=lambda status, job: {"assets": [], "remoteUrls": []},
        append_history=lambda job: [],
        build_wan_node_config_snapshot=lambda workflow_id, segments: {},
        hydrate_input_images=lambda job: [],
    )
    job = create_job(runtime, {"workflowId": "timestamp-smoke.json", "segments": []})
    started_at = datetime.strptime(job["startedAt"], "%Y-%m-%d %H:%M:%S")
    assert abs((now_seoul_naive() - started_at).total_seconds()) < 5
    assert job["taskId"].startswith(f"task_{started_at.strftime('%Y%m%d_%H%M%S')}_")
    print("task timestamp smoke check passed")


if __name__ == "__main__":
    main()
