"""Generator (questioner) agent.

Responsibilities
----------------
- Propose the next question given ``selected_action`` and RAG context.
- Tag the question with the target dimension and rubric points, so the
  evaluator can later score against the same bar.

The full "iterative contract" described in the Plan (Generator <->
Evaluator pre-negotiation) is *scaffolded* here via the
``negotiate_rubric`` helper but kept optional for MVP simplicity. Phase
4 flips it on by default in the ``ask_question`` node.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings as get_settings
from app.engine.context import (
    build_context_frame_for_generator,
    frame_to_generator_messages,
)

# Backwards-compat re-exports. ``test_generator_equivalence.py`` patches
# ``generator.build_strategy_index`` AND ``generator.get_settings``
# side-by-side with the canonical ``app.engine.context.builder.*``
# references so legacy inline assembly and the new slot-based builder
# see the same strategy tail / settings flag. Keep these aliases even
# though ``generate_question`` no longer calls them directly —
# removing them breaks the equivalence coverage that locks the two
# assembly paths to byte-identical prompts.
from app.memory.strategy_store import build_strategy_index as build_strategy_index

from .llm_client import ChatMessage, call_chat, parse_json_response

log = get_logger(__name__)


_DIMENSION_LABELS: dict[str, str] = {
    "technical_depth": "技术深度",
    "problem_solving": "问题解决",
    "communication": "沟通表达",
    "system_design": "系统设计",
    "coding_quality": "代码质量",
    "project_experience": "项目经验",
    "product_thinking": "产品思维",
    "customer_discovery": "客户发现",
    "architecture": "架构能力",
    "behavioral": "行为面试",
    "leadership": "技术领导力",
}


def _dimension_label(dimension: str) -> str:
    return _DIMENSION_LABELS.get(dimension, dimension.replace("_", " "))


def _resume_project_label(resume_anchor: dict[str, Any] | None) -> str:
    if not resume_anchor:
        return "你真实参与过的一个项目"
    for key in ("project_name", "name", "label", "project"):
        value = str(resume_anchor.get(key) or "").strip()
        if value:
            return value
    return "你真实参与过的一个项目"


def _skill_phrase(
    *,
    target_skills: list[str] | None,
    resume_anchor: dict[str, Any] | None,
    self_intro_profile: dict[str, Any] | None,
) -> str:
    candidates: list[Any] = []
    candidates.extend(target_skills or [])
    if resume_anchor:
        candidates.extend(resume_anchor.get("tech_stack") or [])
        candidates.extend(resume_anchor.get("skills") or [])
    if self_intro_profile:
        candidates.extend(self_intro_profile.get("emphasized_skills") or [])

    seen: set[str] = set()
    skills: list[str] = []
    for item in candidates:
        skill = str(item).strip()
        key = skill.lower()
        if skill and key not in seen:
            seen.add(key)
            skills.append(skill)
    return "、".join(skills[:3]) or "关键技术选择"


def _fallback_question_text(
    *,
    dimension: str,
    resume_anchor: dict[str, Any] | None,
    self_intro_profile: dict[str, Any] | None,
    target_skills: list[str] | None,
    target_difficulty: str,
    probe_intent: str | None,
) -> str:
    dim = _dimension_label(dimension)
    project = _resume_project_label(resume_anchor)
    skills = _skill_phrase(
        target_skills=target_skills,
        resume_anchor=resume_anchor,
        self_intro_profile=self_intro_profile,
    )
    if target_difficulty == "hard" or probe_intent in {
        "architecture_challenge",
        "performance_probe",
        "debugging_probe",
    }:
        return (
            f"请结合「{project}」中与「{skills}」相关的{dim}场景，说明当时的约束、"
            "备选方案和最终取舍。再补充你如何用指标、故障复盘或上线结果验证这个选择，"
            "以及如果规模或故障压力更高会怎么演进。"
        )
    if probe_intent == "evidence_probe":
        return (
            f"请结合「{project}」，用一个具体例子说明你如何体现{dim}能力。"
            "重点讲你的个人贡献、可验证证据和最后结果。"
        )
    return (
        f"请结合「{project}」中与「{skills}」相关的一次经历，说明你如何体现{dim}能力。"
        "当时遇到什么问题，你做了哪些取舍，最后结果如何？"
    )


def _default_proposed_contract(
    *,
    dimension: str,
    rubric_points: list[str],
    refine_mode: bool,
    target_difficulty: str = "medium",
    target_skills: list[str] | None = None,
    resume_anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Heuristic contract to attach when the model returned none.

    Keeps ``ask_question_node`` from having to special-case missing
    ``proposed_contract`` fields; downstream ``negotiate_contract``
    can still tighten/override it.
    """
    from app.engine.workflow.difficulty_adapter import difficulty_to_bar_level

    dim = _dimension_label(dimension)
    project = _resume_project_label(resume_anchor)
    skills = "、".join(target_skills or []) or "关键技术选择"
    must_cover = list(rubric_points) or [dim]
    for item in ("具体项目证据", "方案取舍", "结果验证"):
        if item not in must_cover:
            must_cover.append(item)
    if refine_mode and "边界或故障场景" not in must_cover:
        must_cover.append("边界或故障场景")
    return {
        "must_cover": must_cover,
        "acceptable_if_missing": [],
        "acceptance_checks": [
            f"回答能围绕「{project}」或等价真实项目展开，并说明自己的职责。",
            f"回答覆盖「{skills}」相关的关键技术点，且不是只罗列名词。",
            "回答给出至少一个关键方案取舍，包含约束、备选方案或为什么这么选。",
            "回答包含可验证证据，如指标、故障现象、上线结果、复盘结论或明确的验证方法。",
        ],
        "minimum_bar": "至少结合一个真实项目，说清个人贡献、关键取舍和可验证结果。",
        "review_focus": ["项目证据", "方案取舍", "结果验证"],
        "bar_level": difficulty_to_bar_level(target_difficulty),  # type: ignore[arg-type]
    }


