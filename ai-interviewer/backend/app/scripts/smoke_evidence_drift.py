"""Smoke test for L1/L2: evidence spans + verifier drift monitor.

Forces ``EVIDENCE_SPAN_ALIGNMENT`` and ``ENABLE_VERIFIER_DRIFT_MONITOR``
ON via process env, then drives the Evaluator + Verification node
directly with an in-memory LLM stub that returns a **realistic**
canonical ``acceptance_check_results`` payload (real evidence
quotes), and finally hits the admin endpoint through FastAPI's
``TestClient``.

Why not ``run_demo``?
---------------------
``app.scripts.run_demo`` pulls in the full LangGraph workflow which
(a) goes through a pre-existing circular import between
``engine.context`` and ``engine.agents.session_summarizer`` during
first-time module import in a fresh process, and (b) uses the
``_stub_response`` LLM that does NOT emit ``evidence`` quotes, so we
cannot actually observe L2 output through it. Bypassing both is the
cleanest way to produce a deterministic end-to-end signal.

What this script proves
-----------------------
1. ``EVIDENCE_SPAN_ALIGNMENT=true`` at the env level reaches
   ``Settings`` and flows into ``evaluate_answer``, which emits the
   additive ``evidence_spans`` field.
2. ``ENABLE_VERIFIER_DRIFT_MONITOR=true`` at the env level reaches
   ``verification_node`` which records DriftEvents with correct
   aggregation (one verifier call -> one event).
3. ``GET /admin/drift/verifier`` serves the monitor snapshot with the
   expected JSON shape, proving the admin router wiring is live.

Exits non-zero on any missing signal so the script doubles as a
guard against silent rollback.

Usage::

    python -m app.scripts.smoke_evidence_drift
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any


def _force_knobs() -> None:
    """Flip the L1/L2 knobs in the process env **before** any
    ``app.core.settings`` import so the cached ``Settings`` picks
    them up on first construction.
    """
    os.environ["EVIDENCE_SPAN_ALIGNMENT"] = "true"
    os.environ["EVIDENCE_SPAN_FUZZY_THRESHOLD"] = "0.6"
    os.environ["ENABLE_VERIFIER_DRIFT_MONITOR"] = "true"
    os.environ["VERIFIER_DRIFT_WINDOW_SIZE"] = "20"
    os.environ.setdefault("LLM_PROVIDER", "stub")


_REAL_EVIDENCE_PAYLOAD = {
    "score": 7.8,
    "passed": True,
    "strengths": ["concrete TTL", "clear invalidation"],
    "weaknesses": [],
    "rubric_coverage": {"caching": "covered"},
    "acceptance_check_results": {
        "Names an invalidation strategy.": {
            "verdict": "yes",
            "evidence": ["invalidate on write"],
        },
        "Quantifies cache TTL.": {
            "verdict": "yes",
            "evidence": ["5-min TTL"],
        },
        "Discusses consistency trade-off.": {
            "verdict": "partial",
            "evidence": ["this quote is not in the answer"],
        },
    },
    "recommended_next": "advance",
    "recommended_next_plan": "adaptive",
    "rationale": "solid; partial on consistency.",
}


_VERIFIER_PARTIAL_PAYLOAD = {
    "verdict": "partial",
    "reasons_to_doubt": ["consistency quote does not actually appear in the answer"],
    "would_ask_next": "walk me through a concrete consistency failure",
    "confidence": 0.8,
    "rationale": "quote cited for consistency trade-off is not a substring of the candidate answer.",
}


def _patch_call_chat_for_role(
    eval_mod: Any, verif_mod: Any, *, eval_reply: str, verifier_reply: str
) -> None:
    """Replace the role-specific ``call_chat`` with a canned JSON
    response. We import the two modules because each caches its own
    reference to ``call_chat`` at import time (``from .llm_client
    import call_chat`` binds a local name), and patching the source
    module only is not enough.
    """

    def fake_eval_call(messages, *, json_mode=False, **_):  # type: ignore[no-untyped-def]
        return eval_reply

    def fake_verif_call(messages, *, json_mode=False, **_):  # type: ignore[no-untyped-def]
        return verifier_reply

    eval_mod.call_chat = fake_eval_call  # type: ignore[attr-defined]
    verif_mod.call_chat = fake_verif_call  # type: ignore[attr-defined]


def _assert_evidence_spans(
    acceptance_check_results: dict[str, Any], answer: str
) -> tuple[int, int, list[str]]:
    """Walk the evidence_spans and return (exact_hits, none_hits, errors)."""
    errors: list[str] = []
    exact_hits = 0
    none_hits = 0
    for check, value in acceptance_check_results.items():
        if not isinstance(value, dict) or "evidence_spans" not in value:
            errors.append(f"'{check}': no evidence_spans key")
            continue
        spans = value["evidence_spans"]
        evidence = value.get("evidence") or []
        if len(spans) != len(evidence):
            errors.append(
                f"'{check}': spans length {len(spans)} != evidence length {len(evidence)}"
            )
        for i, span in enumerate(spans):
            match = span.get("match")
            if match == "exact":
                exact_hits += 1
                sliced = answer[span["start"] : span["end"]]
                if sliced != span["text"]:
                    errors.append(
                        f"'{check}' span {i}: claims exact but slice {sliced!r} != text {span['text']!r}"
                    )
            elif match == "none":
                none_hits += 1
    return exact_hits, none_hits, errors


def main() -> int:
    _force_knobs()

    # Lazy imports so the env knobs are in place before settings
    # construction.
    from app.core.settings import get_settings

    get_settings.cache_clear()
    s = get_settings()
    print(
        f"[smoke] knobs resolved from env: "
        f"evidence_span_alignment={s.evidence_span_alignment} "
        f"enable_verifier_drift_monitor={s.enable_verifier_drift_monitor} "
        f"window_size={s.verifier_drift_window_size}"
    )
    if not (s.evidence_span_alignment and s.enable_verifier_drift_monitor):
        print(
            "[smoke] FAIL: env knobs did not flow into Settings "
            "(env vs Settings binding broken)."
        )
        return 1

    from app.engine.agents import evaluator_agent as eval_mod
    from app.engine.agents import verification as verif_mod
    from app.engine.workflow.nodes import verification as vnode_mod
    from app.ml.drift.verifier_drift import (
        get_verifier_drift_monitor,
        reset_verifier_drift_monitor_for_tests,
    )

    reset_verifier_drift_monitor_for_tests()
    _patch_call_chat_for_role(
        eval_mod,
        verif_mod,
        eval_reply=json.dumps(_REAL_EVIDENCE_PAYLOAD, ensure_ascii=False),
        verifier_reply=json.dumps(_VERIFIER_PARTIAL_PAYLOAD, ensure_ascii=False),
    )

    answer = (
        "We cache hot reads in Redis with a 5-min TTL and "
        "invalidate on write. For consistency we prefer eventual "
        "consistency with a compensating reconciliation job."
    )

    # --- L2 path: evaluate_answer should emit evidence_spans ---
    result = eval_mod.evaluate_answer(
        dimension="system_design",
        question="Walk me through your caching and consistency strategy.",
        rubric_points=["invalidation", "TTL", "consistency"],
        answer=answer,
        quality_threshold=7.0,
        contract={
            "must_cover": ["invalidation", "TTL", "consistency"],
            "acceptance_checks": [
                "Names an invalidation strategy.",
                "Quantifies cache TTL.",
                "Discusses consistency trade-off.",
            ],
        },
    )
    checks = result["acceptance_check_results"]
    exact_hits, none_hits, shape_errors = _assert_evidence_spans(checks, answer)

    print("\n" + "=" * 78)
    print("L2 EVALUATE_ANSWER OUTPUT")
    print("=" * 78)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "score": result["score"],
                "checks_with_spans": sum(
                    1 for v in checks.values() if isinstance(v, dict) and "evidence_spans" in v
                ),
                "exact_hits": exact_hits,
                "none_hits": none_hits,
                "sample_check": next(iter(checks.items())),
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    # --- L1 path: verification_node should record a DriftEvent ---
    state = {
        "current_question": {"question": "Q", "dimension": "system_design"},
        "current_dimension": "system_design",
        "current_answer": answer,
        "current_answer_raw": answer,
        "current_contract": {
            "must_cover": ["invalidation"],
            "acceptance_checks": ["Names an invalidation strategy."],
            "bar_level": "deep_probe",  # ensure should_trigger fires
        },
        "job_spec": {"level": "senior"},
        "quality_threshold": 7.0,
        "evaluation": result,
    }
    vnode_out = vnode_mod.verification_node(state)  # type: ignore[arg-type]
    drift_snapshot = get_verifier_drift_monitor().snapshot()

    print("\n" + "=" * 78)
    print("L1 VERIFICATION NODE + DRIFT MONITOR")
    print("=" * 78)
    print(
        json.dumps(
            {
                "verification_verdict": (vnode_out.get("verification") or {}).get("verdict"),
                "updated_passed": (vnode_out.get("evaluation") or {}).get("passed"),
                "drift": drift_snapshot,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    # --- Admin endpoint: prove the HTTP route + deps are live ---
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1 import admin as admin_api

    app = FastAPI()
    app.include_router(admin_api.router)
    with TestClient(app) as client:
        r = client.get("/admin/drift/verifier")
    print("\n" + "=" * 78)
    print("ADMIN ENDPOINT /admin/drift/verifier")
    print("=" * 78)
    print(f"status={r.status_code}")
    if r.status_code == 200:
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))

    # ---- verdicts ----
    errors: list[str] = list(shape_errors)
    if exact_hits < 2:
        errors.append(
            f"expected >=2 exact span hits, got {exact_hits} (L2 alignment broken?)"
        )
    if none_hits < 1:
        errors.append(
            "expected >=1 none-span (from the deliberately-unmatched quote), got 0"
        )
    if drift_snapshot.get("samples", 0) != 1:
        errors.append(
            f"expected drift samples=1 after one verifier call, got {drift_snapshot.get('samples')}"
        )
    if drift_snapshot.get("span_miss_rate", 0) == 0:
        errors.append(
            "expected non-zero span_miss_rate (none-span should propagate into drift)"
        )
    if r.status_code != 200:
        errors.append(f"/admin/drift/verifier returned {r.status_code} (expected 200)")
    if r.status_code == 200 and r.json().get("samples") != drift_snapshot.get("samples"):
        errors.append("admin endpoint and in-process snapshot disagree")

    if errors:
        print("\n" + "!" * 78)
        print("SMOKE FAILED")
        print("!" * 78)
        for e in errors:
            print(f" - {e}")
        return 1

    print("\n[smoke] OK: L1 + L2 end-to-end observable (env -> settings -> runtime -> admin)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
