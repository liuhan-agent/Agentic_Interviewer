from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.session_recovery import RecoveryService


class _Workflow:
    def __init__(self, *, values: dict[str, Any] | None, next_nodes: tuple[str, ...]):
        self.state = SimpleNamespace(values=values, next=next_nodes)
        self.calls: list[dict[str, Any]] = []

    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        self.calls.append(config)
        return self.state


class _ExplodingWorkflow:
    def get_state(self, _config: dict[str, Any]) -> SimpleNamespace:
        raise RuntimeError("checkpoint unavailable")


def test_checkpoint_exists_treats_empty_values_as_missing() -> None:
    service = RecoveryService(_Workflow(values={}, next_nodes=()))

    assert service.checkpoint_exists("sess-missing") is False


def test_waiting_question_returns_values_only_at_wait_answer() -> None:
    values = {
        "current_question": {"question": "Q?"},
        "turn_idx": 2,
        "final_report": None,
    }
    service = RecoveryService(_Workflow(values=values, next_nodes=("wait_answer",)))

    assert service.checkpoint_waiting_question("sess-waiting") == values


def test_waiting_question_rejects_terminal_or_empty_question() -> None:
    terminal = RecoveryService(
        _Workflow(
            values={"current_question": {"question": "Q?"}, "final_report": {"done": True}},
            next_nodes=("wait_answer",),
        )
    )
    empty_question = RecoveryService(
        _Workflow(values={"current_question": {}}, next_nodes=("wait_answer",))
    )

    assert terminal.checkpoint_waiting_question("sess-terminal") is None
    assert empty_question.checkpoint_waiting_question("sess-empty") is None


def test_retryable_question_failure_is_only_before_question_exists() -> None:
    retryable = RecoveryService(
        _Workflow(values={"current_question": None}, next_nodes=("ask_question",))
    )
    already_asked = RecoveryService(
        _Workflow(
            values={"current_question": {"question": "Q?"}},
            next_nodes=("ask_question",),
        )
    )

    assert retryable.checkpoint_retryable_question_failure("sess-retry") is True
    assert already_asked.checkpoint_retryable_question_failure("sess-asked") is False


def test_retryable_question_failure_allows_answered_stale_question() -> None:
    service = RecoveryService(
        _Workflow(
            values={
                "current_question": {"question": "previous question"},
                "current_answer": "candidate already answered it",
                "final_report": None,
            },
            next_nodes=("ask_question",),
        )
    )

    assert service.checkpoint_retryable_question_failure("sess-next-question") is True


def test_retryable_evaluator_failure_requires_answer_and_question() -> None:
    retryable = RecoveryService(
        _Workflow(
            values={
                "current_question": {"question": "Q?"},
                "current_answer": "candidate answer",
            },
            next_nodes=("evaluator",),
        )
    )
    missing_answer = RecoveryService(
        _Workflow(
            values={"current_question": {"question": "Q?"}, "current_answer": "   "},
            next_nodes=("evaluator",),
        )
    )

    assert retryable.checkpoint_retryable_evaluator_failure("sess-eval") is True
    assert missing_answer.checkpoint_retryable_evaluator_failure("sess-empty") is False


def test_checkpoint_probe_failures_return_safe_defaults() -> None:
    service = RecoveryService(_ExplodingWorkflow())

    assert service.checkpoint_exists("sess") is False
    assert service.checkpoint_waiting_question("sess") is None
    assert service.checkpoint_retryable_question_failure("sess") is False
    assert service.checkpoint_retryable_evaluator_failure("sess") is False
