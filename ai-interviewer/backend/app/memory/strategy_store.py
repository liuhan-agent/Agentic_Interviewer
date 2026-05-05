"""File-backed strategy memory store.

Borrows the Claude Code pattern: a human-readable ``MEMORY.md`` index
plus individual topic files, all living under ``knowledge/strategy/``.
The store supports reading, writing, and retrieving strategy files so
the interview workflow can both *consume* past experience and *produce*
new experience after each session.

Retrieval is keyword-based (dimension + job_level match against YAML
frontmatter).  The vector store handles deeper semantic similarity;
this module provides the structured, file-native layer on top.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings

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


@dataclass
class StrategyEntry:
    path: Path
    name: str = ""
    description: str = ""
    entry_type: str = "strategy"
    dimensions: list[str] = field(default_factory=list)
    job_levels: list[str] = field(default_factory=list)
    body: str = ""


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
            name=fm.get("name", p.stem),
            description=fm.get("description", ""),
            entry_type=fm.get("type", "strategy"),
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
        if entry.dimensions and dimension in entry.dimensions:
            score += 2
        if entry.job_levels and job_level in entry.job_levels:
            score += 1
        if not entry.dimensions:
            score += 1
        scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    keyword_hits = [e for _, e in scored[:limit] if _ > 0]

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
