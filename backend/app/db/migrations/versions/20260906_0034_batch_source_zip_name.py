"""remember source zip names for batch output downloads

Revision ID: 20260906_0034
Revises: 20260904_0033
Create Date: 2026-09-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260906_0034"
down_revision = "20260904_0033"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "batch_jobs" not in set(inspector.get_table_names()):
        return
    if "source_zip_file_name" not in _columns(inspector, "batch_jobs"):
        op.add_column("batch_jobs", sa.Column("source_zip_file_name", sa.String(length=512), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "batch_jobs" not in set(inspector.get_table_names()):
        return
    if "source_zip_file_name" in _columns(inspector, "batch_jobs"):
        op.drop_column("batch_jobs", "source_zip_file_name")
