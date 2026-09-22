from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from backend.app.db.models import WorkflowDefinition, WorkflowRevision


def test_workflow_metadata_migration_creates_tables_constraints_and_indexes(tmp_path):
    database_path = tmp_path / "workflow-metadata.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database_path}"}

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        schema = inspect(engine)
        assert {"workflow_definitions", "workflow_revisions"} <= set(schema.get_table_names())
        assert {index["name"] for index in schema.get_indexes("workflow_definitions")} >= {
            "ix_workflow_definitions_status_updated",
            "ix_workflow_definitions_source_status",
        }
        assert {index["name"] for index in schema.get_indexes("workflow_revisions")} >= {
            "ix_workflow_revisions_workflow_created",
            "uq_workflow_revisions_number",
            "uq_workflow_revisions_content",
        }
        revision_foreign_keys = schema.get_foreign_keys("workflow_revisions")
        assert any(item["referred_table"] == "workflow_definitions" for item in revision_foreign_keys)
    finally:
        engine.dispose()


def test_workflow_revision_number_is_unique(db_session):
    definition = WorkflowDefinition(
        id="dynamic-a.json",
        display_name="dynamic-a",
        status="INACTIVE",
        source="ADMIN_UPLOAD",
    )
    db_session.add(definition)
    db_session.flush()
    required = {
        "workflow_id": definition.id,
        "revision": 1,
        "workflow_path": "releases/dynamic-a/1/workflow.json",
        "workflow_sha256": "a" * 64,
        "workflow_size_bytes": 2,
        "param_config_path": "releases/dynamic-a/1/paramconfig.json",
        "param_config_sha256": "b" * 64,
        "param_config_size_bytes": 2,
        "validation_status": "VALID",
        "validation_json": {},
    }
    db_session.add(WorkflowRevision(**required))
    db_session.commit()

    duplicate = dict(required)
    duplicate.update(
        workflow_path="releases/dynamic-a/duplicate/workflow.json",
        workflow_sha256="c" * 64,
        param_config_path="releases/dynamic-a/duplicate/paramconfig.json",
        param_config_sha256="d" * 64,
    )
    db_session.add(WorkflowRevision(**duplicate))
    with pytest.raises(IntegrityError):
        db_session.commit()
