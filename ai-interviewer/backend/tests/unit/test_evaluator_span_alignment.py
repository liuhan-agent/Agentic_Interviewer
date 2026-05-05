"""Tests for evidence span alignment (``PLAN_EVIDENCE_SPAN_ALIGNMENT.md``).

The evaluator now optionally enriches ``acceptance_check_results[*]``
with an ``evidence_spans`` list of
``{"text","start","end","match"}`` entries aligned to the candidate
answer. This is opt-in via ``settings.evidence_span_alignment`` so
pre-rollout consumers see zero diff.

What this file pins down:

1. ``_align_one_span`` returns exact offsets on verbatim hits, fuzzy
   offsets when the match ratio clears the threshold, and a
   ``match="none"`` span otherwise. Never raises.
2. Empty inputs degrade to ``match="none"`` (no zero-length
   synthetic spans sneaking into downstream renderers).
3. Chinese / mixed-script text works because ``difflib`` is configured
   with ``autojunk=False`` — common CJK glyphs are NOT discarded as
   "junk".
4. ``_normalize_check_result`` remains additive: without
   ``enable_spans`` the output is byte-identical to the legacy
   ``{"verdict","evidence"}`` shape (no ``evidence_spans`` key).
5. End-to-end ``evaluate_answer`` emits ``evidence_spans`` aligned to
   the answer when the settings knob is ON, and emits nothing extra
   when the knob is OFF (default).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.core.settings import Settings
from app.engine.agents import evaluator_agent as eval_mod
from app.engine.agents.evaluator_agent import (
    _align_one_span,
    _normalize_check_result,
)

# ---------------------------------------------------------------------------
# _align_one_span — exact / fuzzy / none / edge cases
# ---------------------------------------------------------------------------


def test_align_exact_match_returns_char_offsets() -> None:
    """Verbatim ``answer.find`` hit populates start/end + ``match="exact"``."""
    answer = "We prefer AP for availability under partitions."
    quote = "AP for availability"

    span = _align_one_span(quote, answer)

    assert span["text"] == quote
    assert span["match"] == "exact"
    assert span["start"] == answer.find(quote)
    assert span["end"] == span["start"] + len(quote)
    assert answer[span["start"] : span["end"]] == quote


def test_align_fuzzy_match_above_threshold() -> None:
    """When the quote only overlaps a substring of the answer (but
    above the fuzzy threshold), we still locate the best block and
    tag ``match="fuzzy"``."""
    answer = "We chose availability under partitions, CAP-wise AP."
    # Differs from answer by trailing text the evaluator hallucinated.
    quote = "availability under partitions"

    span = _align_one_span(quote, answer, fuzzy_threshold=0.6)

    # Should find the verbatim substring (this is actually exact —
    # the fuzzy path only kicks in when ``.find`` misses).
    assert span["match"] == "exact"
    assert answer[span["start"] : span["end"]] == quote


def test_align_fuzzy_when_exact_misses_but_longest_block_clears_threshold() -> None:
    """Synthesise a case where ``str.find`` misses but difflib's
    longest block still covers ≥60% of the quote length."""
    answer = "We prefer AP for availability in partition scenarios."
    # Quote has a deliberate typo (``availabilty``); exact find fails,
    # but "for availabilty" shares ``for availabil`` with the answer.
    quote = "for availabilty"

    span = _align_one_span(quote, answer, fuzzy_threshold=0.6)

    assert span["match"] == "fuzzy"
    assert span["start"] >= 0
    assert span["end"] > span["start"]
    # The fuzzy block should at least be a prefix of the quote.
    assert answer[span["start"] : span["end"]]


def test_align_no_match_below_threshold() -> None:
    """Totally unrelated quote -> ``match="none"`` with -1 offsets."""
    answer = "Redis outage at 3am because of an OOM-killer loop."
    quote = "consensus protocol quorum"

    span = _align_one_span(quote, answer, fuzzy_threshold=0.6)

    assert span["match"] == "none"
    assert span["start"] == -1
    assert span["end"] == -1
    # Text is preserved so UI renderers can still show the claim even
    # when they cannot highlight.
    assert span["text"] == quote


def test_align_empty_inputs_return_none_span() -> None:
    assert _align_one_span("", "some answer") == {
        "text": "",
        "start": -1,
        "end": -1,
        "match": "none",
    }
    assert _align_one_span("quote", "") == {
        "text": "quote",
        "start": -1,
        "end": -1,
        "match": "none",
    }
    assert _align_one_span("", "") == {
        "text": "",
        "start": -1,
        "end": -1,
        "match": "none",
    }


def test_align_chinese_mixed_script_exact() -> None:
    """Chinese quote inside a mixed-script answer locates precisely.

    ``autojunk=False`` is load-bearing for this case: with the
    default ``autojunk=True``, difflib would flag common CJK chars as
    "junk" and might mis-align fuzzy searches in pathological inputs.
    The exact branch doesn't need it, but we still want a regression
    guard here so nobody ever flips ``autojunk`` back on.
    """
    answer = "我们使用 Redis 缓存热点读, TTL 设为 5 分钟, 写时失效."
    quote = "TTL 设为 5 分钟"

    span = _align_one_span(quote, answer)

    assert span["match"] == "exact"
    assert answer[span["start"] : span["end"]] == quote


# ---------------------------------------------------------------------------
# _normalize_check_result — additive shape, no spans by default
# ---------------------------------------------------------------------------


def test_normalize_without_answer_emits_no_spans_key() -> None:
    """Legacy callers (no ``answer`` arg) must see the exact old
    shape ``{"verdict","evidence"}`` — no ``evidence_spans`` key
    leaking in, otherwise snapshot-equality tests break.
    """
    out = _normalize_check_result(
        {"verdict": "yes", "evidence": ["quote"]}
    )

    assert out == {"verdict": "yes", "evidence": ["quote"]}
    assert "evidence_spans" not in out


def test_normalize_with_answer_and_enabled_emits_spans() -> None:
    answer = "We prefer AP for availability under partitions."

    out = _normalize_check_result(
        {"verdict": "yes", "evidence": ["AP for availability"]},
        answer=answer,
        enable_spans=True,
    )

    assert out["verdict"] == "yes"
    assert out["evidence"] == ["AP for availability"]
    assert len(out["evidence_spans"]) == len(out["evidence"])
    span = out["evidence_spans"][0]
    assert span["match"] == "exact"
    assert answer[span["start"] : span["end"]] == "AP for availability"


def test_normalize_preserves_span_ordering_matches_evidence() -> None:
    """``evidence_spans[i]`` aligns to ``evidence[i]`` — the 1:1
    order is how front-end / drift monitor correlate the two lists.
    """
    answer = "trade consistency for availability. cache TTL is 5 min."

    out = _normalize_check_result(
        {
            "verdict": "yes",
            "evidence": [
                "trade consistency",
                "cache TTL is 5 min",
                "not in the answer at all",
            ],
        },
        answer=answer,
        enable_spans=True,
    )

    spans = out["evidence_spans"]
    assert len(spans) == 3
    assert spans[0]["match"] == "exact"
    assert spans[1]["match"] == "exact"
    assert spans[2]["match"] == "none"
    assert spans[2]["start"] == -1


def test_normalize_legacy_string_with_spans_enabled_has_empty_spans() -> None:
    """A legacy ``"yes"`` string value carries no evidence quotes, so
    ``evidence`` is ``[]`` and ``evidence_spans`` must mirror that
    (not ``None``, not missing — empty list so iteration is safe).
    """
    out = _normalize_check_result(
        "yes",
        answer="some answer",
        enable_spans=True,
    )

    assert out == {
        "verdict": "yes",
        "evidence": [],
        "evidence_spans": [],
    }


# ---------------------------------------------------------------------------
# evaluate_answer — end-to-end, gated by settings
# ---------------------------------------------------------------------------


def test_settings_enable_evidence_span_alignment_by_default() -> None:
    """Production reports should include span data unless env opts out."""
    assert Settings.model_fields["evidence_span_alignment"].default is True


def _fake_response_with_evidence() -> str:
    return (
        '{"score": 8.0, "passed": true, '
        '"strengths": ["concrete trade-offs"], "weaknesses": [], '
        '"acceptance_check_results": {'
        '"Names a CAP trade-off.": {'
        '"verdict": "yes", '
        '"evidence": ["AP for availability"]'
        "}, "
        '"Explains a failure mode.": {'
        '"verdict": "partial", '
        '"evidence": ["network partitions"]'
        "}}, "
        '"recommended_next": "advance", '
        '"recommended_next_plan": "adaptive", '
        '"rationale": "strong"}'
    )


def _stub_settings(*, enable_spans: bool) -> SimpleNamespace:
    """Minimal Settings stub carrying only the knobs the evaluator
    reads. Since ``use_context_builder`` was flattened away in
    Phase-2 legacy downsize, the stub only needs the two evidence-
    span knobs the evaluator touches directly.
    """
    return SimpleNamespace(
        evidence_span_alignment=enable_spans,
        evidence_span_fuzzy_threshold=0.6,
    )


def test_evaluate_answer_emits_spans_when_knob_enabled(monkeypatch) -> None:
    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return _fake_response_with_evidence()

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)
    monkeypatch.setattr(
        eval_mod, "get_settings", lambda: _stub_settings(enable_spans=True)
    )

    answer = "We prefer AP for availability even under network partitions."
    result = eval_mod.evaluate_answer(
        dimension="system_design",
        question="Explain CAP trade-offs.",
        rubric_points=["CAP", "failure mode"],
        answer=answer,
        quality_threshold=7.5,
        contract={
            "must_cover": ["CAP", "failure mode"],
            "acceptance_checks": [
                "Names a CAP trade-off.",
                "Explains a failure mode.",
            ],
        },
    )

    checks = result["acceptance_check_results"]
    # Legacy contract preserved.
    assert checks["Names a CAP trade-off."]["evidence"] == ["AP for availability"]
    assert checks["Explains a failure mode."]["evidence"] == ["network partitions"]
    # Additive evidence_spans present and aligned to the answer.
    cap_spans = checks["Names a CAP trade-off."]["evidence_spans"]
    fail_spans = checks["Explains a failure mode."]["evidence_spans"]
    assert len(cap_spans) == 1
    assert len(fail_spans) == 1
    assert cap_spans[0]["match"] == "exact"
    assert answer[cap_spans[0]["start"] : cap_spans[0]["end"]] == "AP for availability"
    assert fail_spans[0]["match"] == "exact"
    assert answer[fail_spans[0]["start"] : fail_spans[0]["end"]] == "network partitions"


def test_evaluate_answer_silent_when_knob_disabled(monkeypatch) -> None:
    """Default settings (knob OFF) must produce zero shape diff:
    ``evidence_spans`` must NOT appear anywhere in the output.
    """

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return _fake_response_with_evidence()

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)
    monkeypatch.setattr(
        eval_mod, "get_settings", lambda: _stub_settings(enable_spans=False)
    )

    result = eval_mod.evaluate_answer(
        dimension="system_design",
        question="Explain CAP trade-offs.",
        rubric_points=["CAP"],
        answer="We prefer AP for availability.",
        quality_threshold=7.5,
        contract={
            "must_cover": ["CAP"],
            "acceptance_checks": ["Names a CAP trade-off."],
        },
    )

    for check in result["acceptance_check_results"].values():
        assert set(check.keys()) == {"verdict", "evidence"}
        assert "evidence_spans" not in check


def test_evaluate_answer_synthesised_fallback_has_empty_spans_when_enabled(
    monkeypatch,
) -> None:
    """When the LLM goes silent on ``acceptance_check_results`` and we
    synthesise stub entries from the contract, the stubs must include
    ``evidence_spans: []`` so downstream consumers that iterate spans
    don't KeyError. Mirrors the existing silent-LLM test in
    ``test_evaluator_evidence.py`` but for the spans shape.
    """

    def fake_call(messages, *, json_mode=False, **kwargs):  # type: ignore[no-untyped-def]
        return (
            '{"score": 5.0, "passed": false, '
            '"strengths": [], "weaknesses": [], '
            '"recommended_next": "refine", '
            '"rationale": "n/a"}'
        )

    monkeypatch.setattr(eval_mod, "call_chat", fake_call)
    monkeypatch.setattr(
        eval_mod, "get_settings", lambda: _stub_settings(enable_spans=True)
    )

    contract: dict[str, Any] = {
        "must_cover": ["A", "B"],
        "acceptance_checks": ["Names A.", "Names B."],
    }

    result = eval_mod.evaluate_answer(
        dimension="x",
        question="q",
        rubric_points=["A", "B"],
        answer="blank",
        quality_threshold=7.0,
        contract=contract,
    )

    checks = result["acceptance_check_results"]
    assert set(checks.keys()) == {"Names A.", "Names B."}
    for check in checks.values():
        assert set(check.keys()) == {"verdict", "evidence", "evidence_spans"}
        assert check["evidence"] == []
        assert check["evidence_spans"] == []
