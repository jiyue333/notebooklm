from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.config import BASE_DIR, Settings, get_settings
from app.infra.storage.object_store import get_object_store

UPLOAD_ROOT = BASE_DIR / "data"


def _safe_filename(filename: str) -> str:
    name = filename or "upload.bin"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return safe or "upload.bin"


def build_storage_key(*, notebook_id: str, article_id: str, filename: str) -> str:
    safe_name = _safe_filename(filename)
    return str(Path("uploads") / notebook_id / article_id / safe_name)


def is_object_storage_enabled(settings: Settings | None = None) -> bool:
    backend = (settings or get_settings()).file_storage_backend.strip().lower()
    return backend in {"minio", "object", "object_store", "s3"}


def ensure_parent_dir(storage_key: str) -> Path:
    absolute_path = UPLOAD_ROOT / storage_key
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    return absolute_path


def resolve_storage_path(storage_key: str) -> Path:
    return UPLOAD_ROOT / storage_key


def store_file_bytes(*, storage_key: str, data: bytes, content_type: str) -> None:
    if is_object_storage_enabled():
        get_object_store().put_bytes(key=storage_key, data=data, content_type=content_type)
        return
    ensure_parent_dir(storage_key).write_bytes(data)


def load_file_bytes(storage_key: str) -> bytes:
    if is_object_storage_enabled():
        return get_object_store().get_bytes(storage_key)
    return resolve_storage_path(storage_key).read_bytes()


def stored_file_exists(storage_key: str) -> bool:
    if is_object_storage_enabled():
        return get_object_store().exists(storage_key)
    return resolve_storage_path(storage_key).exists()


def build_presigned_get_url(storage_key: str, *, expires_seconds: int = 3600) -> str | None:
    if not is_object_storage_enabled():
        return None
    return get_object_store().presigned_get_url(storage_key, expires_seconds=expires_seconds)


@contextmanager
def materialize_uploaded_file_for_parser(*, file_name: str | None, file_bytes: bytes):
    suffix = Path(file_name or "").suffix
    with NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(file_bytes)
        temp_path = Path(handle.name)
    try:
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


@contextmanager
def materialize_stored_file_for_parser(*, storage_key: str, file_name: str | None):
    if not is_object_storage_enabled():
        yield resolve_storage_path(storage_key)
        return

    data = load_file_bytes(storage_key)
    with materialize_uploaded_file_for_parser(file_name=file_name, file_bytes=data) as temp_path:
        yield temp_path
