"""Structured question-bank selector.

This service is intentionally separate from ``app.engine.rag.retriever``:
the YAML question bank chooses reusable question skeletons, while vector RAG
continues to retrieve supporting knowledge and fallback context.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import get_session
from app.models.question_bank import (
    QuestionRewardRollout,
    QuestionSeed,
    QuestionUsage,
    QuestionUsageStats,
    QuestionVariant,
)
from app.services.question_usage_stats import (
    CONTEXT_SCOPE,
    DEFAULT_ROLLOUT_MODE,
    MIN_CANDIDATES,
    MIN_REWARDED_USES,
    REWARD_SHADOW_BONUS_WEIGHT,
    SEED_SCOPE,
    build_question_reward_context_key,
    question_reward_rollout_id,
)


@dataclass(frozen=True)
class QuestionCandidate:
    seed_id: str
    variant_id: str
    seed_version: int
    variant_version: int
    rank: int
    match_score: float
    match_reasons: list[str]
    injected: bool
    title: str
    dimension: str
    seed_priority: int
    variant_priority: int
    skill_tags: list[str]
    direction_tags: list[str]
    role_tags: list[str]
    rubric: dict[str, Any]
    intent: str
    difficulty: str
    scenario_brief: str
    question_stem: str
    prompt_template: str
    scenario_skill_tags: list[str]
    resume_anchor_hints: list[str]
    failure_categories: list[str]
    rubric_additions: list[str]
    expected_signals: list[str]
    anti_patterns: list[str]
    good_answer_hints: list[str]
    fit_score: float = 0.0
    anchor_confidence: str = ""
    generic_penalty: float = 0.0
    matched_project: str | None = None
    matched_candidate_skills: list[str] | None = None
    matched_job_skills: list[str] | None = None
    reward_shadow_rank: int | None = None
    reward_shadow_score: float | None = None
    reward_shadow_rank_changed: bool = False
    usage_stats: dict[str, Any] | None = None
    reward_shadow_reason: dict[str, Any] | None = None
    reward_rollout_reason: dict[str, Any] | None = None

    def with_injected(self, injected: bool) -> QuestionCandidate:
        return replace(self, injected=injected)

    def as_artifact(self) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "variant_id": self.variant_id,
            "seed_version": self.seed_version,
            "variant_version": self.variant_version,
            "rank": self.rank,
            "match_score": self.match_score,
            "match_reasons": list(self.match_reasons),
            "injected": self.injected,
            "title": self.title,
            "dimension": self.dimension,
            "direction_tags": list(self.direction_tags),
            "role_tags": list(self.role_tags),
            "intent": self.intent,
            "difficulty": self.difficulty,
            "scenario_brief": self.scenario_brief,
            "fit_score": self.fit_score,
            "anchor_confidence": self.anchor_confidence,
            "generic_penalty": self.generic_penalty,
            "matched_project": self.matched_project,
            "matched_candidate_skills": list(self.matched_candidate_skills or []),
            "matched_job_skills": list(self.matched_job_skills or []),
            "reward_shadow_rank": self.reward_shadow_rank,
            "reward_shadow_score": self.reward_shadow_score,
            "reward_shadow_rank_changed": self.reward_shadow_rank_changed,
            "usage_stats": self.usage_stats,
            "reward_shadow_reason": self.reward_shadow_reason,
            "reward_rollout_reason": self.reward_rollout_reason,
        }


@dataclass(frozen=True)
class QuestionSelectionResult:
    candidates: list[QuestionCandidate]

    @property
    def top(self) -> QuestionCandidate | None:
        return self.candidates[0] if self.candidates else None

    def as_artifacts(self) -> list[dict[str, Any]]:
        return [candidate.as_artifact() for candidate in self.candidates]


@dataclass(frozen=True)
class _AggregatedQuestionStats:
    variant_id: str
    uses: int = 0
    injected_uses: int = 0
    rewarded_uses: int = 0
    avg_score: float | None = None
    pass_rate: float | None = None
    avg_immediate_reward: float | None = None


def select_question_candidates(
    session: Session,
    *,
    dimension: str,
    job_level: str | None,
    target_skills: Sequence[str] | None = None,
    failure_categories: Sequence[str] | None = None,
    direction_tags: Sequence[str] | None = None,
    role_tags: Sequence[str] | None = None,
    resume_anchor_text: str | None = None,
    probe_intent: str | None = None,
    difficulty: str | None = None,
    qa_history: Sequence[dict[str, Any]] | None = None,
    fit_profile: Any | None = None,
    question_selector_mode: str = "structured_primary",
    top_k: int = 3,
) -> QuestionSelectionResult:
    """Return deterministic top-k structured question candidates."""

    normalized_dimension = _slugify(dimension)
    normalized_job_level = _slugify(job_level)
    target_skill_set = _slug_set(target_skills)
    failure_set = _slug_set(failure_categories)
    direction_context_tags = list(direction_tags or []) or list(
        getattr(fit_profile, "direction_tags", []) or []
    )
    role_context_tags = list(role_tags or []) or list(
        getattr(fit_profile, "role_tags", []) or []
    )
    direction_tag_set = _slug_set(direction_context_tags)
    role_tag_set = _slug_set(role_context_tags)
    normalized_intent = _slugify(probe_intent)
    normalized_difficulty = _slugify(difficulty)
    used_seed_ids, used_variant_ids = _extract_used_question_refs(qa_history or [])

    rows = session.execute(
        select(QuestionSeed, QuestionVariant)
        .join(QuestionVariant, QuestionVariant.seed_id == QuestionSeed.id)
        .where(
            QuestionSeed.status == "active",
            QuestionVariant.status == "active",
            QuestionSeed.scope == "global",
            QuestionSeed.dimension == normalized_dimension,
        )
    ).all()

    candidates: list[QuestionCandidate] = []
    for seed, variant in rows:
        if normalized_job_level and normalized_job_level not in set(seed.job_levels or []):
            continue
        if _is_deduped(
            seed_id=seed.id,
            variant_id=variant.id,
            intent=normalized_intent or _slugify(variant.intent),
            used_seed_ids=used_seed_ids,
            used_variant_ids=used_variant_ids,
        ):
            continue

        score, reasons = _score_candidate(
            seed,
            variant,
            target_skill_set=target_skill_set,
            failure_set=failure_set,
            resume_anchor_text=resume_anchor_text or "",
            probe_intent=normalized_intent,
            difficulty=normalized_difficulty,
            fit_profile=fit_profile,
            direction_tag_set=direction_tag_set,
            role_tag_set=role_tag_set,
        )
        fit_details = _score_fit_profile_details(seed, variant, fit_profile)
        candidates.append(
            QuestionCandidate(
                seed_id=seed.id,
                variant_id=variant.id,
                seed_version=int(seed.version or 1),
                variant_version=int(variant.version or 1),
                rank=0,
                match_score=score,
                match_reasons=reasons,
                injected=False,
                title=seed.title,
                dimension=seed.dimension,
                seed_priority=int(seed.priority or 0),
                variant_priority=int(variant.priority or 0),
                skill_tags=list(seed.skill_tags or []),
                direction_tags=list(seed.direction_tags or []),
                role_tags=list(variant.role_tags or seed.role_tags or []),
                rubric=dict(seed.rubric or {}),
                intent=variant.intent,
                difficulty=variant.difficulty,
                scenario_brief=variant.scenario_brief,
                question_stem=variant.question_stem,
                prompt_template=variant.prompt_template,
                scenario_skill_tags=list(variant.scenario_skill_tags or []),
                resume_anchor_hints=list(variant.resume_anchor_hints or []),
                failure_categories=list(variant.failure_categories or []),
                rubric_additions=list(variant.rubric_additions or []),
                expected_signals=list(variant.expected_signals or []),
                anti_patterns=list(variant.anti_patterns or []),
                good_answer_hints=list(variant.good_answer_hints or []),
                fit_score=fit_details["fit_score"],
                anchor_confidence=fit_details["anchor_confidence"],
                generic_penalty=fit_details["generic_penalty"],
                matched_project=fit_details["matched_project"],
                matched_candidate_skills=fit_details["matched_candidate_skills"],
                matched_job_skills=fit_details["matched_job_skills"],
            )
        )

    candidates = _apply_role_pack_filter(candidates, role_tag_set)
    question_context_key = build_question_reward_context_key(
        direction_tags=direction_context_tags,
        role_tags=role_context_tags,
        job_level=normalized_job_level,
        dimension=normalized_dimension,
    )
    ranked = _select_with_reward_rollouts(
        session,
        candidates,
        top_k=max(0, int(top_k)),
        question_context_key=question_context_key,
    )
    ranked = [replace(candidate, rank=idx + 1) for idx, candidate in enumerate(ranked)]
    ranked = _apply_reward_shadow(
        session,
        ranked,
        question_selector_mode=question_selector_mode,
    )
    return QuestionSelectionResult(candidates=ranked)


def _select_with_reward_rollouts(
    session: Session,
    candidates: Sequence[QuestionCandidate],
    *,
    top_k: int,
    question_context_key: str,
) -> list[QuestionCandidate]:
    if top_k <= 0 or not candidates:
        return []

    stats_by_variant = _load_aggregated_question_stats(
        session,
        [candidate.variant_id for candidate in candidates],
    )
    seed_ids = sorted({candidate.seed_id for candidate in candidates})
    seed_rollouts = {
        row.scope_key: row
        for row in session.scalars(
            select(QuestionRewardRollout)
            .where(QuestionRewardRollout.scope == SEED_SCOPE)
            .where(QuestionRewardRollout.scope_key.in_(seed_ids))
        )
    } if seed_ids else {}
    context_rollout = session.get(
        QuestionRewardRollout,
        question_reward_rollout_id(
            scope=CONTEXT_SCOPE,
            scope_key=question_context_key,
        ),
    )

    candidates_by_seed: dict[str, list[QuestionCandidate]] = {}
    for candidate in sorted(candidates, key=_metadata_sort_key):
        candidates_by_seed.setdefault(candidate.seed_id, []).append(candidate)

    representatives: list[QuestionCandidate] = []
    duplicate_candidates: list[QuestionCandidate] = []
    seed_reason_by_seed: dict[str, dict[str, Any]] = {}
    for seed_id, seed_candidates in candidates_by_seed.items():
        seed_rollout = seed_rollouts.get(seed_id)
        seed_mode = _rollout_mode(seed_rollout)
        seed_gate_reasons = _seed_reward_gate_reasons(
            seed_candidates,
            stats_by_variant,
        ) if seed_mode == "reward" else []
        seed_live_order = (
            "reward"
            if seed_mode == "reward" and not seed_gate_reasons
            else "metadata_fallback"
            if seed_mode == "reward"
            else "metadata"
        )
        ordered_seed_candidates = sorted(
            seed_candidates,
            key=(
                lambda item: _reward_sort_key(item, stats_by_variant)
                if seed_live_order == "reward"
                else _metadata_sort_key(item)
            ),
        )
        representative = ordered_seed_candidates[0]
        representatives.append(representative)
        duplicate_candidates.extend(ordered_seed_candidates[1:])
        seed_reason_by_seed[seed_id] = {
            "seed_rollout_mode": seed_mode,
            "seed_rollout_source": "override" if seed_rollout else "default",
            "seed_live_order": seed_live_order,
            "seed_gate_reasons": seed_gate_reasons,
        }

    context_mode = _rollout_mode(context_rollout)
    context_gate_reasons = _context_reward_gate_reasons(
        representatives,
        stats_by_variant,
    ) if context_mode == "reward" else []
    context_live_order = (
        "reward"
        if context_mode == "reward" and not context_gate_reasons
        else "metadata_fallback"
        if context_mode == "reward"
        else "metadata"
    )
    representative_order = sorted(
        representatives,
        key=(
            lambda item: _reward_sort_key(item, stats_by_variant)
            if context_live_order == "reward"
            else _metadata_sort_key(item)
        ),
    )
    selected = representative_order[:top_k]
    if len(selected) < top_k:
        selected_ids = {candidate.variant_id for candidate in selected}
        for candidate in sorted(duplicate_candidates, key=_metadata_sort_key):
            if candidate.variant_id in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.variant_id)
            if len(selected) >= top_k:
                break

    context_reason = {
        "question_context_key": question_context_key,
        "context_rollout_mode": context_mode,
        "context_rollout_source": "override" if context_rollout else "default",
        "live_order": context_live_order,
        "gate_reasons": context_gate_reasons,
    }
    return [
        replace(
            candidate,
            reward_rollout_reason={
                **context_reason,
                **seed_reason_by_seed.get(candidate.seed_id, {}),
            },
        )
        for candidate in selected
    ]


def _metadata_sort_key(candidate: QuestionCandidate) -> tuple[float, int, str, str]:
    return (
        -float(candidate.match_score),
        -(int(candidate.seed_priority or 0) + int(candidate.variant_priority or 0)),
        candidate.seed_id,
        candidate.variant_id,
    )


def _reward_sort_key(
    candidate: QuestionCandidate,
    stats_by_variant: dict[str, _AggregatedQuestionStats],
) -> tuple[float, float, int, str, str]:
    stats = stats_by_variant.get(candidate.variant_id)
    reward_score = (
        _reward_shadow_score(candidate, stats)
        if stats is not None
        else float(candidate.match_score)
    )
    metadata_key = _metadata_sort_key(candidate)
    return (-reward_score, *metadata_key[1:])


def _load_aggregated_question_stats(
    session: Session,
    variant_ids: Sequence[str],
) -> dict[str, _AggregatedQuestionStats]:
    clean_variant_ids = sorted({str(value or "").strip() for value in variant_ids if value})
    if not clean_variant_ids:
        return {}
    rows = list(
        session.scalars(
            select(QuestionUsageStats)
            .where(QuestionUsageStats.variant_id.in_(clean_variant_ids))
        )
    )
    grouped: dict[str, list[QuestionUsageStats]] = {}
    for row in rows:
        grouped.setdefault(row.variant_id, []).append(row)
    return {
        variant_id: _aggregate_stats_rows(variant_id, stats_rows)
        for variant_id, stats_rows in grouped.items()
    }


def _aggregate_stats_rows(
    variant_id: str,
    rows: list[QuestionUsageStats],
) -> _AggregatedQuestionStats:
    uses = sum(int(row.uses or 0) for row in rows)
    injected_uses = sum(int(row.injected_uses or 0) for row in rows)
    rewarded_uses = sum(int(row.rewarded_uses or 0) for row in rows)
    return _AggregatedQuestionStats(
        variant_id=variant_id,
        uses=uses,
        injected_uses=injected_uses,
        rewarded_uses=rewarded_uses,
        avg_score=_weighted_avg(
            [(row.avg_score, int(row.rewarded_uses or 0)) for row in rows]
        ),
        pass_rate=_weighted_avg(
            [(row.pass_rate, int(row.rewarded_uses or 0)) for row in rows]
        ),
        avg_immediate_reward=_weighted_avg(
            [
                (row.avg_immediate_reward, int(row.rewarded_uses or 0))
                for row in rows
            ]
        ),
    )


def _weighted_avg(values: Sequence[tuple[float | None, int]]) -> float | None:
    weighted = [
        (float(value), int(weight))
        for value, weight in values
        if value is not None and int(weight or 0) > 0
    ]
    total_weight = sum(weight for _value, weight in weighted)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in weighted) / total_weight


def _rollout_mode(row: QuestionRewardRollout | None) -> str:
    mode = str(getattr(row, "mode", "") or "").strip()
    if mode in {"metadata", "reward_shadow", "reward"}:
        return mode
    return DEFAULT_ROLLOUT_MODE


def _seed_reward_gate_reasons(
    candidates: Sequence[QuestionCandidate],
    stats_by_variant: dict[str, _AggregatedQuestionStats],
) -> list[str]:
    reasons: list[str] = []
    if len(candidates) < 2:
        reasons.append("single_variant_no_rank_effect")
    rewarded = sum(
        int(stats_by_variant.get(candidate.variant_id).rewarded_uses or 0)
        for candidate in candidates
        if stats_by_variant.get(candidate.variant_id) is not None
    )
    if rewarded < MIN_REWARDED_USES:
        reasons.append("reward_samples_below_min")
    return reasons


def _context_reward_gate_reasons(
    candidates: Sequence[QuestionCandidate],
    stats_by_variant: dict[str, _AggregatedQuestionStats],
) -> list[str]:
    reasons: list[str] = []
    if len(candidates) < MIN_CANDIDATES:
        reasons.append("candidate_pool_below_min")
    rewarded = sum(
        int(stats_by_variant.get(candidate.variant_id).rewarded_uses or 0)
        for candidate in candidates
        if stats_by_variant.get(candidate.variant_id) is not None
    )
    if rewarded < MIN_REWARDED_USES:
        reasons.append("reward_samples_below_min")
    return reasons


def _select_seed_diverse_top_k(
    candidates: Sequence[QuestionCandidate],
    top_k: int,
) -> list[QuestionCandidate]:
    if top_k <= 0:
        return []

    selected: list[QuestionCandidate] = []
    duplicate_seed_candidates: list[QuestionCandidate] = []
    selected_seed_ids: set[str] = set()

    for candidate in candidates:
        if candidate.seed_id in selected_seed_ids:
            duplicate_seed_candidates.append(candidate)
            continue
        selected.append(candidate)
        selected_seed_ids.add(candidate.seed_id)
        if len(selected) >= top_k:
            return selected

    for candidate in duplicate_seed_candidates:
        selected.append(candidate)
        if len(selected) >= top_k:
            break
    return selected


def _apply_reward_shadow(
    session: Session,
    candidates: list[QuestionCandidate],
    *,
    question_selector_mode: str,
) -> list[QuestionCandidate]:
    if not candidates:
        return []
    stats_by_variant = _load_aggregated_question_stats(
        session,
        [candidate.variant_id for candidate in candidates],
    )
    scored: list[tuple[float, str, QuestionCandidate, _AggregatedQuestionStats]] = []
    for candidate in candidates:
        stats = stats_by_variant.get(candidate.variant_id)
        if stats is None:
            continue
        score = _reward_shadow_score(candidate, stats)
        scored.append((score, candidate.variant_id, candidate, stats))
    reward_rank_by_variant = {
        candidate.variant_id: idx
        for idx, (_score, _variant_id, candidate, _stats) in enumerate(
            sorted(scored, key=lambda item: (-item[0], item[1])),
            1,
        )
    }
    output: list[QuestionCandidate] = []
    for candidate in candidates:
        stats = stats_by_variant.get(candidate.variant_id)
        if stats is None:
            output.append(
                replace(
                    candidate,
                    reward_shadow_rank=None,
                    reward_shadow_score=None,
                    reward_shadow_rank_changed=False,
                    usage_stats=None,
                    reward_shadow_reason={
                        "status": "no_stats",
                        "metadata_rank": candidate.rank,
                        **(candidate.reward_rollout_reason or {}),
                    },
                )
            )
            continue
        shadow_rank = reward_rank_by_variant.get(candidate.variant_id)
        output.append(
            replace(
                candidate,
                reward_shadow_rank=shadow_rank,
                reward_shadow_score=_reward_shadow_score(candidate, stats),
                reward_shadow_rank_changed=(
                    shadow_rank is not None and shadow_rank != candidate.rank
                ),
                usage_stats=_usage_stats_payload(stats),
                reward_shadow_reason={
                    **_reward_shadow_reason(candidate, stats),
                    **(candidate.reward_rollout_reason or {}),
                },
            )
        )
    return output


def _reward_shadow_score(
    candidate: QuestionCandidate,
    stats: _AggregatedQuestionStats,
) -> float:
    sample_confidence = _sample_confidence(stats)
    reward_bonus = (
        float(stats.avg_immediate_reward or 0.0)
        * REWARD_SHADOW_BONUS_WEIGHT
        * sample_confidence
    )
    usage_bonus = _safe_log(int(stats.uses or 0) + 1) * 0.1 * sample_confidence
    return float(candidate.match_score) + reward_bonus + usage_bonus


def _reward_shadow_reason(
    candidate: QuestionCandidate,
    stats: _AggregatedQuestionStats,
) -> dict[str, Any]:
    sample_confidence = _sample_confidence(stats)
    return {
        "status": "scored",
        "uses": int(stats.uses or 0),
        "injected_uses": int(stats.injected_uses or 0),
        "rewarded_uses": int(stats.rewarded_uses or 0),
        "avg_immediate_reward": stats.avg_immediate_reward,
        "pass_rate": stats.pass_rate,
        "sample_confidence": sample_confidence,
        "metadata_rank": candidate.rank,
        "metadata_score": candidate.match_score,
    }


def _usage_stats_payload(stats: _AggregatedQuestionStats) -> dict[str, Any]:
    return {
        "uses": int(stats.uses or 0),
        "injected_uses": int(stats.injected_uses or 0),
        "rewarded_uses": int(stats.rewarded_uses or 0),
        "avg_score": stats.avg_score,
        "pass_rate": stats.pass_rate,
        "avg_immediate_reward": stats.avg_immediate_reward,
    }


def _sample_confidence(stats: _AggregatedQuestionStats) -> float:
    return min(1.0, int(stats.rewarded_uses or 0) / MIN_REWARDED_USES)


def _safe_log(value: int) -> float:
    import math

    return math.log(max(1, value))


def format_question_seed_block(candidate: QuestionCandidate | None) -> str:
    if candidate is None:
        return ""
    lines = [
        f"Seed: {candidate.title}",
        f"Dimension: {candidate.dimension}",
        f"Intent: {candidate.intent}",
        f"Difficulty: {candidate.difficulty}",
        f"Scenario: {candidate.scenario_brief}",
        f"Question stem: {candidate.question_stem}",
        f"Prompt template: {candidate.prompt_template}",
    ]
    if candidate.skill_tags or candidate.scenario_skill_tags:
        tags = sorted(set(candidate.skill_tags) | set(candidate.scenario_skill_tags))
        lines.append("Skill tags: " + ", ".join(tags))
    if candidate.failure_categories:
        lines.append("Failure categories to probe: " + ", ".join(candidate.failure_categories))
    return "\n".join(lines)


def build_question_seed_contract_hints(
    candidate: QuestionCandidate | None,
) -> dict[str, Any]:
    if candidate is None:
        return {}
    return {
        "question_seed": {
            "seed_id": candidate.seed_id,
            "variant_id": candidate.variant_id,
            "rubric": candidate.rubric,
            "rubric_additions": list(candidate.rubric_additions),
            "expected_signals": list(candidate.expected_signals),
            "anti_patterns": list(candidate.anti_patterns),
            "good_answer_hints": list(candidate.good_answer_hints),
        }
    }


def build_question_history_selection_artifacts(
    current_question: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the minimal selector refs needed for future dedupe.

    ``current_question.selection_artifacts`` is intentionally rich for admin
    observability. ``qa_history`` only needs the actually injected question
    skeleton, otherwise shadow top-k candidates would be treated as seen.
    """

    if not isinstance(current_question, dict):
        return {}
    artifacts = current_question.get("selection_artifacts")
    if not isinstance(artifacts, dict):
        return {}
    items = artifacts.get("question_items")
    if not isinstance(items, list):
        return {}

    history_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("injected") is not True:
            continue
        if _int_or_none(item.get("rank")) != 1:
            continue
        seed_id = str(item.get("seed_id") or "").strip()
        variant_id = str(item.get("variant_id") or "").strip()
        if not seed_id and not variant_id:
            continue
        history_items.append(
            {
                "seed_id": seed_id,
                "variant_id": variant_id,
                "rank": 1,
                "injected": True,
            }
        )
    if not history_items:
        return {}
    return {"question_items": history_items}


