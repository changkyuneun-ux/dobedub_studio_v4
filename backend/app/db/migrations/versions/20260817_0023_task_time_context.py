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
        # MySQL does not permit server defaults on JSON columns. Add the
        # nullable column first, backfill existing rows, then enforce it.
        op.add_column(
            "workflow_tasks",
            sa.Column("time_context_json", sa.JSON(), nullable=True),
        )
        op.execute("UPDATE workflow_tasks SET time_context_json = '{}' WHERE time_context_json IS NULL")
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("workflow_tasks") as batch_op:
                batch_op.alter_column("time_context_json", existing_type=sa.JSON(), nullable=False)
        else:
            op.alter_column("workflow_tasks", "time_context_json", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    if "time_context_json" in _columns():
        op.drop_column("workflow_tasks", "time_context_json")
