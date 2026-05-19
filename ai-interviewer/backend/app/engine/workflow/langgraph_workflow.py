"""Full interview workflow graph.

Topology::

    START
      -> resume_parse
      -> self_intro_question
      -> wait_answer
      -> self_intro_parse
      -> director_sample
      -> ask_question
      -> wait_answer
      -> route_after_wait
           -> "self_intro_parse" -> self_intro_parse
           -> "skip_question"    -> skip_question
           -> "evaluator"        -> evaluator
           -> "end"              -> final_report
      -> skip_question
      -> route_after_skip
           -> "next_question" -> director_sample
           -> "end"           -> final_report
      -> evaluator
      -> verification
      -> reward_update
      -> compress_context
      -> route_after_eval
           -> "refine"        -> refine_followup -> director_sample
           -> "next_question" -> director_sample
           -> "end"           -> final_report
      -> final_report
      -> training_plan
      -> experience_extractor
      -> END

This is a human-readable summary only. The exact node / edge /
conditional-branch snapshot is exposed by ``workflow_topology_snapshot``
and guarded by ``tests/unit/test_langgraph_workflow_topology.py``.

This mirrors the ACO business-loop pattern with the names mapped to
the interview domain. Every cycle goes back through ``director_sample``
so Thompson Sampling gets a fresh draw per turn.

``compress_context`` runs after ``evaluator`` on every cycle and
compacts old QA turns into a structured per-dimension summary.  The
generator reads the summary instead of the full history, keeping
prompts lean for long interviews. Inspired by Claude Code's
session-memory compaction but using deterministic aggregation rather
than an LLM summariser.
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.engine.workflow.checkpoint_metrics import wrap_saver_with_metrics

from .nodes import (
    ask_question_node,
    compress_context_node,
    director_sample_node,
    evaluator_node,
    final_report_node,
    refine_followup_node,
    resume_parse_node,
    reward_update_node,
    self_intro_parse_node,
    self_intro_question_node,
    skip_question_node,
    training_plan_node,
    verification_node,
    wait_answer_node,
)
from .nodes.experience_extractor import experience_extractor_node
from .routers import route_after_eval, route_after_skip, route_after_wait
from .state import InterviewState

log = get_logger(__name__)


def _register_nodes(graph: Any) -> None:
    graph.add_node("resume_parse", resume_parse_node)
    graph.add_node("self_intro_question", self_intro_question_node)
    graph.add_node("self_intro_parse", self_intro_parse_node)
    graph.add_node("director_sample", director_sample_node)
    graph.add_node("ask_question", ask_question_node)
    graph.add_node("wait_answer", wait_answer_node)
    graph.add_node("skip_question", skip_question_node)
    graph.add_node("evaluator", evaluator_node)
    # verification runs between evaluator and compress_context so the
    # compressed transcript reflects the post-verification evaluation.
    graph.add_node("verification", verification_node)
    graph.add_node("reward_update", reward_update_node)
    graph.add_node("compress_context", compress_context_node)
    graph.add_node("refine_followup", refine_followup_node)
    graph.add_node("final_report", final_report_node)
    # Coach turns the final report into an actionable training_plan;
    # runs after final_report so it can read scores / verdict / QA.
    graph.add_node("training_plan", training_plan_node)
    graph.add_node("experience_extractor", experience_extractor_node)


def _register_edges(graph: Any) -> None:
    graph.add_edge(START, "resume_parse")
    graph.add_edge("resume_parse", "self_intro_question")
    graph.add_edge("self_intro_question", "wait_answer")
    graph.add_edge("self_intro_parse", "director_sample")
    graph.add_edge("director_sample", "ask_question")
    graph.add_edge("ask_question", "wait_answer")
    # Cancel-aware edge: a cancelled wait must bypass the evaluator so
    # we do not score a placeholder answer and so the bandit never
    # sees a tainted reward signal. See ``route_after_wait``.
    graph.add_conditional_edges(
        "wait_answer",
        route_after_wait,
        {
            "self_intro_parse": "self_intro_parse",
            "skip_question": "skip_question",
            "evaluator": "evaluator",
            "end": "final_report",
        },
    )
    graph.add_conditional_edges(
        "skip_question",
        route_after_skip,
        {
            "next_question": "director_sample",
            "end": "final_report",
        },
    )

    graph.add_edge("evaluator", "verification")
    graph.add_edge("verification", "reward_update")
    graph.add_edge("reward_update", "compress_context")
    graph.add_conditional_edges(
        "compress_context",
        route_after_eval,
        {
            "refine": "refine_followup",
            "next_question": "director_sample",
            "end": "final_report",
        },
    )
    graph.add_edge("refine_followup", "director_sample")
    graph.add_edge("final_report", "training_plan")
    graph.add_edge("training_plan", "experience_extractor")
    graph.add_edge("experience_extractor", END)


class _TopologyRecorder:
    """Small graph-like recorder used for topology snapshot tests."""

    def __init__(self) -> None:
        self.nodes: list[str] = []
        self.edges: list[dict[str, str]] = []
        self.conditional_edges: list[dict[str, Any]] = []

    def add_node(self, name: str, _node: Any) -> None:
        self.nodes.append(name)

    def add_edge(self, source: Any, target: Any) -> None:
        self.edges.append(
            {
                "source": _topology_endpoint(source),
                "target": _topology_endpoint(target),
            }
        )

    def add_conditional_edges(
        self,
        source: str,
        router: Any,
        branches: dict[str, Any],
    ) -> None:
        self.conditional_edges.append(
            {
                "source": source,
                "router": getattr(router, "__name__", str(router)),
                "branches": {
                    label: _topology_endpoint(target)
                    for label, target in branches.items()
                },
            }
        )


def _topology_endpoint(value: Any) -> str:
    if value == START:
        return "START"
    if value == END:
        return "END"
    return str(value)


def workflow_topology_snapshot() -> dict[str, Any]:
    """Return the registered topology without compiling the graph."""
    recorder = _TopologyRecorder()
    _register_nodes(recorder)
    _register_edges(recorder)
    return {
        "nodes": recorder.nodes,
        "edges": recorder.edges,
        "conditional_edges": recorder.conditional_edges,
    }


def _psycopg_dsn(database_url: str) -> str:
    """Strip the SQLAlchemy dialect prefix for psycopg's libpq-style DSN.

    The Postgres saver (and psycopg itself) expect a raw
    ``postgresql://`` URL. Our settings default uses the SQLAlchemy
    form ``postgresql+psycopg2://...`` for ORM compatibility - this
    shim keeps a single env var for both worlds.
    """
    if database_url.startswith("postgresql+"):
        _, _, rest = database_url.partition("+")
        _, _, tail = rest.partition("://")
        return f"postgresql://{tail}"
    return database_url


_POSTGRES_SAVER: Any | None = None


def reset_default_checkpointer() -> None:
    """Clear the cached Postgres saver for tests that patch settings."""
    global _POSTGRES_SAVER
    _POSTGRES_SAVER = None


def _postgres_saver() -> Any:
    """Build a process-wide ``PostgresSaver`` backed by a persistent pool.

    ``PostgresSaver.from_conn_string`` is an ``@contextmanager``: exiting
    the ``with`` block closes the connection, which would be disastrous
    for a long-running FastAPI process. The supported production
    pattern (per the LangGraph docs) is to drive it with a
    ``psycopg_pool.ConnectionPool`` that stays alive for the lifetime
    of the app and hand the pool to ``PostgresSaver(pool)``.

    We cache the saver in a module-level variable so every call to
    ``build_workflow()`` (tests, session manager, demos) reuses the
    same pool instead of exhausting postgres with fresh connections.
    """
    global _POSTGRES_SAVER
    if _POSTGRES_SAVER is not None:
        return _POSTGRES_SAVER

    settings = get_settings()
    dsn = _psycopg_dsn(settings.database_url)

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool
    except ImportError as e:  # pragma: no cover
        if settings.app_env == "prod":
            raise RuntimeError(
                "postgres checkpoint requested but dependencies are missing"
            ) from e
        log.warning(
            "postgres checkpoint requested but dependencies are missing (%s); "
            "falling back to MemorySaver",
            e,
        )
        # The outer ``_default_checkpointer`` wraps with ``backend="postgres"``
        # because that was the configured intent. We re-wrap here with the
        # actual backend so dashboards report the truth (``memory``); the
        # idempotent marker on the saver instance keeps the second call to
        # ``wrap_saver_with_metrics`` a no-op.
        return wrap_saver_with_metrics(MemorySaver(), backend="memory")

    try:
        pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        pool.open()
        saver = PostgresSaver(pool)
        saver.setup()
    except Exception as e:
        if settings.app_env == "prod":
            raise RuntimeError("PostgresSaver init failed in production") from e
        log.warning(
            "PostgresSaver init failed (%s); falling back to MemorySaver",
            e,
            exc_info=True,
        )
        return wrap_saver_with_metrics(MemorySaver(), backend="memory")

    log.info("using PostgresSaver checkpointer (pool min=1 max=10)")
    _POSTGRES_SAVER = saver
    return saver


def _default_checkpointer() -> Any:
    """Pick a checkpointer based on ``Settings.checkpoint_backend``.

    - ``memory`` (default) -> in-process ``MemorySaver`` - zero setup.
    - ``postgres``         -> ``PostgresSaver`` backed by a pooled
      connection, which unlocks durable HITL (``interrupt()/resume()``
      across process restarts) and cross-session trace joins.

    Resolution is lazy: importing this module does not touch postgres.
    """
    backend = get_settings().checkpoint_backend
    if backend == "memory":
        return wrap_saver_with_metrics(MemorySaver(), backend="memory")
    if backend == "postgres":
        return wrap_saver_with_metrics(_postgres_saver(), backend="postgres")
    if get_settings().app_env == "prod":
        raise RuntimeError(f"unknown checkpoint_backend={backend!r} in production")
    log.warning("unknown checkpoint_backend=%r; using MemorySaver", backend)
    return wrap_saver_with_metrics(MemorySaver(), backend="memory")


def build_workflow(checkpointer: Any | None = None):
    """Compile the interview graph.

    Args:
        checkpointer: If explicitly provided, used as-is. Otherwise the
            backend is chosen by ``Settings.checkpoint_backend``
            (``memory`` or ``postgres``).
    """
    graph = StateGraph(InterviewState)
    _register_nodes(graph)
    _register_edges(graph)
    return graph.compile(checkpointer=checkpointer or _default_checkpointer())
