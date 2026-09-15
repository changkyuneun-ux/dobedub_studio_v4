from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import utc_now
from backend.app.db.models import Asset, WebtoonCutJob, WebtoonCutOutput
from backend.app.services.webtoon_cut_naming import make_source_identity


ACTIVE_JOB_STATUSES = {"pending", "running"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
REVIEW_REQUIRED_FLAGS = {"review_required", "thin", "many", "review_continuous", "missing_output", "error"}


def create_job(
    db: Session,
    *,
    source_asset_id: str,
    input_kind: str,
    created_by: str,
    metadata: dict | None = None,
) -> dict:
    source = _require_asset(db, source_asset_id)
    _assert_asset_owner(source, created_by)
    active = db.scalars(
        select(WebtoonCutJob)
        .where(WebtoonCutJob.created_by == created_by)
        .where(WebtoonCutJob.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(desc(WebtoonCutJob.created_at))
    ).first()
    if active is not None:
        raise ValueError("이미 진행 중인 컷 분할 작업이 있습니다. 완료 또는 취소 후 다시 요청하세요.")
    identity = make_source_identity(source.file_name)
    now = _now()
    job = WebtoonCutJob(
        id=f"wcut_{uuid.uuid4().hex[:12]}",
        status="pending",
        input_kind=input_kind,
        source_asset_id=source.id,
        display_name=identity.display_name,
        safe_stem=identity.safe_stem,
        metadata_json={
            "displayStem": identity.display_stem,
            "sourceStorageKey": source.storage_key,
            "createdBy": created_by,
            **(metadata or {}),
        },
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_payload(job)


def cancel_job(db: Session, job_id: str, *, created_by: str) -> dict:
    job = _require_job(db, job_id, created_by=created_by)
    if job.status in TERMINAL_JOB_STATUSES:
        return _job_payload(job)
    job.status = "cancelled"
    job.cancel_requested_at = _now()
    job.completed_at = _now()
    job.updated_at = _now()
    db.commit()
    db.refresh(job)
    return _job_payload(job)


def get_job(db: Session, job_id: str, *, created_by: str) -> dict:
    job = _require_job(db, job_id, created_by=created_by)
    return _job_payload(job)


def list_jobs(
    db: Session,
    *,
    created_by: str,
    status: str = "",
    input_kind: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    stmt = select(WebtoonCutJob).where(WebtoonCutJob.created_by == created_by)
    if status:
        stmt = stmt.where(WebtoonCutJob.status == status)
    if input_kind:
        stmt = stmt.where(WebtoonCutJob.input_kind == input_kind)
    if query:
        stmt = stmt.where(WebtoonCutJob.display_name.contains(query))
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    items = db.scalars(stmt.order_by(desc(WebtoonCutJob.created_at)).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_job_payload(job) for job in items], "page": page, "pageSize": page_size}


def register_output(
    db: Session,
    *,
    job_id: str,
    asset_id: str,
    display_path: str,
    page_number: int | None,
    cut_index: int,
    created_by: str,
    source_id: str | None = None,
    unit_id: str | None = None,
    width: int | None = None,
    height: int | None = None,
    flags: list[str] | None = None,
    used_in_prompt_count: int = 0,
    used_in_batch_count: int = 0,
    i2v_result_count: int = 0,
) -> dict:
    job = _require_job(db, job_id, created_by=created_by)
    asset = _require_asset(db, asset_id)
    _assert_asset_owner(asset, created_by)
    output = WebtoonCutOutput(
        id=f"wcut_out_{uuid.uuid4().hex[:12]}",
        job_id=job.id,
        source_id=source_id,
        unit_id=unit_id,
        asset_id=asset.id,
        status="ready",
        display_path=display_path,
        page_number=page_number,
        cut_index=cut_index,
        width=width or asset.image_width,
        height=height or asset.image_height,
        flags_json=list(flags or []),
        used_in_prompt_count=used_in_prompt_count,
        used_in_batch_count=used_in_batch_count,
        i2v_result_count=i2v_result_count,
        metadata_json={"createdBy": created_by},
        created_by=created_by,
        created_at=_now(),
    )
    db.add(output)
    job.generated_cut_count += 1
    if set(output.flags_json) & REVIEW_REQUIRED_FLAGS:
        job.review_required_count += 1
    db.commit()
    db.refresh(output)
    return _output_payload(output)


def list_outputs(
    db: Session,
    *,
    job_id: str,
    created_by: str,
    used_state: str = "",
    flags: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    _require_job(db, job_id, created_by=created_by)
    stmt = select(WebtoonCutOutput).where(WebtoonCutOutput.job_id == job_id).where(WebtoonCutOutput.created_by == created_by)
    used_state = str(used_state or "").strip().lower()
    if used_state in {"unused", "미사용"}:
        stmt = stmt.where(WebtoonCutOutput.used_in_prompt_count == 0).where(WebtoonCutOutput.used_in_batch_count == 0).where(WebtoonCutOutput.i2v_result_count == 0)
    elif used_state in {"prompt", "grok"}:
        stmt = stmt.where(WebtoonCutOutput.used_in_prompt_count > 0)
    elif used_state == "batch":
        stmt = stmt.where(WebtoonCutOutput.used_in_batch_count > 0)
    elif used_state in {"i2v", "result"}:
        stmt = stmt.where(WebtoonCutOutput.i2v_result_count > 0)
    if flags:
        wanted = {item.strip() for item in flags.split(",") if item.strip()}
        if wanted:
            outputs = [
                output
                for output in db.scalars(stmt.order_by(asc(WebtoonCutOutput.page_number), asc(WebtoonCutOutput.cut_index))).all()
                if wanted.intersection(set(output.flags_json or []))
            ]
            return _paged_outputs(outputs, page=page, page_size=page_size)
    if query:
        stmt = stmt.where(WebtoonCutOutput.display_path.contains(query))
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 50)))
    outputs = db.scalars(
        stmt.order_by(asc(WebtoonCutOutput.page_number), asc(WebtoonCutOutput.cut_index)).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [_output_payload(output) for output in outputs], "page": page, "pageSize": page_size}


def validate_output_selection(
    outputs: Iterable[dict],
    *,
    expected_job_id: str,
    exclude_review_required: bool,
) -> list[dict]:
    selected = list(outputs)
    if not selected:
        raise ValueError("선택한 컷이 없습니다.")
    valid: list[dict] = []
    for output in selected:
        if output.get("jobId") != expected_job_id:
            raise ValueError("같은 컷 분할 작업의 컷만 선택할 수 있습니다.")
        flags = set(output.get("flags") or [])
        if flags & {"error", "missing_output"}:
            raise ValueError("오류 컷은 후속 작업에 사용할 수 없습니다.")
        if exclude_review_required and flags & REVIEW_REQUIRED_FLAGS:
            continue
        valid.append(output)
    return valid


def create_grok_prompt_input_from_outputs(db: Session, *, job_id: str, output_ids: list[str], created_by: str) -> dict:
    outputs = _load_selected_outputs(db, job_id=job_id, output_ids=output_ids, created_by=created_by)
    for output in outputs:
        output.used_in_prompt_count += 1
    db.commit()
    return {
        "target": "grok_prompt",
        "jobId": job_id,
        "inputAssetIds": [output.asset_id for output in outputs],
        "sourceRelativePaths": [output.display_path for output in outputs],
        "items": [_handoff_item_payload(output) for output in outputs],
    }


def create_batch_input_from_outputs(db: Session, *, job_id: str, output_ids: list[str], created_by: str) -> dict:
    outputs = _load_selected_outputs(db, job_id=job_id, output_ids=output_ids, created_by=created_by)
    for output in outputs:
        output.used_in_batch_count += 1
    db.commit()
    return {
        "target": "batch",
        "jobId": job_id,
        "inputAssetIds": [output.asset_id for output in outputs],
        "sourceRelativePaths": [output.display_path for output in outputs],
        "items": [_handoff_item_payload(output) for output in outputs],
    }


def _load_selected_outputs(db: Session, *, job_id: str, output_ids: list[str], created_by: str) -> list[WebtoonCutOutput]:
    _require_job(db, job_id, created_by=created_by)
    if not output_ids:
        raise ValueError("선택한 컷이 없습니다.")
    outputs = db.scalars(
        select(WebtoonCutOutput)
        .where(WebtoonCutOutput.job_id == job_id)
        .where(WebtoonCutOutput.created_by == created_by)
        .where(WebtoonCutOutput.id.in_(output_ids))
        .order_by(asc(WebtoonCutOutput.page_number), asc(WebtoonCutOutput.cut_index))
    ).all()
    if len(outputs) != len(set(output_ids)):
        raise ValueError("선택한 컷을 찾을 수 없습니다.")
    validate_output_selection([_output_payload(output) for output in outputs], expected_job_id=job_id, exclude_review_required=False)
    return list(outputs)


def _paged_outputs(outputs: list[WebtoonCutOutput], *, page: int, page_size: int) -> dict:
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 50)))
    start = (page - 1) * page_size
    return {"items": [_output_payload(output) for output in outputs[start:start + page_size]], "page": page, "pageSize": page_size}


