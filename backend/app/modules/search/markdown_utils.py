from __future__ import annotations

import hashlib
from pathlib import Path


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def extract_toc(markdown: str) -> list[dict]:
    if not markdown:
        return []
    lines = markdown.splitlines()
    toc: list[dict] = []
    in_code = False
    skipped_first_h1 = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = line.strip().split(" ", 1)
        if not line.startswith("#") or len(match) != 2:
            continue
        level = len(match[0])
        if level < 1 or level > 4:
            continue
        title = match[1].strip()
        if level == 1 and not skipped_first_h1:
            skipped_first_h1 = True
            continue
        toc.append(
            {
                "id": _slugify(title),
                "title": title,
                "level": level,
            }
        )
    return toc


def normalize_text_to_markdown(*, title: str, content: str) -> str:
    normalized_content = content.strip()
    return f"# {title.strip()}\n\n{normalized_content}\n"


def build_image_markdown(*, title: str, image_url: str, body: str | None = None) -> str:
    normalized_title = title.strip() or "图片来源"
    normalized_body = (body or "").strip()
    sections = [
        f"# {normalized_title}",
        "",
        f"![{normalized_title}]({image_url})",
    ]
    if normalized_body:
        sections.extend(["", normalized_body])
    return "\n".join(sections).strip() + "\n"


def contains_image_markup(markdown: str | None) -> bool:
    if not markdown:
        return False
    lowered = markdown.lower()
    return "![" in markdown or "<img" in lowered


def decode_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def build_web_placeholder(*, title: str, url: str) -> str:
    return f"# {title}\n\n来源链接：{url}\n\n该来源已加入，等待正文抓取和解析。\n"


def _slugify(title: str) -> str:
    result = []
    for char in title.lower():
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            result.append(char)
        else:
            result.append("-")
    slug = "".join(result).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def guess_render_mode(*, file_mime: str | None, file_name: str | None) -> str:
    if file_mime == "application/pdf":
        return "pdf"
    if file_name and Path(file_name).suffix.lower() == ".pdf":
        return "pdf"
    return "markdown"
