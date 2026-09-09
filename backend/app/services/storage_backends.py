from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from contextlib import closing
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class StoredObject:
    storage_backend: str
    storage_key: str
    file_name: str
    mime_type: str
    size_bytes: int
    public_url: str | None = None
    bucket: str | None = None
    etag: str | None = None
    last_modified: object | None = None


class LocalAssetStorage:
    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)

    def save_bytes(self, key: str, data: bytes, *, file_name: str, mime_type: str | None = None) -> StoredObject:
        path = self.root_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        resolved_mime = mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        return StoredObject(
            storage_backend="local",
            storage_key=str(path),
            file_name=file_name,
            mime_type=resolved_mime,
            size_bytes=len(data),
        )

    def save_file(self, key: str, source_path: Path, *, file_name: str | None = None, mime_type: str | None = None) -> StoredObject:
        data = Path(source_path).read_bytes()
        return self.save_bytes(key, data, file_name=file_name or Path(source_path).name, mime_type=mime_type)

    def delete(self, storage_key: str) -> bool:
        path = Path(storage_key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def stat(self, storage_key: str) -> StoredObject:
        path = Path(storage_key)
        resolved_mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return StoredObject(
            storage_backend="local",
            storage_key=str(path),
            file_name=path.name,
            mime_type=resolved_mime,
            size_bytes=path.stat().st_size,
        )

    def open_read(self, storage_key: str) -> BinaryIO:
        return Path(storage_key).open("rb")


class S3AssetStorage:
    def __init__(self, *, bucket: str, prefix: str = "", client=None, endpoint_url: str = "", force_path_style: bool = False):
        if not bucket:
            raise ValueError("S3 bucket is required")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or self._default_client(endpoint_url=endpoint_url, force_path_style=force_path_style)

    def save_bytes(self, key: str, data: bytes, *, file_name: str, mime_type: str | None = None) -> StoredObject:
        storage_key = self._key(key)
        resolved_mime = mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        response = self.client.put_object(
            Bucket=self.bucket,
            Key=storage_key,
            Body=data,
            ContentType=resolved_mime,
        )
        return StoredObject(
            storage_backend="s3",
            storage_key=storage_key,
            file_name=file_name,
            mime_type=resolved_mime,
            size_bytes=len(data),
            public_url=f"s3://{self.bucket}/{storage_key}",
            bucket=self.bucket,
            etag=(response or {}).get("ETag"),
        )

    def save_file(self, key: str, source_path: Path, *, file_name: str | None = None, mime_type: str | None = None) -> StoredObject:
        path = Path(source_path)
        storage_key = self._key(key)
        resolved_mime = mime_type or mimetypes.guess_type(file_name or path.name)[0] or "application/octet-stream"
        extra_args = {"ContentType": resolved_mime}
        self.client.upload_file(str(path), self.bucket, storage_key, ExtraArgs=extra_args)
        return StoredObject(
            storage_backend="s3",
            storage_key=storage_key,
            file_name=file_name or path.name,
            mime_type=resolved_mime,
            size_bytes=path.stat().st_size if path.exists() else 0,
            public_url=f"s3://{self.bucket}/{storage_key}",
            bucket=self.bucket,
        )

    def delete(self, storage_key: str) -> bool:
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)
        return True

    def presigned_url(self, storage_key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": storage_key},
            ExpiresIn=expires_in,
        )

    def presigned_put(self, key: str, *, content_type: str, expires_in: int = 3600) -> str:
        storage_key = self._key(key)
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": storage_key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )

    def stat(self, storage_key: str) -> StoredObject:
        response = self.client.head_object(Bucket=self.bucket, Key=storage_key)
        return StoredObject(
            storage_backend="s3",
            storage_key=storage_key,
            file_name=Path(storage_key).name,
            mime_type=response.get("ContentType") or mimetypes.guess_type(storage_key)[0] or "application/octet-stream",
            size_bytes=int(response.get("ContentLength") or 0),
            public_url=f"s3://{self.bucket}/{storage_key}",
            bucket=self.bucket,
            etag=response.get("ETag"),
            last_modified=response.get("LastModified"),
        )

    def open_read(self, storage_key: str):
        response = self.client.get_object(Bucket=self.bucket, Key=storage_key)
        return closing(response["Body"])

    def _key(self, key: str) -> str:
        cleaned = str(key or "").strip().lstrip("/")
        if not cleaned:
            raise ValueError("storage key is required")
        return f"{self.prefix}/{cleaned}" if self.prefix else cleaned

    @staticmethod
    def _default_client(*, endpoint_url: str = "", force_path_style: bool = False):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for STORAGE_BACKEND=s3") from exc
        kwargs = {}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if force_path_style:
            try:
                from botocore.config import Config
            except ImportError as exc:
                raise RuntimeError("botocore is required for S3_FORCE_PATH_STYLE=1") from exc
            kwargs["config"] = Config(s3={"addressing_style": "path"})
        return boto3.client("s3", **kwargs)
