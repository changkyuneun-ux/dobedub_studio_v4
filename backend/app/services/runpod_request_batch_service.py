"""Durable RunPod request-batch state and immutable item snapshots."""
from __future__ import annotations

from collections import Counter
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import now_seoul_naive
from backend.app.db.models import Asset, ImagePromptDraft, RunpodRequestBatch, RunpodRequestItem, User, WorkflowTask
from backend.app.services import workflow_service
from backend.app.services.workflow_patch_service import normalize_resolution_tier
from backend.app.services.workflow_visibility import canonical_workflow_id


ALLOWED_FRAMES: frozenset[int] = frozenset({49, 81})
SD_PIXEL_LIMIT = 409_600


def create_request_batch(
    db: Session,
    *,
    items: list[dict],
    created_by: str,
    submitted_by: str | None = None,
    batch_job_id: str | None = None,
) -> dict:
    """Persist immutable RunPod request items from prompt-draft selections.

    A request item deliberately owns its workflow, prompt text and frame length.
    The source draft remains editable for later work, while queued or executing
    RunPod work cannot be mutated by a browser navigation or a later draft edit.
    """
    normalized_items = _normalize_requested_items(items)
    if not normalized_items:
        raise ValueError("RunPod 요청에 추가할 프롬프트를 하나 이상 선택하세요.")

    drafts = db.scalars(
        select(ImagePromptDraft).where(
            ImagePromptDraft.id.in_([item["promptDraftId"] for item in normalized_items]),
            ImagePromptDraft.created_by == created_by,
        )
    ).all()
    by_id = {draft.id: draft for draft in drafts}
    missing = [item["promptDraftId"] for item in normalized_items if item["promptDraftId"] not in by_id]
    if missing:
        raise ValueError("선택한 프롬프트 초안을 찾을 수 없습니다.")

    for requested in normalized_items:
        draft = by_id[requested["promptDraftId"]]
        if str(draft.status).upper() != "READY" or not str(draft.positive_prompt or "").strip():
            raise ValueError("완료된 Positive Prompt가 있는 초안만 RunPod 요청에 추가할 수 있습니다.")
        asset = db.get(Asset, draft.asset_id)
        if asset is None:
            raise ValueError("입력 이미지 자산을 찾을 수 없습니다.")
        if requested["resolutionTier"] == "hd":
            pixel_count = _asset_pixel_count(asset)
            if pixel_count is not None and pixel_count <= SD_PIXEL_LIMIT:
                raise ValueError("원본 픽셀이 409,600 이하인 이미지는 HD Quality를 선택할 수 없습니다.")

    batch = _existing_batch_job_request_batch(db, batch_job_id=batch_job_id, created_by=created_by)
    if batch is None:
        first_workflow_id = canonical_workflow_id(
            normalized_items[0]["workflowId"] or by_id[normalized_items[0]["promptDraftId"]].workflow_id
        )
        batch = RunpodRequestBatch(
            id=f"rpb_{uuid.uuid4().hex[:16]}",
            # Kept for legacy consumers; every item still retains its own workflow.
            workflow_id=first_workflow_id,
            requested_count=0,
            status="QUEUED",
            queued_count=0,
            created_by=created_by,
            submitted_by=submitted_by or created_by,
            # Set at row creation so the tasks built from these items can read it
            # back through job_payload_from_request_item.
            batch_job_id=batch_job_id,
        )
        db.add(batch)
        db.flush()

    existing_draft_ids = set()
    if batch_job_id:
        existing_draft_ids = {
            str(draft_id)
            for draft_id in db.scalars(
                select(RunpodRequestItem.prompt_draft_id)
                .where(
                    RunpodRequestItem.request_batch_id == batch.id,
                    RunpodRequestItem.prompt_draft_id.is_not(None),
                )
            ).all()
        }
    next_sequence = int(db.scalar(
        select(func.max(RunpodRequestItem.sequence_no)).where(RunpodRequestItem.request_batch_id == batch.id)
    ) or 0) + 1
    created_item_ids: list[str] = []
    default_negatives_by_workflow: dict[str, str] = {}
    for requested in normalized_items:
        if batch_job_id and requested["promptDraftId"] in existing_draft_ids:
            continue
        draft = by_id[requested["promptDraftId"]]
        workflow_id = canonical_workflow_id(requested["workflowId"] or draft.workflow_id)
        if workflow_id not in default_negatives_by_workflow:
            default_negatives_by_workflow[workflow_id] = _workflow_default_negative_prompt(workflow_id)
        negative_prompt = str(draft.negative_prompt or "").strip() or default_negatives_by_workflow[workflow_id] or None
        item_id = f"rpi_{uuid.uuid4().hex[:16]}"
        db.add(RunpodRequestItem(
            id=item_id,
            request_batch_id=batch.id,
            sequence_no=next_sequence,
            prompt_draft_id=draft.id,
            asset_id=draft.asset_id,
            workflow_id=workflow_id,
            positive_prompt=str(draft.positive_prompt or "").strip(),
            negative_prompt=negative_prompt,
            requested_frames=requested["requestedFrames"] or max(1, int(draft.requested_frames or 81)),
            resolution_tier=requested["resolutionTier"],
            status="PENDING_SUBMIT",
        ))
        created_item_ids.append(item_id)
        existing_draft_ids.add(requested["promptDraftId"])
        next_sequence += 1
    refresh_request_batch_summary(db, batch.id)
    db.commit()
    payload = request_batch_payload(db, batch.id, created_by=created_by)
    payload["createdItemIds"] = created_item_ids
    return payload


