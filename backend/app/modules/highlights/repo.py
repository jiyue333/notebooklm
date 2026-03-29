from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.highlights.models import ArticleHighlight


async def list_article_highlights(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
) -> list[ArticleHighlight]:
    result = await session.execute(
        select(ArticleHighlight)
        .where(
            ArticleHighlight.user_id == user_id,
            ArticleHighlight.notebook_id == notebook_id,
            ArticleHighlight.article_id == article_id,
        )
        .order_by(desc(ArticleHighlight.created_at)),
    )
    return list(result.scalars().all())


async def list_notebook_highlights(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
) -> list[ArticleHighlight]:
    result = await session.execute(
        select(ArticleHighlight)
        .where(
            ArticleHighlight.user_id == user_id,
            ArticleHighlight.notebook_id == notebook_id,
        )
        .order_by(desc(ArticleHighlight.created_at)),
    )
    return list(result.scalars().all())


async def get_highlight(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
    highlight_id: str,
) -> ArticleHighlight | None:
    result = await session.execute(
        select(ArticleHighlight).where(
            ArticleHighlight.id == highlight_id,
            ArticleHighlight.user_id == user_id,
            ArticleHighlight.notebook_id == notebook_id,
            ArticleHighlight.article_id == article_id,
        ),
    )
    return result.scalar_one_or_none()


async def create_highlight(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
    selected_text: str,
    color: str,
    comment_text: str | None,
    start_offset: int | None,
    end_offset: int | None,
    occurrence_index: int | None,
) -> ArticleHighlight:
    highlight = ArticleHighlight(
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
        selected_text=selected_text,
        color=color,
        comment_text=comment_text,
        start_offset=start_offset,
        end_offset=end_offset,
        occurrence_index=occurrence_index,
    )
    session.add(highlight)
    await session.flush()
    return highlight


async def delete_highlight(session: AsyncSession, highlight: ArticleHighlight) -> None:
    await session.delete(highlight)

