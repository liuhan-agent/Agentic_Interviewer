"""File-backed skill registry (Hermes-style).

Sibling of :mod:`app.memory.strategy_store`. Both implement the
"``MEMORY.md`` + topic files" pattern from Claude Code, but they
carry **different semantics** so the interview harness can keep them
independent:

- ``knowledge/strategy/`` is the reward-driven memory the
  ``strategy_dream`` agent maintains autonomously. Entries often
  carry ``auto_generated: true`` and exist because some historical
  signal (Thompson posteriors, outcomes) justified them.
- ``knowledge/skills/`` is the **hand-authored** business know-how
  layer — probe strategies, rubric templates, candidate-profile
  tells. Humans add / remove skills; the interview runtime only
  **reads** them.

The registry exposes:

- :func:`list_skills` — enumerate every skill file under
  ``knowledge/skills/`` (ignoring the ``SKILL.md`` index), or the
  DB-backed ``skill_playbook_cards`` registry when enabled.
- :func:`retrieve_skills` — rule-select cards by dimension, level, role,
  probe intent, and failure category.
- :func:`build_skills_block` — render relevance-matched skills into
  a compact markdown block suitable for splicing into the
  Generator's ``skills`` payload slot (``generator_task.md``).

Frontmatter contract (tolerant, per-field optional):

    ---
    name: Senior Backend Bar
    description: Probe high-ownership outcomes, not buzzwords.
    status: active
    priority: 7
    direction_tags: [internet_tech]
    role_tags: [java_backend]
    dimensions: [system_design, leadership]
    job_levels: [senior, staff]
    probe_intents: [evidence_probe]
    failure_categories: [missing_evidence]
    ---

    <body renders into prompts>
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session
from app.models.skill_playbook import SkillPlaybookCard

log = get_logger(__name__)

SkillPlaybookBackend = Literal["file", "db", "db_with_file_fallback"]
_VALID_BACKENDS = {"file", "db", "db_with_file_fallback"}
_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FM_FIELD = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)
_FM_LIST = re.compile(r"\[([^\]]*)\]")
_SkillCache = tuple[Path, tuple[tuple[str, int, int], ...], list["SkillEntry"]]
_skill_cache: _SkillCache | None = None


@dataclass
class SkillEntry:
    """One skill card read off disk.

    ``body`` is the markdown body with frontmatter stripped so callers
    can splice it directly into a prompt without re-parsing.
    """

    path: Path
    id: str = ""
    name: str = ""
    description: str = ""
    status: str = "active"
    priority: int = 0
    direction_tags: list[str] = field(default_factory=list)
    role_tags: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    job_levels: list[str] = field(default_factory=list)
    probe_intents: list[str] = field(default_factory=list)
    failure_categories: list[str] = field(default_factory=list)
    body: str = ""
    match_score: float = 0.0
    match_reasons: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the same YAML-ish frontmatter shape the strategy store uses.

    Kept as a separate local copy so ``skill_store`` does not reach
    into ``strategy_store``'s private helpers; if the frontmatter
    grammar ever changes we can evolve one surface at a time.
    """
    m = _FM_PATTERN.match(text)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, Any] = {}
    for fm in _FM_FIELD.finditer(block):
        key, val = fm.group(1), fm.group(2).strip()
        lm = _FM_LIST.match(val)
        if lm:
            items = [
                i.strip().strip("'\"")
                for i in lm.group(1).split(",")
                if i.strip()
            ]
            result[key] = items
        else:
            result[key] = val
    return result


def _strip_frontmatter(text: str) -> str:
    return _FM_PATTERN.sub("", text).strip()


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _slug_list(values: Any) -> list[str]:
    if values is None:
        return []
    raw = values if isinstance(values, list) else [values]
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        slug = _slugify(value)
        if slug and slug not in seen:
            out.append(slug)
            seen.add(slug)
    return out


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _skills_dir() -> Path:
    return get_settings().knowledge_dir / "skills"


