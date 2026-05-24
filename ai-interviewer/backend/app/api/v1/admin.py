"""Admin observability router.

All routes under ``/admin/*`` are read-only observability surfaces.
They are gated behind :func:`require_admin_token` which enforces a
bearer token when ``settings.api_token`` is non-empty. When no token is
configured, routes fail closed unless ``ALLOW_OPEN_ADMIN=true`` is set
explicitly for a local demo.

The router is intentionally excluded from the generated OpenAPI
schema so the admin surface is not advertised to casual clients.
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session

log = get_logger(__name__)

router = APIRouter(prefix="/admin", include_in_schema=False, tags=["admin"])
api_v1_router = APIRouter(
    prefix="/api/v1/admin", include_in_schema=False, tags=["admin"]
)

_HISTORY_STATUS_FILTERS = {"running", "completed", "cancelled", "errored"}
_HISTORY_TRACE_HEALTH_FILTERS = {"missing", "partial", "complete"}
_HISTORY_SINCE_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}


def _langsmith_web_url(api_endpoint: str | None) -> str:
    """Infer the LangSmith web URL from the configured API endpoint."""
    endpoint = (api_endpoint or "").strip().strip('"').strip("'").rstrip("/")
    if not endpoint:
        return "https://smith.langchain.com"

    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return "https://smith.langchain.com"

    path = parsed.path or ""
    if path.endswith("/api/v1"):
        return urlunparse(
            parsed._replace(path=path[: -len("/api/v1")] or "", query="", fragment="")
        )
    if path.endswith("/api"):
        return urlunparse(
            parsed._replace(path=path[: -len("/api")] or "", query="", fragment="")
        )

    netloc = parsed.netloc.lower()
    if netloc.startswith("eu."):
        return "https://eu.smith.langchain.com"
    if netloc.startswith("aws."):
        return "https://aws.smith.langchain.com"
    if netloc.startswith("dev."):
        return "https://dev.smith.langchain.com"
    if netloc.startswith("beta."):
        return "https://beta.smith.langchain.com"
    return "https://smith.langchain.com"


def _langsmith_admin_meta() -> dict[str, Any]:
    settings = get_settings()
    return {
        "tracing_enabled": bool(getattr(settings, "langsmith_tracing", False)),
        "project": getattr(
            settings,
            "effective_langsmith_project",
            getattr(settings, "langsmith_project", "agentic-interviewer"),
        ),
        "web_url": _langsmith_web_url(getattr(settings, "langsmith_endpoint", None)),
    }


def _latest_langsmith_run_ids(session_ids: list[str]) -> dict[str, str]:
    """Return the newest known LangSmith run id per session."""
    wanted = [sid for sid in session_ids if sid]
    if not wanted:
        return {}

    try:
        from app.models import GenerationTrace, get_session

        with get_session() as sess:
            rows = (
                sess.query(
                    GenerationTrace.session_id,
                    GenerationTrace.langsmith_run_id,
                )
                .filter(GenerationTrace.session_id.in_(wanted))
                .filter(GenerationTrace.langsmith_run_id.isnot(None))
                .order_by(GenerationTrace.created_at.desc(), GenerationTrace.id.desc())
                .all()
            )
    except Exception as e:  # pragma: no cover - admin must remain best-effort
        log.warning("admin sessions: langsmith run lookup failed: %s", e)
        return {}

    latest: dict[str, str] = {}
    for session_id, run_id in rows:
        if session_id not in latest and run_id:
            latest[str(session_id)] = str(run_id)
    return latest


def require_admin_token(
    authorization: str | None = Header(default=None),
) -> None:
    """Fail any request that doesn't carry the configured bearer token.

    When ``settings.api_token`` is empty, admin routes fail closed
    unless ``settings.allow_open_admin`` is explicitly enabled for a
    local demo.
    Non-empty tokens are compared with a constant-time check to
    avoid timing oracle leaks.
    """
    settings = get_settings()
    expected = settings.api_token
    if not expected:
        if getattr(settings, "app_env", "dev") == "prod":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API_TOKEN must be configured in production",
            )
        if not getattr(settings, "allow_open_admin", False):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API_TOKEN must be configured or ALLOW_OPEN_ADMIN=true",
            )
        return
    scheme, _, provided = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin endpoint requires Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    import hmac

    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid admin token",
        )


def _knowledge_coverage_payload(root: Path) -> dict[str, Any]:
    """Summarise ingestible knowledge files by ``source_type``."""
    from app.engine.rag.ingestion import _iter_documents

    chunks_by_type: dict[str, int] = {}
    files_by_type: dict[str, set[str]] = {}
    for _, meta in _iter_documents(root):
        source_type = str(meta.get("source_type") or "misc")
        source = str(meta.get("source") or "")
        chunks_by_type[source_type] = chunks_by_type.get(source_type, 0) + 1
        if source:
            files_by_type.setdefault(source_type, set()).add(source)

    by_source_type = {
        source_type: {
            "files": len(files_by_type.get(source_type, set())),
            "chunks": chunks_by_type.get(source_type, 0),
        }
        for source_type in sorted(files_by_type.keys() | chunks_by_type.keys())
    }
    return {
        "by_source_type": by_source_type,
        "total_files": sum(item["files"] for item in by_source_type.values()),
        "total_chunks": sum(item["chunks"] for item in by_source_type.values()),
    }


@router.get("/bandit/snapshot", dependencies=[Depends(require_admin_token)])
def bandit_snapshot() -> dict[str, Any]:
    """Return the current Thompson posterior + policy knobs.

    Payload shape is stable so operators can wire simple Grafana
    panels against it without re-parsing JSON every release.
    """
    from app.ml.rl.thompson import get_bandit
    from app.services.strategy_learning_facts import bandit_posterior_snapshot

    s = get_settings()
    priors = get_bandit().snapshot()
    try:
        posterior_summary = bandit_posterior_snapshot(limit=10)
    except Exception as e:  # pragma: no cover - admin summary is best-effort
        log.warning("bandit posterior summary unavailable: %s", e)
        posterior_summary = {
            "persisted_prior_count": 0,
            "top_posteriors": [],
        }
    persisted_prior_count = int(posterior_summary.get("persisted_prior_count") or 0)
    return {
        "priors": priors,
        "memory_prior_count": len(priors),
        "persisted_prior_count": persisted_prior_count,
        "top_posteriors": list(posterior_summary.get("top_posteriors") or []),
        "posterior_source": (
            "db_aggregate" if persisted_prior_count > 0 else "memory_only"
        ),
        "policy_mode": s.policy_mode,
        "exploration_rate": s.thompson_exploration_rate,
        "decay": {
            "enabled": s.enable_bandit_decay,
            "factor": s.bandit_decay_factor,
            "floor": s.bandit_decay_floor,
            "interval_days": s.bandit_decay_interval_days,
        },
    }


@router.get("/drift/verifier", dependencies=[Depends(require_admin_token)])
def verifier_drift_snapshot() -> dict[str, Any]:
    """Return the current verifier-drift rolling-window aggregates.

    Payload mirrors
    :meth:`app.ml.drift.verifier_drift.VerifierDriftMonitor.snapshot`
    plus an ``enabled`` meta field so dashboards can distinguish
    "monitor off" from "monitor on but no samples yet".
    """
    from app.ml.drift.verifier_drift import get_verifier_drift_monitor

    s = get_settings()
    snap = get_verifier_drift_monitor().snapshot()
    snap["enabled"] = s.enable_verifier_drift_monitor
    return snap


# ---------------------------------------------------------------------------
# Persisted-drift admin routes (PR6 of drift-feedback persistence)
#
# These four routes surface the ``verifier_drift_events`` /
# ``verifier_drift_patterns`` tables and the aggregation / retention
# triggers so an operator can monitor the rollout without raw SQL.
# Implementation notes:
#
# * GET endpoints clamp limits / windows so a misconfigured client cannot
#   trigger a table scan; payloads stay best-effort (empty list + meta)
#   when the DB hand-off fails so the panel never returns a 500.
# * POST endpoints reuse the task wrappers in ``app/tasks/`` so the same
#   entrypoints can be wired into APScheduler later without divergence.
# * Both GETs include enough meta (``persistence_enabled`` /
#   ``feedback_source``) for the dashboard to render "off but waiting for
#   data" vs "on with empty table" without a second lookup.
# ---------------------------------------------------------------------------

_DRIFT_EVENTS_SINCE_HOURS_CAP = 24 * 30  # 30 days
_DRIFT_EVENTS_LIMIT_CAP = 1000
_DRIFT_PATTERNS_LIMIT_CAP = 500


def _drift_event_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "trace_id": row.trace_id,
        "turn_idx": row.turn_idx,
        "dimension": row.dimension,
        "job_level": row.job_level,
        "evaluator_passed": bool(row.evaluator_passed),
        "verifier_verdict": row.verifier_verdict,
        "verifier_confidence": row.verifier_confidence,
        "verifier_abstained": bool(row.verifier_abstained),
        "overruled": bool(row.overruled),
        "span_miss_count": row.span_miss_count,
        "span_total": row.span_total,
        "overruled_check_name": row.overruled_check_name,
        "evaluator_evidence_quotes": list(
            row.evaluator_evidence_quotes or []
        ),
        "verifier_reasons": list(row.verifier_reasons or []),
        "failure_categories": list(row.failure_categories or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _drift_pattern_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "dimension": row.dimension,
        "check_name": row.check_name,
        "failure_category": row.failure_category,
        "uses": row.uses,
        "overruled_count": row.overruled_count,
        "overrule_rate": row.overrule_rate,
        "sample_evidence": list(row.sample_evidence or []),
        "reasons_sample": list(row.reasons_sample or []),
        "first_seen_at": row.first_seen_at.isoformat()
        if row.first_seen_at
        else None,
        "last_seen_at": row.last_seen_at.isoformat()
        if row.last_seen_at
        else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/drift/events", dependencies=[Depends(require_admin_token)])
def list_drift_events(
    since_hours: int = 24,
    limit: int = 200,
    overruled_only: bool = True,
) -> dict[str, Any]:
    """Return persisted drift events for the most recent ``since_hours``.

    Defaults reflect the headline use case: surface the last day of
    overruled events so an operator can sanity-check the dual-write
    output. ``overruled_only=False`` includes clean / abstain events
    for full audit traces.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.verifier_drift import VerifierDriftEvent

    clamped_since = max(1, min(int(since_hours or 1), _DRIFT_EVENTS_SINCE_HOURS_CAP))
    clamped_limit = max(1, min(int(limit or 200), _DRIFT_EVENTS_LIMIT_CAP))
    # SQLite serialises tz-aware datetimes with a ``+00:00`` suffix while
    # round-tripping the column reads back as tz-naive — a string-prefix
    # comparison then makes ``cutoff`` look ~30µs newer than a row stamped
    # in the same second. Strip the tzinfo so the comparison uses
    # identical wall-clock representations on both SQLite (dev / CI) and
    # Postgres (prod), without changing the semantic UTC anchor.
    cutoff = (datetime.now(UTC) - timedelta(hours=clamped_since)).replace(
        tzinfo=None
    )
    settings = get_settings()

    payload: dict[str, Any] = {
        "since_hours": clamped_since,
        "limit": clamped_limit,
        "overruled_only": bool(overruled_only),
        "persistence_enabled": bool(
            getattr(settings, "enable_verifier_drift_persistence", False)
        ),
        "count": 0,
        "events": [],
    }
    try:
        with get_session() as sess:
            q = sess.query(VerifierDriftEvent).filter(
                VerifierDriftEvent.created_at >= cutoff
            )
            if overruled_only:
                q = q.filter(VerifierDriftEvent.overruled.is_(True))
            rows = (
                q.order_by(
                    VerifierDriftEvent.created_at.desc(),
                    VerifierDriftEvent.id.desc(),
                )
                .limit(clamped_limit)
                .all()
            )
    except Exception as e:  # pragma: no cover - admin must remain best-effort
        log.warning("list_drift_events query failed: %s", e)
        return payload

    payload["count"] = len(rows)
    payload["events"] = [_drift_event_payload(row) for row in rows]
    return payload


