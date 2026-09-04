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


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table in _LINKED_TABLES:
        if table not in tables or "batch_job_id" not in _columns(inspector, table):
            continue
        index_names = {index["name"] for index in inspector.get_indexes(table)}
        if f"ix_{table}_batch_job_id" in index_names:
            op.drop_index(f"ix_{table}_batch_job_id", table_name=table)
        op.drop_column(table, "batch_job_id")

    if "batch_jobs" in tables:
        op.drop_table("batch_jobs")
