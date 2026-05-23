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
from .resume_anchor_cache import ResumeAnchorCacheChunk
from .resume_parse_artifact import ResumeParseArtifact
from .session_anchor import SessionAnchorChunk
from .skill_playbook import SkillPlaybookCard
from .strategy_learning import BanditPosterior, InterviewTurn
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
    "ResumeAnchorCacheChunk",
    "ResumeParseArtifact",
    "SessionAnchorChunk",
    "SkillPlaybookCard",
    "BanditPosterior",
    "InterviewTurn",
    "StrategyMemory",
    "StrategyMemoryStats",
    "StrategyMemoryUsage",
    "StrategySignal",
    "TraceAnnotation",
    "VerifierDriftEvent",
    "VerifierDriftPattern",
]
