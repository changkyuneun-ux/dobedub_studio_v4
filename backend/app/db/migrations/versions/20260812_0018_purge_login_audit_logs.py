"""purge login audit logs

Revision ID: 20260812_0018
Revises: 20260811_0017
Create Date: 2026-08-12

2026-08-12: 사용자 요청 - 감사 로그(audit_logs)는 "어드민 정보 수정사항"만 남기기로
범위를 좁혔다. `action="login"`은 로그인 시도 기록(A-05, auth.py)이지 관리자
정보 수정이 아니라서 이제 기록 대상에서 빠졌는데(auth.py 코드 변경), 그 전까지
이미 쌓여 있던 login 레코드는 이 마이그레이션으로 일괄 삭제한다. `history.delete`
(작업 이력 삭제, history.py)도 같은 이유로 기록을 중단했지만 기존 레코드를
지워달라는 요청은 없었으므로 여기서는 건드리지 않는다 - 필요해지면 별도
마이그레이션으로 처리한다.

downgrade()는 삭제된 로그를 복구할 수 없다(데이터 손실이 의도된 동작) - 다른
정리성 마이그레이션(20260810_0013)과 같은 방식으로 안내만 출력한다.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_0018"
down_revision = "20260811_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("delete from audit_logs where action = 'login'"))


def downgrade() -> None:
    print(
        "[0018_purge_login_audit_logs] downgrade: 삭제된 login 감사 로그는 "
        "복구할 수 없습니다(의도된 데이터 정리) - downgrade는 아무 것도 하지 "
        "않습니다."
    )
