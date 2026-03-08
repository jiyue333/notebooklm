from __future__ import annotations

import re
from pathlib import Path

from app.core.config import BASE_DIR

UPLOAD_ROOT = BASE_DIR / "data"


def _safe_filename(filename: str) -> str:
    name = filename or "upload.bin"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return safe or "upload.bin"


def build_storage_key(*, notebook_id: str, article_id: str, filename: str) -> str:
    safe_name = _safe_filename(filename)
    return str(Path("uploads") / notebook_id / article_id / safe_name)


def ensure_parent_dir(storage_key: str) -> Path:
    absolute_path = UPLOAD_ROOT / storage_key
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    return absolute_path


def resolve_storage_path(storage_key: str) -> Path:
    return UPLOAD_ROOT / storage_key
