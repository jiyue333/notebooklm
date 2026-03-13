from __future__ import annotations

from pathlib import Path

from app.modules.ingest.quality.quality_scorer import ParseQuality


def classify_document_type(
    *,
    input_type: str,
    file_name: str | None = None,
    file_mime: str | None = None,
    parser_name: str | None = None,
    markdown: str | None = None,
    quality: ParseQuality | None = None,
) -> str:
    if input_type in {"url", "search_result"}:
        return "webpage"
    if input_type == "text":
        return "text"

    suffix = Path(file_name or "").suffix.lower()
    mime = (file_mime or "").lower()
    parser = (parser_name or "").lower()
    text = (markdown or "").strip()

    if mime.startswith("image/"):
        return "image"
    if suffix == ".pdf" or mime == "application/pdf":
        if parser.startswith("ocr") or parser.startswith("vision"):
            return "pdf_scanned"
        if quality is not None and quality.needs_llm_fallback and len(text) < 400:
            return "pdf_scanned_like"
        return "pdf"
    if suffix in {".doc", ".docx"} or "word" in mime:
        return "word"
    if suffix in {".ppt", ".pptx"} or "powerpoint" in mime or "presentation" in mime:
        return "powerpoint"
    if suffix in {".html", ".htm"} or mime == "text/html":
        return "html"
    if suffix == ".md":
        return "markdown"
    if suffix == ".txt" or mime.startswith("text/plain"):
        return "plain_text"
    return "other_file"
