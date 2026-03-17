"""搜索模块模型 – 编排用 Pydantic 模型 + 持久化 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.notebooks.models import Notebook


# ========== phase 1 意图识别 ==========

class SearchIntent(str, Enum):
    EXPLORE = "explore"
    COMPARE = "compare"
    ANSWER = "answer"
    LITERATURE_REVIEW = "literature_review"
    FIND_PRIMARY_SOURCE = "find_primary_source"


class CoverageFacet(str, Enum):
    NOVELTY = "novelty"
    AUTHORITATIVE = "authoritative"
    OVERVIEW = "overview"
    RECENT = "recent"
    CRITIQUE = "critique"
    IMPLEMENTATION = "implementation"
    PRIMARY = "primary"


class IntentAnalysis(BaseModel):
    """意图识别阶段的结构化输出。"""

    intent: SearchIntent = Field(description="Primary search intent")
    domain: str = Field(description="Subject domain, e.g. cs, biomed, policy, general")
    facet_weights: dict[CoverageFacet, float] = Field(
        description="Weight for each coverage facet (0.0-1.0), higher = more important",
    )
    reformulated_queries: list[str] = Field(
        description="2-6 reformulated queries targeting different facets",
        min_length=1,
        max_length=8,
    )
    time_sensitive: bool = Field(
        default=False,
        description="Whether the query demands very recent results",
    )


# ========== phase 2 工具结果 ==========

class RawSearchItem(BaseModel):
    """单条归一化后的搜索结果。"""

    title: str
    url: str
    description: str = ""
    author: str | None = None
    published_date: str | None = None
    highlights: list[str] = Field(default_factory=list)
    source_tool: str = ""


# ========== phase 3 打分排序 ==========

class ScoredItem(BaseModel):
    """模型打分后的搜索结果。"""

    title: str
    url: str
    description: str = ""
    author: str | None = None
    published_date: str | None = None
    highlights: list[str] = Field(default_factory=list)
    source_tool: str = ""
    relevance_score: float = Field(0.0, description="0-1 relevance to the query")
    authority_score: float = Field(0.0, description="0-1 source authority")
    novelty_score: float = Field(0.0, description="0-1 novelty vs existing notebook articles")
    final_score: float = Field(0.0, description="Weighted composite score")
    why_selected: str = Field("", description="Brief reason this result is valuable")


class ScoringOutput(BaseModel):
    """轻量模型批量打分结果。"""

    scored_items: list[ScoredItem]


# ========== phase 4 前端卡片 ==========

class SearchCardOut(BaseModel):
    """发给前端的最终卡片。"""

    title: str
    url: str
    source_name: str = ""
    source_type_badge: str = ""
    published_at: str | None = None
    authority_badge: str | None = None
    why_selected: str = ""
    highlights: list[str] = Field(default_factory=list)
    import_suggestion: str = "optional"
    description: str = ""
    author: str | None = None
    final_score: float = 0.0
    display_rank: int = 0


# ========== ORM models ==========


class SearchSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "search_sessions"  # type: ignore[assignment]

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_request_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    mode_label: Mapped[str] = mapped_column(String(64), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
    notebook: Mapped["Notebook"] = relationship()
    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="search_session",
        cascade="all, delete-orphan",
    )


class SearchResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "search_results"  # type: ignore[assignment]

    search_session_id: Mapped[str] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_result_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    favicon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    preview_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    search_session: Mapped[SearchSession] = relationship(back_populates="results")
