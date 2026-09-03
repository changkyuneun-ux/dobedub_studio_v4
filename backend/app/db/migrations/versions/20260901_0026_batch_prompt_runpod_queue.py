"""add durable prompt batch and RunPod dispatch queue metadata

Revision ID: 20260901_0026
Revises: 20260831_0025
Create Date: 2026-09-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260901_0026"
down_revision = "20260831_0025"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "prompt_generation_batches" not in tables:
        op.create_table(
            "prompt_generation_batches",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("workflow_id", sa.String(length=191), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_prompt_generation_batches_workflow_id", "prompt_generation_batches", ["workflow_id"])
        op.create_index("ix_prompt_generation_batches_status", "prompt_generation_batches", ["status"])

    if "prompt_generation_attempts" not in tables:
        op.create_table(
            "prompt_generation_attempts",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("draft_id", sa.String(length=64), nullable=False),
            sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("endpoint", sa.String(length=255), nullable=True),
            sa.Column("model", sa.String(length=191), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=True),
            sa.Column("output_tokens", sa.Integer(), nullable=True),
            sa.Column("response_json", sa.JSON(), nullable=False),
            sa.Column("failure_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_prompt_generation_attempts_draft", "prompt_generation_attempts", ["draft_id", "attempt_no"])

    if "runpod_request_batches" not in tables:
        op.create_table(
            "runpod_request_batches",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("workflow_id", sa.String(length=191), nullable=False),
            sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_runpod_request_batches_workflow_id", "runpod_request_batches", ["workflow_id"])

    draft_columns = _columns(inspector, "image_prompt_drafts")
    if "prompt_batch_id" not in draft_columns:
        op.add_column("image_prompt_drafts", sa.Column("prompt_batch_id", sa.String(length=64), nullable=True))
        op.create_index("ix_image_prompt_drafts_prompt_batch_id", "image_prompt_drafts", ["prompt_batch_id"])
    if "negative_prompt" not in draft_columns:
        op.add_column("image_prompt_drafts", sa.Column("negative_prompt", sa.Text(), nullable=True))
    if "requested_frames" not in draft_columns:
        op.add_column("image_prompt_drafts", sa.Column("requested_frames", sa.Integer(), nullable=True))

    task_columns = _columns(inspector, "workflow_tasks")
    if "prompt_draft_id" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("prompt_draft_id", sa.String(length=64), nullable=True))
        op.create_index("ix_workflow_tasks_prompt_draft_id", "workflow_tasks", ["prompt_draft_id"])
    if "request_batch_id" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("request_batch_id", sa.String(length=64), nullable=True))
        op.create_index("ix_workflow_tasks_request_batch_id", "workflow_tasks", ["request_batch_id"])
    if "dispatch_claimed_at" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("dispatch_claimed_at", sa.DateTime(), nullable=True))
    if "dispatch_attempts" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"))
    if "next_dispatch_at" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("next_dispatch_at", sa.DateTime(), nullable=True))
    if "last_dispatch_error" not in task_columns:
        op.add_column("workflow_tasks", sa.Column("last_dispatch_error", sa.Text(), nullable=True))

    existing_indexes = {index["name"] for index in inspector.get_indexes("workflow_tasks")}
    if "ix_workflow_tasks_dispatch" not in existing_indexes:
        op.create_index(
            "ix_workflow_tasks_dispatch",
            "workflow_tasks",
            ["status", "next_dispatch_at", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    # Do not alter legacy task/history records. Only remove this revision's
    # additive queue structures when explicitly rolling back.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "workflow_tasks" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("workflow_tasks")}
        if "ix_workflow_tasks_dispatch" in indexes:
            op.drop_index("ix_workflow_tasks_dispatch", table_name="workflow_tasks")
        for column in (
            "last_dispatch_error",
            "next_dispatch_at",
            "dispatch_attempts",
            "dispatch_claimed_at",
            "request_batch_id",
            "prompt_draft_id",
        ):
            if column in _columns(inspector, "workflow_tasks"):
                op.drop_column("workflow_tasks", column)

    if "image_prompt_drafts" in tables:
        for column in ("requested_frames", "negative_prompt", "prompt_batch_id"):
            if column in _columns(inspector, "image_prompt_drafts"):
                op.drop_column("image_prompt_drafts", column)

    for table in ("runpod_request_batches", "prompt_generation_attempts", "prompt_generation_batches"):
        if table in tables:
            op.drop_table(table)
