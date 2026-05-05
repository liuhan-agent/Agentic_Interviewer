"""SQLAlchemy ORM models (trace / outcome / session)."""

from sqlalchemy.engine import Engine

from .base import Base, get_engine, get_session, init_db
from .generation_trace import GenerationTrace
from .interview_session import InterviewSession
from .outcome_record import OutcomeRecord
from .trace_annotation import TraceAnnotation


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
    "TraceAnnotation",
]
