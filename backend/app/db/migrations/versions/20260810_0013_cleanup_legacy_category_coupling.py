"""cleanup legacy category coupling

Revision ID: 20260810_0013
Revises: 20260810_0012
Create Date: 2026-08-10

B-06 step 4 (정리). This migration does NOT drop prompt_terms/prompt_categories
themselves - TASKS.md explicitly allows deferring that to a separate release
("별도 릴리스로 미루어도 무방"), and this app still needs *somewhere* to store
new keyword content (label/prompt text/etc.) since prompt_subcategory_keywords
has no content columns of its own. What it does remove is the structural
coupling that step 3's discrepancy report flagged: prompt_terms.category_id
was a NOT NULL FK to prompt_categories.id, which meant a brand-new
PromptSubcategory (one with no legacy_category_id, e.g. anything created via
POST /api/prompts/categories after step 3) could never receive new terms -
upsert_prompt_keyword() had to reject that case with a 400.

This migration relaxes prompt_terms.category_id to nullable (keeps the FK for
any historical rows that still reference a real legacy category; new rows can
use category_id = NULL).  It intentionally retains
prompt_subcategories.legacy_category_id: v3 production databases can contain
valuable legacy mapping data in that column, and schema migration must not
discard operating data merely because v4 service code no longer requires it.

Both alterations use batch mode because SQLite (the dev/test backend) cannot
alter a column's nullability or drop a column that carries a UNIQUE/FK
constraint via a plain ALTER TABLE - it has to rebuild the table. Batch mode
is a no-op passthrough on backends that support ALTER COLUMN/DROP COLUMN
directly (e.g. MySQL, see scripts/mysql_migration_smoke_check.py), so this
migration is safe on both.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260810_0013"
down_revision = "20260810_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_terms") as batch_op:
        batch_op.alter_column("category_id", existing_type=sa.Integer(), nullable=True)

    # Keep legacy_category_id and its values. Extra database columns are safe
    # for the v4 ORM and preserve the prior catalog mapping for rollback/audit.


def downgrade() -> None:
    bind = op.get_bind()

    remaining_null = bind.execute(sa.text(
        "select count(*) from prompt_terms where category_id is null"
    )).scalar()
    if remaining_null:
        # These are terms whose only subcategory link (if any) was itself
        # never connected to a legacy category - i.e. genuinely created after
        # step 4. There is no legacy category to point them at, so the old
        # NOT NULL invariant cannot be restored without deleting data. Leave
        # category_id nullable rather than raise; downgrading past step 4 on
        # a database that has taken step-4-era writes is a best-effort,
        # documented-lossy operation, not a hard failure.
        print(
            "[0013_relax_prompt_term_category] downgrade: "
            f"{remaining_null} prompt_terms row(s) have no legacy category to "
            "restore category_id from (created after step 4) - leaving "
            "prompt_terms.category_id nullable instead of restoring NOT NULL."
        )
        return

    with op.batch_alter_table("prompt_terms") as batch_op:
        batch_op.alter_column("category_id", existing_type=sa.Integer(), nullable=False)
