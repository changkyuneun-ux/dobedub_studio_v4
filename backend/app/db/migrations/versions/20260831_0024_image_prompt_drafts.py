"""persist Grok image prompt drafts

Revision ID: 20260831_0024
Revises: 20260817_0023
Create Date: 2026-08-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_0024"
down_revision = "20260817_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "image_prompt_drafts" in inspector.get_table_names():
        return
    op.create_table(
        "image_prompt_drafts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("asset_id", sa.String(length=64), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", sa.String(length=191), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=191), nullable=False),
        sa.Column("instruction_version", sa.String(length=64), nullable=False),
        sa.Column("positive_prompt", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_image_prompt_drafts_asset_workflow_slot", "image_prompt_drafts", ["asset_id", "workflow_id", "slot_index"], unique=False)
    op.create_index("ix_image_prompt_drafts_created_by_status", "image_prompt_drafts", ["created_by", "status"], unique=False)
    op.create_index("ix_image_prompt_drafts_workflow_id", "image_prompt_drafts", ["workflow_id"], unique=False)
    op.create_index("ix_image_prompt_drafts_status", "image_prompt_drafts", ["status"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "image_prompt_drafts" in inspector.get_table_names():
        op.drop_table("image_prompt_drafts")
