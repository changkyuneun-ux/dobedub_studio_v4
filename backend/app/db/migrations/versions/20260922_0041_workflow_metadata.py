"""add workflow metadata and immutable revisions

Revision ID: 20260922_0041
Revises: 20260915_0040
Create Date: 2026-09-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260922_0041"
down_revision = "20260915_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(length=191), primary_key=True),
        sa.Column("display_name", sa.String(length=191), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("current_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("registered_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workflow_definitions_status", "workflow_definitions", ["status"])
    op.create_index("ix_workflow_definitions_status_updated", "workflow_definitions", ["status", "updated_at", "id"])
    op.create_index("ix_workflow_definitions_source_status", "workflow_definitions", ["source", "status"])

    op.create_table(
        "workflow_revisions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.String(length=191), sa.ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("workflow_path", sa.String(length=1024), nullable=False),
        sa.Column("workflow_sha256", sa.String(length=64), nullable=False),
        sa.Column("workflow_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("param_config_path", sa.String(length=1024), nullable=False),
        sa.Column("param_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("param_config_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("input_image_count", sa.Integer(), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("uq_workflow_revisions_number", "workflow_revisions", ["workflow_id", "revision"], unique=True)
    op.create_index(
        "uq_workflow_revisions_content",
        "workflow_revisions",
        ["workflow_id", "workflow_sha256", "param_config_sha256"],
        unique=True,
    )
    op.create_index("ix_workflow_revisions_workflow_created", "workflow_revisions", ["workflow_id", "created_at"])
    with op.batch_alter_table("workflow_definitions") as batch_op:
        batch_op.create_foreign_key(
            "fk_workflow_definitions_current_revision",
            "workflow_revisions",
            ["current_revision_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_definitions") as batch_op:
        batch_op.drop_constraint("fk_workflow_definitions_current_revision", type_="foreignkey")
    op.drop_table("workflow_revisions")
    op.drop_table("workflow_definitions")
