"""Tests for app.core.deployment_preflight."""
from __future__ import annotations

import pytest

from app.core.deployment_preflight import (
    PreflightError,
    build_config_summary,
    run_preflight,
)


class _StubSettings:
    """Minimal Settings stand-in for preflight tests."""

    def __init__(self, **overrides):
        defaults = {
            "app_env": "dev",
            "checkpoint_backend": "memory",
            "evidence_span_alignment": True,
            "enable_verifier_drift_monitor": False,
            "verifier_adaptive_trigger": False,
            "api_token": None,
            "allow_open_admin": False,
            "database_url": "postgresql+psycopg2://localhost/test",
            "chroma_host": "localhost",
            "chroma_port": 8100,
            "llm_provider": "stub",
            "llm_model": "gpt-4o-mini",
            "use_stub_llm": True,
            "embedding_provider": "openai",
            "allow_stub_embeddings_in_prod": False,
            "resume_parse_cache_backend": "redis",
            "asr_provider": "openai",
            "tts_provider": "openai",
            "langsmith_tracing": False,
            "default_guard_mode": "regex_only",
            "redact_answer_pii": True,
            "enable_skill_injection": False,
            "enable_probe_intent": True,
            "policy_mode": "template",
            "verifier_drift_backend": "memory",
            "redis_url": "redis://localhost:6380/0",
        }
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(self, k, v)


class TestBuildConfigSummary:
    def test_summary_contains_expected_keys(self):
        s = _StubSettings()
        summary = build_config_summary(s)
        expected_keys = {
            "app_env",
            "checkpoint_backend",
            "evidence_span_alignment",
            "enable_verifier_drift_monitor",
            "verifier_adaptive_trigger",
            "api_token_configured",
            "allow_open_admin",
            "database_url_configured",
            "chroma_host",
            "chroma_port",
            "llm_provider",
            "llm_model",
            "stub_mode",
            "embedding_provider",
            "resume_parse_cache_backend",
            "asr_provider",
            "tts_provider",
            "verifier_drift_backend",
            "langsmith_tracing",
            "default_guard_mode",
            "redact_answer_pii",
            "enable_skill_injection",
            "enable_probe_intent",
            "policy_mode",
        }
        assert set(summary.keys()) == expected_keys

    def test_token_not_leaked(self):
        s = _StubSettings(api_token="super-secret-token-12345")
        summary = build_config_summary(s)
        assert summary["api_token_configured"] is True
        for v in summary.values():
            if isinstance(v, str):
                assert "super-secret" not in v

    def test_no_token_shows_false(self):
        s = _StubSettings(api_token=None)
        summary = build_config_summary(s)
        assert summary["api_token_configured"] is False

    def test_database_url_masked(self):
        s = _StubSettings(database_url="postgresql+psycopg2://user:pass@host/db")
        summary = build_config_summary(s)
        assert summary["database_url_configured"] is True
        for v in summary.values():
            if isinstance(v, str):
                assert "pass" not in v or v in ("pass",)


class TestRunPreflight:
    def test_dev_memory_checkpoint_warns_but_succeeds(self):
        s = _StubSettings(app_env="dev", checkpoint_backend="memory")
        summary = run_preflight(s)
        assert summary["checkpoint_backend"] == "memory"

    def test_dev_no_token_warns_but_succeeds(self):
        s = _StubSettings(app_env="dev", api_token=None)
        summary = run_preflight(s)
        assert summary["api_token_configured"] is False

    def test_prod_memory_checkpoint_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="memory",
            api_token="valid-token",
        )
        with pytest.raises(PreflightError, match="checkpoint_backend=memory"):
            run_preflight(s)

    def test_prod_no_token_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token=None,
            allow_open_admin=False,
        )
        with pytest.raises(PreflightError, match="API_TOKEN"):
            run_preflight(s)

    def test_prod_valid_config_succeeds(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
        )
        summary = run_preflight(s)
        assert summary["app_env"] == "prod"
        assert summary["checkpoint_backend"] == "postgres"
        assert summary["api_token_configured"] is True

    def test_prod_stub_llm_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="stub",
            use_stub_llm=True,
        )
        with pytest.raises(PreflightError, match="llm_provider=stub"):
            run_preflight(s)

    def test_prod_stub_embedding_raises_by_default(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            embedding_provider="stub",
        )
        with pytest.raises(PreflightError, match="embedding_provider=stub"):
            run_preflight(s)

    def test_prod_stub_embedding_can_be_explicitly_allowed(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            embedding_provider="stub",
            allow_stub_embeddings_in_prod=True,
        )
        summary = run_preflight(s)
        assert summary["embedding_provider"] == "stub"

    def test_prod_memory_resume_cache_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            resume_parse_cache_backend="memory",
        )
        with pytest.raises(PreflightError, match="resume_parse_cache_backend=memory"):
            run_preflight(s)

    def test_prod_drift_monitor_memory_backend_warns_but_succeeds(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            enable_verifier_drift_monitor=True,
            verifier_drift_backend="memory",
        )
        summary = run_preflight(s)
        assert summary["enable_verifier_drift_monitor"] is True
        assert summary["verifier_drift_backend"] == "memory"

    def test_prod_open_admin_without_token_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token=None,
            allow_open_admin=True,
            llm_provider="openai",
            use_stub_llm=False,
        )
        with pytest.raises(PreflightError, match="API_TOKEN"):
            run_preflight(s)

    def test_test_env_no_strict_checks(self):
        s = _StubSettings(
            app_env="test",
            checkpoint_backend="memory",
            api_token=None,
        )
        summary = run_preflight(s)
        assert summary["app_env"] == "test"
