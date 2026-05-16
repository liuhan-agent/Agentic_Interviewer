"""Role-specific renderers that turn a :class:`ContextFrame` into messages.

A renderer is the sole place that knows how a particular agent's prompt
file (``generator_task.md`` etc.) consumes the frame's ``payload`` keys.
Keeping this mapping in one file means prompt-file changes only ripple
one level out.
"""
from __future__ import annotations

import re

from app.engine.agents.llm_client import CacheHint, ChatMessage
from app.engine.agents.prompts.loader import render_prompt

from .frame import ContextFrame

__all__ = [
    "frame_to_generator_messages",
    "frame_to_evaluator_messages",
    "frame_to_verifier_messages",
    "frame_to_guard_messages",
    "frame_to_contract_negotiator_messages",
    "frame_to_session_summarizer_messages",
    "frame_to_coach_messages",
]


_GENERATOR_PAYLOAD_KEYS = (
    "dimension",
    "target_difficulty",
    "probe_intent",
    "action",
    "refine_mode",
    "job_title",
    "job_level",
    "role_required_skills",
    "target_skills",
    "highlights",
    "resume_anchor",
    "self_intro_profile",
    "user_material_boundary",
    "history_section",
    "retrieval",
    "question_seed",
    "candidate_anchor",
    "strategy",
    "skills",
    "avoid_patterns",
    "contract_hints",
)


def _system_messages_from_frame(frame: ContextFrame) -> list[ChatMessage]:
    """Split the frame's static/dynamic system layers into tagged messages.

    When ``frame.cache_static`` is True (the default) the static prefix
    is marked ``cache_control="ephemeral"`` so providers that support
    prompt caching (Anthropic today; OpenAI's automatic cache is
    size-based and needs no hint) will cache only the stable prefix.
    Phase-1 role builders (Verifier / Guard / Contract-Negotiator /
    Session-Summarizer / Coach) set ``cache_static=False`` because
    their static system text is short, role-specific, and would not
    cleanly share a cache key with the main Generator/Evaluator
    skeleton. The dynamic tail is emitted as a separate plain system
    message only when non-empty, avoiding a stray double-newline in
    the prompt when there is no tail to add.

    Joining the returned messages' ``content`` with ``"\\n\\n"``
    reproduces the exact string the legacy single-system path
    assembled as ``f"{static}\\n\\n{dynamic}"`` - the Generator
    equivalence test locks that invariant.
    """
    cache_hint: CacheHint | None = "ephemeral" if frame.cache_static else None
    system_messages: list[ChatMessage] = [
        ChatMessage(
            "system", frame.static_system, cache_control=cache_hint
        )
    ]
    if frame.dynamic_system:
        system_messages.append(ChatMessage("system", frame.dynamic_system))
    return system_messages


def frame_to_generator_messages(frame: ContextFrame) -> list[ChatMessage]:
    """Render a ``generator``-role frame as the ``call_chat`` message list.

    The system prefix is split into a cacheable ``static_system`` block
    plus an optional uncached ``dynamic_system`` block. The aggregate
    prompt content is identical to what the legacy single-system path
    produced (``static + "\\n\\n" + dynamic``), only now Anthropic's
    prompt cache can target just the static layer - the per-session
    strategy index no longer invalidates the cached prefix on every
    call.

    Raises
    ------
    ValueError
        If ``frame.agent_role`` is anything other than ``"generator"``.
    KeyError
        If ``frame.payload`` is missing a required Generator variable.
        Surfacing this eagerly means a malformed builder fails the unit
        test, not a live interview.
    """
    if frame.agent_role != "generator":
        raise ValueError(
            "frame_to_generator_messages expects agent_role='generator', "
            f"got {frame.agent_role!r}"
        )

    missing = [k for k in _GENERATOR_PAYLOAD_KEYS if k not in frame.payload]
    if missing:
        raise KeyError(
            f"ContextFrame.payload is missing Generator keys: {missing}"
        )

    user_text = render_prompt(
        "generator_task.md",
        **{k: frame.payload[k] for k in _GENERATOR_PAYLOAD_KEYS},
    )
    if not str(frame.payload.get("question_seed") or "").strip():
        user_text = _suppress_empty_question_seed_prompt(user_text)
    if not str(frame.payload.get("candidate_anchor") or "").strip():
        user_text = _suppress_empty_candidate_anchor_prompt(user_text)
    return [
        *_system_messages_from_frame(frame),
        ChatMessage("user", user_text),
    ]


