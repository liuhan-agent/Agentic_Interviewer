"""Tests for the production smoke CLI."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.deployment_preflight import PreflightError
from app.scripts import production_smoke


@dataclass
class _Settings:
    app_env: str = "prod"
    database_url: str = "postgresql+psycopg2://user:secret@localhost/db"
    redis_url: str = "redis://:secret@localhost:6380/0"
    chroma_host: str = "localhost"
    chroma_port: int = 8100


def test_main_prints_sanitized_summary(capsys, monkeypatch) -> None:
    monkeypatch.setattr(production_smoke, "get_settings", lambda: _Settings())
    monkeypatch.setattr(
        production_smoke,
        "run_preflight",
        lambda _settings: {
            "app_env": "prod",
            "checkpoint_backend": "postgres",
            "api_token_configured": True,
            "database_url_configured": True,
            "chroma_host": "localhost",
            "chroma_port": 8100,
        },
    )

    assert production_smoke.main([]) == 0

    out = capsys.readouterr().out
    assert "PRODUCTION PREFLIGHT OK" in out
    assert "api_token_configured" in out
    assert "secret" not in out


def test_main_returns_nonzero_for_preflight_error(capsys, monkeypatch) -> None:
    monkeypatch.setattr(production_smoke, "get_settings", lambda: _Settings())

    def _raise(_settings):
        raise PreflightError("Production preflight failed: API_TOKEN is empty")

    monkeypatch.setattr(production_smoke, "run_preflight", _raise)

    assert production_smoke.main([]) == 1

    captured = capsys.readouterr()
    assert "PRODUCTION PREFLIGHT FAILED" in captured.err
    assert "API_TOKEN is empty" in captured.err


def test_main_runs_optional_dependency_probes(capsys, monkeypatch) -> None:
    monkeypatch.setattr(production_smoke, "get_settings", lambda: _Settings(app_env="dev"))
    monkeypatch.setattr(
        production_smoke,
        "run_preflight",
        lambda _settings: {"app_env": "dev", "api_token_configured": False},
    )
    monkeypatch.setattr(
        production_smoke,
        "run_dependency_probes",
        lambda _settings: [
            production_smoke.ProbeResult("postgres", True, "ok"),
            production_smoke.ProbeResult("redis", True, "ok"),
            production_smoke.ProbeResult("chroma", True, "ok"),
        ],
    )

    assert production_smoke.main(["--check-deps"]) == 0

    out = capsys.readouterr().out
    assert "DEPENDENCY PROBES" in out
    assert "postgres" in out
    assert "redis" in out
    assert "chroma" in out


def test_prod_dependency_probe_failure_is_nonzero(capsys, monkeypatch) -> None:
    monkeypatch.setattr(production_smoke, "get_settings", lambda: _Settings(app_env="prod"))
    monkeypatch.setattr(
        production_smoke,
        "run_preflight",
        lambda _settings: {"app_env": "prod", "api_token_configured": True},
    )
    monkeypatch.setattr(
        production_smoke,
        "run_dependency_probes",
        lambda _settings: [
            production_smoke.ProbeResult("postgres", True, "ok"),
            production_smoke.ProbeResult("redis", False, "connection refused"),
        ],
    )

    assert production_smoke.main(["--check-deps"]) == 1

    captured = capsys.readouterr()
    assert "redis" in captured.out
    assert "connection refused" in captured.out
