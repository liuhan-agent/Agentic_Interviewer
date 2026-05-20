"""FastAPI application entrypoint.

Endpoints::

    GET  /health
    POST /api/v1/interview/sessions
    GET  /api/v1/interview/sessions/{id}/question
    POST /api/v1/interview/sessions/{id}/answer
    GET  /api/v1/interview/sessions/{id}/report
    WS   /ws/voice/{id}
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1 import admin as admin_api
from app.api.v1 import interview as interview_api
from app.api.v1 import llm as llm_api
from app.api.v1 import ws_voice as ws_voice_api
from app.core.deployment_preflight import run_preflight
from app.core.logging import configure_logging, get_logger
from app.core.request_context import install_request_context_middleware
from app.core.settings import Settings, get_settings
from app.models import init_db
from app.tasks.dream_tasks import start_dream_scheduler
from app.tasks.drift_maintenance_tasks import start_drift_maintenance_scheduler
from app.tasks.outcome_sync_tasks import (
    start_background_scheduler,
    start_decay_scheduler,
)
from app.tasks.privacy_cleanup_tasks import start_privacy_cleanup_scheduler
from app.tasks.strategy_promotion_tasks import start_strategy_promotion_scheduler

configure_logging()
log = get_logger(__name__)


def _configure_langsmith(settings: Settings) -> None:
    """Propagate LangSmith settings into the process environment.

    LangChain/LangGraph pick up tracing via ``LANGSMITH_*`` env vars.
    We keep the source of truth in ``Settings`` (so ``.env`` / tests
    work uniformly) and only mirror into ``os.environ`` at startup.
    This is a no-op when ``langsmith_tracing`` is False.
    """
    if not settings.langsmith_tracing:
        return
    if not settings.langsmith_api_key:
        log.warning("LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty; disabling")
        return
    project = settings.effective_langsmith_project
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", project)
    os.environ.setdefault("LANGCHAIN_PROJECT", project)
    os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langsmith_endpoint)
    log.info("LangSmith tracing enabled (project=%s)", project)


def _run_startup(app: FastAPI, settings: Settings) -> None:
    app.state.config_summary = run_preflight(settings)

    try:
        init_db()
    except Exception as e:  # pragma: no cover
        log.warning("init_db during startup failed: %s", e)
    # Delayed-reward closed loop: rehydrating bandit priors from
    # persisted traces has to happen *before* the scheduler starts
    # so the first backfill tick does not double-apply rewards
    # that were already fused into the priors on boot.
    if settings.rehydrate_bandit_on_start:
        try:
            from app.ml.rl.thompson import get_bandit

            get_bandit().rehydrate_from_db()
        except Exception as e:  # pragma: no cover
            log.warning("bandit rehydrate failed: %s", e)

    # Durable HITL: restore interrupted sessions so clients can
    # reconnect via GET /sessions/{id}/resume after a restart.
    try:
        from app.services.session_manager import get_session_manager

        n = get_session_manager().rehydrate()
        if n:
            log.info("rehydrated %d interrupted interview session(s)", n)
    except Exception as e:  # pragma: no cover
        log.warning("session rehydrate failed: %s", e)

    if settings.enable_outcome_sync:
        try:
            app.state.scheduler = start_background_scheduler(
                interval_minutes=settings.outcome_sync_interval_minutes
            )
        except Exception as e:  # pragma: no cover
            log.warning("outcome scheduler startup failed: %s", e)

    if settings.enable_bandit_decay:
        try:
            app.state.decay_scheduler = start_decay_scheduler(
                interval_days=settings.bandit_decay_interval_days,
                factor=settings.bandit_decay_factor,
                floor=settings.bandit_decay_floor,
            )
        except Exception as e:  # pragma: no cover
            log.warning("decay scheduler startup failed: %s", e)

    if settings.enable_strategy_dream:
        try:
            app.state.dream_scheduler = start_dream_scheduler()
        except Exception as e:  # pragma: no cover
            log.warning("strategy dream scheduler startup failed: %s", e)

    if settings.enable_strategy_promotion_scheduler:
        try:
            app.state.strategy_promotion_scheduler = (
                start_strategy_promotion_scheduler(
                    interval_minutes=settings.strategy_promotion_interval_minutes,
                    startup_delay_minutes=(
                        settings.strategy_promotion_startup_delay_minutes
                    ),
                )
            )
        except Exception as e:  # pragma: no cover
            log.warning("strategy promotion scheduler startup failed: %s", e)

    if settings.enable_drift_maintenance_scheduler:
        try:
            app.state.drift_maintenance_scheduler = (
                start_drift_maintenance_scheduler(
                    aggregation_interval_minutes=(
                        settings.drift_pattern_aggregation_interval_minutes
                    ),
                    retention_interval_hours=(
                        settings.drift_event_retention_interval_hours
                    ),
                )
            )
        except Exception as e:  # pragma: no cover
            log.warning("drift maintenance scheduler startup failed: %s", e)

    if settings.enable_privacy_cleanup:
        try:
            app.state.privacy_cleanup_scheduler = start_privacy_cleanup_scheduler(
                interval_hours=settings.privacy_cleanup_interval_hours,
                batch_size=settings.privacy_cleanup_batch_size,
            )
        except Exception as e:  # pragma: no cover
            log.warning("privacy cleanup scheduler startup failed: %s", e)


def _run_shutdown(app: FastAPI) -> None:
    for attr in (
        "scheduler",
        "decay_scheduler",
        "dream_scheduler",
        "strategy_promotion_scheduler",
        "drift_maintenance_scheduler",
        "privacy_cleanup_scheduler",
    ):
        s = getattr(app.state, attr, None)
        if s is not None:
            try:
                s.shutdown(wait=False)
            except Exception as e:  # pragma: no cover
                log.warning("%s shutdown failed: %s", attr, e)


def _lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _run_startup(app, settings)
        try:
            yield
        finally:
            _run_shutdown(app)

    return lifespan


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_langsmith(settings)
    app = FastAPI(
        title="Agentic Interviewer",
        version=__version__,
        description="LangGraph-based multi-agent AI interviewer",
        lifespan=_lifespan(settings),
    )

    # CORS: the Next.js frontend runs on a different origin in dev and
    # browsers block the preflight without this middleware.  Production
    # deployments should narrow ``cors_origins`` to the exact hostnames
    # that are allowed to call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_request_context_middleware(app)

    app.include_router(interview_api.router)
    app.include_router(llm_api.router)
    app.include_router(ws_voice_api.router)
    app.include_router(admin_api.router)
    app.include_router(admin_api.api_v1_router)

    demo_dir = Path(__file__).resolve().parents[1] / "webdemo"
    if demo_dir.exists():
        app.mount("/static", StaticFiles(directory=str(demo_dir)), name="static")

        @app.get("/demo", include_in_schema=False)
        async def _demo_page() -> FileResponse:
            return FileResponse(str(demo_dir / "index.html"))

    app.state.scheduler = None
    app.state.decay_scheduler = None
    app.state.dream_scheduler = None
    app.state.strategy_promotion_scheduler = None
    app.state.drift_maintenance_scheduler = None
    app.state.privacy_cleanup_scheduler = None

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.app_env,
            "llm_provider": settings.llm_provider,
            "stub_mode": str(settings.use_stub_llm),
            "checkpoint_backend": settings.checkpoint_backend,
            "langsmith_tracing": str(settings.langsmith_tracing),
        }

    log.info("FastAPI app constructed (env=%s)", settings.app_env)
    return app


app = create_app()