def _suppress_empty_question_seed_prompt(user_text: str) -> str:
    """Keep vector/shadow prompts free of structured-question-bank text."""

    user_text = re.sub(
        r"\n- If STRUCTURED_QUESTION_SEED is non-empty,.*?(?=\n- Treat TARGET_SKILLS)",
        "",
        user_text,
        flags=re.DOTALL,
    )
    return re.sub(
        r"\nSTRUCTURED_QUESTION_SEED =\n(?:[ \t]*\n)+(?=(?:CANDIDATE_ANCHOR|STRATEGY_MEMORY) =)",
        "\n",
        user_text,
    )


def _suppress_empty_candidate_anchor_prompt(user_text: str) -> str:
    """Keep shadow/vector prompts free of candidate-anchor plumbing."""

    user_text = re.sub(
        r"\n- If CANDIDATE_ANCHOR is non-empty,.*?(?=\n- Treat TARGET_SKILLS|\nRETRIEVED_KNOWLEDGE =)",
        "",
        user_text,
        flags=re.DOTALL,
    )
    return re.sub(
        r"\nCANDIDATE_ANCHOR =\n(?:[ \t]*\n)+(?=STRATEGY_MEMORY =)",
        "\n",
        user_text,
    )


_EVALUATOR_PAYLOAD_KEYS = (
    "dimension",
    "question",
    "contract",
    "rubric_points",
    "answer",
    "threshold",
    "user_material_boundary",
    "video_signals",
)


def frame_to_evaluator_messages(frame: ContextFrame) -> list[ChatMessage]:
    """Render an ``evaluator``-role frame as the ``call_chat`` message list.

    Mirrors :func:`frame_to_generator_messages` contract: the returned
    list is byte-identical to what ``evaluate_answer`` builds inline
    today, covered by ``tests/unit/test_evaluator_equivalence.py``.
    """
    if frame.agent_role != "evaluator":
        raise ValueError(
            "frame_to_evaluator_messages expects agent_role='evaluator', "
            f"got {frame.agent_role!r}"
        )

    missing = [k for k in _EVALUATOR_PAYLOAD_KEYS if k not in frame.payload]
    if missing:
        raise KeyError(
            f"ContextFrame.payload is missing Evaluator keys: {missing}"
        )

    user_text = render_prompt(
        "evaluator_task.md",
        **{k: frame.payload[k] for k in _EVALUATOR_PAYLOAD_KEYS},
    )
    return [
        *_system_messages_from_frame(frame),
        ChatMessage("user", user_text),
    ]


_VERIFIER_PAYLOAD_KEYS = (
    "dimension",
    "contract",
    "question",
    "answer",
    "evaluator_report",
)


def frame_to_verifier_messages(frame: ContextFrame) -> list[ChatMessage]:
    """Render a ``verifier``-role frame as the ``call_chat`` message list.

    Mirrors :func:`frame_to_generator_messages` contract. The returned
    list is byte-identical to what
    :func:`app.engine.agents.verification.verify_answer` builds inline
    today (see ``tests/unit/test_verifier_equivalence.py``). The
    static system layer is NOT cached (``cache_static=False`` in the
    matching builder) because the Verifier's short, role-specific
    prompt does not share a cache key with the main Generator/Evaluator
    skeleton.
    """
    if frame.agent_role != "verifier":
        raise ValueError(
            "frame_to_verifier_messages expects agent_role='verifier', "
            f"got {frame.agent_role!r}"
        )

    missing = [k for k in _VERIFIER_PAYLOAD_KEYS if k not in frame.payload]
    if missing:
        raise KeyError(
            f"ContextFrame.payload is missing Verifier keys: {missing}"
        )

    user_text = render_prompt(
        "verifier_task.md",
        **{k: frame.payload[k] for k in _VERIFIER_PAYLOAD_KEYS},
    )
    return [
        *_system_messages_from_frame(frame),
        ChatMessage("user", user_text),
    ]


_GUARD_PAYLOAD_KEYS = (
    "target_kind",
    "text",
)


