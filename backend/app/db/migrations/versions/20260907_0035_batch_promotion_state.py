"""persist batch prompt-to-RunPod promotion state

Revision ID: 20260907_0035
Revises: 20260906_0034
Create Date: 2026-09-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260907_0035"
down_revision = "20260906_0034"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "image_prompt_drafts" not in set(inspector.get_table_names()):
        return

    columns = _columns(inspector, "image_prompt_drafts")
    additions = (
        ("promotion_status", sa.Column("promotion_status", sa.String(length=32), nullable=False, server_default="NOT_APPLICABLE")),
        ("promotion_attempts", sa.Column("promotion_attempts", sa.Integer(), nullable=False, server_default="0")),
        ("promotion_last_error", sa.Column("promotion_last_error", sa.Text(), nullable=True)),
        ("promotion_next_attempt_at", sa.Column("promotion_next_attempt_at", sa.DateTime(), nullable=True)),
        ("promotion_updated_at", sa.Column("promotion_updated_at", sa.DateTime(), nullable=True)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("image_prompt_drafts", column)

    # Existing Ready batch drafts must be eligible for a durable first handoff;
    # any already-created task is reconciled to TASK_CREATED by the monitor.
    op.execute(
        """
        UPDATE image_prompt_drafts
        SET promotion_status = 'PENDING'
        WHERE batch_job_id IS NOT NULL
          AND status = 'READY'
          AND positive_prompt IS NOT NULL
          AND TRIM(positive_prompt) <> ''
          AND promotion_status = 'NOT_APPLICABLE'
        """
    )

    tables = set(sa.inspect(bind).get_table_names())
    if {"batch_jobs", "workflow_tasks"} <= tables:
        # A legacy process interruption could have left the parent Batch as
        # COMPLETE even though a Ready prompt never produced a RunPod task.
        # Reopen only those exact rows so the monitor can promote them safely.
        op.execute(
            """
            UPDATE batch_jobs
            SET status = 'INCOMPLETE'
            WHERE status = 'COMPLETE'
              AND EXISTS (
                  SELECT 1
                  FROM image_prompt_drafts draft
                  WHERE draft.batch_job_id = batch_jobs.id
                    AND draft.status = 'READY'
                    AND draft.positive_prompt IS NOT NULL
                    AND TRIM(draft.positive_prompt) <> ''
                    AND NOT EXISTS (
                        SELECT 1
                        FROM workflow_tasks task
                        WHERE task.batch_job_id = batch_jobs.id
                          AND task.prompt_draft_id = draft.id
                          AND task.deleted_at IS NULL
                    )
              )
            """
        )

    inspector = sa.inspect(bind)
    if "ix_image_prompt_drafts_batch_promotion_retry" not in _indexes(inspector, "image_prompt_drafts"):
        op.create_index(
            "ix_image_prompt_drafts_batch_promotion_retry",
            "image_prompt_drafts",
            ["batch_job_id", "promotion_status", "promotion_next_attempt_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "image_prompt_drafts" not in set(inspector.get_table_names()):
        return
    if "ix_image_prompt_drafts_batch_promotion_retry" in _indexes(inspector, "image_prompt_drafts"):
        op.drop_index("ix_image_prompt_drafts_batch_promotion_retry", table_name="image_prompt_drafts")
    for name in ("promotion_updated_at", "promotion_next_attempt_at", "promotion_last_error", "promotion_attempts", "promotion_status"):
        if name in _columns(sa.inspect(bind), "image_prompt_drafts"):
            op.drop_column("image_prompt_drafts", name)
