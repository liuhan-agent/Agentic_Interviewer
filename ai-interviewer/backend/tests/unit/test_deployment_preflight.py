"""Tests for app.core.deployment_preflight."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.deployment_preflight import (
    PreflightError,
    _check_chroma_reachable,
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
            "resume_rag_mode": "off",
            "resume_rag_embedding_model": "text-embedding-3-small",
            "resume_rag_embedding_dimension": 1536,
            "resume_rag_session_sample_rate": 1.0,
            "allow_stub_embeddings_in_prod": False,
            "resume_parse_cache_backend": "redis",
            "asr_provider": "openai",
            "tts_provider": "openai",
            "rate_limit_backend": "redis",
            "voice_ticket_backend": "redis",
            "langsmith_tracing": False,
            "default_guard_mode": "regex_only",
            "redact_answer_pii": True,
            "enable_skill_injection": False,
            "skill_playbook_backend": "db_with_file_fallback",
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
            "resume_rag_mode",
            "resume_rag_embedding_model",
            "resume_rag_embedding_dimension",
            "resume_rag_session_sample_rate",
            "resume_parse_cache_backend",
            "asr_provider",
            "tts_provider",
            "rate_limit_backend",
            "voice_ticket_backend",
            "verifier_drift_backend",
            "langsmith_tracing",
            "default_guard_mode",
            "redact_answer_pii",
            "enable_skill_injection",
            "skill_playbook_backend",
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

    def test_skill_playbook_backend_included(self):
        s = _StubSettings(skill_playbook_backend="db")
        summary = build_config_summary(s)
        assert summary["skill_playbook_backend"] == "db"

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
        with patch("app.core.deployment_preflight._check_chroma_reachable"):
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

    def test_prod_memory_rate_limit_backend_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            rate_limit_backend="memory",
        )
        with pytest.raises(PreflightError, match="rate_limit_backend=memory"):
            run_preflight(s)

    def test_prod_memory_voice_ticket_backend_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            voice_ticket_backend="memory",
        )
        with pytest.raises(PreflightError, match="voice_ticket_backend=memory"):
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
        with patch("app.core.deployment_preflight._check_chroma_reachable"):
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

    def test_prod_chroma_unreachable_raises(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            embedding_provider="openai",
        )
        with patch(
            "app.core.deployment_preflight._check_chroma_reachable"
        ) as mock_check:
            mock_check.side_effect = lambda _settings, issues: issues.append(
                "Chroma unreachable at localhost:8100: connection refused"
            )
            with pytest.raises(PreflightError, match="Chroma unreachable"):
                run_preflight(s)

    def test_prod_stub_embedding_skips_chroma_check(self):
        s = _StubSettings(
            app_env="prod",
            checkpoint_backend="postgres",
            api_token="valid-token",
            llm_provider="openai",
            use_stub_llm=False,
            embedding_provider="stub",
            allow_stub_embeddings_in_prod=True,
        )
        with patch(
            "app.core.deployment_preflight._check_chroma_reachable"
        ) as mock_check:
            run_preflight(s)
            mock_check.assert_not_called()

    def test_dev_skips_chroma_check(self):
        s = _StubSettings(app_env="dev", embedding_provider="openai")
        with patch(
            "app.core.deployment_preflight._check_chroma_reachable"
        ) as mock_check:
            run_preflight(s)
            mock_check.assert_not_called()


class TestCheckChromaReachable:
    def test_heartbeat_success(self):
        s = _StubSettings(chroma_host="localhost", chroma_port=8100)
        issues: list[str] = []
        with patch("app.core.deployment_preflight.chromadb", create=True) as mock_mod:
            mock_client = mock_mod.HttpClient.return_value
            mock_client.heartbeat.return_value = 1
            # Patch the import inside the function
            with patch.dict("sys.modules", {"chromadb": mock_mod}):
                _check_chroma_reachable(s, issues)
        assert issues == []

    def test_connection_refused_appends_issue(self):
        s = _StubSettings(chroma_host="localhost", chroma_port=8100)
        issues: list[str] = []
        import sys

        fake_chromadb = type(sys)("chromadb")
        fake_chromadb.HttpClient = lambda **kw: (_ for _ in ()).throw(
            ConnectionError("connection refused")
        )

        class _RaisingHttpClient:
            def __init__(self, **kw):
                raise ConnectionError("connection refused")

        fake_chromadb.HttpClient = _RaisingHttpClient
        with patch.dict("sys.modules", {"chromadb": fake_chromadb}):
            _check_chroma_reachable(s, issues)
        assert len(issues) == 1
        assert "Chroma unreachable" in issues[0]

    def test_import_error_appends_issue(self):
        s = _StubSettings(chroma_host="localhost", chroma_port=8100)
        issues: list[str] = []
        with patch.dict("sys.modules", {"chromadb": None}):
            _check_chroma_reachable(s, issues)
        assert len(issues) == 1
        assert "chromadb package is not installed" in issues[0]
