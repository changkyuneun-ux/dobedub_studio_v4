"""add batch job orchestration tables and links

Revision ID: 20260904_0033
Revises: 20260903_0032
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0033"
down_revision = "20260903_0032"
branch_labels = None
depends_on = None

_LINKED_TABLES = (
    "prompt_generation_batches",
    "runpod_request_batches",
    "image_prompt_drafts",
    "workflow_tasks",
)


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "batch_jobs" not in tables:
        op.create_table(
            "batch_jobs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("workflow_id", sa.String(length=191), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="INCOMPLETE"),
            sa.Column("source_dir_name", sa.String(length=512), nullable=True),
            sa.Column("requested_frames", sa.Integer(), nullable=False, server_default="81"),
            sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("total_images", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prompt_completed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prompt_failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("video_requested_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("video_completed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("video_failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prompt_waiting_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("prompt_generating_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runpod_pending_submit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runpod_queued_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runpod_in_progress_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_downloaded_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_batch_jobs_created_by", "batch_jobs", ["created_by"])
        op.create_index("ix_batch_jobs_workflow_id", "batch_jobs", ["workflow_id"])
        # 미완료 대시보드(상태 필터 + 최신순)와 내역 조회가 함께 쓰는 복합 인덱스.
        op.create_index("ix_batch_jobs_status_created_at", "batch_jobs", ["status", "created_at"])

    for table in _LINKED_TABLES:
        if table not in tables:
            continue
        if "batch_job_id" in _columns(inspector, table):
            continue
        op.add_column(table, sa.Column("batch_job_id", sa.String(length=64), nullable=True))
        op.create_index(f"ix_{table}_batch_job_id", table, ["batch_job_id"])

    if "batch_jobs" in tables:
        batch_columns = _columns(inspector, "batch_jobs")
        for column_name in (
            "prompt_waiting_count",
            "prompt_generating_count",
            "runpod_pending_submit_count",
            "runpod_queued_count",
            "runpod_in_progress_count",
        ):
            if column_name not in batch_columns:
                op.add_column("batch_jobs", sa.Column(column_name, sa.Integer(), nullable=False, server_default="0"))

    if "image_prompt_drafts" in tables and "promotion_claimed_at" not in _columns(inspector, "image_prompt_drafts"):
        op.add_column("image_prompt_drafts", sa.Column("promotion_claimed_at", sa.DateTime(), nullable=True))
    if "runpod_request_items" in tables:
        item_columns = _columns(inspector, "runpod_request_items")
        if "materialization_claimed_at" not in item_columns:
            op.add_column("runpod_request_items", sa.Column("materialization_claimed_at", sa.DateTime(), nullable=True))
        if "materialization_attempts" not in item_columns:
            op.add_column("runpod_request_items", sa.Column("materialization_attempts", sa.Integer(), nullable=False, server_default="0"))

    aggregation_indexes = (
        ("image_prompt_drafts", "ix_image_prompt_drafts_batch_status", ["batch_job_id", "status"]),
        ("workflow_tasks", "ix_workflow_tasks_batch_deleted_status", ["batch_job_id", "deleted_at", "status"]),
        ("image_prompt_drafts", "ix_image_prompt_drafts_promotion", ["status", "promotion_claimed_at", "batch_job_id"]),
        ("runpod_request_items", "ix_runpod_request_items_orphan", ["status", "task_id", "materialization_claimed_at"]),
    )
    for table, index_name, columns in aggregation_indexes:
        if table not in tables:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table)}
        if index_name not in existing:
            op.create_index(index_name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, index_name in (
        ("image_prompt_drafts", "ix_image_prompt_drafts_batch_status"),
        ("workflow_tasks", "ix_workflow_tasks_batch_deleted_status"),
        ("image_prompt_drafts", "ix_image_prompt_drafts_promotion"),
        ("runpod_request_items", "ix_runpod_request_items_orphan"),
    ):
        if table in tables and index_name in {index["name"] for index in inspector.get_indexes(table)}:
            op.drop_index(index_name, table_name=table)

    if "image_prompt_drafts" in tables and "promotion_claimed_at" in _columns(inspector, "image_prompt_drafts"):
        op.drop_column("image_prompt_drafts", "promotion_claimed_at")
    if "runpod_request_items" in tables:
        item_columns = _columns(inspector, "runpod_request_items")
        if "materialization_claimed_at" in item_columns:
            op.drop_column("runpod_request_items", "materialization_claimed_at")
        if "materialization_attempts" in item_columns:
            op.drop_column("runpod_request_items", "materialization_attempts")

    for table in _LINKED_TABLES:
        if table not in tables or "batch_job_id" not in _columns(inspector, table):
            continue
        index_names = {index["name"] for index in inspector.get_indexes(table)}
        if f"ix_{table}_batch_job_id" in index_names:
            op.drop_index(f"ix_{table}_batch_job_id", table_name=table)
        op.drop_column(table, "batch_job_id")

    if "batch_jobs" in tables:
        op.drop_table("batch_jobs")
