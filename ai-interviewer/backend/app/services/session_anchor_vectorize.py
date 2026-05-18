"""Vectorization helpers for session-scoped candidate anchors."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.data.clean import redact_pii
from app.models.base import get_session as get_db_session
from app.models.session_anchor import SessionAnchorChunk
from app.services.resume_chunker import (
    ResumeChunk,
    ResumeChunkerMode,
    chunk_resume,
    extract_tech_keywords,
    infer_dimensions_hint,
)
from app.services.resume_embedding import (
    current_embedding_model_version,
    embed_chunks,
)

log = get_logger(__name__)


def vectorize_resume(
    *,
    session_id: str,
    resume_revision_id: str,
    source_artifact_id: str | None,
    raw_text: str,
    parsed: dict | None,
    db_session: Session | None = None,
) -> dict[str, Any]:
    """Normalize, chunk, redact, embed, and persist resume anchor rows."""

    mode, chunks = chunk_resume(raw_text or "", parsed if isinstance(parsed, dict) else None)
    base_status = {
        "source_type": "resume",
        "resume_revision_id": resume_revision_id,
        "source_artifact_id": source_artifact_id,
        "embedding_model_version": current_embedding_model_version(),
        "mode": mode.value,
        "chunk_count": 0,
        "skipped_reason": None,
        "error": None,
        "text_sha256": _sha256(raw_text or ""),
    }
    if mode is ResumeChunkerMode.D:
        return {
            **base_status,
            "status": "skipped",
            "skipped_reason": "mode_d_minimal_resume",
        }
    redacted_chunks = [_redacted_chunk(chunk) for chunk in chunks if chunk.text.strip()]
    if not redacted_chunks:
        return {
            **base_status,
            "status": "skipped",
            "skipped_reason": "empty_chunks",
        }
    try:
        texts = [chunk.text for chunk in redacted_chunks]
        vectors = embed_chunks(texts)
        expires_at = _expires_at()

        def write(session: Session) -> None:
            with session.begin_nested():
                for chunk, vector in zip(redacted_chunks, vectors, strict=True):
                    session.add(
                        SessionAnchorChunk(
                            session_id=session_id,
                            source_type="resume",
                            source_revision_id=resume_revision_id,
                            source_artifact_id=source_artifact_id,
                            source_turn_id=None,
                            chunk_index=chunk.chunk_index,
                            tier=chunk.tier,
                            section_name=chunk.section_name,
                            heading=chunk.heading,
                            project_name=chunk.project_name,
                            text=chunk.text,
                            tech_keywords=list(chunk.tech_keywords),
                            dimensions_hint=list(chunk.dimensions_hint),
                            chunker_mode=mode.value,
                            embedding_model_version=current_embedding_model_version(),
                            embedding=vector,
                            expires_at=expires_at,
                        )
                    )
                session.flush()

        _with_session(db_session, write)
        return {
            **base_status,
            "status": "ready",
            "chunk_count": len(redacted_chunks),
            "expires_at": expires_at.isoformat(),
        }
    except Exception as e:
        log.warning("vectorize_resume failed: session=%s error=%s", session_id, e)
        return {
            **base_status,
            "status": "failed",
            "error": str(e) or e.__class__.__name__,
        }


def vectorize_self_intro_anchor_cards(
    *,
    session_id: str,
    self_intro_revision_id: str,
    turn_idx: int,
    sanitized_answer: str,
    anchor_cards: list[dict[str, Any]],
    db_session: Session | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Clean, redact, embed, and persist opening self-intro anchor cards."""

    model_version = current_embedding_model_version()
    base_status = {
        "source_type": "self_intro",
        "self_intro_revision_id": self_intro_revision_id,
        "embedding_model_version": model_version,
        "mode": "SI",
        "chunk_count": 0,
        "skipped_reason": None,
        "error": None,
        "text_sha256": _sha256(sanitized_answer or ""),
    }
    if len(str(sanitized_answer or "").strip()) < int(
        get_settings().session_anchor_self_intro_min_chars or 200
    ):
        return {
            **base_status,
            "status": "skipped",
            "skipped_reason": "skipped_short",
        }

    cards = _clean_self_intro_cards(anchor_cards)
    if not cards:
        cards = build_self_intro_fallback_cards(profile or {}, sanitized_answer)
    if not cards:
        return {
            **base_status,
            "status": "skipped",
            "skipped_reason": "empty_anchor_cards",
        }

    redacted_cards = [_redacted_card(card, index) for index, card in enumerate(cards)]
    try:
        vectors = embed_chunks([card["text"] for card in redacted_cards])
        expires_at = _expires_at()

        def write(session: Session) -> None:
            with session.begin_nested():
                for card, vector in zip(redacted_cards, vectors, strict=True):
                    session.add(
                        SessionAnchorChunk(
                            session_id=session_id,
                            source_type="self_intro",
                            source_revision_id=self_intro_revision_id,
                            source_artifact_id=None,
                            source_turn_id=turn_idx,
                            chunk_index=card["chunk_index"],
                            tier="anchor_card",
                            section_name="self_intro",
                            heading=card["title"],
                            project_name=card.get("project_name"),
                            text=card["text"],
                            tech_keywords=card["tech_keywords"],
                            dimensions_hint=infer_dimensions_hint(
                                card["text"],
                                card["tech_keywords"],
                            ),
                            chunker_mode="SI",
                            embedding_model_version=model_version,
                            embedding=vector,
                            expires_at=expires_at,
                        )
                    )
                session.flush()

        _with_session(db_session, write)
        return {
            **base_status,
            "status": "ready",
            "chunk_count": len(redacted_cards),
            "expires_at": expires_at.isoformat(),
        }
    except Exception as e:
        log.warning("vectorize_self_intro failed: session=%s error=%s", session_id, e)
        return {
            **base_status,
            "status": "failed",
            "error": str(e) or e.__class__.__name__,
        }


