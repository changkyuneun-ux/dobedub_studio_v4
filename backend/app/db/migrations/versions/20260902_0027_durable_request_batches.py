"""add durable per-item RunPod request batch snapshots

Revision ID: 20260902_0027
Revises: 20260901_0026
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260902_0027"
down_revision = "20260901_0026"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "runpod_request_items" not in tables:
        op.create_table(
            "runpod_request_items",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("request_batch_id", sa.String(length=64), sa.ForeignKey("runpod_request_batches.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sequence_no", sa.Integer(), nullable=False),
            sa.Column("prompt_draft_id", sa.String(length=64), sa.ForeignKey("image_prompt_drafts.id"), nullable=True),
            sa.Column("asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=False),
            sa.Column("workflow_id", sa.String(length=191), nullable=False),
            sa.Column("positive_prompt", sa.Text(), nullable=False),
            sa.Column("negative_prompt", sa.Text(), nullable=True),
            sa.Column("requested_frames", sa.Integer(), nullable=False, server_default="81"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING_SUBMIT"),
            sa.Column("task_id", sa.String(length=64), sa.ForeignKey("workflow_tasks.id"), nullable=True),
            sa.Column("failure_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_runpod_request_items_request_batch_id", "runpod_request_items", ["request_batch_id"])
        op.create_index("ix_runpod_request_items_prompt_draft_id", "runpod_request_items", ["prompt_draft_id"])
        op.create_index("ix_runpod_request_items_asset_id", "runpod_request_items", ["asset_id"])
        op.create_index("ix_runpod_request_items_workflow_id", "runpod_request_items", ["workflow_id"])
        op.create_index("ix_runpod_request_items_task_id", "runpod_request_items", ["task_id"])
        op.create_index("ix_runpod_request_items_batch_sequence", "runpod_request_items", ["request_batch_id", "sequence_no"])
        op.create_index("ix_runpod_request_items_status", "runpod_request_items", ["status"])

    task_columns = _columns(inspector, "workflow_tasks")
    if "request_item_id" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("request_item_id", sa.String(length=64), nullable=True))
        op.create_index("ix_workflow_tasks_request_item_id", "workflow_tasks", ["request_item_id"])

    batch_columns = _columns(inspector, "runpod_request_batches")
    additions = (
        ("status", sa.String(length=32), "QUEUED"),
        ("queued_count", sa.Integer(), "0"),
        ("in_progress_count", sa.Integer(), "0"),
        ("completed_count", sa.Integer(), "0"),
        ("failed_count", sa.Integer(), "0"),
        ("cancelled_count", sa.Integer(), "0"),
    )
    for name, column_type, default in additions:
        if name not in batch_columns:
            op.add_column("runpod_request_batches", sa.Column(name, column_type, nullable=False, server_default=default))
    if "updated_at" not in batch_columns:
        op.add_column("runpod_request_batches", sa.Column("updated_at", sa.DateTime(), nullable=True))
        op.execute("UPDATE runpod_request_batches SET updated_at = created_at WHERE updated_at IS NULL")

    indexes = {index["name"] for index in inspector.get_indexes("runpod_request_batches")}
    if "ix_runpod_request_batches_status" not in indexes:
        op.create_index("ix_runpod_request_batches_status", "runpod_request_batches", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "runpod_request_items" in tables:
        op.drop_table("runpod_request_items")
    if "workflow_tasks" in tables and "request_item_id" in _columns(inspector, "workflow_tasks"):
        op.drop_column("workflow_tasks", "request_item_id")
    if "runpod_request_batches" in tables:
        for name in ("updated_at", "cancelled_count", "failed_count", "completed_count", "in_progress_count", "queued_count", "status"):
            if name in _columns(inspector, "runpod_request_batches"):
                op.drop_column("runpod_request_batches", name)
