from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.ai.lite_models import build_lite_llm
from app.infra.cache import delete_keys, get_json, notebook_detail_key, set_json
from app.infra.storage.file_store import is_object_storage_enabled
from app.modules.highlights import repo as highlights_repo
from app.modules.notes import repo as notes_repo
from app.modules.notebooks import assembler, repo


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    normalized: list[str] = []
    for item in tags:
        tag = str(item or '').strip()
        if not tag:
            continue
        if tag not in normalized:
            normalized.append(tag)
    return normalized[:8]


_AUTO_NOTEBOOK_TITLE_MAX_LEN = 64
_AUTO_NOTEBOOK_ICON_TIMEOUT_SECONDS = 4.0
_AUTO_NOTEBOOK_TITLE_TIMEOUT_SECONDS = 4.0


def _sanitize_notebook_title(value: str | None) -> str:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    normalized = normalized.strip("'\"`“”‘’")
    return normalized[:_AUTO_NOTEBOOK_TITLE_MAX_LEN]


def _fallback_notebook_title(*, tags: list[str] | None = None) -> str:
    if tags:
        first_tag = _sanitize_notebook_title(tags[0] if tags else "")
        if first_tag:
            return f"{first_tag} 研究"
    return f"未命名笔记本 {datetime.now().strftime('%m-%d')}"


def _flatten_llm_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


async def _generate_notebook_title_with_lite_model(*, tags: list[str], article_titles: list[str]) -> str | None:
    model = build_lite_llm()
    if model is None:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception:
        return None

    tags_text = "、".join(tags[:6]) if tags else "无标签"
    article_text = "\n".join(f"- {item}" for item in article_titles[:6]) if article_titles else "- 暂无来源"
    user_prompt = (
        "请根据下面信息生成一个简短的中文笔记本标题。\n"
        "要求：不超过16个中文字符；不要加引号、序号、句号。\n"
        f"标签：{tags_text}\n"
        "来源标题：\n"
        f"{article_text}\n"
        "仅输出标题。"
    )
    try:
        response = await asyncio.wait_for(
            model.ainvoke([
                SystemMessage(content="你是笔记本标题生成器。"),
                HumanMessage(content=user_prompt),
            ]),
            timeout=_AUTO_NOTEBOOK_TITLE_TIMEOUT_SECONDS,
        )
    except Exception:
        return None

    generated = _sanitize_notebook_title(_flatten_llm_content(getattr(response, "content", "")))
    return generated or None


async def _generate_notebook_icon_with_lite_model(*, title: str, article_titles: list[str]) -> str | None:
    model = build_lite_llm()
    if model is None:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception:
        return None

    article_text = "\n".join(f"- {item}" for item in article_titles[:8]) if article_titles else "- 暂无来源"
    user_prompt = (
        "请为这个研究笔记本生成一个最贴切的单个 emoji 图标。\n"
        "规则：只能输出 1 个 emoji；不要输出解释、文字或标点。\n"
        f"笔记本标题：{title}\n"
        "来源标题：\n"
        f"{article_text}\n"
        "仅输出 emoji。"
    )
    try:
        response = await asyncio.wait_for(
            model.ainvoke([
                SystemMessage(content="你是图标生成器。"),
                HumanMessage(content=user_prompt),
            ]),
            timeout=_AUTO_NOTEBOOK_ICON_TIMEOUT_SECONDS,
        )
    except Exception:
        return None

    generated = str(_flatten_llm_content(getattr(response, "content", ""))).strip().split()[0] if response else ""
    generated = generated.strip("'\"`“”‘’")
    if not generated:
        return None
    return generated[:8]


async def _resolve_notebook_title(
    *,
    title: str | None,
    tags: list[str],
    article_titles: list[str],
) -> str:
    normalized = _sanitize_notebook_title(title)
    if normalized:
        return normalized
    generated = await _generate_notebook_title_with_lite_model(tags=tags, article_titles=article_titles)
    return generated or _fallback_notebook_title(tags=tags)


async def _ensure_notebook_icon(
    session: AsyncSession,
    *,
    notebook,
    article_titles: list[str],
) -> None:
    if notebook.emoji:
        return
    if not article_titles:
        return
    generated_icon = await _generate_notebook_icon_with_lite_model(
        title=_sanitize_notebook_title(notebook.title) or _fallback_notebook_title(),
        article_titles=article_titles,
    )
    if generated_icon:
        notebook.emoji = generated_icon
        await session.flush()


