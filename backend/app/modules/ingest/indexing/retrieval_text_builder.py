from __future__ import annotations


def build_article_retrieval_text(
    *,
    title: str,
    markdown: str | None = None,
    preview_markdown: str | None = None,
    toc: list[dict] | None = None,
) -> str:
    headings = []
    for item in toc or []:
        heading_title = str(item.get("title", "")).strip()
        if heading_title:
            headings.append(heading_title)
        if len(headings) >= 8:
            break

    body = (markdown or preview_markdown or "").strip()
    if len(body) > 2400:
        body = body[:2400]

    parts = [title.strip()]
    if headings:
        parts.append("\n".join(headings))
    if body:
        parts.append(body)
    return "\n\n".join(part for part in parts if part).strip()
