from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.services.session_manager import (
    SessionHandle,
    SessionManager,
    _sync_setup_snapshot_vector_status,
)


def test_wait_until_idle_blocks_until_segment_finally_clears_running():
    manager = SessionManager.__new__(SessionManager)
    handle = SessionHandle(session_id="sess-race", trace_id="trace-race")
    with handle._segment_lock:
        handle._running = True

    def clear_running() -> None:
        time.sleep(0.05)
        with handle._segment_lock:
            handle._running = False

    t = threading.Thread(target=clear_running)
    t.start()
    try:
        assert manager._wait_until_idle(handle, timeout=1.0) is True
    finally:
        t.join(timeout=1.0)


def test_start_segment_reports_already_running_without_starting_thread():
    manager = SessionManager.__new__(SessionManager)
    handle = SessionHandle(session_id="sess-start-busy", trace_id="trace-start-busy")
    with handle._segment_lock:
        handle._running = True

    assert manager._start_segment(handle, object()) is False

    with handle._segment_lock:
        assert handle._running is True


def test_wait_for_next_question_returns_immediately_when_done():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-done", trace_id="trace-done")
    handle.done_event.set()
    manager._sessions[handle.session_id] = handle

    started = time.monotonic()
    assert manager.wait_for_next_question(handle.session_id, timeout=0.5) is None
    elapsed = time.monotonic() - started

    assert elapsed < 0.1


def test_submit_answer_rejects_stale_turn_idx():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-turn", trace_id="trace-turn")
    handle.current_question = {"question": "Q"}
    handle.turn_idx = 2
    handle.question_event.set()
    manager._sessions[handle.session_id] = handle

    with pytest.raises(ValueError, match="turn_idx"):
        manager.submit_answer("sess-turn", "answer", turn_idx=1)

    assert handle.question_event.is_set()


def test_submit_answer_rejects_when_not_waiting_for_answer():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-not-waiting", trace_id="trace-turn")
    handle.current_question = {"question": "Q"}
    handle.turn_idx = 2
    manager._sessions[handle.session_id] = handle

    with pytest.raises(ValueError, match="waiting"):
        manager.submit_answer("sess-not-waiting", "answer", turn_idx=2)


def test_submit_answer_rejects_busy_prior_segment_and_keeps_waiting_state():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-busy", trace_id="trace-busy")
    handle.current_question = {"question": "Q"}
    handle.turn_idx = 2
    handle.asked_turn = 1
    handle.question_event.set()
    manager._sessions[handle.session_id] = handle
    manager._wait_until_idle = lambda _handle: False  # type: ignore[method-assign]

    started: list[object] = []
    manager._start_segment = lambda _handle, command: started.append(command)  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="prior segment"):
        manager.submit_answer("sess-busy", "answer", turn_idx=2)

    assert handle.question_event.is_set()
    assert handle.asked_turn == 1
    assert started == []


def test_submit_answer_requires_byok_reauth_after_rehydrate():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-byok", trace_id="trace-byok")
    handle.current_question = {"question": "Q"}
    handle.turn_idx = 2
    handle.question_event.set()
    handle.llm_config_meta = {"requires_reauth": True}  # type: ignore[attr-defined]
    manager._sessions[handle.session_id] = handle

    with pytest.raises(ValueError, match="reauth_required"):
        manager.submit_answer("sess-byok", "answer", turn_idx=2)


def test_sync_setup_snapshot_vector_status_updates_runtime_statuses() -> None:
    handle = SessionHandle(
        session_id="sess-anchor",
        trace_id="trace-anchor",
        setup_snapshot={
            "candidate": {
                "name": "Ada",
                "resume_parsed": {"summary": "Built payment systems."},
            },
            "job_spec": {"title": "Backend Engineer"},
            "resume_vector_status": {
                "status": "pending_node",
                "resume_source_id": "artifact_1",
                "resume_revision_id": None,
            },
        },
    )
    state = {
        "candidate": {
            "resume_vector_status": {
                "status": "ready",
                "resume_source_id": "artifact_1",
                "resume_revision_id": "rev_1",
                "chunk_count": 24,
            }
        },
        "self_intro_vector_status": {
            "status": "ready",
            "self_intro_revision_id": "intro_rev_1",
            "chunk_count": 5,
        },
    }

    _sync_setup_snapshot_vector_status(handle, state)

    assert handle.setup_snapshot is not None
    assert handle.setup_snapshot["resume_vector_status"]["status"] == "ready"
    assert handle.setup_snapshot["resume_vector_status"]["resume_revision_id"] == "rev_1"
    assert handle.setup_snapshot["candidate"]["resume_vector_status"]["status"] == "ready"
    assert handle.setup_snapshot["self_intro_vector_status"]["status"] == "ready"