def _skills_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    if not root.is_dir():
        return ()
    sig: list[tuple[str, int, int]] = []
    for p in sorted(root.glob("*.md")):
        if p.name == "SKILL.md":
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        sig.append((p.name, stat.st_mtime_ns, stat.st_size))
    return tuple(sig)


def clear_skill_cache_for_tests() -> None:
    global _skill_cache
    _skill_cache = None


def list_skills(
    *,
    backend: SkillPlaybookBackend | str | None = None,
) -> list[SkillEntry]:
    """Return every skill card from the configured playbook backend."""

    resolved_backend = _resolve_backend(backend)
    if resolved_backend == "file":
        return _list_file_skills()
    if resolved_backend == "db":
        try:
            return _list_db_skills()
        except Exception as exc:
            log.warning("skill playbook DB backend failed: %s", exc)
            return []

    try:
        db_entries = _list_db_skills()
    except Exception as exc:
        log.warning(
            "skill playbook DB backend failed; falling back to files: %s",
            exc,
        )
        return _list_file_skills()
    if any(entry.status == "active" for entry in db_entries):
        return db_entries
    return _list_file_skills()


def _list_file_skills() -> list[SkillEntry]:
    """Return every file-backed skill card, ignoring the ``SKILL.md`` index.

    Sorted lexicographically so retrieval is deterministic when two
    skills share the same relevance score.
    """
    global _skill_cache
    root = _skills_dir()
    if not root.is_dir():
        _skill_cache = None
        return []
    signature = _skills_signature(root)
    if (
        _skill_cache is not None
        and _skill_cache[0] == root
        and _skill_cache[1] == signature
    ):
        return list(_skill_cache[2])
    entries: list[SkillEntry] = []
    for p in sorted(root.glob("*.md")):
        if p.name == "SKILL.md":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        entry_id = _slugify(fm.get("id")) or _slugify(p.stem)
        entries.append(
            SkillEntry(
                path=p,
                id=entry_id,
                name=str(fm.get("name", p.stem)),
                description=str(fm.get("description", "")),
                status=_slugify(fm.get("status", "active")) or "active",
                priority=_int_value(fm.get("priority")),
                direction_tags=_slug_list(fm.get("direction_tags")),
                role_tags=_slug_list(fm.get("role_tags")),
                dimensions=_slug_list(fm.get("dimensions")),
                job_levels=_slug_list(fm.get("job_levels")),
                probe_intents=_slug_list(fm.get("probe_intents")),
                failure_categories=_slug_list(fm.get("failure_categories")),
                body=_strip_frontmatter(text),
            )
        )
    _skill_cache = (root, signature, entries)
    return list(entries)


def _list_db_skills() -> list[SkillEntry]:
    rows: list[SkillPlaybookCard]
    with get_session() as session:
        rows = list(
            session.scalars(
                select(SkillPlaybookCard)
                .where(SkillPlaybookCard.source == "manual_markdown")
                .order_by(SkillPlaybookCard.id.asc())
            )
        )
    return [_entry_from_db_card(row) for row in rows]


def _entry_from_db_card(row: SkillPlaybookCard) -> SkillEntry:
    card_id = str(row.id or "")
    return SkillEntry(
        path=Path(f"{card_id}.md"),
        id=card_id,
        name=str(row.name or card_id),
        description=str(row.description or ""),
        status=_slugify(row.status or "active") or "active",
        priority=int(row.priority or 0),
        direction_tags=_list_value(row.direction_tags),
        role_tags=_list_value(row.role_tags),
        dimensions=_list_value(row.dimensions),
        job_levels=_list_value(row.job_levels),
        probe_intents=_list_value(row.probe_intents),
        failure_categories=_list_value(row.failure_categories),
        body=str(row.body_markdown or ""),
    )


def _list_value(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value or "").strip()]


