"""persist RunPod prompt LLM job tracking

Revision ID: 20260813_0022
Revises: 20260813_0021
Create Date: 2026-08-13

Prompt LLM requests used to wait for the full `/runsync` response.  Store the
RunPod job id and terminal failure message so `/run` + `/status` polling can
survive browser, API, and worker cold-start boundaries.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_0022"
down_revision = "20260813_0021"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("prompt_generation_requests")}


def _indexes() -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("prompt_generation_requests")}


def upgrade() -> None:
    columns = _columns()
    if "external_job_id" not in columns:
        op.add_column("prompt_generation_requests", sa.Column("external_job_id", sa.String(length=128), nullable=True))
    if "failure_message" not in columns:
        op.add_column("prompt_generation_requests", sa.Column("failure_message", sa.Text(), nullable=True))
    if "ix_prompt_generation_requests_external_job_id" not in _indexes():
        op.create_index("ix_prompt_generation_requests_external_job_id", "prompt_generation_requests", ["external_job_id"], unique=False)


def downgrade() -> None:
    indexes = _indexes()
    if "ix_prompt_generation_requests_external_job_id" in indexes:
        op.drop_index("ix_prompt_generation_requests_external_job_id", table_name="prompt_generation_requests")
    columns = _columns()
    if "failure_message" in columns:
        op.drop_column("prompt_generation_requests", "failure_message")
    if "external_job_id" in columns:
        op.drop_column("prompt_generation_requests", "external_job_id")