def test_sync_setup_snapshot_vector_status_can_rebuild_missing_snapshot() -> None:
    handle = SessionHandle(session_id="sess-anchor", trace_id="trace-anchor")
    state = {
        "candidate": {
            "name": "Ada",
            "resume_parsed": {"summary": "Built payment systems."},
            "resume_vector_status": {
                "status": "ready",
                "resume_source_id": "artifact_1",
                "resume_revision_id": "rev_1",
            },
        },
        "job_spec": {"title": "Backend Engineer"},
        "self_intro_vector_status": {
            "status": "ready",
            "self_intro_revision_id": "intro_rev_1",
        },
    }

    _sync_setup_snapshot_vector_status(handle, state)

    assert handle.setup_snapshot is not None
    assert handle.setup_snapshot["candidate"]["name"] == "Ada"
    assert handle.setup_snapshot["job_spec"]["title"] == "Backend Engineer"
    assert handle.setup_snapshot["resume_vector_status"]["status"] == "ready"
    assert handle.setup_snapshot["self_intro_vector_status"]["status"] == "ready"


def test_submit_answer_accepts_llm_config_for_reauth():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    started: list[object] = []
    handle = SessionHandle(session_id="sess-byok", trace_id="trace-byok")
    handle.current_question = {"question": "Q"}
    handle.turn_idx = 2
    handle.question_event.set()
    handle.llm_config_meta = {"requires_reauth": True}  # type: ignore[attr-defined]
    manager._sessions[handle.session_id] = handle
    manager._wait_until_idle = lambda _handle: True  # type: ignore[method-assign]
    manager._start_segment = lambda _handle, command: started.append(command)  # type: ignore[method-assign]

    llm_config = {
        "provider": "qwen",
        "api_key": "secret",
        "model": "qwen3.6-flash",
    }
    manager.submit_answer(
        "sess-byok",
        "answer",
        turn_idx=2,
        llm_config=llm_config,
    )

    assert handle.llm_config == llm_config
    assert handle.question_event.is_set() is False
    assert len(started) == 1


def test_skip_question_rejects_stale_turn_idx():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-skip-turn", trace_id="trace-skip")
    handle.current_question = {"question": "Q"}
    handle.turn_idx = 3
    handle.question_event.set()
    manager._sessions[handle.session_id] = handle

    with pytest.raises(ValueError, match="turn_idx"):
        manager.skip_question("sess-skip-turn", turn_idx=2)

    assert handle.question_event.is_set()


def test_skip_question_resumes_with_skip_marker():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    started: list[object] = []
    handle = SessionHandle(session_id="sess-skip", trace_id="trace-skip")
    handle.current_question = {"question": "Q"}
    handle.turn_idx = 3
    handle.asked_turn = 2
    handle.question_event.set()
    manager._sessions[handle.session_id] = handle
    manager._wait_until_idle = lambda _handle: True  # type: ignore[method-assign]
    manager._start_segment = lambda _handle, command: started.append(command)  # type: ignore[method-assign]

    manager.skip_question("sess-skip", turn_idx=3, reason="need practice")

    assert handle.question_event.is_set() is False
    assert handle.asked_turn == 3
    assert len(started) == 1
    assert "__skipped__" in repr(started[0])
    assert "need practice" in repr(started[0])


def test_retry_failed_question_rehydrates_missing_handle_from_retryable_checkpoint():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    started: list[tuple[str, object]] = []

    manager._checkpoint_retryable_question_failure = lambda session_id: True  # type: ignore[attr-defined]
    manager._load_persisted_session_for_retry = lambda session_id: {  # type: ignore[attr-defined]
        "trace_id": "trace-retry",
        "candidate_name": "Alex",
        "job_title": "Java 后端",
        "job_level": "junior",
        "mode": "mixed",
        "turn_idx": 1,
        "asked_turn": 0,
    }

    def fake_start_segment(handle: SessionHandle, stream_input: object) -> None:
        started.append((handle.session_id, stream_input))

    manager._start_segment = fake_start_segment  # type: ignore[method-assign]

    handle = manager.retry_failed_question("sess-retry")

    assert handle is not None
    assert handle.session_id == "sess-retry"
    assert handle.trace_id == "trace-retry"
    assert handle.job_title == "Java 后端"
    assert handle.done_event.is_set() is False
    assert handle.question_event.is_set() is False
    assert manager._sessions["sess-retry"] is handle
    assert started == [("sess-retry", None)]


def test_retry_failed_question_accepts_fresh_llm_config():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-retry-llm", trace_id="trace-retry")
    handle.error = "invalid api key"
    handle.error_kind = "auth"
    handle.llm_config_meta = {"requires_reauth": True}
    handle.done_event.set()
    manager._sessions[handle.session_id] = handle
    manager._checkpoint_retryable_question_failure = lambda session_id: True  # type: ignore[attr-defined]
    manager._checkpoint_retryable_evaluator_failure = lambda session_id: False  # type: ignore[attr-defined]
    manager._wait_until_idle = lambda _handle: True  # type: ignore[method-assign]
    manager._start_segment = lambda _handle, stream_input: True  # type: ignore[method-assign]
    manager._mark_retry_running = lambda _session_id: None  # type: ignore[method-assign]
    llm_config = {
        "provider": "qwen",
        "api_key": "fresh-key",
        "model": "qwen3.6-flash",
    }

    retried = manager.retry_failed_question("sess-retry-llm", llm_config=llm_config)

    assert retried is handle
    assert handle.llm_config == llm_config
    assert handle.llm_config_meta == {
        "provider": "qwen",
        "model": "qwen3.6-flash",
        "requires_reauth": True,
    }
    assert handle.error is None
    assert handle.error_kind is None


