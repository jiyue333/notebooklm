from __future__ import annotations

from hashlib import sha256

from app.modules.ingest.draft import IngestDraft


def build_dedupe_key(draft: IngestDraft) -> str:
    if draft.file_bytes is not None:
        return sha256(draft.file_bytes).hexdigest()
    if draft.normalized_url or draft.source_url:
        return sha256((draft.normalized_url or draft.source_url or "").encode("utf-8")).hexdigest()
    if draft.raw_text_input:
        return sha256(draft.raw_text_input.encode("utf-8")).hexdigest()
    return sha256((draft.preview_markdown or draft.title).encode("utf-8")).hexdigest()


def extract_file_ext(file_name: str | None) -> str | None:
    if not file_name:
        return None
    suffix = file_name.rsplit(".", 1)
    if len(suffix) == 1:
        return None
    return suffix[-1].lower()