def _workflow_default_negative_prompt(workflow_id: str) -> str:
    try:
        schema = workflow_service.get_workflow_schema(workflow_id)
    except Exception:
        return ""
    for segment in schema.get("segments") or []:
        negative_prompt = str(segment.get("defaultNegativePrompt") or "").strip()
        if negative_prompt:
            return negative_prompt
    return ""


def _existing_batch_job_request_batch(db: Session, *, batch_job_id: str | None, created_by: str) -> RunpodRequestBatch | None:
    normalized_batch_job_id = str(batch_job_id or "").strip()
    if not normalized_batch_job_id:
        return None
    return db.scalar(
        select(RunpodRequestBatch)
        .where(
            RunpodRequestBatch.batch_job_id == normalized_batch_job_id,
            RunpodRequestBatch.created_by == created_by,
        )
        .order_by(RunpodRequestBatch.created_at.asc(), RunpodRequestBatch.id.asc())
        .limit(1)
    )


def request_batch_payload(
    db: Session,
    batch_id: str,
    *,
    created_by: str | None = None,
    actor_id: str | None = None,
    can_manage: bool = False,
) -> dict:
    batch = db.get(RunpodRequestBatch, batch_id)
    if batch is None:
        raise ValueError("RunPod 요청 묶음을 찾을 수 없습니다.")
    if created_by and batch.created_by != created_by:
        raise ValueError("RunPod 요청 묶음을 찾을 수 없습니다.")
    if actor_id and not can_manage and actor_id not in {batch.created_by, batch.submitted_by}:
        raise ValueError("RunPod 요청 묶음을 찾을 수 없습니다.")
    _reconcile_task_links_from_snapshot(db, batch)
    refresh_request_batch_summary(db, batch.id)
    db.commit()
    db.refresh(batch)
    items = db.scalars(
        select(RunpodRequestItem)
        .where(RunpodRequestItem.request_batch_id == batch.id)
        .order_by(RunpodRequestItem.sequence_no.asc())
    ).all()
    worker_name = _user_name(db, batch.created_by)
    item_assets, item_runpod_job_ids = _item_relations(db, list(items))
    return {
        "id": batch.id,
        "workflowId": batch.workflow_id,
        "status": batch.status,
        "requestedCount": batch.requested_count,
        "queuedCount": batch.queued_count,
        "inProgressCount": batch.in_progress_count,
        "completedCount": batch.completed_count,
        "failedCount": batch.failed_count,
        "cancelledCount": batch.cancelled_count,
        "createdAt": batch.created_at.isoformat() if batch.created_at else None,
        "updatedAt": batch.updated_at.isoformat() if batch.updated_at else None,
        "createdBy": batch.created_by,
        "createdByName": _user_name(db, batch.created_by),
        "submittedBy": batch.submitted_by,
        "submittedByName": _user_name(db, batch.submitted_by),
        "items": [
            _item_payload(
                db,
                item,
                worker_id=batch.created_by,
                worker_name=worker_name,
                assets=item_assets,
                runpod_job_ids=item_runpod_job_ids,
            )
            for item in items
        ],
    }


