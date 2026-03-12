from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UploadedSourceFile:
    file_name: str | None
    content_type: str | None
    data: bytes
