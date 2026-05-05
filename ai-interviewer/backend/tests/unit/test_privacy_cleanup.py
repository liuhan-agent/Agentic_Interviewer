from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.generation_trace import GenerationTrace
from app.models.interview_session import InterviewSession
from app.models.outcome_record import OutcomeRecord
from app.services import privacy_cleanup


@contextmanager
def _isolated_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def get_session():
        sess = testing_session_local()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    monkeypatch.setattr(privacy_cleanup, "get_db_session", get_session, raising=False)
    yield testing_session_local


def _seed(testing_session_local, *, session_id: str, age_days: int) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=age_days)
    with testing_session_local() as sess:
        sess.add(
            InterviewSession(
                session_id=session_id,
                trace_id=f"trace-{session_id}",
                candidate_name="Ada",
                job_title="Backend",
                job_level="senior",
                mode="mixed",
                status="completed",
                created_at=old,
                updated_at=old,
            )
        )
        sess.add(
            GenerationTrace(
                trace_id=f"trace-{session_id}",
                session_id=session_id,
                turn_idx=0,
                node="ask_question",
                created_at=old,
            )
        )
        sess.add(
            OutcomeRecord(
                session_id=session_id,
                outcome="hired",
                collected_at=old,
            )
        )
        sess.commit()


def _counts(testing_session_local) -> tuple[int, int, int]:
    with testing_session_local() as sess:
        return (
            sess.query(InterviewSession).count(),
            sess.query(GenerationTrace).count(),
            sess.query(OutcomeRecord).count(),
        )


def test_cleanup_expired_data_dry_run_keeps_rows(monkeypatch) -> None:
    with _isolated_db(monkeypatch) as db:
        _seed(db, session_id="sess-old", age_days=45)
        _seed(db, session_id="sess-new", age_days=1)

        report = privacy_cleanup.cleanup_expired_data(dry_run=True)

        assert report["dry_run"] is True
        assert report["sessions_deleted"] == 1
        assert report["traces_deleted"] == 1
        assert report["outcomes_deleted"] == 0
        assert _counts(db) == (2, 2, 2)


def test_cleanup_expired_data_apply_deletes_expired_rows(monkeypatch) -> None:
    with _isolated_db(monkeypatch) as db:
        _seed(db, session_id="sess-old", age_days=45)
        _seed(db, session_id="sess-new", age_days=1)

        report = privacy_cleanup.cleanup_expired_data(dry_run=False)

        assert report["dry_run"] is False
        assert report["sessions_deleted"] == 1
        assert report["traces_deleted"] == 1
        assert report["outcomes_deleted"] == 0
        assert _counts(db) == (1, 1, 2)


def test_cleanup_expired_data_respects_batch_size(monkeypatch) -> None:
    with _isolated_db(monkeypatch) as db:
        _seed(db, session_id="sess-old-1", age_days=45)
        _seed(db, session_id="sess-old-2", age_days=45)

        report = privacy_cleanup.cleanup_expired_data(dry_run=False, batch_size=1)

        assert report["sessions_deleted"] == 1
        assert report["traces_deleted"] == 1
        assert _counts(db) == (1, 1, 2)
