"""Shared state ("blackboard") for the interview LangGraph workflow.

Mirrors the ACO ``ContentGenerationState`` pattern: every node reads
from and writes to a single typed dictionary, and LangGraph uses
reducers to merge partial updates. Keeping the fields here in one
place makes state evolution and debugging dramatically easier than
passing ad-hoc kwargs between nodes.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

MAX_MESSAGES = 30


def _capped_add(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Like ``operator.add`` but keeps only the most recent entries.

    ``messages`` is an audit trail that no node reads during the
    interview loop.  Letting it grow unboundedly inflates checkpoint
    size (especially with PostgresSaver) for no functional benefit.
    """
    combined = existing + new
    if len(combined) > MAX_MESSAGES:
        return combined[-MAX_MESSAGES:]
    return combined

InterviewMode = Literal["tech", "behavioral", "mixed"]
DimensionStatus = Literal["pending", "active", "passed", "failed"]
AnswerIntent = Literal[
    "normal",
    "empty",
    "clarification",
    "repeat",
    "too_short",
    "skipped",
]


class QATurn(TypedDict, total=False):
    """A single question/answer exchange."""
    turn_idx: int
    dimension: str
    question: str
    answer: str
    resume_anchor: dict[str, Any]
    target_skills: list[str]
    skill_focus: dict[str, Any]
    selected_action: str
    evaluation: dict[str, Any]
    timestamp: str
    selection_artifacts: dict[str, Any]
    # ``answer_intent`` is classified by ``wait_answer_node`` from the
    # raw candidate answer (empty / too_short / clarification / repeat /
    # skipped / normal). Persisting it on the turn record lets the final
    # report, replay, and any downstream training pipeline see *why* a
    # turn was scored the way it was without re-running the classifier.
    answer_intent: AnswerIntent
    video_signals: dict[str, Any]


class SelfIntroCommunicationSignal(TypedDict, total=False):
    structure: Literal["clear", "average", "unclear"]
    notes: list[str]


class SelfIntroProfile(TypedDict, total=False):
    summary: str
    emphasized_projects: list[str]
    emphasized_skills: list[str]
    preferred_focus: list[str]
    clarification_targets: list[str]
    communication_signal: SelfIntroCommunicationSignal
    anchor_cards: list[dict[str, Any]]
    parse_status: Literal["llm", "heuristic", "fallback"]


PlanTemplate = Literal["simple", "adaptive", "deep_probe", "quick_review"]

FailureCategory = Literal[
    "missing_evidence",
    "missing_tradeoff",
    "missing_metrics",
    "unclear_architecture",
    "weak_debugging",
    "weak_prioritization",
    "weak_roleplay_response",
]

ProbeIntent = Literal[
    "general",
    "evidence_probe",
    "tradeoff_probe",
    "coverage_closeout",
    "architecture_challenge",
    "debugging_probe",
    "performance_probe",
    "metric_probe",
    "prioritization_probe",
    "experiment_probe",
    "roleplay_probe",
    "objection_probe",
    "escalation_probe",
    # Business-scenario specific intents added for sales / HR /
    # ops / management directions where the existing 13 values
    # could not capture the third-party / case-walkthrough /
    # multi-stakeholder / process-recipe shapes of expected probes.
    "case_study_probe",
    "reference_check_probe",
    "stakeholder_pushback_probe",
    "process_design_probe",
]
BarLevel = Literal["intro", "standard", "deep_probe"]
PlanStepKind = Literal[
    "retrieve_rag",
    "retrieve_strategy",
    "retrieve_skills",
    "retrieve_candidate_anchors",
    "draft_question",
    "negotiate_contract",
    "challenge_with_reference",
    "guardrail_check",
]


class PlanContract(TypedDict, total=False):
    """Signed-off acceptance contract for a single ask-question round.

    Produced collaboratively: the generator drafts an initial proposal
    in ``ask_question_node``, then (optionally) the evaluator confirms
    it via the ``negotiate_contract`` step. The resulting contract is
    the single source of truth for the evaluator during scoring - the
    evaluator is expected to answer each ``acceptance_checks`` item
    explicitly instead of inventing its own rubric on the fly.

    Fields:
    - ``must_cover``: rubric points the answer *must* address.
    - ``acceptable_if_missing``: rubric points that are nice to have
      but do not by themselves fail the answer.
    - ``acceptance_checks``: short imperative/declarative sentences the
      evaluator grades yes/partial/no against.
    - ``minimum_bar``: one-sentence description of the pass threshold.
    - ``review_focus``: 2-3 high-signal concerns the evaluator should
      zero in on (e.g. "quantification", "trade-off clarity").
    - ``bar_level``: difficulty band, used to pick scoring strictness.
    - ``signed_by``: ordered list of roles that have co-signed the
      contract. Used downstream for telemetry / audit.
    """

    must_cover: list[str]
    acceptable_if_missing: list[str]
    acceptance_checks: list[str]
    minimum_bar: str
    review_focus: list[str]
    bar_level: BarLevel
    signed_by: list[Literal["generator", "evaluator"]]