def build_self_intro_fallback_cards(
    profile: dict[str, Any],
    sanitized_answer: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    summary = str((profile or {}).get("summary") or "").strip()
    if summary:
        cards.append(
            {
                "kind": "claim",
                "title": "Self-intro summary",
                "text": summary,
                "tech_keywords": extract_tech_keywords(summary),
            }
        )
    for project in _as_text_list((profile or {}).get("emphasized_projects"), limit=2):
        cards.append(
            {
                "kind": "project",
                "title": project[:80],
                "text": project,
                "tech_keywords": extract_tech_keywords(project),
            }
        )
    if not cards and str(sanitized_answer or "").strip():
        text = str(sanitized_answer).strip()[
            : int(get_settings().session_anchor_self_intro_card_max_chars or 500)
        ]
        cards.append(
            {
                "kind": "claim",
                "title": "Opening self-introduction",
                "text": text,
                "tech_keywords": extract_tech_keywords(text),
            }
        )
    return cards[: int(get_settings().session_anchor_self_intro_max_cards or 8)]


def _clean_self_intro_cards(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = {
        "project",
        "responsibility",
        "tech",
        "difficulty",
        "result",
        "claim",
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        text = " ".join(str(item.get("text") or "").split())
        if kind not in allowed or not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        title = str(item.get("title") or kind).strip()[:80]
        limit = int(get_settings().session_anchor_self_intro_card_max_chars or 500)
        cards.append(
            {
                "kind": kind,
                "title": title,
                "text": text[:limit],
                "tech_keywords": _as_text_list(item.get("tech_keywords"), limit=10),
                "project_name": title if kind == "project" else None,
            }
        )
        if len(cards) >= int(get_settings().session_anchor_self_intro_max_cards or 8):
            break
    return cards


def _redacted_chunk(chunk: ResumeChunk) -> ResumeChunk:
    redacted = redact_pii(chunk.text).cleaned
    keywords = extract_tech_keywords(redacted) or list(chunk.tech_keywords)
    return ResumeChunk(
        chunk_index=chunk.chunk_index,
        tier=chunk.tier,
        section_name=chunk.section_name,
        heading=chunk.heading,
        project_name=chunk.project_name,
        text=redacted,
        tech_keywords=keywords,
        dimensions_hint=infer_dimensions_hint(redacted, keywords),
    )


def _redacted_card(card: dict[str, Any], index: int) -> dict[str, Any]:
    redacted = redact_pii(str(card.get("text") or "")).cleaned
    keywords = _as_text_list(card.get("tech_keywords"), limit=10)
    if not keywords:
        keywords = extract_tech_keywords(redacted)
    return {
        "chunk_index": index,
        "title": str(card.get("title") or card.get("kind") or "anchor")[:80],
        "project_name": card.get("project_name"),
        "text": redacted,
        "tech_keywords": keywords,
    }


def _expires_at() -> datetime:
    return _now() + timedelta(
        hours=max(1, int(get_settings().resume_rag_session_ttl_hours or 24)) + 24
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _with_session(db_session: Session | None, fn):
    if db_session is not None:
        return fn(db_session)
    with get_db_session() as session:
        return fn(session)


def _as_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:120])
        if len(out) >= limit:
            break
    return out


def _now() -> datetime:
    return datetime.now(UTC)
