"""Trace table - one row per node execution we care about."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GenerationTrace(Base):
    """Single source of truth for RL back-filling and trainset export.

    We deliberately flatten the most-queried fields out of the full
    state snapshot (turn, dimension, action, score) so that the
    outcome bridge and trainset builder can write simple SQL joins
    without parsing JSON on every row.
    """

    __tablename__ = "generation_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    turn_idx: Mapped[int] = mapped_column(Integer, index=True)
    node: Mapped[str] = mapped_column(String(64), index=True)

    dimension: Mapped[str | None] = mapped_column(String(64), index=True)
    action_id: Mapped[str | None] = mapped_column(String(64), index=True)
    policy_id: Mapped[str | None] = mapped_column(String(128))
    context_key: Mapped[str | None] = mapped_column(String(128), index=True)
    policy_context_keys: Mapped[list | None] = mapped_column(JSON)

    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column()
    immediate_reward: Mapped[float | None] = mapped_column(Float)
    delayed_reward: Mapped[float | None] = mapped_column(Float)
    # ``applied_to_bandit`` is stamped True only after the *delayed*
    # reward has been fused via ``outcome_reward_bridge``.  It was
    # originally the sole signal for ``rehydrate_from_db`` and caused
    # immediate-reward history to be dropped on restart.
    applied_to_bandit: Mapped[bool] = mapped_column(default=False, index=True)
    # ``immediate_reward_applied`` separately tracks whether the
    # evaluator-time reward has already been fused into the bandit.
    # Rehydrate replays rows where this flag is True so the posterior
    # survives a restart even if no outcome has arrived yet.
    immediate_reward_applied: Mapped[bool] = mapped_column(
        default=False, index=True
    )

    state_snapshot: Mapped[dict | None] = mapped_column(JSON)
    question: Mapped[str | None] = mapped_column(String(2048))
    answer: Mapped[str | None] = mapped_column(Text)
    evaluation: Mapped[dict | None] = mapped_column(JSON)

    # LangSmith run-tree root id for this node execution (when tracing
    # is enabled). Serves as the foreign key between our local trace
    # table and the remote LangSmith project so ops can click through
    # from an anomalous reward row to the full prompt/response tree.
    # Nullable + indexed because:
    # - ``langsmith_tracing=false`` (the default) leaves this NULL;
    # - the column is frequently looked up when replaying an
    #   individual session in the LangSmith UI.
    langsmith_run_id: Mapped[str | None] = mapped_column(String(64), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
