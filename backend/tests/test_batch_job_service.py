"""Batch job orchestration: creation, promotion, counters and queries."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect

from backend.app.db.models import BatchJob, ImagePromptDraft, PromptGenerationBatch, RunpodRequestBatch, WorkflowTask

# NOTE: this module deliberately relies on the shared `db_session` fixture
# (backend/tests/conftest.py) rather than instantiating SessionLocal()
# directly. Base.metadata.create_all()/drop_all() run only inside that
# fixture's setup/teardown, so a bare SessionLocal() call sees no tables at
# all when this file is collected on its own.


def test_batch_job_table_exists(db_session):
    inspector = inspect(db_session.get_bind())
    assert "batch_jobs" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("batch_jobs")}
    assert {
        "id",
        "workflow_id",
        "status",
        "source_dir_name",
        "requested_frames",
        "duration_seconds",
        "total_images",
        "prompt_completed_count",
        "prompt_failed_count",
        "video_requested_count",
        "video_completed_count",
        "video_failed_count",
        "last_downloaded_at",
        "created_by",
        "created_at",
        "updated_at",
    } <= columns


@pytest.mark.parametrize(
    "table, model",
    [
        ("prompt_generation_batches", PromptGenerationBatch),
        ("runpod_request_batches", RunpodRequestBatch),
        ("image_prompt_drafts", ImagePromptDraft),
        ("workflow_tasks", WorkflowTask),
    ],
)
def test_batch_job_id_column_added(db_session, table, model):
    inspector = inspect(db_session.get_bind())
    assert "batch_job_id" in {column["name"] for column in inspector.get_columns(table)}
    assert hasattr(model, "batch_job_id")
