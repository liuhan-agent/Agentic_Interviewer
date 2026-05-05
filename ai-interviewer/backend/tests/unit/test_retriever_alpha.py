"""Hybrid RAG alpha resolution (P3 #6).

Until this PR, ``_blend`` was hardcoded at ``alpha=0.6`` and
``retrieve_for_question`` had no way to override it. Now the value
flows through a four-step resolver:

    caller > InterviewDirection.retrieval_alpha > settings default > 0.6

These tests exercise every step and the [0, 1] clamp so an out-of-range
JSON value can never silently regress retrieval quality.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.engine.rag import retriever as retriever_mod
from app.engine.rag.retriever import (
    _HYBRID_ALPHA_HARD_DEFAULT,
    _clamp_alpha,
    _resolve_hybrid_alpha,
)

# ---------------------------------------------------------------------------
# _clamp_alpha
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.0, 0.0),
        (0.5, 0.5),
        (1.0, 1.0),
        (-0.1, 0.0),
        (-100.0, 0.0),
        (1.4, 1.0),
        (99.0, 1.0),
    ],
)
def test_clamp_alpha_keeps_value_in_unit_interval(raw: float, expected: float) -> None:
    assert _clamp_alpha(raw) == expected


# ---------------------------------------------------------------------------
# _resolve_hybrid_alpha — precedence
# ---------------------------------------------------------------------------


def _stub_settings(default: float | None) -> Any:
    if default is None:
        return SimpleNamespace()
    return SimpleNamespace(retrieval_alpha_default=default)


def test_resolve_explicit_override_wins() -> None:
    """Caller-supplied alpha beats every other source."""
    out = _resolve_hybrid_alpha(
        explicit=0.8,
        direction_alpha=0.3,
        settings=_stub_settings(0.4),
    )
    assert out == 0.8


def test_resolve_direction_override_wins_when_no_explicit() -> None:
    out = _resolve_hybrid_alpha(
        explicit=None,
        direction_alpha=0.3,
        settings=_stub_settings(0.9),
    )
    assert out == 0.3


def test_resolve_falls_back_to_settings_default() -> None:
    out = _resolve_hybrid_alpha(
        explicit=None,
        direction_alpha=None,
        settings=_stub_settings(0.42),
    )
    assert out == 0.42


def test_resolve_falls_back_to_hard_default_when_settings_missing_attr() -> None:
    out = _resolve_hybrid_alpha(
        explicit=None,
        direction_alpha=None,
        settings=_stub_settings(None),
    )
    assert out == _HYBRID_ALPHA_HARD_DEFAULT


def test_resolve_clamps_out_of_range_explicit_value() -> None:
    out = _resolve_hybrid_alpha(
        explicit=2.5,
        direction_alpha=None,
        settings=_stub_settings(0.5),
    )
    assert out == 1.0


def test_resolve_clamps_out_of_range_direction_alpha() -> None:
    out = _resolve_hybrid_alpha(
        explicit=None,
        direction_alpha=-0.4,
        settings=_stub_settings(0.5),
    )
    assert out == 0.0


# ---------------------------------------------------------------------------
# retrieve_for_question — alpha plumbing through to _blend
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal store that returns a deterministic 3-doc top-k.

    The blending behaviour depends only on relative score order, so the
    raw score values are arbitrary as long as they're distinct enough to
    let the alpha shift change the final ranking visibly.
    """

    def __init__(self, docs: list[retriever_mod.RetrievedDoc]) -> None:
        self._docs = docs

    def similarity_search(self, query: str, k: int):  # noqa: ARG002
        return list(self._docs)


def _docs() -> list[retriever_mod.RetrievedDoc]:
    return [
        retriever_mod.RetrievedDoc(
            text="redis java spring transaction isolation",
            metadata={"source": "kb"},
            score=0.95,
        ),
        retriever_mod.RetrievedDoc(
            text="react javascript hooks render",
            metadata={"source": "kb"},
            score=0.50,
        ),
        retriever_mod.RetrievedDoc(
            text="machine learning python pytorch experiment",
            metadata={"source": "kb"},
            score=0.20,
        ),
    ]