def _reconcile_task_links_from_snapshot(db: Session, batch: RunpodRequestBatch) -> None:
    """Repair batch references written by the initial durable-queue release.

    The original writer stored request IDs in WorkflowTask.payload_json but did
    not copy them into the indexed task columns.  A request item already holds
    the task ID, so the immutable snapshot gives us a safe, exact repair key.
    This makes existing running requests visible without an operator script.
    """
    items = db.scalars(
        select(RunpodRequestItem).where(RunpodRequestItem.request_batch_id == batch.id)
    ).all()
    task_ids = [item.task_id for item in items if item.task_id]
    if not task_ids:
        return
    # 필요한 컬럼만 한 번에 읽는다. item마다 db.get(WorkflowTask, ...)로 전체
    # 엔티티를 가져오던 이전 구현은 폴링되는 이 경로에서 결과물 base64가 담긴
    # runpod_status_json까지 매번 함께 끌어왔다.
    task_rows = {
        str(row.id): row
        for row in db.execute(
            select(
                WorkflowTask.id,
                WorkflowTask.payload_json,
                WorkflowTask.status,
                WorkflowTask.last_dispatch_error,
                WorkflowTask.request_batch_id,
                WorkflowTask.request_item_id,
            ).where(WorkflowTask.id.in_(task_ids))
        ).all()
    }
    for item in items:
        row = task_rows.get(str(item.task_id or ""))
        if row is None:
            continue
        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        if payload.get("requestBatchId") != batch.id or payload.get("requestItemId") != item.id:
            continue
        # 복구가 필요한 행만 쓴다. 이미 링크가 맞으면 쓰기는 발생하지 않는다.
        if row.request_batch_id != batch.id or row.request_item_id != item.id:
            db.execute(
                update(WorkflowTask)
                .where(WorkflowTask.id == row.id)
                .values(request_batch_id=batch.id, request_item_id=item.id)
            )
        item.status = _item_status(row.status)
        item.failure_message = row.last_dispatch_error if item.status == "PENDING_SUBMIT" else None


def latest_active_request_batch(db: Session, *, created_by: str) -> dict | None:
    terminal = {"COMPLETED", "SUCCESS", "PARTIAL_FAILED", "FAILED", "CANCELLED"}
    batch = db.scalar(
        select(RunpodRequestBatch)
        .where(RunpodRequestBatch.created_by == created_by, RunpodRequestBatch.status.not_in(terminal))
        .order_by(RunpodRequestBatch.updated_at.desc(), RunpodRequestBatch.created_at.desc())
        .limit(1)
    )
    return request_batch_payload(db, batch.id, created_by=created_by) if batch else None


def request_batch_dashboard(
    db: Session,
    *,
    created_by: str | None = None,
    workflow_id: str = "",
    status_filter: str = "",
) -> dict:
    """Summarize request-ready drafts and active request batch item states."""
    totals = {
        "incomplete": 0,
        "requestReady": 0,
        "pendingSubmit": 0,
        "runpodQueued": 0,
        "inProgress": 0,
        "completed": 0,
        "failed": 0,
    }
    workers: dict[str, dict] = {}
    for item in _request_queue_entries(
        db,
        created_by=created_by,
        workflow_id=workflow_id,
        status_filter=status_filter,
        include_terminal_items=True,
    ):
        worker_id = str(item.get("workerId") or "")
        entry = workers.setdefault(worker_id, {
            "workerId": item.get("workerId"),
            "workerName": item.get("workerName") or _user_name(db, worker_id),
            "incomplete": 0,
            "requestReady": 0,
            "pendingSubmit": 0,
            "runpodQueued": 0,
            "inProgress": 0,
            "completed": 0,
            "failed": 0,
        })
        entry["incomplete"] += 1
        totals["incomplete"] += 1
        if item.get("canSubmit"):
            entry["requestReady"] += 1
            totals["requestReady"] += 1
            continue
        state = str(item.get("status") or "").upper()
        if state in {"PENDING_SUBMIT", "DISPATCHING"}:
            entry["pendingSubmit"] += 1
            totals["pendingSubmit"] += 1
        elif state in {"QUEUED", "IN_QUEUE"}:
            entry["runpodQueued"] += 1
            totals["runpodQueued"] += 1
        elif state in {"IN_PROGRESS", "RUNNING"}:
            entry["inProgress"] += 1
            totals["inProgress"] += 1
        elif state in {"COMPLETED", "SUCCESS"}:
            entry["completed"] += 1
            totals["completed"] += 1
        elif state in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            entry["failed"] += 1
            totals["failed"] += 1

    return {
        "totals": totals,
        "workers": sorted(workers.values(), key=lambda entry: (str(entry["workerName"] or ""), str(entry["workerId"] or ""))),
    }


