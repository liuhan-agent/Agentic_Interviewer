"""P0 runtime smoke for the text interview workflow.

This script keeps the smoke path offline and deterministic by forcing
stub LLM/embedding providers, then reuses ``run_demo`` to execute the
real LangGraph workflow. It exits non-zero if the final state loses the
runtime signals that downstream demos, reports, and PR checks rely on.

Usage::

    python -m app.scripts.smoke_p0_runtime --turns 3 --budget 6
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from numbers import Real
from typing import Any


def _force_offline_runtime() -> None:
    """Make the smoke independent from local API keys or network state."""
    os.environ["LLM_PROVIDER"] = "stub"
    os.environ["EMBEDDING_PROVIDER"] = "stub"
    os.environ["CHECKPOINT_BACKEND"] = "memory"


def _is_non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def collect_smoke_errors(result: dict[str, Any], *, min_turns: int) -> list[str]:
    """Return human-readable contract errors for a ``run_demo.run`` result."""
    errors: list[str] = []

    session_id = result.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        errors.append("session_id missing")

    state = result.get("state")
    if not isinstance(state, dict):
        return errors + ["state missing or non-object"]

    qa_history = state.get("qa_history")
    if not isinstance(qa_history, list):
        errors.append("qa_history missing or non-list")
    elif len(qa_history) < min_turns:
        errors.append(f"qa_history has {len(qa_history)} turns, expected at least {min_turns}")

    report = state.get("final_report")
    if not isinstance(report, dict) or not report:
        report = {}
        errors.append("final_report missing")

    if not isinstance(report.get("overall_score"), Real):
        errors.append("final_report.overall_score missing or non-numeric")
    if not _is_non_empty_dict(report.get("training_plan")):
        errors.append("final_report.training_plan missing")

    artifacts = report.get("workflow_artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        errors.append("final_report.workflow_artifacts missing")

    for key in ("latest_ask_plan", "latest_contract"):
        if not _is_non_empty_dict(artifacts.get(key)):
            errors.append(f"workflow_artifacts.{key} missing")

    return errors


def build_smoke_summary(result: dict[str, Any]) -> dict[str, Any]:
    state = result.get("state") if isinstance(result.get("state"), dict) else {}
    report = state.get("final_report") if isinstance(state.get("final_report"), dict) else {}
    artifacts = (
        report.get("workflow_artifacts") if isinstance(report.get("workflow_artifacts"), dict) else {}
    )
    return {
        "session_id": result.get("session_id"),
        "turns": len(state.get("qa_history") or []),
        "overall_score": report.get("overall_score"),
        "training_plan_source": (report.get("training_plan") or {}).get("source"),
        "latest_plan_template": (artifacts.get("latest_ask_plan") or {}).get("template"),
        "contract_signed_by": (artifacts.get("latest_contract") or {}).get("signed_by"),
        "verification_verdict": (artifacts.get("latest_verification") or {}).get("verdict"),
    }


def run_smoke(*, turns: int, threshold: float, budget: int) -> int:
    _force_offline_runtime()

    from app.core.settings import get_settings
    from app.scripts.run_demo import run

    get_settings.cache_clear()
    result = run(max_turns=turns, quality_threshold=threshold, turn_budget=budget)
    errors = collect_smoke_errors(result, min_turns=turns)

    print("\n" + "=" * 78)
    print("P0 RUNTIME SMOKE SUMMARY")
    print("=" * 78)
    print(json.dumps(build_smoke_summary(result), indent=2, ensure_ascii=False))

    if errors:
        print("\n" + "!" * 78)
        print("P0 RUNTIME SMOKE FAILED")
        print("!" * 78)
        for error in errors:
            print(f" - {error}")
        return 1

    print("\n[smoke] OK: P0 runtime workflow completed with report artifacts")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the P0 runtime smoke")
    parser.add_argument("--turns", type=int, default=3, help="minimum completed turns")
    parser.add_argument("--threshold", type=float, default=7.0, help="quality threshold")
    parser.add_argument("--budget", type=int, default=6, help="turn budget")
    args = parser.parse_args()

    if args.turns < 1:
        parser.error("--turns must be >= 1")
    if args.budget < args.turns:
        parser.error("--budget must be >= --turns")

    return run_smoke(turns=args.turns, threshold=args.threshold, budget=args.budget)


if __name__ == "__main__":
    sys.exit(main())
