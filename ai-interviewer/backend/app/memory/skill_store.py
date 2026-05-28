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

import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import yaml
from sqlalchemy import select

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session
from app.models.skill_playbook import SkillPlaybookCard
from app.services.skill_usage_stats import (
    MIN_REWARDED_USES,
    REWARD_SHADOW_BONUS_WEIGHT,
    skill_usage_context_key,
)

log = get_logger(__name__)

SkillPlaybookBackend = Literal["file", "db", "db_with_file_fallback"]
_VALID_BACKENDS = {"file", "db", "db_with_file_fallback"}
_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SkillCache = tuple[Path, tuple[tuple[str, int, int], ...], list["SkillEntry"]]
_skill_cache: _SkillCache | None = None
SKILL_REWARD_ROLLOUT_MODES = {"metadata", "reward_shadow", "reward"}
DEFAULT_SKILL_REWARD_ROLLOUT_MODE = "reward_shadow"
MIN_REWARD_CANDIDATE_COUNT = 5
MAX_OVERRULE_RATE = 0.25


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
    display_name_zh: str = ""
    display_description_zh: str = ""
    status: str = "active"
    priority: int = 0
    direction_tags: list[str] = field(default_factory=list)
    role_tags: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    job_levels: list[str] = field(default_factory=list)
    probe_intents: list[str] = field(default_factory=list)
    failure_categories: list[str] = field(default_factory=list)
    generator_moves: list[str] = field(default_factory=list)
    watch_for: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    evaluator_rubric_hints: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)
    score_bias_rules: list[str] = field(default_factory=list)
    evaluator_visibility: bool = False
    body: str = ""
    match_score: float = 0.0
    match_reasons: list[str] = field(default_factory=list)
    reward_shadow_rank: int | None = None
    reward_shadow_score: float | None = None
    reward_shadow_rank_changed: bool = False
    usage_stats: dict[str, Any] | None = None
    reward_shadow_reason: dict[str, Any] | None = None


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
    try:
        parsed = yaml.safe_load(block) or {}
    except yaml.YAMLError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


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


