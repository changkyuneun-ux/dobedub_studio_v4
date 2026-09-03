"""retire Grok instruction documents database storage

Revision ID: 20260831_0025
Revises: 20260831_0024
Create Date: 2026-08-31
"""
from __future__ import annotations

revision = "20260831_0025"
down_revision = "20260831_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Grok instruction content is a JSON runtime asset. Existing installations
    # may retain the former table physically, but application code never reads
    # or writes it and no data is deleted during this migration.
    pass


def downgrade() -> None:
    pass
