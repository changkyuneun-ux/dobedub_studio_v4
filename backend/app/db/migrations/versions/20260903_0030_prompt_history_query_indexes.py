"""add prompt history lookup indexes

Revision ID: 20260903_0030
Revises: 20260902_0029
Create Date: 2026-09-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_0030"
down_revision = "20260902_0029"
branch_labels = None
depends_on = None


INDEXES = [
    (
        "ix_image_prompt_drafts_owner_workflow_status_updated",
        "image_prompt_drafts",
        ["created_by", "workflow_id", "status", "updated_at", "id"],
    ),
    (
        "ix_image_prompt_drafts_owner_updated_id",
        "image_prompt_drafts",
        ["created_by", "updated_at", "id"],
    ),
    (
        "ix_image_prompt_drafts_workflow_status_updated",
        "image_prompt_drafts",
        ["workflow_id", "status", "updated_at", "id"],
    ),
    (
        "ix_image_prompt_drafts_workflow_updated_id",
        "image_prompt_drafts",
        ["workflow_id", "updated_at", "id"],
    ),
    (
        "ix_image_prompt_drafts_workflow_owner_status",
        "image_prompt_drafts",
        ["workflow_id", "created_by", "status"],
    ),
    (
        "ix_image_prompt_drafts_updated_id",
        "image_prompt_drafts",
        ["updated_at", "id"],
    ),
    (
        "ix_prompt_generation_attempts_draft_attempt_latest",
        "prompt_generation_attempts",
        ["draft_id", "attempt_no", "id"],
    ),
    (
        "ix_workflow_tasks_prompt_draft_latest",
        "workflow_tasks",
        ["prompt_draft_id", "deleted_at", "created_at", "id"],
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table_name, columns in INDEXES:
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        if name not in existing:
            op.create_index(name, table_name, columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for name, table_name, _columns in reversed(INDEXES):
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        if name in existing:
            op.drop_index(name, table_name=table_name)
