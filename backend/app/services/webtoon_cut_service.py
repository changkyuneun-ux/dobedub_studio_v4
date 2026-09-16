from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterable
from typing import BinaryIO, Iterator
from urllib.parse import quote
import zipfile

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import utc_now
from backend.app.db.models import Asset, WebtoonCutJob, WebtoonCutOutput
from backend.app.services.webtoon_cut_naming import make_source_identity
from backend.app.services.zip_encoding_service import normalize_zip_path


ACTIVE_JOB_STATUSES = {"pending", "running"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
REVIEW_REQUIRED_FLAGS = {"review_required", "thin", "many", "review_continuous", "missing_output", "error"}
CHUNK_SIZE = 1024 * 1024
ZIP_RESPONSE_HEADERS = {"Content-Encoding": "identity"}
SPLIT_MODES = {"print", "dark-webtoon"}


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
        .where(WebtoonCutJob.deleted_at.is_(None))
        .order_by(desc(WebtoonCutJob.created_at))
    ).first()
    if active is not None:
        raise ValueError("이미 진행 중인 컷 분할 작업이 있습니다. 완료 또는 취소 후 다시 요청하세요.")
    identity = make_source_identity(source.file_name)
    now = _now()
    split_mode = _normalize_split_mode((metadata or {}).get("splitMode"))
    job = WebtoonCutJob(
        id=f"wcut_{uuid.uuid4().hex[:12]}",
        status="pending",
        input_kind=input_kind,
        source_asset_id=source.id,
        display_name=identity.display_name,
        safe_stem=identity.safe_stem,
        metadata_json={
            **(metadata or {}),
            "displayStem": identity.display_stem,
            "sourceStorageKey": source.storage_key,
            "createdBy": created_by,
            "splitMode": split_mode,
        },
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_payload(job)


def cancel_job(db: Session, job_id: str, *, created_by: str | None) -> dict:
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


def get_job(db: Session, job_id: str, *, created_by: str | None) -> dict:
    job = _require_job(db, job_id, created_by=created_by)
    return _job_payload(job)


def delete_job(db: Session, job_id: str, *, created_by: str | None) -> dict:
    job = _require_job(db, job_id, created_by=created_by, include_deleted=True)
    if job.status not in TERMINAL_JOB_STATUSES:
        raise ValueError("진행 중인 컷 분할 작업은 삭제할 수 없습니다. 먼저 취소 또는 완료 후 삭제하세요.")
    if job.deleted_at is None:
        now = _now()
        job.deleted_at = now
        job.updated_at = now
        db.commit()
    return {"deleted": True, "jobId": job.id}


def list_jobs(
    db: Session,
    *,
    created_by: str | None,
    status: str = "",
    input_kind: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    stmt = select(WebtoonCutJob).where(WebtoonCutJob.deleted_at.is_(None))
    if created_by:
        stmt = stmt.where(WebtoonCutJob.created_by == created_by)
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
    existing = db.scalars(
        select(WebtoonCutOutput)
        .where(WebtoonCutOutput.job_id == job.id)
        .where(WebtoonCutOutput.display_path == display_path)
        .order_by(asc(WebtoonCutOutput.created_at), asc(WebtoonCutOutput.id))
        .limit(1)
    ).first()
    if existing is not None:
        return _output_payload(existing)
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
    created_by: str | None,
    used_state: str = "",
    flags: str = "",
    query: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    _require_job(db, job_id, created_by=created_by)
    stmt = select(WebtoonCutOutput).where(WebtoonCutOutput.job_id == job_id)
    if created_by:
        stmt = stmt.where(WebtoonCutOutput.created_by == created_by)
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
                for output in _dedupe_outputs_by_display_path(db.scalars(stmt.order_by(asc(WebtoonCutOutput.page_number), asc(WebtoonCutOutput.cut_index), asc(WebtoonCutOutput.created_at))).all())
                if wanted.intersection(set(output.flags_json or []))
            ]
            return _paged_outputs(outputs, page=page, page_size=page_size)
    if query:
        stmt = stmt.where(WebtoonCutOutput.display_path.contains(query))
    return _paged_deduped_outputs(db, stmt, page=page, page_size=page_size)


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


def create_grok_prompt_input_from_outputs(db: Session, *, job_id: str, output_ids: list[str], created_by: str | None) -> dict:
    job = _require_job(db, job_id, created_by=created_by)
    outputs = _load_selected_outputs(db, job_id=job_id, output_ids=output_ids, created_by=created_by)
    for output in outputs:
        output.used_in_prompt_count += 1
    db.commit()
    return {
        "target": "grok_prompt",
        "jobId": job_id,
        "sourceDisplayName": job.display_name,
        "inputAssetIds": [output.asset_id for output in outputs],
        "sourceRelativePaths": [output.display_path for output in outputs],
        "items": [_handoff_item_payload(output) for output in outputs],
    }


def create_batch_input_from_outputs(db: Session, *, job_id: str, output_ids: list[str], created_by: str | None) -> dict:
    job = _require_job(db, job_id, created_by=created_by)
    outputs = _load_selected_outputs(db, job_id=job_id, output_ids=output_ids, created_by=created_by)
    for output in outputs:
        output.used_in_batch_count += 1
    db.commit()
    return {
        "target": "batch",
        "jobId": job_id,
        "sourceDisplayName": job.display_name,
        "inputAssetIds": [output.asset_id for output in outputs],
        "sourceRelativePaths": [output.display_path for output in outputs],
        "items": [_handoff_item_payload(output) for output in outputs],
    }


def stream_selected_outputs_zip(
    db: Session,
    *,
    job_id: str,
    output_ids: list[str],
    created_by: str | None,
) -> tuple[Iterator[bytes], int, str]:
    job = _require_job(db, job_id, created_by=created_by)
    requested_ids = [str(item) for item in output_ids if str(item).strip()]
    if not requested_ids:
        raise ValueError("다운로드할 컷을 선택해주세요.")
    stmt = (
        select(WebtoonCutOutput, Asset)
        .join(Asset, Asset.id == WebtoonCutOutput.asset_id)
        .where(WebtoonCutOutput.job_id == job_id)
        .where(WebtoonCutOutput.id.in_(requested_ids))
        .order_by(asc(WebtoonCutOutput.page_number), asc(WebtoonCutOutput.cut_index), asc(WebtoonCutOutput.created_at))
    )
    if created_by:
        stmt = stmt.where(WebtoonCutOutput.created_by == created_by)
    rows = db.execute(stmt).all()
    if len(rows) != len(set(requested_ids)):
        raise ValueError("선택한 컷을 찾을 수 없습니다.")

    used: set[str] = set()
    entries: list[dict] = []
    skipped = 0
    for output, asset in rows:
        entry_name = _zip_entry_name_for_cut(output.display_path, asset.file_name, used)
        used.add(entry_name)
        if not asset.storage_key:
            skipped += 1
            continue
        entries.append({
            "entryName": entry_name,
            "storageBackend": asset.storage_backend or "local",
            "storageKey": asset.storage_key,
        })
    if not entries:
        raise ValueError("내려받을 컷 파일이 없습니다.")

    def generate() -> Iterator[bytes]:
        buffer = _StreamBuffer()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
            for entry in entries:
                with archive.open(entry["entryName"], mode="w") as target, _open_output_asset_stream(entry) as source:
                    while True:
                        chunk = source.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        target.write(chunk)
                        yield from buffer.drain()
                yield from buffer.drain()
        yield from buffer.drain()

    return generate(), skipped, selected_outputs_zip_filename(job)


def selected_outputs_zip_filename(job: WebtoonCutJob) -> str:
    stem = Path(normalize_zip_path(str(job.display_name or job.safe_stem or job.id))).stem or "webtoon_cut"
    return f"{stem}_cuts_selected.zip"


def content_disposition_for_selected_outputs(job: WebtoonCutJob) -> str:
    filename = selected_outputs_zip_filename(job)
    fallback = "webtoon_cut_selected.zip"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _load_selected_outputs(db: Session, *, job_id: str, output_ids: list[str], created_by: str | None) -> list[WebtoonCutOutput]:
    _require_job(db, job_id, created_by=created_by)
    if not output_ids:
        raise ValueError("선택한 컷이 없습니다.")
    stmt = (
        select(WebtoonCutOutput)
        .where(WebtoonCutOutput.job_id == job_id)
        .where(WebtoonCutOutput.id.in_(output_ids))
        .order_by(asc(WebtoonCutOutput.page_number), asc(WebtoonCutOutput.cut_index))
    )
    if created_by:
        stmt = stmt.where(WebtoonCutOutput.created_by == created_by)
    outputs = db.scalars(stmt).all()
    if len(outputs) != len(set(output_ids)):
        raise ValueError("선택한 컷을 찾을 수 없습니다.")
    validate_output_selection([_output_payload(output) for output in outputs], expected_job_id=job_id, exclude_review_required=False)
    return list(outputs)


def _zip_entry_name_for_cut(display_path: str, file_name: str, used: set[str]) -> str:
    relative_path = _safe_zip_relative_path(display_path)
    if relative_path is None:
        relative_path = PurePosixPath(Path(str(file_name or "cut.png")).name)
    candidate = str(relative_path)
    if candidate not in used:
        return candidate
    path = PurePosixPath(candidate)
    stem = path.stem or "cut"
    suffix = path.suffix or ".png"
    parent = "" if str(path.parent) == "." else f"{path.parent}/"
    index = 1
    while f"{parent}{stem}-{index}{suffix}" in used:
        index += 1
    return f"{parent}{stem}-{index}{suffix}"


def _safe_zip_relative_path(value: str) -> PurePosixPath | None:
    raw = normalize_zip_path(str(value or "").strip()).replace("\\", "/")
    if not raw:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


@contextmanager
def _open_output_asset_stream(entry: dict) -> Iterator[BinaryIO]:
    if entry.get("storageBackend") == "s3":
        from backend.app.services import studio_api_service

        with studio_api_service.s3_asset_storage().open_read(str(entry.get("storageKey") or "")) as source:
            yield source
        return

    path = Path(str(entry.get("storageKey") or ""))
    with path.open("rb") as source:
        yield source


class _StreamBuffer:
    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._position = 0

    def write(self, data: bytes) -> int:
        chunk = bytes(data)
        if chunk:
            self._parts.append(chunk)
            self._position += len(chunk)
        return len(data)

    def tell(self) -> int:
        return self._position

    def flush(self) -> None:
        return None

    def drain(self) -> Iterator[bytes]:
        while self._parts:
            yield self._parts.pop(0)


def _paged_outputs(outputs: list[WebtoonCutOutput], *, page: int, page_size: int) -> dict:
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 50)))
    start = (page - 1) * page_size
    return {"items": [_output_payload(output) for output in outputs[start:start + page_size]], "page": page, "pageSize": page_size}


