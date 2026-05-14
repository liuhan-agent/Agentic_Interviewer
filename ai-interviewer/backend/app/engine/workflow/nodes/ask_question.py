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

import time
from typing import Any

from app.core.logging import get_logger
from app.core.metrics import record_question_fallback
from app.core.settings import get_settings
from app.core.tracer import get_tracer
from app.engine.agents.contract import negotiate_contract_via_evaluator
from app.engine.agents.generator import generate_question
from app.engine.agents.security import check_question
from app.engine.rag.retriever import retrieve_for_question
from app.engine.resume_plan import select_resume_anchor
from app.engine.workflow.difficulty_adapter import difficulty_to_bar_level
from app.engine.workflow.plans import build_llm_ask_plan, resolve_ask_plan
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

log = get_logger(__name__)


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
    # on the keyword-filtered top-N for both memory layers. Pass the
    # same flag through so skill + strategy retrieval stay symmetric.
    use_llm_selector = bool(
        getattr(settings, "enable_llm_memory_selector", False)
    )
    recent_qa_summary = str(state.get("qa_summary") or "")

    strategies = retrieve_strategies(
        dimension=ctx["dimension"],
        job_level=job_level,
        use_llm_selector=use_llm_selector,
        recent_qa_summary=recent_qa_summary,
    )
    ctx["strategy_block"] = format_strategies_for_prompt(strategies)

    # Skill injection is a sibling signal to strategy memory: strategies
    # are reward-driven (maintained by ``strategy_dream``), skills are
    # hand-authored by humans (``knowledge/skills/``). We retrieve both
    # off the same ``(dimension, job_level)`` key so they appear
    # side-by-side in the Generator prompt's independent slots. Opt-in
    # via ``enable_skill_injection`` because an empty
    # ``knowledge/skills/`` directory would inject only the
    # no-match placeholder on every turn.
    # ``getattr`` form lets test fixtures stub settings with a trimmed
    # ``SimpleNamespace`` that only declares the knobs the test cares
    # about — same defensive pattern we use for the evidence-span and
    # drift-feedback knobs in ``evaluator_agent``.
    if getattr(settings, "enable_skill_injection", False):
        skills = retrieve_skills(
            dimension=ctx["dimension"],
            job_level=job_level,
            limit=int(getattr(settings, "skill_retrieval_limit", 3)),
            use_llm_selector=use_llm_selector,
            recent_qa_summary=recent_qa_summary,
        )
        ctx["skill_block"] = build_skills_block(skills)

    # PLAN_DRIFT_RAG_FEEDBACK: same ``overruled_patterns`` snapshot
    # that feeds the Evaluator negatives (``PLAN_DRIFT_FEEDBACK``),
    # re-rendered from the Generator's perspective — "design the
    # question AWAY from these shallow evidence shapes". Only
    # overwrites the default placeholder when the renderer returns a
    # non-empty block.
    if getattr(settings, "enable_generator_avoid_patterns", False):
        try:
            rendered = build_generator_avoid_patterns(
                dimension=ctx["dimension"],
                top_n=int(getattr(settings, "drift_feedback_top_n", 3)),
                min_support=int(getattr(settings, "drift_feedback_min_support", 2)),
            )
            if rendered:
                ctx["avoid_patterns"] = rendered
        except Exception as e:  # pragma: no cover - feedback is non-critical
            log.debug("generator avoid-patterns render failed: %s", e)


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
        retrieval_block=ctx.get("retrieval_block", ""),
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
    )
    ctx["contract"] = contract


def _step_challenge_with_reference(state: InterviewState, ctx: dict[str, Any]) -> None:
    """Attach a short reference scenario to the question.

    Kept intentionally deterministic in P0 - the challenge text is
    stitched from retrieval_block's top line if present. An LLM-based
    variant can be added later by swapping this helper out.
    """
    payload = ctx.get("question_payload") or {}
    retrieval_block = ctx.get("retrieval_block", "") or ""
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


def _normalise_question_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


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
    if not question or question not in previous:
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
                return llm_plan
            log.info("ask_plan: llm planner returned None; falling back to default")

    return resolve_ask_plan(
        selected_action=selected_action,
        refine_mode=refine_mode,
        pending_plan_template=pending_plan_template,
        runtime_config=runtime_config,
        turn_budget_remaining=turn_budget_remaining,
        uncovered_dimensions=uncovered_dimensions,
        job_level=job_level,
    )


def ask_question_node(state: InterviewState) -> dict[str, Any]:
    node_started_at = time.perf_counter()
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
    ctx: dict[str, Any] = {
        "dimension": dimension,
        "qa_history": state.get("qa_history", []),
        "resume_anchor": select_resume_anchor(
            candidate=state.get("candidate", {}),
            job_spec=state.get("job_spec", {}),
            dimension=dimension,
            qa_history=state.get("qa_history", []),
            turn_idx=state.get("formal_turn_idx", state.get("turn_idx", 0)),
            self_intro_profile=state.get("self_intro_profile") or {},
        ),
        "retrieval_block": "",
        "strategy_block": "(no relevant strategy memories)",
        "skill_block": "(no relevant interview skills)",
        "avoid_patterns": "(no historical shallow patterns on this dimension)",
        "question_payload": {},
        "proposed_contract": {},
        "contract": None,
        "contract_hints": contract_hints,
    }
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
    ctx["probe_intent"] = probe_intent

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
    contract = _finalise_contract(plan, ctx)
    question_payload["contract"] = contract
    # Rubric_points is kept for backwards compatibility: evaluator_node
    # still tolerates the old shape when the new contract path is off.
    question_payload.setdefault(
        "rubric_points", list(contract.get("must_cover", [])),
    )
    if question_payload.get("duplicate_rewrite") or question_payload.get("language_fallback"):
        contract = _fallback_contract_for_rewritten_question(
            dimension=dimension,
            target_skills=ctx.get("target_skills") or [],
            target_difficulty=state.get("target_difficulty", "medium"),
        )
        question_payload["contract"] = contract
        question_payload["rubric_points"] = list(contract.get("must_cover", []))

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
                "target_skills": ctx.get("target_skills") or [],
                "skill_focus": ctx.get("skill_focus") or {},
                "elapsed_ms": int((time.perf_counter() - node_started_at) * 1000),
            },
        )
    except Exception as e:  # pragma: no cover - side channel
        log.warning("ask_question tracer side-channel failed: %s", e)
    return update
