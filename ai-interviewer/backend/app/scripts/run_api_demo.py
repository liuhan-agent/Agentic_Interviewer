"""Hit the running FastAPI instance end-to-end.

Start the server first::

    uvicorn app.main:app --port 8765

Then::

    python -m app.scripts.run_api_demo --base http://localhost:8765
"""
from __future__ import annotations

import argparse
import json
import time

import httpx

DEFAULT_CANDIDATE = {
    "name": "Alex Chen",
    "resume_parsed": {
        "summary": "5y senior backend; payments, messaging.",
        "skills": ["python", "go", "postgres", "kafka"],
        "highlights": ["Migrated monolith to event-driven microservices."],
    },
}
DEFAULT_JOB = {
    "title": "Senior Backend Engineer",
    "level": "senior",
    "required_skills": ["python", "system_design", "databases"],
    "rubric_dimensions": ["technical_depth", "system_design", "leadership"],
    "rubric": {
        "technical_depth": "Concrete failure modes.",
        "system_design": "Trade-offs and scale reasoning.",
        "leadership": "Ownership of outcomes.",
    },
}
CANNED = [
    "Sure. At ShieldPay I built an idempotency layer with Redis and Lua.",
    "I once chased a 30s GC spike in a sidecar; eBPF traces nailed it.",
    "For a collab editor I'd reach for a sequence CRDT like Yjs.",
    "Disagreed with a senior eng on schema registry, wrote a comparison doc.",
    "Hardest mentorship moment: coaching a strong IC on code-review tone.",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8765")
    parser.add_argument("--max-turns", type=int, default=5)
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base, timeout=60, trust_env=False)
    print("health:", client.get("/health").json())

    resp = client.post(
        "/api/v1/interview/sessions",
        json={
            "candidate": DEFAULT_CANDIDATE,
            "job_spec": DEFAULT_JOB,
            "max_turns": args.max_turns,
            "quality_threshold": 7.0,
            "turn_budget": args.max_turns + 2,
        },
    )
    resp.raise_for_status()
    sid = resp.json()["session_id"]
    print("session:", sid)

    answers = iter(CANNED)
    for _ in range(args.max_turns + 3):
        q = client.get(f"/api/v1/interview/sessions/{sid}/question?timeout=20")
        q.raise_for_status()
        data = q.json()
        if data["status"] == "completed":
            print("\n=== COMPLETED ===")
            print(json.dumps(data["final_report"], indent=2, ensure_ascii=False))
            return
        question = data.get("question")
        if not question:
            time.sleep(0.5)
            continue
        print(f"\nTurn {data.get('turn_idx')}  Q: {question.get('question')}")
        answer = next(answers, "I'd need to think about that more.")
        print(f"          A: {answer[:90]}...")
        client.post(f"/api/v1/interview/sessions/{sid}/answer", json={"answer": answer})

    r = client.get(f"/api/v1/interview/sessions/{sid}/report")
    print("\nreport endpoint:", r.status_code, r.text[:600])


if __name__ == "__main__":
    main()