def request_batch_queue(
    db: Session,
    *,
    created_by: str | None = None,
    workflow_id: str = "",
    status_filter: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """Return the paged operational queue and its exact filtered total.

    A row is either an unsubmitted READY prompt draft or an immutable request
    item from an active request batch.  This is deliberately the same source
    used by ``request_batch_dashboard`` so the dashboard can never count a
    different set of items than the table below it.
    """
    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(200, int(page_size or 10)))
    rows = _request_queue_entries(
        db,
        created_by=created_by,
        workflow_id=workflow_id,
        status_filter=status_filter,
    )
    start = (safe_page - 1) * safe_page_size
    return {
        "items": rows[start:start + safe_page_size],
        "page": safe_page,
        "pageSize": safe_page_size,
        "total": len(rows),
    }


def _request_queue_entries(
    db: Session,
    *,
    created_by: str | None = None,
    workflow_id: str = "",
    status_filter: str = "",
    include_terminal_items: bool = False,
) -> list[dict]:
    """Build a canonical, de-duplicated view of work not yet completed."""
    terminal_batches = {"COMPLETED", "SUCCESS", "PARTIAL_FAILED", "FAILED", "CANCELLED"}
    terminal_items = {"COMPLETED", "SUCCESS"}
    batch_statement = select(RunpodRequestItem, RunpodRequestBatch).join(
        RunpodRequestBatch,
        RunpodRequestItem.request_batch_id == RunpodRequestBatch.id,
    ).where(
        RunpodRequestBatch.status.not_in(terminal_batches),
        RunpodRequestBatch.batch_job_id.is_(None),
    )
    if created_by:
        batch_statement = batch_statement.where(RunpodRequestBatch.created_by == created_by)
    if workflow_id:
        workflow_names = _workflow_filter_names(workflow_id)
        batch_statement = batch_statement.where(RunpodRequestItem.workflow_id.in_(workflow_names))

    entries: list[dict] = []
    # 행을 먼저 모은 뒤 참조 자산/task를 한 번에 읽는다. 루프 안에서 항목마다
    # db.get()을 부르면 2초 폴링되는 이 경로가 N+1이 된다.
    queue_rows = [
        (request_item, batch)
        for request_item, batch in db.execute(batch_statement).all()
        if include_terminal_items or str(request_item.status or "").upper() not in terminal_items
    ]
    item_assets, item_runpod_job_ids = _item_relations(db, [row[0] for row in queue_rows])
    for request_item, batch in queue_rows:
        worker_name = _user_name(db, batch.created_by)
        payload = _item_payload(
            db,
            request_item,
            worker_id=batch.created_by,
            worker_name=worker_name,
            assets=item_assets,
            runpod_job_ids=item_runpod_job_ids,
        )
        payload.update({
            "kind": "REQUEST_ITEM",
            "requestBatchId": batch.id,
            "promptBatchId": _prompt_batch_id(db, request_item.prompt_draft_id),
            "canSubmit": False,
            "updatedAt": request_item.updated_at.isoformat() if request_item.updated_at else None,
        })
        entries.append(payload)

    # A draft should disappear from the "requestable" list only while it is in
    # an active request batch, or after a real WorkflowTask has been created.
    # A failed pre-submission request item has no RunPod task behind it; Prompt
    # History still shows that draft as "미요청", so it must be requestable again.
    requested_draft_ids = {
        str(draft_id)
        for draft_id in db.scalars(
            select(RunpodRequestItem.prompt_draft_id)
            .join(RunpodRequestBatch, RunpodRequestItem.request_batch_id == RunpodRequestBatch.id)
            .where(
                RunpodRequestItem.prompt_draft_id.is_not(None),
                RunpodRequestBatch.status.not_in(terminal_batches),
                RunpodRequestBatch.batch_job_id.is_(None),
            )
        ).all()
    }
    requested_draft_ids.update(
        str(draft_id)
        for draft_id in db.scalars(
            select(WorkflowTask.prompt_draft_id).where(
                WorkflowTask.prompt_draft_id.is_not(None),
                WorkflowTask.deleted_at.is_(None),
            )
        ).all()
    )
    draft_statement = select(ImagePromptDraft).where(
        ImagePromptDraft.status == "READY",
        ImagePromptDraft.positive_prompt.is_not(None),
        ImagePromptDraft.batch_job_id.is_(None),
    )
    if created_by:
        draft_statement = draft_statement.where(ImagePromptDraft.created_by == created_by)
    if workflow_id:
        workflow_names = _workflow_filter_names(workflow_id)
        draft_statement = draft_statement.where(ImagePromptDraft.workflow_id.in_(workflow_names))
    for draft in db.scalars(draft_statement).all():
        if draft.id in requested_draft_ids:
            continue
        asset = db.get(Asset, draft.asset_id)
        entries.append({
            "id": f"draft:{draft.id}",
            "kind": "PROMPT_DRAFT",
            "requestBatchId": None,
            "sequenceNo": draft.slot_index,
            "promptDraftId": draft.id,
            "promptBatchId": draft.prompt_batch_id,
            "assetId": draft.asset_id,
            "asset": _asset_payload(asset),
            "workflowId": canonical_workflow_id(draft.workflow_id),
            "positivePrompt": str(draft.positive_prompt or ""),
            "negativePrompt": draft.negative_prompt,
            "requestedFrames": int(draft.requested_frames or 81),
            "resolutionTier": "sd",
            "status": "READY",
            "taskId": None,
            "runpodJobId": None,
            "failureMessage": draft.failure_message,
            "workerId": draft.created_by,
            "workerName": _user_name(db, draft.created_by),
            "canSubmit": True,
            "updatedAt": draft.updated_at.isoformat() if draft.updated_at else None,
        })

    filtered = [item for item in entries if _matches_queue_status_filter(item, status_filter)]
    return sorted(filtered, key=lambda item: (str(item.get("updatedAt") or ""), str(item["id"])), reverse=True)


