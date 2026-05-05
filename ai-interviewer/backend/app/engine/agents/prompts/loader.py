"""Prompt file loader with frontmatter + variable validation.

Keeps prompts as ``.md`` files under this directory so they can be
reviewed, diffed, and A/B tested without touching Python. Every prompt
file has a tiny YAML-ish frontmatter declaring its variables; the
loader validates that callers supply every declared variable before
rendering, so a missing key no longer silently produces a malformed
prompt.

File format
-----------
::

    ---
    name: generator_task
    version: v1
    description: Generator agent's main question-authoring task.
    variables:
      - dimension
      - action
      - refine_mode
    ---

    You are the question author. The dimension is {dimension}. ...

The frontmatter is parsed with a narrow subset of YAML (scalar values
and bullet-list arrays) to avoid pulling in a PyYAML dependency; the
same approach already lives in ``app.memory.strategy_store``.

API
---
- :func:`load_prompt` — backwards-compatible ``raw file body`` reader
  (strips frontmatter when present).
- :func:`render_prompt` — frontmatter-aware renderer, performs
  ``.format(**vars)`` after validating the variable set.
- :func:`get_prompt_meta` — frontmatter-only accessor for tests and
  introspection.

``render_prompt`` raises :class:`PromptVariableMissing` if any declared
variable is absent from the call's kwargs. Extra kwargs are tolerated
and ignored so evolving a prompt to drop a variable does not break
callers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent
_FM_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class PromptError(RuntimeError):
    """Base class for loader errors."""


# ``noqa: N818`` — the exceptions below carry a descriptive verb/noun
# phrase rather than the generic ``Error`` suffix because callers write
# ``except PromptNotFound`` / ``except PromptVariableMissing`` which
# reads as a sentence. Keeping them as-is avoids breaking every site
# that catches them.
class PromptNotFound(PromptError):  # noqa: N818
    """Raised when the prompt file does not exist."""


class PromptVariableMissing(PromptError):  # noqa: N818
    """Raised when ``render_prompt`` is called without a declared var.

    Carries the list of missing variable names so callers can surface
    a useful error instead of guessing from a ``KeyError``.
    """

    def __init__(self, prompt_name: str, missing: list[str]) -> None:
        self.prompt_name = prompt_name
        self.missing = missing
        super().__init__(
            f"prompt {prompt_name!r} is missing variables: {sorted(missing)}"
        )


@dataclass
class PromptMeta:
    name: str = ""
    version: str = ""
    description: str = ""
    variables: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> tuple[PromptMeta, str]:
    """Split ``text`` into ``(meta, body)``.

    The frontmatter grammar is intentionally tiny:

    - ``key: value`` for scalar strings (value may be empty)
    - ``key:`` on its own line followed by indented ``- item`` lines
      for list values

    Anything else is tolerated silently so humans editing the files
    do not get surprised by a YAML parser. Unknown keys are dropped.
    """
    m = _FM_PATTERN.match(text)
    if not m:
        return PromptMeta(), text

    block = m.group(1)
    body = text[m.end():]

    meta = PromptMeta()
    current_list_key: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            current_list_key = None
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # List item continuation (``  - value``)
        if indent > 0 and stripped.startswith("-"):
            if current_list_key == "variables":
                item = stripped[1:].strip()
                if item:
                    meta.variables.append(item)
            continue

        # ``key: value`` or ``key:``
        if ":" not in stripped:
            current_list_key = None
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()

        if not val:
            current_list_key = key
            continue

        current_list_key = None
        if key == "name":
            meta.name = val
        elif key == "version":
            meta.version = val
        elif key == "description":
            meta.description = val
        elif key == "variables":
            # Inline ``variables: [a, b]`` style — optional nicety.
            inline = val.strip()
            if inline.startswith("[") and inline.endswith("]"):
                items = [i.strip().strip("'\"") for i in inline[1:-1].split(",")]
                meta.variables = [i for i in items if i]

    return meta, body


@lru_cache(maxsize=64)
def _read_prompt_file(name: str) -> tuple[PromptMeta, str]:
    """Return ``(meta, body)`` for a named prompt file.

    The result is cached at the module level; call ``_read_prompt_file.cache_clear()``
    if you need to pick up on-disk changes during a test run.
    """
    path = _PROMPT_DIR / name
    if not path.exists():
        raise PromptNotFound(f"prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    return _parse_frontmatter(text)


def get_prompt_meta(name: str) -> PromptMeta:
    """Frontmatter accessor; does not render."""
    meta, _ = _read_prompt_file(name)
    return meta


def load_prompt(name: str) -> str:
    """Return the prompt body stripped of frontmatter.

    Preserved for backwards compatibility. Existing callers that do
    their own ``.format(**vars)`` (the ``system_skeleton.md`` path,
    for example) get the same substring they had before.
    """
    _, body = _read_prompt_file(name)
    return body


def render_prompt(name: str, /, **vars: object) -> str:
    """Render a prompt file with the given variables.

    - Reads the frontmatter-declared variable set.
    - Raises :class:`PromptVariableMissing` if any declared variable is
      absent from ``vars`` (empty strings count as present).
    - Extra kwargs are ignored so prompts can drop variables without
      breaking callers in lockstep.
    - Calls ``body.format(**vars)`` for substitution so existing
      ``{name}`` placeholders keep working. Literal braces inside the
      prompt must be escaped as ``{{`` / ``}}`` just like before.
    """
    meta, body = _read_prompt_file(name)

    if meta.variables:
        missing = [v for v in meta.variables if v not in vars]
        if missing:
            raise PromptVariableMissing(name, missing)

    if not vars:
        return body

    try:
        return body.format(**vars)
    except KeyError as e:
        raise PromptVariableMissing(name, [str(e).strip("'\"")]) from e


def clear_cache() -> None:
    """Test helper: drop the on-disk cache so edited files are re-read."""
    _read_prompt_file.cache_clear()
