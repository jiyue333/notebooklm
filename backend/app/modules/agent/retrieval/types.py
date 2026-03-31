"""检索模块数据类型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RetrievalResult:
    chunk_id: str
    article_id: str
    article_title: str
    raw_text: str
    contextualized_text: str
    score: float
    locator_text: str = ""
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
    chunk_index: int | None = None
    section_path: str | None = None
    heading_title: str | None = None

    def to_evidence_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "article_id": self.article_id,
            "article_title": self.article_title,
            "raw_text": self.raw_text,
            "evidence_text": self.contextualized_text or self.raw_text,
            "locator_text": self.locator_text or self.raw_text,
            "score": round(self.score, 4),
            "section_path": self.section_path,
            "heading_title": self.heading_title,
        }


@dataclass(slots=True)
class ArticleRecallResult:
    article_id: str
    title: str
    summary_text: str | None = None
    score: float = 0.0


@dataclass(slots=True)
class HybridRetrievalRequest:
    query: str
    scope_article_ids: list[str] = field(default_factory=list)
    top_k: int = 10
    dense_top_k: int | None = None
    sparse_top_k: int | None = None
    dense_weight: float = 0.7
    sparse_weight: float = 0.3
    use_rerank: bool = True
    rerank_top_n: int | None = None
    user: object | None = None