class AskPlanStep(TypedDict, total=False):
    """A single step in the ``ask_question`` node's local execution plan.

    Mirrors ACO's ``PlanStep`` pattern but narrower: this is an
    in-node half-structured execution recipe, not a graph-level node.
    The executor runs steps by ``step_id`` ascending; ``optional``
    steps are skipped on failure without breaking the plan.
    """

    step_id: int
    kind: PlanStepKind
    goal: str
    success_criteria: str
    produced_keys: list[str]
    dependencies: list[int]
    optional: bool


class AskPlan(TypedDict, total=False):
    """Half-structured execution recipe for one round of ``ask_question``.

    - ``template``: which default template this plan was resolved from
      (``simple`` / ``adaptive`` / ``deep_probe`` / ``quick_review``). When the optional
      LLM planner is enabled, ``source`` is ``llm`` and ``template`` is
      the closest-matching label.
    - ``source``: how the plan was produced. Always ``default`` in P0
      unless ``runtime_config.ask_planning=True`` flips it to ``llm``.

    The plan object lives on ``state.current_ask_plan`` for the
    duration of one ask-wait-evaluate cycle and is replaced on the
    next ``director_sample`` pass.
    """

    plan_id: str
    template: PlanTemplate
    complexity: Literal["simple", "medium", "hard"]
    steps: list[AskPlanStep]
    source: Literal["default", "llm"]


class InterviewState(TypedDict, total=False):
    """Single blackboard shared by every node.

    Fields are ``total=False`` so node implementations can return
    partial updates (``{"turn_idx": turn_idx + 1}``) without having
    to re-emit the full state.
    """

    session_id: str
    trace_id: str

    candidate: dict[str, Any]
    job_spec: dict[str, Any]
    context_flags: dict[str, list[str]]
    mode: InterviewMode

    rubric: dict[str, Any]
    dimensions: list[str]
    focus_dimensions: list[str]
    dimension_status: dict[str, DimensionStatus]
    current_dimension: str | None

    selected_action: dict[str, Any]
    policy_id: str | None
    policy_context_keys: list[str]

    turn_idx: int
    formal_turn_idx: int
    current_question: dict[str, Any]
    current_skill_focus: dict[str, Any]
    current_answer: str
    current_answer_intent: AnswerIntent
    # Unredacted copy of the candidate's raw answer for the current
    # turn. Kept only for legacy checkpoints; new runs store raw text
    # in a process-local side-channel keyed by ``current_answer_raw_ref``
    # so sensitive text does not land in checkpoints or trace rows.
    current_answer_raw: str
    current_answer_raw_ref: str
    qa_history: Annotated[list[QATurn], operator.add]

    # Compressed summary of older QA turns, grouped by dimension.
    # Written by ``compress_context_node`` after evaluation; the
    # generator reads this instead of the full ``qa_history`` tail.
    qa_summary: str
    # Tracks which turn_idx was last compressed so we only summarise
    # the delta on each pass.
    qa_summary_through_turn: int

    evaluation: dict[str, Any]
    scores_per_dim: dict[str, float | None]
    score_breakdowns: dict[str, dict[str, Any]]

    max_turns: int
    quality_threshold: float
    turn_budget_remaining: int

    runtime_config: dict[str, Any]
    messages: Annotated[list[dict[str, Any]], _capped_add]

    final_report: dict[str, Any] | None
    status: Literal["running", "completed", "errored", "cancelled"]
    error: str | None

    # When True, the upcoming ``director_sample`` round must stay on
    # ``current_dimension`` (no switch / skip). Set by
    # ``refine_followup_node`` after the evaluator requests a deeper
    # pass on the same dimension, and cleared again by the director as
    # soon as it has honoured the lock. This guarantees that "refine"
    # really means refine, independent of what Thompson sampling would
    # otherwise prefer.
    refine_mode: bool

    # P0 Plan + Contract additions. All fields are additive and
    # default to missing/None for backwards compatibility with older
    # callers that still set ``runtime_config.iterative_contract``
    # rather than going through the plan executor.
    current_ask_plan: AskPlan | None
    current_contract: PlanContract | None
    # P1 verification side-channel: populated by
    # ``verification_node`` when triggered; consumed read-only by
    # ``experience_extractor_node`` and by any data/trainset builder.
    # Set to ``None`` when no verification ran this turn.
    verification: dict[str, Any] | None
    # Set by ``refine_followup_node`` from ``evaluation.recommended_next_plan``
    # so the next ``director_sample`` -> ``ask_question`` cycle can skip
    # the default template mapping and use the evaluator's suggestion.
    # Consumed and cleared by ``director_sample_node``.
    pending_plan_template: PlanTemplate | None
    # Structured hints the evaluator wants the generator to honour in
    # the upcoming draft_question step, e.g. ``must_address`` weaknesses
    # from the previous turn. Consumed and cleared alongside
    # ``pending_plan_template``.
    pending_contract_hints: dict[str, Any] | None

    # Adaptive difficulty: computed by ``director_sample_node`` from the
    # candidate's score trajectory on the current dimension.  The
    # generator is instructed to match this level; the contract's
    # ``bar_level`` is set accordingly.
    target_difficulty: Literal["easy", "medium", "hard"]

    intro_completed: bool
    self_intro_answer: str
    self_intro_profile: SelfIntroProfile
    self_intro_vector_status: dict[str, Any]

    # Video interview: per-turn visual signals from the front-end
    # MediaPipe face analysis. ``None`` when the camera is off.
    video_signals: dict[str, Any] | None
    answer_repair_count: int


