from __future__ import annotations

from pathlib import Path


def guess_mime_from_suffix(file_name: str | None) -> str:
    normalized_suffix = Path(file_name or "").suffix.lower()
    if normalized_suffix == ".pdf":
        return "application/pdf"
    if normalized_suffix in {".txt", ".md"}:
        return "text/plain"
    if normalized_suffix == ".png":
        return "image/png"
    if normalized_suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if normalized_suffix == ".gif":
        return "image/gif"
    if normalized_suffix == ".webp":
        return "image/webp"
    if normalized_suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if normalized_suffix == ".doc":
        return "application/msword"
    return "application/octet-stream"


def is_image_mime(file_mime: str | None) -> bool:
    return bool(file_mime and file_mime.lower().startswith("image/"))
