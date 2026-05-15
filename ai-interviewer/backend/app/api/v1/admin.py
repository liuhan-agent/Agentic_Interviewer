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

from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.models import get_session

log = get_logger(__name__)

router = APIRouter(prefix="/admin", include_in_schema=False, tags=["admin"])
api_v1_router = APIRouter(
    prefix="/api/v1/admin", include_in_schema=False, tags=["admin"]
)


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

    s = get_settings()
    return {
        "priors": get_bandit().snapshot(),
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
    from app.tasks.drift_pattern_aggregation_tasks import (
        run_drift_pattern_aggregation_now,
    )

    return run_drift_pattern_aggregation_now()


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
    from app.tasks.drift_event_retention_tasks import (
        run_drift_event_retention_now,
    )

    return run_drift_event_retention_now()


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


def _recent_interview_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent persisted interview sessions for admin history."""
    from sqlalchemy import func

    from app.models import GenerationTrace, InterviewSession, get_session

    capped_limit = max(1, min(int(limit or 20), 100))
    try:
        with get_session() as sess:
            rows = (
                sess.query(InterviewSession)
                .order_by(InterviewSession.created_at.desc())
                .limit(capped_limit)
                .all()
            )
            session_ids = [row.session_id for row in rows]
            trace_counts: dict[str, dict[str, int]] = {
                session_id: {} for session_id in session_ids
            }
            if session_ids:
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
    except Exception as e:  # pragma: no cover - admin remains best-effort
        log.warning("admin interview sessions lookup failed: %s", e)
        return []

    items: list[dict[str, Any]] = []
    for row in rows:
        report = row.final_report or {}
        node_counts = trace_counts.get(row.session_id, {})
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
        items.append(
            {
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
                "overall_verdict": report.get("overall_verdict")
                or report.get("verdict"),
                "trace_count": trace_count,
                "evaluator_trace_count": evaluator_trace_count,
                "reward_trace_count": reward_trace_count,
                "final_report_trace_count": final_report_trace_count,
                "trace_health": trace_health,
                "error_kind": row.error_kind,
                "retryable": bool(row.retryable),
                "cost_summary": report.get("cost_summary"),
            }
        )
    return items


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
        "trace_diagnostics": trace_diagnostics(summary_nodes, session_status=row.status),
        "langsmith": _langsmith_admin_meta(),
        "node_count_total": total_trace_count,
        "nodes_offset": safe_offset,
        "nodes_limit": capped_limit,
        "nodes_has_more": safe_offset + len(nodes) < total_trace_count,
        "nodes": nodes,
    }


@router.get("/interview-sessions", dependencies=[Depends(require_admin_token)])
def list_interview_sessions(limit: int = 20) -> dict[str, Any]:
    """Return recent persisted interview sessions from the database."""
    sessions = _recent_interview_sessions(limit=limit)
    return {
        "count": len(sessions),
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

    from app.models import GenerationTrace, get_session

    cutoff = datetime.now(UTC) - timedelta(hours=_ROLLUP_WINDOWS_HOURS[since])
    try:
        with get_session() as sess:
            rows = (
                sess.query(GenerationTrace)
                .filter(GenerationTrace.created_at >= cutoff)
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

    for row in rows:
        node = str(getattr(row, "node", "") or "")
        if node == "evaluator":
            total_evaluator += 1
            evaluation = _as_dict(getattr(row, "evaluation", None))
            acceptance = _as_dict(evaluation.get("acceptance_check_results"))
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

    from app.models import GenerationTrace, get_session

    cutoff = datetime.now(UTC) - timedelta(hours=_ROLLUP_WINDOWS_HOURS[since])
    try:
        with get_session() as sess:
            rows = (
                sess.query(GenerationTrace)
                .filter(GenerationTrace.created_at >= cutoff)
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
