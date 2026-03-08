from __future__ import annotations

NOTEBOOK_ASYNC_TOPIC = "notebook_async"

TAG_SEARCH_DEEP = "search.deep"
TAG_ARTICLE_INGEST = "article.ingest"
TAG_ARTICLE_REINDEX = "article.reindex"
TAG_MAINTENANCE_CLEANUP = "maintenance.cleanup"

ALL_SUPPORTED_TAGS = {
    TAG_SEARCH_DEEP,
    TAG_ARTICLE_INGEST,
    TAG_ARTICLE_REINDEX,
    TAG_MAINTENANCE_CLEANUP,
}
