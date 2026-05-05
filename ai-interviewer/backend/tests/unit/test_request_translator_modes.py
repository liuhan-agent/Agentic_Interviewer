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


def test_translate_request_generates_timestamped_session_id() -> None:
    session_id, _, _ = translate_request(_base_request(None))

    assert re.fullmatch(r"sess-\d{8}-\d{6}-[0-9a-f]{6}", session_id)


def test_translate_request_preserves_explicit_session_id() -> None:
    req = _base_request(None)
    req["session_id"] = "sess-custom"

    session_id, _, state = translate_request(req)

    assert session_id == "sess-custom"
    assert state["session_id"] == "sess-custom"