def record_question_usages(
    *,
    candidates: Sequence[QuestionCandidate],
    session_id: str,
    turn_idx: int,
    trace_id: str | None,
    question_selector_mode: str,
    question_context_key: str | None = None,
    direction_tag: str | None = None,
    role_tag: str | None = None,
    job_level: str | None = None,
    dimension: str | None = None,
    session: Session | None = None,
) -> None:
    """Write top-k selector candidates for later attribution.

    Result fields remain null here. ``reward_update`` fills only the injected
    rank-1 row after the evaluator score is known.
    """

    if not candidates:
        return
    if session is None:
        with get_session() as sess:
            record_question_usages(
                candidates=candidates,
                session_id=session_id,
                turn_idx=turn_idx,
                trace_id=trace_id,
                question_selector_mode=question_selector_mode,
                question_context_key=question_context_key,
                direction_tag=direction_tag,
                role_tag=role_tag,
                job_level=job_level,
                dimension=dimension,
                session=sess,
            )
        return

    for candidate in candidates:
        usage_id = _usage_id(
            session_id=session_id,
            turn_idx=turn_idx,
            variant_id=candidate.variant_id,
            rank=candidate.rank,
            question_selector_mode=question_selector_mode,
        )
        values = {
            "id": usage_id,
            "session_id": session_id,
            "turn_idx": turn_idx,
            "trace_id": trace_id,
            "seed_id": candidate.seed_id,
            "variant_id": candidate.variant_id,
            "seed_version": candidate.seed_version,
            "variant_version": candidate.variant_version,
            "rank": candidate.rank,
            "match_score": candidate.match_score,
            "match_reasons": list(candidate.match_reasons),
            "injected": bool(candidate.injected),
            "question_selector_mode": question_selector_mode,
            "question_context_key": question_context_key,
            "direction_tag": direction_tag,
            "role_tag": role_tag,
            "job_level": job_level,
            "dimension": dimension,
        }
        row = session.get(QuestionUsage, usage_id)
        if row is None:
            session.add(QuestionUsage(**values))
            continue
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()


