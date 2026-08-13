"""preserve existing login audit logs

Revision ID: 20260812_0018
Revises: 20260811_0017
Create Date: 2026-08-12

로그인 시도는 새 감사 로그 작성 대상에서 제외되었지만, 이미 저장된 로그인 감사
로그는 운영 데이터다. 운영 RDS migration은 기존 업무 데이터를 변경하지 않는다는
원칙에 따라 이 revision은 schema graph를 연결하는 no-op으로 유지한다.

이전 코드에 있던 `delete from audit_logs where action = 'login'`은 RDS가 아직 이
revision을 적용하지 않은 환경에서 과거 데이터를 삭제하므로 제거했다. 별도의 데이터
정리 작업은 backup과 명시적 운영 승인을 받은 전용 작업으로만 수행한다.
"""
from __future__ import annotations

from alembic import op


revision = "20260812_0018"
down_revision = "20260811_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Intentionally no-op: never delete historical audit records during schema migration.
    pass


def downgrade() -> None:
    # No schema or data change was made in upgrade.
    pass
