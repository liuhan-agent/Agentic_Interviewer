"""Production preflight CLI.

Runs the same sanitized configuration checks used at FastAPI startup and
optionally probes infrastructure dependencies. The output is safe for CI logs:
it prints booleans, enums, host/port metadata, and probe status only.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.core.deployment_preflight import PreflightError, run_preflight
from app.core.settings import Settings, get_settings


@dataclass(frozen=True)
class ProbeResult:
    """Dependency probe result rendered by the CLI."""

    name: str
    ok: bool
    message: str


def _safe_error(exc: Exception, settings: Settings) -> str:
    """Return a short error message without known DSNs or credentials."""
    message = str(exc).splitlines()[0]
    for secretish in (
        getattr(settings, "database_url", None),
        getattr(settings, "redis_url", None),
    ):
        if secretish:
            message = message.replace(str(secretish), "<redacted>")
    return f"{type(exc).__name__}: {message}"


def _probe_postgres(settings: Settings) -> ProbeResult:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(settings.database_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        return ProbeResult("postgres", True, "ok")
    except Exception as exc:
        return ProbeResult("postgres", False, _safe_error(exc, settings))


def _probe_redis(settings: Settings) -> ProbeResult:
    try:
        from redis import Redis

        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        client.close()
        return ProbeResult("redis", True, "ok")
    except Exception as exc:
        return ProbeResult("redis", False, _safe_error(exc, settings))


def _probe_chroma(settings: Settings) -> ProbeResult:
    try:
        import chromadb

        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        client.heartbeat()
        return ProbeResult("chroma", True, "ok")
    except Exception as exc:
        return ProbeResult("chroma", False, _safe_error(exc, settings))


def run_dependency_probes(settings: Settings) -> list[ProbeResult]:
    """Run optional infrastructure probes.

    Unit tests monkeypatch this function so the CLI contract stays independent
    from local Postgres, Redis, or Chroma availability.
    """
    return [
        _probe_postgres(settings),
        _probe_redis(settings),
        _probe_chroma(settings),
    ]


def _print_json(title: str, payload: Any) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run production preflight checks for AI Interviewer",
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="also probe Postgres, Redis, and Chroma connectivity",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        summary = run_preflight(settings)
    except PreflightError as exc:
        print("PRODUCTION PREFLIGHT FAILED", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    _print_json("PRODUCTION PREFLIGHT OK", summary)

    if not args.check_deps:
        return 0

    probes = run_dependency_probes(settings)
    _print_json("DEPENDENCY PROBES", [asdict(result) for result in probes])
    if settings.app_env == "prod" and any(not result.ok for result in probes):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
