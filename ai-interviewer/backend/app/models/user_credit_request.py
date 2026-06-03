"""User-submitted requests for additional interview credits."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

CREDIT_REQUEST_STATUS_PENDING = "pending"
CREDIT_REQUEST_STATUS_APPROVED = "approved"
CREDIT_REQUEST_STATUS_REJECTED = "rejected"


class UserCreditRequest(Base):
    __tablename__ = "user_credit_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    requested_amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20),
        default=CREDIT_REQUEST_STATUS_PENDING,
        index=True,
    )
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credit_ledger_entry_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("user_credit_ledger.id"),
        index=True,
    )
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