def _matches_queue_status_filter(item: dict, status_filter: str) -> bool:
    normalized = str(status_filter or "").strip().lower().replace("_", "").replace("-", "")
    if not normalized or normalized == "all":
        return True
    if normalized in {"requestable", "ready"}:
        return bool(item.get("canSubmit"))
    state = str(item.get("status") or "").upper()
    if normalized in {"pendingsubmit", "submitwaiting", "pending", "dispatching"}:
        return not item.get("canSubmit") and state in {"PENDING_SUBMIT", "DISPATCHING"}
    if normalized in {"runpodqueued", "queued", "inqueue"}:
        return state in {"QUEUED", "IN_QUEUE"}
    if normalized in {"inprogress", "running"}:
        return state in {"IN_PROGRESS", "RUNNING"}
    if normalized == "failed":
        return state in {"FAILED", "TIMED_OUT"}
    if normalized == "cancelled":
        return state == "CANCELLED"
    if normalized == "timedout":
        return state == "TIMED_OUT"
    if normalized in {"completed", "complete", "success"}:
        return state in {"COMPLETED", "SUCCESS"}
    return True


def _prompt_batch_id(db: Session, draft_id: str | None) -> str | None:
    if not draft_id:
        return None
    draft = db.get(ImagePromptDraft, draft_id)
    return draft.prompt_batch_id if draft else None


