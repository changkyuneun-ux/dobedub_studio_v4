"""sandbox pod selection settings

Revision ID: 20260911_0037
Revises: 20260909_0036
Create Date: 2026-09-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_0037"
down_revision = "20260909_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sandbox_pod_settings" in set(inspector.get_table_names()):
        return
    op.create_table(
        "sandbox_pod_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("selected_pod_id", sa.String(length=64), nullable=True),
        sa.Column("auto_switch_on_start_failure", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pod_priority_json", sa.JSON(), nullable=True),
        sa.Column("updated_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sandbox_pod_settings" in set(inspector.get_table_names()):
        op.drop_table("sandbox_pod_settings")