def _resolve_backend(backend: SkillPlaybookBackend | str | None) -> str:
    value = backend or getattr(
        get_settings(),
        "skill_playbook_backend",
        "db_with_file_fallback",
    )
    resolved = str(value or "db_with_file_fallback")
    if resolved not in _VALID_BACKENDS:
        log.warning(
            "unknown skill_playbook_backend=%s; using db_with_file_fallback",
            resolved,
        )
        return "db_with_file_fallback"
    return resolved


def retrieve_skills(
    *,
    dimension: str,
    job_level: str = "mid",
    limit: int = 3,
    use_llm_selector: bool = False,
    recent_qa_summary: str = "",
    direction_tags: list[str] | None = None,
    role_tags: list[str] | None = None,
    probe_intent: str | None = None,
    failure_categories: list[str] | None = None,
    backend: SkillPlaybookBackend | str | None = None,
) -> list[SkillEntry]:
    """Return skill cards relevant to the current ``(dimension, job_level)``.

    Strongly scoped cards must match their declared dimension / level /
    direction / role. Universal cards can still participate, but direct
    role and probe matches outrank them.

    ``use_llm_selector`` (``PLAN_LLM_MEMORY_SELECTOR``) opts into a
    second-pass LLM side-query on the keyword-filtered top-N: mirrors
    Claude Code's ``findRelevantMemories.sideQuery``. LLM failure or
    unparsable reply degrades silently to the keyword top-N so this
    kwarg can be flipped ON without new error paths at the call site.
    """
    dimension_slug = _slugify(dimension)
    job_level_slug = _slugify(job_level)
    direction_tag_set = set(_slug_list(direction_tags))
    role_tag_set = set(_slug_list(role_tags))
    probe_intent_slug = _slugify(probe_intent)
    failure_set = set(_slug_list(failure_categories))

    all_entries = list_skills(backend=backend)
    scored: list[SkillEntry] = []
    for entry in all_entries:
        ranked = _rank_skill_entry(
            entry,
            dimension=dimension_slug,
            job_level=job_level_slug,
            direction_tags=direction_tag_set,
            role_tags=role_tag_set,
            probe_intent=probe_intent_slug,
            failure_categories=failure_set,
        )
        if ranked is not None:
            scored.append(ranked)
    scored.sort(
        key=lambda e: (
            -float(e.match_score),
            -int(e.priority or 0),
            e.id or e.path.name,
        )
    )
    keyword_hits = scored[:limit]

    if not use_llm_selector or not keyword_hits:
        return keyword_hits

    # LLM second-pass (Claude Code ``findRelevantMemories`` equivalent).
    # The import is local so the base keyword path keeps no runtime
    # dependency on the LLM client — tests that only use keyword
    # retrieval stay free of the prompt-rendering / call_chat import
    # graph.
    from app.memory.llm_selector import (
        MemoryCandidate,
        SelectorContext,
        select_memories_with_llm,
    )

    candidates = [
        MemoryCandidate(
            filename=e.path.name,
            name=e.name,
            description=e.description,
            kind="skill",
            dimensions=list(e.dimensions),
            job_levels=list(e.job_levels),
        )
        for e in keyword_hits
    ]
    selected = select_memories_with_llm(
        candidates,
        SelectorContext(
            dimension=dimension,
            job_level=job_level,
            purpose="generator",
            recent_qa_summary=recent_qa_summary,
        ),
        top_n=limit,
    )
    if selected is None:
        # LLM failed → fall back to keyword top-N without changing shape.
        return keyword_hits
    if not selected:
        # LLM explicitly said "none relevant" — respect that and
        # return empty; callers already treat an empty list as "no
        # skill injected" and use the default placeholder.
        return []
    by_name = {e.path.name: e for e in keyword_hits}
    return [by_name[f] for f in selected if f in by_name]


