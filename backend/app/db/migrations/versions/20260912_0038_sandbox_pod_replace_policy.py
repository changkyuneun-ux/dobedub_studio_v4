"""sandbox pod replace-same-gpu policy

Revision ID: 20260912_0038
Revises: 20260911_0037
Create Date: 2026-09-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260912_0038"
down_revision = "20260911_0037"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sandbox_pod_settings" not in set(inspector.get_table_names()):
        return
    if "replace_same_gpu_pods" not in _columns(inspector, "sandbox_pod_settings"):
        op.add_column(
            "sandbox_pod_settings",
            sa.Column("replace_same_gpu_pods", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "sandbox_pod_settings" in set(inspector.get_table_names()) and "replace_same_gpu_pods" in _columns(inspector, "sandbox_pod_settings"):
        op.drop_column("sandbox_pod_settings", "replace_same_gpu_pods")
