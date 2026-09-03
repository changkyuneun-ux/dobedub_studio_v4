"""drop duplicated RunPod result media from workflow_tasks provider columns

RunPod returns finished media inline as base64 (``output.images[*].data``).
``output_service.save_runpod_outputs()`` already decoded those bytes into the
asset store, so the copy kept in ``runpod_status_json`` was a duplicate that no
response ever used - only filename/executionTime/delayTime/jobId are read back.
It made every task read drag up to 1.6MB per row through memory, which is why
the prompt history screen was slow and why ECS ran out of memory.

This migration removes the duplicated body and keeps the response envelope.
A task whose output files are missing from storage is skipped, so the base64
stays available as the only remaining copy of that result.

Revision ID: 20260903_0032
Revises: 20260903_0031
Create Date: 2026-09-03
"""
from __future__ import annotations

import json
import os

import sqlalchemy as sa
from alembic import op


revision = "20260903_0032"
down_revision = "20260903_0031"
branch_labels = None
depends_on = None


# Frozen copy of task_tracking_service.prune_provider_payload. Migrations must
# not change behaviour when the application helper is later edited.
MAX_STRING_LENGTH = 4096


def _prune(value):
    if isinstance(value, dict):
        pruned: dict = {}
        for key, item in value.items():
            if isinstance(item, str) and len(item) > MAX_STRING_LENGTH:
                pruned[key] = ""
                pruned[f"{key}Bytes"] = len(item)
                pruned[f"{key}Stripped"] = True
                continue
            pruned[key] = _prune(item)
        return pruned
    if isinstance(value, list):
        return [_prune(item) for item in value]
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return ""
    return value


def _loads(raw):
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _output_file_state(connection) -> tuple[set[str], set[str]]:
    """Return (tasks with a missing output file, tasks with any output link).

    A task whose file is gone keeps its provider payload: that base64 is then
    the only surviving copy of the result.
    """
    rows = connection.execute(
        sa.text(
            """
            SELECT o.task_id, a.storage_backend, a.storage_key
            FROM task_output_assets o
            JOIN assets a ON a.id = o.asset_id
            """
        )
    ).all()
    missing: set[str] = set()
    linked: set[str] = set()
    for task_id, storage_backend, storage_key in rows:
        linked.add(str(task_id))
        if str(storage_backend or "local") != "local":
            continue
        if not storage_key or not os.path.isfile(str(storage_key)):
            missing.add(str(task_id))
    return missing, linked


def upgrade() -> None:
    connection = op.get_bind()
    missing, linked = _output_file_state(connection)
    task_ids = [
        str(row[0])
        for row in connection.execute(sa.text("SELECT id FROM workflow_tasks")).all()
    ]
    for task_id in task_ids:
        # A task with no output link never produced a file, so its provider
        # payload is also the only copy. Skip it for the same reason.
        if task_id in missing or task_id not in linked:
            continue
        # One row at a time: the whole point is not to hold every payload in
        # memory at once.
        row = connection.execute(
            sa.text(
                "SELECT runpod_status_json, runpod_submit_json"
                " FROM workflow_tasks WHERE id = :task_id"
            ),
            {"task_id": task_id},
        ).first()
        if row is None:
            continue
        status_payload = _loads(row[0])
        submit_payload = _loads(row[1])
        pruned_status = _prune(status_payload) if status_payload is not None else None
        pruned_submit = _prune(submit_payload) if submit_payload is not None else None
        if pruned_status == status_payload and pruned_submit == submit_payload:
            continue
        connection.execute(
            sa.text(
                "UPDATE workflow_tasks"
                " SET runpod_status_json = :status_json, runpod_submit_json = :submit_json"
                " WHERE id = :task_id"
            ),
            {
                "status_json": json.dumps(pruned_status if pruned_status is not None else {}, ensure_ascii=False),
                "submit_json": json.dumps(pruned_submit if pruned_submit is not None else {}, ensure_ascii=False),
                "task_id": task_id,
            },
        )


def downgrade() -> None:
    # The removed bytes are a duplicate of the stored asset files and cannot be
    # rebuilt from this table. Restoring the column is not possible.
    pass