def _text_list(values: Any) -> list[str]:
    if values is None:
        return []
    raw = values if isinstance(values, list) else [values]
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        text = str(value or "").strip()
        key = text.casefold()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def _bool_value(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else False


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
                display_name_zh=str(fm.get("display_name_zh", "")),
                display_description_zh=str(
                    fm.get("display_description_zh", "")
                ),
                status=_slugify(fm.get("status", "active")) or "active",
                priority=_int_value(fm.get("priority")),
                direction_tags=_slug_list(fm.get("direction_tags")),
                role_tags=_slug_list(fm.get("role_tags")),
                dimensions=_slug_list(fm.get("dimensions")),
                job_levels=_slug_list(fm.get("job_levels")),
                probe_intents=_slug_list(fm.get("probe_intents")),
                failure_categories=_slug_list(fm.get("failure_categories")),
                generator_moves=_text_list(fm.get("generator_moves")),
                watch_for=_text_list(fm.get("watch_for")),
                avoid=_text_list(fm.get("avoid")),
                evaluator_rubric_hints=_text_list(
                    fm.get("evaluator_rubric_hints")
                ),
                positive_signals=_text_list(fm.get("positive_signals")),
                negative_signals=_text_list(fm.get("negative_signals")),
                score_bias_rules=_text_list(fm.get("score_bias_rules")),
                evaluator_visibility=_bool_value(fm.get("evaluator_visibility")),
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
        display_name_zh=str(row.display_name_zh or ""),
        display_description_zh=str(row.display_description_zh or ""),
        status=_slugify(row.status or "active") or "active",
        priority=int(row.priority or 0),
        direction_tags=_list_value(row.direction_tags),
        role_tags=_list_value(row.role_tags),
        dimensions=_list_value(row.dimensions),
        job_levels=_list_value(row.job_levels),
        probe_intents=_list_value(row.probe_intents),
        failure_categories=_list_value(row.failure_categories),
        generator_moves=_list_value(row.generator_moves),
        watch_for=_list_value(row.watch_for),
        avoid=_list_value(row.avoid),
        evaluator_rubric_hints=_list_value(row.evaluator_rubric_hints),
        positive_signals=_list_value(row.positive_signals),
        negative_signals=_list_value(row.negative_signals),
        score_bias_rules=_list_value(row.score_bias_rules),
        evaluator_visibility=bool(row.evaluator_visibility),
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
    role_tag_values = _slug_list(role_tags)
    role_tag_set = set(role_tag_values)
    probe_intent_slug = _slugify(probe_intent)
    failure_set = set(_slug_list(failure_categories))
    context_key = skill_usage_context_key(
        role=_context_role(role_tag_values),
        job_level=job_level_slug,
        dimension=dimension_slug,
        probe_intent=probe_intent_slug,
    )

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
    keyword_hits = _apply_reward_ranking(
        scored,
        context_key=context_key,
        limit=limit,
    )

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


def _apply_reward_ranking(
    entries: list[SkillEntry],
    *,
    context_key: str,
    limit: int,
) -> list[SkillEntry]:
    if not entries:
        return []
    metadata_rank_by_skill = {entry.id: idx for idx, entry in enumerate(entries, 1)}
    mode = DEFAULT_SKILL_REWARD_ROLLOUT_MODE
    rollout_reason = ""
    try:
        from app.models.skill_playbook import SkillRewardRollout, SkillUsageStats

        skill_ids = [entry.id for entry in entries if entry.id]
        if not skill_ids:
            return [
                replace(
                    entry,
                    reward_shadow_reason={
                        "status": "no_skill_id",
                        "metadata_rank": idx,
                    },
                )
                for idx, entry in enumerate(entries[:limit], 1)
            ]
        with get_session() as session:
            stats_rows = list(
                session.scalars(
                    select(SkillUsageStats)
                    .where(SkillUsageStats.skill_id.in_(skill_ids))
                    .where(SkillUsageStats.skill_context_key == context_key)
                )
            )
            rollout = session.get(SkillRewardRollout, context_key)
            if rollout is not None:
                candidate_mode = str(getattr(rollout, "mode", "") or "").strip()
                if candidate_mode in SKILL_REWARD_ROLLOUT_MODES:
                    mode = candidate_mode
                rollout_reason = str(getattr(rollout, "reason", "") or "")
    except Exception as exc:  # pragma: no cover - diagnostic side channel
        log.debug("skill reward-shadow lookup failed: %s", exc)
        return [
            replace(
                entry,
                reward_shadow_reason={
                    "status": "stats_unavailable",
                    "metadata_rank": idx,
                },
            )
            for idx, entry in enumerate(entries[:limit], 1)
        ]

    stats_by_skill = {row.skill_id: row for row in stats_rows}
    reward_score_by_skill: dict[str, float] = {}
    for entry in entries:
        stats = stats_by_skill.get(entry.id)
        reward_score_by_skill[entry.id] = (
            _reward_shadow_score(entry, stats)
            if stats is not None
            else float(entry.match_score or 0.0)
        )
    reward_ranked = sorted(
        entries,
        key=lambda entry: (
            -reward_score_by_skill.get(entry.id, float(entry.match_score or 0.0)),
            entry.id or entry.path.name,
        ),
    )
    reward_rank_by_skill = {
        entry.id: idx
        for idx, entry in enumerate(reward_ranked, 1)
    }
    metadata_top = [entry.id for entry in entries[:limit]]
    reward_top = [entry.id for entry in reward_ranked[:limit]]
    rank_changed = metadata_top != reward_top
    rewarded_sample_count = sum(
        int(getattr(stats, "rewarded_uses", 0) or 0)
        for stats in stats_by_skill.values()
    )
    gate_reasons = _skill_reward_gate_reasons(
        candidate_count=len(entries),
        rewarded_sample_count=rewarded_sample_count,
        rank_changed=rank_changed,
        stats_rows=list(stats_by_skill.values()),
    )
    live_enabled = not gate_reasons
    live_order = (
        "reward"
        if mode == "reward" and live_enabled
        else "metadata_fallback"
        if mode == "reward"
        else "metadata"
        if mode == "metadata"
        else "reward_shadow"
    )
    selected_entries = reward_ranked[:limit] if live_order == "reward" else entries[:limit]

    output: list[SkillEntry] = []
    for entry in selected_entries:
        metadata_rank = metadata_rank_by_skill.get(entry.id)
        stats = stats_by_skill.get(entry.id)
        if stats is None:
            output.append(
                replace(
                    entry,
                    reward_shadow_rank=None,
                    reward_shadow_score=None,
                    reward_shadow_rank_changed=False,
                    usage_stats=None,
                    reward_shadow_reason={
                        "status": "no_stats",
                        "metadata_rank": metadata_rank,
                        "skill_context_key": context_key,
                        "candidate_count": len(entries),
                        "rewarded_sample_count": rewarded_sample_count,
                        "rollout_mode": mode,
                        "rollout_reason": rollout_reason,
                        "live_order": live_order,
                        "gate_reasons": gate_reasons,
                        "rank_changed": rank_changed,
                    },
                )
            )
            continue
        shadow_rank = reward_rank_by_skill.get(entry.id)
        output.append(
            replace(
                entry,
                reward_shadow_rank=shadow_rank,
                reward_shadow_score=_reward_shadow_score(entry, stats),
                reward_shadow_rank_changed=(
                    shadow_rank is not None and shadow_rank != metadata_rank
                ),
                usage_stats=_usage_stats_payload(stats),
                reward_shadow_reason=_reward_shadow_reason(
                    entry,
                    stats,
                    metadata_rank=metadata_rank,
                    shadow_rank=shadow_rank,
                    context_key=context_key,
                    rollout_mode=mode,
                    rollout_reason=rollout_reason,
                    live_order=live_order,
                    gate_reasons=gate_reasons,
                    candidate_count=len(entries),
                    rewarded_sample_count=rewarded_sample_count,
                    rank_changed=rank_changed,
                ),
            )
        )
    return output


def _apply_reward_shadow(
    entries: list[SkillEntry],
    *,
    context_key: str,
) -> list[SkillEntry]:
    return _apply_reward_ranking(entries, context_key=context_key, limit=len(entries))


def _skill_reward_gate_reasons(
    *,
    candidate_count: int,
    rewarded_sample_count: int,
    rank_changed: bool,
    stats_rows: list[Any],
) -> list[str]:
    reasons: list[str] = []
    if candidate_count < MIN_REWARD_CANDIDATE_COUNT:
        reasons.append("candidate_pool_below_min")
    if candidate_count < 2:
        reasons.append("single_skill_no_rank_effect")
    if rewarded_sample_count < MIN_REWARDED_USES:
        reasons.append("reward_samples_below_min")
    if any(
        getattr(row, "overrule_rate", None) is not None
        and float(getattr(row, "overrule_rate") or 0.0) > MAX_OVERRULE_RATE
        for row in stats_rows
    ):
        reasons.append("overrule_rate_high")
    if not rank_changed:
        reasons.append("reward_shadow_rank_same")
    return reasons


def _reward_shadow_score(entry: SkillEntry, stats: Any) -> float:
    sample_confidence = _sample_confidence(stats)
    reward_bonus = (
        float(getattr(stats, "avg_blended_reward", None) or 0.0)
        * REWARD_SHADOW_BONUS_WEIGHT
        * sample_confidence
    )
    usage_bonus = (
        math.log(int(getattr(stats, "uses", 0) or 0) + 1)
        * 0.1
        * sample_confidence
    )
    return float(entry.match_score or 0.0) + reward_bonus + usage_bonus


def _reward_shadow_reason(
    entry: SkillEntry,
    stats: Any,
    *,
    metadata_rank: int,
    shadow_rank: int | None,
    context_key: str,
    rollout_mode: str,
    rollout_reason: str,
    live_order: str,
    gate_reasons: list[str],
    candidate_count: int,
    rewarded_sample_count: int,
    rank_changed: bool,
) -> dict[str, Any]:
    sample_confidence = _sample_confidence(stats)
    return {
        "status": "scored",
        "skill_context_key": context_key,
        "uses": int(getattr(stats, "uses", 0) or 0),
        "injected_uses": int(getattr(stats, "injected_uses", 0) or 0),
        "rewarded_uses": int(getattr(stats, "rewarded_uses", 0) or 0),
        "avg_blended_reward": getattr(stats, "avg_blended_reward", None),
        "avg_immediate_reward": getattr(stats, "avg_immediate_reward", None),
        "pass_rate": getattr(stats, "pass_rate", None),
        "overrule_rate": getattr(stats, "overrule_rate", None),
        "sample_confidence": sample_confidence,
        "sample_status": (
            "ready"
            if int(getattr(stats, "rewarded_uses", 0) or 0) >= MIN_REWARDED_USES
            else "low_sample"
        ),
        "metadata_rank": metadata_rank,
        "metadata_score": float(entry.match_score or 0.0),
        "shadow_rank": shadow_rank,
        "reward_shadow_score": _reward_shadow_score(entry, stats),
        "candidate_count": candidate_count,
        "rewarded_sample_count": rewarded_sample_count,
        "rollout_mode": rollout_mode,
        "rollout_reason": rollout_reason,
        "live_order": live_order,
        "gate_reasons": gate_reasons,
        "rank_changed": rank_changed,
    }


def _usage_stats_payload(stats: Any) -> dict[str, Any]:
    return {
        "uses": int(getattr(stats, "uses", 0) or 0),
        "injected_uses": int(getattr(stats, "injected_uses", 0) or 0),
        "rewarded_uses": int(getattr(stats, "rewarded_uses", 0) or 0),
        "avg_score": getattr(stats, "avg_score", None),
        "pass_rate": getattr(stats, "pass_rate", None),
        "avg_immediate_reward": getattr(stats, "avg_immediate_reward", None),
        "avg_blended_reward": getattr(stats, "avg_blended_reward", None),
        "overrule_rate": getattr(stats, "overrule_rate", None),
    }


def _sample_confidence(stats: Any) -> float:
    return min(
        1.0,
        int(getattr(stats, "rewarded_uses", 0) or 0) / MIN_REWARDED_USES,
    )


def _context_role(role_tags: list[str]) -> str:
    concrete = [role for role in role_tags if role and role != "general"]
    return concrete[0] if concrete else "general"


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
        body = _generator_skill_body(e)
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


def _generator_skill_body(entry: SkillEntry) -> str:
    sections: list[str] = []
    for title, values in (
        ("Generator moves", entry.generator_moves),
        ("Watch for", entry.watch_for),
        ("Avoid", entry.avoid),
    ):
        items = _text_list(values)
        if not items:
            continue
        rendered = "\n".join(f"    - {item}" for item in items)
        sections.append(f"  {title}:\n{rendered}")
    if sections:
        return "\n".join(sections)
    return entry.body


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
