"""Regression tests for the ``QueueAnswerProvider`` cancellation path.

Before this fix ``get()`` could block forever if a WebSocket client
disconnected before submitting an answer: the inner ``while`` loop
looped on every wakeup regardless of whether anything had changed.
``cancel()`` is the escape hatch - waking every waiter with a
``ProviderCancelled`` instead of an answer so the workflow thread
can exit instead of leaking.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.engine.workflow.nodes.answer_provider import (
    ProviderCancelled,
    QueueAnswerProvider,
)


def test_get_returns_submitted_answer():
    p = QueueAnswerProvider()
    p.submit(0, "hello")
    assert p.get(0, {"question": "q"}) == "hello"


def test_get_raises_when_cancelled_before_submit():
    p = QueueAnswerProvider()

    errors: list[BaseException] = []
    done = threading.Event()

    def _worker():
        try:
            p.get(0, {"question": "q"})
        except BaseException as e:
            errors.append(e)
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    # Give the waiter a moment to park in the Condition.
    time.sleep(0.05)
    p.cancel()

    assert done.wait(timeout=2.0), "provider.get did not return after cancel()"
    assert len(errors) == 1
    assert isinstance(errors[0], ProviderCancelled)


def test_cancel_is_idempotent_and_submit_is_noop_after_cancel():
    p = QueueAnswerProvider()
    p.cancel()
    p.cancel()
    # submit() after cancel must be a silent no-op; the workflow thread
    # is expected to have already exited via ProviderCancelled.
    p.submit(0, "late")
    with pytest.raises(ProviderCancelled):
        p.get(0, {"question": "q"})
    assert p.cancelled is True