def test_retry_failed_question_rejects_non_retryable_checkpoint():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    manager._checkpoint_retryable_question_failure = lambda session_id: False  # type: ignore[attr-defined]

    assert manager.retry_failed_question("sess-nope") is None


def test_retry_failed_question_keeps_terminal_error_when_segment_does_not_start():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    handle = SessionHandle(session_id="sess-retry-start-fail", trace_id="trace-retry")
    handle.error = "provider timed out"
    handle.error_kind = "timeout"
    handle.final_state = {"status": "errored", "error": "provider timed out"}  # type: ignore[typeddict-item]
    handle.current_question = {"question": "old question"}
    handle.done_event.set()
    manager._sessions[handle.session_id] = handle
    manager._checkpoint_retryable_question_failure = lambda session_id: True  # type: ignore[attr-defined]
    manager._checkpoint_retryable_evaluator_failure = lambda session_id: False  # type: ignore[attr-defined]
    manager._wait_until_idle = lambda _handle: True  # type: ignore[method-assign]
    manager._start_segment = lambda _handle, stream_input: False  # type: ignore[method-assign]

    marked_running: list[str] = []
    manager._mark_retry_running = marked_running.append  # type: ignore[method-assign]

    assert manager.retry_failed_question("sess-retry-start-fail") is None

    assert handle.error == "provider timed out"
    assert handle.error_kind == "timeout"
    assert handle.final_state == {"status": "errored", "error": "provider timed out"}
    assert handle.current_question == {"question": "old question"}
    assert handle.done_event.is_set()
    assert marked_running == []


def test_can_retry_failed_question_allows_evaluator_checkpoint():
    manager = SessionManager.__new__(SessionManager)

    class _Workflow:
        def get_state(self, _config):
            return SimpleNamespace(
                next=("evaluator",),
                values={
                    "current_question": {"question": "Q"},
                    "current_answer": "candidate answer",
                    "final_report": None,
                },
            )

    manager._workflow = _Workflow()

    assert manager.can_retry_failed_question("sess-eval") is True


def test_retry_failed_question_resumes_evaluator_checkpoint():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    started: list[tuple[str, object]] = []

    manager._checkpoint_retryable_question_failure = lambda session_id: False  # type: ignore[attr-defined]
    manager._checkpoint_retryable_evaluator_failure = lambda session_id: True  # type: ignore[attr-defined]
    manager._load_persisted_session_for_retry = lambda session_id: {  # type: ignore[attr-defined]
        "trace_id": "trace-eval",
        "candidate_name": "Alex",
        "job_title": "Java backend",
        "job_level": "junior",
        "mode": "mixed",
        "turn_idx": 1,
        "asked_turn": 0,
    }

    def fake_start_segment(handle: SessionHandle, stream_input: object) -> None:
        started.append((handle.session_id, stream_input))

    manager._start_segment = fake_start_segment  # type: ignore[method-assign]

    handle = manager.retry_failed_question("sess-eval")

    assert handle is not None
    assert handle.session_id == "sess-eval"
    assert handle.error is None
    assert handle.done_event.is_set() is False
    assert started == [("sess-eval", None)]


def test_recover_waiting_session_rehydrates_question_checkpoint():
    manager = SessionManager.__new__(SessionManager)
    manager._sessions = {}
    manager._lock = threading.Lock()
    persisted: list[tuple[str, int]] = []

    manager._checkpoint_waiting_question = lambda session_id: {  # type: ignore[attr-defined]
        "current_question": {"question": "Tell me about a system."},
        "turn_idx": 2,
    }
    manager._load_persisted_session_for_retry = lambda session_id: {  # type: ignore[attr-defined]
        "trace_id": "trace-waiting",
        "candidate_name": "Alex",
        "job_title": "Java 后端",
        "job_level": "junior",
        "mode": "mixed",
        "turn_idx": 2,
        "asked_turn": 1,
    }

    def fake_persist_interrupt(
        handle: SessionHandle,
        question: dict[str, object],
        turn_idx: int,
    ) -> None:
        persisted.append((question["question"], turn_idx))  # type: ignore[arg-type]

    manager._persist_interrupt = fake_persist_interrupt  # type: ignore[method-assign]

    handle = manager.recover_waiting_session("sess-waiting")

    assert handle is not None
    assert handle.session_id == "sess-waiting"
    assert handle.trace_id == "trace-waiting"
    assert handle.current_question == {"question": "Tell me about a system."}
    assert handle.turn_idx == 2
    assert handle.question_event.is_set()
    assert handle.done_event.is_set() is False
    assert manager._sessions["sess-waiting"] is handle
    assert persisted == [("Tell me about a system.", 2)]
