"""Strategy consolidation via forked agent ("autoDream").

Implements a genuine multi-turn agent loop — the dream agent can
read strategy files, inspect Bandit posteriors, decide what to
change, execute writes, and verify results across multiple iterations.

Architecture mirrors Claude Code's ``runForkedAgent``:
  - A sandboxed tool set (read / write / delete / list — scoped to
    ``knowledge/strategy/`` only).
  - A consolidation system prompt that steers the agent through the
    4-phase review process.
  - A ``max_iterations`` cap that prevents runaway loops.
  - Backup before execution, rollback on failure.

The forked agent does NOT inherit a parent agent's prompt-cache state
(same as Hermes' review agent), because it runs in its own context
with a specialised system prompt.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.engine.agents.llm_client import ChatMessage, call_chat
from app.memory.strategy_store import (
    _rebuild_memory_index,  # noqa: PLC2701
    _strategy_dir,  # noqa: PLC2701
    backup_strategies,
    delete_strategy,
    list_strategies,
    restore_from_backup,
    save_strategy,
    update_strategy_body,
)
from app.ml.rl.thompson import get_bandit

log = get_logger(__name__)

MAX_ITERATIONS = 8

# ---------------------------------------------------------------------------
# Sandboxed tool definitions (only strategy-directory operations)
# ---------------------------------------------------------------------------

_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "list_strategies",
            "description": (
                "List all strategy files with metadata "
                "(name, description, dimensions, job_levels, file path, modification date)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_strategy",
            "description": "Read the full content of a strategy file by filename.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The .md filename within knowledge/strategy/",
                    }
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_strategy",
            "description": (
                "Replace the body of an existing strategy file. "
                "Keeps the frontmatter intact."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "new_body": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["filename", "new_body", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_strategy_file",
            "description": "Delete a strategy file that is obsolete or redundant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["filename", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_merged_strategy",
            "description": (
                "Create a new strategy file that merges content "
                "from multiple existing files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "dimensions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "job_levels": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "body": {"type": "string"},
                    "source_files_to_delete": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filenames of the source files to remove after merge.",
                    },
                },
                "required": ["name", "description", "dimensions", "job_levels", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bandit_posteriors",
            "description": (
                "Retrieve current Thompson Sampling posteriors for all arms. "
                "Returns (context_key, action_id) -> (alpha, beta, mean)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_dream",
            "description": "Signal that the consolidation is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One sentence summary of what this dream cycle did.",
                    }
                },
                "required": ["summary"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution (sandboxed to strategy directory)
# ---------------------------------------------------------------------------

def _safe_path_within_root(fname: str, root: Path) -> Path | None:
    """Resolve ``fname`` relative to ``root`` and refuse path traversal.

    The dream agent is an LLM, so we cannot trust that ``filename``
    arguments stay within ``knowledge/strategy/``. A hallucinated
    ``"../../etc/passwd"`` would otherwise let the agent read or
    delete arbitrary files.

    Returns the resolved path only if it lives under ``root`` and is
    not a bare directory reference (empty / ``.`` / ``..``). Returns
    ``None`` when the input is rejected.
    """
    if not fname or fname in {".", ".."}:
        return None
    # Absolute paths and parent-escape sequences are rejected outright.
    if fname.startswith(("/", "\\")) or ":" in fname:
        return None
    candidate = (root / fname).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _sandbox_error(reason: str) -> str:
    return json.dumps({"error": reason, "sandbox_violation": True})


def _exec_tool(name: str, args: dict[str, Any]) -> str:
    root = _strategy_dir()

    if name == "list_strategies":
        entries = list_strategies()
        items = []
        for e in entries:
            mtime = "unknown"
            try:
                mtime = datetime.fromtimestamp(
                    e.path.stat().st_mtime, tz=UTC
                ).strftime("%Y-%m-%d")
            except OSError:
                pass
            items.append({
                "filename": e.path.name,
                "name": e.name,
                "description": e.description[:150],
                "dimensions": e.dimensions,
                "job_levels": e.job_levels,
                "last_modified": mtime,
            })
        return json.dumps(items, ensure_ascii=False)

    if name == "read_strategy":
        fname = args.get("filename", "")
        path = _safe_path_within_root(fname, root)
        if path is None:
            return _sandbox_error(
                f"filename {fname!r} rejected: must be a simple name "
                f"under knowledge/strategy/"
            )
        if not path.exists() or not path.is_file():
            return json.dumps({"error": f"File not found: {fname}"})
        return path.read_text(encoding="utf-8")

    if name == "update_strategy":
        fname = args.get("filename", "")
        path = _safe_path_within_root(fname, root)
        if path is None:
            return _sandbox_error(
                f"filename {fname!r} rejected: must be a simple name "
                f"under knowledge/strategy/"
            )
        if not path.exists():
            return json.dumps({"error": f"File not found: {fname}"})
        update_strategy_body(path, args.get("new_body", ""))
        return json.dumps({"ok": True, "updated": fname, "reason": args.get("reason", "")})

    if name == "delete_strategy_file":
        fname = args.get("filename", "")
        path = _safe_path_within_root(fname, root)
        if path is None:
            return _sandbox_error(
                f"filename {fname!r} rejected: must be a simple name "
                f"under knowledge/strategy/"
            )
        if not path.exists():
            return json.dumps({"error": f"File not found: {fname}"})
        delete_strategy(path)
        return json.dumps({"ok": True, "deleted": fname, "reason": args.get("reason", "")})

    if name == "create_merged_strategy":
        new_path = save_strategy(
            name=args.get("name", "Merged Strategy"),
            description=args.get("description", ""),
            dimensions=args.get("dimensions", []),
            job_levels=args.get("job_levels", []),
            body=args.get("body", ""),
        )
        deleted: list[str] = []
        rejected: list[str] = []
        for src in args.get("source_files_to_delete", []):
            safe = _safe_path_within_root(src, root)
            if safe is None:
                rejected.append(src)
                continue
            if safe.exists():
                safe.unlink()
                deleted.append(src)
        if deleted:
            _rebuild_memory_index()
        payload: dict[str, Any] = {
            "ok": True,
            "created": new_path.name,
            "deleted_sources": deleted,
        }
        if rejected:
            payload["rejected_sources"] = rejected
            payload["sandbox_violation"] = True
        return json.dumps(payload)

    if name == "get_bandit_posteriors":
        bandit = get_bandit()
        snapshot = bandit.snapshot()
        result = {}
        for key, params in snapshot.items():
            alpha = params.get("alpha", 1.0)
            beta = params.get("beta", 1.0)
            result[key] = {
                "alpha": round(alpha, 2),
                "beta": round(beta, 2),
                "mean": round(alpha / (alpha + beta), 3) if (alpha + beta) > 0 else 0.5,
                "observations": round(alpha + beta - 2.0, 0),
            }
        return json.dumps(result, ensure_ascii=False)

    if name == "finish_dream":
        return json.dumps({"done": True, "summary": args.get("summary", "")})

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the **strategy consolidation agent** for an AI interview system.
You have been forked from the main runtime to perform a periodic review
of the strategy memory layer.

## Your mission
Review all strategy files, compare them against current Bandit posteriors,
and tidy the strategy directory:
- Merge duplicate strategies that cover the same dimension+level+action.
- Update strategies whose recommendations contradict fresh Bandit evidence.
- Delete auto-generated strategies that are stale (>30 days old with
  no supporting Bandit observations).
- Leave hand-written strategies intact unless clearly obsolete.

## Efficiency strategy (IMPORTANT)
You have at most {max_iterations} tool-call rounds. Be efficient:
- **Round 1**: Call `list_strategies` AND `get_bandit_posteriors` together.
- **Round 2**: Read any files that look problematic (batch reads).
- **Round 3+**: Execute all necessary writes (batch writes).
- **Final round**: Call `finish_dream`.

Do NOT read a file, then write it, then read another file, then write it.
Batch your reads first, then batch your writes.

## Constraints
- NEVER invent new strategies from scratch. Only merge/update/prune.
- Prefer keeping manual (non-auto-generated) strategies.
- When merging, keep the richer/more detailed content.
- If a strategy recommends action X but Bandit shows X has mean reward
  < 0.35 with ≥ 5 observations, update the strategy to match the data.
- Maximum 5 write operations per dream cycle.
- If nothing needs changing, just call `finish_dream` immediately.

## Information boundary
Only use information from the strategy files and Bandit posteriors.
Do NOT attempt to read code, run commands, or access any resources
outside the strategy directory.
"""

