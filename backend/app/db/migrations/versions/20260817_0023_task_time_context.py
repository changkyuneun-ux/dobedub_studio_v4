"""persist task timestamp source context

Revision ID: 20260817_0023
Revises: 20260813_0022
Create Date: 2026-08-17

RunPod worker logs use KST while ECS container time is UTC. Store the raw
provider values and normalized UTC/KST pairs without rewriting legacy task
timestamps whose original timezone cannot be determined safely.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260817_0023"
down_revision = "20260813_0022"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workflow_tasks")}


def upgrade() -> None:
    if "time_context_json" not in _columns():
        op.add_column(
            "workflow_tasks",
            sa.Column("time_context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    if "time_context_json" in _columns():
        op.drop_column("workflow_tasks", "time_context_json")
