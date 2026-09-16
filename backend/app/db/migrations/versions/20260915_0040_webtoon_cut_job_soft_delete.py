"""soft delete webtoon cut jobs

Revision ID: 20260915_0040
Revises: 20260915_0039
Create Date: 2026-09-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260915_0040"
down_revision = "20260915_0039"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {item["name"] for item in inspector.get_columns(table)}


def _has_index(inspector, table: str, index_name: str) -> bool:
    return index_name in {item["name"] for item in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "webtoon_cut_jobs" not in table_names:
        return
    if not _has_column(inspector, "webtoon_cut_jobs", "deleted_at"):
        op.add_column("webtoon_cut_jobs", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    inspector = sa.inspect(bind)
    if not _has_index(inspector, "webtoon_cut_jobs", "ix_webtoon_cut_jobs_deleted_at"):
        op.create_index("ix_webtoon_cut_jobs_deleted_at", "webtoon_cut_jobs", ["deleted_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "webtoon_cut_jobs" not in table_names:
        return
    if _has_index(inspector, "webtoon_cut_jobs", "ix_webtoon_cut_jobs_deleted_at"):
        op.drop_index("ix_webtoon_cut_jobs_deleted_at", table_name="webtoon_cut_jobs")
    inspector = sa.inspect(bind)
    if _has_column(inspector, "webtoon_cut_jobs", "deleted_at"):
        op.drop_column("webtoon_cut_jobs", "deleted_at")