@pytest.fixture()
def patched_retriever(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture the resolved alpha that ``_blend`` actually receives."""
    captured: dict[str, Any] = {}

    real_blend = retriever_mod._blend

    def spy_blend(
        base: list[retriever_mod.RetrievedDoc],
        bm25_scores: list[float],
        *,
        alpha: float = 0.6,
    ) -> list[retriever_mod.RetrievedDoc]:
        captured["alpha"] = alpha
        return real_blend(base, bm25_scores, alpha=alpha)

    monkeypatch.setattr(retriever_mod, "_blend", spy_blend)
    monkeypatch.setattr(retriever_mod, "get_vectorstore", lambda: _FakeStore(_docs()))
    return captured


def test_retrieve_for_question_uses_settings_default_when_no_overrides(
    patched_retriever: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No explicit alpha + no direction_alpha → settings default."""
    monkeypatch.setattr(
        retriever_mod,
        "_resolve_hybrid_alpha",
        lambda *, explicit, direction_alpha, settings: _resolve_hybrid_alpha(
            explicit=explicit,
            direction_alpha=direction_alpha,
            settings=_stub_settings(0.42),
        ),
    )
    retriever_mod.retrieve_for_question(
        job_spec={"title": "Java Backend Engineer", "required_skills": ["redis"]},
        dimension="system_design",
        mode="hybrid",
    )
    assert patched_retriever["alpha"] == 0.42


def test_retrieve_for_question_caller_alpha_wins(
    patched_retriever: dict[str, Any],
) -> None:
    retriever_mod.retrieve_for_question(
        job_spec={"title": "Java Backend Engineer", "required_skills": ["redis"]},
        dimension="system_design",
        mode="hybrid",
        alpha=0.85,
        direction_alpha=0.3,
    )
    assert patched_retriever["alpha"] == 0.85


def test_retrieve_for_question_direction_alpha_used_when_no_explicit(
    patched_retriever: dict[str, Any],
) -> None:
    retriever_mod.retrieve_for_question(
        job_spec={"title": "Java Backend Engineer", "required_skills": ["redis"]},
        dimension="system_design",
        mode="hybrid",
        direction_alpha=0.25,
    )
    assert patched_retriever["alpha"] == 0.25


def test_retrieve_for_question_vector_mode_does_not_call_blend(
    patched_retriever: dict[str, Any],
) -> None:
    """In vector-only mode the blend path is skipped entirely; alpha is
    irrelevant. The spy must remain untouched."""
    retriever_mod.retrieve_for_question(
        job_spec={"title": "Java Backend Engineer", "required_skills": ["redis"]},
        dimension="system_design",
        mode="vector",
        alpha=0.85,
    )
    assert "alpha" not in patched_retriever


def test_retrieve_for_question_clamps_out_of_range_caller_alpha(
    patched_retriever: dict[str, Any],
) -> None:
    retriever_mod.retrieve_for_question(
        job_spec={"title": "Java Backend Engineer", "required_skills": ["redis"]},
        dimension="system_design",
        mode="hybrid",
        alpha=99.0,
    )
    assert patched_retriever["alpha"] == 1.0


# ---------------------------------------------------------------------------
# job_directions.py: retrieval.alpha parsing
# ---------------------------------------------------------------------------


def test_parse_optional_alpha_handles_missing_block() -> None:
    from app.services.job_directions import _parse_optional_alpha

    assert _parse_optional_alpha({}) is None
    assert _parse_optional_alpha({"retrieval": None}) is None
    assert _parse_optional_alpha({"retrieval": {}}) is None


def test_parse_optional_alpha_returns_float() -> None:
    from app.services.job_directions import _parse_optional_alpha

    assert _parse_optional_alpha({"retrieval": {"alpha": 0.4}}) == 0.4
    assert _parse_optional_alpha({"retrieval": {"alpha": "0.7"}}) == 0.7


def test_parse_optional_alpha_returns_none_for_invalid_value() -> None:
    from app.services.job_directions import _parse_optional_alpha

    assert _parse_optional_alpha({"retrieval": {"alpha": "not-a-number"}}) is None
    assert _parse_optional_alpha({"retrieval": {"alpha": None}}) is None


def test_loaded_directions_pick_up_retrieval_alpha_from_json() -> None:
    """The shipped JSON must populate ``retrieval_alpha`` for the
    three sample directions, leaving the rest at ``None``."""
    from app.services.job_directions import (
        _load_directions,
        get_interview_direction,
    )

    _load_directions.cache_clear()  # fresh read of the on-disk JSON
    java = get_interview_direction("java_backend")
    frontend = get_interview_direction("frontend")
    ai_algo = get_interview_direction("ai_algorithm")
    sre = get_interview_direction("sre")

    assert java.retrieval_alpha == 0.5
    assert frontend.retrieval_alpha == 0.55
    assert ai_algo.retrieval_alpha == 0.7
    # Directions that did not opt in stay at None — backward-compat.
    assert sre.retrieval_alpha is None
