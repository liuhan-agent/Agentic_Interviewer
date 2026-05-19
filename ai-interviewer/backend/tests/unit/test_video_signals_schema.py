from __future__ import annotations

from app.core.video_signals_schema import normalize_video_signals


def test_normalize_video_signals_accepts_valid_payload() -> None:
    assert normalize_video_signals(
        {
            "confidence": 0.7,
            "engagement": 0.5,
            "dominant_emotion": "positive",
            "sample_count": 12,
        }
    ) == {
        "confidence": 0.7,
        "engagement": 0.5,
        "dominant_emotion": "positive",
        "sample_count": 12,
    }


def test_normalize_video_signals_drops_malformed_payloads() -> None:
    assert normalize_video_signals(None) is None
    assert normalize_video_signals({"confidence": 2}) is None
    assert normalize_video_signals(["not", "a", "dict"]) is None
