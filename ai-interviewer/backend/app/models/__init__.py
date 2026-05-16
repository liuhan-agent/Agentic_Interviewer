"""SQLAlchemy ORM models (trace / outcome / session)."""

from sqlalchemy.engine import Engine

from .base import Base, get_engine, get_session, init_db
from .generation_trace import GenerationTrace
from .interview_session import InterviewSession
from .outcome_record import OutcomeRecord
from .question_bank import (
    QuestionRerankUsage,
    QuestionReview,
    QuestionSeed,
    QuestionUsage,
    QuestionVariant,
)
from .strategy_memory import (
    StrategyMemory,
    StrategyMemoryStats,
    StrategyMemoryUsage,
    StrategySignal,
)
from .trace_annotation import TraceAnnotation
from .verifier_drift import VerifierDriftEvent, VerifierDriftPattern


def __getattr__(name: str) -> Engine:
    if name == "engine":
        return get_engine()
    raise AttributeError(name)

__all__ = [
    "Base",
    "engine",
    "get_engine",
    "get_session",
    "init_db",
    "GenerationTrace",
    "InterviewSession",
    "OutcomeRecord",
    "QuestionSeed",
    "QuestionRerankUsage",
    "QuestionReview",
    "QuestionUsage",
    "QuestionVariant",
    "StrategyMemory",
    "StrategyMemoryStats",
    "StrategyMemoryUsage",
    "StrategySignal",
    "TraceAnnotation",
    "VerifierDriftEvent",
    "VerifierDriftPattern",
]
