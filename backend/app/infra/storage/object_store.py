from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from minio import Minio

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class StoredObject:
    key: str
    bucket: str
    content_type: str


class ObjectStore(Protocol):
    def put_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str: ...

    def delete(self, key: str) -> None: ...


class S3CompatibleObjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = Minio(
            endpoint=self._settings.object_storage_endpoint,
            access_key=self._settings.object_storage_access_key,
            secret_key=self._settings.object_storage_secret_key,
            secure=self._settings.object_storage_secure,
            region=self._settings.object_storage_region,
        )

    @property
    def bucket(self) -> str:
        return self._settings.object_storage_bucket

    def ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self.bucket):
            self._client.make_bucket(self.bucket)

    def put_bytes(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        self.ensure_bucket()
        self._client.put_object(
            self.bucket,
            key,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return StoredObject(key=key, bucket=self.bucket, content_type=content_type)

    def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        return self._client.presigned_get_object(self.bucket, key, expires=expires_seconds)

    def delete(self, key: str) -> None:
        self._client.remove_object(self.bucket, key)
