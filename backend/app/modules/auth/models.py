from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.notebooks.models import Notebook


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"  # type: ignore[assignment]
    __table_args__ = {"comment": "用户表"}

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="用户名")
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="登录邮箱")
    password_hash: Mapped[str] = mapped_column(Text, nullable=False, comment="密码哈希")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="头像链接")
    settings_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="用户设置 JSON")

    llm_api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True, comment="大模型 API Key 密文")
    llm_api_key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True, comment="大模型 API Key 后四位")
    llm_api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="大模型 API Key 更新时间")

    exa_api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Exa API Key 密文")
    exa_api_key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True, comment="Exa API Key 后四位")
    exa_api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="Exa API Key 更新时间")

    embedding_api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Embedding API Key 密文")
    embedding_api_key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True, comment="Embedding API Key 后四位")
    embedding_api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="Embedding API Key 更新时间")

    tokens: Mapped[list["AuthToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    notebooks: Mapped[list["Notebook"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class AuthToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_tokens"  # type: ignore[assignment]
    __table_args__ = {"comment": "登录令牌表"}

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户 ID",
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="令牌哈希")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="过期时间")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")

    user: Mapped[User] = relationship(back_populates="tokens")
