"""Compare LLM-output vs keyword-inferred failure_categories.

PR6 P0 observation surface. The evaluator now emits
``failure_categories`` directly (PR1) while ``normalize_failure_category``
keeps producing a keyword-derived inference for the refine-followup
fallback path (PR2). Before we can decide whether to retire the
keyword path in P1, we need a per-window snapshot of how often the two
sources agree.

The aggregation reads the most recent ``limit`` evaluator
``GenerationTrace`` rows, runs ``normalize_failure_category`` on each
recorded evaluation's free-text fields, and buckets the comparison
into four mutually exclusive counters:

- ``llm_only``       — evaluator emitted at least one legal category,
                       the keyword normalizer would have returned None.
- ``normalize_only`` — evaluator emitted ``[]``, the keyword normalizer
                       would have produced a category.
- ``both``           — both sources non-empty.
- ``neither``        — both sources empty (clean pass, or both blind).

The output is intentionally schema-free for now: a small dataclass
plus ``as_dict`` so the admin endpoint can stream it as JSON without
pulling in pydantic.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.engine.workflow.probe_intent import normalize_failure_category
from app.models.generation_trace import GenerationTrace


@dataclass(frozen=True)
class FailureCategoryOverlapStats:
    sample_size: int
    limit: int
    llm_only: int
    normalize_only: int
    both: int
    neither: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def compute_failure_category_overlap_stats(
    *,
    session: Session,
    limit: int = 200,
) -> FailureCategoryOverlapStats:
    """Bucket the most recent ``limit`` evaluator traces into 4 counters.

    ``limit`` is hard-capped to ``[1, 1000]`` so a runaway query can't
    page in the whole trace table. Non-dict / missing ``evaluation``
    snapshots are skipped — they signal a malformed legacy row, not a
    real evaluator turn.
    """
    capped = max(1, min(int(limit or 200), 1000))
    rows = list(
        session.scalars(
            select(GenerationTrace)
            .where(GenerationTrace.node == "evaluator")
            .order_by(desc(GenerationTrace.id))
            .limit(capped)
        )
    )

    llm_only = 0
    normalize_only = 0
    both = 0
    neither = 0
    sample_size = 0
    for row in rows:
        evaluation = row.evaluation
        if not isinstance(evaluation, dict):
            continue
        sample_size += 1
        llm_cats = [
            str(item).strip()
            for item in (evaluation.get("failure_categories") or [])
            if isinstance(item, str) and str(item).strip()
        ]
        inferred = normalize_failure_category(
            failure_reason=evaluation.get("failure_reason"),
            weaknesses=evaluation.get("weaknesses") or [],
            missing_must_cover=[
                key
                for key, status in (evaluation.get("rubric_coverage") or {}).items()
                if status == "missing"
            ],
        )
        llm_has = bool(llm_cats)
        norm_has = bool(inferred)
        if llm_has and norm_has:
            both += 1
        elif llm_has:
            llm_only += 1
        elif norm_has:
            normalize_only += 1
        else:
            neither += 1

    return FailureCategoryOverlapStats(
        sample_size=sample_size,
        limit=capped,
        llm_only=llm_only,
        normalize_only=normalize_only,
        both=both,
        neither=neither,
    )
