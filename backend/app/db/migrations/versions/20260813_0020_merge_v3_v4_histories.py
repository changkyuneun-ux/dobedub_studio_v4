"""merge legacy v3 and v4 catalog histories

Revision ID: 20260813_0020
Revises: 20260810_0013, 20260812_0013

The production RDS was last migrated by v3 while fresh v4 databases follow the
catalog hierarchy branch.  This merge node connects both histories without
changing existing data.
"""
from __future__ import annotations


revision = "20260813_0020"
down_revision = ("20260810_0013", "20260812_0013")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
