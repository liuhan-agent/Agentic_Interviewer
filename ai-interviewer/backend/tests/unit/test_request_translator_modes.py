"""Mode-alias handling in ``translate_request``.

The Next.js frontend historically types ``mode`` as
``"mixed" | "text" | "voice"`` (the latter two describe the client
channel, not the interview topic). Before the alias table, any
request with ``mode="text"`` or ``mode="voice"`` was silently coerced
to ``"mixed"`` but the TypeScript definition was effectively lying —
those values never survived into the graph state. The aliases now
pin down exactly how the backend reacts so the contract stays
honest.
"""
from __future__ import annotations

import re

from app.core.request_translator import translate_request


def _base_request(mode: str | None = None) -> dict[str, object]:
    req: dict[str, object] = {
        "candidate": {"name": "Alex", "resume_parsed": {"summary": "x"}},
        "job_spec": {
            "title": "Backend Engineer",
            "level": "senior",
            "required_skills": ["python"],
            "rubric_dimensions": ["technical_depth"],
        },
    }
    if mode is not None:
        req["mode"] = mode
    return req


def test_translate_request_accepts_tech_mode() -> None:
    _, _, state = translate_request(_base_request("tech"))
    assert state["mode"] == "tech"


def test_translate_request_accepts_behavioral_mode() -> None:
    _, _, state = translate_request(_base_request("behavioral"))
    assert state["mode"] == "behavioral"


def test_translate_request_text_is_aliased_to_mixed() -> None:
    """``text`` describes the client channel; it aliases to ``mixed``
    rather than getting silently dropped.
    """
    _, _, state = translate_request(_base_request("text"))
    assert state["mode"] == "mixed"


def test_translate_request_voice_is_aliased_to_mixed() -> None:
    _, _, state = translate_request(_base_request("voice"))
    assert state["mode"] == "mixed"


def test_translate_request_unknown_mode_falls_back_to_mixed() -> None:
    """Anything not in ``_ALLOWED_MODES`` or ``_MODE_ALIASES`` falls
    back to ``mixed`` so a malformed client still boots cleanly.
    """
    _, _, state = translate_request(_base_request("zzz-unknown"))
    assert state["mode"] == "mixed"


def test_translate_request_missing_mode_defaults_to_mixed() -> None:
    _, _, state = translate_request(_base_request(None))
    assert state["mode"] == "mixed"


def test_translate_request_preserves_user_material_context_flags() -> None:
    req = _base_request(None)
    req["candidate"] = {
        "name": "Alex",
        "resume_parsed": {
            "summary": "x",
            "context_flags": ["possible_prompt_injection"],
        },
    }
    req["job_spec"] = {
        "title": "Backend Engineer",
        "level": "senior",
        "context_flags": ["possible_prompt_injection"],
    }

    _, _, state = translate_request(req)

    assert state["context_flags"] == {
        "resume": ["possible_prompt_injection"],
        "job_spec": ["possible_prompt_injection"],
    }


def test_translate_request_filters_focus_dimensions_to_rubric() -> None:
    req = _base_request(None)
    req["job_spec"] = {
        "title": "Backend Engineer",
        "level": "senior",
        "required_skills": ["python"],
        "rubric_dimensions": ["technical_depth", "system_design"],
    }
    req["focus_dimensions"] = ["system_design", "missing", "technical_depth"]

    _, _, state = translate_request(req)

    assert state["focus_dimensions"] == ["system_design", "technical_depth"]


def test_translate_request_generates_timestamped_session_id() -> None:
    session_id, _, _ = translate_request(_base_request(None))

    assert re.fullmatch(r"sess-\d{8}-\d{6}-[0-9a-f]{6}", session_id)


def test_translate_request_preserves_explicit_session_id() -> None:
    req = _base_request(None)
    req["session_id"] = "sess-custom"

    session_id, _, state = translate_request(req)

    assert session_id == "sess-custom"
    assert state["session_id"] == "sess-custom"


def test_runtime_config_defaults() -> None:
    """When the request omits runtime fields, runtime_config carries the
    safe defaults that downstream nodes (ask_question, evaluator) rely on.
    """
    _, _, state = translate_request(_base_request(None))
    runtime = state["runtime_config"]
    assert runtime["rag_top_k"] == 5
    assert runtime["rag_mode"] == "vector"
    assert runtime["llm_temperature"] is None
    assert runtime["interview_depth"] == "standard"


def test_runtime_config_preserves_interview_depth() -> None:
    req = _base_request(None)
    req["interview_depth"] = "deep"

    _, _, state = translate_request(req)

    assert state["runtime_config"]["interview_depth"] == "deep"


def test_runtime_config_clamps_rag_top_k_above_upper_bound() -> None:
    """Huge top_k values would over-pull from the vector store and bloat
    the prompt. The translator clamps them to the documented ceiling."""
    req = _base_request(None)
    req["rag_top_k"] = 10_000
    _, _, state = translate_request(req)
    assert state["runtime_config"]["rag_top_k"] == 50


def test_runtime_config_clamps_rag_top_k_below_lower_bound() -> None:
    req = _base_request(None)
    req["rag_top_k"] = 0
    _, _, state = translate_request(req)
    assert state["runtime_config"]["rag_top_k"] == 1


def test_runtime_config_falls_back_to_default_for_garbage_rag_top_k() -> None:
    """Non-numeric / bool inputs collapse to the default so a malformed
    runtime payload still produces a valid graph state."""
    for garbage in ("abc", [], True, False):
        req = _base_request(None)
        req["rag_top_k"] = garbage
        _, _, state = translate_request(req)
        assert state["runtime_config"]["rag_top_k"] == 5


def test_runtime_config_rejects_unknown_rag_mode() -> None:
    """``rag_mode`` is restricted to the documented retriever backends so
    a fat-fingered client cannot silently change retrieval behaviour."""
    req = _base_request(None)
    req["rag_mode"] = "graph"
    _, _, state = translate_request(req)
    assert state["runtime_config"]["rag_mode"] == "vector"


def test_runtime_config_accepts_hybrid_rag_mode() -> None:
    req = _base_request(None)
    req["rag_mode"] = "hybrid"
    _, _, state = translate_request(req)
    assert state["runtime_config"]["rag_mode"] == "hybrid"


def test_runtime_config_clamps_llm_temperature_above_upper_bound() -> None:
    """Out-of-range temperatures degrade LLM output quality. The
    translator clamps them to the OpenAI-style [0.0, 2.0] window."""
    req = _base_request(None)
    req["llm_temperature"] = 5.0
    _, _, state = translate_request(req)
    assert state["runtime_config"]["llm_temperature"] == 2.0


def test_runtime_config_clamps_llm_temperature_below_lower_bound() -> None:
    req = _base_request(None)
    req["llm_temperature"] = -0.5
    _, _, state = translate_request(req)
    assert state["runtime_config"]["llm_temperature"] == 0.0


def test_runtime_config_preserves_valid_llm_temperature() -> None:
    req = _base_request(None)
    req["llm_temperature"] = 0.4
    _, _, state = translate_request(req)
    assert state["runtime_config"]["llm_temperature"] == 0.4


def test_runtime_config_falls_back_to_none_for_garbage_temperature() -> None:
    """Non-numeric or bool temperature inputs collapse to ``None`` so
    downstream LLM calls keep using ``settings.llm_temperature``."""
    for garbage in ("hot", [], True):
        req = _base_request(None)
        req["llm_temperature"] = garbage
        _, _, state = translate_request(req)
        assert state["runtime_config"]["llm_temperature"] is None
