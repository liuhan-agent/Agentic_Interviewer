"""Strategy memory retrieval and persistence.

The production runtime is DB-backed: active rows in ``strategy_memories``
are retrieved, attributed through ``strategy_memory_usages``, and ranked
against ``strategy_memory_stats`` when reward ranking is enabled.

The legacy file backend remains as a dev/test fallback and seed source
for ``knowledge/strategy/*.md``. Keeping both backends behind the same
functions lets the workflow consume strategy memories without knowing
whether they came from imported markdown seeds or promoted DB signals.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import log as math_log
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session
from app.models.strategy_memory import (
    StrategyMemory,
    StrategyMemoryStats,
    StrategyRewardRollout,
)

log = get_logger(__name__)


def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically via a temp file + rename."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FM_FIELD = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)
_FM_LIST = re.compile(r"\[([^\]]*)\]")
_StrategyCache = tuple[Path, tuple[tuple[str, int, int], ...], list["StrategyEntry"]]
_strategy_cache: _StrategyCache | None = None
MIN_REWARD_RANKING_CANDIDATES = 5
MIN_REWARD_RANKING_USES = 20
MAX_REWARD_RANKING_OVERRULE_RATE = 0.25
REWARD_SCOPE_WEIGHTS = {
    "exact": 1.0,
    "fallback": 0.5,
    "global": 0.15,
    "none": 0.0,
}
STRATEGY_RANKING_MODES = {"metadata", "reward_shadow", "reward"}


@dataclass
class StrategyEntry:
    path: Path
    id: str | None = None
    slug: str | None = None
    memory_key: str | None = None
    name: str = ""
    description: str = ""
    display_name_zh: str = ""
    display_description_zh: str = ""
    entry_type: str = "strategy"
    source: str = "file"
    status: str = "active"
    quality_reason: str | None = None
    promotion_stage: str = ""
    confidence: float = 0.0
    support_count: int = 0
    priority: int = 0
    ranking_score: float = 0.0
    ranking_reason: dict[str, Any] = field(default_factory=dict)
    shadow_rank: int | None = None
    dimensions: list[str] = field(default_factory=list)
    job_levels: list[str] = field(default_factory=list)
    body: str = ""


@dataclass(frozen=True)
class _StrategyStatsMatch:
    stats: StrategyMemoryStats | None
    context_key: str | None
    scope: str
    requested_context_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _RewardRankingDetails:
    score: float
    sample_confidence: float
    scope_weight: float
    reward_bonus: float
    usage_bonus: float
    overrule_penalty: float
    gate_status: str
    gate_reasons: list[str]


@dataclass(frozen=True)
class _StrategyRankingModeSelection:
    mode: str
    source: str
    context_key: str | None = None


def _parse_frontmatter(text: str) -> dict[str, Any]:
    m = _FM_PATTERN.match(text)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, Any] = {}
    for fm in _FM_FIELD.finditer(block):
        key, val = fm.group(1), fm.group(2).strip()
        lm = _FM_LIST.match(val)
        if lm:
            items = [i.strip().strip("'\"") for i in lm.group(1).split(",") if i.strip()]
            result[key] = items
        else:
            result[key] = val
    return result


def _strip_frontmatter(text: str) -> str:
    return _FM_PATTERN.sub("", text).strip()


def _strategy_dir() -> Path:
    return get_settings().knowledge_dir / "strategy"


def _strategy_backend() -> str:
    return str(getattr(get_settings(), "strategy_memory_backend", "file") or "file")


def _strategy_ranking_mode() -> str:
    mode = str(
        getattr(get_settings(), "strategy_memory_ranking_mode", "metadata")
        or "metadata"
    )
    return mode if mode in STRATEGY_RANKING_MODES else "metadata"


def _strategy_ranking_mode_selection(
    policy_context_keys: list[str] | None,
) -> _StrategyRankingModeSelection:
    override = _strategy_reward_rollout_override(policy_context_keys)
    if override is not None:
        return override
    return _StrategyRankingModeSelection(
        mode=_strategy_ranking_mode(),
        source="global_setting",
        context_key=None,
    )


def _strategy_reward_rollout_override(
    policy_context_keys: list[str] | None,
) -> _StrategyRankingModeSelection | None:
    requested_context_keys = _normalize_context_keys(policy_context_keys)
    if not requested_context_keys:
        return None
    try:
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(StrategyRewardRollout).where(
                        StrategyRewardRollout.context_key.in_(requested_context_keys)
                    )
                )
            )
    except Exception as exc:  # pragma: no cover - retrieval must stay best-effort
        log.warning("strategy reward rollout lookup failed: %s", exc)
        return None
    rows_by_key = {row.context_key: row for row in rows}
    for context_key in requested_context_keys:
        row = rows_by_key.get(context_key)
        mode = str(getattr(row, "mode", "") or "").strip() if row else ""
        if mode in STRATEGY_RANKING_MODES:
            return _StrategyRankingModeSelection(
                mode=mode,
                source="context_override",
                context_key=context_key,
            )
    return None


def _strategy_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    if not root.is_dir():
        return ()
    sig: list[tuple[str, int, int]] = []
    for p in sorted(root.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        sig.append((p.name, stat.st_mtime_ns, stat.st_size))
    return tuple(sig)


def clear_strategy_cache_for_tests() -> None:
    global _strategy_cache
    _strategy_cache = None


def list_strategies() -> list[StrategyEntry]:
    if _strategy_backend() == "db":
        return _list_db_strategies()
    return _list_file_strategies()


def _list_db_strategies() -> list[StrategyEntry]:
    with get_session() as session:
        rows = list(
            session.scalars(
                select(StrategyMemory)
                .where(StrategyMemory.status == "active")
                .order_by(StrategyMemory.slug.asc())
            )
        )
    return [
        StrategyEntry(
            path=Path(f"{row.slug}.md"),
            id=row.id,
            slug=row.slug,
            memory_key=row.memory_key,
            name=row.name,
            description=row.description,
            display_name_zh=str(getattr(row, "display_name_zh", "") or ""),
            display_description_zh=str(
                getattr(row, "display_description_zh", "") or ""
            ),
            entry_type="strategy",
            source=row.source,
            status=row.status,
            quality_reason=row.quality_reason,
            promotion_stage=row.promotion_stage,
            confidence=float(row.confidence or 0.0),
            support_count=int(row.support_count or 0),
            priority=int(row.priority or 0),
            dimensions=list(row.dimensions or []),
            job_levels=list(row.job_levels or []),
            body=row.body_markdown or "",
        )
        for row in rows
    ]


def _list_file_strategies() -> list[StrategyEntry]:
    global _strategy_cache
    root = _strategy_dir()
    if not root.is_dir():
        _strategy_cache = None
        return []
    signature = _strategy_signature(root)
    if (
        _strategy_cache is not None
        and _strategy_cache[0] == root
        and _strategy_cache[1] == signature
    ):
        return list(_strategy_cache[2])
    entries: list[StrategyEntry] = []
    for p in sorted(root.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        entries.append(StrategyEntry(
            path=p,
            slug=p.stem,
            name=fm.get("name", p.stem),
            description=fm.get("description", ""),
            display_name_zh=str(fm.get("display_name_zh", "")),
            display_description_zh=str(fm.get("display_description_zh", "")),
            entry_type=fm.get("type", "strategy"),
            source="file",
            status="active",
            dimensions=fm.get("dimensions", []),
            job_levels=fm.get("job_levels", []),
            body=_strip_frontmatter(text),
        ))
    _strategy_cache = (root, signature, entries)
    return list(entries)


def retrieve_strategies(
    *,
    dimension: str,
    job_level: str = "mid",
    limit: int = 3,
    use_llm_selector: bool = False,
    recent_qa_summary: str = "",
    policy_context_keys: list[str] | None = None,
) -> list[StrategyEntry]:
    """Return strategy entries relevant to the given dimension and level.

    ``use_llm_selector`` (``PLAN_LLM_MEMORY_SELECTOR``) opts into the
    same second-pass LLM sideQuery that :func:`retrieve_skills` uses.
    Kept signature-parallel so ``ask_question_node`` can flip both
    layers with one flag.
    """
    all_entries = list_strategies()
    scored: list[tuple[int, StrategyEntry]] = []
    for entry in all_entries:
        score = 0
        if entry.dimensions:
            if dimension not in entry.dimensions:
                continue
            score += 2
        else:
            score += 1
        if entry.job_levels:
            if job_level not in entry.job_levels:
                continue
            score += 1
        scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    keyword_hits = _rank_strategy_hits(
        scored,
        limit=limit,
        policy_context_keys=policy_context_keys,
    )

    if not use_llm_selector or not keyword_hits:
        return keyword_hits

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
            kind="strategy",
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
        return keyword_hits
    if not selected:
        return []
    by_name = {e.path.name: e for e in keyword_hits}
    return [by_name[f] for f in selected if f in by_name]


def _rank_strategy_hits(
    scored: list[tuple[int, StrategyEntry]],
    *,
    limit: int,
    policy_context_keys: list[str] | None = None,
) -> list[StrategyEntry]:
    metadata_hits = [entry for score, entry in scored if score > 0]
    if not metadata_hits:
        return []

    mode_selection = _strategy_ranking_mode_selection(policy_context_keys)
    mode = mode_selection.mode
    if mode not in {"reward_shadow", "reward"}:
        return metadata_hits[:limit]

    metadata_scores = {id(entry): score for score, entry in scored}
    stats_by_strategy = _load_strategy_stats(
        metadata_hits,
        policy_context_keys=policy_context_keys,
    )
    details_by_entry = {
        id(entry): _reward_ranking_details(
            base_score=metadata_scores.get(id(entry), 0),
            priority=entry.priority,
            stats_match=stats_by_strategy.get(entry.id or ""),
            candidate_count=len(metadata_hits),
        )
        for entry in metadata_hits
    }
    reward_ranked = sorted(
        metadata_hits,
        key=lambda entry: _reward_ranking_score(
            entry,
            base_score=metadata_scores.get(id(entry), 0),
            stats_match=stats_by_strategy.get(entry.id or ""),
            details=details_by_entry.get(id(entry)),
        ),
        reverse=True,
    )
    live_reward_enabled = _live_reward_ranking_enabled(
        list(details_by_entry.values()),
        candidate_count=len(metadata_hits),
    )
    live_order = (
        "reward"
        if mode == "reward" and live_reward_enabled
        else "metadata_fallback"
        if mode == "reward"
        else "reward_shadow"
    )
    for idx, entry in enumerate(reward_ranked, 1):
        entry.shadow_rank = idx
    for entry in metadata_hits:
        stats_match = stats_by_strategy.get(entry.id or "")
        entry.ranking_score = _reward_ranking_score(
            entry,
            base_score=metadata_scores.get(id(entry), 0),
            stats_match=stats_match,
            details=details_by_entry.get(id(entry)),
        )
        entry.ranking_reason = _ranking_reason(
            entry,
            base_score=metadata_scores.get(id(entry), 0),
            stats_match=stats_match,
            details=details_by_entry.get(id(entry)),
            live_order=live_order,
            mode_selection=mode_selection,
        )

    if mode == "reward" and live_reward_enabled:
        return reward_ranked[:limit]
    return metadata_hits[:limit]


def _load_strategy_stats(
    entries: list[StrategyEntry],
    *,
    policy_context_keys: list[str] | None = None,
) -> dict[str, _StrategyStatsMatch]:
    requested_context_keys = _normalize_context_keys(policy_context_keys)
    context_order = [*requested_context_keys, "__global__"]
    strategy_ids = [entry.id for entry in entries if entry.id]
    if not strategy_ids:
        return {}
    with get_session() as session:
        rows = list(
            session.scalars(
                select(StrategyMemoryStats)
                .where(StrategyMemoryStats.strategy_id.in_(strategy_ids))
                .where(StrategyMemoryStats.context_key.in_(context_order))
            )
        )
    rows_by_key = {
        (row.strategy_id, row.context_key): row
        for row in rows
    }
    return {
        strategy_id: _select_stats_match(
            strategy_id,
            rows_by_key=rows_by_key,
            context_order=context_order,
            requested_context_keys=requested_context_keys,
        )
        for strategy_id in strategy_ids
    }


def _normalize_context_keys(policy_context_keys: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for key in policy_context_keys or []:
        value = str(key or "").strip()
        if not value or value == "__global__" or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _select_stats_match(
    strategy_id: str,
    *,
    rows_by_key: dict[tuple[str, str], StrategyMemoryStats],
    context_order: list[str],
    requested_context_keys: list[str],
) -> _StrategyStatsMatch:
    for idx, context_key in enumerate(context_order):
        row = rows_by_key.get((strategy_id, context_key))
        if row is None:
            continue
        if context_key == "__global__":
            scope = "global"
        elif idx == 0:
            scope = "exact"
        else:
            scope = "fallback"
        return _StrategyStatsMatch(
            stats=row,
            context_key=context_key,
            scope=scope,
            requested_context_keys=list(requested_context_keys),
        )
    return _StrategyStatsMatch(
        stats=None,
        context_key=None,
        scope="none",
        requested_context_keys=list(requested_context_keys),
    )


def _reward_ranking_score(
    entry: StrategyEntry,
    *,
    base_score: int,
    stats_match: _StrategyStatsMatch | None,
    details: _RewardRankingDetails | None = None,
) -> float:
    if details is not None:
        return details.score
    score = float(base_score + entry.priority)
    stats = stats_match.stats if stats_match is not None else None
    if stats is None:
        return score
    avg_reward = float(stats.avg_blended_reward or 0.0)
    uses = max(0, int(stats.uses or 0))
    overrule_rate = float(stats.overrule_rate or 0.0)
    return (
        score
        + (avg_reward * 0.5)
        + (math_log(uses + 1) * 0.1)
        - (overrule_rate * 0.5)
    )


def _reward_ranking_details(
    *,
    base_score: int,
    priority: int,
    stats_match: _StrategyStatsMatch | None,
    candidate_count: int,
) -> _RewardRankingDetails:
    score = float(base_score + priority)
    stats = stats_match.stats if stats_match is not None else None
    scope = stats_match.scope if stats_match is not None else "none"
    scope_weight = REWARD_SCOPE_WEIGHTS.get(scope, 0.0)
    gate_reasons: list[str] = []
    avg_reward = (
        float(stats.avg_blended_reward)
        if stats and stats.avg_blended_reward is not None
        else None
    )
    uses = max(0, int(stats.uses or 0)) if stats is not None else 0
    overrule_rate = float(stats.overrule_rate or 0.0) if stats is not None else 0.0
    sample_confidence = min(1.0, uses / MIN_REWARD_RANKING_USES)

    if candidate_count < MIN_REWARD_RANKING_CANDIDATES:
        gate_reasons.append("candidate_pool_below_min")
    if stats is None or avg_reward is None:
        gate_reasons.append("missing_reward_stats")
    if scope == "global":
        gate_reasons.append("global_prior_only")
    if stats is not None and uses < MIN_REWARD_RANKING_USES:
        gate_reasons.append("reward_samples_below_min")
    if overrule_rate > MAX_REWARD_RANKING_OVERRULE_RATE:
        gate_reasons.append("overrule_rate_high")

    reward_bonus = (
        (avg_reward or 0.0)
        * 0.5
        * scope_weight
        * sample_confidence
    )
    usage_bonus = math_log(uses + 1) * 0.1 * scope_weight * sample_confidence
    overrule_penalty = overrule_rate * 0.5 * scope_weight
    score = score + reward_bonus + usage_bonus - overrule_penalty
    gate_status = "eligible" if not gate_reasons else "gated"
    return _RewardRankingDetails(
        score=score,
        sample_confidence=sample_confidence,
        scope_weight=scope_weight,
        reward_bonus=reward_bonus,
        usage_bonus=usage_bonus,
        overrule_penalty=overrule_penalty,
        gate_status=gate_status,
        gate_reasons=gate_reasons,
    )


def _live_reward_ranking_enabled(
    details: list[_RewardRankingDetails],
    *,
    candidate_count: int,
) -> bool:
    if candidate_count < MIN_REWARD_RANKING_CANDIDATES:
        return False
    return any(detail.gate_status == "eligible" for detail in details)


def _ranking_reason(
    entry: StrategyEntry,
    *,
    base_score: int,
    stats_match: _StrategyStatsMatch | None,
    details: _RewardRankingDetails | None = None,
    live_order: str | None = None,
    mode_selection: _StrategyRankingModeSelection | None = None,
) -> dict[str, Any]:
    requested_context_keys = (
        list(stats_match.requested_context_keys)
        if stats_match is not None
        else []
    )
    stats = stats_match.stats if stats_match is not None else None
    mode_payload = {
        "ranking_mode": mode_selection.mode if mode_selection else None,
        "ranking_mode_source": mode_selection.source if mode_selection else None,
        "ranking_mode_context_key": mode_selection.context_key
        if mode_selection
        else None,
    }
    if stats is None:
        return {
            **mode_payload,
            "base_score": base_score,
            "priority": entry.priority,
            "uses": 0,
            "requested_context_keys": requested_context_keys,
            "stats_context_key": None,
            "stats_scope": "none",
            "scope_weight": details.scope_weight if details else 0.0,
            "sample_confidence": details.sample_confidence if details else 0.0,
            "reward_bonus": details.reward_bonus if details else 0.0,
            "usage_bonus": details.usage_bonus if details else 0.0,
            "overrule_penalty": details.overrule_penalty if details else 0.0,
            "gate_status": details.gate_status if details else "gated",
            "gate_reasons": details.gate_reasons if details else ["missing_reward_stats"],
            "live_order": live_order,
        }
    return {
        **mode_payload,
        "base_score": base_score,
        "priority": entry.priority,
        "uses": stats.uses,
        "avg_blended_reward": stats.avg_blended_reward,
        "overrule_rate": stats.overrule_rate,
        "requested_context_keys": requested_context_keys,
        "stats_context_key": stats_match.context_key if stats_match else None,
        "stats_scope": stats_match.scope if stats_match else "none",
        "scope_weight": details.scope_weight if details else 0.0,
        "sample_confidence": details.sample_confidence if details else 0.0,
        "reward_bonus": details.reward_bonus if details else 0.0,
        "usage_bonus": details.usage_bonus if details else 0.0,
        "overrule_penalty": details.overrule_penalty if details else 0.0,
        "gate_status": details.gate_status if details else "gated",
        "gate_reasons": details.gate_reasons if details else [],
        "live_order": live_order,
    }


def build_strategy_index() -> str:
    """Tier 1: lightweight index for the system prompt.

    Returns a compact catalog of all available strategies (name +
    description only, no body text) so the LLM knows what experience
    exists without burning tokens on full content.
    """
    entries = list_strategies()
    if not entries:
        return ""
    lines = [
        "## Available Strategy Memories",
        "Scan the strategies below. When generating a question, if a "
        "strategy matches the current dimension and job level, its full "
        "content will be provided in the STRATEGY_MEMORY block.\n",
    ]
    for e in entries:
        dims = ", ".join(e.dimensions) if e.dimensions else "all"
        levels = ", ".join(e.job_levels) if e.job_levels else "all"
        lines.append(f"- {e.name} [{dims} | {levels}]: {e.description}")
    return "\n".join(lines)


def format_strategies_for_prompt(
    entries: list[StrategyEntry],
    *,
    max_body_chars: int = 800,
) -> str:
    """Tier 2: full content for the most relevant strategies.

    Only strategies that survive the ``retrieve_strategies`` relevance
    filter reach this point.  Bodies are truncated to *max_body_chars*
    to keep the prompt budget bounded; the index (Tier 1) already told
    the LLM what else exists.
    """
    if not entries:
        return "(no relevant strategy memories)"
    blocks: list[str] = []
    for i, e in enumerate(entries, 1):
        body = e.body
        truncated = ""
        if len(body) > max_body_chars:
            body = body[:max_body_chars]
            truncated = " [truncated — see full file for details]"
        blocks.append(
            f"[Strategy {i}] {e.name}\n"
            f"  Applies to: dims={e.dimensions}, levels={e.job_levels}\n"
            f"  {body}{truncated}"
        )
    return "\n\n".join(blocks)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug[:60]


def save_strategy(
    *,
    name: str,
    description: str,
    dimensions: list[str],
    job_levels: list[str],
    body: str,
    memory_key: str | None = None,
) -> Path:
    """Persist a new or updated strategy topic file and refresh the index."""
    if _strategy_backend() == "db":
        return _save_db_strategy(
            name=name,
            description=description,
            dimensions=dimensions,
            job_levels=job_levels,
            body=body,
            memory_key=memory_key,
        )
    root = _strategy_dir()
    root.mkdir(parents=True, exist_ok=True)
    slug = _slugify(name)
    path = root / f"{slug}.md"

    dims_str = ", ".join(dimensions)
    levels_str = ", ".join(job_levels)
    memory_key_line = f"memory_key: {memory_key}\n" if memory_key else ""
    content = (
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"type: strategy\n"
        f"dimensions: [{dims_str}]\n"
        f"job_levels: [{levels_str}]\n"
        f"auto_generated: true\n"
        f"{memory_key_line}"
        f"created_at: {datetime.now(UTC).isoformat()}\n"
        f"---\n\n"
        f"{body}\n"
    )
    _atomic_write_text(path, content)
    log.info("saved strategy %r -> %s", name, path)
    clear_strategy_cache_for_tests()
    _rebuild_memory_index()
    return path


def _save_db_strategy(
    *,
    name: str,
    description: str,
    dimensions: list[str],
    job_levels: list[str],
    body: str,
    memory_key: str | None = None,
) -> Path:
    slug = _slugify(name)
    with get_session() as session:
        row = session.scalar(select(StrategyMemory).where(StrategyMemory.slug == slug))
        if row is None and memory_key:
            row = session.scalar(
                select(StrategyMemory).where(StrategyMemory.memory_key == memory_key)
            )
        if row is None:
            row = StrategyMemory(
                id=f"auto:{slug}",
                slug=slug,
                source="promoted_signal",
                status="active",
                promotion_stage="low_confidence",
            )
            session.add(row)
        row.name = name
        row.description = description
        row.memory_key = memory_key
        row.dimensions = list(dimensions)
        row.job_levels = list(job_levels)
        row.body_markdown = body
        row.version = int(row.version or 1) + 1
    clear_strategy_cache_for_tests()
    return Path(f"{slug}.md")


def delete_strategy(path: Path) -> bool:
    """Remove a single strategy file and refresh the index."""
    if not path.exists():
        return False
    path.unlink()
    log.info("deleted strategy %s", path)
    clear_strategy_cache_for_tests()
    _rebuild_memory_index()
    return True


def update_strategy_body(path: Path, new_body: str) -> bool:
    """Replace a strategy file's body while keeping its frontmatter."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    fm_match = _FM_PATTERN.match(text)
    if fm_match:
        header = text[: fm_match.end()]
    else:
        header = ""
    _atomic_write_text(path, f"{header}{new_body}\n")
    log.info("updated strategy body %s", path)
    clear_strategy_cache_for_tests()
    _rebuild_memory_index()
    return True