# ---------------------------------------------------------------------------
# Forked agent loop
# ---------------------------------------------------------------------------


def _run_openai_turn(
    messages: list[ChatMessage],
    settings: Any,
    actions_executed: int,
    backup_dir: Path,
    iteration: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Execute one turn of the OpenAI tool-calling loop.

    Returns ``(state_update, finish_result)``.  When ``finish_result``
    is not ``None`` the caller should return it immediately (the agent
    called ``finish_dream``).
    """
    from app.engine.agents.llm_client import _get_openai_client

    client = _get_openai_client(
        api_key=settings.openai_api_key,
        base_url=None,
        timeout=float(settings.llm_request_timeout_seconds),
        max_retries=0,
    )

    api_msgs: list[dict[str, Any]] = [m.to_dict() for m in messages]
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=api_msgs,
        tools=_TOOL_DEFS,
        temperature=0.3,
        max_tokens=2048,
    )

    choice = resp.choices[0]
    assistant_msg = choice.message

    if not assistant_msg.tool_calls:
        messages.append(ChatMessage("assistant", assistant_msg.content or ""))
        log.info("dream agent stopped (no tool calls) at iteration %d", iteration + 1)
        return {"_break": True, "_summary": assistant_msg.content or "Dream completed."}, None

    # Append the raw assistant message (with tool_calls) to context.
    # OpenAI expects the assistant message to appear in the history
    # with its tool_calls intact before the corresponding tool results.
    raw_asst: dict[str, Any] = {
        "role": "assistant",
        "content": assistant_msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in assistant_msg.tool_calls
        ],
    }
    messages.append(ChatMessage("assistant", assistant_msg.content or ""))
    # We also keep the raw dict for the next API call via a side-channel:
    # replace the last ChatMessage's to_dict output with the full version.
    messages[-1]._raw_dict = raw_asst  # type: ignore[attr-defined]

    for tc in assistant_msg.tool_calls:
        fn_name = tc.function.name
        fn_args = json.loads(tc.function.arguments or "{}")
        log.info("dream agent tool: %s(%s)", fn_name, list(fn_args.keys()))

        if fn_name == "finish_dream":
            summary = fn_args.get("summary", "Dream completed.")
            _rebuild_memory_index()
            return {}, {
                "actions_executed": actions_executed,
                "summary": summary,
                "backup_dir": str(backup_dir),
                "iterations": iteration + 1,
            }

        result = _exec_tool(fn_name, fn_args)

        if fn_name in ("update_strategy", "delete_strategy_file", "create_merged_strategy"):
            actions_executed += 1

        messages.append(ChatMessage(
            "tool", result, tool_call_id=tc.id, name=fn_name
        ))

    return {"_actions_executed": actions_executed}, None


def run_dream() -> dict[str, Any]:
    """Execute one full dream cycle using a multi-turn forked agent."""
    entries = list_strategies()
    if not entries:
        log.info("dream: no strategies to consolidate")
        return {"actions_executed": 0, "summary": "No strategies to review."}

    backup_dir = backup_strategies()

    system = _SYSTEM_PROMPT.format(max_iterations=MAX_ITERATIONS)
    messages: list[ChatMessage] = [ChatMessage("system", system)]

    initial_user = (
        "You have been woken up for a dream consolidation cycle. "
        "Start by listing strategies and checking Bandit posteriors."
    )
    messages.append(ChatMessage("user", initial_user))

    actions_executed = 0
    summary = ""

    from app.core.settings import get_settings
    settings = get_settings()

    # Stub mode never runs real consolidation: skip entirely and signal
    # the caller so gates (e.g. ``sessions_since_dream``) are NOT reset.
    # Otherwise every CI / dev run silently eats a scheduled dream cycle
    # even though nothing was reviewed.
    if settings.use_stub_llm:
        log.info("dream: stub LLM detected, skipping consolidation")
        return {
            "actions_executed": 0,
            "summary": "Dream skipped: stub LLM provider is active.",
            "skipped": True,
        }

    for iteration in range(MAX_ITERATIONS):
        log.debug("dream agent iteration %d/%d", iteration + 1, MAX_ITERATIONS)

        try:

            if settings.llm_provider == "openai":
                api_messages, finish_result = _run_openai_turn(
                    messages, settings, actions_executed, backup_dir, iteration
                )
                if finish_result is not None:
                    return finish_result
                actions_executed = api_messages.pop("_actions_executed", actions_executed)
                if api_messages.get("_break"):
                    summary = api_messages.get("_summary", "Dream completed.")
                    break
            else:
                raw = call_chat(
                    messages,
                    json_mode=False,
                    temperature=0.3,
                    agent_role="strategy_dream",
                )
                summary = raw or "Dream completed."
                break

        except Exception as e:
            log.error("dream agent iteration %d failed: %s", iteration + 1, e)
            log.info("rolling back from backup %s", backup_dir)
            restore_from_backup(backup_dir)
            return {
                "actions_executed": 0,
                "summary": f"Dream failed at iteration {iteration + 1}: {e}",
                "rolled_back": True,
            }

    _rebuild_memory_index()

    if not summary:
        summary = f"Dream completed after {MAX_ITERATIONS} iterations."

    log.info("dream completed: %d actions, summary=%s", actions_executed, summary)
    return {
        "actions_executed": actions_executed,
        "summary": summary,
        "backup_dir": str(backup_dir),
        "iterations": MAX_ITERATIONS,
    }
