"""restore OPERATOR role permissions

Revision ID: 20260903_0031
Revises: 20260903_0030
Create Date: 2026-09-03
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "20260903_0031"
down_revision = "20260903_0030"
branch_labels = None
depends_on = None


OPERATOR_ROLE = {
    "code": "OPERATOR",
    "name": "Operator",
    "description": "영상 생성, 작업 조회, 프롬프트 리뷰 등 실무 작업 권한",
    "level": 20,
    "sort_order": 30,
}

OPERATOR_PERMISSIONS = [
    ("workflows:read", "workflows", "read", "워크플로우 조회", "워크플로우 목록과 메타데이터 조회", 40),
    ("prompts:build", "prompts", "build", "프롬프트 생성", "Prompt Builder와 Qwen 프롬프트 생성", 60),
    ("prompts:reuse", "prompts", "reuse", "프롬프트 재사용", "재사용 가능 프롬프트 검색과 적용", 61),
    ("prompts:review", "prompts", "review", "프롬프트 리뷰", "품질 등급, 코멘트, 재사용 가능 여부 관리", 62),
    ("jobs:run", "jobs", "run", "작업 실행", "영상 생성 작업 제출", 70),
    ("jobs:cancel", "jobs", "cancel", "작업 취소", "RunPod 생성 작업 취소", 71),
    ("history:read", "history", "read", "작업 이력 조회", "작업 결과와 이력 조회", 80),
    ("metadata:read", "metadata", "read", "메타데이터 조회", "Workflow metadata 조회", 90),
    ("system:read", "system", "read", "시스템 상태 조회", "ComfyUI/Qwen/DB 상태 확인", 100),
    ("manual:read", "manual", "read", "사용자 매뉴얼 조회", "사용자 매뉴얼 조회", 110),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.utcnow()
    _ensure_operator_role(bind, now)
    _ensure_permissions(bind, now)
    _ensure_operator_role_permissions(bind, now)


def downgrade() -> None:
    # This migration repairs production RBAC drift. Downgrade intentionally
    # keeps the repaired permissions to avoid removing operator access.
    pass


def _ensure_operator_role(bind, now: datetime) -> None:
    exists = bind.execute(
        sa.text("select 1 from roles where code = :code"),
        {"code": OPERATOR_ROLE["code"]},
    ).scalar()
    if exists:
        return
    bind.execute(
        sa.text(
            "insert into roles "
            "(code, name, description, level, is_system, is_active, sort_order, created_at, updated_at) "
            "values (:code, :name, :description, :level, :is_system, :is_active, :sort_order, :created_at, :updated_at)"
        ),
        {
            **OPERATOR_ROLE,
            "is_system": True,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        },
    )


def _ensure_permissions(bind, now: datetime) -> None:
    for code, domain, action, name, description, sort_order in OPERATOR_PERMISSIONS:
        exists = bind.execute(
            sa.text("select 1 from permissions where code = :code"),
            {"code": code},
        ).scalar()
        if exists:
            continue
        bind.execute(
            sa.text(
                "insert into permissions "
                "(code, domain, action, name, description, is_system, is_active, sort_order, created_at, updated_at) "
                "values (:code, :domain, :action, :name, :description, :is_system, :is_active, :sort_order, :created_at, :updated_at)"
            ),
            {
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
            },
        )


def _ensure_operator_role_permissions(bind, now: datetime) -> None:
    role_id = bind.execute(
        sa.text("select id from roles where code = :code"),
        {"code": OPERATOR_ROLE["code"]},
    ).scalar_one()
    for code, _domain, _action, _name, _description, _sort_order in OPERATOR_PERMISSIONS:
        permission_id = bind.execute(
            sa.text("select id from permissions where code = :code"),
            {"code": code},
        ).scalar_one()
        exists = bind.execute(
            sa.text(
                "select 1 from role_permissions "
                "where role_id = :role_id and permission_id = :permission_id"
            ),
            {"role_id": role_id, "permission_id": permission_id},
        ).scalar()
        if exists:
            continue
        bind.execute(
            sa.text(
                "insert into role_permissions (role_id, permission_id, created_at) "
                "values (:role_id, :permission_id, :created_at)"
            ),
            {"role_id": role_id, "permission_id": permission_id, "created_at": now},
        )
