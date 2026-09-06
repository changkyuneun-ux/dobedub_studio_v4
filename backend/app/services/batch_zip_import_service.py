"""ZIP upload import for batch image jobs."""
from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path, PurePosixPath
import stat
import uuid
import zipfile

from backend.app.repositories.factory import data_paths
from backend.app.services import studio_api_service
from backend.app.services.zip_encoding_service import normalize_zip_path


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_ZIP_BYTES = 500 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_IMAGE_COUNT = 500


@dataclass(frozen=True)
class BatchZipImportResult:
    source_dir_name: str
    source_zip_file_name: str
    image_count: int
    items: list[dict[str, str]]


def import_zip_bytes(
    raw: bytes,
    *,
    zip_file_name: str,
    work_dir: Path | None = None,
) -> BatchZipImportResult:
    """Validate, persist extracted images, and register them as input assets."""
    if not zip_file_name.lower().endswith(".zip"):
        raise ValueError("ZIP 파일만 업로드할 수 있습니다.")
    if not raw:
        raise ValueError("업로드한 ZIP 파일이 비어 있습니다.")
    if len(raw) > MAX_ZIP_BYTES:
        raise ValueError("업로드한 ZIP 파일이 허용 크기를 초과했습니다.")

    root = Path(work_dir) if work_dir is not None else data_paths()["uploads"] / "batch_zip_imports"
    import_dir = root / f"batch_zip_{uuid.uuid4().hex[:12]}"
    import_dir.mkdir(parents=True, exist_ok=True)

    try:
        zip_path = import_dir / "source.zip"
        zip_path.write_bytes(raw)
        with zipfile.ZipFile(zip_path) as archive:
            members = _image_members(archive)
            if not members:
                raise ValueError("ZIP 안에 처리할 이미지 파일이 없습니다.")
            if len(members) > MAX_IMAGE_COUNT:
                raise ValueError(f"이미지는 최대 {MAX_IMAGE_COUNT}개까지 처리할 수 있습니다.")
            total_size = sum(int(member.file_size or 0) for member, _path in members)
            if total_size > MAX_EXTRACTED_BYTES:
                raise ValueError("압축 해제 후 이미지 크기 합계가 허용 범위를 초과했습니다.")

            source_dir_name = _source_dir_name([path for _member, path in members], zip_file_name)
            items: list[dict[str, str]] = []
            for member, safe_path in members:
                target = import_dir / "images" / Path(*safe_path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    destination.write(source.read())
                file_name = safe_path.name
                asset = studio_api_service.register_asset(
                    target,
                    "input_image",
                    mimetypes.guess_type(file_name)[0] or "application/octet-stream",
                    file_name,
                )
                items.append({
                    "assetId": str(asset["assetId"]),
                    "fileName": file_name,
                    "relativePath": safe_path.as_posix(),
                })
    except zipfile.BadZipFile as exc:
        raise ValueError("올바른 ZIP 파일이 아닙니다.") from exc
    finally:
        candidate = import_dir / "source.zip"
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass

    return BatchZipImportResult(
        source_dir_name=source_dir_name,
        source_zip_file_name=normalize_zip_path(Path(zip_file_name).name),
        image_count=len(items),
        items=items,
    )


def _image_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    result: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for member in archive.infolist():
        safe_path = _safe_member_path(member)
        if safe_path is None:
            continue
        result.append((member, safe_path))
    result.sort(key=lambda item: item[1].as_posix())
    return result


def _safe_member_path(member: zipfile.ZipInfo) -> PurePosixPath | None:
    raw_name = normalize_zip_path(member.filename).replace("\\", "/")
    path = PurePosixPath(raw_name)
    if member.is_dir():
        return None
    if member.flag_bits & 0x1:
        raise ValueError("암호화된 ZIP 파일은 처리할 수 없습니다.")
    mode = (member.external_attr >> 16) & 0xFFFF
    if mode and stat.S_ISLNK(mode):
        raise ValueError("ZIP 안의 심볼릭 링크는 처리할 수 없습니다.")
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"안전하지 않은 ZIP 경로입니다: {raw_name}")
    if "__MACOSX" in path.parts or path.name == ".DS_Store" or path.name.startswith("._"):
        return None
    if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        return None
    return path


def _source_dir_name(paths: list[PurePosixPath], zip_file_name: str) -> str:
    top_levels = {path.parts[0] for path in paths if len(path.parts) > 1}
    if len(top_levels) == 1 and all(len(path.parts) > 1 for path in paths):
        return next(iter(top_levels))
    return Path(Path(zip_file_name).name).stem or "upload"


__all__ = [
    "BatchZipImportResult",
    "SUPPORTED_IMAGE_SUFFIXES",
    "import_zip_bytes",
]