def _score_candidate(
    seed: QuestionSeed,
    variant: QuestionVariant,
    *,
    target_skill_set: set[str],
    failure_set: set[str],
    resume_anchor_text: str,
    probe_intent: str,
    difficulty: str,
    fit_profile: Any | None = None,
    direction_tag_set: set[str] | None = None,
    role_tag_set: set[str] | None = None,
) -> tuple[float, list[str]]:
    score = float(int(seed.priority or 0) + int(variant.priority or 0))
    reasons = [f"priority:{int(seed.priority or 0) + int(variant.priority or 0)}"]

    seed_tags = set(seed.skill_tags or [])
    scenario_tags = set(variant.scenario_skill_tags or [])
    seed_direction_tags = set(seed.direction_tags or [])
    variant_role_tags = set(variant.role_tags or seed.role_tags or [])
    for tag in sorted((direction_tag_set or set()) & seed_direction_tags):
        score += 6.0
        reasons.append(f"direction_tag:{tag}")
    for tag in sorted((role_tag_set or set()) & variant_role_tags):
        score += 80.0
        reasons.append(f"role_tag:{tag}")
    for tag in sorted(target_skill_set & seed_tags):
        score += 12.0
        reasons.append(f"target_skill:{tag}")
    for tag in sorted(target_skill_set & scenario_tags):
        score += 10.0
        reasons.append(f"scenario_skill:{tag}")

    for category in sorted(failure_set & set(variant.failure_categories or [])):
        score += 8.0
        reasons.append(f"failure_category:{category}")

    resume_blob = _resume_match_blob(resume_anchor_text)
    for hint in sorted(set(variant.resume_anchor_hints or [])):
        if hint and (hint in resume_blob or hint in resume_anchor_text.lower()):
            score += 6.0
            reasons.append(f"resume_anchor:{hint}")

    if probe_intent and probe_intent == _slugify(variant.intent):
        score += 4.0
        reasons.append(f"intent:{variant.intent}")
    if difficulty and difficulty == _slugify(variant.difficulty):
        score += 3.0
        reasons.append(f"difficulty:{variant.difficulty}")
    fit_score, fit_reasons = _score_fit_profile(seed, variant, fit_profile)
    score += fit_score
    reasons.extend(fit_reasons)
    return score, reasons


