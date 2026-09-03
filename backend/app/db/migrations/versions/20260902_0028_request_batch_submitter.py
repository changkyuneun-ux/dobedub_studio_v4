"""add submitting actor to durable RunPod request batches

Revision ID: 20260902_0028
Revises: 20260902_0027
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260902_0028"
down_revision = "20260902_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("runpod_request_batches")}
    if "submitted_by" not in columns:
        op.add_column("runpod_request_batches", sa.Column("submitted_by", sa.String(length=191), nullable=True))
        # SQLite cannot add a foreign key after table creation without a batch
        # table rebuild. The column is sufficient for local compatibility; MySQL
        # and PostgreSQL retain the production referential constraint.
        if bind.dialect.name != "sqlite":
            op.create_foreign_key(
                "fk_runpod_request_batches_submitted_by_users",
                "runpod_request_batches",
                "users",
                ["submitted_by"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("runpod_request_batches")}
    if "submitted_by" in columns:
        if bind.dialect.name != "sqlite":
            op.drop_constraint("fk_runpod_request_batches_submitted_by_users", "runpod_request_batches", type_="foreignkey")
        op.drop_column("runpod_request_batches", "submitted_by")
