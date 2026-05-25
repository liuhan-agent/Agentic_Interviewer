"""Retriever for session-scoped candidate anchor chunks."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.base import get_session as get_db_session
from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_embedding import (
    current_embedding_model_version,
    embed_query,
)

_ANCHOR_WEIGHT = 0.7
_BOOST_WEIGHT = 0.2
_CONSTRAINT_WEIGHT = 0.1


@dataclass
class CandidateAnchorHit:
    id: int
    source_type: str
    source_revision_id: str
    chunk_index: int
    tier: str
    chunker_mode: str
    heading: str
    project_name: str
    text: str
    score: float
    distance: float
    adjusted_score: float
    anchor_score: float = 0.0
    boost_score: float = 0.0
    constraint_match: float = 0.0
    final_score: float = 0.0
    matched_target_skills: list[str] = field(default_factory=list)
    matched_dimensions: list[str] = field(default_factory=list)
    matched_seed_terms: list[str] = field(default_factory=list)
    deduped: bool = False
    dedupe_reason: str | None = None

    def as_artifact(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source_revision_id": self.source_revision_id,
            "chunk_index": self.chunk_index,
            "tier": self.tier,
            "chunker_mode": self.chunker_mode,
            "heading": self.heading,
            "project_name": self.project_name,
            "score": round(self.adjusted_score, 6),
            "raw_score": round(self.score, 6),
            "distance": round(self.distance, 6),
            "deduped": self.deduped,
            "dedupe_reason": self.dedupe_reason,
            "excerpt": self.text[:240],
            "anchor_score": round(self.anchor_score, 6),
            "boost_score": round(self.boost_score, 6),
            "constraint_match": round(self.constraint_match, 6),
            "final_score": round(self.final_score, 6),
            "matched_target_skills": list(self.matched_target_skills),
            "matched_dimensions": list(self.matched_dimensions),
            "matched_seed_terms": list(self.matched_seed_terms),
        }


@dataclass
class CandidateAnchorQueryProfile:
    anchor_terms: list[str] = field(default_factory=list)
    anchor_identity_terms: list[str] = field(default_factory=list)
    boost_terms: list[str] = field(default_factory=list)
    constraint_terms: list[str] = field(default_factory=list)
    dimension_terms: list[str] = field(default_factory=list)
    target_skill_terms: list[str] = field(default_factory=list)
    seed_terms: list[str] = field(default_factory=list)
    seed_match_terms: list[str] = field(default_factory=list)
    anchor_key: str = ""

    @property
    def query_terms(self) -> list[str]:
        return [
            *self.anchor_terms,
            *self.boost_terms,
            *self.constraint_terms,
        ]

    @property
    def query_text(self) -> str:
        return " ".join(self.query_terms).strip()

    @property
    def anchor_query_text(self) -> str:
        return " ".join(self.anchor_terms).strip()

    @property
    def boost_query_text(self) -> str:
        if not self.boost_terms:
            return ""
        return " ".join(_dedupe_texts([*self.anchor_identity_terms, *self.boost_terms])).strip()

    @property
    def constraint_query_text(self) -> str:
        return " ".join(self.constraint_terms).strip()


@dataclass
class ConstraintMatch:
    score: float = 0.0
    matched_target_skills: list[str] = field(default_factory=list)
    matched_dimensions: list[str] = field(default_factory=list)
    matched_seed_terms: list[str] = field(default_factory=list)


@dataclass
class CandidateAnchorRagResult:
    resume_block: str
    self_intro_block: str
    hits: list[CandidateAnchorHit]
    latency_ms: int
    fallback_reason: str | None
    skipped: bool
    query_terms: list[str] = field(default_factory=list)
    anchor_terms: list[str] = field(default_factory=list)
    boost_terms: list[str] = field(default_factory=list)
    constraint_terms: list[str] = field(default_factory=list)
    query_text: str = ""
    anchor_query_text: str = ""
    boost_query_text: str = ""
    constraint_query_text: str = ""
    anchor_key: str = ""
    boost_fallback_reason: str | None = None
    ranking_weights: dict[str, float] = field(default_factory=dict)

    def as_artifact(self, *, mode: str) -> dict[str, Any]:
        resume_block = (self.resume_block or "").strip()
        self_intro_block = (self.self_intro_block or "").strip()
        prompt_injected = mode == "primary" and bool(
            resume_block or self_intro_block
        )
        prompt_source_counts = {
            "resume": 1 if prompt_injected and resume_block else 0,
            "self_intro": 1 if prompt_injected and self_intro_block else 0,
        }
        return {
            "status": mode,
            "skipped": self.skipped,
            "fallback_reason": self.fallback_reason,
            "latency_ms": self.latency_ms,
            "query_terms": list(self.query_terms),
            "anchor_terms": list(self.anchor_terms),
            "boost_terms": list(self.boost_terms),
            "constraint_terms": list(self.constraint_terms),
            "query_text": self.query_text,
            "anchor_query_text": self.anchor_query_text,
            "boost_query_text": self.boost_query_text,
            "constraint_query_text": self.constraint_query_text,
            "anchor_key": self.anchor_key,
            "boost_fallback_reason": self.boost_fallback_reason,
            "ranking_weights": dict(self.ranking_weights),
            "hits": [hit.as_artifact() for hit in self.hits],
            "resume_hit_count": sum(1 for hit in self.hits if hit.source_type == "resume"),
            "self_intro_hit_count": sum(
                1 for hit in self.hits if hit.source_type == "self_intro"
            ),
            "prompt_injected": prompt_injected,
            "prompt_block_sources": [
                source for source, count in prompt_source_counts.items() if count > 0
            ],
            "prompt_source_counts": {
                source: count for source, count in prompt_source_counts.items() if count > 0
            },
            "prompt_block_chars": (
                len(resume_block) + len(self_intro_block) if prompt_injected else 0
            ),
        }


def retrieve_candidate_anchors(
    *,
    session_id: str,
    resume_revision_id: str | None,
    self_intro_revision_id: str | None,
    dimension: str,
    seed: dict | None,
    target_skills: list[str] | None,
    rule_anchor: dict | None,
    self_intro_profile: dict | None,
    db_session: Session | None = None,
    used_project_names: list[str] | None = None,
    embedding_override: dict[str, Any] | None = None,
) -> CandidateAnchorRagResult:
    started = time.perf_counter()
    if not session_id or not (resume_revision_id or self_intro_revision_id):
        return _result(
            started,
            fallback_reason="not_ready",
            skipped=True,
        )

    query_profile = _query_profile(
        dimension=dimension,
        seed=seed,
        target_skills=target_skills,
        rule_anchor=rule_anchor,
        self_intro_profile=self_intro_profile,
    )
    query_terms = query_profile.query_terms
    settings = get_settings()
    try:
        model_version = current_embedding_model_version(embedding_override)
    except Exception:
        return _result(
            started,
            fallback_reason="misconfig",
            query_profile=query_profile,
        )
    anchor_query_text = query_profile.anchor_query_text or query_profile.query_text
    anchor_vector = embed_query(
        anchor_query_text,
        timeout_ms=int(
            getattr(settings, "resume_rag_query_embedding_timeout_ms", None)
            or settings.resume_rag_timeout_ms
            or 3000
        ),
        embedding_override=embedding_override,
        cache_key=_query_cache_key(
            dimension=dimension,
            seed=seed,
            target_skills=target_skills or [],
            query_terms=query_profile.anchor_terms or query_terms,
            embedding_model_version=model_version,
        ),
    )
    if anchor_vector is None:
        return _result(
            started,
            fallback_reason="timeout",
            query_profile=query_profile,
        )
    boost_vector: list[float] | None = None
    boost_fallback_reason: str | None = None
    boost_query_text = query_profile.boost_query_text
    if query_profile.anchor_query_text and boost_query_text:
        boost_vector = embed_query(
            boost_query_text,
            timeout_ms=int(
                getattr(settings, "resume_rag_query_embedding_timeout_ms", None)
                or settings.resume_rag_timeout_ms
                or 3000
            ),
            embedding_override=embedding_override,
            cache_key=_query_cache_key(
                dimension=dimension,
                seed=seed,
                target_skills=target_skills or [],
                query_terms=_dedupe_texts(
                    [*query_profile.anchor_identity_terms, *query_profile.boost_terms]
                ),
                embedding_model_version=model_version,
            ),
        )
        if boost_vector is None:
            boost_fallback_reason = "timeout"

    rows = _with_session(
        db_session,
        lambda session: _fetch_rows(
            session=session,
            session_id=session_id,
            resume_revision_id=resume_revision_id,
            self_intro_revision_id=self_intro_revision_id,
            embedding_model_version=model_version,
        ),
    )
    threshold = float(settings.resume_rag_distance_threshold or 0.45)
    scored = [
        hit
        for row in rows
        if (
            hit := _hit_from_row(
                row,
                anchor_vector=anchor_vector,
                boost_vector=boost_vector,
                query_profile=query_profile,
                distance_threshold=threshold,
                used_project_names=used_project_names or [],
            )
        )
        is not None
    ]
    if not scored:
        return _result(
            started,
            fallback_reason="low_score" if rows else "empty",
            query_profile=query_profile,
            boost_fallback_reason=boost_fallback_reason,
        )

    resume_hits = _dedupe_resume_hits(
        [hit for hit in scored if hit.source_type == "resume"],
        rule_anchor=rule_anchor,
    )
    self_intro_hits = [
        hit for hit in scored if hit.source_type == "self_intro"
    ]
    resume_hits = sorted(
        resume_hits,
        key=lambda hit: hit.adjusted_score,
        reverse=True,
    )[: int(settings.session_anchor_top_k_resume or 2)]
    self_intro_hits = sorted(
        self_intro_hits,
        key=lambda hit: hit.adjusted_score,
        reverse=True,
    )[: int(settings.session_anchor_top_k_self_intro or 1)]
    kept = [*resume_hits, *self_intro_hits]
    if not kept:
        return _result(
            started,
            fallback_reason="empty",
            query_profile=query_profile,
            boost_fallback_reason=boost_fallback_reason,
        )

    block_max = int(settings.resume_rag_block_max_chars or 800)
    return _result(
        started,
        resume_block=_render_block(resume_hits, max_chars=block_max),
        self_intro_block=_render_block(
            self_intro_hits,
            max_chars=min(500, block_max),
        ),
        hits=kept,
        query_profile=query_profile,
        boost_fallback_reason=boost_fallback_reason,
    )


def _fetch_rows(
    *,
    session: Session,
    session_id: str,
    resume_revision_id: str | None,
    self_intro_revision_id: str | None,
    embedding_model_version: str,
) -> list[SessionAnchorChunk]:
    filters = []
    if resume_revision_id:
        filters.append(
            (SessionAnchorChunk.source_type == "resume")
            & (SessionAnchorChunk.source_revision_id == resume_revision_id)
        )
    if self_intro_revision_id:
        filters.append(
            (SessionAnchorChunk.source_type == "self_intro")
            & (SessionAnchorChunk.source_revision_id == self_intro_revision_id)
        )
    if not filters:
        return []
    stmt = (
        select(SessionAnchorChunk)
        .where(
            SessionAnchorChunk.session_id == session_id,
            SessionAnchorChunk.embedding_model_version == embedding_model_version,
            or_(*filters),
        )
        .limit(
            max(
                10,
                int(get_settings().session_anchor_top_k_resume or 2)
                + int(get_settings().session_anchor_top_k_self_intro or 1)
                + 8,
            )
        )
    )
    return list(session.scalars(stmt).all())


def _hit_from_row(
    row: SessionAnchorChunk,
    *,
    anchor_vector: list[float],
    boost_vector: list[float] | None,
    query_profile: CandidateAnchorQueryProfile,
    distance_threshold: float,
    used_project_names: list[str],
) -> CandidateAnchorHit | None:
    row_vector = _vector(row.embedding)
    anchor_distance = _cosine_distance(anchor_vector, row_vector)
    anchor_score = _score_for_distance(anchor_distance, distance_threshold)
    boost_distance = math.inf
    boost_score = 0.0
    if boost_vector is not None:
        boost_distance = _cosine_distance(boost_vector, row_vector)
        boost_score = _score_for_distance(boost_distance, distance_threshold)
    if anchor_score <= 0.0 and boost_score <= 0.0:
        return None
    constraint = _constraint_match(row, query_profile)
    score = max(anchor_score, boost_score)
    distance = min(
        anchor_distance if anchor_score > 0.0 else math.inf,
        boost_distance if boost_score > 0.0 else math.inf,
    )
    if math.isinf(distance):
        distance = min(anchor_distance, boost_distance)
    adjusted_score = (
        _ANCHOR_WEIGHT * anchor_score
        + _BOOST_WEIGHT * boost_score
        + _CONSTRAINT_WEIGHT * constraint.score
    )
    project = str(row.project_name or "").strip()
    if row.source_type == "resume" and project:
        used_counts = Counter(
            name.lower() for name in used_project_names if str(name or "").strip()
        )
        count = used_counts.get(project.lower(), 0)
        if count:
            penalty = float(get_settings().resume_rag_used_project_penalty or 0.05)
            adjusted_score = max(0.0, adjusted_score - (penalty * count))
    return CandidateAnchorHit(
        id=int(row.id or 0),
        source_type=str(row.source_type or ""),
        source_revision_id=str(row.source_revision_id or ""),
        chunk_index=int(row.chunk_index or 0),
        tier=str(row.tier or ""),
        chunker_mode=str(row.chunker_mode or ""),
        heading=str(row.heading or ""),
        project_name=project,
        text=str(row.text or ""),
        score=score,
        distance=distance,
        adjusted_score=adjusted_score,
        anchor_score=anchor_score,
        boost_score=boost_score,
        constraint_match=constraint.score,
        final_score=adjusted_score,
        matched_target_skills=constraint.matched_target_skills,
        matched_dimensions=constraint.matched_dimensions,
        matched_seed_terms=constraint.matched_seed_terms,
    )


def _dedupe_resume_hits(
    hits: list[CandidateAnchorHit],
    *,
    rule_anchor: dict | None,
) -> list[CandidateAnchorHit]:
    best_by_key: dict[tuple[str, str], CandidateAnchorHit] = {}
    for hit in hits:
        key = (hit.project_name, hit.heading)
        existing = best_by_key.get(key)
        if existing is None or hit.adjusted_score > existing.adjusted_score:
            best_by_key[key] = hit
    kept = list(best_by_key.values())
    rule_project = str((rule_anchor or {}).get("project_name") or "").strip().lower()
    if rule_project:
        for hit in kept:
            if hit.project_name.lower() == rule_project:
                hit.deduped = True
                hit.dedupe_reason = "rule_anchor_overlap"
    return kept


def _render_block(hits: list[CandidateAnchorHit], *, max_chars: int) -> str:
    lines: list[str] = []
    for hit in hits:
        if hit.source_type == "resume":
            header_bits = [bit for bit in (hit.project_name, hit.heading) if bit]
            header = " / ".join(header_bits)
            if hit.deduped:
                lines.append(f"[resume] {hit.text}")
            else:
                lines.append(f"[resume] {header}: {hit.text}" if header else f"[resume] {hit.text}")
        else:
            heading = f"{hit.heading}: " if hit.heading else ""
            lines.append(f"[self_intro] {heading}{hit.text}")
    rendered = "\n".join(lines)
    return rendered[:max_chars]


def _query_profile(
    *,
    dimension: str,
    seed: dict | None,
    target_skills: list[str] | None,
    rule_anchor: dict | None,
    self_intro_profile: dict | None,
) -> CandidateAnchorQueryProfile:
    return CandidateAnchorQueryProfile(
        anchor_terms=_anchor_query_terms(rule_anchor),
        anchor_identity_terms=_anchor_identity_terms(rule_anchor),
        boost_terms=_boost_query_terms(self_intro_profile),
        **_constraint_query_terms(
            dimension=dimension,
            seed=seed,
            target_skills=target_skills,
        ),
        anchor_key=_anchor_key(rule_anchor),
    )


def _anchor_query_terms(rule_anchor: dict | None) -> list[str]:
    if not isinstance(rule_anchor, dict):
        return []
    terms: list[str] = []
    terms.extend(_anchor_identity_terms(rule_anchor))
    for key in ("skills", "tech_stack", "question_anchors", "dimensions"):
        terms.extend(str(item).strip() for item in _as_text_list(rule_anchor.get(key)))
    terms.extend(_semantic_anchor_key_terms(_anchor_key(rule_anchor)))
    return _dedupe_texts(terms)


def _anchor_identity_terms(rule_anchor: dict | None) -> list[str]:
    if not isinstance(rule_anchor, dict):
        return []
    return _dedupe_texts(
        [str(rule_anchor.get(key) or "").strip() for key in ("label", "project_name")]
    )


def _boost_query_terms(self_intro_profile: dict | None) -> list[str]:
    terms: list[str] = []
    if isinstance(self_intro_profile, dict):
        for key in ("emphasized_projects", "emphasized_skills", "preferred_focus"):
            terms.extend(str(item).strip() for item in _as_text_list(self_intro_profile.get(key)))
    return _dedupe_texts(terms)


def _constraint_query_terms(
    *,
    dimension: str,
    seed: dict | None,
    target_skills: list[str] | None,
) -> dict[str, list[str]]:
    dimension_terms = _dedupe_texts([str(dimension or "").strip()])
    target_skill_terms = _dedupe_texts(
        [str(skill).strip() for skill in (target_skills or [])]
    )
    seed_terms: list[str] = []
    seed_match_terms: list[str] = []
    seed = seed or {}
    if isinstance(seed, dict):
        for key in ("scenario_brief", "title", "intent"):
            value = str(seed.get(key) or "").strip()
            if value:
                seed_terms.append(value)
                seed_match_terms.extend(_term_tokens(value))
    return {
        "constraint_terms": _dedupe_texts(
            [*dimension_terms, *target_skill_terms, *seed_terms]
        ),
        "dimension_terms": dimension_terms,
        "target_skill_terms": target_skill_terms,
        "seed_terms": _dedupe_texts(seed_terms),
        "seed_match_terms": _dedupe_texts(seed_match_terms),
    }


def _anchor_key(rule_anchor: dict | None) -> str:
    if not isinstance(rule_anchor, dict):
        return ""
    return str(rule_anchor.get("anchor_key") or "").strip()


def _semantic_anchor_key_terms(anchor_key: str) -> list[str]:
    key = str(anchor_key or "").strip().lower()
    if not key:
        return []
    raw_parts = [part for part in key.replace("_", "-").split("-") if part]
    if not raw_parts:
        return []
    if any(_looks_like_hash(part) for part in raw_parts):
        return []
    if raw_parts[0] == "focus":
        raw_parts = raw_parts[1:]
    ignored = {"global", "project", "proj"}
    semantic = [part for part in raw_parts if part not in ignored and not part.isdigit()]
    if len(semantic) < 2:
        return []
    return [" ".join(semantic)]


def _looks_like_hash(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) >= 8 and all(ch in "0123456789abcdef" for ch in text)


def _score_for_distance(distance: float, threshold: float) -> float:
    if distance >= threshold:
        return 0.0
    return max(0.0, 1.0 - distance)


def _constraint_match(
    row: SessionAnchorChunk,
    query_profile: CandidateAnchorQueryProfile,
) -> ConstraintMatch:
    target_matches = _matched_terms(
        query_profile.target_skill_terms,
        _row_search_blob(row, include_dimensions=False),
    )
    dimension_matches = _matched_terms(
        query_profile.dimension_terms,
        _row_search_blob(row, include_dimensions=True),
    )
    seed_matches = _matched_terms(
        query_profile.seed_match_terms,
        _row_search_blob(row, include_dimensions=False),
    )
    target_score = _ratio(target_matches, query_profile.target_skill_terms)
    dimension_score = _ratio(dimension_matches, query_profile.dimension_terms)
    seed_score = _ratio(seed_matches, query_profile.seed_match_terms)
    score = (
        0.5 * target_score
        + 0.3 * dimension_score
        + 0.2 * seed_score
    )
    return ConstraintMatch(
        score=round(score, 6),
        matched_target_skills=target_matches,
        matched_dimensions=dimension_matches,
        matched_seed_terms=seed_matches,
    )


def _matched_terms(terms: list[str], blob: str) -> list[str]:
    matches: list[str] = []
    for term in terms:
        normalized = _normalise_match_text(term)
        artifact_term = _artifact_match_term(term)
        if normalized and normalized in blob and artifact_term not in matches:
            matches.append(artifact_term)
    return matches


def _ratio(matches: list[str], terms: list[str]) -> float:
    normalized_terms = [_normalise_match_text(term) for term in terms]
    normalized_terms = [term for term in normalized_terms if term]
    if not normalized_terms:
        return 0.0
    return min(1.0, len(matches) / len(set(normalized_terms)))


def _row_search_blob(row: SessionAnchorChunk, *, include_dimensions: bool) -> str:
    parts = [
        str(row.heading or ""),
        str(row.project_name or ""),
        str(row.text or ""),
        " ".join(_as_text_list(row.tech_keywords)),
    ]
    if include_dimensions:
        parts.append(" ".join(_as_text_list(row.dimensions_hint)))
    return _normalise_match_text(" ".join(parts))


def _normalise_match_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text)


def _artifact_match_term(value: str) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().lower())


def _term_tokens(value: str) -> list[str]:
    text = _normalise_match_text(value)
    return re.findall(r"[\w\u4e00-\u9fff]+", text)


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _query_cache_key(
    *,
    dimension: str,
    seed: dict | None,
    target_skills: list[str],
    query_terms: list[str],
    embedding_model_version: str,
) -> str:
    seed_id = ""
    if isinstance(seed, dict):
        seed_id = str(seed.get("id") or seed.get("variant_id") or "").strip()
    self_intro_terms_sha = hashlib.sha1(
        "\n".join(query_terms).encode("utf-8")
    ).hexdigest()[:12]
    return (
        f"{embedding_model_version}|{dimension}|{seed_id}|"
        f"{','.join(target_skills)}|{self_intro_terms_sha}"
    )


def _dedupe_texts(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        converted = value.tolist()
        if isinstance(converted, list):
            return [float(item) for item in converted]
    if isinstance(value, list | tuple):
        return [float(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [float(item) for item in parsed]
        except Exception:
            return []
    return []


def _cosine_distance(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 1.0
    length = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(length))
    norm_a = math.sqrt(sum(a[i] * a[i] for i in range(length)))
    norm_b = math.sqrt(sum(b[i] * b[i] for i in range(length)))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return max(0.0, 1.0 - (dot / (norm_a * norm_b)))


def _result(
    started: float,
    *,
    resume_block: str = "",
    self_intro_block: str = "",
    hits: list[CandidateAnchorHit] | None = None,
    fallback_reason: str | None = None,
    skipped: bool = False,
    query_profile: CandidateAnchorQueryProfile | None = None,
    boost_fallback_reason: str | None = None,
) -> CandidateAnchorRagResult:
    query_profile = query_profile or CandidateAnchorQueryProfile()
    return CandidateAnchorRagResult(
        resume_block=resume_block,
        self_intro_block=self_intro_block,
        hits=hits or [],
        latency_ms=int((time.perf_counter() - started) * 1000),
        fallback_reason=fallback_reason,
        skipped=skipped,
        query_terms=query_profile.query_terms,
        anchor_terms=query_profile.anchor_terms,
        boost_terms=query_profile.boost_terms,
        constraint_terms=query_profile.constraint_terms,
        query_text=query_profile.query_text,
        anchor_query_text=query_profile.anchor_query_text,
        boost_query_text=query_profile.boost_query_text,
        constraint_query_text=query_profile.constraint_query_text,
        anchor_key=query_profile.anchor_key,
        boost_fallback_reason=boost_fallback_reason,
        ranking_weights={
            "anchor": _ANCHOR_WEIGHT,
            "boost": _BOOST_WEIGHT,
            "constraint": _CONSTRAINT_WEIGHT,
        },
    )


def _with_session(db_session: Session | None, fn):
    if db_session is not None:
        return fn(db_session)
    with get_db_session() as session:
        return fn(session)
