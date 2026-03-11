from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Computed, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.infra.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.notes.models import Note

class Notebook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notebooks"  # type: ignore[assignment]

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)

    user: Mapped["User"] = relationship(back_populates="notebooks")
    notes: Mapped[list["Note"]] = relationship(
        back_populates="notebook",
        cascade="all, delete-orphan",
    )
    articles: Mapped[list["Article"]] = relationship(
        back_populates="notebook",
        cascade="all, delete-orphan",
    )


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"  # type: ignore[assignment]

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
    input_type: Mapped[str] = mapped_column(String(32), nullable=False)
    origin_search_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    origin_search_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_title_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int | None] = mapped_column(nullable=True)
    file_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    preview_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    clean_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    toc_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False)
    parse_error_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parse_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    article_retrieval_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('simple', coalesce(article_retrieval_text, '')), 'B')",
            persisted=True,
        ),
        nullable=True,
    )
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    embedding_dimension: Mapped[int | None] = mapped_column(nullable=True)
    article_vector: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    chunk_status: Mapped[str] = mapped_column(String(16), nullable=False)
    index_status: Mapped[str] = mapped_column(String(16), nullable=False)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notebook: Mapped[Notebook] = relationship(back_populates="articles")
    chunks: Mapped[list["ArticleChunk"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
    )


class ArticleChunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "article_chunks"  # type: ignore[assignment]

    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    heading_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_vector: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    article: Mapped[Article] = relationship(back_populates="chunks")