def attach_task_to_request_item(
    db: Session,
    *,
    item_id: str,
    task_id: str,
    materialization_claimed_at=None,
) -> bool:
    item = db.get(RunpodRequestItem, item_id)
    if item is None:
        raise ValueError("RunPod 요청 항목을 찾을 수 없습니다.")
    if materialization_claimed_at is not None:
        result = db.execute(
            update(RunpodRequestItem)
            .where(
                RunpodRequestItem.id == item_id,
                RunpodRequestItem.task_id.is_(None),
                RunpodRequestItem.materialization_claimed_at == materialization_claimed_at,
            )
            .values(task_id=task_id, status="PENDING_SUBMIT", failure_message=None, materialization_claimed_at=None)
        )
        if not result.rowcount:
            db.rollback()
            return False
        refresh_request_batch_summary(db, item.request_batch_id)
        db.commit()
        return True
    item.task_id = task_id
    item.status = "PENDING_SUBMIT"
    item.failure_message = None
    item.materialization_claimed_at = None
    refresh_request_batch_summary(db, item.request_batch_id)
    db.commit()
    return True


def mark_request_item_failed(db: Session, *, item_id: str, message: str, materialization_claimed_at=None) -> bool:
    item = db.get(RunpodRequestItem, item_id)
    if item is None:
        return False
    if materialization_claimed_at is not None:
        result = db.execute(
            update(RunpodRequestItem)
            .where(
                RunpodRequestItem.id == item_id,
                RunpodRequestItem.materialization_claimed_at == materialization_claimed_at,
            )
            .values(
                status="FAILED",
                failure_message=str(message or "RunPod 요청 등록에 실패했습니다."),
                materialization_claimed_at=None,
            )
        )
        if not result.rowcount:
            db.rollback()
            return False
        refresh_request_batch_summary(db, item.request_batch_id)
        db.commit()
        return True
    item.status = "FAILED"
    item.failure_message = str(message or "RunPod 요청 등록에 실패했습니다.")
    item.materialization_claimed_at = None
    refresh_request_batch_summary(db, item.request_batch_id)
    db.commit()
    return True


def sync_request_batch_for_task(db: Session, task: WorkflowTask) -> None:
    item_id = str(task.request_item_id or "").strip()
    if not item_id:
        return
    item = db.get(RunpodRequestItem, item_id)
    if item is None:
        return
    item.task_id = task.id
    item.status = _item_status(task.status)
    item.failure_message = task.last_dispatch_error if item.status == "PENDING_SUBMIT" else None
    refresh_request_batch_summary(db, item.request_batch_id)


def refresh_request_batch_summary(db: Session, batch_id: str) -> None:
    batch = db.get(RunpodRequestBatch, batch_id)
    if batch is None:
        return
    items = db.scalars(select(RunpodRequestItem).where(RunpodRequestItem.request_batch_id == batch_id)).all()
    states = Counter(str(item.status or "PENDING_SUBMIT").upper() for item in items)
    batch.requested_count = len(items)
    batch.queued_count = sum(states[state] for state in ("PENDING_SUBMIT", "DISPATCHING", "QUEUED", "IN_QUEUE"))
    batch.in_progress_count = sum(states[state] for state in ("IN_PROGRESS", "RUNNING"))
    batch.completed_count = states["COMPLETED"] + states["SUCCESS"]
    batch.failed_count = states["FAILED"] + states["TIMED_OUT"]
    batch.cancelled_count = states["CANCELLED"]
    if not items:
        batch.status = "DRAFT"
    elif batch.queued_count or batch.in_progress_count:
        batch.status = "IN_PROGRESS" if batch.in_progress_count else "QUEUED"
    elif batch.completed_count == len(items):
        batch.status = "COMPLETED"
    elif batch.completed_count:
        batch.status = "PARTIAL_FAILED"
    elif batch.cancelled_count == len(items):
        batch.status = "CANCELLED"
    else:
        batch.status = "FAILED"
    batch.updated_at = now_seoul_naive()


def _item_status(task_status: str | None) -> str:
    state = str(task_status or "PENDING_SUBMIT").upper()
    if state == "SUCCESS":
        return "COMPLETED"
    return state


