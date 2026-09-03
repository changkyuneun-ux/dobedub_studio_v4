"""add jobs manage permission

Revision ID: 20260902_0029
Revises: 20260902_0028
Create Date: 2026-09-02
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "20260902_0029"
down_revision = "20260902_0028"
branch_labels = None
depends_on = None


PERMISSION = (
    "jobs:manage",
    "jobs",
    "manage",
    "RunPod 요청 관리",
    "다른 작업자의 RunPod 요청 배치 조회 및 관리",
    72,
)


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("select 1 from permissions where code = :code"),
        {"code": PERMISSION[0]},
    ).scalar()
    if exists:
        return

    now = datetime.utcnow()
    permission_table = sa.table(
        "permissions",
        sa.column("code", sa.String()),
        sa.column("domain", sa.String()),
        sa.column("action", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    code, domain, action, name, description, sort_order = PERMISSION
    op.bulk_insert(permission_table, [{
        "code": code,
        "domain": domain,
        "action": action,
        "name": name,
        "description": description,
        "is_system": True,
        "is_active": True,
        "sort_order": sort_order,
        "created_at": now,
        "updated_at": now,
    }])


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("delete from permissions where code = :code"),
        {"code": PERMISSION[0]},
    )
