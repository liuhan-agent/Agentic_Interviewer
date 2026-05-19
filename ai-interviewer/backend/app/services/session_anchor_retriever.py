"""Retriever for session-scoped candidate anchor chunks."""
from __future__ import annotations

import hashlib
import json
import math
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
        }


@dataclass
class CandidateAnchorRagResult:
    resume_block: str
    self_intro_block: str
    hits: list[CandidateAnchorHit]
    latency_ms: int
    fallback_reason: str | None
    skipped: bool
    query_terms: list[str] = field(default_factory=list)

    def as_artifact(self, *, mode: str) -> dict[str, Any]:
        return {
            "status": mode,
            "skipped": self.skipped,
            "fallback_reason": self.fallback_reason,
            "latency_ms": self.latency_ms,
            "query_terms": list(self.query_terms),
            "hits": [hit.as_artifact() for hit in self.hits],
            "resume_hit_count": sum(1 for hit in self.hits if hit.source_type == "resume"),
            "self_intro_hit_count": sum(
                1 for hit in self.hits if hit.source_type == "self_intro"
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
) -> CandidateAnchorRagResult:
    started = time.perf_counter()
    if not session_id or not (resume_revision_id or self_intro_revision_id):
        return _result(
            started,
            fallback_reason="not_ready",
            skipped=True,
        )

    query_terms = _query_terms(
        dimension=dimension,
        seed=seed,
        target_skills=target_skills,
        rule_anchor=rule_anchor,
        self_intro_profile=self_intro_profile,
    )
    settings = get_settings()
    vector = embed_query(
        " ".join(query_terms),
        timeout_ms=int(settings.resume_rag_timeout_ms or 300),
        cache_key=_query_cache_key(
            dimension=dimension,
            seed=seed,
            target_skills=target_skills or [],
            query_terms=query_terms,
        ),
    )
    if vector is None:
        return _result(
            started,
            fallback_reason="timeout",
            query_terms=query_terms,
        )

    rows = _with_session(
        db_session,
        lambda session: _fetch_rows(
            session=session,
            session_id=session_id,
            resume_revision_id=resume_revision_id,
            self_intro_revision_id=self_intro_revision_id,
            embedding_model_version=current_embedding_model_version(),
        ),
    )
    threshold = float(settings.resume_rag_distance_threshold or 0.45)
    scored = [
        hit
        for row in rows
        if (
            hit := _hit_from_row(
                row,
                query_vector=vector,
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
            query_terms=query_terms,
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
            query_terms=query_terms,
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
        query_terms=query_terms,
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
    query_vector: list[float],
    distance_threshold: float,
    used_project_names: list[str],
) -> CandidateAnchorHit | None:
    distance = _cosine_distance(query_vector, _vector(row.embedding))
    if distance >= distance_threshold:
        return None
    score = max(0.0, 1.0 - distance)
    adjusted_score = score
    project = str(row.project_name or "").strip()
    if row.source_type == "resume" and project:
        used_counts = Counter(
            name.lower() for name in used_project_names if str(name or "").strip()
        )
        count = used_counts.get(project.lower(), 0)
        if count:
            penalty = float(get_settings().resume_rag_used_project_penalty or 0.05)
            adjusted_score = score * ((1 - penalty) ** count)
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


def _query_terms(
    *,
    dimension: str,
    seed: dict | None,
    target_skills: list[str] | None,
    rule_anchor: dict | None,
    self_intro_profile: dict | None,
) -> list[str]:
    terms: list[str] = []
    seed = seed or {}
    if isinstance(seed, dict):
        for key in ("scenario_brief", "title", "intent"):
            value = str(seed.get(key) or "").strip()
            if value:
                terms.append(value)
                break
    terms.append(str(dimension or "").strip())
    terms.extend(str(skill).strip() for skill in (target_skills or []))
    if isinstance(rule_anchor, dict):
        terms.append(str(rule_anchor.get("project_name") or "").strip())
    if isinstance(self_intro_profile, dict):
        for key in ("emphasized_projects", "emphasized_skills", "preferred_focus"):
            values = self_intro_profile.get(key)
            if isinstance(values, list):
                terms.extend(str(item).strip() for item in values)
    return _dedupe_texts(terms)


def _query_cache_key(
    *,
    dimension: str,
    seed: dict | None,
    target_skills: list[str],
    query_terms: list[str],
) -> str:
    seed_id = ""
    if isinstance(seed, dict):
        seed_id = str(seed.get("id") or seed.get("variant_id") or "").strip()
    self_intro_terms_sha = hashlib.sha1(
        "\n".join(query_terms).encode("utf-8")
    ).hexdigest()[:12]
    return f"{dimension}|{seed_id}|{','.join(target_skills)}|{self_intro_terms_sha}"


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
    query_terms: list[str] | None = None,
) -> CandidateAnchorRagResult:
    return CandidateAnchorRagResult(
        resume_block=resume_block,
        self_intro_block=self_intro_block,
        hits=hits or [],
        latency_ms=int((time.perf_counter() - started) * 1000),
        fallback_reason=fallback_reason,
        skipped=skipped,
        query_terms=query_terms or [],
    )


def _with_session(db_session: Session | None, fn):
    if db_session is not None:
        return fn(db_session)
    with get_db_session() as session:
        return fn(session)
