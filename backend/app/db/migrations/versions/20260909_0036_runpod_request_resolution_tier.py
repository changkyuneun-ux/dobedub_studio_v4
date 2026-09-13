"""persist RunPod resolution tier

Revision ID: 20260909_0036
Revises: 20260907_0035
Create Date: 2026-09-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260909_0036"
down_revision = "20260907_0035"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "runpod_request_items" not in set(inspector.get_table_names()):
        pass
    elif "resolution_tier" not in _columns(inspector, "runpod_request_items"):
        op.add_column(
            "runpod_request_items",
            sa.Column("resolution_tier", sa.String(length=16), nullable=False, server_default="sd"),
        )
    inspector = sa.inspect(bind)
    if "batch_jobs" in set(inspector.get_table_names()) and "resolution_tier" not in _columns(inspector, "batch_jobs"):
        op.add_column(
            "batch_jobs",
            sa.Column("resolution_tier", sa.String(length=16), nullable=False, server_default="sd"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "runpod_request_items" in set(inspector.get_table_names()) and "resolution_tier" in _columns(inspector, "runpod_request_items"):
        op.drop_column("runpod_request_items", "resolution_tier")
    inspector = sa.inspect(bind)
    if "batch_jobs" in set(inspector.get_table_names()) and "resolution_tier" in _columns(inspector, "batch_jobs"):
        op.drop_column("batch_jobs", "resolution_tier")
