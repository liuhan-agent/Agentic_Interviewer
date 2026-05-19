"""Shadow LLM reranker for structured question candidates.

The reranker is observational in P1.1: it never changes the rule
selector's top candidate, prompt injection, rewards, or stats.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.engine.agents.llm_client import ChatMessage, call_chat, parse_json_response
from app.models.base import get_session
from app.models.question_bank import QuestionRerankUsage
from app.services.question_fit_profile import QuestionFitProfile
from app.services.question_selector import QuestionCandidate


@dataclass(frozen=True)
class QuestionRerankResult:
    status: str
    preferred_variant_id: str | None = None
    ranked_variant_ids: list[str] | None = None
    fit_scores: dict[str, float] | None = None
    anchor_choice: str | None = None
    reasons: list[str] | None = None
    confidence: float | None = None
    model: str | None = None
    latency_ms: int | None = None
    error: str | None = None

    def with_result(self, **kwargs: Any) -> QuestionRerankResult:
        return replace(self, **kwargs)

    def as_artifact(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "preferred_variant_id": self.preferred_variant_id,
            "ranked_variant_ids": list(self.ranked_variant_ids or []),
            "fit_scores": dict(self.fit_scores or {}),
            "anchor_choice": self.anchor_choice,
            "reasons": list(self.reasons or []),
            "confidence": self.confidence,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def rerank_question_candidates(
    *,
    candidates: Sequence[QuestionCandidate],
    fit_profile: QuestionFitProfile | None,
    question_selector_mode: str,
    enabled: bool,
    timeout_ms: int = 4000,
) -> QuestionRerankResult:
    top_candidates = list(candidates)[:3]
    if (
        not enabled
        or question_selector_mode == "vector"
        or len(top_candidates) < 2
    ):
        return QuestionRerankResult(status="skipped")

    allowed_ids = [candidate.variant_id for candidate in top_candidates]
    started = time.perf_counter()
    model = _model_name()
    try:
        raw = call_chat(
            _messages(top_candidates, fit_profile),
            json_mode=True,
            agent_role="question_reranker",
            request_timeout=max(0.1, int(timeout_ms or 4000) / 1000.0),
            max_retries=0,
            provider_max_retries=0,
        )
        data = parse_json_response(raw)
        if not data.get("ranked_variant_ids"):
            raise ValueError("missing ranked_variant_ids")
        ranked = _ranked_ids(data.get("ranked_variant_ids"), allowed_ids)
        fit_scores = _fit_scores(data.get("fit_scores"), allowed_ids)
        preferred = ranked[0] if ranked else None
        return QuestionRerankResult(
            status="ok",
            preferred_variant_id=preferred,
            ranked_variant_ids=ranked,
            fit_scores=fit_scores,
            anchor_choice=_optional_text(data.get("anchor_choice")),
            reasons=_string_list(data.get("reasons"))[:5],
            confidence=_float_or_none(data.get("confidence")),
            model=model,
            latency_ms=_latency_ms(started),
            error=None,
        )
    except Exception as exc:
        return QuestionRerankResult(
            status="error",
            preferred_variant_id=None,
            ranked_variant_ids=[],
            fit_scores={},
            anchor_choice=None,
            reasons=[],
            confidence=None,
            model=model,
            latency_ms=_latency_ms(started),
            error=str(exc)[:500],
        )


def record_question_rerank_usage(
    *,
    result: QuestionRerankResult,
    candidates: Sequence[QuestionCandidate],
    session_id: str,
    turn_idx: int,
    trace_id: str | None,
    dimension: str,
    probe_intent: str | None,
    question_selector_mode: str,
    session: Session | None = None,
) -> None:
    candidate_list = list(candidates)[:3]
    if not candidate_list or result.status == "skipped":
        return
    if session is None:
        with get_session() as sess:
            record_question_rerank_usage(
                result=result,
                candidates=candidate_list,
                session_id=session_id,
                turn_idx=turn_idx,
                trace_id=trace_id,
                dimension=dimension,
                probe_intent=probe_intent,
                question_selector_mode=question_selector_mode,
                session=sess,
            )
        return

    rule_top = candidate_list[0]
    id_to_seed = {candidate.variant_id: candidate.seed_id for candidate in candidate_list}
    row_id = _usage_id(
        session_id=session_id,
        turn_idx=turn_idx,
        trace_id=trace_id,
        question_selector_mode=question_selector_mode,
    )
    values = {
        "id": row_id,
        "session_id": session_id,
        "turn_idx": int(turn_idx),
        "trace_id": trace_id,
        "dimension": dimension,
        "probe_intent": probe_intent,
        "question_selector_mode": question_selector_mode,
        "rule_top_seed_id": rule_top.seed_id,
        "rule_top_variant_id": rule_top.variant_id,
        "llm_top_seed_id": id_to_seed.get(result.preferred_variant_id or ""),
        "llm_top_variant_id": result.preferred_variant_id,
        "candidate_variant_ids": [candidate.variant_id for candidate in candidate_list],
        "ranked_variant_ids": list(result.ranked_variant_ids or []),
        "fit_scores": dict(result.fit_scores or {}),
        "anchor_choice": result.anchor_choice,
        "reasons": list(result.reasons or []),
        "confidence": result.confidence,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "status": result.status,
        "error": result.error,
    }
    row = session.get(QuestionRerankUsage, row_id)
    if row is None:
        session.add(QuestionRerankUsage(**values))
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()


def _messages(
    candidates: Sequence[QuestionCandidate],
    fit_profile: QuestionFitProfile | None,
) -> list[ChatMessage]:
    profile = fit_profile.as_artifact() if fit_profile is not None else {}
    candidate_payload = [
        {
            "variant_id": candidate.variant_id,
            "rank": candidate.rank,
            "title": candidate.title,
            "intent": candidate.intent,
            "difficulty": candidate.difficulty,
            "scenario_brief": candidate.scenario_brief,
            "question_stem": candidate.question_stem,
            "skill_tags": candidate.skill_tags,
            "scenario_skill_tags": candidate.scenario_skill_tags,
            "resume_anchor_hints": candidate.resume_anchor_hints,
            "failure_categories": candidate.failure_categories,
            "rule_match_reasons": candidate.match_reasons,
        }
        for candidate in candidates
    ]
    system = (
        "You are a shadow reranker for interview question candidates. "
        "Return JSON only. Choose among the provided variant_id values only. "
        "Do not request more context and do not use external knowledge."
    )
    user = {
        "fit_profile": profile,
        "candidates": candidate_payload,
        "output_schema": {
            "ranked_variant_ids": ["variant id in best-to-worst order"],
            "fit_scores": {"variant_id": 0.0},
            "anchor_choice": "short anchor label or empty",
            "reasons": ["short reason"],
            "confidence": 0.0,
        },
    }
    return [
        ChatMessage("system", system),
        ChatMessage("user", json.dumps(user, ensure_ascii=False)),
    ]


def _ranked_ids(raw: Any, allowed_ids: list[str]) -> list[str]:
    values = _string_list(raw)
    invalid = [item for item in values if item not in allowed_ids]
    if invalid:
        raise ValueError(f"invalid rerank variant id(s): {invalid}")
    ranked: list[str] = []
    for item in values:
        if item not in ranked:
            ranked.append(item)
    for item in allowed_ids:
        if item not in ranked:
            ranked.append(item)
    return ranked


def _fit_scores(raw: Any, allowed_ids: list[str]) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    scores: dict[str, float] = {}
    for key, value in raw.items():
        variant_id = str(key or "")
        if variant_id not in allowed_ids:
            raise ValueError(f"invalid fit score variant id: {variant_id}")
        parsed = _float_or_none(value)
        if parsed is not None:
            scores[variant_id] = parsed
    return scores


def _usage_id(
    *,
    session_id: str,
    turn_idx: int,
    trace_id: str | None,
    question_selector_mode: str,
) -> str:
    material = f"{session_id}|{turn_idx}|{trace_id or ''}|{question_selector_mode}"
    digest = hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"question-rerank:{digest[:32]}"


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [text for item in raw if (text := str(item or "").strip())]


def _optional_text(raw: Any) -> str | None:
    text = str(raw or "").strip()
    return text or None


def _float_or_none(raw: Any) -> float | None:
    try:
        return float(raw)
    except Exception:
        return None


def _latency_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _model_name() -> str | None:
    settings = get_settings()
    return str(
        getattr(settings, "llm_model", None)
        or getattr(settings, "openai_model", None)
        or ""
    ) or None
