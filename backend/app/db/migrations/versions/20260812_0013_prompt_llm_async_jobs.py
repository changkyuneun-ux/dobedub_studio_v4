"""legacy v3 prompt LLM async jobs marker

Revision ID: 20260812_0013
Revises: 20260812_0012

The v3 RDS already contains external_job_id and failure_message on
prompt_generation_requests.  This no-op marker lets Alembic resolve that
existing RDS revision without replaying or mutating prior application data.
"""
from __future__ import annotations


revision = "20260812_0013"
down_revision = "20260812_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
