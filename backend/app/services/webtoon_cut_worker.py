from __future__ import annotations

import mimetypes
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from backend.app.core.timezone_utils import utc_now
from backend.app.core.config import get_settings
from backend.app.db.models import Asset, WebtoonCutJob
from backend.app.db.session import SessionLocal
from backend.app.services.studio_api_service import s3_asset_storage
from backend.app.services.webtoon_cut_naming import make_source_identity, output_relative_path, validate_zip_entry_path
from backend.app.services.webtoon_cut_service import register_output
from backend.app.services.webtoon_panel_engine import page_count, process_image_file, process_pdf_page


def process_next_pending_job() -> dict:
    with SessionLocal() as session:
        job = session.scalars(_pending_job_claim_statement()).first()
        if job is None:
            return {"processed": False}
        job.status = "running"
        job.started_at = _now()
        job.updated_at = _now()
        session.commit()
        job_id = job.id
    return process_job(job_id)


def _pending_job_claim_statement():
    return (
        select(WebtoonCutJob)
        .where(WebtoonCutJob.status == "pending")
        .order_by(asc(WebtoonCutJob.created_at))
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def process_job(job_id: str) -> dict:
    workdir = Path(tempfile.mkdtemp(prefix=f"webtoon_cut_{job_id}_"))
    try:
        with SessionLocal() as session:
            job = session.get(WebtoonCutJob, job_id)
            if job is None:
                return {"processed": False, "reason": "missing"}
            source = session.get(Asset, job.source_asset_id)
            if source is None:
                _fail_job(session, job, "source asset missing")
                return {"processed": False, "reason": "source_missing"}
            local_source = _materialize_asset(source, workdir)
            total_units = _count_units(local_source, job.input_kind)
            job.total_units = total_units
            job.updated_at = _now()
            session.commit()

        try:
            if _is_zip(local_source):
                _process_zip_job(job_id, local_source, workdir)
            elif _is_pdf(local_source):
                _process_pdf_job(job_id, local_source, workdir)
            else:
                _process_image_job(job_id, local_source, workdir)
        except Exception as exc:
            with SessionLocal() as session:
                job = session.get(WebtoonCutJob, job_id)
                if job is not None:
                    _fail_job(session, job, str(exc))
            return {"processed": False, "jobId": job_id, "reason": "failed"}

        with SessionLocal() as session:
            job = session.get(WebtoonCutJob, job_id)
            if job is None:
                return {"processed": True}
            if job.status not in {"failed", "cancelled"}:
                job.status = "completed"
            job.completed_at = _now()
            job.updated_at = _now()
            session.commit()
        return {"processed": True, "jobId": job_id}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _process_pdf_job(
    job_id: str,
    pdf_path: Path,
    workdir: Path,
    *,
    source_stem: str | None = None,
    input_kind: str = "pdf",
    zip_stem: str | None = None,
    zip_internal_relative_dir: str | None = None,
) -> None:
    total = page_count(pdf_path)
    for page_number in range(1, total + 1):
        with SessionLocal() as session:
            job = session.get(WebtoonCutJob, job_id)
            if job is None or _job_should_stop(job):
                return
            job.current_unit_label = f"page {page_number:03d}"
            job.updated_at = _now()
            session.commit()
        page_out = workdir / "pages" / f"{page_number:03d}"
        try:
            result = process_pdf_page(pdf_path, page_number=page_number, output_dir=page_out)
            with SessionLocal() as session:
                job = session.get(WebtoonCutJob, job_id)
                if job is None or _job_should_stop(job):
                    return
            _store_result(
                job_id,
                result,
                source_stem=source_stem,
                input_kind=input_kind,
                zip_stem=zip_stem,
                zip_internal_relative_dir=zip_internal_relative_dir,
            )
        finally:
            shutil.rmtree(page_out, ignore_errors=True)


def _process_image_job(
    job_id: str,
    image_path: Path,
    workdir: Path,
    *,
    source_stem: str | None = None,
    input_kind: str = "image",
    zip_stem: str | None = None,
    zip_internal_relative_dir: str | None = None,
) -> None:
    with SessionLocal() as session:
        job = session.get(WebtoonCutJob, job_id)
        if job is None or _job_should_stop(job):
            return
        job.current_unit_label = image_path.name
        job.updated_at = _now()
        session.commit()
    result = process_image_file(image_path, output_dir=workdir / "image", page_number=None)
    with SessionLocal() as session:
        job = session.get(WebtoonCutJob, job_id)
        if job is None or _job_should_stop(job):
            return
    _store_result(
        job_id,
        result,
        source_stem=source_stem,
        input_kind=input_kind,
        zip_stem=zip_stem,
        zip_internal_relative_dir=zip_internal_relative_dir,
    )


def _process_zip_job(job_id: str, zip_path: Path, workdir: Path) -> None:
    extract_root = workdir / "zip"
    extract_root.mkdir(parents=True, exist_ok=True)
    zip_identity = make_source_identity(zip_path.name)
    with zipfile.ZipFile(zip_path) as archive:
        entries = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            try:
                entry_path = validate_zip_entry_path(info.filename)
            except ValueError:
                continue
            suffix = Path(entry_path).suffix.lower()
            if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                continue
            target = extract_root / entry_path
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            entries.append((entry_path, target))

    for entry_path, target in sorted(entries, key=lambda item: item[0]):
        rel_dir = str(Path(entry_path).parent)
        if rel_dir == ".":
            rel_dir = ""
        source_stem = Path(entry_path).stem
        if target.suffix.lower() == ".pdf":
            _process_pdf_job(
                job_id,
                target,
                workdir / "zip-pdf" / source_stem,
                source_stem=source_stem,
                input_kind="zip_pdf",
                zip_stem=zip_identity.display_stem,
                zip_internal_relative_dir=rel_dir,
            )
        else:
            _process_image_job(
                job_id,
                target,
                workdir / "zip-image" / source_stem,
                source_stem=source_stem,
                input_kind="zip_image",
                zip_stem=zip_identity.display_stem,
                zip_internal_relative_dir=rel_dir,
            )


def _store_result(
    job_id: str,
    result,
    *,
    source_stem: str | None = None,
    input_kind: str = "image",
    zip_stem: str | None = None,
    zip_internal_relative_dir: str | None = None,
) -> None:
    with SessionLocal() as session:
        job = session.get(WebtoonCutJob, job_id)
        if job is None:
            return
        resolved_source_stem = source_stem or str((job.metadata_json or {}).get("displayStem") or Path(job.display_name).stem)
        for cut in result.cuts:
            rel_path = output_relative_path(
                input_kind=input_kind if input_kind.startswith("zip_") else ("pdf" if result.page_number else "image"),
                source_stem=resolved_source_stem,
                page_number=result.page_number,
                cut_index=cut.cut_index,
                zip_stem=zip_stem,
                zip_internal_relative_dir=zip_internal_relative_dir,
            )
            asset = _store_cut_asset(session, cut.path, rel_path=rel_path, created_by=job.created_by, width=cut.width, height=cut.height)
            register_output(
                session,
                job_id=job.id,
                asset_id=asset.id,
                display_path=rel_path,
                page_number=result.page_number,
                cut_index=cut.cut_index,
                width=cut.width,
                height=cut.height,
                flags=list(dict.fromkeys([*result.flags, *cut.flags])),
                created_by=job.created_by,
            )
        job.completed_units += 1
        job.updated_at = _now()
        session.commit()


def _store_cut_asset(session: Session, path: Path, *, rel_path: str, created_by: str, width: int, height: int) -> Asset:
    settings = get_settings()
    key = f"webtoon-cut/users/{created_by}/outputs/{uuid.uuid4().hex[:12]}/{rel_path}"
    storage = s3_asset_storage()
    stored = storage.save_file(key, path, file_name=Path(rel_path).name, mime_type="image/png")
    asset = Asset(
        id=f"asset_{uuid.uuid4().hex[:12]}",
        asset_type="webtoon_cut_image",
        file_name=Path(rel_path).name,
        mime_type="image/png",
        size_bytes=stored.size_bytes,
        image_width=width or None,
        image_height=height or None,
        storage_backend="s3",
        storage_key=stored.storage_key,
        public_url=f"s3://{settings.s3_bucket}/{stored.storage_key}",
        metadata_json={"createdBy": created_by, "displayPath": rel_path},
        created_at=_now(),
    )
    session.add(asset)
    session.flush()
    return asset


def _materialize_asset(asset: Asset, workdir: Path) -> Path:
    suffix = Path(asset.file_name).suffix or mimetypes.guess_extension(asset.mime_type) or ".bin"
    target = workdir / f"source{suffix}"
    if asset.storage_backend == "s3":
        with s3_asset_storage().open_read(asset.storage_key) as stream:
            target.write_bytes(stream.read())
    else:
        shutil.copyfile(Path(asset.storage_key), target)
    return target


def _count_units(path: Path, input_kind: str) -> int:
    if _is_zip(path) or input_kind == "zip":
        return _count_zip_units(path)
    if _is_pdf(path) or input_kind == "pdf":
        return page_count(path)
    return 1


def _count_zip_units(path: Path) -> int:
    total = 0
    with tempfile.TemporaryDirectory(prefix="webtoon_zip_count_") as tmp:
        tmpdir = Path(tmp)
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                try:
                    entry_path = validate_zip_entry_path(info.filename)
                except ValueError:
                    continue
                suffix = Path(entry_path).suffix.lower()
                if suffix == ".pdf":
                    target = tmpdir / f"{uuid.uuid4().hex}.pdf"
                    with archive.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    total += page_count(target)
                elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    total += 1
    return total or 1


def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def _is_zip(path: Path) -> bool:
    return path.suffix.lower() == ".zip"


def _job_should_stop(job: WebtoonCutJob) -> bool:
    return job.status in {"cancel_requested", "cancelled", "failed"}


def _fail_job(session, job: WebtoonCutJob, message: str) -> None:
    job.status = "failed"
    job.error_message = message
    job.updated_at = _now()
    session.commit()


def _now():
    return utc_now().replace(tzinfo=None)