def _apply_role_pack_filter(
    candidates: list[QuestionCandidate],
    role_tag_set: set[str],
) -> list[QuestionCandidate]:
    if not candidates or not role_tag_set:
        return candidates
    matching = [
        candidate
        for candidate in candidates
        if role_tag_set & set(candidate.role_tags or [])
    ]
    if not matching:
        return [
            replace(
                candidate,
                match_reasons=[
                    *candidate.match_reasons,
                    "role_fallback:no_matching_role_pack",
                ],
            )
            for candidate in candidates
        ]

    allowed: list[QuestionCandidate] = []
    for candidate in candidates:
        candidate_roles = set(candidate.role_tags or [])
        if role_tag_set & candidate_roles:
            allowed.append(candidate)
        elif "general" in candidate_roles or not candidate_roles:
            allowed.append(
                replace(
                    candidate,
                    match_reasons=[*candidate.match_reasons, "role_fallback:generic"],
                )
            )
    return allowed


def _score_fit_profile(
    seed: QuestionSeed,
    variant: QuestionVariant,
    fit_profile: Any | None,
) -> tuple[float, list[str]]:
    details = _score_fit_profile_details(seed, variant, fit_profile)
    reasons: list[str] = []
    for skill in details["matched_candidate_skills"]:
        reasons.append(f"candidate_project_fit:{skill}")
    for skill in details["matched_job_skills"]:
        reasons.append(f"job_skill_fit:{skill}")
    turn_intent = getattr(fit_profile, "turn_intent", "") if fit_profile is not None else ""
    if turn_intent and turn_intent == _slugify(variant.intent):
        reasons.append(f"turn_fit:{variant.intent}")
    penalty = details["generic_penalty"]
    if penalty:
        reasons.append(f"generic_penalty:{int(penalty)}")
    return details["fit_score"] + penalty, reasons


