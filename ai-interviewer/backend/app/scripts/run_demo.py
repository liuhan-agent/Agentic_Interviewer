"""End-to-end text-mode interview demo.

Runs the full LangGraph 7-node workflow with a scripted answer
provider. Works with *no* API keys by relying on the LLM stub + the
in-memory vector store. With an OPENAI_API_KEY it seamlessly uses the
real model.

Usage::

    python -m app.scripts.run_demo
    python -m app.scripts.run_demo --turns 4 --threshold 8.0
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from app.core.langsmith_utils import build_langsmith_config
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.engine.rag.ingestion import ingest_folder
from app.engine.rag.vectorstore import get_vectorstore
from app.engine.workflow.langgraph_workflow import build_workflow
from app.engine.workflow.nodes.answer_provider import (
    StaticAnswerProvider,
    register_provider,
    unregister_provider,
)
from app.engine.workflow.state import build_initial_state

log = get_logger(__name__)


CANNED_ANSWERS = [
    (
        "Sure. At ShieldPay I built an idempotency layer using a Redis-backed "
        "deduplication table keyed on (tenant, request_id). Writes go through a "
        "Lua script that atomically claims the key, persists the payload, and "
        "returns the prior response if present. We handled retries across "
        "network partitions by making the client-generated key the source of "
        "truth and rejecting conflicting payloads with a 409."
    ),
    (
        "We had a tail-latency problem I chased for about a week. Turned out "
        "to be a 30s GC pause in a sidecar that every pod talked to. I used "
        "eBPF traces to correlate latency spikes with the sidecar's heap "
        "usage, and the fix was switching its allocator plus adding backpressure "
        "so the spikes did not propagate. p99 dropped from 800ms to 180ms."
    ),
    (
        "I would frame it as a CRDT problem. For the text body I would use a "
        "sequence CRDT like RGA or Yjs so concurrent edits merge without a "
        "central arbiter. Presence is a separate channel on WebSocket, "
        "throttled to ~15 Hz per client. Persistence happens on a "
        "periodic snapshot plus the log of CRDT ops so we can rebuild any "
        "historical state."
    ),
    (
        "One strong example: a senior engineer and I disagreed on whether to "
        "build our own schema registry or adopt Confluent's. I wrote a 2-page "
        "comparison doc including long-term maintenance cost and migration "
        "risk, got a few other staff engineers to weigh in, and we ended up "
        "doing a narrower in-house build tailored to our Avro-heavy stack. "
        "Key for me was staying concrete and letting the data do the arguing."
    ),
    (
        "The hardest mentorship moment was an engineer who was technically "
        "strong but burning out the rest of the team. I had three 1:1s over "
        "a month focused not on the work but on how their comments in code "
        "reviews were landing. We agreed on a style contract. Six months "
        "later they were one of our best reviewers, and I had learned that "
        "feedback needs a format as much as a message."
    ),
    (
        "I would first validate the feature drift claim by replaying a "
        "golden test set through the last four model versions. Then I would "
        "compare live feature distributions against the training slice from "
        "the same window. Typically the root cause is either a silent "
        "upstream schema change or a time-zone bug in a windowed feature. "
        "After fixing, I would add a canary evaluator that flags KS-test "
        "drift on the top 20 features."
    ),
    (
        "Honestly, yes - I had a migration that missed its goal. We rushed "
        "a column rename without the full shadow-read period and a "
        "downstream job kept reading the old column for two weeks. No data "
        "loss, but the dashboards were stale. I owned the fix and the "
        "retrospective action items - mainly that schema moves now require a "
        "tracked deprecation window and an automated check."
    ),
    (
        "For a one-line \"make search better\" spec I would spend the first "
        "week understanding what \"better\" means to the business - "
        "instrumentation, user sessions, complaints. Week two I would ship "
        "a measurable baseline improvement (usually latency or a small "
        "ranking tweak) so I can prove we can move numbers. Then I would "
        "propose a two-quarter roadmap with explicit metrics."
    ),
]


def _fixture_candidate() -> dict[str, Any]:
    return {
        "name": "Alex Chen",
        "email_hash": "sha256:demo",
        "resume_parsed": {
            "summary": "5y senior backend engineer; payments, messaging, schema registry.",
            "skills": ["python", "go", "postgres", "kafka", "kubernetes", "redis"],
            "highlights": [
                "Led migration of monolithic payments to event-driven microservices.",
                "Authored company-wide schema registry adopted by 12 teams.",
                "Mentored two engineers through senior promotion.",
            ],
        },
    }


def _fixture_job_spec() -> dict[str, Any]:
    return {
        "title": "Senior Backend Engineer",
        "level": "senior",
        "required_skills": ["python", "system_design", "databases", "observability"],
        "rubric_dimensions": ["technical_depth", "system_design", "leadership"],
        "rubric": {
            "technical_depth": (
                "Goes beyond surface APIs - can discuss concrete failure modes, "
                "trade-offs, and production experience."
            ),
            "system_design": (
                "Scopes cleanly, decomposes, justifies architecture, understands "
                "capacity and failure modes."
            ),
            "leadership": (
                "Owns outcomes end-to-end, drives alignment, surfaces and resolves "
                "conflict constructively, grows teammates."
            ),
        },
    }


def _ensure_kb_seeded() -> None:
    store = get_vectorstore()
    if store.count() > 0:
        return
    root = Path(get_settings().knowledge_dir)
    if not root.exists():
        log.warning("No knowledge dir at %s - running without retrieval", root)
        return
    ingest_folder(root)


def _pretty_print_turn(turn: dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print(f"Turn {turn.get('turn_idx')}  [{turn.get('dimension')}]")
    print(f"  Strategy: {turn.get('selected_action')}")
    print(f"  Q: {turn.get('question')}")
    print(f"  A: {turn.get('answer')[:240]}{'...' if len(turn.get('answer', '')) > 240 else ''}")
    evaluation = turn.get("evaluation") or {}
    print(f"  Score: {evaluation.get('score')}  passed={evaluation.get('passed')}")
    if evaluation.get("strengths"):
        print(f"    + Strengths:  {', '.join(evaluation['strengths'][:3])}")
    if evaluation.get("weaknesses"):
        print(f"    - Weaknesses: {', '.join(evaluation['weaknesses'][:3])}")


def _build_demo_summary(final_state: dict[str, Any]) -> dict[str, Any]:
    """Compact showcase payload for screenshots / README snippets."""
    report = final_state.get("final_report") or {}
    artifacts = report.get("workflow_artifacts") or {}
    contract_summary = report.get("contract_summary") or {}
    latest_plan = artifacts.get("latest_ask_plan") or {}
    latest_contract = artifacts.get("latest_contract") or {}
    latest_verification = artifacts.get("latest_verification") or {}
    training_plan = report.get("training_plan") or {}

    return {
        "session_id": final_state.get("session_id"),
        "turns": len(final_state.get("qa_history") or []),
        "overall_score": report.get("overall_score"),
        "verdict": report.get("verdict"),
        "closed_loop_ready": bool(report.get("closed_loop_ready")),
        "plan_template": latest_plan.get("template"),
        "contract_signed_by": latest_contract.get("signed_by"),
        "verification_verdict": latest_verification.get("verdict"),
        "training_plan_source": training_plan.get("source"),
        "contract_checks": {
            "yes": contract_summary.get("checks_yes", 0),
            "partial": contract_summary.get("checks_partial", 0),
            "no": contract_summary.get("checks_no", 0),
            "total": contract_summary.get("total_checks", 0),
        },
    }


def run(
    *,
    max_turns: int = 8,
    quality_threshold: float = 7.5,
    turn_budget: int = 12,
) -> dict[str, Any]:
    _ensure_kb_seeded()

    session_id = f"demo-{uuid.uuid4().hex[:8]}"
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    provider = StaticAnswerProvider(CANNED_ANSWERS, default="I'd need to think about that more.")
    register_provider(session_id, provider)

    initial = build_initial_state(
        session_id=session_id,
        trace_id=trace_id,
        candidate=_fixture_candidate(),
        job_spec=_fixture_job_spec(),
        mode="mixed",
        runtime_config={"rag_top_k": 5, "use_sync_provider": True},
        max_turns=max_turns,
        quality_threshold=quality_threshold,
        turn_budget=turn_budget,
    )

    workflow = build_workflow()
    config: dict[str, Any] = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 60,
    }
    # Attach the same LangSmith metadata the API path emits so demos
    # surface alongside real interviews in the LangSmith dashboard
    # with identical filter keys. No-op when tracing is off.
    ls_settings = get_settings()
    config.update(
        build_langsmith_config(
            tracing_enabled=bool(ls_settings.langsmith_tracing),
            session_id=session_id,
            trace_id=trace_id,
            app_env=ls_settings.app_env,
            candidate_name=(initial.get("candidate") or {}).get("name"),
            job_level=(initial.get("job_spec") or {}).get("level"),
            job_title=(initial.get("job_spec") or {}).get("title"),
            mode=initial.get("mode"),
            turn_idx=int(initial.get("turn_idx") or 0),
            extra_tags=["source:run_demo"],
        )
    )

    log.info("Starting interview session=%s", session_id)
    try:
        final_state = workflow.invoke(initial, config=config)
    finally:
        unregister_provider(session_id)

    for turn in final_state.get("qa_history", []):
        _pretty_print_turn(turn)

    report = final_state.get("final_report", {})
    print("\n" + "#" * 78)
    print("FINAL REPORT")
    print("#" * 78)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    print("\n" + "#" * 78)
    print("CLOSED LOOP SUMMARY")
    print("#" * 78)
    print(json.dumps(_build_demo_summary(final_state), indent=2, ensure_ascii=False))

    return {"session_id": session_id, "state": final_state}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the text-mode interview demo")
    parser.add_argument("--turns", type=int, default=6, help="max_turns")
    parser.add_argument("--threshold", type=float, default=7.0, help="quality_threshold")
    parser.add_argument("--budget", type=int, default=10, help="turn_budget")
    args = parser.parse_args()
    run(max_turns=args.turns, quality_threshold=args.threshold, turn_budget=args.budget)


if __name__ == "__main__":
    main()
