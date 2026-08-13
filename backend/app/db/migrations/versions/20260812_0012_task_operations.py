"""legacy v3 durable task operations marker

Revision ID: 20260812_0012
Revises: 20260807_0011

This revision is retained so v3 RDS databases at 20260812_0013 remain part of
the v4 Alembic graph.  It deliberately performs no work in v4: the v3 RDS
already has its task_events, operation_policies and task-monitor columns, while
the v4 runtime uses its own task_execution_policies table.
"""
from __future__ import annotations


revision = "20260812_0012"
down_revision = "20260807_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
