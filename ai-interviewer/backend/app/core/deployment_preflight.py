"""Deployment preflight checks and startup configuration summary.

Runs at FastAPI startup to surface the active configuration as a
sanitised summary (booleans / enums only — no secrets) and, when
``APP_ENV=prod``, hard-fails on configurations that are unsafe for
production (e.g. memory checkpoint backend, missing API token).
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.settings import Settings

log = get_logger(__name__)


class PreflightError(RuntimeError):
    """Raised when a production-critical configuration check fails."""


def build_config_summary(settings: Settings) -> dict[str, Any]:
    """Return a sanitised snapshot of runtime-relevant configuration.

    Values are booleans, enums, or masked indicators — never raw
    secrets.  Safe to log and expose via the health endpoint.
    """
    return {
        "app_env": settings.app_env,
        "checkpoint_backend": settings.checkpoint_backend,
        "evidence_span_alignment": settings.evidence_span_alignment,
        "enable_verifier_drift_monitor": settings.enable_verifier_drift_monitor,
        "verifier_adaptive_trigger": settings.verifier_adaptive_trigger,
        "api_token_configured": bool(settings.api_token),
        "allow_open_admin": settings.allow_open_admin,
        "database_url_configured": bool(settings.database_url),
        "chroma_host": settings.chroma_host,
        "chroma_port": settings.chroma_port,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "stub_mode": settings.use_stub_llm,
        "embedding_provider": settings.embedding_provider,
        "resume_rag_mode": settings.resume_rag_mode,
        "resume_rag_embedding_model": settings.resume_rag_embedding_model,
        "resume_rag_embedding_dimension": settings.resume_rag_embedding_dimension,
        "resume_rag_session_sample_rate": settings.resume_rag_session_sample_rate,
        "resume_parse_cache_backend": settings.resume_parse_cache_backend,
        "asr_provider": settings.asr_provider,
        "tts_provider": settings.tts_provider,
        "rate_limit_backend": settings.rate_limit_backend,
        "voice_ticket_backend": settings.voice_ticket_backend,
        "verifier_drift_backend": settings.verifier_drift_backend,
        "langsmith_tracing": settings.langsmith_tracing,
        "default_guard_mode": settings.default_guard_mode,
        "redact_answer_pii": settings.redact_answer_pii,
        "enable_skill_injection": settings.enable_skill_injection,
        "skill_playbook_backend": settings.skill_playbook_backend,
        "enable_probe_intent": settings.enable_probe_intent,
        "policy_mode": settings.policy_mode,
    }


def _check_chroma_reachable(settings: Settings, issues: list[str]) -> None:
    """Verify Chroma is reachable in production (non-stub embeddings only).

    Appends to *issues* on failure rather than raising directly, so the
    caller can aggregate all preflight problems into a single report.
    """
    try:
        import chromadb  # noqa: F811

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        client.heartbeat()
    except ImportError:
        issues.append(
            "chromadb package is not installed; "
            "required for production RAG with non-stub embeddings"
        )
    except Exception as exc:
        issues.append(
            f"Chroma unreachable at {settings.chroma_host}:{settings.chroma_port}: {exc}"
        )


def run_preflight(settings: Settings) -> dict[str, Any]:
    """Execute preflight checks and return the config summary.

    In ``dev`` / ``test`` environments, issues are logged as warnings
    but never raise.  In ``prod``, hard-fail on critical
    misconfigurations so the process does not silently start with
    unsafe defaults.

    Returns the config summary dict for downstream consumers
    (e.g. health endpoint, startup log).
    """
    summary = build_config_summary(settings)

    log.info("startup config summary: %s", summary)

    is_prod = settings.app_env == "prod"
    issues: list[str] = []

    if settings.checkpoint_backend == "memory":
        msg = (
            "checkpoint_backend=memory does not survive process restarts; "
            "set CHECKPOINT_BACKEND=postgres for durable HITL"
        )
        if is_prod:
            issues.append(msg)
        else:
            log.warning("preflight: %s", msg)

    if not settings.api_token:
        msg = "API_TOKEN is empty; admin endpoints require a token in production"
        if is_prod:
            issues.append(msg)
        else:
            log.warning("preflight: %s", msg)

    if settings.use_stub_llm or settings.llm_provider == "stub":
        msg = "llm_provider=stub/use_stub_llm is not allowed in production"
        if is_prod:
            issues.append(msg)
        else:
            log.warning("preflight: %s", msg)

    if settings.embedding_provider == "stub":
        msg = "embedding_provider=stub is not allowed in production by default"
        if is_prod and not settings.allow_stub_embeddings_in_prod:
            issues.append(msg)
        else:
            log.warning("preflight: %s", msg)

    if settings.resume_parse_cache_backend == "memory":
        msg = (
            "resume_parse_cache_backend=memory is not safe for production "
            "multi-worker deployments"
        )
        if is_prod:
            issues.append(msg)
        else:
            log.warning("preflight: %s", msg)

    if settings.rate_limit_backend == "memory":
        msg = (
            "rate_limit_backend=memory is not safe for production "
            "multi-worker deployments; set RATE_LIMIT_BACKEND=redis"
        )
        if is_prod:
            issues.append(msg)
        else:
            log.warning("preflight: %s", msg)

    if settings.voice_ticket_backend == "memory":
        msg = (
            "voice_ticket_backend=memory is not safe for production "
            "multi-worker voice sessions; set VOICE_TICKET_BACKEND=redis"
        )
        if is_prod:
            issues.append(msg)
        else:
            log.warning("preflight: %s", msg)

    if is_prod and settings.embedding_provider != "stub":
        _check_chroma_reachable(settings, issues)

    if (
        settings.enable_verifier_drift_monitor
        and settings.verifier_drift_backend == "memory"
    ):
        log.warning(
            "preflight: verifier drift monitor uses memory backend; "
            "multi-worker production windows are not shared"
        )

    if is_prod and issues:
        detail = "; ".join(issues)
        raise PreflightError(
            f"Production preflight failed ({len(issues)} issue(s)): {detail}"
        )

    return summary
