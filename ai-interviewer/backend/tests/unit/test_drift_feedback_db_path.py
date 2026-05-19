"""Tests for the ``drift_feedback_source`` switch in ``prompt_feedback``.

PR5 of the drift-feedback persistence track: ``build_evaluator_drift_negatives``
and ``build_generator_avoid_patterns`` historically read the
in-process :class:`VerifierDriftMonitor` snapshot. PR5 lets the same
two helpers read the persisted ``verifier_drift_patterns`` table
instead, plus a ``db_shadow`` middle gear that lets us validate the DB
path without changing the visible prompt.

Pinned contract:

1. ``source="monitor"``: identical to pre-PR5 behaviour.
2. ``source="db"``: read from ``verifier_drift_patterns`` filtered to
   the requested ``dimension``, ``failure_categories``, ``top_n`` and
   ``min_support``.
3. ``source="db_shadow"``: byte-identical to ``"monitor"`` for the
   returned markdown; the DB read is purely additive (no visible
   prompt diff).
4. ``failure_categories=None``: fall back to the
   ``"__global__"`` rollup.
5. When ``source`` is omitted, fall through to
   ``Settings.drift_feedback_source``.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.verifier_drift import VerifierDriftPattern


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _seed_db_pattern(
    sess,
    *,
    id_: str,
    dimension: str = "system_design",
    check_name: str = "Mentions concrete failure modes",
    failure_category: str = "__global__",
    uses: int = 5,
    sample_evidence: list[str] | None = None,
    reasons_sample: list[str] | None = None,
) -> None:
    now = datetime.now(UTC)
    sess.add(
        VerifierDriftPattern(
            id=id_,
            dimension=dimension,
            check_name=check_name,
            failure_category=failure_category,
            uses=uses,
            overruled_count=uses,
            overrule_rate=1.0,
            sample_evidence=list(sample_evidence or ["we used Redis"]),
            reasons_sample=list(
                reasons_sample or ["evidence is generic boilerplate"]
            ),
            first_seen_at=now,
            last_seen_at=now,
        )
    )


def _install_settings(monkeypatch, *, source: str) -> None:
    from app.ml.drift import prompt_feedback as mod

    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: SimpleNamespace(drift_feedback_source=source),
    )


def _install_db_session(monkeypatch, Session) -> None:
    from app.ml.drift import prompt_feedback as mod

    @contextmanager
    def get_session():
        with Session() as sess:
            yield sess
            sess.commit()

    monkeypatch.setattr(mod, "get_session", get_session)


def _install_monitor_snapshot(monkeypatch, snapshot: dict[str, Any]) -> None:
    from app.ml.drift import prompt_feedback as mod

    class _Monitor:
        def snapshot(self) -> dict[str, Any]:
            return snapshot

    monkeypatch.setattr(
        mod,
        "get_verifier_drift_monitor",
        lambda: _Monitor(),
    )


def test_monitor_source_falls_back_to_legacy_snapshot(monkeypatch) -> None:
    from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives

    snapshot = {
        "overruled_patterns": [
            {
                "dimension": "system_design",
                "check": "Mentions concrete failure modes",
                "count": 3,
                "sample_evidence": ["we used Redis"],
                "reasons_sample": ["generic boilerplate"],
            }
        ]
    }
    _install_monitor_snapshot(monkeypatch, snapshot)
    _install_settings(monkeypatch, source="monitor")

    rendered = build_evaluator_drift_negatives(dimension="system_design")

    assert "Prior Evaluator Drift" in rendered
    assert "Mentions concrete failure modes" in rendered


def test_db_source_reads_verifier_drift_patterns(monkeypatch) -> None:
    from app.ml.drift.prompt_feedback import build_generator_avoid_patterns

    Session = _session_factory()
    with Session() as sess:
        _seed_db_pattern(
            sess,
            id_="pat-1",
            uses=5,
            sample_evidence=["scale to millions"],
            reasons_sample=["evidence is too vague"],
        )
        sess.commit()

    _install_db_session(monkeypatch, Session)
    _install_settings(monkeypatch, source="db")
    # Monitor stays unused under source=db; install a poison snapshot
    # to make any accidental fallback obvious.
    _install_monitor_snapshot(
        monkeypatch,
        {
            "overruled_patterns": [
                {
                    "dimension": "system_design",
                    "check": "POISON",
                    "count": 99,
                    "sample_evidence": ["poison"],
                }
            ]
        },
    )

    rendered = build_generator_avoid_patterns(dimension="system_design")

    assert "POISON" not in rendered
    assert "Mentions concrete failure modes" in rendered
    assert "scale to millions" in rendered


def test_db_source_respects_min_support_threshold(monkeypatch) -> None:
    from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives

    Session = _session_factory()
    with Session() as sess:
        _seed_db_pattern(sess, id_="pat-low", uses=1)
        sess.commit()

    _install_db_session(monkeypatch, Session)
    _install_settings(monkeypatch, source="db")
    _install_monitor_snapshot(monkeypatch, {"overruled_patterns": []})

    rendered = build_evaluator_drift_negatives(
        dimension="system_design", min_support=3
    )
    assert rendered == ""


def test_db_source_filters_by_failure_categories(monkeypatch) -> None:
    """When ``failure_categories`` is provided, only rows whose
    ``failure_category`` is in that set are surfaced."""
    from app.ml.drift.prompt_feedback import build_generator_avoid_patterns

    Session = _session_factory()
    with Session() as sess:
        _seed_db_pattern(
            sess,
            id_="pat-missing-metrics",
            failure_category="missing_metrics",
            sample_evidence=["scale to millions"],
        )
        _seed_db_pattern(
            sess,
            id_="pat-weak-debug",
            failure_category="weak_debugging",
            sample_evidence=["debug-poison"],
        )
        _seed_db_pattern(
            sess,
            id_="pat-global",
            failure_category="__global__",
            sample_evidence=["global-poison"],
        )
        sess.commit()

    _install_db_session(monkeypatch, Session)
    _install_settings(monkeypatch, source="db")
    _install_monitor_snapshot(monkeypatch, {"overruled_patterns": []})

    rendered = build_generator_avoid_patterns(
        dimension="system_design",
        failure_categories=["missing_metrics"],
    )

    assert "scale to millions" in rendered
    assert "debug-poison" not in rendered
    assert "global-poison" not in rendered


def test_db_source_falls_back_to_global_when_no_failure_categories(monkeypatch) -> None:
    """Without ``failure_categories``, we read the ``__global__`` rollup
    so the helper keeps working in the legacy call sites that do not
    yet plumb a category through."""
    from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives

    Session = _session_factory()
    with Session() as sess:
        _seed_db_pattern(
            sess,
            id_="pat-cat",
            failure_category="missing_metrics",
            sample_evidence=["should-be-ignored"],
        )
        _seed_db_pattern(
            sess,
            id_="pat-global",
            failure_category="__global__",
            sample_evidence=["use-this-one"],
        )
        sess.commit()

    _install_db_session(monkeypatch, Session)
    _install_settings(monkeypatch, source="db")
    _install_monitor_snapshot(monkeypatch, {"overruled_patterns": []})

    rendered = build_evaluator_drift_negatives(dimension="system_design")
    assert "use-this-one" in rendered
    assert "should-be-ignored" not in rendered


def test_db_shadow_returns_monitor_output(monkeypatch) -> None:
    """``db_shadow`` must NOT change the markdown the prompt sees — it
    still returns whatever the monitor would have returned. The DB path
    is exercised purely as a side observation in PR6 admin / future
    trace work."""
    from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives

    Session = _session_factory()
    with Session() as sess:
        _seed_db_pattern(
            sess,
            id_="pat-shadow",
            sample_evidence=["db-only"],
        )
        sess.commit()

    _install_db_session(monkeypatch, Session)
    _install_settings(monkeypatch, source="db_shadow")
    _install_monitor_snapshot(
        monkeypatch,
        {
            "overruled_patterns": [
                {
                    "dimension": "system_design",
                    "check": "Mentions concrete failure modes",
                    "count": 3,
                    "sample_evidence": ["monitor-only"],
                    "reasons_sample": ["from monitor"],
                }
            ]
        },
    )

    rendered = build_evaluator_drift_negatives(dimension="system_design")
    assert "monitor-only" in rendered
    assert "db-only" not in rendered


def test_db_shadow_logs_diff_without_changing_output(monkeypatch, caplog) -> None:
    """``db_shadow`` must additionally emit a structured ``log.info`` line
    showing both source key sets so operators can audit DB vs monitor
    parity before flipping ``source`` to ``"db"``. The rendered prompt
    is still the monitor output - logging is purely a side observation.
    """
    import logging

    from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives

    Session = _session_factory()
    with Session() as sess:
        _seed_db_pattern(
            sess,
            id_="pat-db",
            dimension="system_design",
            check_name="Mentions concrete failure modes",
            sample_evidence=["db-side evidence"],
        )
        sess.commit()

    _install_db_session(monkeypatch, Session)
    _install_settings(monkeypatch, source="db_shadow")
    _install_monitor_snapshot(
        monkeypatch,
        {
            "overruled_patterns": [
                {
                    "dimension": "system_design",
                    "check": "Triages a real incident",
                    "count": 3,
                    "sample_evidence": ["monitor-side evidence"],
                }
            ]
        },
    )

    with caplog.at_level(logging.INFO, logger="app.ml.drift.prompt_feedback"):
        rendered = build_evaluator_drift_negatives(dimension="system_design")

    assert "monitor-side evidence" in rendered
    assert "db-side evidence" not in rendered

    diff_records = [
        record for record in caplog.records
        if "drift_feedback shadow diff" in record.getMessage()
    ]
    assert diff_records, "expected at least one shadow-diff log line"

    diff_message = diff_records[0].getMessage()
    assert "monitor=1" in diff_message
    assert "db=1" in diff_message
    assert "Triages a real incident" in diff_message
    assert "Mentions concrete failure modes" in diff_message


def test_explicit_source_argument_overrides_settings(monkeypatch) -> None:
    """When a caller passes ``source`` explicitly, that wins regardless
    of the settings default."""
    from app.ml.drift.prompt_feedback import build_evaluator_drift_negatives

    Session = _session_factory()
    with Session() as sess:
        _seed_db_pattern(
            sess,
            id_="pat-explicit",
            sample_evidence=["db-wins"],
        )
        sess.commit()

    _install_db_session(monkeypatch, Session)
    _install_settings(monkeypatch, source="monitor")
    _install_monitor_snapshot(
        monkeypatch,
        {
            "overruled_patterns": [
                {
                    "dimension": "system_design",
                    "check": "Mentions concrete failure modes",
                    "count": 3,
                    "sample_evidence": ["monitor-loses"],
                }
            ]
        },
    )

    rendered = build_evaluator_drift_negatives(
        dimension="system_design",
        source="db",
    )
    assert "db-wins" in rendered
    assert "monitor-loses" not in rendered
