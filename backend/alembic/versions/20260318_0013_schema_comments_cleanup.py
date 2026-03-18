"""add schema comments and drop legacy summary_cache table

Revision ID: 20260318_0013
Revises: 20260315_0012
Create Date: 2026-03-18 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260318_0013"
down_revision = "20260315_0012"
branch_labels = None
depends_on = None


TABLE_COMMENTS = {
    "users": "用户表",
    "auth_tokens": "登录令牌表",
    "notebooks": "笔记本表",
    "notes": "笔记表",
    "search_sessions": "来源搜索会话表",
    "search_results": "搜索结果表",
    "articles": "文章与来源表",
    "article_chunks": "文章分块表",
    "jobs": "异步任务表",
    "conversations": "聊天会话表",
    "conversation_messages": "聊天消息表",
    "summary_caches": "文章摘要缓存表",
}


COLUMN_COMMENTS = {
    "users": {
        "id": "主键 ID",
        "name": "用户名",
        "email": "登录邮箱",
        "password_hash": "密码哈希",
        "avatar_url": "头像链接",
        "settings_json": "用户设置 JSON",
        "llm_api_key_ciphertext": "大模型 API Key 密文",
        "llm_api_key_last4": "大模型 API Key 后四位",
        "llm_api_key_updated_at": "大模型 API Key 更新时间",
        "exa_api_key_ciphertext": "Exa API Key 密文",
        "exa_api_key_last4": "Exa API Key 后四位",
        "exa_api_key_updated_at": "Exa API Key 更新时间",
        "embedding_api_key_ciphertext": "Embedding API Key 密文",
        "embedding_api_key_last4": "Embedding API Key 后四位",
        "embedding_api_key_updated_at": "Embedding API Key 更新时间",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    "auth_tokens": {
        "id": "主键 ID",
        "user_id": "所属用户 ID",
        "token_hash": "令牌哈希",
        "expires_at": "过期时间",
        "created_at": "创建时间",
    },
    "notebooks": {
        "id": "主键 ID",
        "user_id": "所属用户 ID",
        "title": "笔记本标题",
        "emoji": "笔记本图标",
        "color": "笔记本主题色",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    "notes": {
        "id": "主键 ID",
        "notebook_id": "所属笔记本 ID",
        "title": "笔记标题",
        "content_markdown": "Markdown 正文",
        "note_type": "笔记类型",
        "source_count": "关联来源数量",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    "search_sessions": {
        "id": "主键 ID",
        "user_id": "所属用户 ID",
        "notebook_id": "所属笔记本 ID",
        "query": "原始查询词",
        "normalized_query": "归一化查询词",
        "mode": "搜索模式",
        "execution_mode": "执行方式",
        "provider_name": "搜索提供方",
        "provider_request_json": "请求参数快照 JSON",
        "status": "会话状态",
        "mode_label": "模式展示文案",
        "result_count": "结果数量",
        "error_code": "错误代码",
        "error_message": "错误信息",
        "created_at": "创建时间",
        "completed_at": "完成时间",
        "expires_at": "过期时间",
    },
    "search_results": {
        "id": "主键 ID",
        "search_session_id": "所属搜索会话 ID",
        "provider_result_id": "提供方结果 ID",
        "raw_url": "原始链接",
        "canonical_url": "规范化链接",
        "url_hash": "链接哈希",
        "title": "结果标题",
        "description": "结果摘要",
        "author": "作者",
        "published_at": "发布时间",
        "domain": "来源域名",
        "favicon_url": "站点图标链接",
        "display_rank": "展示排序",
        "preview_markdown": "预览 Markdown",
        "raw_payload_json": "原始扩展载荷 JSON",
        "created_at": "创建时间",
    },
    "articles": {
        "id": "主键 ID",
        "user_id": "所属用户 ID",
        "notebook_id": "所属笔记本 ID",
        "input_type": "来源输入类型",
        "origin_search_session_id": "来源搜索会话 ID",
        "origin_search_result_id": "来源搜索结果 ID",
        "source_url": "原始来源链接",
        "normalized_url": "规范化来源链接",
        "dedupe_key": "去重键",
        "source_title_raw": "原始来源标题",
        "raw_text_input": "手动粘贴的原始文本",
        "file_name": "上传文件名",
        "file_ext": "上传文件扩展名",
        "file_mime": "上传文件 MIME",
        "file_size": "上传文件大小",
        "file_storage_key": "对象存储键",
        "title": "展示标题",
        "author": "作者",
        "published_at": "发布时间",
        "language": "内容语言",
        "preview_markdown": "预览 Markdown",
        "clean_markdown": "清洗后的正文 Markdown",
        "toc_json": "目录结构 JSON",
        "content_hash": "正文内容哈希",
        "parser_name": "采用的解析器",
        "parse_status": "解析状态",
        "parse_error_tag": "解析错误标签",
        "parse_error_message": "解析错误信息",
        "parse_quality_score": "解析质量评分",
        "article_retrieval_text": "文章级检索文本",
        "article_tsv": "文章全文检索向量",
        "embedding_provider": "向量化服务提供方",
        "embedding_model": "向量模型名称",
        "embedding_profile_key": "向量配置标识",
        "embedding_dimension": "向量维度",
        "article_vector": "文章级向量",
        "block_graph_json": "块级结构图谱 JSON",
        "quality_profile_json": "质量画像 JSON",
        "chunk_status": "分块状态",
        "index_status": "索引状态",
        "ingested_at": "入库完成时间",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    "article_chunks": {
        "id": "主键 ID",
        "article_id": "所属文章 ID",
        "chunk_index": "分块序号",
        "section_path": "所属章节路径",
        "heading_title": "所属标题",
        "token_count": "Token 数量",
        "chunk_text": "分块文本",
        "chunk_vector": "分块向量",
        "created_at": "创建时间",
    },
    "jobs": {
        "id": "主键 ID",
        "job_type": "任务类型",
        "article_id": "关联文章 ID",
        "search_session_id": "关联搜索会话 ID",
        "dedupe_key": "去重键",
        "payload_json": "任务载荷 JSON",
        "status": "任务状态",
        "attempts": "已尝试次数",
        "max_attempts": "最大重试次数",
        "last_error": "最近一次错误",
        "trace_id": "链路追踪 ID",
        "created_at": "创建时间",
        "available_at": "可执行时间",
        "started_at": "开始执行时间",
        "finished_at": "结束执行时间",
    },
    "conversations": {
        "id": "主键 ID",
        "user_id": "所属用户 ID",
        "notebook_id": "所属笔记本 ID",
        "current_article_id": "当前关联文章 ID",
        "title": "会话标题",
        "rolling_summary": "滚动摘要",
        "last_message_at": "最后一条消息时间",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    },
    "conversation_messages": {
        "id": "主键 ID",
        "conversation_id": "所属会话 ID",
        "article_id": "关联文章 ID",
        "role": "消息角色",
        "route": "回答路由",
        "content": "消息内容",
        "retrieval_snapshot_json": "检索快照 JSON",
        "created_at": "创建时间",
    },
    "summary_caches": {
        "id": "主键 ID",
        "article_id": "所属文章 ID",
        "content_hash": "正文内容哈希",
        "prompt_version": "提示词版本",
        "model_provider": "模型提供方",
        "model_name": "模型名称",
        "output_language": "输出语言",
        "summary_text": "摘要正文",
        "created_at": "创建时间",
    },
}


def _escape_comment(comment: str | None) -> str:
    if comment is None:
        return "NULL"
    return "'" + comment.replace("'", "''") + "'"


def _set_table_comment(table_name: str, comment: str | None) -> None:
    op.execute(f"COMMENT ON TABLE {table_name} IS {_escape_comment(comment)}")


def _set_column_comment(table_name: str, column_name: str, comment: str | None) -> None:
    op.execute(f"COMMENT ON COLUMN {table_name}.{column_name} IS {_escape_comment(comment)}")


def upgrade() -> None:
    for table_name, comment in TABLE_COMMENTS.items():
        _set_table_comment(table_name, comment)

    for table_name, columns in COLUMN_COMMENTS.items():
        for column_name, comment in columns.items():
            _set_column_comment(table_name, column_name, comment)

    op.execute("DROP TABLE IF EXISTS summary_cache CASCADE")


def downgrade() -> None:
    op.create_table(
        "summary_cache",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model_provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("output_language", sa.String(length=64), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_summary_cache")),
        sa.UniqueConstraint(
            "article_id",
            "content_hash",
            "prompt_version",
            "model_provider",
            "model_name",
            "output_language",
            name="uq_summary_cache_identity",
        ),
    )
    op.create_index(op.f("ix_summary_cache_user_id"), "summary_cache", ["user_id"], unique=False)
    op.create_index(op.f("ix_summary_cache_article_id"), "summary_cache", ["article_id"], unique=False)

    for table_name, columns in COLUMN_COMMENTS.items():
        for column_name in columns:
            _set_column_comment(table_name, column_name, None)

    for table_name in TABLE_COMMENTS:
        _set_table_comment(table_name, None)
