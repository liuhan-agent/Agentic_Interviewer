"""SQLAlchemy ORM models (trace / outcome / session)."""

from sqlalchemy.engine import Engine

from .base import Base, get_engine, get_session, init_db
from .generation_trace import GenerationTrace
from .interview_session import InterviewSession
from .outcome_record import OutcomeRecord
from .question_bank import (
    QuestionRewardRollout,
    QuestionRerankUsage,
    QuestionReview,
    QuestionSeed,
    QuestionUsage,
    QuestionUsageStats,
    QuestionVariant,
)
from .resume_anchor_cache import ResumeAnchorCacheChunk
from .resume_parse_artifact import ResumeParseArtifact
from .session_anchor import SessionAnchorChunk
from .skill_playbook import (
    SkillPlaybookCard,
    SkillRewardRollout,
    SkillUsage,
    SkillUsageStats,
)
from .strategy_learning import BanditPosterior, InterviewTurn
from .strategy_memory import (
    StrategyMemory,
    StrategyMemoryStats,
    StrategyMemoryUsage,
    StrategyRewardRollout,
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
    "QuestionRewardRollout",
    "QuestionRerankUsage",
    "QuestionReview",
    "QuestionUsage",
    "QuestionUsageStats",
    "QuestionVariant",
    "ResumeAnchorCacheChunk",
    "ResumeParseArtifact",
    "SessionAnchorChunk",
    "SkillPlaybookCard",
    "SkillRewardRollout",
    "SkillUsage",
    "SkillUsageStats",
    "BanditPosterior",
    "InterviewTurn",
    "StrategyMemory",
    "StrategyMemoryStats",
    "StrategyMemoryUsage",
    "StrategyRewardRollout",
    "StrategySignal",
    "TraceAnnotation",
    "VerifierDriftEvent",
    "VerifierDriftPattern",
]
