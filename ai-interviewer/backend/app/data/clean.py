"""Very small PII redaction pass.

This is a pragmatic regex sweep.  When ``settings.pii_extra_patterns``
is True (the default) we also scrub URLs, IPv4 addresses, and Chinese
18-digit national ID numbers.  Phase 4 can route high-risk text
through a small NER model; the API shape stays the same so callers
never have to change.

Ordering is critical: more specific patterns (e.g. 18-digit ID, IPv4
dotted-quad) must run before the generic ``long_digit`` sweep or they
will be eaten as a raw digit run.  The implementation below preserves
that ordering explicitly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.settings import get_settings

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{10,}\b")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_CHINA_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@dataclass
class RedactionResult:
    cleaned: str
    redactions: dict[str, int]


def redact_pii(text: str) -> RedactionResult:
    """Redact PII and return cleaned text plus a per-category counter.

    Categories returned in ``RedactionResult.redactions``:

    - ``email``        — email addresses
    - ``url``          — http(s) URLs (opt-in via ``pii_extra_patterns``)
    - ``phone``        — phone-number-like digit groups
    - ``china_id``     — Chinese 18-digit national IDs
                         (opt-in via ``pii_extra_patterns``)
    - ``ip``           — IPv4 dotted-quad addresses
                         (opt-in via ``pii_extra_patterns``)
    - ``long_digit``   — any remaining run of 10+ digits
    """
    counts = {
        "email": 0,
        "phone": 0,
        "long_digit": 0,
        "url": 0,
        "china_id": 0,
        "ip": 0,
    }

    def _sub(pattern: re.Pattern[str], label: str, replacement: str, source: str) -> str:
        def _repl(_m: re.Match[str]) -> str:
            counts[label] += 1
            return replacement

        return pattern.sub(_repl, source)

    extra = get_settings().pii_extra_patterns

    t = text or ""

    # URL first: otherwise the embedded "@" in some URLs triggers the
    # email regex, which then leaves broken URL fragments around.
    if extra:
        t = _sub(_URL_RE, "url", "[url redacted]", t)

    t = _sub(_EMAIL_RE, "email", "[email redacted]", t)
    t = _sub(_PHONE_RE, "phone", "[phone redacted]", t)

    if extra:
        # 18-digit Chinese ID MUST be redacted before long_digit, or
        # its 17 leading digits get eaten and the trailing X/x is
        # left dangling as stray noise.
        t = _sub(_CHINA_ID_RE, "china_id", "[id redacted]", t)
        # IPv4 MUST be redacted before long_digit for the same reason:
        # "192.168.1.100" collapses to "1921681100" under _LONG_DIGITS
        # only if the dots survive the phone regex, which they
        # sometimes do.
        t = _sub(_IPV4_RE, "ip", "[ip redacted]", t)

    t = _sub(_LONG_DIGITS_RE, "long_digit", "[id redacted]", t)
    return RedactionResult(cleaned=t, redactions=counts)
