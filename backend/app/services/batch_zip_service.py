"""Stream completed batch outputs as an output/-prefixed ZIP archive."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Asset, BatchJob, TaskInputAsset, TaskOutputAsset, WorkflowTask
from backend.app.db.session import SessionLocal
from backend.app.services import batch_job_service

OUTPUT_DIR = "output"
CHUNK_SIZE = 1024 * 1024
ZIP_RESPONSE_HEADERS = {"Content-Encoding": "identity"}


def zip_entry_name(source_file_name: str, used: set[str]) -> str:
    stem = Path(str(source_file_name or "video")).name
    stem = Path(stem).stem or "video"
    candidate = f"{OUTPUT_DIR}/{stem}.mp4"
    if candidate not in used:
        return candidate
    index = 1
    while f"{OUTPUT_DIR}/{stem}-{index}.mp4" in used:
        index += 1
    return f"{OUTPUT_DIR}/{stem}-{index}.mp4"


def collect_batch_outputs(db: Session, batch_job_id: str, *, task_ids: list[str] | None) -> list[dict]:
    query = (
        select(WorkflowTask.id, TaskOutputAsset.asset_id, Asset.file_name)
        .join(TaskOutputAsset, TaskOutputAsset.task_id == WorkflowTask.id)
        .join(Asset, Asset.id == TaskOutputAsset.asset_id)
        .where(
            WorkflowTask.batch_job_id == batch_job_id,
            WorkflowTask.deleted_at.is_(None),
            WorkflowTask.status.in_(batch_job_service.SUCCESS_TASK_STATES),
        )
        .order_by(WorkflowTask.created_at.asc(), WorkflowTask.id.asc())
    )
    if task_ids:
        query = query.where(WorkflowTask.id.in_(task_ids))

    source_names = _source_file_names(db, batch_job_id)
    used: set[str] = set()
    collected: list[dict] = []
    for task_id, asset_id, output_file_name in db.execute(query).all():
        base_name = source_names.get(str(task_id)) or output_file_name or task_id
        entry = zip_entry_name(str(base_name), used)
        used.add(entry)
        collected.append({"assetId": str(asset_id), "entryName": entry})
    return collected


def _source_file_names(db: Session, batch_job_id: str) -> dict[str, str]:
    rows = db.execute(
        select(WorkflowTask.id, Asset.file_name)
        .join(TaskInputAsset, TaskInputAsset.task_id == WorkflowTask.id)
        .join(Asset, Asset.id == TaskInputAsset.asset_id)
        .where(WorkflowTask.batch_job_id == batch_job_id)
        .order_by(TaskInputAsset.slot_index.asc())
    ).all()
    names: dict[str, str] = {}
    for task_id, file_name in rows:
        names.setdefault(str(task_id), str(file_name))
    return names


def stream_batch_zip(batch_job_id: str, *, task_ids: list[str] | None) -> tuple[Iterator[bytes], int]:
    from backend.app.services import studio_api_service

    db = SessionLocal()
    try:
        if db.get(BatchJob, batch_job_id) is None:
            raise ValueError("배치 작업을 찾을 수 없습니다.")
        entries = collect_batch_outputs(db, batch_job_id, task_ids=task_ids)
    finally:
        db.close()

    resolved: list[tuple[str, Path]] = []
    skipped = 0
    for entry in entries:
        try:
            _, path = studio_api_service.get_asset(entry["assetId"])
        except (KeyError, FileNotFoundError):
            skipped += 1
            continue
        if not path.exists():
            skipped += 1
            continue
        resolved.append((entry["entryName"], path))

    if not resolved:
        raise ValueError("내려받을 완료 영상이 없습니다.")

    def generate() -> Iterator[bytes]:
        buffer = _StreamBuffer()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
            for entry_name, path in resolved:
                with archive.open(entry_name, mode="w") as target, path.open("rb") as source:
                    while True:
                        chunk = source.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        target.write(chunk)
                        yield from buffer.drain()
                yield from buffer.drain()
        yield from buffer.drain()

    return generate(), skipped


class _StreamBuffer:
    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._position = 0

    def write(self, data: bytes) -> int:
        chunk = bytes(data)
        self._parts.append(chunk)
        self._position += len(chunk)
        return len(chunk)

    def flush(self) -> None:
        return None

    def tell(self) -> int:
        return self._position

    def seekable(self) -> bool:
        return False

    def drain(self) -> Iterator[bytes]:
        parts, self._parts = self._parts, []
        for part in parts:
            if part:
                yield part
