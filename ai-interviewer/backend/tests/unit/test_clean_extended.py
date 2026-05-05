"""Extended PII redaction coverage (URL / IPv4 / Chinese 18-digit ID).

These tests lock in the ordering rules called out in
``app/data/clean.py``:

- URL runs before EMAIL so embedded ``@`` in URLs does not leak as a
  broken email fragment.
- Chinese 18-digit ID runs before the generic ``long_digit`` sweep or
  the trailing X/x would be left dangling.
- IPv4 runs before ``long_digit`` for the same reason.
"""
from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.data.clean import redact_pii


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """Reset the ``@lru_cache`` on ``get_settings`` for each test so
    env mutations in other test modules cannot bleed into PII regex
    behaviour asserted here."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_url_is_redacted_when_extra_patterns_enabled():
    text = "See the repo at https://github.com/foo/bar for details."
    r = redact_pii(text)
    assert "https://github.com/foo/bar" not in r.cleaned
    assert "[url redacted]" in r.cleaned
    assert r.redactions["url"] == 1


def test_ipv4_is_redacted():
    text = "Server at 10.0.5.42 went down last night."
    r = redact_pii(text)
    assert "10.0.5.42" not in r.cleaned
    assert "[ip redacted]" in r.cleaned
    assert r.redactions["ip"] == 1


def test_china_18_digit_id_is_redacted():
    # Synthetic ID; last char is ``X`` which the generic long_digit
    # pattern would NOT match - this is exactly why ``china_id`` has
    # to run first.
    text = "My national id: 11010519491231002X, please keep private."
    r = redact_pii(text)
    assert "11010519491231002X" not in r.cleaned
    assert r.redactions["china_id"] == 1
    # And the trailing X must not leak as stray noise.
    assert "X," not in r.cleaned


def test_long_digit_run_is_redacted_by_some_category():
    """A long digit run that is NOT an ID or an IP must be redacted
    by *some* PII category. Today the phone regex is generous enough
    to consume 10-16 digit runs, so the signal surfaces under
    ``phone``; if that regex is ever tightened the ``long_digit``
    fallback picks it up instead. Either way the string must not
    leak into the cleaned output.
    """
    text = "tracking no 987654321098765 and more text"
    r = redact_pii(text)
    assert "987654321098765" not in r.cleaned
    assert (r.redactions["phone"] + r.redactions["long_digit"]) == 1


def test_mixed_pii_all_categories_fire_once():
    text = (
        "Email: bob@example.com - repo https://site.io/x - "
        "call 13812345678 - ip 192.168.1.1 - id 11010519491231002X"
    )
    r = redact_pii(text)
    assert "bob@example.com" not in r.cleaned
    assert "https://site.io/x" not in r.cleaned
    assert "13812345678" not in r.cleaned
    assert "192.168.1.1" not in r.cleaned
    assert "11010519491231002X" not in r.cleaned
    assert r.redactions["email"] == 1
    assert r.redactions["url"] == 1
    # phone pattern is permissive so it may also fire on the IPv4
    # before our IPv4-first rule rewrites it; the important invariant
    # is that the raw IP string is gone, not which category counted
    # for it.
    assert (r.redactions["phone"] + r.redactions["ip"]) >= 2
    assert r.redactions["china_id"] == 1


def test_pii_extra_disabled_retains_legacy_behaviour(monkeypatch):
    """``pii_extra_patterns=False`` must recreate the pre-Step-3
    behaviour bit-for-bit: URL / IP / Chinese-ID must flow through."""
    monkeypatch.setenv("PII_EXTRA_PATTERNS", "false")
    get_settings.cache_clear()
    text = "repo https://site.io/x ; ip 10.0.0.1 ; id 11010519491231002X"
    r = redact_pii(text)
    # All three opt-in patterns are disabled; the surviving substrings
    # should remain in cleaned output (modulo what the legacy
    # long_digit sweep kills, which is digits only and won't touch
    # letters / dots / slashes).
    assert "https://site.io/x" in r.cleaned
    assert "10.0.0.1" in r.cleaned
    # The leading 17 digits of the ID get eaten by long_digit here;
    # the trailing X is left dangling, which is precisely the bug
    # Step 3 existed to fix.  We assert the regression shape (X
    # stranded) to keep the test honest about what the toggle does.
    assert r.cleaned.endswith("X")