def _score_fit_profile_details(
    seed: QuestionSeed,
    variant: QuestionVariant,
    fit_profile: Any | None,
) -> dict[str, Any]:
    if fit_profile is None:
        return {
            "fit_score": 0.0,
            "anchor_confidence": "",
            "generic_penalty": 0.0,
            "matched_project": None,
            "matched_candidate_skills": [],
            "matched_job_skills": [],
        }
    seed_tags = set(seed.skill_tags or [])
    scenario_tags = set(variant.scenario_skill_tags or [])
    anchor_hints = set(variant.resume_anchor_hints or [])
    all_tags = seed_tags | scenario_tags | anchor_hints

    candidate_skills = set(getattr(fit_profile, "candidate_skills", []) or [])
    anchor_terms = set(getattr(fit_profile, "resume_anchor_terms", []) or [])
    job_core_skills = set(getattr(fit_profile, "job_core_skills", []) or [])
    target_skills = set(getattr(fit_profile, "target_skills", []) or [])
    candidate_matches = sorted((candidate_skills | anchor_terms | target_skills) & all_tags)
    job_matches = sorted(job_core_skills & (seed_tags | scenario_tags))

    fit_score = 0.0
    if candidate_matches:
        fit_score += 20.0 + max(0, len(candidate_matches) - 1) * 2.0
    if job_matches:
        fit_score += 12.0 + max(0, len(job_matches) - 1) * 1.5
    turn_intent = getattr(fit_profile, "turn_intent", "") or ""
    if turn_intent and turn_intent == _slugify(variant.intent):
        fit_score += 2.0
    anchor_confidence = str(getattr(fit_profile, "anchor_confidence", "") or "")
    if anchor_confidence == "high" and candidate_matches:
        fit_score += 4.0
    elif anchor_confidence == "medium" and candidate_matches:
        fit_score += 1.0

    generic_risk = str(getattr(fit_profile, "generic_risk", "") or "")
    generic_penalty = 0.0
    if generic_risk == "high":
        generic_penalty = -4.0
    elif generic_risk == "medium" and not (candidate_matches or job_matches):
        generic_penalty = -2.0

    matched_project = None
    projects = getattr(fit_profile, "candidate_projects", []) or []
    if projects:
        first_project = projects[0]
        if isinstance(first_project, dict):
            matched_project = first_project.get("name")

    return {
        "fit_score": fit_score,
        "anchor_confidence": anchor_confidence,
        "generic_penalty": generic_penalty,
        "matched_project": matched_project,
        "matched_candidate_skills": candidate_matches,
        "matched_job_skills": job_matches,
    }


