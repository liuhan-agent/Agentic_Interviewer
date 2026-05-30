"""Ask-question node: run the ``AskPlan`` steps and emit question + contract.

Execution model
---------------
The node resolves an :class:`AskPlan` (either from the current
``selected_action``, a ``pending_plan_template`` left by the previous
evaluator, or the legacy ``runtime_config.iterative_contract`` flag)
and then runs its steps in order. Each step updates a small
``step_ctx`` dict; the node only writes back to state after the
whole plan has been executed.

The plan executor here is intentionally simple (a linear loop with
minimal retry): the plan is an in-node artifact, not a graph-level
state machine. If richer semantics are ever needed, that belongs at
the LangGraph layer, not here.

Contract
--------
The signed-off :class:`PlanContract` is written to both
``state['current_contract']`` and ``state['current_question']['contract']``
so both old and new readers can find it.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import record_question_fallback
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.agents.contract import negotiate_contract_via_evaluator
from app.engine.agents.generator import generate_question
from app.engine.agents.security import check_question
from app.engine.context.history_context import build_history_context
from app.engine.rag.retriever import retrieve_for_question
from app.engine.resume_plan import select_resume_anchor_with_schedule
from app.engine.workflow.difficulty_adapter import difficulty_to_bar_level
from app.engine.workflow.plans import build_llm_ask_plan, resolve_ask_plan
from app.engine.workflow.policy_context import policy_context_keys
from app.engine.workflow.probe_intent import resolve_probe_intent
from app.engine.workflow.replay_basis import build_replay_question_basis
from app.engine.workflow.skill_focus import select_target_skills
from app.engine.workflow.state import (
    AskPlan,
    InterviewState,
    PlanContract,
    PlanTemplate,
)
from app.memory.skill_store import build_skills_block, retrieve_skills
from app.memory.strategy_store import format_strategies_for_prompt, retrieve_strategies
from app.ml.drift.prompt_feedback import build_generator_avoid_patterns
from app.models.base import get_session
from app.services.question_fit_profile import (
    build_question_fit_profile as _build_question_fit_profile,
)
from app.services.question_fit_profile import (
    candidate_anchor_artifact,
    format_candidate_anchor_block,
    resolve_question_bank_tags,
)
from app.services.question_reranker import (
    QuestionRerankResult,
)
from app.services.question_reranker import (
    record_question_rerank_usage as _record_question_rerank_usage,
)
from app.services.question_reranker import (
    rerank_question_candidates as _rerank_question_candidates,
)
from app.services.question_selector import (
    QuestionCandidate,
    QuestionSelectionResult,
    build_question_seed_contract_hints,
    format_question_seed_block,
)
from app.services.question_selector import (
    record_question_usages as _record_question_usages,
)
from app.services.question_selector import (
    select_question_candidates as _select_question_candidates,
)
from app.services.question_usage_stats import build_question_reward_context_key
from app.services.resume_vector_jobs import refresh_resume_vector_status
from app.services.session_anchor_retriever import retrieve_candidate_anchors

log = get_logger(__name__)

_QUESTION_SELECTOR_MODES = {"vector", "structured_shadow", "structured_primary"}
_PROMPT_SLOT_TEXT_LIMIT = 2000
_PROMPT_SLOT_PLACEHOLDER_REASONS = {
    "(no relevant knowledge retrieved)": "no_relevant_knowledge",
    "(no relevant strategy memories)": "no_relevant_strategy_memories",
    "(no relevant interview skills)": "no_relevant_interview_skills",
}
_EXPECTED_CONTRACT_BAR_BY_DIFFICULTY = {
    "easy": "intro",
    "medium": "standard",
    "hard": "deep_probe",
}
_GENERIC_CONTRACT_ITEMS = {"depth", "clarity"}


def select_question_candidates(**kwargs: Any) -> QuestionSelectionResult:
    """Thin DB wrapper kept patchable for workflow tests."""

    with get_session() as session:
        return _select_question_candidates(session, **kwargs)


def record_question_usages(**kwargs: Any) -> None:
    """Thin persistence wrapper kept patchable for workflow tests."""

    _record_question_usages(**kwargs)


def build_question_fit_profile(**kwargs: Any) -> Any:
    """Thin profile wrapper kept patchable for workflow tests."""

    return _build_question_fit_profile(**kwargs)


def rerank_question_candidates(**kwargs: Any) -> QuestionRerankResult:
    """Thin shadow-reranker wrapper kept patchable for workflow tests."""

    return _rerank_question_candidates(**kwargs)


def record_question_rerank_usage(**kwargs: Any) -> None:
    """Thin persistence wrapper kept patchable for workflow tests."""

    _record_question_rerank_usage(**kwargs)


def _step_retrieve_rag(state: InterviewState, ctx: dict[str, Any]) -> None:
    runtime_config = state.get("runtime_config") or {}
    retrieve_kwargs: dict[str, Any] = {
        "job_spec": state.get("job_spec", {}),
        "dimension": ctx["dimension"],
        "previous_qa": state.get("qa_history", []),
        "top_k": runtime_config.get("rag_top_k", 5),
        "mode": runtime_config.get("rag_mode", "vector"),
    }
    if ctx.get("resume_anchor"):
        retrieve_kwargs["resume_anchor"] = ctx["resume_anchor"]
    if ctx.get("target_skills"):
        retrieve_kwargs["target_skills"] = ctx["target_skills"]
    direction_alpha = _resolve_direction_alpha(state)
    if direction_alpha is not None:
        retrieve_kwargs["direction_alpha"] = direction_alpha
    retrieval = retrieve_for_question(**retrieve_kwargs)
    ctx["retrieval_block"] = retrieval.as_prompt_block
    ctx["rag_artifact"] = _rag_selection_artifact(
        retrieval,
        mode=str(retrieve_kwargs.get("mode") or "vector"),
        top_k=int(retrieve_kwargs.get("top_k") or 5),
    )


def _resolve_direction_alpha(state: InterviewState) -> float | None:
    """Look up the per-direction Hybrid RAG blend weight (P3 #6).

    Returns ``None`` when:
      * ``runtime_config.rag_mode`` is not ``hybrid`` (cheap short-circuit
        — the retriever ignores ``alpha`` in vector mode anyway, but
        skipping the lookup here keeps the hot path import-free);
      * ``job_spec.interview_direction`` is missing or unknown
        (``InterviewDirectionNotFound``); or
      * the matched direction did not declare a ``retrieval.alpha``.

    Any of those falls back to ``settings.retrieval_alpha_default``
    inside :func:`_resolve_hybrid_alpha`.
    """
    runtime_config = state.get("runtime_config") or {}
    if (runtime_config.get("rag_mode") or "vector") != "hybrid":
        return None
    direction_id = (state.get("job_spec") or {}).get("interview_direction")
    if not direction_id:
        return None
    try:
        from app.services.job_directions import (
            InterviewDirectionNotFound,
            get_interview_direction,
        )

        direction = get_interview_direction(str(direction_id))
    except InterviewDirectionNotFound:
        return None
    return direction.retrieval_alpha


def _step_retrieve_strategy(state: InterviewState, ctx: dict[str, Any]) -> None:
    job_level = (state.get("job_spec") or {}).get("level", "mid")
    settings = get_settings()
    # PLAN_LLM_MEMORY_SELECTOR: opt-in second-pass LLM selector runs
    # on the keyword-filtered top-N for strategy memories.
    use_llm_selector = bool(
        getattr(settings, "enable_llm_memory_selector", False)
    )
    recent_qa_summary = str(
        ctx.get("history_selector_summary") or state.get("qa_summary") or ""
    )

    strategies = retrieve_strategies(
        dimension=ctx["dimension"],
        job_level=job_level,
        policy_context_keys=_strategy_policy_context_keys(state, ctx),
        use_llm_selector=use_llm_selector,
        recent_qa_summary=recent_qa_summary,
    )
    refs = [_strategy_memory_ref(entry) for entry in strategies]
    ctx["strategy_memory_refs"] = [ref for ref in refs if ref]
    ctx["strategy_block"] = format_strategies_for_prompt(strategies)

    # PLAN_DRIFT_RAG_FEEDBACK: same ``overruled_patterns`` snapshot
    # that feeds the Evaluator negatives (``PLAN_DRIFT_FEEDBACK``),
    # re-rendered from the Generator's perspective — "design the
    # question AWAY from these shallow evidence shapes". Only
    # overwrites the default placeholder when the renderer returns a
    # non-empty block.
    avoid_enabled = bool(getattr(settings, "enable_generator_avoid_patterns", False))
    avoid_top_n = int(getattr(settings, "drift_feedback_top_n", 3))
    avoid_min_support = int(getattr(settings, "drift_feedback_min_support", 2))
    ctx["avoid_pattern_artifact"] = {
        "enabled": avoid_enabled,
        "rendered": False,
        "dimension": ctx["dimension"],
        "top_n": avoid_top_n,
        "min_support": avoid_min_support,
    }
    if avoid_enabled:
        # PR5+6 of drift-feedback persistence: when ``drift_feedback_source``
        # is ``db`` / ``db_shadow``, the renderer can drill into the
        # ``(dimension, check, failure_category)`` rows of
        # ``verifier_drift_patterns`` instead of always rolling up to
        # ``__global__``. Forwarding the structured failure categories
        # from ``contract_hints`` here is what closes that loop — the
        # caller already has them via ``_failure_categories_from_hints``
        # for ``selection_artifacts``, so reusing the same helper keeps
        # both sites reading from the same source of truth.
        avoid_failure_categories = _failure_categories_from_hints(
            ctx.get("contract_hints")
        )
        try:
            rendered = build_generator_avoid_patterns(
                dimension=ctx["dimension"],
                top_n=avoid_top_n,
                min_support=avoid_min_support,
                failure_categories=avoid_failure_categories,
            )
            if rendered:
                ctx["avoid_patterns"] = rendered
                ctx["avoid_pattern_artifact"]["rendered"] = True
        except Exception as e:  # pragma: no cover - feedback is non-critical
            log.debug("generator avoid-patterns render failed: %s", e)


def _step_retrieve_skills(state: InterviewState, ctx: dict[str, Any]) -> None:
    settings = get_settings()
    skill_enabled = bool(getattr(settings, "enable_skill_injection", False))
    ctx["skill_artifact"] = {
        "enabled": skill_enabled,
        "refs": [],
    }
    if not skill_enabled:
        return

    job_level = (state.get("job_spec") or {}).get("level", "mid")
    use_llm_selector = bool(
        getattr(settings, "enable_llm_memory_selector", False)
    )
    recent_qa_summary = str(
        ctx.get("history_selector_summary") or state.get("qa_summary") or ""
    )
    direction_tags = ctx.get("question_direction_tags")
    role_tags = ctx.get("question_role_tags")
    if direction_tags is None or role_tags is None:
        direction_tags, role_tags = resolve_question_bank_tags(
            job_spec=state.get("job_spec", {}),
            runtime_config=state.get("runtime_config") or {},
        )
        ctx["question_direction_tags"] = direction_tags
        ctx["question_role_tags"] = role_tags

    try:
        skills = retrieve_skills(
            dimension=ctx["dimension"],
            job_level=job_level,
            limit=int(getattr(settings, "skill_retrieval_limit", 3)),
            backend=str(
                getattr(
                    settings,
                    "skill_playbook_backend",
                    "db_with_file_fallback",
                )
            ),
            use_llm_selector=use_llm_selector,
            recent_qa_summary=recent_qa_summary,
            direction_tags=list(direction_tags or []),
            role_tags=list(role_tags or []),
            probe_intent=ctx.get("probe_intent"),
            failure_categories=_failure_categories_from_hints(
                ctx.get("contract_hints"),
            ),
        )
        skill_refs = []
        for idx, skill in enumerate(skills, 1):
            ref = _skill_card_ref(skill)
            ref["rank"] = idx
            skill_refs.append(ref)
        ctx["skill_artifact"]["refs"] = skill_refs
        ctx["skill_block"] = build_skills_block(skills)
    except Exception as e:  # pragma: no cover - defensive degradation
        log.warning("skill retrieval failed; continuing without skills: %s", e)
        ctx.setdefault("skill_block", "(no relevant interview skills)")
        ctx["skill_artifact"].update({
            "error": "retrieval_failed",
            "error_type": type(e).__name__,
        })


def _strategy_policy_context_keys(
    state: InterviewState,
    ctx: dict[str, Any],
) -> list[str]:
    keys = state.get("policy_context_keys")
    if isinstance(keys, list) and keys:
        return [str(key) for key in keys if str(key or "").strip()]
    return policy_context_keys(state.get("job_spec") or {}, ctx.get("dimension"))


def _rag_selection_artifact(
    retrieval: Any,
    *,
    mode: str,
    top_k: int,
) -> dict[str, Any]:
    docs = list(getattr(retrieval, "docs", []) or [])
    doc_refs: list[dict[str, Any]] = []
    for doc in docs:
        metadata = dict(getattr(doc, "metadata", {}) or {})
        doc_refs.append({
            "source": metadata.get("source"),
            "chunk": metadata.get("chunk"),
            "source_type": metadata.get("source_type"),
            "score": float(getattr(doc, "score", 0.0) or 0.0),
        })
    return {
        "mode": mode,
        "top_k": top_k,
        "doc_refs": doc_refs,
        "empty": not bool(doc_refs),
        "reason": "matched" if doc_refs else "no_relevant_knowledge",
    }


def _skill_card_ref(entry: Any) -> dict[str, Any]:
    path = getattr(entry, "path", None)
    evaluator_rubric_hints = list(
        getattr(entry, "evaluator_rubric_hints", []) or []
    )
    positive_signals = list(getattr(entry, "positive_signals", []) or [])
    negative_signals = list(getattr(entry, "negative_signals", []) or [])
    score_bias_rules = list(getattr(entry, "score_bias_rules", []) or [])
    evaluator_visibility = bool(getattr(entry, "evaluator_visibility", False))

    # ``evaluator_payload`` is the Phase-A observability surface for the
    # evaluator skill-injection roadmap (see ``PLAN_SKILL_INJECTION.md``
    # Phase-3 hook). It groups the four evaluator-visible frontmatter
    # fields under a single key **only when** the card author has
    # explicitly opted in via ``evaluator_visibility: true``, so admin
    # observability can show "this is what the Evaluator could be told
    # about this turn" without consumers having to filter the flat
    # fields themselves.
    #
    # The flat fields (``evaluator_rubric_hints`` / ``positive_signals``
    # / ``negative_signals`` / ``score_bias_rules`` /
    # ``evaluator_visibility``) stay on the payload for backward
    # compatibility with any existing reader; the new grouped key is
    # ``None`` whenever the card does not advertise evaluator
    # visibility, giving downstream code a single boolean check instead
    # of recombining four list fields with the visibility flag.
    evaluator_payload: dict[str, Any] | None = None
    if evaluator_visibility:
        evaluator_payload = {
            "rubric_hints": evaluator_rubric_hints,
            "positive_signals": positive_signals,
            "negative_signals": negative_signals,
            "score_bias_rules": score_bias_rules,
        }

    return {
        "filename": path.name if path is not None else "",
        "id": getattr(entry, "id", ""),
        "name": getattr(entry, "name", ""),
        "description": getattr(entry, "description", ""),
        "display_name_zh": getattr(entry, "display_name_zh", ""),
        "display_description_zh": getattr(entry, "display_description_zh", ""),
        "status": getattr(entry, "status", "active"),
        "priority": int(getattr(entry, "priority", 0) or 0),
        "direction_tags": list(getattr(entry, "direction_tags", []) or []),
        "role_tags": list(getattr(entry, "role_tags", []) or []),
        "dimensions": list(getattr(entry, "dimensions", []) or []),
        "job_levels": list(getattr(entry, "job_levels", []) or []),
        "probe_intents": list(getattr(entry, "probe_intents", []) or []),
        "failure_categories": list(getattr(entry, "failure_categories", []) or []),
        "generator_moves": list(getattr(entry, "generator_moves", []) or []),
        "watch_for": list(getattr(entry, "watch_for", []) or []),
        "avoid": list(getattr(entry, "avoid", []) or []),
        "evaluator_rubric_hints": evaluator_rubric_hints,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "score_bias_rules": score_bias_rules,
        "evaluator_visibility": evaluator_visibility,
        "evaluator_payload": evaluator_payload,
        "match_score": float(getattr(entry, "match_score", 0.0) or 0.0),
        "match_reasons": list(getattr(entry, "match_reasons", []) or []),
        "reward_shadow_rank": getattr(entry, "reward_shadow_rank", None),
        "reward_shadow_score": getattr(entry, "reward_shadow_score", None),
        "reward_shadow_rank_changed": bool(
            getattr(entry, "reward_shadow_rank_changed", False)
        ),
        "usage_stats": getattr(entry, "usage_stats", None),
        "reward_shadow_reason": getattr(entry, "reward_shadow_reason", None),
    }


def _build_selection_artifacts(ctx: dict[str, Any]) -> dict[str, Any]:
    artifacts = {
        "rag": ctx.get("rag_artifact") or {
            "mode": "none",
            "top_k": 0,
            "doc_refs": [],
            "empty": True,
            "reason": "disabled",
        },
        "strategies": list(ctx.get("strategy_memory_refs") or []),
        "skills": ctx.get("skill_artifact") or {
            "enabled": False,
            "refs": [],
        },
        "avoid_patterns": ctx.get("avoid_pattern_artifact") or {
            "enabled": False,
            "rendered": False,
            "dimension": ctx.get("dimension"),
            "top_n": 0,
            "min_support": 0,
        },
        "question_items": list(ctx.get("question_items") or []),
        "failure_categories": _failure_categories_from_hints(
            ctx.get("contract_hints"),
        ),
        "candidate_anchor_rag": ctx.get("candidate_anchor_rag_artifact")
        or {"status": "off"},
        "resume_anchor": ctx.get("resume_anchor") or {},
        "anchor_scheduler": ctx.get("anchor_scheduler")
        or {
            "available": False,
            "anchor_key": None,
            "anchor_attempt": 0,
            "max_anchor_attempts": 0,
            "expansion_reason": "none",
        },
    }
    if ctx.get("question_fit_profile_artifact") is not None:
        artifacts["question_fit_profile"] = ctx["question_fit_profile_artifact"]
    if ctx.get("question_reranker_artifact") is not None:
        artifacts["question_reranker"] = ctx["question_reranker_artifact"]
    if ctx.get("candidate_anchor_artifact") is not None:
        artifacts["candidate_anchor"] = ctx["candidate_anchor_artifact"]
    return artifacts


def _failure_categories_from_hints(
    contract_hints: dict[str, Any] | None,
) -> list[str]:
    """Surface refine-followup failure_categories into selection artifacts.

    Reads the multi-value list when ``refine_followup`` (PR2) supplied
    it, otherwise wraps the legacy single ``failure_category`` so
    downstream consumers always see a list. ``None`` / unknown shapes
    degrade to ``[]`` — observability never aborts the ask path.
    """
    hints = contract_hints or {}
    multi = hints.get("failure_categories")
    if isinstance(multi, list) and multi:
        return [str(item) for item in multi if str(item or "").strip()]
    single = hints.get("failure_category")
    if isinstance(single, str) and single.strip():
        return [single]
    return []


def _resolve_question_selector_mode(state: InterviewState) -> str:
    runtime_config = state.get("runtime_config") or {}
    raw = runtime_config.get("question_selector_mode")
    if raw is None:
        # Real Settings carries the production default (structured_shadow).
        # Many legacy unit tests stub Settings with a narrow SimpleNamespace;
        # defaulting that legacy stub to vector preserves their old no-DB path.
        raw = getattr(get_settings(), "question_selector_mode", "vector")
    mode = str(raw or "structured_shadow")
    return mode if mode in _QUESTION_SELECTOR_MODES else "structured_shadow"


def _question_variant_intent(
    *,
    state: InterviewState,
    ctx: dict[str, Any],
    probe_intent: str | None,
) -> str:
    try:
        formal_turn = int(state.get("formal_turn_idx", state.get("turn_idx", 0)) or 0)
    except Exception:
        formal_turn = 0
    if formal_turn <= 0 and not (state.get("qa_history") or []):
        return "opening"

    hints = ctx.get("contract_hints") or {}
    if hints.get("failure_category") or hints.get("failure_categories"):
        return "recovery"

    selected = state.get("selected_action") or {}
    template = str(selected.get("plan_template") or selected.get("id") or "")
    if "deep_probe" in template:
        return "deep_probe"
    if probe_intent in {
        "architecture_challenge",
        "debugging_probe",
        "performance_probe",
        "metric_probe",
    }:
        return "deep_probe"
    return "followup"


def _question_selector_difficulty(target_difficulty: Any) -> str:
    value = str(target_difficulty or "").strip().lower()
    return {
        "easy": "warmup",
        "medium": "standard",
        "hard": "deep_probe",
        "intro": "warmup",
    }.get(value, value if value in {"warmup", "standard", "deep_probe", "stretch"} else "standard")


def _structured_primary_allowed(candidate: QuestionCandidate, settings: Any) -> bool:
    candidate_roles = {str(tag) for tag in candidate.role_tags or [] if str(tag).strip()}
    if not candidate_roles:
        return True
    allowed_roles = {
        str(tag)
        for tag in getattr(settings, "question_primary_role_tags", ["java_backend"])
        if str(tag).strip()
    }
    return bool(candidate_roles & allowed_roles)


def _resume_anchor_text(anchor: Any) -> str:
    if not isinstance(anchor, dict):
        return ""
    parts: list[str] = []
    for key in (
        "project_name",
        "name",
        "label",
        "project",
        "summary",
        "description",
        "role",
    ):
        value = str(anchor.get(key) or "").strip()
        if value:
            parts.append(value)
    for key in ("tech_stack", "skills", "keywords"):
        values = anchor.get(key)
        if isinstance(values, list):
            parts.extend(str(item) for item in values if str(item or "").strip())
    return " ".join(parts)


def _merge_contract_hints(
    base: dict[str, Any] | None,
    addition: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (addition or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _step_select_structured_question(
    state: InterviewState,
    ctx: dict[str, Any],
    *,
    probe_intent: str | None,
) -> None:
    mode = _resolve_question_selector_mode(state)
    ctx["question_selector_mode"] = mode
    ctx["question_candidates"] = []
    ctx["question_items"] = []
    ctx["question_seed_block"] = ""
    ctx["candidate_anchor_block"] = ""
    ctx["question_fit_profile_artifact"] = None
    ctx["question_reranker_artifact"] = None
    ctx["candidate_anchor_artifact"] = None
    ctx["structured_primary_seed_hit"] = False
    if mode == "vector":
        return

    settings = get_settings()
    intent = _question_variant_intent(state=state, ctx=ctx, probe_intent=probe_intent)
    direction_tags, role_tags = resolve_question_bank_tags(
        job_spec=state.get("job_spec", {}),
        runtime_config=state.get("runtime_config") or {},
    )
    ctx["question_direction_tags"] = direction_tags
    ctx["question_role_tags"] = role_tags
    job_level = str((state.get("job_spec") or {}).get("level", "mid") or "mid")
    question_context_key = build_question_reward_context_key(
        direction_tags=direction_tags,
        role_tags=role_tags,
        job_level=job_level,
        dimension=ctx["dimension"],
    )
    ctx["question_context_key"] = question_context_key
    fit_profile = None
    if bool(getattr(settings, "enable_question_fit_profile", True)):
        try:
            fit_profile = build_question_fit_profile(
                candidate=state.get("candidate", {}),
                self_intro_profile=state.get("self_intro_profile") or {},
                job_spec=state.get("job_spec", {}),
                target_skills=ctx.get("target_skills") or [],
                resume_anchor=ctx.get("resume_anchor"),
                pending_contract_hints=ctx.get("contract_hints"),
                dimension=ctx["dimension"],
                probe_intent=intent,
                runtime_config=state.get("runtime_config") or {},
            )
            ctx["question_fit_profile"] = fit_profile
            ctx["question_fit_profile_artifact"] = fit_profile.as_artifact()
        except Exception as e:  # pragma: no cover - non-critical selection signal
            log.debug("question fit profile build failed: %s", e)
            fit_profile = None

    try:
        selection = select_question_candidates(
            dimension=ctx["dimension"],
            job_level=job_level,
            target_skills=ctx.get("target_skills") or [],
            failure_categories=_failure_categories_from_hints(ctx.get("contract_hints")),
            resume_anchor_text=_resume_anchor_text(ctx.get("resume_anchor")),
            probe_intent=intent,
            difficulty=_question_selector_difficulty(
                state.get("target_difficulty", "medium")
            ),
            qa_history=state.get("qa_history", []),
            fit_profile=fit_profile,
            top_k=3,
            direction_tags=ctx.get("question_direction_tags") or [],
            role_tags=ctx.get("question_role_tags") or [],
            question_selector_mode=mode,
        )
    except Exception as e:  # pragma: no cover - non-critical shadow path
        log.debug("structured question selector failed: %s", e)
        return

    candidates: list[QuestionCandidate] = list(selection.candidates)
    if (
        mode == "structured_primary"
        and candidates
        and _structured_primary_allowed(candidates[0], settings)
    ):
        candidates = [
            candidate.with_injected(candidate.rank == 1)
            for candidate in candidates
        ]
        top = candidates[0]
        ctx["structured_primary_seed_hit"] = True
        ctx["question_seed_block"] = format_question_seed_block(top)
        if fit_profile is not None:
            ctx["candidate_anchor_block"] = format_candidate_anchor_block(
                fit_profile,
                top,
            )
            ctx["candidate_anchor_artifact"] = candidate_anchor_artifact(
                fit_profile,
                top,
            )
        ctx["question_seed_contract_hints"] = build_question_seed_contract_hints(top)
        ctx["contract_hints"] = _merge_contract_hints(
            ctx.get("contract_hints"),
            ctx.get("question_seed_contract_hints"),
        )

    if (
        bool(getattr(settings, "enable_question_reranker_shadow", False))
        and len(candidates) >= 2
    ):
        try:
            rerank_result = rerank_question_candidates(
                candidates=candidates,
                fit_profile=fit_profile,
                question_selector_mode=mode,
                enabled=True,
                timeout_ms=int(getattr(settings, "question_reranker_timeout_ms", 4000)),
            )
            if getattr(rerank_result, "status", "skipped") != "skipped":
                ctx["question_reranker_artifact"] = rerank_result.as_artifact()
                try:
                    record_question_rerank_usage(
                        result=rerank_result,
                        candidates=candidates,
                        session_id=str(state.get("session_id") or ""),
                        turn_idx=int(
                            state.get("formal_turn_idx", state.get("turn_idx", 0)) or 0
                        ),
                        trace_id=state.get("trace_id"),
                        dimension=ctx["dimension"],
                        probe_intent=intent,
                        question_selector_mode=mode,
                    )
                except Exception as e:  # pragma: no cover - observability only
                    log.debug("question rerank usage write failed: %s", e)
        except Exception as e:  # pragma: no cover - shadow-only path
            log.debug("question shadow reranker failed: %s", e)

    ctx["question_candidates"] = candidates
    ctx["question_items"] = [candidate.as_artifact() for candidate in candidates]
    if candidates:
        try:
            record_question_usages(
                candidates=candidates,
                session_id=str(state.get("session_id") or ""),
                turn_idx=int(state.get("formal_turn_idx", state.get("turn_idx", 0)) or 0),
                trace_id=state.get("trace_id"),
                question_selector_mode=mode,
                question_context_key=question_context_key,
                direction_tag=direction_tags[0] if direction_tags else None,
                role_tag=role_tags[0] if role_tags else None,
                job_level=job_level,
                dimension=ctx["dimension"],
            )
        except Exception as e:  # pragma: no cover - observability only
            log.debug("question usage write failed: %s", e)


def _retrieval_block_for_prompt(ctx: dict[str, Any]) -> str:
    if ctx.get("structured_primary_seed_hit"):
        return ""
    return ctx.get("retrieval_block", "")


def _ask_plan_for_trace(
    plan: AskPlan,
    *,
    state: InterviewState,
    runtime_config: dict[str, Any],
) -> dict[str, Any]:
    selected_action = state.get("selected_action") or {}
    return {
        "plan_id": str(plan.get("plan_id") or ""),
        "template": plan.get("template"),
        "complexity": plan.get("complexity"),
        "source": plan.get("source"),
        "resolution_inputs": {
            "selected_action_id": selected_action.get("id"),
            "selected_action_label": selected_action.get("label"),
            "selected_action_plan_template": selected_action.get("plan_template"),
            "pending_plan_template": state.get("pending_plan_template"),
            "ask_planning": bool(runtime_config.get("ask_planning")),
        },
        "steps": [
            {
                "step_id": step.get("step_id"),
                "kind": step.get("kind"),
                "goal": step.get("goal"),
                "success_criteria": step.get("success_criteria"),
                "produced_keys": list(step.get("produced_keys") or []),
                "dependencies": list(step.get("dependencies") or []),
                "optional": bool(step.get("optional")),
            }
            for step in plan.get("steps", [])
        ],
    }


def _prompt_slot_for_trace(
    *,
    prompt_label: str,
    source_key: str,
    text: Any,
    text_limit: int,
    legacy: bool = False,
    empty_reason: str | None = None,
) -> dict[str, Any]:
    raw = text if isinstance(text, str) else ""
    stripped = raw.strip()
    reason = empty_reason
    if reason is None:
        reason = _PROMPT_SLOT_PLACEHOLDER_REASONS.get(stripped)
    if reason is None and not stripped:
        reason = "empty"
    limit = max(0, int(text_limit))
    return {
        "prompt_label": prompt_label,
        "source_key": source_key,
        "injected": bool(stripped) and reason is None,
        "chars": len(raw),
        "truncated": len(raw) > limit,
        "text": raw[:limit],
        "empty_reason": reason if reason is not None else None,
        "legacy": bool(legacy),
    }


def _prompt_slots_for_trace(
    ctx: dict[str, Any],
    *,
    text_limit: int = _PROMPT_SLOT_TEXT_LIMIT,
) -> list[dict[str, Any]]:
    retrieval_text = _retrieval_block_for_prompt(ctx)
    retrieval_empty_reason = (
        "structured_question_seed_hit"
        if ctx.get("structured_primary_seed_hit") and not retrieval_text.strip()
        else None
    )
    slots = [
        (
            "RETRIEVED_KNOWLEDGE",
            "retrieval_block",
            retrieval_text,
            True,
            retrieval_empty_reason,
        ),
        (
            "STRUCTURED_QUESTION_SEED",
            "question_seed_block",
            ctx.get("question_seed_block", ""),
            False,
            None,
        ),
        (
            "CANDIDATE_ANCHOR",
            "candidate_anchor_block",
            ctx.get("candidate_anchor_block", ""),
            False,
            None,
        ),
        (
            "CANDIDATE_RESUME_RAG",
            "resume_rag_block",
            ctx.get("resume_rag_block", ""),
            False,
            None,
        ),
        (
            "SELF_INTRO_RAG",
            "self_intro_rag_block",
            ctx.get("self_intro_rag_block", ""),
            False,
            None,
        ),
        (
            "STRATEGY_MEMORY",
            "strategy_block",
            ctx.get("strategy_block", ""),
            False,
            None,
        ),
        (
            "INTERVIEW_SKILLS",
            "skill_block",
            ctx.get("skill_block", ""),
            False,
            None,
        ),
    ]
    rendered_slots = [
        _prompt_slot_for_trace(
            prompt_label=prompt_label,
            source_key=source_key,
            text=text,
            text_limit=text_limit,
            legacy=legacy,
            empty_reason=empty_reason,
        )
        for prompt_label, source_key, text, legacy, empty_reason in slots
    ]
    history_slots = [
        slot
        for slot in (ctx.get("history_prompt_slots") or [])
        if isinstance(slot, dict)
    ]
    return [*history_slots, *rendered_slots]


def _step_retrieve_candidate_anchors(
    state: InterviewState,
    ctx: dict[str, Any],
) -> None:
    settings = get_settings()
    mode = str(getattr(settings, "resume_rag_mode", "off") or "off")
    ctx["resume_rag_block"] = ""
    ctx["self_intro_rag_block"] = ""
    if mode == "off":
        ctx["candidate_anchor_rag_artifact"] = {"status": "off"}
        return
    sample_rate = getattr(settings, "resume_rag_session_sample_rate", 1.0)
    if not _session_anchor_sampled_in(str(state.get("session_id") or ""), sample_rate):
        ctx["candidate_anchor_rag_artifact"] = {
            "status": mode,
            "skipped": True,
            "fallback_reason": "sampled_out",
            "hits": [],
        }
        return

    resume_status = ((state.get("candidate") or {}).get("resume_vector_status") or {})
    self_intro_status = state.get("self_intro_vector_status") or {}
    result = retrieve_candidate_anchors(
        session_id=str(state.get("session_id") or ""),
        resume_revision_id=_ready_revision(resume_status, "resume_revision_id"),
        self_intro_revision_id=_ready_revision(
            self_intro_status,
            "self_intro_revision_id",
        ),
        dimension=ctx["dimension"],
        seed=(ctx.get("question_items") or [None])[0],
        target_skills=ctx.get("target_skills") or [],
        rule_anchor=ctx.get("resume_anchor"),
        self_intro_profile=state.get("self_intro_profile") or {},
        used_project_names=_used_project_names(state),
    )
    if mode == "primary":
        ctx["resume_rag_block"] = result.resume_block
        ctx["self_intro_rag_block"] = result.self_intro_block
    ctx["candidate_anchor_rag_artifact"] = result.as_artifact(mode=mode)


def _session_anchor_sampled_in(session_id: str, sample_rate: float) -> bool:
    try:
        rate = float(sample_rate)
    except (TypeError, ValueError):
        rate = 1.0
    rate = max(0.0, min(1.0, rate))
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    key = (session_id or "unknown-session").encode("utf-8")
    bucket = int(hashlib.sha1(key).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < rate


def _ready_revision(status: dict[str, Any], key: str) -> str | None:
    if not isinstance(status, dict) or status.get("status") != "ready":
        return None
    revision = str(status.get(key) or "").strip()
    return revision or None


def _state_with_refreshed_resume_vector_status(
    state: InterviewState,
) -> tuple[InterviewState, dict[str, Any] | None]:
    candidate = state.get("candidate") or {}
    if not isinstance(candidate, dict):
        return state, None
    status = candidate.get("resume_vector_status") or {}
    if not isinstance(status, dict):
        return state, None
    if status.get("status") not in {"pending_background", "pending_node"}:
        return state, None
    source_id = (
        candidate.get("resume_source_id")
        or status.get("resume_source_id")
        or status.get("source_artifact_id")
    )
    if not source_id:
        return state, None
    latest = refresh_resume_vector_status(
        session_id=str(state.get("session_id") or ""),
        resume_source_id=str(source_id),
        parsed=candidate.get("resume_parsed")
        if isinstance(candidate.get("resume_parsed"), dict)
        else None,
        embedding_override=_runtime_embedding_override(),
        current_status=status,
    )
    if latest.get("wait_timeout_ms") == 0:
        latest.pop("wait_timed_out", None)
        latest.pop("wait_timeout_ms", None)
    refreshed = {**candidate, "resume_vector_status": latest}
    return {**state, "candidate": refreshed}, refreshed  # type: ignore[return-value]


def _runtime_embedding_override() -> dict[str, Any] | None:
    try:
        from app.services.session_manager import get_llm_override

        llm_config = get_llm_override()
    except Exception:
        return None
    if not isinstance(llm_config, dict):
        return None
    override = llm_config.get("embedding_override")
    return override if isinstance(override, dict) else None


def _used_project_names(state: InterviewState) -> list[str]:
    candidate = state.get("candidate") or {}
    parsed = candidate.get("resume_parsed") if isinstance(candidate, dict) else {}
    projects = (parsed or {}).get("projects") if isinstance(parsed, dict) else []
    focus_areas = (parsed or {}).get("focus_areas") if isinstance(parsed, dict) else []
    projects = projects if isinstance(projects, list) else []
    focus_areas = focus_areas if isinstance(focus_areas, list) else []
    projects_by_id = {
        str(project.get("id")): project
        for project in projects
        if isinstance(project, dict) and project.get("id")
    }
    focus_project_id = {
        str(focus.get("id")): str(focus.get("project_id") or "")
        for focus in focus_areas
        if isinstance(focus, dict) and focus.get("id")
    }
    used: list[str] = []
    for turn in state.get("qa_history") or []:
        if not isinstance(turn, dict):
            continue
        anchor = turn.get("resume_anchor") if isinstance(turn.get("resume_anchor"), dict) else {}
        project_name = str(anchor.get("project_name") or "").strip()
        project_id = str(
            anchor.get("project_id")
            or turn.get("project_id")
            or focus_project_id.get(str(anchor.get("focus_id") or turn.get("focus_id") or ""), "")
        ).strip()
        if not project_name and project_id:
            project = projects_by_id.get(project_id) or {}
            project_name = str(project.get("name") or "").strip()
        if project_name:
            used.append(project_name)
    return used


def _step_draft_question(state: InterviewState, ctx: dict[str, Any]) -> None:
    runtime_config = state.get("runtime_config") or {}
    refine_mode = bool(state.get("refine_mode")) or bool(
        (ctx.get("contract_hints") or {}).get("refine_mode")
    )
    question_payload = generate_question(
        dimension=ctx["dimension"],
        action=state.get("selected_action") or {},
        job_spec=state.get("job_spec", {}),
        candidate=state.get("candidate", {}),
        recent_qa=state.get("qa_history", []),
        retrieval_block=_retrieval_block_for_prompt(ctx),
        question_seed_block=ctx.get("question_seed_block", ""),
        candidate_anchor_block=ctx.get("candidate_anchor_block", ""),
        resume_rag_block=ctx.get("resume_rag_block", ""),
        self_intro_rag_block=ctx.get("self_intro_rag_block", ""),
        strategy_block=ctx.get("strategy_block", "(no relevant strategy memories)"),
        skill_block=ctx.get("skill_block", "(no relevant interview skills)"),
        avoid_patterns_block=ctx.get(
            "avoid_patterns",
            "(no historical shallow patterns on this dimension)",
        ),
        resume_anchor=ctx.get("resume_anchor"),
        self_intro_profile=state.get("self_intro_profile") or {},
        qa_summary=state.get("qa_summary", ""),
        refine_mode=refine_mode,
        contract_hints=ctx.get("contract_hints"),
        target_difficulty=state.get("target_difficulty", "medium"),
        target_skills=ctx.get("target_skills") or [],
        probe_intent=ctx.get("probe_intent"),
        context_flags=state.get("context_flags") or {},
        history_section_override=ctx.get("history_section"),
    )
    # ``runtime_config.iterative_contract`` is the legacy on/off switch.
    # The plan executor supersedes it, but we note it on the payload
    # so downstream audits can see which path was taken.
    question_payload["iterative_contract_legacy_flag"] = bool(
        runtime_config.get("iterative_contract", False)
    )
    ctx["question_payload"] = question_payload
    ctx["proposed_contract"] = question_payload.get("proposed_contract", {})


def _step_negotiate_contract(state: InterviewState, ctx: dict[str, Any]) -> None:
    job_level = (state.get("job_spec") or {}).get("level", "mid")
    question = (ctx.get("question_payload") or {}).get("question", "")
    contract = negotiate_contract_via_evaluator(
        dimension=ctx["dimension"],
        job_level=job_level,
        question=question,
        proposed_contract=ctx.get("proposed_contract") or {},
        contract_hints=ctx.get("contract_hints"),
        target_difficulty=state.get("target_difficulty", "medium"),
    )
    ctx["contract"] = contract


def _step_challenge_with_reference(state: InterviewState, ctx: dict[str, Any]) -> None:
    """Attach a short reference scenario to the question.

    Kept intentionally deterministic in P0 - the challenge text is
    stitched from retrieval_block's top line if present. An LLM-based
    variant can be added later by swapping this helper out.
    """
    payload = ctx.get("question_payload") or {}
    retrieval_block = (
        ctx.get("resume_rag_block")
        or ctx.get("self_intro_rag_block")
        or _retrieval_block_for_prompt(ctx)
        or ""
    )
    first_line = next(
        (line for line in retrieval_block.splitlines() if line.strip()),
        "",
    )
    if first_line:
        payload["challenge_context"] = first_line.strip()[:240]
    ctx["question_payload"] = payload


def _step_guardrail_check(state: InterviewState, ctx: dict[str, Any]) -> None:
    payload = ctx.get("question_payload") or {}
    verdict = check_question(
        payload.get("question", ""),
        runtime_config=state.get("runtime_config"),
    )
    dimension = ctx["dimension"]
    if not verdict.allowed:
        log.warning(
            "security guardrail blocked question: %s (%s)",
            verdict.reason,
            payload.get("question"),
        )
        payload["question"] = (
            f"请结合一个真实项目，说明它如何体现你的{_display_dimension(dimension)}能力。"
        )
        payload["safety_fallback"] = verdict.reason
        record_question_fallback("safety")
    ctx["question_payload"] = payload


_STEP_DISPATCH = {
    "retrieve_rag": _step_retrieve_rag,
    "retrieve_strategy": _step_retrieve_strategy,
    "retrieve_skills": _step_retrieve_skills,
    "retrieve_candidate_anchors": _step_retrieve_candidate_anchors,
    "draft_question": _step_draft_question,
    "negotiate_contract": _step_negotiate_contract,
    "challenge_with_reference": _step_challenge_with_reference,
    "guardrail_check": _step_guardrail_check,
}


def _run_plan(plan: AskPlan, state: InterviewState, ctx: dict[str, Any]) -> None:
    for step in plan.get("steps", []):
        kind = step.get("kind")
        fn = _STEP_DISPATCH.get(kind or "")
        if fn is None:
            log.warning("ask_plan: unknown step kind=%s, skipping", kind)
            continue
        try:
            fn(state, ctx)
        except Exception as e:  # pragma: no cover - defensive
            if step.get("optional"):
                log.info(
                    "ask_plan: optional step %s failed (%s); continuing",
                    kind,
                    e,
                )
                continue
            log.exception("ask_plan: step %s failed", kind)
            raise


def _retrieve_skills_plan_step(dependencies: list[int]) -> dict[str, Any]:
    return {
        "step_id": 0,
        "kind": "retrieve_skills",
        "goal": "Surface playbook cards matching the current turn before drafting.",
        "success_criteria": (
            "skill_block is set (possibly the no-match placeholder)."
        ),
        "produced_keys": ["skill_block", "skill_artifact"],
        "dependencies": list(dependencies),
        "optional": True,
    }


def _ensure_retrieve_skills_step(plan: AskPlan) -> AskPlan:
    steps = [dict(step) for step in plan.get("steps", [])]
    if any(step.get("kind") == "retrieve_skills" for step in steps):
        return plan

    draft_idx = next(
        (
            idx
            for idx, step in enumerate(steps)
            if step.get("kind") == "draft_question"
        ),
        None,
    )
    if draft_idx is None:
        return plan

    insert_idx = draft_idx
    for idx, step in enumerate(steps[:draft_idx]):
        if step.get("kind") == "retrieve_candidate_anchors":
            insert_idx = idx
            break

    dependencies = [
        int(step.get("step_id") or idx + 1)
        for idx, step in enumerate(steps[:insert_idx])
    ]
    steps.insert(insert_idx, _retrieve_skills_plan_step(dependencies))
    return _renumber_plan_steps(plan, steps)


def _renumber_plan_steps(plan: AskPlan, steps: list[dict[str, Any]]) -> AskPlan:
    old_to_new: dict[int, int] = {}
    for new_id, step in enumerate(steps, start=1):
        try:
            old_id = int(step.get("step_id", new_id))
        except (TypeError, ValueError):
            old_id = new_id
        if old_id > 0:
            old_to_new[old_id] = new_id

    normalised: list[dict[str, Any]] = []
    skill_step_id: int | None = None
    for new_id, step in enumerate(steps, start=1):
        next_step = dict(step)
        next_step["step_id"] = new_id
        dependencies: list[int] = []
        for dep in step.get("dependencies") or []:
            try:
                dep_id = int(dep)
            except (TypeError, ValueError):
                continue
            mapped = old_to_new.get(dep_id)
            if mapped is not None and mapped < new_id and mapped not in dependencies:
                dependencies.append(mapped)
        next_step["dependencies"] = dependencies
        if next_step.get("kind") == "retrieve_skills":
            skill_step_id = new_id
        normalised.append(next_step)

    if skill_step_id is not None:
        for step in normalised:
            if step.get("kind") != "draft_question":
                continue
            draft_id = int(step.get("step_id", 0) or 0)
            dependencies = list(step.get("dependencies") or [])
            if skill_step_id < draft_id and skill_step_id not in dependencies:
                dependencies.append(skill_step_id)
                step["dependencies"] = sorted(dependencies)
            break

    return {
        **plan,
        "steps": normalised,  # type: ignore[typeddict-item]
    }


def _has_coverage_pressure(
    *,
    turn_budget_remaining: int | None,
    uncovered_dimensions: int,
) -> bool:
    """Return True when the remaining formal turns cannot cover all open dims."""
    if turn_budget_remaining is None:
        return False
    return (
        int(turn_budget_remaining) <= int(uncovered_dimensions)
        and uncovered_dimensions > 1
    )


_TECH_SECOND_PASS_PROBES = (
    "debugging_probe",
    "performance_probe",
    "metric_probe",
    "architecture_challenge",
)
_BUSINESS_SECOND_PASS_PROBES = (
    "case_study_probe",
    "stakeholder_pushback_probe",
    "process_design_probe",
)
_BUSINESS_DIMENSIONS = {
    "communication",
    "customer_discovery",
    "objection_handling",
    "negotiation",
    "pipeline_management",
    "stakeholder_management",
    "customer_empathy",
    "service_orientation",
}


def _anchor_key_of_turn(turn: dict[str, Any]) -> str:
    anchor = turn.get("resume_anchor")
    if not isinstance(anchor, dict):
        return ""
    return str(anchor.get("anchor_key") or anchor.get("focus_id") or "").strip()


def _used_probe_intents_for_anchor(
    qa_history: list[dict[str, Any]],
    anchor_key: str,
) -> set[str]:
    used: set[str] = set()
    if not anchor_key:
        return used
    for turn in qa_history:
        if _anchor_key_of_turn(turn) != anchor_key:
            continue
        probe = turn.get("probe_intent")
        if not probe and isinstance(turn.get("current_question"), dict):
            probe = turn["current_question"].get("probe_intent")
        if probe:
            used.add(str(probe))
    return used


def _rotate_second_pass_probe_intent(
    *,
    probe_intent: str | None,
    dimension: str,
    scheduler: dict[str, Any] | None,
    qa_history: list[dict[str, Any]],
) -> str | None:
    scheduler = scheduler or {}
    try:
        anchor_attempt = int(scheduler.get("anchor_attempt") or 0)
    except (TypeError, ValueError):
        anchor_attempt = 0
    if anchor_attempt <= 1:
        return probe_intent

    anchor_key = str(scheduler.get("anchor_key") or "").strip()
    used = _used_probe_intents_for_anchor(qa_history, anchor_key)
    candidates = (
        _BUSINESS_SECOND_PASS_PROBES
        if dimension in _BUSINESS_DIMENSIONS
        else _TECH_SECOND_PASS_PROBES
    )
    for candidate in candidates:
        if candidate != probe_intent and candidate not in used:
            return candidate
    return probe_intent


def _normalise_question_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalise_question_skill(value: str) -> str:
    compact = re.sub(r"[^a-z0-9+#.]+", "", value.strip().lower())
    aliases = {
        "springsecurity": "springsecurity",
        "springboot": "springboot",
    }
    return aliases.get(compact, compact)


def _generic_tradeoff_signature(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip().lower()
    required = ("约束", "备选方案", "最终取舍", "故障复盘", "怎么演进")
    if not text or not all(token in text for token in required):
        return None

    project_match = re.search(r"请结合「([^」]+)」", text)
    skills_match = re.search(r"中与「([^」]+)」相关", text)
    if not project_match or not skills_match:
        return None

    skills = {
        normalised
        for raw in re.split(r"[、,，/ ]+", skills_match.group(1))
        if (normalised := _normalise_question_skill(raw))
    }
    return {"project": project_match.group(1), "skills": skills}


def _is_near_duplicate_question(
    question: Any,
    previous_questions: set[str],
) -> bool:
    current = _generic_tradeoff_signature(question)
    if not current:
        return False
    current_skills = current["skills"]
    for previous in previous_questions:
        prior = _generic_tradeoff_signature(previous)
        if not prior or prior["project"] != current["project"]:
            continue
        prior_skills = prior["skills"]
        if not current_skills or not prior_skills:
            continue
        overlap = current_skills & prior_skills
        if len(overlap) >= max(1, min(len(current_skills), len(prior_skills)) - 1):
            return True
    return False


def _previous_question_texts(qa_history: list[dict[str, Any]]) -> set[str]:
    texts: set[str] = set()
    for turn in qa_history:
        question = turn.get("question")
        if not question and isinstance(turn.get("current_question"), dict):
            question = turn["current_question"].get("question")
        normalised = _normalise_question_text(question)
        if normalised:
            texts.add(normalised)
    return texts


def _display_anchor(anchor: dict[str, Any] | None) -> str:
    if not isinstance(anchor, dict):
        return "你的一个简历项目"
    return (
        str(anchor.get("project_name") or anchor.get("label") or "").strip()
        or "你的一个简历项目"
    )


def _display_skills(skills: list[Any] | None) -> str:
    items = [str(item).strip() for item in (skills or []) if str(item).strip()]
    if not items:
        return "关键设计选择"
    return "、".join(items[:3])


def _display_dimension(dimension: str) -> str:
    labels = {
        "technical_depth": "技术深度",
        "system_design": "系统设计",
        "problem_solving": "问题解决",
        "coding_quality": "代码质量",
        "project_experience": "项目经验",
        "communication": "沟通表达",
        "product_sense": "产品理解",
        "data_analysis": "数据分析",
        "customer_discovery": "客户理解",
        "objection_handling": "异议处理",
        "negotiation": "商务谈判",
        "pipeline_management": "过程推进",
    }
    return labels.get(dimension, dimension.replace("_", " "))


def _strategy_memory_ref(entry: Any) -> dict[str, Any]:
    ref = {
        "id": getattr(entry, "id", None),
        "slug": getattr(entry, "slug", None),
        "memory_key": getattr(entry, "memory_key", None),
        "name": getattr(entry, "name", ""),
        "description": getattr(entry, "description", ""),
        "display_name_zh": getattr(entry, "display_name_zh", ""),
        "display_description_zh": getattr(entry, "display_description_zh", ""),
        "source": getattr(entry, "source", ""),
        "status": getattr(entry, "status", ""),
        "promotion_stage": getattr(entry, "promotion_stage", ""),
        "confidence": float(getattr(entry, "confidence", 0.0) or 0.0),
        "support_count": int(getattr(entry, "support_count", 0) or 0),
    }
    ranking_reason = getattr(entry, "ranking_reason", {}) or {}
    if ranking_reason:
        ref["shadow_rank"] = getattr(entry, "shadow_rank", None)
        ref["ranking_score"] = float(getattr(entry, "ranking_score", 0.0) or 0.0)
        ref["ranking_reason"] = dict(ranking_reason)
    if not any(ref.get(key) for key in ("id", "slug", "memory_key", "name")):
        return {}
    return ref


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _looks_like_english_question(text: Any) -> bool:
    value = str(text or "").strip()
    if not value or _has_cjk(value):
        return False
    alpha_count = sum(1 for char in value if char.isascii() and char.isalpha())
    return alpha_count >= 20 and " " in value


def _rewrite_non_chinese_question(
    payload: dict[str, Any],
    *,
    ctx: dict[str, Any],
    dimension: str,
) -> None:
    if not _looks_like_english_question(payload.get("question")):
        return

    original = str(payload.get("question") or "")
    anchor = _display_anchor(ctx.get("resume_anchor"))
    skills = _display_skills(ctx.get("target_skills"))
    dimension_label = _display_dimension(dimension)
    payload["question"] = (
        f"请结合{anchor}，围绕{dimension_label}和{skills}展开说明："
        "当时要解决的核心问题是什么，你采取了哪些具体做法，做过哪些权衡？"
        "如果结果不符合预期，你会如何校验并兜底？"
    )
    payload["language_fallback"] = True
    payload.setdefault("original_question", original)
    record_question_fallback("language")


def _rewrite_duplicate_question(
    payload: dict[str, Any],
    *,
    ctx: dict[str, Any],
    dimension: str,
) -> None:
    previous = _previous_question_texts(ctx.get("qa_history") or [])
    question = _normalise_question_text(payload.get("question"))
    if not question or (
        question not in previous
        and not _is_near_duplicate_question(payload.get("question"), previous)
    ):
        return

    original = str(payload.get("question") or "")
    anchor = _display_anchor(ctx.get("resume_anchor"))
    skills = _display_skills(ctx.get("target_skills"))
    dimension_label = _display_dimension(dimension)
    payload["question"] = (
        f"请换一个角度结合{anchor}，围绕{dimension_label}和{skills}展开说明："
        "当时你解决的具体问题是什么，比较过哪些方案，为什么最终选择这个方案？"
    )
    payload["duplicate_rewrite"] = True
    payload["original_question"] = original
    record_question_fallback("duplicate")


def _lock_question_dimension(payload: dict[str, Any], dimension: str) -> None:
    model_dimension = payload.get("dimension")
    if model_dimension and model_dimension != dimension:
        payload.setdefault("model_dimension", model_dimension)
    payload["dimension"] = dimension


def _fallback_contract_for_rewritten_question(
    *,
    dimension: str,
    target_skills: list[Any],
    target_difficulty: str,
) -> PlanContract:
    focus = _display_skills(target_skills)
    if focus == "关键设计选择":
        focus = _display_dimension(dimension)
    return {
        "must_cover": [focus, "具体例子", "方案取舍"],
        "acceptable_if_missing": [],
        "acceptance_checks": [
            f"回答围绕{focus}展开。",
            "回答包含候选人亲身经历中的具体场景。",
            "回答说明至少一个方案取舍或失败处理。",
        ],
        "minimum_bar": "至少给出一个真实项目场景，并说明做法与取舍。",
        "review_focus": ["真实经历", "取舍清晰度", "结果或复盘"],
        "bar_level": difficulty_to_bar_level(target_difficulty),  # type: ignore[arg-type]
        "signed_by": ["generator"],
    }


def _finalise_contract(
    plan: AskPlan,
    ctx: dict[str, Any],
) -> PlanContract:
    """Return whichever contract the plan produced.

    Adaptive / deep_probe plans run ``negotiate_contract`` which
    sets ``ctx['contract']``; the simple plan does not, so we wrap
    the generator's proposal as a generator-only signed contract.
    """
    contract = ctx.get("contract")
    if contract:
        return contract

    proposed = ctx.get("proposed_contract") or {}
    return {
        "must_cover": proposed.get("must_cover") or ["depth", "clarity"],
        "acceptable_if_missing": proposed.get("acceptable_if_missing", []),
        "acceptance_checks": proposed.get("acceptance_checks")
        or [
            f"Answer directly addresses {ctx['dimension'].replace('_', ' ')}.",
            "Answer provides at least one concrete example or mechanism.",
        ],
        "minimum_bar": proposed.get(
            "minimum_bar",
            "Covers the core concept with one concrete example.",
        ),
        "review_focus": proposed.get("review_focus", []),
        "bar_level": proposed.get("bar_level", "standard"),
        "signed_by": ["generator"],
    }


def _strings_for_trace(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalise_contract_coverage_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _contract_coverage_terms(value: str) -> set[str]:
    text = str(value or "").strip().lower()
    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", text)
        if len(token) >= 2
    }
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        terms.update(run[idx : idx + 2] for idx in range(len(run) - 1))
    return terms


def _contract_item_is_covered(
    item: str,
    *,
    checks_text: str,
    check_terms: set[str],
) -> bool:
    item_norm = _normalise_contract_coverage_text(item)
    checks_norm = _normalise_contract_coverage_text(checks_text)
    if not item_norm:
        return True
    if item_norm in checks_norm or checks_norm in item_norm:
        return True

    item_terms = _contract_coverage_terms(item)
    if not item_terms or not check_terms:
        return False
    overlap = item_terms & check_terms
    if len(overlap) < 2:
        return False
    return len(overlap) / min(len(item_terms), 10) >= 0.2


def _contract_diagnostics_for_trace(
    contract: dict[str, Any] | None,
    *,
    proposed_contract: dict[str, Any] | None,
    plan: AskPlan | dict[str, Any] | None,
    target_difficulty: str | None,
    rewrite_fallback: bool,
) -> dict[str, Any]:
    """Return trace-only contract quality diagnostics without mutating inputs."""

    final_contract = contract or {}
    proposed = proposed_contract or {}
    signed_by = set(_strings_for_trace(final_contract.get("signed_by")))
    must_cover = _strings_for_trace(final_contract.get("must_cover"))
    acceptance_checks = _strings_for_trace(final_contract.get("acceptance_checks"))
    bar_level = str(final_contract.get("bar_level") or "").strip() or None
    expected_bar_level = _EXPECTED_CONTRACT_BAR_BY_DIFFICULTY.get(
        str(target_difficulty or "").strip().lower(),
    )

    if rewrite_fallback:
        source = "rewrite_fallback"
    elif "evaluator" in signed_by:
        source = "evaluator_signed"
    elif "generator" in signed_by:
        source = "generator_only"
    elif proposed:
        source = "generator_only"
    else:
        source = "fallback"

    if "evaluator" in signed_by:
        signed_status = "evaluator_signed"
    elif "generator" in signed_by:
        signed_status = "generator_only"
    else:
        signed_status = "unsigned"

    checks_text = "\n".join(acceptance_checks)
    check_terms = _contract_coverage_terms(checks_text)
    uncovered_must_cover_items = [
        item
        for item in must_cover
        if not _contract_item_is_covered(
            item,
            checks_text=checks_text,
            check_terms=check_terms,
        )
    ]
    generic_items = [
        item for item in must_cover if item.strip().lower() in _GENERIC_CONTRACT_ITEMS
    ]
    bar_level_match = (
        None
        if expected_bar_level is None or bar_level is None
        else bar_level == expected_bar_level
    )

    warnings: list[str] = []
    if rewrite_fallback:
        warnings.append("rewrite_fallback")
    if signed_status != "evaluator_signed":
        warnings.append("not_evaluator_signed")
    if not must_cover:
        warnings.append("empty_must_cover")
    if not acceptance_checks:
        warnings.append("empty_acceptance_checks")
    if uncovered_must_cover_items:
        warnings.append("must_cover_without_acceptance_check")
    if bar_level_match is False:
        warnings.append("bar_level_mismatch")
    if generic_items:
        warnings.append("generic_contract_item")

    return {
        "source": source,
        "signed_status": signed_status,
        "must_cover_count": len(must_cover),
        "acceptance_check_count": len(acceptance_checks),
        "bar_level": bar_level,
        "expected_bar_level": expected_bar_level,
        "bar_level_match": bar_level_match,
        "uncovered_must_cover_items": uncovered_must_cover_items,
        "generic_items": generic_items,
        "warnings": warnings,
    }


def _resolve_plan(
    *,
    selected_action: dict[str, Any] | None,
    refine_mode: bool,
    pending_plan_template: PlanTemplate | None,
    runtime_config: dict[str, Any],
    dimension: str,
    job_level: str,
    contract_hints: dict[str, Any] | None,
    turn_budget_remaining: int | None = None,
    uncovered_dimensions: int | None = None,
) -> AskPlan:
    """Pick a plan, optionally delegating to the LLM planner.

    Resolution order:

    1. If ``runtime_config.ask_planning`` is True AND the runtime is
       not in stub mode, try :func:`build_llm_ask_plan`. The planner
       is grounded (allowed step kinds are fixed, guardrail must be
       last, at most 2 edits over the base template) and degrades to
       ``None`` on any parse / schema failure, in which case we fall
       through to (2).
    2. :func:`resolve_ask_plan` - deterministic template mapping that
       has always been the P0 default.

    Stub mode is short-circuited so the existing unit tests (which
    run against a fixture LLM and assume the bandit-arm-to-template
    mapping) stay byte-identical.
    """
    if runtime_config.get("ask_planning"):
        try:
            stub = get_settings().use_stub_llm
        except Exception:  # pragma: no cover - defensive
            stub = True
        if not stub:
            llm_plan = build_llm_ask_plan(
                dimension=dimension,
                job_level=job_level,
                selected_action=selected_action,
                refine_mode=refine_mode,
                pending_plan_template=pending_plan_template,
                contract_hints=contract_hints,
            )
            if llm_plan is not None:
                log.info(
                    "ask_plan: using llm-authored plan (template=%s, %d steps)",
                    llm_plan.get("template"),
                    len(llm_plan.get("steps", [])),
                )
                return _ensure_retrieve_skills_step(llm_plan)
            log.info("ask_plan: llm planner returned None; falling back to default")

    plan = resolve_ask_plan(
        selected_action=selected_action,
        refine_mode=refine_mode,
        pending_plan_template=pending_plan_template,
        runtime_config=runtime_config,
        turn_budget_remaining=turn_budget_remaining,
        uncovered_dimensions=uncovered_dimensions,
        job_level=job_level,
    )
    return _ensure_retrieve_skills_step(plan)


def ask_question_node(state: InterviewState) -> dict[str, Any]:
    node_started_at = time.perf_counter()
    state, refreshed_candidate = _state_with_refreshed_resume_vector_status(state)
    runtime_config = state.get("runtime_config") or {}
    dimension = (
        state.get("current_dimension")
        or (state.get("dimensions") or ["general"])[0]
    )
    job_level = (state.get("job_spec") or {}).get("level", "mid")
    contract_hints = state.get("pending_contract_hints") or {}

    dims = state.get("dimensions", [])
    dim_status = state.get("dimension_status", {})
    uncovered = sum(
        1 for d in dims if dim_status.get(d) in {None, "pending", "active"}
    )
    plan = _resolve_plan(
        selected_action=state.get("selected_action"),
        refine_mode=bool(state.get("refine_mode")),
        pending_plan_template=state.get("pending_plan_template"),
        runtime_config=runtime_config,
        dimension=dimension,
        job_level=job_level,
        contract_hints=contract_hints,
        turn_budget_remaining=state.get("turn_budget_remaining"),
        uncovered_dimensions=uncovered,
    )
    anchor_selection = select_resume_anchor_with_schedule(
        candidate=state.get("candidate", {}),
        job_spec=state.get("job_spec", {}),
        dimension=dimension,
        qa_history=state.get("qa_history", []),
        turn_idx=state.get("formal_turn_idx", state.get("turn_idx", 0)),
        self_intro_profile=state.get("self_intro_profile") or {},
        interview_depth=str(runtime_config.get("interview_depth") or "standard"),
        focus_dimensions=list(state.get("focus_dimensions") or []),
    )
    ctx: dict[str, Any] = {
        "dimension": dimension,
        "qa_history": state.get("qa_history", []),
        "resume_anchor": anchor_selection.get("resume_anchor"),
        "anchor_scheduler": anchor_selection.get("scheduler") or {},
        "retrieval_block": "",
        "strategy_block": "(no relevant strategy memories)",
        "skill_block": "(no relevant interview skills)",
        "avoid_patterns": "(no historical shallow patterns on this dimension)",
        "strategy_memory_refs": [],
        "question_payload": {},
        "proposed_contract": {},
        "contract": None,
        "contract_hints": contract_hints,
    }
    history_context = build_history_context(
        qa_history=state.get("qa_history", []),
        current_dimension=dimension,
    )
    ctx["history_context"] = history_context
    ctx["history_section"] = history_context.get("history_section", "")
    ctx["history_selector_summary"] = history_context.get("selector_summary", "")
    ctx["history_prompt_slots"] = history_context.get("prompt_slots", [])
    skill_focus = select_target_skills(
        job_spec=state.get("job_spec", {}),
        resume_anchor=ctx.get("resume_anchor"),
        self_intro_profile=state.get("self_intro_profile") or {},
        qa_history=state.get("qa_history", []),
        current_dimension=dimension,
        selected_action=state.get("selected_action") or {},
    )
    ctx["skill_focus"] = skill_focus
    ctx["target_skills"] = skill_focus.get("target_skills") or []

    direction = (state.get("job_spec") or {}).get("interview_direction")
    probe_intent = resolve_probe_intent(
        direction=direction,
        dimension=dimension,
        job_level=job_level,
        failure_category=(contract_hints or {}).get("failure_category"),
        failure_reason=(contract_hints or {}).get("failure_reason"),
        evaluator_hint=(contract_hints or {}).get("probe_intent"),
        coverage_closeout=_has_coverage_pressure(
            turn_budget_remaining=state.get("turn_budget_remaining"),
            uncovered_dimensions=uncovered,
        ),
    )
    probe_intent = _rotate_second_pass_probe_intent(
        probe_intent=probe_intent,
        dimension=dimension,
        scheduler=ctx.get("anchor_scheduler"),
        qa_history=state.get("qa_history", []),
    )
    ctx["probe_intent"] = probe_intent

    _step_select_structured_question(state, ctx, probe_intent=probe_intent)
    _run_plan(plan, state, ctx)

    question_payload: dict[str, Any] = ctx.get("question_payload") or {}
    if probe_intent:
        question_payload["probe_intent"] = probe_intent
    _lock_question_dimension(question_payload, dimension)
    _rewrite_duplicate_question(question_payload, ctx=ctx, dimension=dimension)
    _rewrite_non_chinese_question(question_payload, ctx=ctx, dimension=dimension)
    question_payload.setdefault("question_type", "technical")
    question_payload.setdefault(
        "formal_turn_idx",
        state.get("formal_turn_idx", state.get("turn_idx", 0)),
    )
    if ctx.get("resume_anchor"):
        question_payload.setdefault("resume_anchor", ctx["resume_anchor"])
    question_payload["strategy_memory_refs"] = list(
        ctx.get("strategy_memory_refs") or []
    )
    question_payload["target_skills"] = list(ctx.get("target_skills") or [])
    question_payload["skill_focus"] = ctx.get("skill_focus") or {}
    question_basis = build_replay_question_basis(
        dimension=dimension,
        resume_anchor=ctx.get("resume_anchor"),
        target_skills=ctx.get("target_skills") or [],
        skill_focus=ctx.get("skill_focus") or {},
        job_spec=state.get("job_spec") or {},
        refine_mode=bool(state.get("refine_mode")),
        contract_hints=contract_hints,
    )
    if question_basis is not None:
        question_payload["question_basis"] = question_basis
    selection_artifacts = _build_selection_artifacts(ctx)
    question_payload["selection_artifacts"] = selection_artifacts
    contract = _finalise_contract(plan, ctx)
    question_payload["contract"] = contract
    # Rubric_points is kept for backwards compatibility: evaluator_node
    # still tolerates the old shape when the new contract path is off.
    question_payload.setdefault(
        "rubric_points", list(contract.get("must_cover", [])),
    )
    rewrite_contract_fallback = False
    if question_payload.get("duplicate_rewrite") or question_payload.get("language_fallback"):
        rewrite_contract_fallback = True
        contract = _fallback_contract_for_rewritten_question(
            dimension=dimension,
            target_skills=ctx.get("target_skills") or [],
            target_difficulty=state.get("target_difficulty", "medium"),
        )
        question_payload["contract"] = contract
        question_payload["rubric_points"] = list(contract.get("must_cover", []))

    contract_diagnostics = _contract_diagnostics_for_trace(
        contract,
        proposed_contract=ctx.get("proposed_contract") or {},
        plan=plan,
        target_difficulty=state.get("target_difficulty", "medium"),
        rewrite_fallback=rewrite_contract_fallback,
    )

    if "evaluator" not in (contract.get("signed_by") or []):
        record_question_fallback("contract_unsigned")

    log.info(
        "ask_question turn=%d dim=%s plan=%s signed_by=%s",
        state.get("turn_idx", 0),
        dimension,
        plan.get("template"),
        contract.get("signed_by"),
    )

    update = {
        "current_question": question_payload,
        "current_ask_plan": plan,
        "current_contract": contract,
        "current_skill_focus": ctx.get("skill_focus") or {},
        "qa_summary_projection": (ctx.get("history_context") or {}).get(
            "projection",
            {},
        ),
        "qa_summary_projection_through_turn": (
            (ctx.get("history_context") or {})
            .get("projection", {})
            .get("source_last_turn_idx", -1)
        ),
        # Consume both forward-carried hints now that the plan has
        # used them. Clearing here (rather than in director_sample)
        # guarantees ``ask_question_node`` observes them for exactly
        # one cycle, which is the contract refine_followup_node relies on.
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "messages": [
            {
                "role": "assistant",
                "turn_idx": state.get("turn_idx", 0),
                "kind": "question",
                "content": question_payload.get("question", ""),
            }
        ],
    }
    if refreshed_candidate is not None:
        update["candidate"] = refreshed_candidate
    try:
        get_tracer().trace_node_event(
            {**state, **update},
            node="ask_question",
            payload={
                "plan_template": plan.get("template"),
                "dimension": dimension,
                "signed_by": contract.get("signed_by"),
                "contract_must_cover_count": len(contract.get("must_cover") or []),
                "contract_acceptance_check_count": len(
                    contract.get("acceptance_checks") or []
                ),
                "contract_bar_level": contract.get("bar_level"),
                "contract": contract,
                "contract_diagnostics": contract_diagnostics,
                "target_skills": ctx.get("target_skills") or [],
                "skill_focus": ctx.get("skill_focus") or {},
                "strategy_memory_refs": ctx.get("strategy_memory_refs") or [],
                "selection_artifacts": selection_artifacts,
                "ask_plan": _ask_plan_for_trace(
                    plan,
                    state=state,
                    runtime_config=runtime_config,
                ),
                "history_context": ctx.get("history_context") or {},
                "qa_summary_projection": update.get("qa_summary_projection") or {},
                "history_prompt_slots": ctx.get("history_prompt_slots") or [],
                "prompt_slots": _prompt_slots_for_trace(ctx),
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("ask_question tracer side-channel failed: %s", e)
    return update
