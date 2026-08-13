"""audit logs

Revision ID: 20260811_0014
Revises: 20260810_0013
Create Date: 2026-08-11

A-04: 권한 변경, 사용자 관리(생성/수정/비밀번호 재설정/비활성화), 프롬프트 카탈로그
수정(용어/카테고리/카테고리 그룹/시스템 프롬프트), Sandbox Pod 제어, 작업 이력 삭제,
로그인 시도(A-05가 별도 테이블 없이 이 테이블의 action='login'으로 흡수)에 대한
감사 로그 테이블을 추가한다.

actor_id는 users.id에 대한 FK를 걸지 않는다 - 로그인 실패 시 제출된 id가 실제
사용자가 아닐 수 있고, 이후 탈퇴/삭제된 사용자의 과거 기록도 그대로 보존해야
하기 때문이다(느슨한 참조 문자열).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_0014"
down_revision = "20260813_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.String(length=191), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=191), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at_id", "audit_logs", ["created_at", "id"])
    op.create_index("ix_audit_logs_target", "audit_logs", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_target", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")