def backup_strategies() -> Path:
    """Copy all strategy files to a timestamped backup directory."""
    import shutil

    root = _strategy_dir()
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    backup_dir = root / ".dream_backup" / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    for p in root.glob("*.md"):
        shutil.copy2(p, backup_dir / p.name)
    log.info("backed up strategies to %s", backup_dir)
    return backup_dir


def restore_from_backup(backup_dir: Path) -> int:
    """Restore strategy files from a backup directory."""
    import shutil

    root = _strategy_dir()
    count = 0
    for p in backup_dir.glob("*.md"):
        shutil.copy2(p, root / p.name)
        count += 1
    if count:
        clear_strategy_cache_for_tests()
        _rebuild_memory_index()
    log.info("restored %d strategy files from %s", count, backup_dir)
    return count


def _rebuild_memory_index() -> None:
    """Regenerate ``MEMORY.md`` from the current set of topic files."""
    root = _strategy_dir()
    entries = list_strategies()
    lines = [
        "# Interview Strategy Memory\n",
        "Long-term strategy knowledge distilled from interview sessions.",
        "Each entry links to a topic file with full details.\n",
    ]
    for e in entries:
        fname = e.path.name
        lines.append(f"- [{e.name}]({fname}) — {e.description}")
    _atomic_write_text(root / "MEMORY.md", "\n".join(lines) + "\n")
