from __future__ import annotations

from app.engine.workflow.policy_context import parse_policy_context_key


def test_parse_policy_context_key_for_global_level_dimension() -> None:
    parsed = parse_policy_context_key("senior:system_design")

    assert parsed.direction is None
    assert parsed.job_level == "senior"
    assert parsed.dimension == "system_design"


def test_parse_policy_context_key_for_direction_level_dimension() -> None:
    parsed = parse_policy_context_key("java_backend:senior:system_design")

    assert parsed.direction == "java_backend"
    assert parsed.job_level == "senior"
    assert parsed.dimension == "system_design"


def test_parse_policy_context_key_falls_back_for_invalid_key() -> None:
    parsed = parse_policy_context_key("")

    assert parsed.direction is None
    assert parsed.job_level == "mid"
    assert parsed.dimension == "general"