async def list_notebooks(session: AsyncSession, *, user_id: str, query: str | None = None) -> list[dict]:
    notebooks = await repo.list_notebooks(session, user_id=user_id, query=query)
    counts = await repo.count_articles_by_notebook_ids(
        session,
        user_id=user_id,
        notebook_ids=[notebook.id for notebook in notebooks],
    )
    articles_cache: dict[str, list] = {}
    should_commit = False

    async def _get_notebook_articles(notebook_id: str):
        if notebook_id in articles_cache:
            return articles_cache[notebook_id]
        articles = await repo.list_articles_by_notebook(
            session,
            user_id=user_id,
            notebook_id=notebook_id,
        )
        articles_cache[notebook_id] = articles
        return articles

    for notebook in notebooks:
        notebook_tags = notebook.tags_json or []
        normalized_title = _sanitize_notebook_title(notebook.title)
        if not normalized_title:
            articles = await _get_notebook_articles(notebook.id)
            article_titles = [
                _sanitize_notebook_title(article.title)
                for article in articles
                if _sanitize_notebook_title(article.title)
            ]
            notebook.title = await _resolve_notebook_title(
                title=notebook.title,
                tags=notebook_tags,
                article_titles=article_titles,
            )
            should_commit = True

        if counts.get(notebook.id, 0) > 0 and not notebook.emoji:
            articles = await _get_notebook_articles(notebook.id)
            article_titles = [
                _sanitize_notebook_title(article.title)
                for article in articles
                if _sanitize_notebook_title(article.title)
            ]
            before = notebook.emoji
            await _ensure_notebook_icon(
                session,
                notebook=notebook,
                article_titles=article_titles,
            )
            if notebook.emoji != before:
                should_commit = True

    if should_commit:
        await session.commit()

    return [
        assembler.build_notebook_summary(notebook, source_count=counts.get(notebook.id, 0))
        for notebook in notebooks
    ]


async def create_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    title: str | None,
    emoji: str | None,
    color: str | None,
    tags: list[str] | None = None,
) -> dict:
    normalized_tags = _normalize_tags(tags)
    normalized_title = await _resolve_notebook_title(
        title=title,
        tags=normalized_tags,
        article_titles=[],
    )
    if await _title_exists(session, user_id=user_id, title=normalized_title):
        raise AppError(409, '笔记本标题已存在', code='notebook_title_conflict')

    notebook = await repo.create_notebook(
        session,
        user_id=user_id,
        title=normalized_title,
        emoji=emoji,
        color=color,
        tags=normalized_tags,
    )
    await session.commit()
    await session.refresh(notebook)
    detail = assembler.build_notebook_detail(notebook, [], [], source_count=0)
    await set_json(
        notebook_detail_key(user_id=user_id, notebook_id=notebook.id),
        detail,
        ttl_seconds=_resolve_notebook_detail_ttl(detail),
    )
    return detail


async def get_notebook_detail(session: AsyncSession, *, user_id: str, notebook_id: str, mark_opened: bool = True) -> dict:
    cache_key = notebook_detail_key(user_id=user_id, notebook_id=notebook_id)
    cached = await get_json(cache_key)
    if isinstance(cached, dict) and not _should_refresh_cached_notebook_detail(cached):
        if mark_opened:
            notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
            if notebook is not None:
                await repo.mark_notebook_opened(session, notebook=notebook, opened_at=datetime.now(UTC))
                await session.commit()
        return cached

    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, '未找到对应的笔记本', code='notebook_not_found')

    if mark_opened:
        await repo.mark_notebook_opened(session, notebook=notebook, opened_at=datetime.now(UTC))

    notes = await notes_repo.list_notes(session, user_id=user_id, notebook_id=notebook_id)
    articles = await repo.list_articles_by_notebook(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
    )
    await _ensure_notebook_icon(
        session,
        notebook=notebook,
        article_titles=[_sanitize_notebook_title(article.title) for article in articles if _sanitize_notebook_title(article.title)],
    )
    detail = assembler.build_notebook_detail(notebook, notes, articles, source_count=len(articles))
    await set_json(cache_key, detail, ttl_seconds=_resolve_notebook_detail_ttl(detail))
    await session.commit()
    return detail


async def update_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    title: str | None,
    emoji: str | None,
    color: str | None,
    tags: list[str] | None = None,
) -> dict:
    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, '未找到对应的笔记本', code='notebook_not_found')

    if title is not None:
        existing_articles = await repo.list_articles_by_notebook(
            session,
            user_id=user_id,
            notebook_id=notebook_id,
        )
        normalized_title = await _resolve_notebook_title(
            title=title,
            tags=_normalize_tags(tags) if tags is not None else (notebook.tags_json or []),
            article_titles=[
                _sanitize_notebook_title(article.title)
                for article in existing_articles
                if _sanitize_notebook_title(article.title)
            ],
        )
        title_owner = await repo.get_notebook_by_title(session, user_id=user_id, title=normalized_title)
        if title_owner is not None and title_owner.id != notebook_id:
            raise AppError(409, '笔记本标题已存在', code='notebook_title_conflict')
        notebook.title = normalized_title
    if emoji is not None:
        notebook.emoji = emoji
    if color is not None:
        notebook.color = color
    if tags is not None:
        notebook.tags_json = _normalize_tags(tags)

    await session.commit()
    await session.refresh(notebook)
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)
    return assembler.build_notebook_summary(notebook)


