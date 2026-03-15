"""Stage C – Document Type Router.

Classifies the artifact into a ``DocCategory`` (html, pdf, office,
text, image) so downstream stages know which parser lane to use.
"""

from __future__ import annotations

from app.modules.ingest.pipeline.types import CanonicalDoc, DocCategory, DocRoute

_MIME_MAP: dict[str, DocCategory] = {
    "text/html": DocCategory.HTML,
    "application/xhtml+xml": DocCategory.HTML,
    "application/pdf": DocCategory.PDF,
    "text/plain": DocCategory.TEXT,
    "text/markdown": DocCategory.TEXT,
    "text/csv": DocCategory.TEXT,
    "application/epub+zip": DocCategory.OFFICE,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocCategory.OFFICE,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": DocCategory.OFFICE,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DocCategory.OFFICE,
    "application/msword": DocCategory.OFFICE,
    "application/vnd.ms-powerpoint": DocCategory.OFFICE,
    "application/vnd.ms-excel": DocCategory.OFFICE,
    "application/rtf": DocCategory.OFFICE,
}

_EXT_MAP: dict[str, DocCategory] = {
    ".html": DocCategory.HTML,
    ".htm": DocCategory.HTML,
    ".pdf": DocCategory.PDF,
    ".txt": DocCategory.TEXT,
    ".md": DocCategory.TEXT,
    ".csv": DocCategory.TEXT,
    ".tsv": DocCategory.TEXT,
    ".docx": DocCategory.OFFICE,
    ".doc": DocCategory.OFFICE,
    ".pptx": DocCategory.OFFICE,
    ".ppt": DocCategory.OFFICE,
    ".xlsx": DocCategory.OFFICE,
    ".xls": DocCategory.OFFICE,
    ".epub": DocCategory.OFFICE,
    ".rtf": DocCategory.OFFICE,
    ".png": DocCategory.IMAGE,
    ".jpg": DocCategory.IMAGE,
    ".jpeg": DocCategory.IMAGE,
    ".gif": DocCategory.IMAGE,
    ".webp": DocCategory.IMAGE,
    ".svg": DocCategory.IMAGE,
}

_IMAGE_MIMES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
})


def route_document(doc: CanonicalDoc) -> DocRoute:
    """Classify the document and return parser hints."""

    mime = doc.artifact.content_type.lower()
    ext = (doc.artifact.file_ext or "").lower()

    # 1. MIME
    if mime in _IMAGE_MIMES:
        return DocRoute(category=DocCategory.IMAGE, mime_type=mime, file_ext=ext)
    cat = _MIME_MAP.get(mime)
    if cat:
        return DocRoute(
            category=cat,
            mime_type=mime,
            file_ext=ext,
            parser_hints=_hints_for(cat, doc),
        )

    # 2. Extension
    cat = _EXT_MAP.get(ext)
    if cat:
        return DocRoute(
            category=cat,
            mime_type=mime,
            file_ext=ext,
            parser_hints=_hints_for(cat, doc),
        )

    # 3. URL pattern – assume HTML if it looks like a webpage
    if doc.artifact.source_url and not ext:
        return DocRoute(
            category=DocCategory.HTML,
            mime_type=mime,
            file_ext=ext,
            parser_hints=["trafilatura"],
        )

    return DocRoute(category=DocCategory.UNKNOWN, mime_type=mime, file_ext=ext)


def _hints_for(cat: DocCategory, doc: CanonicalDoc) -> list[str]:
    if cat == DocCategory.HTML:
        hints = ["trafilatura"]
        if doc.artifact.source_url:
            hints.append("exa")
        return hints
    if cat == DocCategory.PDF:
        return ["markitdown"]
    if cat == DocCategory.OFFICE:
        return ["markitdown"]
    if cat == DocCategory.TEXT:
        return ["text_direct"]
    return []