def _paged_deduped_outputs(db: Session, stmt, *, page: int, page_size: int) -> dict:
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 50)))
    ranked = (
        stmt.add_columns(
            func.row_number()
            .over(
                partition_by=WebtoonCutOutput.display_path,
                order_by=(
                    asc(WebtoonCutOutput.page_number),
                    asc(WebtoonCutOutput.cut_index),
                    asc(WebtoonCutOutput.created_at),
                    asc(WebtoonCutOutput.id),
                ),
            )
            .label("display_path_rank")
        )
        .subquery()
    )
    output_ids = db.scalars(
        select(ranked.c.id)
        .where(ranked.c.display_path_rank == 1)
        .order_by(asc(ranked.c.page_number), asc(ranked.c.cut_index), asc(ranked.c.created_at), asc(ranked.c.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    if not output_ids:
        return {"items": [], "page": page, "pageSize": page_size}
    outputs_by_id = {output.id: output for output in db.scalars(select(WebtoonCutOutput).where(WebtoonCutOutput.id.in_(output_ids))).all()}
    return {"items": [_output_payload(outputs_by_id[output_id]) for output_id in output_ids if output_id in outputs_by_id], "page": page, "pageSize": page_size}


def _dedupe_outputs_by_display_path(outputs: Iterable[WebtoonCutOutput]) -> list[WebtoonCutOutput]:
    deduped: list[WebtoonCutOutput] = []
    seen: set[str] = set()
    for output in outputs:
        key = output.display_path
        if key in seen:
            continue
        seen.add(key)
        deduped.append(output)
    return deduped


def _require_job(db: Session, job_id: str, *, created_by: str | None, include_deleted: bool = False) -> WebtoonCutJob:
    job = db.get(WebtoonCutJob, job_id)
    if job is None:
        raise KeyError(job_id)
    if job.deleted_at is not None and not include_deleted:
        raise KeyError(job_id)
    if created_by and job.created_by != created_by:
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
    metadata = job.metadata_json or {}
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
        "splitMode": _normalize_split_mode(metadata.get("splitMode")),
        "cancelRequestedAt": job.cancel_requested_at.isoformat() if job.cancel_requested_at else None,
        "createdBy": job.created_by,
        "createdAt": job.created_at.isoformat() if job.created_at else None,
        "updatedAt": job.updated_at.isoformat() if job.updated_at else None,
    }


def _normalize_split_mode(value: object) -> str:
    text = str(value or "print").strip()
    return text if text in SPLIT_MODES else "print"


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
