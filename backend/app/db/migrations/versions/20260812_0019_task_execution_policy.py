"""task execution policy

Revision ID: 20260812_0019
Revises: 20260812_0018
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_0019"
down_revision = "20260812_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_execution_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("max_active_tasks_per_user", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("max_active_tasks_total", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("updated_by", sa.String(length=191), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        "INSERT INTO task_execution_policies "
        "(id, max_active_tasks_per_user, max_active_tasks_total, created_at, updated_at) "
        "VALUES (1, 3, 10, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    op.drop_table("task_execution_policies")
