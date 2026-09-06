"""Recover RunPod request items whose WorkflowTask was never materialized."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from backend.app.db.models import RunpodRequestBatch, RunpodRequestItem, User, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services.runpod_request_batch_service import attach_task_to_request_item, mark_request_item_failed

STALE_ORPHAN_ITEM_SECONDS = 300
MAX_MATERIALIZE_ATTEMPTS = 3
MATERIALIZE_LIMIT_PER_CYCLE = 20


def materialize_orphan_request_items() -> dict[str, Any]:
    from backend.app.services import studio_api_service

    db = SessionLocal()
    try:
        claimed = claim_orphan_request_items(db, limit=MATERIALIZE_LIMIT_PER_CYCLE)
    finally:
        db.close()

    materialized = 0
    failed = 0
    for item_id, owner_id, claimed_at, attempts in claimed:
        link_db = SessionLocal()
        try:
            existing_task_id = link_db.scalar(
                select(WorkflowTask.id).where(
                    WorkflowTask.request_item_id == item_id,
                    WorkflowTask.deleted_at.is_(None),
                )
            )
            if existing_task_id:
                if attach_task_to_request_item(
                    link_db,
                    item_id=item_id,
                    task_id=str(existing_task_id),
                    materialization_claimed_at=claimed_at,
                ):
                    materialized += 1
                continue
        finally:
            link_db.close()

        try:
            recheck_db = SessionLocal()
            try:
                if not still_owns_orphan_claim(recheck_db, item_id=item_id, claimed_at=claimed_at):
                    continue
            finally:
                recheck_db.close()
            job_payload = studio_api_service.job_payload_from_request_item(item_id, user={"id": owner_id}, worker_id=owner_id)
            job = studio_api_service.create_job(job_payload, user=_submitter_user(owner_id))
            attach_db = SessionLocal()
            try:
                if attach_task_to_request_item(
                    attach_db,
                    item_id=item_id,
                    task_id=job["taskId"],
                    materialization_claimed_at=claimed_at,
                ):
                    materialized += 1
            finally:
                attach_db.close()
        except Exception as exc:  # noqa: BLE001
            if attempts >= MAX_MATERIALIZE_ATTEMPTS:
                fail_db = SessionLocal()
                try:
                    if mark_request_item_failed(
                        fail_db,
                        item_id=item_id,
                        message=f"복구 {attempts}회 실패: {exc}",
                        materialization_claimed_at=claimed_at,
                    ):
                        failed += 1
                finally:
                    fail_db.close()
            else:
                release_db = SessionLocal()
                try:
                    release_orphan_claim(release_db, item_id=item_id, claimed_at=claimed_at)
                finally:
                    release_db.close()
    return {"materialized": materialized, "failed": failed}


def claim_orphan_request_items(db, *, limit: int) -> list[tuple[str, str, datetime, int]]:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=STALE_ORPHAN_ITEM_SECONDS)
    candidates = db.execute(
        select(RunpodRequestItem.id, RunpodRequestBatch.created_by)
        .join(RunpodRequestBatch, RunpodRequestBatch.id == RunpodRequestItem.request_batch_id)
        .where(
            RunpodRequestItem.task_id.is_(None),
            RunpodRequestItem.status == "PENDING_SUBMIT",
            RunpodRequestItem.created_at <= cutoff,
            or_(
                RunpodRequestItem.materialization_claimed_at.is_(None),
                RunpodRequestItem.materialization_claimed_at <= cutoff,
            ),
        )
        .order_by(RunpodRequestItem.created_at.asc(), RunpodRequestItem.id.asc())
        .limit(limit)
    ).all()
    claimed_ids: list[str] = []
    for item_id, owner_id in candidates:
        if not owner_id:
            continue
        result = db.execute(
            RunpodRequestItem.__table__.update()
            .where(
                RunpodRequestItem.id == item_id,
                RunpodRequestItem.task_id.is_(None),
                RunpodRequestItem.status == "PENDING_SUBMIT",
                or_(
                    RunpodRequestItem.materialization_claimed_at.is_(None),
                    RunpodRequestItem.materialization_claimed_at <= cutoff,
                ),
            )
            .values(
                materialization_claimed_at=now,
                materialization_attempts=RunpodRequestItem.materialization_attempts + 1,
            )
        )
        if result.rowcount:
            claimed_ids.append(str(item_id))
    db.commit()
    if not claimed_ids:
        return []
    return [
        (str(item_id), str(owner_id), claimed_at, int(attempts or 0))
        for item_id, owner_id, claimed_at, attempts in db.execute(
            select(
                RunpodRequestItem.id,
                RunpodRequestBatch.created_by,
                RunpodRequestItem.materialization_claimed_at,
                RunpodRequestItem.materialization_attempts,
            )
            .join(RunpodRequestBatch, RunpodRequestBatch.id == RunpodRequestItem.request_batch_id)
            .where(RunpodRequestItem.id.in_(claimed_ids))
        ).all()
        if claimed_at is not None
    ]


def still_owns_orphan_claim(db, *, item_id: str, claimed_at: datetime) -> bool:
    row = db.scalar(
        select(RunpodRequestItem.id).where(
            RunpodRequestItem.id == item_id,
            RunpodRequestItem.materialization_claimed_at == claimed_at,
        )
    )
    return row is not None


def release_orphan_claim(db, *, item_id: str, claimed_at: datetime) -> None:
    db.execute(
        RunpodRequestItem.__table__.update()
        .where(RunpodRequestItem.id == item_id, RunpodRequestItem.materialization_claimed_at == claimed_at)
        .values(materialization_claimed_at=None)
    )
    db.commit()


def _submitter_user(owner_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        user = db.get(User, owner_id)
        if user is None:
            return {"id": owner_id}
        return {"id": user.id, "name": user.name, "role": user.role, "permissions": user.permissions_json or []}
    finally:
        db.close()