def build_initial_state(
    *,
    session_id: str,
    trace_id: str,
    candidate: dict[str, Any],
    job_spec: dict[str, Any],
    mode: InterviewMode = "mixed",
    runtime_config: dict[str, Any] | None = None,
    context_flags: dict[str, list[str]] | None = None,
    focus_dimensions: list[str] | None = None,
    max_turns: int = 8,
    quality_threshold: float = 7.5,
    turn_budget: int = 12,
) -> InterviewState:
    """Factory for the ``initial_state`` used by ``workflow.invoke``.

    The defaults match ``Settings.default_*`` but callers (typically
    the API request translator) can override them based on the
    incoming request.
    """
    dimensions = list(job_spec.get("rubric_dimensions", [])) or [
        "technical_depth",
        "problem_solving",
        "communication",
    ]
    dimension_set = set(dimensions)
    focus = [
        d
        for d in (focus_dimensions or [])
        if isinstance(d, str) and d in dimension_set
    ]
    return {
        "session_id": session_id,
        "trace_id": trace_id,
        "candidate": candidate,
        "job_spec": job_spec,
        "context_flags": context_flags or {"resume": [], "job_spec": []},
        "mode": mode,
        "rubric": job_spec.get("rubric", {}),
        "dimensions": dimensions,
        "focus_dimensions": focus,
        "dimension_status": {d: "pending" for d in dimensions},
        "current_dimension": None,
        "selected_action": {},
        "policy_id": None,
        "policy_context_keys": [],
        "turn_idx": 0,
        "formal_turn_idx": 0,
        "current_question": {},
        "current_skill_focus": {},
        "current_answer": "",
        "current_answer_intent": "normal",
        "current_answer_raw": "",
        "current_answer_raw_ref": "",
        "qa_history": [],
        "qa_summary": "",
        "qa_summary_through_turn": -1,
        "evaluation": {},
        "scores_per_dim": {d: None for d in dimensions},
        "score_breakdowns": {},
        "max_turns": max_turns,
        "quality_threshold": quality_threshold,
        "turn_budget_remaining": turn_budget,
        "runtime_config": runtime_config or {},
        "messages": [],
        "final_report": None,
        "status": "running",
        "error": None,
        "refine_mode": False,
        "current_ask_plan": None,
        "current_contract": None,
        "verification": None,
        "pending_plan_template": None,
        "pending_contract_hints": None,
        "target_difficulty": "medium",
        "intro_completed": False,
        "self_intro_answer": "",
        "self_intro_profile": {},
        "self_intro_vector_status": {},
        "video_signals": None,
        "answer_repair_count": 0,
    }
