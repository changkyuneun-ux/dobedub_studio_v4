#!/usr/bin/env python3
"""Run Alembic migrations against a temporary SQLite database.

This verifies the migration graph without requiring a local MySQL server. ECS
and RDS use the same Alembic scripts with DATABASE_URL set to a MySQL URL.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


EXPECTED_TABLES = {
    "users",
    "assets",
    "collections",
    "collection_items",
    "workflow_tasks",
    "task_execution_policies",
    "task_input_assets",
    "task_output_assets",
    "config_snapshots",
    "prompt_entries",
    "prompt_categories",
    "prompt_category_terms",
    "prompt_terms",
    "prompt_term_relations",
    "prompt_term_renderings",
    "prompt_rules",
    "prompt_templates",
    "prompt_generation_requests",
    "prompt_generation_outputs",
    "prompt_feedback",
    "model_profiles",
    "reports",
}


def main():
    with tempfile.TemporaryDirectory(prefix="dobedub-db-smoke-") as tmp:
        database_path = Path(tmp) / "dobedub-smoke.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        from scripts.upgrade_database import migration_state

        before_upgrade = migration_state(config)
        assert before_upgrade["migrationRequired"] is True, before_upgrade
        # 0018 must not delete an existing login audit record while advancing the
        # RDS schema.  Keep the check explicit because production data retention
        # is more important than the revision's historical filename.
        command.upgrade(config, "20260811_0017")
        engine = create_engine(os.environ["DATABASE_URL"], future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into audit_logs "
                    "(actor_id, action, target_type, target_id, created_at) "
                    "values ('user_smoke', 'login', 'session', 'user_smoke', CURRENT_TIMESTAMP)"
                )
            )

        command.upgrade(config, "head")
        after_upgrade = migration_state(config)
        assert after_upgrade["migrationRequired"] is False, after_upgrade

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        missing = EXPECTED_TABLES - tables
        assert not missing, f"Missing tables: {sorted(missing)}"
        with engine.begin() as connection:
            login_audit_count = connection.execute(
                text("select count(*) from audit_logs where action = 'login'")
            ).scalar_one()
            assert login_audit_count == 1, login_audit_count
            policy = connection.execute(
                text(
                    "select max_active_tasks_per_user, max_active_tasks_total "
                    "from task_execution_policies where id = 1"
                )
            ).one()
            assert policy == (3, 10), policy
            connection.execute(text("insert into users (id, name, role, created_at, updated_at) values ('user_smoke', 'Smoke User', 'operator', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            count = connection.execute(text("select count(*) from users")).scalar_one()
            assert count == 1

    # The production RDS was last advanced by v3, whose Alembic history ends
    # at 20260812_0013.  Verify that v4 can bridge from that precise revision
    # without replaying catalog seed/backfill writes or dropping the legacy
    # mapping column that contains live operating data.
    with tempfile.TemporaryDirectory(prefix="dobedub-db-legacy-bridge-") as tmp:
        database_path = Path(tmp) / "dobedub-legacy-bridge.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
        os.environ["PRESERVE_EXISTING_CATALOG_DATA"] = "1"
        config = Config(str(PROJECT_ROOT / "alembic.ini"))

        command.upgrade(config, "20260812_0013")
        engine = create_engine(os.environ["DATABASE_URL"], future=True)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into prompt_scopes "
                    "(code, name_ko, name_en, sort_order, is_active, created_at, updated_at) "
                    "values ('LEGACY_SCOPE', 'Legacy', 'Legacy', 99, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        command.upgrade(config, "head")
        bridged_state = migration_state(config)
        assert bridged_state["migrationRequired"] is False, bridged_state

        inspector = inspect(engine)
        assert "legacy_category_id" in {
            column["name"] for column in inspector.get_columns("prompt_subcategories")
        }
        category_id = next(
            column for column in inspector.get_columns("prompt_terms") if column["name"] == "category_id"
        )
        assert category_id["nullable"] is True, category_id
        with engine.begin() as connection:
            legacy_scope_count = connection.execute(
                text("select count(*) from prompt_scopes where code = 'LEGACY_SCOPE'")
            ).scalar_one()
            assert legacy_scope_count == 1, legacy_scope_count
            policy = connection.execute(
                text(
                    "select max_active_tasks_per_user, max_active_tasks_total "
                    "from task_execution_policies where id = 1"
                )
            ).one()
            assert policy == (3, 10), policy

    os.environ.pop("PRESERVE_EXISTING_CATALOG_DATA", None)

    print("OK db migration smoke check passed")


if __name__ == "__main__":
    main()