def _is_deduped(
    *,
    seed_id: str,
    variant_id: str,
    intent: str,
    used_seed_ids: set[str],
    used_variant_ids: set[str],
) -> bool:
    if intent == "opening":
        return seed_id in used_seed_ids
    return variant_id in used_variant_ids


def _extract_used_question_refs(
    qa_history: Sequence[dict[str, Any]],
) -> tuple[set[str], set[str]]:
    seed_ids: set[str] = set()
    variant_ids: set[str] = set()
    for turn in qa_history:
        artifacts = turn.get("selection_artifacts")
        if not isinstance(artifacts, dict):
            artifacts = turn
        items = artifacts.get("question_items") if isinstance(artifacts, dict) else None
        if not isinstance(items, list):
            continue
        has_injected_marker = any(
            isinstance(item, dict) and "injected" in item
            for item in items
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            if has_injected_marker and item.get("injected") is not True:
                continue
            seed_id = str(item.get("seed_id") or "").strip()
            variant_id = str(item.get("variant_id") or "").strip()
            if seed_id:
                seed_ids.add(seed_id)
            if variant_id:
                variant_ids.add(variant_id)
    return seed_ids, variant_ids


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usage_id(
    *,
    session_id: str,
    turn_idx: int,
    variant_id: str,
    rank: int,
    question_selector_mode: str,
) -> str:
    material = f"{session_id}|{turn_idx}|{variant_id}|{rank}|{question_selector_mode}"
    digest = hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"question-usage:{digest[:32]}"


def _slug_set(values: Sequence[str] | None) -> set[str]:
    return {slug for value in values or [] if (slug := _slugify(value))}


def _resume_match_blob(text: str) -> str:
    tokens = re.split(r"[\s,;，；、。/|]+", text.lower())
    return " ".join(_slugify(token) for token in tokens if token)


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")