@router.get("/drift/patterns", dependencies=[Depends(require_admin_token)])
def list_drift_patterns(
    dimension: str | None = None,
    failure_category: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return the aggregated drift patterns read model.

    Optional ``dimension`` and ``failure_category`` filters let
    dashboards drill into specific buckets; ``feedback_source`` meta
    tells the dashboard which renderer the deployment is currently
    using (monitor / db_shadow / db) so the operator can spot
    misalignment between data and prompt path.
    """
    from app.models.verifier_drift import VerifierDriftPattern

    clamped_limit = max(1, min(int(limit or 100), _DRIFT_PATTERNS_LIMIT_CAP))
    settings = get_settings()
    payload: dict[str, Any] = {
        "dimension": dimension,
        "failure_category": failure_category,
        "limit": clamped_limit,
        "feedback_source": str(
            getattr(settings, "drift_feedback_source", "monitor") or "monitor"
        ),
        "count": 0,
        "patterns": [],
    }
    try:
        with get_session() as sess:
            q = sess.query(VerifierDriftPattern)
            if dimension is not None:
                q = q.filter(VerifierDriftPattern.dimension == dimension)
            if failure_category is not None:
                q = q.filter(
                    VerifierDriftPattern.failure_category == failure_category
                )
            rows = (
                q.order_by(
                    VerifierDriftPattern.uses.desc(),
                    VerifierDriftPattern.dimension.asc(),
                    VerifierDriftPattern.check_name.asc(),
                )
                .limit(clamped_limit)
                .all()
            )
    except Exception as e:  # pragma: no cover - admin must remain best-effort
        log.warning("list_drift_patterns query failed: %s", e)
        return payload

    payload["count"] = len(rows)
    payload["patterns"] = [_drift_pattern_payload(row) for row in rows]
    return payload


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@router.get("/drift/freshness", dependencies=[Depends(require_admin_token)])
def drift_freshness() -> dict[str, Any]:
    """Return scheduler and DB freshness meta for persisted drift."""
    from sqlalchemy import func

    from app.models.verifier_drift import VerifierDriftEvent, VerifierDriftPattern
    from app.tasks.drift_maintenance_tasks import get_drift_maintenance_status

    settings = get_settings()
    payload: dict[str, Any] = {
        "scheduler_enabled": bool(
            getattr(settings, "enable_drift_maintenance_scheduler", False)
        ),
        "aggregation_interval_minutes": int(
            getattr(settings, "drift_pattern_aggregation_interval_minutes", 30)
            or 30
        ),
        "retention_interval_hours": int(
            getattr(settings, "drift_event_retention_interval_hours", 24) or 24
        ),
        "persistence_enabled": bool(
            getattr(settings, "enable_verifier_drift_persistence", False)
        ),
        "feedback_source": str(
            getattr(settings, "drift_feedback_source", "monitor") or "monitor"
        ),
        "maintenance": get_drift_maintenance_status(),
        "event_count": 0,
        "pattern_count": 0,
        "newest_event_at": None,
        "newest_pattern_updated_at": None,
    }
    try:
        with get_session() as sess:
            payload["event_count"] = int(
                sess.query(func.count(VerifierDriftEvent.id)).scalar() or 0
            )
            payload["pattern_count"] = int(
                sess.query(func.count(VerifierDriftPattern.id)).scalar() or 0
            )
            payload["newest_event_at"] = _iso_or_none(
                sess.query(func.max(VerifierDriftEvent.created_at)).scalar()
            )
            payload["newest_pattern_updated_at"] = _iso_or_none(
                sess.query(func.max(VerifierDriftPattern.updated_at)).scalar()
            )
    except Exception as e:  # pragma: no cover - admin must remain best-effort
        log.warning("drift freshness query failed: %s", e)
        payload["db_error"] = str(e)
    return payload


@router.post(
    "/drift/aggregation/run",
    dependencies=[Depends(require_admin_token)],
)
def run_drift_pattern_aggregation_route() -> dict[str, int]:
    """Trigger one drift-pattern aggregation pass on demand.

    Wraps :func:`run_drift_pattern_aggregation_now` so the admin
    surface and a future scheduler share the same entrypoint;
    idempotent so an operator can re-run it after manually mutating
    the events table.
    """
    from app.tasks.drift_maintenance_tasks import (
        run_drift_pattern_aggregation_tracked,
    )

    return run_drift_pattern_aggregation_tracked()


@router.post(
    "/drift/retention/run",
    dependencies=[Depends(require_admin_token)],
)
def run_drift_event_retention_route() -> dict[str, int]:
    """Trigger one retention sweep on demand.

    Wraps :func:`run_drift_event_retention_now`; idempotent so a
    repeated call with no new stale rows simply returns
    ``{"deleted": 0}``.
    """
    from app.tasks.drift_maintenance_tasks import (
        run_drift_event_retention_tracked,
    )

    return run_drift_event_retention_tracked()


_DRIFT_PARITY_TOP_N_CAP = 50
_DRIFT_PARITY_MIN_SUPPORT_CAP = 1000


@router.get(
    "/drift/shadow-parity",
    dependencies=[Depends(require_admin_token)],
)
def drift_shadow_parity(
    top_n: int = 5,
    min_support: int = 2,
    dimensions: str | None = None,
) -> dict[str, Any]:
    """Compare monitor vs DB read paths to gate the ``db_shadow`` flip.

    Returns the per-dimension intersection / monitor-only / db-only
    pattern keys plus Jaccard similarity. Operators flip
    ``drift_feedback_source`` from ``"db_shadow"`` to ``"db"`` only
    after average Jaccard sits ≥ 0.9 across a week — see
    ``docs/PLAN_DRIFT_PERSISTENCE.md §7``.

    Parameters
    ----------
    top_n
        Maximum patterns each side surfaces per dimension. Clamped to
        the same window the renderers use so the parity matches what
        a candidate would actually receive.
    min_support
        Minimum ``count`` per pattern before it counts towards either
        side. Matches the renderer defaults so low-noise patterns do
        not poison the diff.
    dimensions
        Optional comma-separated allowlist (``"system_design,coding"``).
        Empty / omitted triggers an auto-scan over the union of
        ``monitor.snapshot()["per_dimension"].keys()`` and
        ``SELECT DISTINCT dimension FROM verifier_drift_patterns``.
    """
    from app.services.drift_feedback_parity import compute_drift_feedback_parity

    clamped_top_n = max(1, min(int(top_n or 5), _DRIFT_PARITY_TOP_N_CAP))
    clamped_min_support = max(
        1, min(int(min_support or 2), _DRIFT_PARITY_MIN_SUPPORT_CAP)
    )
    dim_list: list[str] | None
    if dimensions:
        dim_list = [d.strip() for d in dimensions.split(",") if d.strip()]
        if not dim_list:
            dim_list = None
    else:
        dim_list = None

    try:
        result = compute_drift_feedback_parity(
            dimensions=dim_list,
            top_n=clamped_top_n,
            min_support=clamped_min_support,
        )
        return result.asdict()
    except Exception as e:  # pragma: no cover - admin remains best-effort
        log.warning("drift shadow parity failed: %s", e)
        settings = get_settings()
        return {
            "top_n": clamped_top_n,
            "min_support": clamped_min_support,
            "feedback_source": str(
                getattr(settings, "drift_feedback_source", "monitor")
                or "monitor"
            ),
            "monitor_backend": str(
                getattr(settings, "verifier_drift_backend", "memory")
                or "memory"
            ),
            "per_dimension": [],
            "summary": {
                "dimensions_checked": 0,
                "avg_jaccard": None,
                "min_jaccard": None,
                "max_jaccard": None,
            },
            "db_error": str(e),
        }


@api_v1_router.get("/knowledge/coverage", dependencies=[Depends(require_admin_token)])
@router.get("/knowledge/coverage", dependencies=[Depends(require_admin_token)])
def knowledge_coverage() -> dict[str, Any]:
    """Return ingestible knowledge-file and chunk coverage by source type."""
    return _knowledge_coverage_payload(Path(get_settings().knowledge_dir))


@router.get("/sessions", dependencies=[Depends(require_admin_token)])
def list_sessions() -> dict[str, Any]:
    """Enumerate active session handles held by the session manager.

    Useful for debugging durable HITL flows: operators can see which
    sessions are interrupted, running, or done without rummaging
    through logs.
    """
    from app.services.session_manager import get_session_manager

    mgr = get_session_manager()
    items = mgr.snapshot()
    run_ids = _latest_langsmith_run_ids(
        [str(item.get("session_id")) for item in items if item.get("session_id")]
    )
    sessions = [
        {
            **item,
            "langsmith_run_id": run_ids.get(str(item.get("session_id")))
            or item.get("langsmith_run_id"),
        }
        for item in items
    ]
    return {
        "count": len(sessions),
        "langsmith": _langsmith_admin_meta(),
        "sessions": sessions,
    }


def _history_filter_value(
    value: str | None,
    *,
    allowed: set[str],
    name: str,
) -> str | None:
    text = (value or "").strip().lower()
    if not text or text == "all":
        return None
    if text not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{name} must be one of: {', '.join(sorted(allowed))}",
        )
    return text


def _history_since_value(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text or text == "all":
        return None
    if text not in _HISTORY_SINCE_HOURS:
        raise HTTPException(
            status_code=422,
            detail=f"since must be one of: {', '.join(_HISTORY_SINCE_HOURS)}",
        )
    return text


def _history_search_value(value: str | None) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:120] or None


def _apply_history_db_filters(
    query: Any,
    InterviewSession: Any,
    *,
    status_filter: str | None = None,
    q: str | None = None,
    since: str | None = None,
) -> Any:
    from sqlalchemy import or_

    if status_filter:
        query = query.filter(InterviewSession.status == status_filter)
    if since:
        cutoff = datetime.now(UTC) - timedelta(hours=_HISTORY_SINCE_HOURS[since])
        query = query.filter(InterviewSession.created_at >= cutoff)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                InterviewSession.session_id.ilike(pattern),
                InterviewSession.candidate_name.ilike(pattern),
                InterviewSession.job_title.ilike(pattern),
            )
        )
    return query


def _trace_counts_for_sessions(
    sess: Any,
    session_ids: list[str],
) -> dict[str, dict[str, int]]:
    from sqlalchemy import func

    from app.models import GenerationTrace

    trace_counts: dict[str, dict[str, int]] = {session_id: {} for session_id in session_ids}
    if not session_ids:
        return trace_counts
    for session_id, node, count in (
        sess.query(
            GenerationTrace.session_id,
            GenerationTrace.node,
            func.count(GenerationTrace.id),
        )
        .filter(GenerationTrace.session_id.in_(session_ids))
        .group_by(GenerationTrace.session_id, GenerationTrace.node)
        .all()
    ):
        trace_counts.setdefault(str(session_id), {})[str(node)] = int(count)
    return trace_counts


def _session_history_item(row: Any, node_counts: dict[str, int]) -> dict[str, Any]:
    report = row.final_report or {}
    trace_count = sum(node_counts.values())
    evaluator_trace_count = int(node_counts.get("evaluator", 0))
    reward_trace_count = int(node_counts.get("reward_update", 0))
    final_report_trace_count = int(node_counts.get("final_report", 0))
    trace_health = _trace_health(
        [
            {"node": node}
            for node, count in node_counts.items()
            for _ in range(max(0, count))
        ],
        session_status=row.status,
    )
    return {
        "session_id": row.session_id,
        "trace_id": row.trace_id,
        "candidate_name": row.candidate_name,
        "job_title": row.job_title,
        "job_level": row.job_level,
        "mode": row.mode,
        "status": row.status,
        "turn_idx": row.turn_idx,
        "asked_turn": row.asked_turn,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "has_report": bool(report),
        "overall_score": report.get("overall_score"),
        "overall_verdict": report.get("overall_verdict") or report.get("verdict"),
        "trace_count": trace_count,
        "evaluator_trace_count": evaluator_trace_count,
        "reward_trace_count": reward_trace_count,
        "final_report_trace_count": final_report_trace_count,
        "trace_health": trace_health,
        "error_kind": row.error_kind,
        "retryable": bool(row.retryable),
        "cost_summary": report.get("cost_summary"),
    }


def _recent_interview_sessions(
    limit: int = 20,
    offset: int = 0,
    *,
    status_filter: str | None = None,
    trace_health_filter: str | None = None,
    has_report_filter: bool | None = None,
    q: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent persisted interview sessions for admin history."""
    from app.models import InterviewSession, get_session

    capped_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    try:
        with get_session() as sess:
            query = _apply_history_db_filters(
                sess.query(InterviewSession),
                InterviewSession,
                status_filter=status_filter,
                q=q,
                since=since,
            ).order_by(InterviewSession.created_at.desc())
            needs_python_filter = (
                trace_health_filter is not None or has_report_filter is not None
            )
            rows = (
                query.all()
                if needs_python_filter
                else query.offset(safe_offset).limit(capped_limit).all()
            )
            trace_counts = _trace_counts_for_sessions(
                sess,
                [row.session_id for row in rows],
            )
    except Exception as e:  # pragma: no cover - admin remains best-effort
        log.warning("admin interview sessions lookup failed: %s", e)
        return []

    items: list[dict[str, Any]] = []
    for row in rows:
        item = _session_history_item(row, trace_counts.get(row.session_id, {}))
        if has_report_filter is not None and item["has_report"] is not has_report_filter:
            continue
        if trace_health_filter is not None and item["trace_health"] != trace_health_filter:
            continue
        items.append(item)
    if needs_python_filter:
        return items[safe_offset : safe_offset + capped_limit]
    return items


def _interview_session_total_count(
    *,
    status_filter: str | None = None,
    trace_health_filter: str | None = None,
    has_report_filter: bool | None = None,
    q: str | None = None,
    since: str | None = None,
) -> int:
    """Return total persisted interview session rows, independent of page limit."""
    from sqlalchemy import func

    from app.models import InterviewSession, get_session

    try:
        with get_session() as sess:
            base_query = _apply_history_db_filters(
                sess.query(InterviewSession),
                InterviewSession,
                status_filter=status_filter,
                q=q,
                since=since,
            )
            needs_python_filter = (
                trace_health_filter is not None or has_report_filter is not None
            )
            if not needs_python_filter:
                return int(
                    base_query.with_entities(
                        func.count(InterviewSession.session_id)
                    ).scalar()
                    or 0
                )
            rows = base_query.all()
            trace_counts = _trace_counts_for_sessions(
                sess,
                [row.session_id for row in rows],
            )
            total = 0
            for row in rows:
                item = _session_history_item(
                    row,
                    trace_counts.get(row.session_id, {}),
                )
                if (
                    has_report_filter is not None
                    and item["has_report"] is not has_report_filter
                ):
                    continue
                if (
                    trace_health_filter is not None
                    and item["trace_health"] != trace_health_filter
                ):
                    continue
                total += 1
            return total
    except Exception as e:  # pragma: no cover - admin remains best-effort
        log.warning("admin interview session count lookup failed: %s", e)
        return 0


def _trace_health(
    nodes: list[dict[str, Any]],
    *,
    session_status: str | None = None,
) -> str:
    """Backwards-compatible wrapper around the shared classifier.

    The actual rule set lives in
    :func:`app.services.trace_health.classify_trace_health` so the
    candidate-facing report API and this admin surface agree on what
    "complete" means.  Keep this thin shim so existing imports
    (``from app.api.v1.admin import _trace_health``) stay working.
    """
    from app.services.trace_health import classify_trace_health

    return classify_trace_health(nodes, session_status=session_status)


def _answer_excerpt(value: Any, *, limit: int = 220) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _trace_node_payload(trace: Any) -> dict[str, Any]:
    snapshot = trace.state_snapshot or {}
    payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
    summary = payload if isinstance(payload, dict) else {}
    if not summary and isinstance(snapshot, dict):
        summary = {
            key: snapshot.get(key)
            for key in (
                "diagnostics",
                "selected_action",
                "dimension_status",
                "target_difficulty",
                "timing",
            )
            if snapshot.get(key) is not None
        }
    return {
        "id": trace.id,
        "turn_idx": trace.turn_idx,
        "node": trace.node,
        "dimension": trace.dimension,
        "action_id": trace.action_id,
        "policy_id": trace.policy_id,
        "context_key": trace.context_key,
        "policy_context_keys": trace.policy_context_keys,
        "score": trace.score,
        "passed": trace.passed,
        "immediate_reward": trace.immediate_reward,
        "immediate_reward_applied": bool(trace.immediate_reward_applied),
        "question": trace.question,
        "answer_excerpt": _answer_excerpt(trace.answer),
        "evaluation": trace.evaluation,
        "payload": summary,
        "langsmith_run_id": trace.langsmith_run_id,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }


def _trace_record_from_unknown(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _trace_record_has_fallback_marker(record: dict[str, Any]) -> bool:
    if record.get("source") == "fallback":
        return True
    if str(record.get("fallback_reason") or "").strip():
        return True
    weaknesses = record.get("weaknesses")
    if isinstance(weaknesses, list):
        return any("fallback" in str(item or "").lower() for item in weaknesses)
    return False


def _trace_has_evaluator_fallback(trace: Any) -> bool:
    if getattr(trace, "node", None) != "evaluator":
        return False
    evaluation = _trace_record_from_unknown(getattr(trace, "evaluation", None))
    snapshot = _trace_record_from_unknown(getattr(trace, "state_snapshot", None))
    payload = _trace_record_from_unknown(snapshot.get("payload"))
    return (
        _trace_record_has_fallback_marker(evaluation)
        or _trace_record_has_fallback_marker(_trace_record_from_unknown(payload.get("evaluation")))
        or _trace_record_has_fallback_marker(payload)
    )


def _interview_session_trace_payload(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    from sqlalchemy import func

    from app.models import GenerationTrace, InterviewSession, get_session

    capped_limit = max(1, min(int(limit or 100), 300))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    with get_session() as sess:
        row = sess.get(InterviewSession, session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        summary_rows = (
            sess.query(GenerationTrace.node, func.count(GenerationTrace.id))
            .filter(GenerationTrace.session_id == session_id)
            .group_by(GenerationTrace.node)
            .all()
        )
        all_traces = (
            sess.query(GenerationTrace)
            .filter(GenerationTrace.session_id == session_id)
            .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
            .all()
        )
        traces = (
            sess.query(GenerationTrace)
            .filter(GenerationTrace.session_id == session_id)
            .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
            .offset(safe_offset)
            .limit(capped_limit)
            .all()
        )

    nodes = [_trace_node_payload(trace) for trace in traces]
    report = row.final_report or {}
    from app.services.trace_health import trace_diagnostics

    node_counts = {str(node or ""): int(count) for node, count in summary_rows}
    total_trace_count = sum(node_counts.values())
    summary_nodes = [{"node": node} for node in node_counts]
    diagnostics = trace_diagnostics(summary_nodes, session_status=row.status)
    last_trace = all_traces[-1] if all_traces else None
    if last_trace is not None:
        diagnostics["last_node"] = last_trace.node
    return {
        "session_id": row.session_id,
        "trace_id": row.trace_id,
        "status": row.status,
        "has_report": bool(report),
        "overall_score": report.get("overall_score"),
        "overall_verdict": report.get("overall_verdict") or report.get("verdict"),
        "trace_count": total_trace_count,
        "evaluator_trace_count": int(node_counts.get("evaluator", 0)),
        "reward_trace_count": int(node_counts.get("reward_update", 0)),
        "final_report_trace_count": int(node_counts.get("final_report", 0)),
        "trace_health": _trace_health(summary_nodes, session_status=row.status),
        "trace_diagnostics": diagnostics,
        "langsmith": _langsmith_admin_meta(),
        "node_count_total": total_trace_count,
        "node_type_counts": node_counts,
        "fallback_trace_count": sum(
            1 for trace in all_traces if _trace_has_evaluator_fallback(trace)
        ),
        "turn_count": len(
            {
                trace.turn_idx
                for trace in all_traces
                if getattr(trace, "turn_idx", None) is not None
            }
        ),
        "nodes_offset": safe_offset,
        "nodes_limit": capped_limit,
        "nodes_has_more": safe_offset + len(nodes) < total_trace_count,
        "nodes": nodes,
    }


@router.get("/interview-sessions", dependencies=[Depends(require_admin_token)])
def list_interview_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    status: str | None = Query(default=None),
    trace_health: str | None = Query(default=None),
    has_report: bool | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
    since: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return recent persisted interview sessions from the database."""
    capped_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    status_filter = _history_filter_value(
        status,
        allowed=_HISTORY_STATUS_FILTERS,
        name="status",
    )
    trace_health_filter = _history_filter_value(
        trace_health,
        allowed=_HISTORY_TRACE_HEALTH_FILTERS,
        name="trace_health",
    )
    since_filter = _history_since_value(since)
    search_filter = _history_search_value(q)
    sessions = _recent_interview_sessions(
        limit=capped_limit,
        offset=safe_offset,
        status_filter=status_filter,
        trace_health_filter=trace_health_filter,
        has_report_filter=has_report,
        q=search_filter,
        since=since_filter,
    )
    total_count = _interview_session_total_count(
        status_filter=status_filter,
        trace_health_filter=trace_health_filter,
        has_report_filter=has_report,
        q=search_filter,
        since=since_filter,
    )
    return {
        "count": len(sessions),
        "total_count": max(total_count, safe_offset + len(sessions)),
        "limit": capped_limit,
        "offset": safe_offset,
        "filters": {
            "status": status_filter,
            "trace_health": trace_health_filter,
            "has_report": has_report,
            "q": search_filter,
            "since": since_filter,
        },
        "sessions": sessions,
    }


@router.delete(
    "/interview-sessions/{session_id}",
    dependencies=[Depends(require_admin_token)],
)
def admin_delete_session(session_id: str) -> dict[str, Any]:
    """Hard-delete a persisted interview session (admin-only).

    Removes DB rows (interview_sessions, generation_traces, interview_outcomes),
    active session handle, and LangGraph checkpoint thread.
    """
    from app.services.privacy_cleanup import delete_session_data
    from app.services.session_manager import get_session_manager

    manager = get_session_manager()
    active_removed = False
    if manager.get(session_id) is not None:
        try:
            manager.cancel(session_id)
        finally:
            manager.remove(session_id)
            active_removed = True

    payload = delete_session_data(session_id)
    payload["deleted"] = bool(payload.get("deleted") or active_removed)

    workflow = getattr(manager, "_workflow", None)
    checkpointer = getattr(workflow, "checkpointer", None)
    delete_thread = getattr(checkpointer, "delete_thread", None)
    if callable(delete_thread):
        try:
            delete_thread(session_id)
            payload["checkpoint_deleted"] = True
        except Exception as e:
            log.warning("admin delete checkpoint thread failed for %s: %s", session_id, e)
            payload["checkpoint_deleted"] = False

    log.info("admin deleted session %s: %s", session_id, payload)
    return payload


_ANCHOR_SOURCE_TYPES = ("resume", "self_intro")
_ANCHOR_CHUNKER_MODES = ("A", "B", "C", "D", "SI")
_ANCHOR_FALLBACK_REASONS = (
    "low_score",
    "timeout",
    "empty",
    "not_ready",
    "skipped",
    "error",
)


@router.get(
    "/session-anchors/summary",
    dependencies=[Depends(require_admin_token)],
)
def session_anchor_summary() -> dict[str, Any]:
    """Summarise session-scoped candidate anchor chunks."""
    from sqlalchemy import distinct, func

    from app.models.session_anchor import SessionAnchorChunk
    from app.services.resume_embedding import current_embedding_model_version

    with get_session() as sess:
        total_chunks = int(sess.query(func.count(SessionAnchorChunk.id)).scalar() or 0)
        total_sessions = int(
            sess.query(func.count(distinct(SessionAnchorChunk.session_id))).scalar() or 0
        )
        source_rows = (
            sess.query(
                SessionAnchorChunk.source_type,
                func.count(SessionAnchorChunk.id),
                func.count(distinct(SessionAnchorChunk.session_id)),
            )
            .group_by(SessionAnchorChunk.source_type)
            .all()
        )
        mode_rows = (
            sess.query(
                SessionAnchorChunk.chunker_mode,
                func.count(SessionAnchorChunk.id),
                func.count(distinct(SessionAnchorChunk.session_id)),
            )
            .group_by(SessionAnchorChunk.chunker_mode)
            .all()
        )
        model_version_rows = (
            sess.query(
                SessionAnchorChunk.embedding_model_version,
                func.count(SessionAnchorChunk.id),
                func.count(distinct(SessionAnchorChunk.session_id)),
            )
            .group_by(SessionAnchorChunk.embedding_model_version)
            .all()
        )
        recent_rows = (
            sess.query(
                SessionAnchorChunk.session_id,
                func.count(SessionAnchorChunk.id),
                func.max(SessionAnchorChunk.created_at),
            )
            .group_by(SessionAnchorChunk.session_id)
            .order_by(func.max(SessionAnchorChunk.created_at).desc())
            .limit(10)
            .all()
        )

    by_source_type = {
        source: {"chunks": 0, "sessions": 0}
        for source in _ANCHOR_SOURCE_TYPES
    }
    for source, chunks, sessions in source_rows:
        key = str(source or "unknown")
        by_source_type[key] = {
            "chunks": int(chunks or 0),
            "sessions": int(sessions or 0),
        }

    by_mode = {
        mode: {"chunks": 0, "sessions": 0, "avg_chunks_per_session": 0.0}
        for mode in _ANCHOR_CHUNKER_MODES
    }
    for mode, chunks, sessions in mode_rows:
        key = str(mode or "unknown")
        chunk_count = int(chunks or 0)
        session_count = int(sessions or 0)
        by_mode[key] = {
            "chunks": chunk_count,
            "sessions": session_count,
            "avg_chunks_per_session": (
                round(chunk_count / session_count, 2) if session_count else 0.0
            ),
        }

    recent_sessions = [
        {
            "session_id": str(session_id),
            "chunks": int(chunks or 0),
            "last_chunk_at": created_at.isoformat() if created_at else None,
        }
        for session_id, chunks, created_at in recent_rows
    ]
    by_embedding_model_version = {
        str(version or "unknown"): {
            "chunks": int(chunks or 0),
            "sessions": int(sessions or 0),
        }
        for version, chunks, sessions in model_version_rows
    }

    return {
        "resume_rag_mode": str(getattr(get_settings(), "resume_rag_mode", "off")),
        "total_chunks": total_chunks,
        "total_sessions": total_sessions,
        "by_source_type": by_source_type,
        "by_mode": by_mode,
        "embedding_model_version": current_embedding_model_version(),
        "by_embedding_model_version": by_embedding_model_version,
        "recent_sessions": recent_sessions,
    }


@router.get(
    "/session-anchors/metrics",
    dependencies=[Depends(require_admin_token)],
)
def session_anchor_metrics(window_hours: int = 24) -> dict[str, Any]:
    """Aggregate session-anchor RAG artifacts from recent ask traces."""
    from app.models.generation_trace import GenerationTrace

    hours = max(1, min(int(window_hours or 24), 24 * 30))
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    with get_session() as sess:
        rows = (
            sess.query(GenerationTrace)
            .filter(GenerationTrace.node == "ask_question")
            .filter(GenerationTrace.created_at >= cutoff)
            .order_by(GenerationTrace.created_at.desc())
            .limit(5000)
            .all()
        )

    source_buckets = {
        source: _new_anchor_metric_bucket()
        for source in _ANCHOR_SOURCE_TYPES
    }
    mode_buckets = {
        mode: _new_anchor_metric_bucket()
        for mode in (*_ANCHOR_CHUNKER_MODES, "unknown")
    }
    status_counts: dict[str, int] = {}

    for row in rows:
        artifact = _candidate_anchor_artifact(row)
        if not artifact:
            continue
        status_value = str(artifact.get("status") or "unknown")
        status_counts[status_value] = status_counts.get(status_value, 0) + 1
        if status_value == "off":
            continue

        fallback = str(artifact.get("fallback_reason") or "").strip()
        latency = _coerce_int(artifact.get("latency_ms"))
        hits = [
            hit for hit in artifact.get("hits") or []
            if isinstance(hit, dict)
        ]
        hit_sources = {
            str(hit.get("source_type") or "unknown") for hit in hits
        }
        hit_modes = {
            _anchor_hit_mode(hit)
            for hit in hits
        }

        for source, bucket in source_buckets.items():
            _record_anchor_retrieval(
                bucket,
                hit=source in hit_sources,
                fallback_reason=fallback,
                latency_ms=latency,
            )

        if hit_modes:
            for mode in hit_modes:
                bucket = mode_buckets.setdefault(mode, _new_anchor_metric_bucket())
                _record_anchor_retrieval(
                    bucket,
                    hit=True,
                    fallback_reason="",
                    latency_ms=latency,
                )
        else:
            _record_anchor_retrieval(
                mode_buckets["unknown"],
                hit=False,
                fallback_reason=fallback,
                latency_ms=latency,
            )

    return {
        "window_hours": hours,
        "by_source_type": {
            key: _finalize_anchor_metric_bucket(bucket)
            for key, bucket in sorted(source_buckets.items())
        },
        "by_mode": {
            key: _finalize_anchor_metric_bucket(bucket)
            for key, bucket in sorted(mode_buckets.items())
        },
        "by_status": status_counts,
    }


@router.get(
    "/session-anchors/sessions",
    dependencies=[Depends(require_admin_token)],
)
def session_anchor_sessions(since: str = Query(default="24h")) -> dict[str, Any]:
    """Return session-level candidate-anchor RAG runtime observability."""
    from app.models.generation_trace import GenerationTrace
    from app.models.interview_session import InterviewSession
    from app.models.session_anchor import SessionAnchorChunk

    if since not in _HISTORY_SINCE_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"since must be one of: {', '.join(_HISTORY_SINCE_HOURS)}",
        )
    hours = _HISTORY_SINCE_HOURS[since]
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    with get_session() as sess:
        sessions = (
            sess.query(InterviewSession)
            .filter(InterviewSession.created_at >= cutoff)
            .order_by(InterviewSession.created_at.desc(), InterviewSession.session_id.asc())
            .all()
        )
        session_ids = [str(row.session_id) for row in sessions]
        chunks = (
            sess.query(SessionAnchorChunk)
            .filter(SessionAnchorChunk.session_id.in_(session_ids))
            .all()
            if session_ids
            else []
        )
        traces = (
            sess.query(GenerationTrace)
            .filter(GenerationTrace.session_id.in_(session_ids))
            .filter(GenerationTrace.node == "ask_question")
            .filter(GenerationTrace.created_at >= cutoff)
            .order_by(GenerationTrace.created_at.asc(), GenerationTrace.id.asc())
            .all()
            if session_ids
            else []
        )

    buckets = {
        session_id: _new_session_anchor_session_bucket()
        for session_id in session_ids
    }
    for chunk in chunks:
        bucket = buckets.get(str(chunk.session_id))
        if bucket is None:
            continue
        source = str(chunk.source_type or "unknown")
        bucket["total_chunks"] += 1
        bucket["chunks_by_source"][source] = bucket["chunks_by_source"].get(source, 0) + 1
        mode = str(chunk.chunker_mode or "").strip()
        if mode:
            bucket["chunker_modes"].add(mode)
        version = str(chunk.embedding_model_version or "").strip()
        if version:
            bucket["embedding_model_versions"].add(version)

    for trace in traces:
        bucket = buckets.get(str(trace.session_id))
        if bucket is None:
            continue
        artifact = _candidate_anchor_artifact(trace)
        if not artifact:
            continue
        trace_created_at = getattr(trace, "created_at", None)
        if trace_created_at is not None:
            previous = bucket.get("last_trace_at")
            if previous is None or trace_created_at > previous:
                bucket["last_trace_at"] = trace_created_at

        status_value = str(artifact.get("status") or "unknown")
        status_counts = bucket["rag_status_distribution"]
        status_counts[status_value] = int(status_counts.get(status_value) or 0) + 1
        if status_value == "off":
            continue

        bucket["retrieval_attempts"] += 1
        latency = _coerce_int(artifact.get("latency_ms"))
        if latency is not None:
            bucket["latencies"].append(latency)
        hits = [hit for hit in artifact.get("hits") or [] if isinstance(hit, dict)]
        bucket["total_hit_items"] += len(hits)
        if hits:
            bucket["hit_count"] += 1
            for hit in hits:
                source = str(hit.get("source_type") or "unknown")
                source_hits = bucket["source_hit_counts"]
                source_hits[source] = int(source_hits.get(source) or 0) + 1
        else:
            bucket["fallback_count"] += 1
            reason = str(artifact.get("fallback_reason") or "empty").strip() or "empty"
            reasons = bucket["fallback_reasons"]
            reasons[reason] = int(reasons.get(reason) or 0) + 1

    rows = [
        _finalize_session_anchor_session_row(session_row, buckets[str(session_row.session_id)])
        for session_row in sessions
    ]
    session_count = len(rows)
    indexed_sessions = sum(1 for row in rows if row["total_chunks"] > 0)
    hit_sessions = sum(1 for row in rows if row["hit_count"] > 0)
    fallback_sessions = sum(1 for row in rows if row["fallback_count"] > 0)
    return {
        "window": since,
        "window_hours": hours,
        "session_count": session_count,
        "summary": {
            "indexed_sessions": indexed_sessions,
            "indexed_session_rate": _rate(indexed_sessions, session_count),
            "hit_sessions": hit_sessions,
            "hit_session_rate": _rate(hit_sessions, session_count),
            "fallback_sessions": fallback_sessions,
            "fallback_session_rate": _rate(fallback_sessions, session_count),
        },
        "sessions": rows,
    }


@router.delete(
    "/sessions/{session_id}/anchor-data",
    dependencies=[Depends(require_admin_token)],
)
def delete_session_anchor_data(session_id: str) -> dict[str, Any]:
    """Delete all session-scoped anchor data and scrub persisted snapshots."""
    from sqlalchemy import delete, select

    from app.models.generation_trace import GenerationTrace
    from app.models.interview_session import InterviewSession
    from app.models.resume_parse_artifact import ResumeParseArtifact
    from app.models.session_anchor import SessionAnchorChunk
    from app.services.resume_anchor_cache import purge_resume_anchor_cache_keys

    with get_session() as sess:
        session_row = sess.get(InterviewSession, session_id)
        artifact_ids = _resume_artifact_ids_from_session(session_row)
        cache_keys = set(
            sess.scalars(
                select(SessionAnchorChunk.source_cache_key).where(
                    SessionAnchorChunk.session_id == session_id,
                    SessionAnchorChunk.source_cache_key.isnot(None),
                )
            ).all()
        )
        chunk_artifact_ids = set(
            sess.scalars(
                select(SessionAnchorChunk.source_artifact_id).where(
                    SessionAnchorChunk.session_id == session_id,
                    SessionAnchorChunk.source_artifact_id.isnot(None),
                )
            ).all()
        )
        artifact_ids.update(str(v) for v in chunk_artifact_ids if v)

        chunks_deleted = int(
            sess.execute(
                delete(SessionAnchorChunk).where(
                    SessionAnchorChunk.session_id == session_id
                )
            ).rowcount
            or 0
        )
        artifacts_deleted = 0
        if artifact_ids:
            artifacts_deleted = int(
                sess.execute(
                    delete(ResumeParseArtifact).where(
                        ResumeParseArtifact.artifact_id.in_(sorted(artifact_ids))
                    )
                ).rowcount
                or 0
            )
        cache_deleted = purge_resume_anchor_cache_keys(
            {str(value) for value in cache_keys if value},
            db_session=sess,
        )

        sessions_scrubbed = 0
        if session_row is not None:
            setup_snapshot, setup_changed = _scrub_anchor_payload(
                session_row.setup_snapshot
            )
            current_question, question_changed = _scrub_anchor_payload(
                session_row.current_question
            )
            if setup_changed:
                session_row.setup_snapshot = setup_snapshot
            if question_changed:
                session_row.current_question = current_question
            if setup_changed or question_changed:
                sessions_scrubbed = 1

        traces_scrubbed = 0
        traces = sess.scalars(
            select(GenerationTrace).where(GenerationTrace.session_id == session_id)
        ).all()
        for trace in traces:
            scrubbed, changed = _scrub_anchor_payload(trace.state_snapshot)
            if changed:
                trace.state_snapshot = scrubbed
                traces_scrubbed += 1

    payload = {
        "session_id": session_id,
        "chunks_deleted": chunks_deleted,
        "resume_artifacts_deleted": artifacts_deleted,
        "resume_artifact_ids": sorted(artifact_ids),
        "resume_anchor_cache_deleted": cache_deleted,
        "resume_anchor_cache_keys": sorted(str(value) for value in cache_keys if value),
        "sessions_scrubbed": sessions_scrubbed,
        "traces_scrubbed": traces_scrubbed,
        "deleted": bool(
            chunks_deleted
            or artifacts_deleted
            or cache_deleted
            or sessions_scrubbed
            or traces_scrubbed
        ),
    }
    log.info("admin deleted session anchor data %s: %s", session_id, payload)
    return payload


def _new_anchor_metric_bucket() -> dict[str, Any]:
    return {
        "total_retrievals": 0,
        "hit_count": 0,
        "fallback_distribution": {
            reason: 0 for reason in _ANCHOR_FALLBACK_REASONS
        },
        "_latencies": [],
    }


def _new_session_anchor_session_bucket() -> dict[str, Any]:
    return {
        "total_chunks": 0,
        "chunks_by_source": {source: 0 for source in _ANCHOR_SOURCE_TYPES},
        "chunker_modes": set(),
        "embedding_model_versions": set(),
        "retrieval_attempts": 0,
        "hit_count": 0,
        "total_hit_items": 0,
        "source_hit_counts": {source: 0 for source in _ANCHOR_SOURCE_TYPES},
        "fallback_count": 0,
        "fallback_reasons": {},
        "latencies": [],
        "rag_status_distribution": {},
        "last_trace_at": None,
    }


def _ordered_anchor_modes(values: set[str]) -> list[str]:
    ordered = [mode for mode in _ANCHOR_CHUNKER_MODES if mode in values]
    extras = sorted(mode for mode in values if mode not in _ANCHOR_CHUNKER_MODES)
    return [*ordered, *extras]


def _clean_count_map(values: dict[str, int]) -> dict[str, int]:
    return {str(key): int(value or 0) for key, value in values.items() if int(value or 0) > 0}


def _finalize_session_anchor_session_row(session_row: Any, bucket: dict[str, Any]) -> dict[str, Any]:
    attempts = int(bucket.get("retrieval_attempts") or 0)
    hit_count = int(bucket.get("hit_count") or 0)
    total_hit_items = int(bucket.get("total_hit_items") or 0)
    latencies = sorted(int(v) for v in bucket.get("latencies") or [] if isinstance(v, int))
    chunks_by_source = _clean_count_map(bucket.get("chunks_by_source") or {})
    source_hit_counts = _clean_count_map(bucket.get("source_hit_counts") or {})
    return {
        "session_id": str(getattr(session_row, "session_id", "") or ""),
        "candidate_name": getattr(session_row, "candidate_name", None),
        "job_title": getattr(session_row, "job_title", None),
        "session_status": str(getattr(session_row, "status", "") or "unknown"),
        "created_at": _iso_or_none(getattr(session_row, "created_at", None)),
        "updated_at": _iso_or_none(getattr(session_row, "updated_at", None)),
        "has_resume_chunks": bool((bucket.get("chunks_by_source") or {}).get("resume")),
        "has_self_intro_chunks": bool((bucket.get("chunks_by_source") or {}).get("self_intro")),
        "total_chunks": int(bucket.get("total_chunks") or 0),
        "chunks_by_source": chunks_by_source,
        "chunker_modes": _ordered_anchor_modes(bucket.get("chunker_modes") or set()),
        "embedding_model_versions": sorted(bucket.get("embedding_model_versions") or []),
        "retrieval_attempts": attempts,
        "hit_count": hit_count,
        "hit_rate": round(hit_count / attempts, 3) if attempts else 0.0,
        "source_hit_counts": source_hit_counts,
        "avg_hits_per_attempt": round(total_hit_items / attempts, 3) if attempts else 0.0,
        "fallback_count": int(bucket.get("fallback_count") or 0),
        "fallback_reasons": _clean_count_map(bucket.get("fallback_reasons") or {}),
        "latency_ms": {
            "p50": _percentile_nearest(latencies, 0.50),
            "p95": _percentile_nearest(latencies, 0.95),
            "p99": _percentile_nearest(latencies, 0.99),
        },
        "rag_status_distribution": _clean_count_map(
            bucket.get("rag_status_distribution") or {}
        ),
        "last_trace_at": _iso_or_none(bucket.get("last_trace_at")),
    }


def _record_anchor_retrieval(
    bucket: dict[str, Any],
    *,
    hit: bool,
    fallback_reason: str,
    latency_ms: int | None,
) -> None:
    bucket["total_retrievals"] = int(bucket.get("total_retrievals") or 0) + 1
    if hit:
        bucket["hit_count"] = int(bucket.get("hit_count") or 0) + 1
    else:
        reason = fallback_reason or "empty"
        fallback = bucket.setdefault("fallback_distribution", {})
        fallback[reason] = int(fallback.get(reason) or 0) + 1
    if latency_ms is not None:
        bucket.setdefault("_latencies", []).append(latency_ms)


def _finalize_anchor_metric_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    total = int(bucket.get("total_retrievals") or 0)
    hits = int(bucket.get("hit_count") or 0)
    latencies = sorted(
        int(v) for v in bucket.get("_latencies") or [] if isinstance(v, int)
    )
    return {
        "total_retrievals": total,
        "hit_count": hits,
        "hit_rate": round(hits / total, 3) if total else 0.0,
        "fallback_distribution": dict(bucket.get("fallback_distribution") or {}),
        "latency_ms": {
            "p50": _percentile_nearest(latencies, 0.50),
            "p99": _percentile_nearest(latencies, 0.99),
        },
    }


def _percentile_nearest(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int(len(values) * percentile + 0.9999) - 1))
    return values[index]


def _candidate_anchor_artifact(row: Any) -> dict[str, Any]:
    snapshot = _as_dict(getattr(row, "state_snapshot", None))
    payload = _as_dict(snapshot.get("payload"))
    selection = _as_dict(payload.get("selection_artifacts"))
    artifact = _as_dict(selection.get("candidate_anchor_rag"))
    if artifact:
        return artifact
    state = _as_dict(snapshot.get("state"))
    question = _as_dict(state.get("current_question"))
    selection = _as_dict(question.get("selection_artifacts"))
    return _as_dict(selection.get("candidate_anchor_rag"))


def _anchor_hit_mode(hit: dict[str, Any]) -> str:
    mode = str(hit.get("chunker_mode") or "").strip()
    if mode:
        return mode
    if str(hit.get("source_type") or "") == "self_intro":
        return "SI"
    return "unknown"


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _resume_artifact_ids_from_session(row: Any) -> set[str]:
    if row is None:
        return set()
    snapshot = _as_dict(getattr(row, "setup_snapshot", None))
    candidate = _as_dict(snapshot.get("candidate"))
    candidates = [
        candidate.get("resume_source_id"),
        _as_dict(candidate.get("resume_vector_status")).get("resume_source_id"),
        _as_dict(snapshot.get("resume_vector_status")).get("resume_source_id"),
    ]
    return {str(value) for value in candidates if value}


_ANCHOR_SCRUB_KEYS = {
    "anchor_cards",
    "candidate_anchor_rag",
    "candidate_anchor_rag_artifact",
    "resume_anchor",
    "resume_parsed",
    "resume_rag_block",
    "resume_source_id",
    "resume_vector_status",
    "source_cache_key",
    "self_intro_profile",
    "self_intro_rag_block",
    "self_intro_vector_status",
}


def _scrub_anchor_payload(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _ANCHOR_SCRUB_KEYS:
                changed = True
                continue
            scrubbed, item_changed = _scrub_anchor_payload(item)
            out[key] = scrubbed
            changed = changed or item_changed
        return out, changed
    if isinstance(value, list):
        changed = False
        items = []
        for item in value:
            scrubbed, item_changed = _scrub_anchor_payload(item)
            items.append(scrubbed)
            changed = changed or item_changed
        return items, changed
    return value, False


@router.get(
    "/interview-sessions/{session_id}/traces",
    dependencies=[Depends(require_admin_token)],
)
def get_interview_session_traces(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Return compact workflow traces for a persisted interview session."""
    if offset == 0:
        return _interview_session_trace_payload(session_id=session_id, limit=limit)
    return _interview_session_trace_payload(
        session_id=session_id,
        limit=limit,
        offset=offset,
    )


_ROLLUP_WINDOWS_HOURS = {"1h": 1, "24h": 24, "7d": 24 * 7, "30d": 24 * 30}
_ROLLUP_GROUPBYS = {"health", "node", "verdict", "fallback"}


@router.get("/trace-rollup", dependencies=[Depends(require_admin_token)])
def trace_rollup(
    since: str = "24h",
    groupby: str = "health",
) -> dict[str, Any]:
    """Aggregate trace coverage across recent interview sessions.

    Powers the admin observability roll-up card: how many sessions
    landed today / this week, sliced by ``trace_health`` (default),
    by ``node`` (which workflow steps fired), or by ``verdict``
    (hire-language outcome distribution). Cached lightly with a
    server-side TTL inside :func:`_compute_trace_rollup` so the
    15-second auto-refresh on the panel does not pound the DB.
    """
    if since not in _ROLLUP_WINDOWS_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported since={since!r}; allowed: {sorted(_ROLLUP_WINDOWS_HOURS)}",
        )
    if groupby not in _ROLLUP_GROUPBYS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported groupby={groupby!r}; allowed: {sorted(_ROLLUP_GROUPBYS)}",
        )
    return _compute_trace_rollup(since=since, groupby=groupby)


def _compute_trace_rollup(*, since: str, groupby: str) -> dict[str, Any]:
    """Run the actual SQL aggregation. Pulled out so tests can patch it."""
    from datetime import UTC, datetime, timedelta

    from app.models import GenerationTrace, InterviewSession, get_session
    from app.services.trace_health import classify_trace_health

    hours = _ROLLUP_WINDOWS_HOURS[since]
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    bucket_counts: dict[str, int] = {}
    total_sessions = 0
    try:
        with get_session() as sess:
            session_rows = (
                sess.query(
                    InterviewSession.session_id,
                    InterviewSession.status,
                    InterviewSession.final_report,
                )
                .filter(InterviewSession.created_at >= cutoff)
                .limit(5000)
                .all()
            )
            session_ids = [row.session_id for row in session_rows]
            total_sessions = len(session_ids)
            if not session_ids:
                return _empty_rollup(since=since, groupby=groupby)
            node_rows = (
                sess.query(
                    GenerationTrace.session_id,
                    GenerationTrace.node,
                )
                .filter(GenerationTrace.session_id.in_(session_ids))
                .all()
            )
    except Exception as e:  # pragma: no cover - DB outages must not 500 the panel
        log.warning("compute_trace_rollup failed: %s", e)
        return _empty_rollup(since=since, groupby=groupby)

    if groupby == "node":
        for _sid, node in node_rows:
            key = str(node or "unknown")
            bucket_counts[key] = bucket_counts.get(key, 0) + 1
    elif groupby == "verdict":
        for row in session_rows:
            report = row.final_report or {}
            verdict = (
                report.get("overall_verdict")
                or report.get("verdict")
                or "unknown"
            )
            key = str(verdict)
            bucket_counts[key] = bucket_counts.get(key, 0) + 1
    elif groupby == "fallback":
        total_turns = 0
        fallback_turns = 0
        affected_sessions = 0
        for row in session_rows:
            report = row.final_report or {}
            session_turns = _non_negative_int(report.get("total_turns"))
            session_fallbacks = min(
                _non_negative_int(report.get("evaluator_fallback_count")),
                session_turns,
            )
            total_turns += session_turns
            fallback_turns += session_fallbacks
            key = "with_fallback" if session_fallbacks > 0 else "clean"
            if session_fallbacks > 0:
                affected_sessions += 1
            bucket_counts[key] = bucket_counts.get(key, 0) + 1
    else:  # groupby == "health"
        per_session: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
        for sid, node in node_rows:
            per_session.setdefault(str(sid), []).append({"node": str(node or "")})
        status_by_id = {row.session_id: row.status for row in session_rows}
        for sid in session_ids:
            health = classify_trace_health(
                per_session.get(sid, []),
                session_status=status_by_id.get(sid),
            )
            bucket_counts[health] = bucket_counts.get(health, 0) + 1

    total_for_share = sum(bucket_counts.values()) or 1
    buckets = [
        {
            "key": key,
            "count": count,
            "share": round(count / total_for_share, 4),
        }
        for key, count in sorted(
            bucket_counts.items(), key=lambda kv: kv[1], reverse=True
        )
    ]
    payload: dict[str, Any] = {
        "since": since,
        "now": datetime.now(UTC).isoformat(),
        "total_sessions": total_sessions,
        "groupby": groupby,
        "buckets": buckets,
    }
    if groupby == "fallback":
        payload.update(
            {
                "affected_sessions": affected_sessions,
                "fallback_turns": fallback_turns,
                "total_turns": total_turns,
                "fallback_rate": round(fallback_turns / total_turns, 4)
                if total_turns
                else 0.0,
            }
        )
    return payload


def _non_negative_int(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(n, 0)


def _empty_rollup(*, since: str, groupby: str) -> dict[str, Any]:
    from datetime import UTC, datetime

    payload: dict[str, Any] = {
        "since": since,
        "now": datetime.now(UTC).isoformat(),
        "total_sessions": 0,
        "groupby": groupby,
        "buckets": [],
    }
    if groupby == "fallback":
        payload.update(
            {
                "affected_sessions": 0,
                "fallback_turns": 0,
                "total_turns": 0,
                "fallback_rate": 0.0,
            }
        )
    return payload


@router.get("/evidence-rollup", dependencies=[Depends(require_admin_token)])
def evidence_rollup(since: str = "24h") -> dict[str, Any]:
    """Aggregate evaluator evidence coverage for recent trace rows."""
    if since not in _ROLLUP_WINDOWS_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported since={since!r}; allowed: {sorted(_ROLLUP_WINDOWS_HOURS)}",
        )
    return _compute_evidence_rollup(since=since)


@router.get("/credibility-rollup", dependencies=[Depends(require_admin_token)])
def credibility_rollup() -> dict[str, Any]:
    """Per-session credibility assessment for recent completed sessions.

    Reads ``final_report`` traces that contain a ``credibility_summary``
    block and returns the distribution of credibility levels plus
    per-session details for the admin dashboard.
    """
    return _compute_credibility_rollup()


def _compute_evidence_rollup(*, since: str) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.models import GenerationTrace, InterviewSession, get_session
    from app.services.scoring_quality import acceptance_evidence_quality

    cutoff = datetime.now(UTC) - timedelta(hours=_ROLLUP_WINDOWS_HOURS[since])
    try:
        with get_session() as sess:
            rows = (
                sess.query(GenerationTrace)
                .join(
                    InterviewSession,
                    GenerationTrace.session_id == InterviewSession.session_id,
                )
                .filter(InterviewSession.created_at >= cutoff)
                .limit(5000)
                .all()
            )
    except Exception as e:  # pragma: no cover - DB outages must not 500 the panel
        log.warning("compute_evidence_rollup failed: %s", e)
        return _empty_evidence_rollup(since=since)

    total_evaluator = 0
    with_acceptance = 0
    with_spans = 0
    fallback_traces = 0
    verification_traces = 0
    verification_triggered = 0
    verification_changed = 0
    total_acceptance_checks = 0
    yes_checks = 0
    unsupported_yes_checks = 0
    evidence_span_total = 0
    evidence_span_none_count = 0
    evidence_quote_total = 0

    for row in rows:
        node = str(getattr(row, "node", "") or "")
        if node == "evaluator":
            total_evaluator += 1
            evaluation = _as_dict(getattr(row, "evaluation", None))
            acceptance = _as_dict(evaluation.get("acceptance_check_results"))
            quality = acceptance_evidence_quality(acceptance)
            total_acceptance_checks += quality["total_acceptance_checks"]
            yes_checks += quality["yes_checks"]
            unsupported_yes_checks += quality["unsupported_yes_checks"]
            evidence_span_total += quality["evidence_span_total"]
            evidence_span_none_count += quality["evidence_span_none_count"]
            evidence_quote_total += quality["evidence_quote_total"]
            if acceptance:
                with_acceptance += 1
            if _has_evidence_spans(acceptance):
                with_spans += 1
            if evaluation.get("source") == "fallback" or evaluation.get("fallback_reason"):
                fallback_traces += 1
        elif node == "verification":
            verification_traces += 1
            payload = _trace_payload(row)
            if payload.get("triggered"):
                verification_triggered += 1
            if payload.get("verdict_changed"):
                verification_changed += 1

    return {
        "since": since,
        "now": datetime.now(UTC).isoformat(),
        "total_evaluator_traces": total_evaluator,
        "with_acceptance_checks": with_acceptance,
        "with_evidence_spans": with_spans,
        "fallback_traces": fallback_traces,
        "acceptance_check_rate": _rate(with_acceptance, total_evaluator),
        "evidence_span_rate": _rate(with_spans, total_evaluator),
        "fallback_rate": _rate(fallback_traces, total_evaluator),
        "total_acceptance_checks": total_acceptance_checks,
        "yes_checks": yes_checks,
        "unsupported_yes_checks": unsupported_yes_checks,
        "unsupported_yes_rate": _rate(unsupported_yes_checks, yes_checks),
        "evidence_span_total": evidence_span_total,
        "evidence_span_none_count": evidence_span_none_count,
        "evidence_span_none_rate": _rate(
            evidence_span_none_count,
            evidence_span_total,
        ),
        "evidence_quote_total": evidence_quote_total,
        "avg_evidence_quotes_per_check": _rate(
            evidence_quote_total,
            total_acceptance_checks,
        ),
        "verification_traces": verification_traces,
        "verification_triggered": verification_triggered,
        "verification_changed": verification_changed,
        "verification_trigger_rate": _rate(
            verification_triggered,
            verification_traces,
        ),
        "verification_change_rate": _rate(
            verification_changed,
            verification_triggered,
        ),
    }


def _compute_credibility_rollup() -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.models import GenerationTrace, get_session
    from app.services.scoring_credibility import compute_credibility

    cutoff = datetime.now(UTC) - timedelta(hours=168)
    try:
        with get_session() as sess:
            rows = (
                sess.query(GenerationTrace)
                .filter(GenerationTrace.node == "final_report")
                .filter(GenerationTrace.created_at >= cutoff)
                .order_by(GenerationTrace.created_at.desc())
                .limit(200)
                .all()
            )
    except Exception as e:  # pragma: no cover
        log.warning("compute_credibility_rollup failed: %s", e)
        return {
            "now": datetime.now(UTC).isoformat(),
            "total_sessions": 0,
            "distribution": {"high": 0, "medium": 0, "low": 0},
            "sessions": [],
        }

    distribution: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    session_details: list[dict[str, Any]] = []

    for row in rows:
        snapshot = _as_dict(getattr(row, "state_snapshot", None))
        payload = _as_dict(snapshot.get("payload"))
        state_payload = _as_dict(snapshot.get("state"))
        report_payload = _as_dict(state_payload.get("final_report"))
        source_payload = (
            payload
            if payload.get("credibility_summary") or payload.get("total_turns")
            else report_payload
        )
        session_id = str(getattr(row, "session_id", "") or "")

        cred = source_payload.get("credibility_summary")
        if isinstance(cred, dict) and "credibility_level" in cred:
            level = str(cred["credibility_level"])
            distribution[level] = distribution.get(level, 0) + 1
            session_details.append({
                "session_id": session_id,
                "credibility_level": level,
                "fallback_rate": cred.get("fallback_rate", 0.0),
                "evidence_span_miss_rate": cred.get("evidence_span_miss_rate", 0.0),
                "contract_no_rate": cred.get("contract_no_rate", 0.0),
            })
            continue

        ev_summary = _as_dict(source_payload.get("evidence_summary"))
        ct_summary = _as_dict(source_payload.get("contract_summary"))
        verification = _as_dict(
            snapshot.get("verification") or source_payload.get("verification")
        )
        total_turns = int(source_payload.get("total_turns", 0) or 0)
        fallback_count = int(
            source_payload.get("evaluator_fallback_count", 0) or 0
        )

        if total_turns <= 0:
            continue

        cred_result = compute_credibility(
            total_turns=total_turns,
            evaluator_fallback_count=fallback_count,
            evidence_summary=ev_summary,
            contract_summary=ct_summary,
            verification=verification,
        )
        level = cred_result["credibility_level"]
        distribution[level] = distribution.get(level, 0) + 1
        session_details.append({
            "session_id": session_id,
            "credibility_level": level,
            "fallback_rate": cred_result["fallback_rate"],
            "evidence_span_miss_rate": cred_result["evidence_span_miss_rate"],
            "contract_no_rate": cred_result["contract_no_rate"],
        })

    return {
        "now": datetime.now(UTC).isoformat(),
        "total_sessions": len(session_details),
        "distribution": distribution,
        "sessions": session_details[:50],
    }


def _empty_evidence_rollup(*, since: str) -> dict[str, Any]:
    from datetime import UTC, datetime

    return {
        "since": since,
        "now": datetime.now(UTC).isoformat(),
        "total_evaluator_traces": 0,
        "with_acceptance_checks": 0,
        "with_evidence_spans": 0,
        "fallback_traces": 0,
        "acceptance_check_rate": 0.0,
        "evidence_span_rate": 0.0,
        "fallback_rate": 0.0,
        "total_acceptance_checks": 0,
        "yes_checks": 0,
        "unsupported_yes_checks": 0,
        "unsupported_yes_rate": 0.0,
        "evidence_span_total": 0,
        "evidence_span_none_count": 0,
        "evidence_span_none_rate": 0.0,
        "evidence_quote_total": 0,
        "avg_evidence_quotes_per_check": 0.0,
        "verification_traces": 0,
        "verification_triggered": 0,
        "verification_changed": 0,
        "verification_trigger_rate": 0.0,
        "verification_change_rate": 0.0,
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _trace_payload(row: Any) -> dict[str, Any]:
    snapshot = _as_dict(getattr(row, "state_snapshot", None))
    return _as_dict(snapshot.get("payload"))


def _has_evidence_spans(acceptance: dict[str, Any]) -> bool:
    for check in acceptance.values():
        item = _as_dict(check)
        spans = item.get("evidence_spans")
        if isinstance(spans, list) and len(spans) > 0:
            return True
    return False


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


@router.get("/question-quality-rollup", dependencies=[Depends(require_admin_token)])
def question_quality_rollup(since: str = "24h") -> dict[str, Any]:
    """Aggregate question-generation grounding signals for recent traces."""
    if since not in _ROLLUP_WINDOWS_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported since={since!r}; allowed: {sorted(_ROLLUP_WINDOWS_HOURS)}",
        )
    return _compute_question_quality_rollup(since=since)


def _compute_question_quality_rollup(*, since: str) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.models import GenerationTrace, InterviewSession, get_session

    cutoff = datetime.now(UTC) - timedelta(hours=_ROLLUP_WINDOWS_HOURS[since])
    try:
        with get_session() as sess:
            rows = (
                sess.query(GenerationTrace)
                .join(
                    InterviewSession,
                    GenerationTrace.session_id == InterviewSession.session_id,
                )
                .filter(InterviewSession.created_at >= cutoff)
                .limit(5000)
                .all()
            )
    except Exception as e:  # pragma: no cover - DB outages must not 500 the panel
        log.warning("compute_question_quality_rollup failed: %s", e)
        return _empty_question_quality_rollup(since=since)

    total = 0
    with_contract = 0
    evaluator_signed = 0
    with_retrieval = 0
    with_target_skills = 0
    with_skill_focus = 0
    deep_probe = 0
    acceptance_check_total = 0

    for row in rows:
        if str(getattr(row, "node", "") or "") != "ask_question":
            continue
        total += 1
        payload = _trace_payload(row)
        snapshot = _as_dict(getattr(row, "state_snapshot", None))
        state = _as_dict(snapshot.get("state"))
        acceptance_count = _non_negative_int(
            payload.get("contract_acceptance_check_count")
        )
        acceptance_check_total += acceptance_count
        if acceptance_count > 0:
            with_contract += 1
        signed_by = payload.get("signed_by")
        if isinstance(signed_by, list) and "evaluator" in signed_by:
            evaluator_signed += 1
        if str(state.get("retrieval_block") or "").strip():
            with_retrieval += 1
        if isinstance(payload.get("target_skills"), list) and payload.get("target_skills"):
            with_target_skills += 1
        if _as_dict(payload.get("skill_focus")):
            with_skill_focus += 1
        if payload.get("plan_template") == "deep_probe":
            deep_probe += 1

    return {
        "since": since,
        "now": datetime.now(UTC).isoformat(),
        "total_ask_question_traces": total,
        "with_acceptance_contract": with_contract,
        "with_evaluator_signed_contract": evaluator_signed,
        "with_retrieval_context": with_retrieval,
        "with_target_skills": with_target_skills,
        "with_skill_focus": with_skill_focus,
        "deep_probe_questions": deep_probe,
        "contract_rate": _rate(with_contract, total),
        "evaluator_signed_rate": _rate(evaluator_signed, total),
        "retrieval_grounding_rate": _rate(with_retrieval, total),
        "target_skill_rate": _rate(with_target_skills, total),
        "skill_focus_rate": _rate(with_skill_focus, total),
        "deep_probe_rate": _rate(deep_probe, total),
        "avg_acceptance_checks": round(acceptance_check_total / total, 4)
        if total
        else 0.0,
    }


def _empty_question_quality_rollup(*, since: str) -> dict[str, Any]:
    from datetime import UTC, datetime

    return {
        "since": since,
        "now": datetime.now(UTC).isoformat(),
        "total_ask_question_traces": 0,
        "with_acceptance_contract": 0,
        "with_evaluator_signed_contract": 0,
        "with_retrieval_context": 0,
        "with_target_skills": 0,
        "with_skill_focus": 0,
        "deep_probe_questions": 0,
        "contract_rate": 0.0,
        "evaluator_signed_rate": 0.0,
        "retrieval_grounding_rate": 0.0,
        "target_skill_rate": 0.0,
        "skill_focus_rate": 0.0,
        "deep_probe_rate": 0.0,
        "avg_acceptance_checks": 0.0,
    }


_RECENT_TRACES_NODES = {
    "evaluator",
    "director_sample",
    "verification",
    "reward_update",
    "route_decision",
    "final_report",
    "ask_question",
    "compress_context",
    "refine_followup",
    "training_plan",
    "experience_extractor",
    "resume_parse",
}


@router.get("/recent-traces", dependencies=[Depends(require_admin_token)])
def recent_traces(node: str = "evaluator", limit: int = 50) -> dict[str, Any]:
    """Return the most recent ``generation_traces`` rows for a node.

    Powers the reverse-lookup card on the admin panel: instead of
    pivoting through a session, the operator can ask "show me the
    last 50 evaluator runs across all interviews" and click through
    to the offending Trace Explorer view. The route filters on
    ``node`` (whitelisted to known workflow steps) and orders by
    ``created_at`` descending so the freshest events lead.
    """
    if node not in _RECENT_TRACES_NODES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported node={node!r}; allowed: {sorted(_RECENT_TRACES_NODES)}",
        )
    capped_limit = max(1, min(int(limit or 50), 200))
    try:
        from app.models import GenerationTrace, get_session

        with get_session() as sess:
            rows = (
                sess.query(GenerationTrace)
                .filter(GenerationTrace.node == node)
                .order_by(GenerationTrace.created_at.desc())
                .limit(capped_limit)
                .all()
            )
    except Exception as e:  # pragma: no cover
        log.warning("recent_traces query failed: %s", e)
        return {"node": node, "limit": capped_limit, "items": []}

    items: list[dict[str, Any]] = []
    for trace in rows:
        items.append(
            {
                "id": trace.id,
                "session_id": trace.session_id,
                "node": trace.node,
                "dimension": trace.dimension,
                "turn_idx": trace.turn_idx,
                "score": trace.score,
                "passed": trace.passed,
                "immediate_reward": trace.immediate_reward,
                "action_id": trace.action_id,
                "context_key": trace.context_key,
                "langsmith_run_id": trace.langsmith_run_id,
                "created_at": trace.created_at.isoformat() if trace.created_at else None,
            }
        )
    return {"node": node, "limit": capped_limit, "items": items}


@router.get("/metrics", dependencies=[Depends(require_admin_token)])
def metrics() -> Response:
    """Return Prometheus text exposition for operators."""
    from app.core.metrics import metrics_content_type, metrics_text

    return Response(content=metrics_text(), media_type=metrics_content_type())


@router.get("/tracer/health", dependencies=[Depends(require_admin_token)])
def tracer_health() -> dict[str, Any]:
    """Return a compact JSON snapshot of local trace write health."""
    from app.core.metrics import tracer_health_snapshot

    return tracer_health_snapshot()


@router.get("/fallback-rates", dependencies=[Depends(require_admin_token)])
def fallback_rates() -> dict[str, Any]:
    """Return per-kind question/evaluator fallback counters.

    Counts accumulate from process start. ``kind`` is one of
    ``language`` / ``duplicate`` / ``safety`` /
    ``contract_unsigned`` / ``evaluator_fallback``. Use Prometheus
    (``/admin/metrics``) for long-horizon rates; this endpoint is
    the in-process companion that lets the admin dashboard render
    a live counter snapshot without scraping.
    """
    from app.core.metrics import question_fallbacks_snapshot

    return {"fallback_counts": question_fallbacks_snapshot()}


@router.get("/security/summary", dependencies=[Depends(require_admin_token)])
def security_summary() -> dict[str, Any]:
    """Return lightweight counters for security and privacy hardening paths."""
    from app.core.metrics import security_metrics_snapshot

    return security_metrics_snapshot()


def _question_seed_payload(row: Any, *, variant_count: int | None = None) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "version": row.version,
        "title": row.title,
        "dimension": row.dimension,
        "job_levels": list(row.job_levels or []),
        "skill_tags": list(row.skill_tags or []),
        "direction_tags": list(getattr(row, "direction_tags", []) or []),
        "role_tags": list(getattr(row, "role_tags", []) or []),
        "rubric": row.rubric or {},
        "priority": row.priority,
        "status": row.status,
        "source": row.source,
        "scope": row.scope,
        "org_id": row.org_id,
        "job_template_id": row.job_template_id,
        "language": row.language,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if variant_count is not None:
        payload["variant_count"] = variant_count
    return payload


def _question_variant_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "seed_id": row.seed_id,
        "version": row.version,
        "intent": row.intent,
        "difficulty": row.difficulty,
        "scenario_brief": row.scenario_brief,
        "question_stem": row.question_stem,
        "prompt_template": row.prompt_template,
        "scenario_skill_tags": list(row.scenario_skill_tags or []),
        "resume_anchor_hints": list(row.resume_anchor_hints or []),
        "failure_categories": list(row.failure_categories or []),
        "rubric_additions": list(row.rubric_additions or []),
        "expected_signals": list(row.expected_signals or []),
        "anti_patterns": list(row.anti_patterns or []),
        "good_answer_hints": list(row.good_answer_hints or []),
        "role_tags": list(getattr(row, "role_tags", []) or []),
        "priority": row.priority,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _question_usage_payload(
    row: Any,
    *,
    seed: Any | None = None,
    variant: Any | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "turn_idx": row.turn_idx,
        "trace_id": row.trace_id,
        "seed_id": row.seed_id,
        "variant_id": row.variant_id,
        "seed_version": row.seed_version,
        "variant_version": row.variant_version,
        "rank": row.rank,
        "match_score": row.match_score,
        "match_reasons": list(row.match_reasons or []),
        "injected": row.injected,
        "question_selector_mode": row.question_selector_mode,
        "direction_tags": list(getattr(seed, "direction_tags", []) or []),
        "role_tags": list(
            getattr(variant, "role_tags", []) or getattr(seed, "role_tags", []) or []
        ),
        "score": row.score,
        "passed": row.passed,
        "immediate_reward": row.immediate_reward,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _question_rerank_usage_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "turn_idx": row.turn_idx,
        "trace_id": row.trace_id,
        "dimension": row.dimension,
        "probe_intent": row.probe_intent,
        "question_selector_mode": row.question_selector_mode,
        "rule_top_seed_id": row.rule_top_seed_id,
        "rule_top_variant_id": row.rule_top_variant_id,
        "llm_top_seed_id": row.llm_top_seed_id,
        "llm_top_variant_id": row.llm_top_variant_id,
        "candidate_variant_ids": list(row.candidate_variant_ids or []),
        "ranked_variant_ids": list(row.ranked_variant_ids or []),
        "fit_scores": row.fit_scores or {},
        "anchor_choice": row.anchor_choice,
        "reasons": list(row.reasons or []),
        "confidence": row.confidence,
        "model": row.model,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _question_review_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "turn_idx": row.turn_idx,
        "trace_id": row.trace_id,
        "question_rerank_usage_id": row.question_rerank_usage_id,
        "rule_variant_id": row.rule_variant_id,
        "llm_variant_id": row.llm_variant_id,
        "winner": row.winner,
        "reasons": list(row.reasons or []),
        "notes": row.notes,
        "reviewer": row.reviewer,
        "context_summary": row.context_summary or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _skill_playbook_payload(row: Any, *, include_body: bool = False) -> dict[str, Any]:
    body_markdown = str(row.body_markdown or "")
    preview = re.sub(r"\s+", " ", body_markdown).strip()[:240]
    payload = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "tags": {
            "direction_tags": list(row.direction_tags or []),
            "role_tags": list(row.role_tags or []),
            "probe_intents": list(row.probe_intents or []),
            "failure_categories": list(row.failure_categories or []),
        },
        "direction_tags": list(row.direction_tags or []),
        "role_tags": list(row.role_tags or []),
        "dimensions": list(row.dimensions or []),
        "job_levels": list(row.job_levels or []),
        "probe_intents": list(row.probe_intents or []),
        "failure_categories": list(row.failure_categories or []),
        "generator_moves": list(row.generator_moves or []),
        "watch_for": list(row.watch_for or []),
        "avoid": list(row.avoid or []),
        "evaluator_rubric_hints": list(row.evaluator_rubric_hints or []),
        "positive_signals": list(row.positive_signals or []),
        "negative_signals": list(row.negative_signals or []),
        "score_bias_rules": list(row.score_bias_rules or []),
        "evaluator_visibility": bool(row.evaluator_visibility),
        "source": row.source,
        "version": row.version,
        "content_hash": row.content_hash,
        "body_preview": preview,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_body:
        payload["body_markdown"] = body_markdown
    return payload


@router.get("/skill-playbooks", dependencies=[Depends(require_admin_token)])
def list_skill_playbooks(
    status: str | None = None,
    direction_tag: str | None = None,
    role_tag: str | None = None,
    dimension: str | None = None,
) -> dict[str, Any]:
    from app.models.skill_playbook import SkillPlaybookCard

    status_filter = _slug_filter(status)
    direction_filter = _slug_filter(direction_tag)
    role_filter = _slug_filter(role_tag)
    dimension_filter = _slug_filter(dimension)

    with get_session() as sess:
        rows = (
            sess.query(SkillPlaybookCard)
            .order_by(
                SkillPlaybookCard.status.asc(),
                SkillPlaybookCard.priority.desc(),
                SkillPlaybookCard.id.asc(),
            )
            .all()
        )

    filtered = []
    for row in rows:
        if status_filter and _slug_filter(row.status) != status_filter:
            continue
        if direction_filter and direction_filter not in set(row.direction_tags or []):
            continue
        if role_filter and role_filter not in set(row.role_tags or []):
            continue
        if dimension_filter and dimension_filter not in set(row.dimensions or []):
            continue
        filtered.append(row)

    status_counts: dict[str, int] = {}
    for row in filtered:
        status_key = str(row.status or "")
        status_counts[status_key] = status_counts.get(status_key, 0) + 1

    settings = get_settings()
    return {
        "runtime_backend": getattr(
            settings,
            "skill_playbook_backend",
            "db_with_file_fallback",
        ),
        "count": len(filtered),
        "active_count": sum(1 for row in filtered if row.status == "active"),
        "status_counts": status_counts,
        "skill_playbooks": [_skill_playbook_payload(row) for row in filtered],
    }


@router.post("/skill-playbooks/import", dependencies=[Depends(require_admin_token)])
def import_skill_playbooks(archive_missing: bool = False) -> dict[str, int]:
    from app.services.skill_playbook_import import (
        SkillPlaybookImportError,
        import_skill_playbook_dir,
    )

    skill_dir = Path(get_settings().knowledge_dir) / "skills"
    try:
        with get_session() as sess:
            result = import_skill_playbook_dir(
                skill_dir,
                session=sess,
                archive_missing=archive_missing,
            )
    except SkillPlaybookImportError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc
    return {
        "imported": result.imported,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "archived": result.archived,
        "skipped": result.skipped,
    }


@router.get("/skill-playbooks/{card_id}", dependencies=[Depends(require_admin_token)])
def get_skill_playbook(card_id: str) -> dict[str, Any]:
    from app.models.skill_playbook import SkillPlaybookCard

    with get_session() as sess:
        row = sess.get(SkillPlaybookCard, card_id)
        if row is None:
            raise HTTPException(status_code=404, detail="skill playbook not found")
        payload = _skill_playbook_payload(row, include_body=True)
    return {"skill_playbook": payload}


@router.get("/question-seeds", dependencies=[Depends(require_admin_token)])
def list_question_seeds(
    direction_tag: str | None = None,
    role_tag: str | None = None,
) -> dict[str, Any]:
    from app.models.question_bank import QuestionSeed, QuestionVariant

    with get_session() as sess:
        seeds = (
            sess.query(QuestionSeed)
            .order_by(
                QuestionSeed.dimension.asc(),
                QuestionSeed.status.asc(),
                QuestionSeed.priority.desc(),
                QuestionSeed.id.asc(),
            )
            .all()
        )
        variants = sess.query(QuestionVariant.seed_id).all()
    direction_filter = _slug_filter(direction_tag)
    role_filter = _slug_filter(role_tag)
    if direction_filter:
        seeds = [
            seed
            for seed in seeds
            if direction_filter in set(getattr(seed, "direction_tags", []) or [])
        ]
    if role_filter:
        seeds = [
            seed
            for seed in seeds
            if role_filter in set(getattr(seed, "role_tags", []) or [])
        ]
    counts: dict[str, int] = {}
    for (seed_id,) in variants:
        counts[seed_id] = counts.get(seed_id, 0) + 1
    return {
        "count": len(seeds),
        "question_seeds": [
            _question_seed_payload(row, variant_count=counts.get(row.id, 0))
            for row in seeds
        ],
    }


@router.post("/question-seeds/import", dependencies=[Depends(require_admin_token)])
def import_question_seeds(archive_missing: bool = False) -> dict[str, int]:
    from app.services.question_seed_import import (
        QuestionSeedImportError,
        import_question_seed_dir,
    )

    seed_dir = Path(get_settings().knowledge_dir) / "question_seeds"
    try:
        with get_session() as sess:
            result = import_question_seed_dir(
                seed_dir,
                session=sess,
                archive_missing=archive_missing,
            )
    except QuestionSeedImportError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc
    return {
        "imported_seeds": result.imported_seeds,
        "updated_seeds": result.updated_seeds,
        "unchanged_seeds": result.unchanged_seeds,
        "imported_variants": result.imported_variants,
        "updated_variants": result.updated_variants,
        "unchanged_variants": result.unchanged_variants,
        "archived_seeds": result.archived_seeds,
        "archived_variants": result.archived_variants,
    }


@router.post("/question-seeds/lint", dependencies=[Depends(require_admin_token)])
def lint_question_seeds(strict_quality: bool = False) -> dict[str, Any]:
    from app.services.question_seed_lint import lint_question_seed_dir

    seed_dir = Path(get_settings().knowledge_dir) / "question_seeds"
    result = lint_question_seed_dir(seed_dir, strict=bool(strict_quality))
    return result.as_dict()


@router.get("/question-seeds/{seed_id}", dependencies=[Depends(require_admin_token)])
def get_question_seed(seed_id: str) -> dict[str, Any]:
    from app.models.question_bank import QuestionSeed, QuestionVariant

    with get_session() as sess:
        seed = sess.get(QuestionSeed, seed_id)
        if seed is None:
            raise HTTPException(status_code=404, detail="question seed not found")
        variants = (
            sess.query(QuestionVariant)
            .filter(QuestionVariant.seed_id == seed_id)
            .order_by(
                QuestionVariant.status.asc(),
                QuestionVariant.priority.desc(),
                QuestionVariant.id.asc(),
            )
            .all()
        )
    return {
        "seed": _question_seed_payload(seed, variant_count=len(variants)),
        "variants": [_question_variant_payload(row) for row in variants],
    }


@router.get("/question-usages", dependencies=[Depends(require_admin_token)])
def list_question_usages(
    limit: int = 100,
    direction_tag: str | None = None,
    role_tag: str | None = None,
) -> dict[str, Any]:
    from app.models.question_bank import QuestionSeed, QuestionUsage, QuestionVariant

    capped_limit = max(1, min(int(limit or 100), 500))
    direction_filter = _slug_filter(direction_tag)
    role_filter = _slug_filter(role_tag)
    query_limit = 500 if (direction_filter or role_filter) else capped_limit
    with get_session() as sess:
        rows = (
            sess.query(QuestionUsage)
            .order_by(QuestionUsage.created_at.desc())
            .limit(query_limit)
            .all()
        )
        seed_ids = {row.seed_id for row in rows}
        variant_ids = {row.variant_id for row in rows}
        seeds = {
            row.id: row
            for row in sess.query(QuestionSeed).filter(QuestionSeed.id.in_(seed_ids)).all()
        } if seed_ids else {}
        variants = {
            row.id: row
            for row in sess.query(QuestionVariant).filter(QuestionVariant.id.in_(variant_ids)).all()
        } if variant_ids else {}
    payloads = []
    for row in rows:
        seed = seeds.get(row.seed_id)
        variant = variants.get(row.variant_id)
        payload = _question_usage_payload(row, seed=seed, variant=variant)
        if direction_filter and direction_filter not in set(payload["direction_tags"]):
            continue
        if role_filter and role_filter not in set(payload["role_tags"]):
            continue
        payloads.append(payload)
        if len(payloads) >= capped_limit:
            break
    return {
        "count": len(payloads),
        "usages": payloads,
    }


@router.get("/question-rerank-usages", dependencies=[Depends(require_admin_token)])
def list_question_rerank_usages(limit: int = 100) -> dict[str, Any]:
    from app.models.question_bank import QuestionRerankUsage

    capped_limit = max(1, min(int(limit or 100), 500))
    with get_session() as sess:
        rows = (
            sess.query(QuestionRerankUsage)
            .order_by(QuestionRerankUsage.created_at.desc())
            .limit(capped_limit)
            .all()
        )
    return {
        "count": len(rows),
        "rerank_usages": [_question_rerank_usage_payload(row) for row in rows],
    }


@router.get("/question-reviews", dependencies=[Depends(require_admin_token)])
def list_question_reviews(limit: int = 100) -> dict[str, Any]:
    from app.models.question_bank import QuestionReview

    capped_limit = max(1, min(int(limit or 100), 500))
    with get_session() as sess:
        rows = (
            sess.query(QuestionReview)
            .order_by(QuestionReview.created_at.desc())
            .limit(capped_limit)
            .all()
        )
    return {
        "count": len(rows),
        "reviews": [_question_review_payload(row) for row in rows],
    }


@router.post("/question-reviews", dependencies=[Depends(require_admin_token)])
def create_question_review(payload: dict[str, Any]) -> dict[str, Any]:
    from app.models.question_bank import QuestionReview

    winner = str(payload.get("winner") or "").strip().lower()
    if winner not in {"rule", "llm", "tie", "neither"}:
        raise HTTPException(status_code=422, detail="winner must be rule|llm|tie|neither")
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    turn_idx = int(payload.get("turn_idx") or 0)
    review_id = str(payload.get("id") or "").strip() or _question_review_id(
        session_id=session_id,
        turn_idx=turn_idx,
        rule_variant_id=str(payload.get("rule_variant_id") or ""),
        llm_variant_id=str(payload.get("llm_variant_id") or ""),
        winner=winner,
    )
    values = {
        "id": review_id,
        "session_id": session_id,
        "turn_idx": turn_idx,
        "trace_id": _optional_str(payload.get("trace_id")),
        "question_rerank_usage_id": _optional_str(payload.get("question_rerank_usage_id")),
        "rule_variant_id": _optional_str(payload.get("rule_variant_id")),
        "llm_variant_id": _optional_str(payload.get("llm_variant_id")),
        "winner": winner,
        "reasons": _list_of_str(payload.get("reasons")),
        "notes": str(payload.get("notes") or "").strip()[:4000],
        "reviewer": str(payload.get("reviewer") or "admin").strip()[:96] or "admin",
        "context_summary": payload.get("context_summary")
        if isinstance(payload.get("context_summary"), dict)
        else {},
    }
    with get_session() as sess:
        row = sess.get(QuestionReview, review_id)
        if row is None:
            row = QuestionReview(**values)
            sess.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        sess.flush()
        response = _question_review_payload(row)
    return {"review": response}


def _question_review_id(
    *,
    session_id: str,
    turn_idx: int,
    rule_variant_id: str,
    llm_variant_id: str,
    winner: str,
) -> str:
    material = f"{session_id}|{turn_idx}|{rule_variant_id}|{llm_variant_id}|{winner}"
    digest = hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"question-review:{digest[:32]}"


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def _slug_filter(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _set_question_seed_status(seed_id: str, status_value: str) -> dict[str, str]:
    from app.models.question_bank import QuestionSeed

    with get_session() as sess:
        row = sess.get(QuestionSeed, seed_id)
        if row is None:
            raise HTTPException(status_code=404, detail="question seed not found")
        row.status = status_value
    return {"id": seed_id, "status": status_value}


def _set_question_variant_status(variant_id: str, status_value: str) -> dict[str, str]:
    from app.models.question_bank import QuestionVariant

    with get_session() as sess:
        row = sess.get(QuestionVariant, variant_id)
        if row is None:
            raise HTTPException(status_code=404, detail="question variant not found")
        row.status = status_value
    return {"id": variant_id, "status": status_value}


@router.post(
    "/question-seeds/{seed_id}/disable",
    dependencies=[Depends(require_admin_token)],
)
def disable_question_seed(seed_id: str) -> dict[str, str]:
    return _set_question_seed_status(seed_id, "disabled")


@router.post(
    "/question-seeds/{seed_id}/archive",
    dependencies=[Depends(require_admin_token)],
)
def archive_question_seed(seed_id: str) -> dict[str, str]:
    return _set_question_seed_status(seed_id, "archived")


@router.post(
    "/question-variants/{variant_id}/disable",
    dependencies=[Depends(require_admin_token)],
)
def disable_question_variant(variant_id: str) -> dict[str, str]:
    return _set_question_variant_status(variant_id, "disabled")


@router.post(
    "/question-variants/{variant_id}/archive",
    dependencies=[Depends(require_admin_token)],
)
def archive_question_variant(variant_id: str) -> dict[str, str]:
    return _set_question_variant_status(variant_id, "archived")


@router.get("/checkpoint/health", dependencies=[Depends(require_admin_token)])
def checkpoint_health() -> dict[str, Any]:
    """Return checkpoint write-latency aggregates per ``(backend, operation)``.

    Powers the operator dashboard for P3 #2 (checkpoint write latency
    observability). The Histogram is the authoritative source for
    Prometheus / Grafana; this endpoint is the in-process companion
    that lets a small admin UI render p50 / p95 / p99 / failure counts
    without scraping. Empty dict means no checkpoint write has been
    observed since the process started or since the last reset.
    """
    from app.core.metrics import checkpoint_write_snapshot

    return {"checkpoint_writes": checkpoint_write_snapshot()}


@router.get("/strategies", dependencies=[Depends(require_admin_token)])
def list_strategies_route() -> dict[str, Any]:
    """Return strategy memory entries across all admin-visible statuses."""
    from app.models.strategy_memory import StrategyMemory

    with get_session() as sess:
        entries = (
            sess.query(StrategyMemory)
            .order_by(StrategyMemory.status.asc(), StrategyMemory.slug.asc())
            .all()
        )
    return {
        "count": len(entries),
        "strategies": [
            {
                "id": row.id,
                "slug": row.slug,
                "memory_key": row.memory_key,
                "path": f"{row.slug}.md",
                "name": row.name,
                "dimensions": list(row.dimensions or []),
                "job_levels": list(row.job_levels or []),
                "description": (row.description or "")[:200],
                "source": row.source,
                "status": row.status,
                "quality_reason": row.quality_reason,
                "promotion_stage": row.promotion_stage,
                "confidence": row.confidence,
                "support_count": row.support_count,
            }
            for row in entries
        ],
    }


def _set_strategy_status(strategy_id: str, status_value: str) -> dict[str, str]:
    from app.models.strategy_memory import StrategyMemory

    with get_session() as sess:
        row = sess.get(StrategyMemory, strategy_id)
        if row is None:
            raise HTTPException(status_code=404, detail="strategy not found")
        row.status = status_value
    return {"id": strategy_id, "status": status_value}


@router.post("/strategies/{strategy_id}/disable", dependencies=[Depends(require_admin_token)])
def disable_strategy(strategy_id: str) -> dict[str, str]:
    return _set_strategy_status(strategy_id, "disabled")


@router.post("/strategies/{strategy_id}/archive", dependencies=[Depends(require_admin_token)])
def archive_strategy(strategy_id: str) -> dict[str, str]:
    return _set_strategy_status(strategy_id, "archived")


@router.get("/strategy-signals", dependencies=[Depends(require_admin_token)])
def list_strategy_signals(limit: int = 100) -> dict[str, Any]:
    from app.models.strategy_memory import StrategySignal

    capped_limit = max(1, min(int(limit or 100), 500))
    with get_session() as sess:
        rows = (
            sess.query(StrategySignal)
            .order_by(StrategySignal.created_at.desc())
            .limit(capped_limit)
            .all()
        )
    return {
        "count": len(rows),
        "signals": [
            {
                "id": row.id,
                "signal_key": row.signal_key,
                "group_key": row.group_key,
                "session_id": row.session_id,
                "turn_idx": row.turn_idx,
                "dimension": row.dimension,
                "job_level": row.job_level,
                "action_id": row.action_id,
                "plan_template": row.plan_template,
                "probe_intent": row.probe_intent,
                "failure_categories": row.failure_categories or [],
                "score_after": row.score_after,
                "score_delta": row.score_delta,
                "immediate_reward": row.immediate_reward,
                "verifier_overruled": row.verifier_overruled,
                "signal_type": row.signal_type,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.get("/strategy-usages", dependencies=[Depends(require_admin_token)])
def list_strategy_usages(limit: int = 100) -> dict[str, Any]:
    from app.models.strategy_memory import StrategyMemoryUsage

    capped_limit = max(1, min(int(limit or 100), 500))
    with get_session() as sess:
        rows = (
            sess.query(StrategyMemoryUsage)
            .order_by(StrategyMemoryUsage.created_at.desc())
            .limit(capped_limit)
            .all()
        )
    return {
        "count": len(rows),
        "usages": [
            {
                "id": row.id,
                "strategy_id": row.strategy_id,
                "session_id": row.session_id,
                "turn_idx": row.turn_idx,
                "trace_id": row.trace_id,
                "context_key": row.context_key,
                "action_id": row.action_id,
                "plan_template": row.plan_template,
                "score": row.score,
                "passed": row.passed,
                "immediate_reward": row.immediate_reward,
                "delayed_reward": row.delayed_reward,
                "verifier_overruled": row.verifier_overruled,
                "helpful_score": row.helpful_score,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.get("/strategy-stats", dependencies=[Depends(require_admin_token)])
def list_strategy_stats(limit: int = 100) -> dict[str, Any]:
    from app.models.strategy_memory import StrategyMemoryStats

    capped_limit = max(1, min(int(limit or 100), 500))
    with get_session() as sess:
        rows = (
            sess.query(StrategyMemoryStats)
            .order_by(
                StrategyMemoryStats.strategy_id.asc(),
                StrategyMemoryStats.context_key.asc(),
            )
            .limit(capped_limit)
            .all()
        )
    return {
        "count": len(rows),
        "stats": [
            {
                "id": row.id,
                "strategy_id": row.strategy_id,
                "context_key": row.context_key,
                "uses": row.uses,
                "avg_score": row.avg_score,
                "pass_rate": row.pass_rate,
                "avg_immediate_reward": row.avg_immediate_reward,
                "avg_delayed_reward": row.avg_delayed_reward,
                "avg_blended_reward": row.avg_blended_reward,
                "overrule_rate": row.overrule_rate,
                "helpful_avg": row.helpful_avg,
                "last_used_at": row.last_used_at.isoformat()
                if row.last_used_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
    }


@router.post("/strategy-stats/refresh", dependencies=[Depends(require_admin_token)])
def refresh_strategy_stats() -> dict[str, int]:
    from app.services.strategy_memory_stats import refresh_strategy_memory_stats

    with get_session() as sess:
        result = refresh_strategy_memory_stats(session=sess)
    return {"refreshed": result.refreshed, "deleted": result.deleted}


@router.post("/strategy-promotion/run", dependencies=[Depends(require_admin_token)])
def run_strategy_promotion() -> dict[str, int]:
    from app.tasks.strategy_promotion_tasks import run_strategy_promotion_now

    return run_strategy_promotion_now()


@router.get(
    "/failure-category-stats",
    dependencies=[Depends(require_admin_token)],
)
def failure_category_overlap(limit: int = 200) -> dict[str, int]:
    """LLM-output vs keyword-inferred ``failure_categories`` overlap.

    Observation surface for PR6: scans the most recent ``limit``
    evaluator traces and returns four mutually exclusive counters
    (``llm_only`` / ``normalize_only`` / ``both`` / ``neither``) plus
    the sample size that fed the comparison. Used to decide whether to
    retire the keyword normalizer in P1.
    """
    from app.services.failure_category_stats import (
        compute_failure_category_overlap_stats,
    )

    with get_session() as sess:
        stats = compute_failure_category_overlap_stats(session=sess, limit=limit)
    return stats.as_dict()


@router.get(
    "/interview-sessions/{session_id}/workflow-chain",
    dependencies=[Depends(require_admin_token)],
)
def get_workflow_decision_chain(
    session_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Per-turn workflow decision chain: director -> evaluator -> reward -> verifier.

    Groups trace rows by turn and extracts the decision-relevant fields
    so the frontend can render a compact "why this action / how scored /
    what the verifier said" timeline without parsing raw state snapshots.
    """
    from app.models import GenerationTrace, InterviewSession, get_session

    capped_limit = max(1, min(int(limit or 100), 300))
    with get_session() as sess:
        row = sess.get(InterviewSession, session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        traces = (
            sess.query(GenerationTrace)
            .filter(GenerationTrace.session_id == session_id)
            .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
            .limit(capped_limit)
            .all()
        )

    turns: dict[int, dict[str, Any]] = {}
    for trace in traces:
        turn = turns.setdefault(trace.turn_idx, {
            "turn_idx": trace.turn_idx,
            "dimension": None,
            "director": None,
            "evaluator": None,
            "reward": None,
            "verifier": None,
        })
        if trace.dimension:
            turn["dimension"] = trace.dimension

        if trace.node == "director_sample":
            snap = trace.state_snapshot or {}
            diag = snap.get("diagnostics") or {}
            action = snap.get("selected_action") or {}
            turn["director"] = {
                "action_id": action.get("id") or trace.action_id,
                "action_label": action.get("label") or action.get("id") or trace.action_id,
                "context_key": trace.context_key,
                "exploration": diag.get("exploration_type"),
                "allowed_arms": diag.get("allowed_arms"),
                "posterior_mean": diag.get("posterior_mean"),
                "runner_up": diag.get("runner_up"),
                "target_difficulty": snap.get("target_difficulty"),
            }
        elif trace.node == "evaluator":
            evaluation = trace.evaluation or {}
            turn["evaluator"] = {
                "score": trace.score,
                "passed": trace.passed,
                "immediate_reward": trace.immediate_reward,
                "strengths": evaluation.get("strengths"),
                "weaknesses": evaluation.get("weaknesses"),
                "question": trace.question,
                "answer_excerpt": _answer_excerpt(trace.answer),
            }
        elif trace.node == "reward_update":
            snap = trace.state_snapshot or {}
            payload = snap.get("payload") or snap
            turn["reward"] = {
                "reward_value": trace.immediate_reward,
                "reward_source": payload.get("reward_source"),
                "skipped": payload.get("skipped"),
                "skip_reason": payload.get("skip_reason"),
            }
        elif trace.node == "verification":
            snap = trace.state_snapshot or {}
            payload = snap.get("payload") or snap
            turn["verifier"] = {
                "original_passed": payload.get("original_passed"),
                "final_passed": trace.passed,
                "overruled": payload.get("overruled", False),
                "confidence": payload.get("confidence"),
                "rationale": payload.get("rationale"),
            }

    sorted_turns = sorted(turns.values(), key=lambda t: t["turn_idx"])
    return {
        "session_id": session_id,
        "status": row.status if row else None,
        "turn_count": len(sorted_turns),
        "turns": sorted_turns,
    }


@router.get(
    "/rag/eval",
    dependencies=[Depends(require_admin_token)],
)
def rag_evaluation_summary(
    since: str = "7d",
    limit: int = 200,
) -> dict[str, Any]:
    """Aggregate RAG retrieval metrics from recent sessions.

    Scans evaluator traces for retrieval-related signals: whether the
    retrieval block was non-empty, how many strategies/skills were
    injected, and correlates with evaluator scores to give a rough
    retrieval quality signal.
    """
    from datetime import UTC, datetime, timedelta

    from app.models import GenerationTrace, get_session

    hours_map = {"1h": 1, "24h": 24, "7d": 24 * 7, "30d": 24 * 30}
    hours = hours_map.get(since, 24 * 7)
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    with get_session() as sess:
        traces = (
            sess.query(GenerationTrace)
            .filter(
                GenerationTrace.node.in_(["evaluator", "director_sample"]),
                GenerationTrace.created_at >= cutoff,
            )
            .order_by(GenerationTrace.created_at.desc())
            .limit(max(1, min(int(limit or 200), 500)))
            .all()
        )

    total_evaluator = 0
    with_retrieval = 0
    without_retrieval = 0
    scores_with = []
    scores_without = []
    dimension_retrieval: dict[str, dict[str, int]] = {}

    for trace in traces:
        if trace.node != "evaluator":
            continue
        total_evaluator += 1
        snap = trace.state_snapshot or {}
        has_retrieval = bool(
            snap.get("retrieval_block")
            or snap.get("strategy_hits")
            or snap.get("skill_hits")
        )

        dim = trace.dimension or "unknown"
        dim_bucket = dimension_retrieval.setdefault(dim, {"with": 0, "without": 0})
        if has_retrieval:
            with_retrieval += 1
            dim_bucket["with"] += 1
            if trace.score is not None:
                scores_with.append(trace.score)
        else:
            without_retrieval += 1
            dim_bucket["without"] += 1
            if trace.score is not None:
                scores_without.append(trace.score)

    avg_with = round(sum(scores_with) / max(1, len(scores_with)), 2)
    avg_without = round(sum(scores_without) / max(1, len(scores_without)), 2)

    return {
        "window": since,
        "total_evaluator_traces": total_evaluator,
        "with_retrieval": with_retrieval,
        "without_retrieval": without_retrieval,
        "retrieval_rate": round(with_retrieval / max(1, total_evaluator), 3),
        "avg_score_with_retrieval": avg_with,
        "avg_score_without_retrieval": avg_without,
        "score_delta": round(avg_with - avg_without, 2),
        "per_dimension": dimension_retrieval,
    }


# ---------------------------------------------------------------------------
# Trace Annotations (Human Review)
# ---------------------------------------------------------------------------

_VALID_ANNOTATION_TYPES = {"bad_question", "wrong_score", "rag_miss", "verifier_error", "other"}
_VALID_VERDICTS = {"flagged", "approved", "corrected"}


@router.post("/annotations", dependencies=[Depends(require_admin_token)])
def create_annotation(body: dict[str, Any]) -> dict[str, Any]:
    """Create a human review annotation on a trace row."""
    from app.models import GenerationTrace, TraceAnnotation, get_session

    trace_id = str(body.get("trace_id") or "").strip()
    session_id = str(body.get("session_id") or "").strip()
    if not trace_id or not session_id:
        raise HTTPException(status_code=422, detail="trace_id and session_id required")

    turn_idx = body.get("turn_idx")
    if not isinstance(turn_idx, int) or turn_idx < 0:
        raise HTTPException(status_code=422, detail="turn_idx must be a non-negative integer")

    annotation_type = str(body.get("annotation_type") or "").strip()
    if annotation_type not in _VALID_ANNOTATION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"annotation_type must be one of {sorted(_VALID_ANNOTATION_TYPES)}",
        )

    verdict = str(body.get("verdict") or "flagged").strip()
    if verdict not in _VALID_VERDICTS:
        raise HTTPException(
            status_code=422,
            detail=f"verdict must be one of {sorted(_VALID_VERDICTS)}",
        )

    notes = str(body.get("notes") or "").strip()[:2000]
    reviewer = str(body.get("reviewer") or "admin").strip()[:64]
    raw_generation_trace_id = body.get("generation_trace_id")
    generation_trace_id: int | None = None
    if raw_generation_trace_id is not None:
        if not isinstance(raw_generation_trace_id, int) or raw_generation_trace_id <= 0:
            raise HTTPException(
                status_code=422,
                detail="generation_trace_id must be a positive integer",
            )
        generation_trace_id = raw_generation_trace_id
    node = str(body.get("node") or "").strip()[:64] or None

    with get_session() as sess:
        if generation_trace_id is not None:
            trace_row = sess.get(GenerationTrace, generation_trace_id)
            if trace_row is None:
                raise HTTPException(status_code=404, detail="generation trace not found")
            if getattr(trace_row, "session_id", None) != session_id:
                raise HTTPException(
                    status_code=422,
                    detail="generation trace does not belong to session",
                )
            node = str(getattr(trace_row, "node", "") or node or "")[:64] or None
            trace_id = str(getattr(trace_row, "trace_id", "") or trace_id)
        ann = TraceAnnotation(
            trace_id=trace_id,
            session_id=session_id,
            turn_idx=turn_idx,
            generation_trace_id=generation_trace_id,
            node=node,
            annotation_type=annotation_type,
            verdict=verdict,
            notes=notes or None,
            reviewer=reviewer,
        )
        sess.add(ann)
        sess.flush()
        ann_id = ann.id

    log.info(
        "annotation created id=%d session=%s turn=%d type=%s verdict=%s",
        ann_id, session_id, turn_idx, annotation_type, verdict,
    )
    return {"id": ann_id, "ok": True}


@router.get("/annotations", dependencies=[Depends(require_admin_token)])
def list_annotations(
    session_id: str | None = None,
    annotation_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List annotations, optionally filtered by session or type."""
    from app.models import TraceAnnotation, get_session

    capped = max(1, min(int(limit or 100), 500))
    with get_session() as sess:
        q = sess.query(TraceAnnotation)
        if session_id:
            q = q.filter(TraceAnnotation.session_id == session_id)
        if annotation_type and annotation_type in _VALID_ANNOTATION_TYPES:
            q = q.filter(TraceAnnotation.annotation_type == annotation_type)
        rows = q.order_by(TraceAnnotation.created_at.desc()).limit(capped).all()

    return {
        "count": len(rows),
        "annotations": [
            {
                "id": r.id,
                "trace_id": r.trace_id,
                "session_id": r.session_id,
                "turn_idx": r.turn_idx,
                "generation_trace_id": r.generation_trace_id,
                "node": r.node,
                "annotation_type": r.annotation_type,
                "verdict": r.verdict,
                "notes": r.notes,
                "reviewer": r.reviewer,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/annotations/stats", dependencies=[Depends(require_admin_token)])
def annotation_stats() -> dict[str, Any]:
    """Aggregate annotation counts by type and verdict."""
    from sqlalchemy import func

    from app.models import TraceAnnotation, get_session

    with get_session() as sess:
        total = sess.query(func.count(TraceAnnotation.id)).scalar() or 0
        by_type = (
            sess.query(TraceAnnotation.annotation_type, func.count(TraceAnnotation.id))
            .group_by(TraceAnnotation.annotation_type)
            .all()
        )
        by_verdict = (
            sess.query(TraceAnnotation.verdict, func.count(TraceAnnotation.id))
            .group_by(TraceAnnotation.verdict)
            .all()
        )

    return {
        "total": total,
        "by_type": {t: c for t, c in by_type},
        "by_verdict": {v: c for v, c in by_verdict},
    }