def _require_job(db: Session, job_id: str, *, created_by: str) -> WebtoonCutJob:
    job = db.get(WebtoonCutJob, job_id)
    if job is None:
        raise KeyError(job_id)
    if job.created_by != created_by:
        raise PermissionError("컷 분할 작업 접근 권한이 없습니다.")
    return job


def _require_asset(db: Session, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise KeyError(asset_id)
    return asset


def _assert_asset_owner(asset: Asset, created_by: str) -> None:
    owner = str((asset.metadata_json or {}).get("createdBy") or "")
    if owner and owner != created_by:
        raise PermissionError("자산 접근 권한이 없습니다.")


def _job_payload(job: WebtoonCutJob) -> dict:
    return {
        "jobId": job.id,
        "status": job.status,
        "inputKind": job.input_kind,
        "sourceAssetId": job.source_asset_id,
        "displayName": job.display_name,
        "totalUnits": job.total_units,
        "completedUnits": job.completed_units,
        "generatedCutCount": job.generated_cut_count,
        "reviewRequiredCount": job.review_required_count,
        "failedUnits": job.failed_units,
        "currentUnitLabel": job.current_unit_label,
        "cancelRequestedAt": job.cancel_requested_at.isoformat() if job.cancel_requested_at else None,
        "createdBy": job.created_by,
        "createdAt": job.created_at.isoformat() if job.created_at else None,
        "updatedAt": job.updated_at.isoformat() if job.updated_at else None,
    }


def _output_payload(output: WebtoonCutOutput) -> dict:
    return {
        "outputId": output.id,
        "jobId": output.job_id,
        "assetId": output.asset_id,
        "viewUrl": f"/api/files/{output.asset_id}?download=0",
        "downloadUrl": f"/api/files/{output.asset_id}?download=1",
        "displayPath": output.display_path,
        "pageNumber": output.page_number,
        "cutIndex": output.cut_index,
        "width": output.width,
        "height": output.height,
        "flags": list(output.flags_json or []),
        "usedInPromptCount": output.used_in_prompt_count,
        "usedInBatchCount": output.used_in_batch_count,
        "i2vResultCount": output.i2v_result_count,
        "createdBy": output.created_by,
    }


def _handoff_item_payload(output: WebtoonCutOutput) -> dict:
    return {
        "outputId": output.id,
        "assetId": output.asset_id,
        "fileName": output.display_path.rsplit("/", 1)[-1] or output.asset_id,
        "mimeType": "image/png",
        "sourceRelativePath": output.display_path,
        "imageWidth": output.width,
        "imageHeight": output.height,
        "downloadUrl": f"/api/files/{output.asset_id}",
    }


def download_expires_at() -> datetime:
    return _now() + timedelta(hours=24)


def _now() -> datetime:
    return utc_now().replace(tzinfo=None)