def generate_question(
    *,
    dimension: str,
    action: dict[str, Any],
    job_spec: dict[str, Any],
    candidate: dict[str, Any],
    recent_qa: list[dict[str, Any]],
    retrieval_block: str,
    question_seed_block: str = "",
    candidate_anchor_block: str = "",
    strategy_block: str = "(no relevant strategy memories)",
    skill_block: str = "(no relevant interview skills)",
    avoid_patterns_block: str = "(no historical shallow patterns on this dimension)",
    resume_anchor: dict[str, Any] | None = None,
    self_intro_profile: dict[str, Any] | None = None,
    qa_summary: str = "",
    refine_mode: bool = False,
    contract_hints: dict[str, Any] | None = None,
    target_difficulty: str = "medium",
    target_skills: list[str] | None = None,
    probe_intent: str | None = None,
    context_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce the next structured question payload.

    Returns a dict shaped like the JSON schema above. The payload now
    also includes a ``proposed_contract`` drafted by the generator.
    ``ask_question_node`` will either use it as-is (simple plan) or
    hand it to ``negotiate_contract_via_evaluator`` for a co-sign
    (adaptive / deep_probe plans). Callers are responsible for
    storing the payload into ``state["current_question"]``.

    ``skill_block`` (``PLAN_SKILL_INJECTION``) is an optional block of
    hand-authored interview skill cards that the
    ``ask_question_node`` may splice in when
    :attr:`Settings.enable_skill_injection` is ON. The default
    placeholder keeps the prompt byte-stable when the flag is OFF.
    """
    frame = build_context_frame_for_generator(
        dimension=dimension,
        action=action,
        job_spec=job_spec,
        candidate=candidate,
        recent_qa=recent_qa,
        retrieval_block=retrieval_block,
        question_seed_block=question_seed_block,
        candidate_anchor_block=candidate_anchor_block,
        strategy_block=strategy_block,
        skill_block=skill_block,
        avoid_patterns_block=avoid_patterns_block,
        resume_anchor=resume_anchor,
        self_intro_profile=self_intro_profile or {},
        qa_summary=qa_summary,
        refine_mode=refine_mode,
        contract_hints=contract_hints,
        target_difficulty=target_difficulty,
        target_skills=target_skills or [],
        probe_intent=probe_intent,
        context_flags=context_flags,
    )
    messages = frame_to_generator_messages(frame)
    raw = call_chat(messages, json_mode=True, agent_role="generator")
    data = parse_json_response(raw)
    from app.engine.workflow.difficulty_adapter import difficulty_to_bar_level

    rubric_points = data.get("rubric_points") or ["depth", "clarity"]
    proposed = data.get("proposed_contract") or _default_proposed_contract(
        dimension=dimension,
        rubric_points=rubric_points,
        refine_mode=refine_mode,
        target_difficulty=target_difficulty,
        target_skills=target_skills,
        resume_anchor=resume_anchor,
    )
    # Override bar_level to match the adaptive target_difficulty
    proposed["bar_level"] = difficulty_to_bar_level(target_difficulty)  # type: ignore[arg-type]
    question = {
        "question": data.get("question")
        or _fallback_question_text(
            dimension=dimension,
            resume_anchor=resume_anchor,
            self_intro_profile=self_intro_profile,
            target_skills=target_skills,
            target_difficulty=target_difficulty,
            probe_intent=probe_intent,
        ),
        "dimension": data.get("dimension", dimension),
        "rubric_points": rubric_points,
        "difficulty": target_difficulty,
        "rationale": data.get("rationale", ""),
        "proposed_contract": proposed,
    }
    if resume_anchor:
        question["resume_anchor"] = resume_anchor
    log.debug(
        "generator produced question for dim=%s: %s",
        dimension,
        question["question"][:80],
    )
    return question


_RUBRIC_NEG_TASK = """Before asking this question, agree with the evaluator
on what makes a "strong" answer. Reply as JSON:

{{
  "rubric_points": ["..."],
  "minimum_bar": "one-sentence description of the pass threshold"
}}

DIMENSION = {dimension}
QUESTION = {question}
"""


def negotiate_rubric(
    *,
    dimension: str,
    question: str,
) -> dict[str, Any]:
    """Light-weight stand-in for the iterative contract negotiation.

    Calling this before emitting the question lets the evaluator grade
    against a pre-committed yardstick instead of making one up after
    the fact. Returns a ``{rubric_points, minimum_bar}`` dict.
    """
    messages = [
        ChatMessage("system", "You co-design interview rubrics with another agent."),
        ChatMessage("user", _RUBRIC_NEG_TASK.format(dimension=dimension, question=question)),
    ]
    raw = call_chat(messages, json_mode=True, agent_role="rubric_negotiator")
    data = parse_json_response(raw)
    return {
        "rubric_points": data.get("rubric_points") or ["depth", "clarity"],
        "minimum_bar": data.get("minimum_bar", "Covers the core concept with one concrete example."),
    }
