"""Retrieval orchestration used by the ``ask_question`` node.

Two modes:

- ``vector`` (default) : pure vector top-k via the vector store.
- ``hybrid``           : blend vector top-k with a BM25 overlay. The
  BM25 scorer is a tiny in-process implementation over the same
  document corpus; it costs nothing to run and reliably rescues
  keyword matches that embedding similarity misses.

Callers pick the mode via ``runtime_config.rag_mode``. Keeping both
implementations under one function means the ``ask_question`` node
never needs to know which backend answered.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger

from .ingestion import is_rag_source_allowed
from .vectorstore import RetrievedDoc, get_vectorstore

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


@dataclass
class RetrievalContext:
    docs: list[RetrievedDoc]
    as_prompt_block: str


def _bm25_scores(query: str, docs: list[RetrievedDoc], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    q_tokens = _tokenize(query)
    if not q_tokens or not docs:
        return [0.0] * len(docs)

    tokenized_docs = [_tokenize(d.text) for d in docs]
    doc_freqs = [Counter(tokens) for tokens in tokenized_docs]
    doc_lens = [len(tokens) for tokens in tokenized_docs]
    avgdl = sum(doc_lens) / len(doc_lens)
    N = len(docs)  # noqa: N806 — BM25 convention: ``N`` is the corpus size

    df: Counter[str] = Counter()
    for freqs in doc_freqs:
        for term in freqs.keys():
            df[term] += 1

    scores: list[float] = []
    for freqs, dl in zip(doc_freqs, doc_lens, strict=True):
        score = 0.0
        for q in q_tokens:
            if q not in freqs:
                continue
            idf = math.log(1 + (N - df[q] + 0.5) / (df[q] + 0.5))
            tf = freqs[q]
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avgdl)))
        scores.append(score)
    return scores


def _normalise(values: list[float]) -> list[float]:
    lo = min(values) if values else 0.0
    hi = max(values) if values else 1.0
    rng = hi - lo or 1.0
    return [(v - lo) / rng for v in values]


# Hard fallback used when neither caller, direction config, nor settings
# supply a value. 0.6 is the empirical sweet spot the retriever has been
# tuned at since launch — see ``docs/PLAN_HYBRID_ALPHA.md``.
_HYBRID_ALPHA_HARD_DEFAULT = 0.6


def _blend(
    base: list[RetrievedDoc],
    bm25_scores: list[float],
    *,
    alpha: float = _HYBRID_ALPHA_HARD_DEFAULT,
) -> list[RetrievedDoc]:
    """Linearly combine vector score and BM25 score.

    ``alpha`` weights the vector score; ``1-alpha`` weights BM25. The
    final score is re-attached to a fresh ``RetrievedDoc`` so the
    returned ordering matches the blended rank.
    """
    vec_norm = _normalise([d.score for d in base])
    bm25_norm = _normalise(bm25_scores)
    blended: list[RetrievedDoc] = []
    for doc, v, b in zip(base, vec_norm, bm25_norm, strict=True):
        final = alpha * v + (1.0 - alpha) * b
        blended.append(RetrievedDoc(text=doc.text, metadata=dict(doc.metadata), score=final))
    blended.sort(key=lambda d: d.score, reverse=True)
    return blended


def _filter_rag_docs(docs: list[RetrievedDoc], *, top_k: int) -> list[RetrievedDoc]:
    allowed = [
        doc
        for doc in docs
        if is_rag_source_allowed(str((doc.metadata or {}).get("source") or ""))
    ]
    return allowed[:top_k]


def _clamp_alpha(value: float) -> float:
    """Clamp ``alpha`` to the valid [0, 1] range.

    External JSON / .env values are user-controlled and may drift outside
    the unit interval; the linear blend would still run, but anything
    above 1 makes BM25 a *negative* term while anything below 0 inverts
    the vector signal. Both regress retrieval quality silently. The
    safer behaviour is a hard clamp at the resolution boundary.
    """
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _resolve_hybrid_alpha(
    *,
    explicit: float | None,
    direction_alpha: float | None,
    settings: Any,
) -> float:
    """Pick the hybrid blend weight to use for one ``retrieve_for_question`` call.

    Resolution order (first non-None wins):

    1. ``explicit`` — caller passed an explicit override (rare; primarily
       for unit tests).
    2. ``direction_alpha`` — value pulled from
       ``InterviewDirection.retrieval_alpha`` so each interview direction
       can dial vector vs. BM25 independently.
    3. ``settings.retrieval_alpha_default`` — operator-level default.
    4. :data:`_HYBRID_ALPHA_HARD_DEFAULT` — last-resort fallback so the
       function never raises on missing config.

    The resolved value is always clamped to [0, 1] before return.
    """
    if explicit is not None:
        return _clamp_alpha(float(explicit))
    if direction_alpha is not None:
        return _clamp_alpha(float(direction_alpha))
    settings_alpha = getattr(settings, "retrieval_alpha_default", None)
    if settings_alpha is not None:
        return _clamp_alpha(float(settings_alpha))
    return _HYBRID_ALPHA_HARD_DEFAULT


def _query_tail_signals(
    previous_qa: list[dict[str, Any]] | None,
    *,
    dimension: str,
    max_terms: int = 4,
) -> list[str]:
    """Pull weakness / must_cover tokens from the most recent same-dimension turn.

    On a refine round, the generator-evaluator pair has already told us
    *what to probe next*: ``evaluation.weaknesses`` and
    ``current_contract.must_cover``.  Feeding those back into the
    retrieval query sharpens the RAG from "generic dimension knowledge"
    to "knowledge about the exact gap we just saw".  Only the most
    recent turn on the same dimension is used so we stay responsive to
    immediate signals without drifting on older ones.
    """
    if not previous_qa:
        return []
    relevant = [qa for qa in previous_qa if qa.get("dimension") == dimension]
    if not relevant:
        relevant = previous_qa
    last = relevant[-1]
    evaluation = last.get("evaluation") or {}
    weaknesses = [str(w) for w in (evaluation.get("weaknesses") or []) if w]
    contract = last.get("contract") or evaluation.get("contract") or {}
    must_cover = [str(m) for m in (contract.get("must_cover") or []) if m]
    rubric_missing = [
        str(k)
        for k, v in (evaluation.get("rubric_coverage") or {}).items()
        if v == "missing"
    ]
    merged: list[str] = []
    for bucket in (weaknesses, rubric_missing, must_cover):
        for term in bucket:
            if term and term not in merged:
                merged.append(term)
            if len(merged) >= max_terms:
                return merged
    return merged


def retrieve_for_question(
    *,
    job_spec: dict[str, Any],
    dimension: str,
    previous_qa: list[dict[str, Any]] | None = None,
    resume_anchor: dict[str, Any] | None = None,
    target_skills: list[str] | None = None,
    top_k: int = 5,
    mode: str = "vector",
    alpha: float | None = None,
    direction_alpha: float | None = None,
) -> RetrievalContext:
    skills = " ".join(target_skills or job_spec.get("required_skills", []) or [])
    title = job_spec.get("title", "")
    direction = job_spec.get("interview_direction_label", "")
    tail = _query_tail_signals(previous_qa, dimension=dimension)
    anchor_parts: list[str] = []
    if resume_anchor:
        anchor_parts.extend(
            [
                str(resume_anchor.get("label") or ""),
                str(resume_anchor.get("project_name") or ""),
                " ".join(str(s) for s in (resume_anchor.get("tech_stack") or [])),
                " ".join(
                    str(s) for s in (resume_anchor.get("question_anchors") or [])
                ),
                " ".join(str(s) for s in (resume_anchor.get("skills") or [])),
            ]
        )
    parts = [title, direction, dimension, skills, *anchor_parts, *tail]
    query = " ".join(p for p in parts if p).strip()

    store = get_vectorstore()
    search_k = top_k * 4 if mode == "hybrid" else top_k * 3
    docs = store.similarity_search(query, k=search_k)
    docs = _filter_rag_docs(docs, top_k=search_k)

    if mode == "hybrid" and docs:
        # ``get_settings`` is imported lazily so the unit tests that
        # bypass the global settings (``test_target_skills.py`` etc.)
        # never have to monkeypatch it. The lazy import also keeps
        # ``retriever`` import-cost low for the much more common
        # ``mode='vector'`` path that does not need any blend config.
        from app.core.settings import get_settings

        resolved_alpha = _resolve_hybrid_alpha(
            explicit=alpha,
            direction_alpha=direction_alpha,
            settings=get_settings(),
        )
        bm25 = _bm25_scores(query, docs)
        docs = _blend(docs, bm25, alpha=resolved_alpha)[:top_k]
    else:
        docs = docs[:top_k]

    if not docs:
        log.info("retriever returned no docs for query=%r", query)
    lines = []
    for i, doc in enumerate(docs, start=1):
        tag = doc.metadata.get("source", "kb")
        lines.append(f"[{i}] ({tag}, score={doc.score:.2f}) {doc.text}")
    as_prompt_block = "\n".join(lines) if lines else "(no relevant knowledge retrieved)"
    return RetrievalContext(docs=docs, as_prompt_block=as_prompt_block)
