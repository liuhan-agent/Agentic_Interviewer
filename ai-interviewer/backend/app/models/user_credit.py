"""User interview credit balance and append-only ledger."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserCreditAccount(Base):
    __tablename__ = "user_credit_accounts"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        primary_key=True,
    )
    balance: Mapped[int] = mapped_column(Integer, default=0)
    free_grant_version: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class UserCreditLedger(Base):
    __tablename__ = "user_credit_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    external_ref: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(String(300))
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON)
    balance_after: Mapped[int] = mapped_column(Integer)
    admin_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
