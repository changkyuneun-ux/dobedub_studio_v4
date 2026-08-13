"""asset input image dimensions

Revision ID: 20260813_0021
Revises: 20260812_0019
Create Date: 2026-08-13

Records the original dimensions for uploaded image assets. Existing assets
remain unchanged and retain NULL until they are uploaded again.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_0021"
down_revision = "20260812_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("image_width", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("image_height", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "image_height")
    op.drop_column("assets", "image_width")
