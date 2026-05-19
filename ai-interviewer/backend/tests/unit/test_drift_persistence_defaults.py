"""PR7 rollout defaults for the verifier-drift persistence track.

Pins the four ``Settings`` knobs that PR7 flipped into their rollout
position so a future tweak that silently re-disables persistence or
re-points the feedback source back to ``monitor`` shows up as a
failing test instead of a silent prompt regression on every
deployment.

Why this lives in its own file:

* ``test_settings_verifier_threshold.py`` already owns the verifier
  abstain threshold default; tucking the drift defaults next to a
  semantically unrelated assertion would dilute either file's intent.
* Each test re-runs ``get_settings.cache_clear()`` AND strips the
  drift env keys via ``monkeypatch.delenv`` so the assertion holds
  regardless of whether the developer's ``.env`` (or a CI runner)
  overrode one of these knobs for their own purposes.
"""
from __future__ import annotations

import pytest

from app.core import settings as settings_mod
from app.ml.drift import prompt_feedback


_DRIFT_ENV_KEYS = (
    "ENABLE_VERIFIER_DRIFT_PERSISTENCE",
    "DRIFT_FEEDBACK_SOURCE",
    "VERIFIER_DRIFT_EVENT_RETENTION_DAYS",
    "DRIFT_PATTERN_AGGREGATION_WINDOW_DAYS",
)


@pytest.fixture(autouse=True)
def _isolate_drift_env(monkeypatch: pytest.MonkeyPatch):
    """Strip any process / ``.env`` overrides so we read the code defaults.

    Yields control to the test body, then clears the settings cache
    again on the way out so the next test in the suite reconstructs
    ``Settings`` from whatever the real environment dictates.
    """
    for key in _DRIFT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    settings_mod.get_settings.cache_clear()
    yield
    settings_mod.get_settings.cache_clear()


def test_default_settings_enable_drift_persistence() -> None:
    """PR7 rollout: persistence is ON by default so a fresh deployment
    starts capturing drift events without an extra flip in ``.env``."""
    settings = settings_mod.get_settings()
    assert settings.enable_verifier_drift_persistence is True


def test_default_settings_use_db_shadow_feedback_source() -> None:
    """PR7 rollout: prompt callers default to ``db_shadow`` so the
    visible markdown stays byte-identical with the monitor path while
    the DB read happens in the background for parity audit."""
    settings = settings_mod.get_settings()
    assert settings.drift_feedback_source == "db_shadow"


def test_resolve_source_defaults_to_db_shadow() -> None:
    """When callers omit ``source=``, ``_resolve_source`` reads the
    settings default — pinning this here means PR7 rollout cannot be
    silently undone by a refactor that bypasses ``_resolve_source``."""
    assert prompt_feedback._resolve_source(None) == "db_shadow"


def test_default_retention_and_window_lengths() -> None:
    """PR7 rollout: 90-day raw event retention + 30-day aggregation
    window keep the read model fresh without dropping recent drift.

    Locking the numbers here avoids a silent halving of either knob
    (e.g. a careless ``retention=30`` typo) wiping out long-tail drift
    signal the Generator / Evaluator feedback path depends on.
    """
    settings = settings_mod.get_settings()
    assert settings.verifier_drift_event_retention_days == 90
    assert settings.drift_pattern_aggregation_window_days == 30
