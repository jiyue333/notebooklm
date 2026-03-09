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

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    llm_api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_api_key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    llm_api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exa_api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    exa_api_key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    exa_api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    embedding_api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_api_key_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    embedding_api_key_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="tokens")
