"""Contract negotiation between Generator and Evaluator.

The generator proposes a draft contract inside ``generate_question``;
this module wraps the *evaluator-side* confirmation step. Having the
evaluator sign off on the rubric BEFORE the candidate sees the
question is the core of the "iterative contract" pattern: the grader
commits to a yardstick instead of inventing one post-hoc.

Output shape::

    {
      "must_cover":           ["..."],
      "acceptable_if_missing":["..."],
      "acceptance_checks":    ["..."],   # yes/partial/no items
      "minimum_bar":          "one sentence",
      "review_focus":         ["..."],
      "bar_level":            "intro|standard|deep_probe",
      "signed_by":            ["generator", "evaluator"]
    }

This helper is defensive: any LLM parsing failure degrades to the
generator's proposal (still marked ``signed_by=['generator']`` so
downstream code knows the contract was *not* co-signed).
"""
from __future__ import annotations

from typing import Any

# ``get_settings`` is re-exported for backwards compatibility:
# ``test_contract_equivalence.py`` patches ``contract.get_settings`` to
# flip the ``use_context_builder`` flag underneath
# ``negotiate_contract_via_evaluator`` without touching the global
# settings cache. The alias stays even when this module does not read
# the setting directly so the patch target remains stable.
from app.core.logging import get_logger
from app.core.settings import get_settings as get_settings
from app.engine.context import (
    build_context_frame_for_contract_negotiator,
    frame_to_contract_negotiator_messages,
)
from app.engine.workflow.difficulty_adapter import difficulty_to_bar_level

from .llm_client import call_chat, parse_json_response

log = get_logger(__name__)


def _expected_bar_level(target_difficulty: str | None) -> str | None:
    value = str(target_difficulty or "").strip().lower()
    if value not in {"easy", "medium", "hard"}:
        return None
    return difficulty_to_bar_level(value)  # type: ignore[arg-type]


def _default_contract(
    *,
    proposed: dict[str, Any],
    dimension: str,
    expected_bar_level: str | None = None,
) -> dict[str, Any]:
    """Fallback contract if both generator proposal and LLM reply fail.

    Uses sensible defaults keyed on ``dimension`` so the interview
    can still proceed with *some* yardstick rather than a scoring
    void. Marked ``signed_by=['generator']`` only, so later audits
    can tell it was never actually co-signed.
    """
    must_cover = proposed.get("must_cover") or proposed.get("rubric_points") or [
        "depth",
        "clarity",
    ]
    acceptance_checks = proposed.get("acceptance_checks") or [
        f"Answer directly addresses {dimension.replace('_', ' ')}.",
        "Answer provides at least one concrete example or mechanism.",
    ]
    return {
        "must_cover": must_cover,
        "acceptable_if_missing": proposed.get("acceptable_if_missing", []),
        "acceptance_checks": acceptance_checks,
        "minimum_bar": proposed.get(
            "minimum_bar",
            "Covers the core concept with one concrete example.",
        ),
        "review_focus": proposed.get("review_focus", []),
        "bar_level": expected_bar_level or proposed.get("bar_level", "standard"),
        "signed_by": ["generator"],
    }


def negotiate_contract_via_evaluator(
    *,
    dimension: str,
    job_level: str,
    question: str,
    proposed_contract: dict[str, Any],
    contract_hints: dict[str, Any] | None = None,
    target_difficulty: str | None = None,
) -> dict[str, Any]:
    """Have the Evaluator confirm/amend ``proposed_contract``.

    Returns a contract dict in the shape described in the module
    docstring. ``signed_by`` is always either
    ``['generator']`` (degraded path) or ``['generator', 'evaluator']``
    (happy path).
    """
    hints = contract_hints or {}
    expected_bar_level = _expected_bar_level(target_difficulty)
    frame = build_context_frame_for_contract_negotiator(
        dimension=dimension,
        job_level=job_level,
        question=question,
        proposed_contract=proposed_contract,
        contract_hints=hints,
        target_difficulty=target_difficulty or "",
    )
    messages = frame_to_contract_negotiator_messages(frame)
    try:
        raw = call_chat(messages, json_mode=True, agent_role="contract_negotiator")
        data = parse_json_response(raw)
    except Exception as e:  # pragma: no cover - provider flakes
        log.warning("contract negotiation failed, falling back: %s", e)
        data = {}

    if not isinstance(data, dict) or not data:
        return _default_contract(
            proposed=proposed_contract,
            dimension=dimension,
            expected_bar_level=expected_bar_level,
        )

    must_cover = data.get("must_cover") or proposed_contract.get(
        "must_cover"
    ) or proposed_contract.get("rubric_points") or []
    acceptance_checks = data.get("acceptance_checks") or proposed_contract.get(
        "acceptance_checks"
    ) or []

    signed: list[str] = ["generator", "evaluator"]
    # Heuristic: if the evaluator returned an essentially-empty shape
    # (both must_cover and acceptance_checks missing) we haven't
    # really gotten a co-sign; record that.
    if not must_cover and not acceptance_checks:
        log.info("evaluator reply was empty; treating contract as unsigned")
        signed = ["generator"]

    return {
        "must_cover": list(must_cover) or ["depth", "clarity"],
        "acceptable_if_missing": list(
            data.get("acceptable_if_missing")
            or proposed_contract.get("acceptable_if_missing", [])
        ),
        "acceptance_checks": list(
            acceptance_checks
            or [
                f"Answer directly addresses {dimension.replace('_', ' ')}.",
                "Answer provides at least one concrete example or mechanism.",
            ]
        ),
        "minimum_bar": data.get("minimum_bar")
        or proposed_contract.get(
            "minimum_bar",
            "Covers the core concept with one concrete example.",
        ),
        "review_focus": list(
            data.get("review_focus") or proposed_contract.get("review_focus", [])
        ),
        "bar_level": expected_bar_level
        or data.get("bar_level")
        or proposed_contract.get("bar_level", "standard"),
        "signed_by": signed,
    }
