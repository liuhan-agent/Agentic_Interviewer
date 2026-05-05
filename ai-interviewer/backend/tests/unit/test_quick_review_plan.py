from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.core.settings import Settings
from app.engine.workflow.nodes import director_sample as director_mod
from app.engine.workflow.plans import resolve_ask_plan
from app.ml.rl.action_space import PLAN_ADAPTIVE


QUICK_REVIEW_ARM = "plan_quick_review"


class _CapturingBandit:
    def __init__(self) -> None:
        self.masks: list[set[str]] = []

    def observation_count(self, *_args: Any, **_kwargs: Any) -> int:
        return 10

    def select(self, _context_key: str, *, mask: set[str] | None = None):
        self.masks.append(set(mask or set()))
        return PLAN_ADAPTIVE, {"mode": "test_capture_mask"}


def _state() -> dict[str, Any]:
    return {
        "session_id": "sess-quick-review",
        "trace_id": "trace-quick-review",
        "job_spec": {"level": "mid"},
        "dimensions": ["technical_depth", "system_design"],
        "dimension_status": {
            "technical_depth": "active",
            "system_design": "pending",
        },
        "current_dimension": "technical_depth",
        "turn_idx": 1,
        "qa_history": [],
        "refine_mode": False,
        "runtime_config": {"policy_mode": "template"},
    }


def test_quick_review_plan_is_disabled_by_default() -> None:
    assert Settings().enable_quick_review_plan is False


def test_director_does_not_offer_quick_review_when_disabled(monkeypatch) -> None:
    bandit = _CapturingBandit()
    monkeypatch.setattr(director_mod, "get_bandit", lambda: bandit)
    monkeypatch.setattr(
        director_mod,
        "get_settings",
        lambda: SimpleNamespace(
            policy_mode="template",
            policy_direction_min_observations=3,
            enable_quick_review_plan=False,
        ),
    )

    director_mod.director_sample_node(_state())  # type: ignore[arg-type]

    assert bandit.masks
    assert QUICK_REVIEW_ARM not in bandit.masks[-1]


def test_director_offers_quick_review_when_enabled(monkeypatch) -> None:
    bandit = _CapturingBandit()
    monkeypatch.setattr(director_mod, "get_bandit", lambda: bandit)
    monkeypatch.setattr(
        director_mod,
        "get_settings",
        lambda: SimpleNamespace(
            policy_mode="template",
            policy_direction_min_observations=3,
            enable_quick_review_plan=True,
        ),
    )

    director_mod.director_sample_node(_state())  # type: ignore[arg-type]

    assert bandit.masks
    assert QUICK_REVIEW_ARM in bandit.masks[-1]


def test_resolve_ask_plan_uses_quick_review_template() -> None:
    plan = resolve_ask_plan(
        selected_action={"id": QUICK_REVIEW_ARM, "plan_template": "quick_review"},
        refine_mode=False,
        pending_plan_template=None,
        runtime_config={},
    )

    assert plan["template"] == "quick_review"
    assert plan["complexity"] == "simple"
    kinds = [step.get("kind") for step in plan["steps"]]
    assert kinds[-1] == "guardrail_check"
    assert "negotiate_contract" not in kinds
