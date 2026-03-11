from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks.models import Article, ArticleChunk


async def count_reindexable_articles(session, *, user) -> int:
    result = await session.execute(
        select(Article.id).where(
            Article.user_id == user.id,
            Article.clean_markdown.is_not(None),
        )
    )
    return len(list(result.scalars().all()))


async def clear_existing_embeddings(session, *, user, next_runtime) -> None:
    article_result = await session.execute(
        select(Article.id).where(
            Article.user_id == user.id,
            Article.clean_markdown.is_not(None),
        )
    )
    article_ids = list(article_result.scalars().all())
    if not article_ids:
        return

    await session.execute(
        update(Article)
        .where(Article.id.in_(article_ids))
        .values(
            article_vector=None,
            embedding_provider=next_runtime.provider,
            embedding_model=next_runtime.model_name,
            embedding_profile_key=next_runtime.profile_key,
            embedding_dimension=None,
            index_status="stale",
            chunk_status="stale",
        )
    )
    await session.execute(delete(ArticleChunk).where(ArticleChunk.article_id.in_(article_ids)))


async def schedule_embedding_reindex(session, *, user, runtime_config) -> list:
    result = await session.execute(
        select(Article).where(
            Article.user_id == user.id,
            Article.clean_markdown.is_not(None),
        )
    )
    articles = list(result.scalars().all())
    jobs = []
    now = datetime.now(UTC)
    for article in articles:
        if (
            article.embedding_profile_key == runtime_config.profile_key
            and article.embedding_dimension is not None
        ):
            continue
        article.index_status = "stale"
        job = await jobs_repo.create_article_reindex_job(
            session,
            article_id=article.id,
            search_session_id=article.origin_search_session_id,
            dedupe_key=f"article_reindex:{article.id}:{runtime_config.profile_key}",
            payload_json={"articleId": article.id, "reason": "embedding_config_changed"},
            created_at=now,
        )
        jobs.append(job)
    return jobs