def _rank_skill_entry(
    entry: SkillEntry,
    *,
    dimension: str,
    job_level: str,
    direction_tags: set[str],
    role_tags: set[str],
    probe_intent: str,
    failure_categories: set[str],
) -> SkillEntry | None:
    if entry.status != "active":
        return None
    if entry.dimensions and dimension not in set(entry.dimensions):
        return None
    if entry.job_levels and job_level not in set(entry.job_levels):
        return None

    entry_direction_tags = set(entry.direction_tags)
    if entry_direction_tags and not (entry_direction_tags & direction_tags):
        return None
    entry_role_tags = set(entry.role_tags)
    if (
        entry_role_tags
        and "general" not in entry_role_tags
        and not (entry_role_tags & role_tags)
    ):
        return None

    score = float(entry.priority or 0)
    reasons = [f"priority:{entry.priority}"]
    if entry.dimensions:
        score += 20.0
        reasons.append(f"dimension:{dimension}")
    else:
        score += 1.0
        reasons.append("dimension:universal")
    if entry.job_levels:
        score += 8.0
        reasons.append(f"job_level:{job_level}")
    else:
        score += 1.0
        reasons.append("job_level:universal")
    for tag in sorted(entry_direction_tags & direction_tags):
        score += 10.0
        reasons.append(f"direction_tag:{tag}")
    for tag in sorted(entry_role_tags & role_tags):
        score += 20.0
        reasons.append(f"role_tag:{tag}")
    if probe_intent and probe_intent in set(entry.probe_intents):
        score += 8.0
        reasons.append(f"probe_intent:{probe_intent}")
    for category in sorted(set(entry.failure_categories) & failure_categories):
        score += 12.0
        reasons.append(f"failure_category:{category}")

    return replace(entry, match_score=score, match_reasons=reasons)


def build_skills_block(
    entries: list[SkillEntry],
    *,
    max_body_chars: int = 600,
) -> str:
    """Render a list of skill cards into a compact markdown block.

    Returned string is splicing-ready for the Generator's ``skills``
    payload slot. An empty input list returns
    ``"(no relevant interview skills)"`` so the prompt template has a
    deterministic placeholder, matching the convention the strategy
    store uses for its "no match" case.

    Bodies are truncated to ``max_body_chars`` each; the full file
    stays on disk for operators who want to inspect it.
    """
    if not entries:
        return "(no relevant interview skills)"
    blocks: list[str] = []
    for i, e in enumerate(entries, 1):
        body = e.body
        truncated = ""
        if len(body) > max_body_chars:
            body = body[:max_body_chars]
            truncated = " [truncated — see knowledge/skills/ for full text]"
        dims = ", ".join(e.dimensions) if e.dimensions else "all"
        levels = ", ".join(e.job_levels) if e.job_levels else "all"
        blocks.append(
            f"[Skill {i}] {e.name}\n"
            f"  Applies to: dims={dims}, levels={levels}\n"
            f"  Why selected: {', '.join(e.match_reasons) or 'manual playbook match'}\n"
            f"  {e.description}\n\n"
            f"  {body}{truncated}"
        )
    return "\n\n".join(blocks)


def build_skills_index() -> str:
    """Tier-1 lightweight index (names + descriptions only).

    Intended for future ``dynamic_system`` wiring analogous to
    :func:`app.memory.strategy_store.build_strategy_index` — the LLM
    learns "what skill cards exist" without burning tokens on their
    full bodies. Not consumed by the current
    ``build_context_frame_for_generator`` path, but kept here so the
    Phase-3 follow-up that splits skill loading across tiers is a
    one-line change.
    """
    entries = list_skills()
    if not entries:
        return ""
    lines = [
        "## Available Interview Skills",
        "Scan the skills below. When authoring a question, if a skill "
        "matches the current dimension / job level, its full body "
        "will be provided in the SKILLS block.\n",
    ]
    for e in entries:
        dims = ", ".join(e.dimensions) if e.dimensions else "all"
        levels = ", ".join(e.job_levels) if e.job_levels else "all"
        lines.append(f"- {e.name} [{dims} | {levels}]: {e.description}")
    return "\n".join(lines)
