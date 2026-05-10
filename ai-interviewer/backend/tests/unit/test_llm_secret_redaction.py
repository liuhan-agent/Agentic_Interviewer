"""BYOK LLM key redaction defenses.

Locks in the three-layer protection of user-provided LLM API keys so that
future PRs cannot accidentally regress the secret-handling contract:

1. ``_safe_llm_config_meta`` strips ``api_key`` from any meta dict that
   may be persisted to the database (top-level **and** nested inside
   ``role_overrides``).
2. ``redact_llm_secrets`` replaces api_key occurrences inside provider
   error text with a stable placeholder before the text reaches logs or
   client responses.
3. The two functions never raise on ``None`` / empty inputs (they live on
   error paths and must stay silent).
"""
from __future__ import annotations

from app.engine.agents.llm_client import redact_llm_secrets
from app.services.session_manager import _safe_llm_config_meta


class TestSafeLLMConfigMeta:
    def test_returns_none_when_config_is_none(self) -> None:
        assert _safe_llm_config_meta(None) is None

    def test_returns_none_when_config_is_empty_dict(self) -> None:
        assert _safe_llm_config_meta({}) is None

    def test_strips_top_level_api_key_and_marks_requires_reauth(self) -> None:
        meta = _safe_llm_config_meta(
            {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "sk-real-secret-value",
            }
        )

        assert meta is not None
        assert "api_key" not in meta
        assert meta["provider"] == "openai"
        assert meta["model"] == "gpt-4o"
        assert meta["requires_reauth"] is True

    def test_marks_requires_reauth_false_when_api_key_absent(self) -> None:
        meta = _safe_llm_config_meta(
            {"provider": "openai", "model": "gpt-4o"}
        )

        assert meta is not None
        assert meta["requires_reauth"] is False

    def test_strips_nested_api_key_inside_role_overrides(self) -> None:
        meta = _safe_llm_config_meta(
            {
                "provider": "openai",
                "role_overrides": {
                    "coach": {
                        "provider": "anthropic",
                        "api_key": "sk-ant-nested-secret",
                        "model": "claude-3",
                    }
                },
            }
        )

        assert meta is not None
        coach_meta = meta["role_overrides"]["coach"]
        assert "api_key" not in coach_meta
        assert coach_meta["provider"] == "anthropic"
        assert coach_meta["model"] == "claude-3"
        assert meta["requires_reauth"] is True

    def test_strips_nested_api_key_inside_voice_overrides(self) -> None:
        meta = _safe_llm_config_meta(
            {
                "provider": "openai",
                "voice_overrides": {
                    "asr": {
                        "provider": "openai",
                        "api_key": "sk-voice-asr-secret",
                        "model": "whisper-1",
                    },
                    "tts": {
                        "provider": "openai",
                        "api_key": "sk-voice-tts-secret",
                        "model": "gpt-4o-mini-tts",
                        "voice": "alloy",
                    },
                },
            }
        )

        assert meta is not None
        asr_meta = meta["voice_overrides"]["asr"]
        tts_meta = meta["voice_overrides"]["tts"]
        assert "api_key" not in asr_meta
        assert "api_key" not in tts_meta
        assert asr_meta["model"] == "whisper-1"
        assert tts_meta["voice"] == "alloy"
        assert meta["requires_reauth"] is True


class TestRedactLLMSecrets:
    def test_returns_text_unchanged_when_text_empty(self) -> None:
        assert redact_llm_secrets("", {"api_key": "sk-secret"}) == ""

    def test_returns_text_unchanged_when_config_is_none(self) -> None:
        original = "401 unauthorized for sk-real-secret"
        assert redact_llm_secrets(original, None) == original

    def test_replaces_top_level_api_key_in_error_text(self) -> None:
        text = "OpenAI 401: invalid api key sk-real-secret-value (req_id=abc)"
        config = {"provider": "openai", "api_key": "sk-real-secret-value"}

        redacted = redact_llm_secrets(text, config)

        assert "sk-real-secret-value" not in redacted
        assert "[redacted-api-key]" in redacted

    def test_replaces_nested_api_key_in_role_overrides(self) -> None:
        text = "Anthropic 403: forbidden key=sk-ant-nested-secret"
        config = {
            "role_overrides": {
                "coach": {"api_key": "sk-ant-nested-secret"},
            }
        }

        redacted = redact_llm_secrets(text, config)

        assert "sk-ant-nested-secret" not in redacted
        assert "[redacted-api-key]" in redacted

    def test_replaces_nested_api_key_in_voice_overrides(self) -> None:
        text = "OpenAI audio rejected key sk-voice-tts-secret"
        config = {
            "voice_overrides": {
                "tts": {"api_key": "sk-voice-tts-secret"},
            }
        }

        redacted = redact_llm_secrets(text, config)

        assert "sk-voice-tts-secret" not in redacted
        assert "[redacted-api-key]" in redacted

    def test_leaves_text_unchanged_when_config_has_no_api_key(self) -> None:
        text = "OpenAI 429: rate limited"
        config = {"provider": "openai", "model": "gpt-4o"}

        assert redact_llm_secrets(text, config) == text
