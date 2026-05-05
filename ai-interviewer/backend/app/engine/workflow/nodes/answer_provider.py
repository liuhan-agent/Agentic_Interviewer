"""Answer provider abstraction.

``wait_answer_node`` needs to be able to obtain the candidate's answer
in three very different transport contexts:

1. CLI demo -> a scripted list of canned answers
2. REST API -> an answer posted by the client to ``/sessions/{id}/answer``
3. WebSocket voice -> a Whisper transcript delivered asynchronously

Rather than having the node hard-code any of those, it asks whatever
provider was registered for the current session. The registry lives
outside the LangGraph state on purpose: providers hold local resources
(threads, sockets, queues) that are not JSON/msgpack serialisable and
must not be checkpointed.
"""
from __future__ import annotations

import threading
from typing import Protocol

ANSWER_PROVIDER_KEY = "_answer_provider_session_id"


class ProviderCancelledError(Exception):
    """Raised by a provider when the session has been cancelled.

    The synchronous branch of ``wait_answer_node`` catches this and
    short-circuits the graph to ``final_report`` via the
    ``status=cancelled`` state marker. Using a dedicated exception (not
    ``KeyboardInterrupt`` or a sentinel string) keeps the intent
    explicit and avoids colliding with valid empty-string answers.
    """


# Backwards-compatible alias for readability at call sites that
# originally imported ``ProviderCancelled``. Both names point at the
# same class so ``except ProviderCancelled`` keeps working.
ProviderCancelled = ProviderCancelledError


class AnswerProvider(Protocol):
    """Strategy used by ``wait_answer_node``."""

    def get(self, turn_idx: int, question: dict) -> str: ...  # pragma: no cover


class StaticAnswerProvider:
    """Plays back a fixed list of answers; loops or pads with a default."""

    def __init__(self, answers: list[str], *, default: str = "I'm not sure.") -> None:
        self._answers = list(answers)
        self._default = default

    def get(self, turn_idx: int, question: dict) -> str:
        if not self._answers:
            return self._default
        idx = turn_idx % len(self._answers)
        return self._answers[idx]


class QueueAnswerProvider:
    """Thread-safe queue used by the REST/WS layer to push answers in.

    Cancellation model
    ------------------
    A background workflow thread sits in ``get`` until either an
    answer is submitted or ``cancel`` is called. Before the fix this
    loop was effectively unbounded: a client disconnect at the API /
    WebSocket layer left the thread blocked forever, leaking state
    and never firing the manager's ``done_event``. ``cancel`` now
    flips a flag and notifies all waiters so ``get`` can surface a
    ``ProviderCancelled`` without relying on a sentinel answer.
    """

    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._pending: dict[int, str] = {}
        self._cancelled = False

    def submit(self, turn_idx: int, answer: str) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._pending[turn_idx] = answer
            self._lock.notify_all()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._lock.notify_all()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def get(self, turn_idx: int, question: dict) -> str:
        with self._lock:
            while turn_idx not in self._pending:
                if self._cancelled:
                    raise ProviderCancelledError(
                        f"session cancelled while waiting for turn={turn_idx}"
                    )
                self._lock.wait(timeout=60.0)
            return self._pending.pop(turn_idx)


_registry: dict[str, AnswerProvider] = {}
_registry_lock = threading.Lock()


def register_provider(session_id: str, provider: AnswerProvider) -> None:
    """Attach a provider to a session.

    Call this *before* ``workflow.invoke``. The provider is looked up
    by ``session_id`` inside ``wait_answer_node`` and kept out of the
    graph state so the checkpointer can serialise everything else.
    """
    with _registry_lock:
        _registry[session_id] = provider


def get_provider(session_id: str) -> AnswerProvider | None:
    with _registry_lock:
        return _registry.get(session_id)


def unregister_provider(session_id: str) -> None:
    with _registry_lock:
        _registry.pop(session_id, None)
