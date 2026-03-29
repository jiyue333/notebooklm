from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Computed, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.infra.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.notes.models import Note

class Notebook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notebooks"  # type: ignore[assignment]
    __table_args__ = {"comment": "笔记本表"}

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户 ID",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="笔记本标题")
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="笔记本图标")
    color: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="笔记本主题色")
    tags_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True, comment="笔记本标签 JSON")
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="最近打开时间")

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
    __table_args__ = {"comment": "文章与来源表"}

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户 ID",
    )
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属笔记本 ID",
    )
    input_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="来源输入类型")
    origin_search_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="SET NULL"),
        nullable=True,
        comment="来源搜索会话 ID",
    )
    origin_search_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_results.id", ondelete="SET NULL"),
        nullable=True,
        comment="来源搜索结果 ID",
    )
    rss_feed_id: Mapped[str | None] = mapped_column(
        ForeignKey("rss_feeds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="RSS 订阅源 ID",
    )
    rss_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True, comment="Miniflux Entry ID")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始来源链接")
    normalized_url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="规范化来源链接")
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="去重键")
    source_title_raw: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原始来源标题")
    raw_text_input: Mapped[str | None] = mapped_column(Text, nullable=True, comment="手动粘贴的原始文本")
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True, comment="上传文件名")
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="上传文件扩展名")
    file_mime: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="上传文件 MIME")
    file_size: Mapped[int | None] = mapped_column(nullable=True, comment="上传文件大小")
    file_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True, comment="对象存储键")
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="展示标题")
    author: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作者")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发布时间")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="内容语言")
    preview_markdown: Mapped[str | None] = mapped_column(Text, nullable=True, comment="预览 Markdown")
    clean_markdown: Mapped[str | None] = mapped_column(Text, nullable=True, comment="清洗后的正文 Markdown")
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True, comment="remark 渲染的 HTML")
    mdast_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="mdast AST 树")
    toc_json: Mapped[list | None] = mapped_column(JSONB, nullable=True, comment="目录结构 JSON")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="正文内容哈希")
    tika_mime: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="Tika 检测的 MIME 类型")
    reading_time_minutes: Mapped[int | None] = mapped_column(nullable=True, comment="预估阅读时间(分钟)")
    parser_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="采用的解析器")
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, comment="解析状态")
    parse_error_tag: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="解析错误标签")
    parse_error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析错误信息")
    parse_quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True, comment="解析质量评分")
    article_retrieval_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="文章级检索文本")
    article_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('simple', coalesce(article_retrieval_text, '')), 'B')",
            persisted=True,
        ),
        nullable=True,
        comment="文章全文检索向量",
    )
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="向量化服务提供方")
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="向量模型名称")
    embedding_profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment="向量配置标识")
    embedding_dimension: Mapped[int | None] = mapped_column(nullable=True, comment="向量维度")
    article_vector: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True, comment="文章级向量")
    block_graph_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="块级结构图谱 JSON")
    quality_profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="质量画像 JSON")
    chunk_status: Mapped[str] = mapped_column(String(16), nullable=False, comment="分块状态")
    index_status: Mapped[str] = mapped_column(String(16), nullable=False, comment="索引状态")
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="入库完成时间")

    notebook: Mapped[Notebook] = relationship(back_populates="articles")
    chunks: Mapped[list["ArticleChunk"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
    )


class ArticleChunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "article_chunks"  # type: ignore[assignment]
    __table_args__ = {"comment": "文章分块表"}

    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属文章 ID",
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False, comment="分块序号")
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True, comment="所属章节路径")
    heading_title: Mapped[str | None] = mapped_column(Text, nullable=True, comment="所属标题")
    token_count: Mapped[int] = mapped_column(nullable=False, comment="Token 数量")
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False, comment="分块文本")
    contextualized_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="上下文增强文本")
    chunk_vector: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True, comment="分块向量")
    chunk_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(contextualized_text, chunk_text))",
            persisted=True,
        ),
        nullable=True,
        comment="分块全文检索向量",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")

    article: Mapped[Article] = relationship(back_populates="chunks")