def frame_to_guard_messages(frame: ContextFrame) -> list[ChatMessage]:
    """Render a ``guard``-role frame as the ``call_chat`` message list.

    Byte-identical to :func:`app.engine.agents.guard.classify`'s inline
    assembly. The static system layer is uncached for the same reason
    as the Verifier renderer.
    """
    if frame.agent_role != "guard":
        raise ValueError(
            "frame_to_guard_messages expects agent_role='guard', "
            f"got {frame.agent_role!r}"
        )

    missing = [k for k in _GUARD_PAYLOAD_KEYS if k not in frame.payload]
    if missing:
        raise KeyError(
            f"ContextFrame.payload is missing Guard keys: {missing}"
        )

    user_text = render_prompt(
        "guard_check.md",
        **{k: frame.payload[k] for k in _GUARD_PAYLOAD_KEYS},
    )
    return [
        *_system_messages_from_frame(frame),
        ChatMessage("user", user_text),
    ]


_CONTRACT_NEGOTIATOR_PAYLOAD_KEYS = (
    "dimension",
    "job_level",
    "question",
    "proposed_contract",
    "contract_hints",
)


def frame_to_contract_negotiator_messages(
    frame: ContextFrame,
) -> list[ChatMessage]:
    """Render a ``contract_negotiator``-role frame into messages.

    Byte-identical to
    :func:`app.engine.agents.contract.negotiate_contract_via_evaluator`'s
    inline assembly.
    """
    if frame.agent_role != "contract_negotiator":
        raise ValueError(
            "frame_to_contract_negotiator_messages expects "
            "agent_role='contract_negotiator', "
            f"got {frame.agent_role!r}"
        )

    missing = [
        k for k in _CONTRACT_NEGOTIATOR_PAYLOAD_KEYS if k not in frame.payload
    ]
    if missing:
        raise KeyError(
            "ContextFrame.payload is missing Contract-Negotiator keys: "
            f"{missing}"
        )

    user_text = render_prompt(
        "contract_negotiate.md",
        **{k: frame.payload[k] for k in _CONTRACT_NEGOTIATOR_PAYLOAD_KEYS},
    )
    return [
        *_system_messages_from_frame(frame),
        ChatMessage("user", user_text),
    ]


_SESSION_SUMMARIZER_PAYLOAD_KEYS = (
    "job_title",
    "job_level",
    "existing_summary",
    "new_turns",
)


def frame_to_session_summarizer_messages(
    frame: ContextFrame,
) -> list[ChatMessage]:
    """Render a ``session_summarizer``-role frame into messages.

    Byte-identical to
    :func:`app.engine.agents.session_summarizer.summarise_session`'s
    inline assembly.
    """
    if frame.agent_role != "session_summarizer":
        raise ValueError(
            "frame_to_session_summarizer_messages expects "
            "agent_role='session_summarizer', "
            f"got {frame.agent_role!r}"
        )

    missing = [
        k for k in _SESSION_SUMMARIZER_PAYLOAD_KEYS if k not in frame.payload
    ]
    if missing:
        raise KeyError(
            "ContextFrame.payload is missing Session-Summarizer keys: "
            f"{missing}"
        )

    user_text = render_prompt(
        "session_summary.md",
        **{k: frame.payload[k] for k in _SESSION_SUMMARIZER_PAYLOAD_KEYS},
    )
    return [
        *_system_messages_from_frame(frame),
        ChatMessage("user", user_text),
    ]


_COACH_PAYLOAD_KEYS = (
    "job_spec",
    "candidate",
    "final_report",
    "qa_tailored",
    "self_intro_profile",
    "dimension_evidence",
    "verification_summary",
)


def frame_to_coach_messages(frame: ContextFrame) -> list[ChatMessage]:
    """Render a ``coach``-role frame into messages.

    Byte-identical to :func:`app.engine.agents.coach.build_training_plan`'s
    inline assembly once the Phase-1 Step-5 migration externalises the
    ``_COACH_TASK`` f-string template into ``prompts/coach_task.md``.
    """
    if frame.agent_role != "coach":
        raise ValueError(
            "frame_to_coach_messages expects agent_role='coach', "
            f"got {frame.agent_role!r}"
        )

    missing = [k for k in _COACH_PAYLOAD_KEYS if k not in frame.payload]
    if missing:
        raise KeyError(
            f"ContextFrame.payload is missing Coach keys: {missing}"
        )

    user_text = render_prompt(
        "coach_task.md",
        **{k: frame.payload[k] for k in _COACH_PAYLOAD_KEYS},
    )
    return [
        *_system_messages_from_frame(frame),
        ChatMessage("user", user_text),
    ]