def _sanitize_markdown_heading(value: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[\r\n#]+", " ", str(value or "")).strip()
    return cleaned or fallback


def _sanitize_markdown_filename(value: str | None) -> str:
    cleaned = re.sub(r"[\\/\r\n:*?\"<>|]+", "-", str(value or "notebook")).strip(" .")
    return cleaned or "notebook"


def _highlight_color_label(color: str | None) -> str:
    mapping = {
        "yellow": "黄色",
        "blue": "蓝色",
        "green": "绿色",
        "pink": "粉色",
        "purple": "紫色",
        "orange": "橙色",
    }
    return mapping.get(str(color or "").lower(), "默认")


async def export_notebook_markdown(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
) -> tuple[str, str]:
    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    notes = await notes_repo.list_notes(session, user_id=user_id, notebook_id=notebook_id)
    articles = await repo.list_articles_by_notebook(session, user_id=user_id, notebook_id=notebook_id)
    highlights = await highlights_repo.list_notebook_highlights(session, user_id=user_id, notebook_id=notebook_id)

    article_title_map = {
        article.id: _sanitize_markdown_heading(article.title, "未命名文章")
        for article in articles
    }

    lines: list[str] = []
    lines.append(f"# {_sanitize_markdown_heading(notebook.title, '未命名笔记本')}")
    lines.append("")
    lines.append(f"- 导出时间：{datetime.now(UTC).astimezone().isoformat(timespec='seconds')}")
    lines.append(f"- 笔记数量：{len(notes)}")
    lines.append(f"- 高亮数量：{len(highlights)}")
    lines.append("")

    lines.append("## 笔记")
    lines.append("")
    if not notes:
        lines.append("_暂无笔记_")
        lines.append("")
    else:
        for idx, note in enumerate(notes, 1):
            lines.append(f"### {idx}. {_sanitize_markdown_heading(note.title, '无标题笔记')}")
            if note.tags_json:
                lines.append(f"- 标签：{', '.join(note.tags_json)}")
            lines.append(f"- 类型：{note.note_type}")
            lines.append(f"- 来源数：{note.source_count}")
            lines.append("")
            content = (note.content_markdown or "").strip()
            lines.append(content if content else "_（空内容）_")
            lines.append("")

    lines.append("## 高亮汇总")
    lines.append("")
    if not highlights:
        lines.append("_暂无高亮_")
        lines.append("")
    else:
        grouped: dict[str, list] = {}
        for item in highlights:
            grouped.setdefault(item.article_id, []).append(item)

        for article_id, items in grouped.items():
            lines.append(f"### {article_title_map.get(article_id, '未命名文章')}")
            lines.append("")
            for idx, item in enumerate(items, 1):
                quote = (item.selected_text or "").strip().replace("\n", " ")
                lines.append(f"{idx}. [{_highlight_color_label(item.color)}] {quote}")
                if item.comment_text:
                    lines.append(f"   - 批注：{item.comment_text.strip()}")
                lines.append(f"   - 创建时间：{item.created_at.astimezone().isoformat(timespec='seconds')}")
            lines.append("")

    content = "\n".join(lines).strip() + "\n"
    filename = f"{_sanitize_markdown_filename(notebook.title)}.md"
    return filename, content


async def delete_notebook(session: AsyncSession, *, user_id: str, notebook_id: str) -> None:
    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, '未找到对应的笔记本', code='notebook_not_found')
    await repo.delete_notebook(session, notebook)
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)


async def search_workspace(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
) -> list[dict]:
    return await repo.search_notebooks_and_articles(session, user_id=user_id, query=query)


async def invalidate_notebook_detail_cache(*, user_id: str, notebook_id: str) -> None:
    await delete_keys([notebook_detail_key(user_id=user_id, notebook_id=notebook_id)])


async def _title_exists(session: AsyncSession, *, user_id: str, title: str) -> bool:
    if not title:
        return False
    return await repo.get_notebook_by_title(session, user_id=user_id, title=title) is not None


def _resolve_notebook_detail_ttl(detail: dict) -> int:
    settings = get_settings()
    has_pending_articles = any(
        not article.get('contentReady') and article.get('parseStatus') != 'failed'
        for article in detail.get('articles', [])
    )
    if has_pending_articles:
        return settings.cache_ttl_notebook_detail_pending_seconds
    return settings.cache_ttl_notebook_detail_seconds


def _should_refresh_cached_notebook_detail(detail: dict) -> bool:
    if not is_object_storage_enabled():
        return False
    articles = detail.get('articles', [])
    return any(
        isinstance(article, dict)
        and isinstance(article.get('fileUrl'), str)
        and article['fileUrl'].startswith('/api/notebooks/')
        and not (
            article.get('renderMode') == 'pdf'
            or article.get('fileMime') == 'application/pdf'
        )
        for article in articles
    )
