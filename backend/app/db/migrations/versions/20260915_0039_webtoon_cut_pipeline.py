"""server-side webtoon cut pipeline

Revision ID: 20260915_0039
Revises: 20260912_0038
Create Date: 2026-09-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260915_0039"
down_revision = "20260912_0038"
branch_labels = None
depends_on = None


def _has_table(inspector, table: str) -> bool:
    return table in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "webtoon_cut_jobs"):
        op.create_table(
            "webtoon_cut_jobs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("input_kind", sa.String(length=32), nullable=False),
            sa.Column("source_asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=False),
            sa.Column("display_name", sa.String(length=512), nullable=False),
            sa.Column("safe_stem", sa.String(length=191), nullable=False),
            sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completed_units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("generated_cut_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("review_required_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_unit_label", sa.String(length=512), nullable=True),
            sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("manifest_asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=True),
            sa.Column("summary_asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(length=191), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_webtoon_cut_jobs_status", "webtoon_cut_jobs", ["status"])
        op.create_index("ix_webtoon_cut_jobs_input_kind", "webtoon_cut_jobs", ["input_kind"])
        op.create_index("ix_webtoon_cut_jobs_source_asset_id", "webtoon_cut_jobs", ["source_asset_id"])
        op.create_index("ix_webtoon_cut_jobs_created_by", "webtoon_cut_jobs", ["created_by"])
        op.create_index("ix_webtoon_cut_jobs_created_by_status", "webtoon_cut_jobs", ["created_by", "status"])
        op.create_index("ix_webtoon_cut_jobs_created_at_id", "webtoon_cut_jobs", ["created_at", "id"])

    if not _has_table(inspector, "webtoon_cut_sources"):
        op.create_table(
            "webtoon_cut_sources",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("job_id", sa.String(length=64), sa.ForeignKey("webtoon_cut_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=False),
            sa.Column("input_kind", sa.String(length=32), nullable=False),
            sa.Column("display_name", sa.String(length=512), nullable=False),
            sa.Column("display_path", sa.String(length=1024), nullable=False),
            sa.Column("zip_entry_path", sa.String(length=1024), nullable=True),
            sa.Column("safe_stem", sa.String(length=191), nullable=False),
            sa.Column("mime_type", sa.String(length=191), nullable=False, server_default="application/octet-stream"),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sort_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_webtoon_cut_sources_job_order", "webtoon_cut_sources", ["job_id", "sort_index"])
        op.create_index("ix_webtoon_cut_sources_display_path", "webtoon_cut_sources", ["display_path"])

    if not _has_table(inspector, "webtoon_cut_units"):
        op.create_table(
            "webtoon_cut_units",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("job_id", sa.String(length=64), sa.ForeignKey("webtoon_cut_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_id", sa.String(length=64), sa.ForeignKey("webtoon_cut_sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("unit_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("display_label", sa.String(length=512), nullable=False),
            sa.Column("render_asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=True),
            sa.Column("debug_asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=True),
            sa.Column("detected_cut_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("flags_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_webtoon_cut_units_status", "webtoon_cut_units", ["status"])
        op.create_index("ix_webtoon_cut_units_job_status", "webtoon_cut_units", ["job_id", "status"])
        op.create_index("ix_webtoon_cut_units_job_order", "webtoon_cut_units", ["job_id", "source_id", "page_number", "unit_index"])

    if not _has_table(inspector, "webtoon_cut_outputs"):
        op.create_table(
            "webtoon_cut_outputs",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("job_id", sa.String(length=64), sa.ForeignKey("webtoon_cut_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_id", sa.String(length=64), sa.ForeignKey("webtoon_cut_sources.id", ondelete="CASCADE"), nullable=True),
            sa.Column("unit_id", sa.String(length=64), sa.ForeignKey("webtoon_cut_units.id", ondelete="SET NULL"), nullable=True),
            sa.Column("asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
            sa.Column("display_path", sa.String(length=1024), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("cut_index", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("flags_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("used_in_prompt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("used_in_batch_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("i2v_result_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(length=191), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_webtoon_cut_outputs_asset_id", "webtoon_cut_outputs", ["asset_id"])
        op.create_index("ix_webtoon_cut_outputs_status", "webtoon_cut_outputs", ["status"])
        op.create_index("ix_webtoon_cut_outputs_created_by", "webtoon_cut_outputs", ["created_by"])
        op.create_index("ix_webtoon_cut_outputs_job_page_cut", "webtoon_cut_outputs", ["job_id", "page_number", "cut_index"])
        op.create_index("ix_webtoon_cut_outputs_job_status", "webtoon_cut_outputs", ["job_id", "status"])
        op.create_index("ix_webtoon_cut_outputs_display_path", "webtoon_cut_outputs", ["display_path"])

    if not _has_table(inspector, "webtoon_cut_downloads"):
        op.create_table(
            "webtoon_cut_downloads",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("job_id", sa.String(length=64), sa.ForeignKey("webtoon_cut_jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("asset_id", sa.String(length=64), sa.ForeignKey("assets.id"), nullable=False),
            sa.Column("selection_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.String(length=191), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_webtoon_cut_downloads_created_by", "webtoon_cut_downloads", ["created_by"])
        op.create_index("ix_webtoon_cut_downloads_job_created", "webtoon_cut_downloads", ["job_id", "created_at"])


def downgrade() -> None:
    for table in (
        "webtoon_cut_downloads",
        "webtoon_cut_outputs",
        "webtoon_cut_units",
        "webtoon_cut_sources",
        "webtoon_cut_jobs",
    ):
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        if table in set(inspector.get_table_names()):
            op.drop_table(table)