def _item_relations(db: Session, items: list[RunpodRequestItem]) -> tuple[dict, dict]:
    """항목 목록이 참조하는 자산과 RunPod job ID를 각각 한 번의 쿼리로 읽는다.

    항목마다 db.get()을 부르던 이전 구현은 N+1이었고, WorkflowTask는 전체
    엔티티로 로드되어 결과물 base64가 담긴 runpod_status_json까지 끌어왔다.
    """
    asset_ids = {item.asset_id for item in items if item.asset_id}
    task_ids = {item.task_id for item in items if item.task_id}
    assets = {
        asset.id: asset
        for asset in (db.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all() if asset_ids else [])
    }
    runpod_job_ids = {
        str(task_id): runpod_job_id
        for task_id, runpod_job_id in (
            db.execute(
                select(WorkflowTask.id, WorkflowTask.runpod_job_id).where(WorkflowTask.id.in_(task_ids))
            ).all()
            if task_ids
            else []
        )
    }
    return assets, runpod_job_ids


def _item_payload(
    db: Session,
    item: RunpodRequestItem,
    *,
    worker_id: str | None = None,
    worker_name: str | None = None,
    assets: dict | None = None,
    runpod_job_ids: dict | None = None,
) -> dict:
    if assets is None or runpod_job_ids is None:
        assets, runpod_job_ids = _item_relations(db, [item])
    asset = assets.get(item.asset_id)
    runpod_job_id = runpod_job_ids.get(str(item.task_id)) if item.task_id else None
    return {
        "id": item.id,
        "sequenceNo": item.sequence_no,
        "promptDraftId": item.prompt_draft_id,
        "assetId": item.asset_id,
        "asset": _asset_payload(asset),
        "workflowId": canonical_workflow_id(item.workflow_id),
        "positivePrompt": item.positive_prompt,
        "negativePrompt": item.negative_prompt,
        "requestedFrames": item.requested_frames,
        "resolutionTier": normalize_resolution_tier(getattr(item, "resolution_tier", None)),
        "status": item.status,
        "taskId": item.task_id,
        "runpodJobId": runpod_job_id,
        "failureMessage": item.failure_message,
        "workerId": worker_id,
        "workerName": worker_name,
    }


def _asset_payload(asset: Asset | None) -> dict | None:
    if asset is None:
        return None
    width, height = _asset_dimensions(asset)
    return {
        "fileName": asset.file_name,
        "mimeType": asset.mime_type,
        "imageWidth": width,
        "imageHeight": height,
    }


def _asset_pixel_count(asset: Asset) -> int | None:
    width, height = _asset_dimensions(asset)
    return width * height if width and height else None


def _asset_dimensions(asset: Asset) -> tuple[int | None, int | None]:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    width = _positive_int(asset.image_width) or _positive_int(metadata.get("imageWidth")) or _positive_int(metadata.get("width"))
    height = _positive_int(asset.image_height) or _positive_int(metadata.get("imageHeight")) or _positive_int(metadata.get("height"))
    return width, height


def _workflow_filter_names(workflow_id: str) -> set[str]:
    canonical_id = canonical_workflow_id(workflow_id)
    return {str(workflow_id or ""), canonical_id, *_legacy_ids_for_canonical(canonical_id)}


def _legacy_ids_for_canonical(workflow_id: str) -> list[str]:
    from backend.app.services.workflow_visibility import LEGACY_WORKFLOW_ID_MAP

    return [legacy_id for legacy_id, canonical_id in LEGACY_WORKFLOW_ID_MAP.items() if canonical_id == workflow_id]


def _positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _user_name(db: Session, user_id: str | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.name if user else user_id


def _normalize_requested_items(items: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise ValueError("RunPod 요청 항목 형식이 올바르지 않습니다.")
        draft_id = str(raw_item.get("promptDraftId") or "").strip()
        if not draft_id or draft_id in seen:
            continue
        seen.add(draft_id)
        frames_raw = raw_item.get("requestedFrames")
        try:
            frames = max(1, int(frames_raw)) if frames_raw is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError("영상 Length 값이 올바르지 않습니다.") from exc
        if frames is not None and frames not in ALLOWED_FRAMES:
            allowed = ", ".join(str(item) for item in sorted(ALLOWED_FRAMES))
            raise ValueError(f"영상 Length는 {allowed} 중 하나여야 합니다.")
        normalized.append({
            "promptDraftId": draft_id,
            "workflowId": str(raw_item.get("workflowId") or "").strip(),
            "requestedFrames": frames,
            "resolutionTier": normalize_resolution_tier(raw_item.get("resolutionTier")),
        })
    return normalized
