from __future__ import annotations

import threading
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import interview as interview_api
from app.core.idempotency import reset_idempotency_store
from app.core.session_auth import hash_session_token


class _Handle:
    trace_id = "trace-auth"
    done_event: threading.Event
    final_state: dict[str, Any] | None
    cancelled = False
    error = None
    error_kind = None
    current_question = {"question": "Q", "dimension": "technical_depth"}
    turn_idx = 2
    max_turns = 8
    enable_video_analysis = True

    def __init__(self) -> None:
        self.done_event = threading.Event()
        self.final_state = None
        self.session_token_hash = hash_session_token("session-secret")
        self.setup_snapshot = {
            "candidate": {
                "name": "Alex Chen",
                "resume_parsed": {
                    "summary": "Backend engineer.",
                    "skills": ["Python"],
                    "highlights": ["Built streaming systems."],
                    "projects": [],
                    "focus_areas": [],
                    "concerns": [],
                    "candidate_profile": {
                        "education_level": "本科",
                        "school": "Example University",
                    },
                },
            },
            "job_spec": {
                "title": "Backend Engineer",
                "level": "senior",
                "required_skills": ["Python"],
                "rubric_dimensions": ["system_design"],
                "rubric": {},
                "interview_industry": "internet",
                "interview_direction": "python_backend",
                "interview_direction_label": "Python 后端",
            },
        }


class _Manager:
    def __init__(self) -> None:
        self.handle = _Handle()
        self.submitted: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []
        self.hints: list[dict[str, Any]] = []
        self.reauth_required = False

    def get(self, session_id: str) -> _Handle | None:
        return self.handle if session_id == "sess-auth" else None

    def wait_for_next_question(
        self,
        session_id: str,
        timeout: float = 30.0,
    ) -> dict[str, Any] | None:
        return self.handle.current_question

    def submit_answer(
        self,
        session_id: str,
        answer: str,
        *,
        turn_idx: int,
        video_signals: dict[str, Any] | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        if self.reauth_required:
            raise ValueError("llm_config reauth_required")
        if turn_idx != self.handle.turn_idx:
            raise ValueError("turn_idx mismatch")
        self.submitted.append(
            {
                "session_id": session_id,
                "answer": answer,
                "turn_idx": turn_idx,
                "video_signals": video_signals,
                "llm_config": llm_config,
            }
        )

    def skip_question(
        self,
        session_id: str,
        *,
        turn_idx: int,
        reason: str | None = None,
    ) -> None:
        if turn_idx != self.handle.turn_idx:
            raise ValueError("turn_idx mismatch")
        self.skipped.append(
            {"session_id": session_id, "turn_idx": turn_idx, "reason": reason}
        )

    def request_hint(
        self,
        session_id: str,
        *,
        turn_idx: int,
        llm_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if session_id != "sess-auth":
            raise KeyError(session_id)
        if turn_idx != self.handle.turn_idx:
            raise ValueError("turn_idx mismatch")
        if self.reauth_required:
            raise ValueError("llm_config reauth_required")
        self.hints.append(
            {"session_id": session_id, "turn_idx": turn_idx, "llm_config": llm_config}
        )
        return {
            "session_id": session_id,
            "turn_idx": turn_idx,
            "hint": "可以先从目标、约束和验证方式三个角度组织回答。",
            "source": "contract",
        }


def test_compact_dimension_scores_ignores_null_unscored_values() -> None:
    assert interview_api._compact_dimension_scores(
        {
            "technical_depth": {"score": 8.5},
            "project_experience": {"score": None},
            "legacy_zero": {"score": 0.0},
            "raw_number": 7,
        }
    ) == {
        "technical_depth": 8.5,
        "legacy_zero": 0.0,
        "raw_number": 7.0,
    }


class _StubTTS:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def synth(
        self,
        text: str,
        *,
        llm_config: dict[str, Any] | None = None,
    ):
        self.calls.append({"text": text, "llm_config": llm_config})
        yield b"audio-1"
        yield b"audio-2"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _Manager]:
    manager = _Manager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: manager)
    # Idempotency cache is a process-local singleton; reset between
    # cases so a stray hit from a prior test cannot leak into this one.
    reset_idempotency_store()
    app = FastAPI()
    app.include_router(interview_api.router)
    return TestClient(app), manager


def test_session_endpoint_rejects_missing_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get("/api/v1/interview/sessions/sess-auth/question")

    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("method", "suffix", "json_body"),
    [
        ("get", "question", None),
        ("post", "answer", {"answer": "A", "turn_idx": 2}),
        ("get", "resume", None),
    ],
)
def test_session_endpoints_reject_invalid_path_session_id(
    client: tuple[TestClient, _Manager],
    method: str,
    suffix: str,
    json_body: dict[str, Any] | None,
) -> None:
    http, _manager = client
    url = f"/api/v1/interview/sessions/{'x' * 65}/{suffix}"
    kwargs: dict[str, Any] = {"headers": {"X-Session-Token": "session-secret"}}
    if json_body is not None:
        kwargs["json"] = json_body

    resp = getattr(http, method)(url, **kwargs)

    assert resp.status_code == 422


def test_session_endpoint_rejects_illegal_path_session_id(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/bad%20id/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 422


def test_session_endpoint_rejects_wrong_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/question",
        headers={"X-Session-Token": "wrong"},
    )

    assert resp.status_code == 403


def test_session_endpoint_accepts_correct_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/question",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    assert resp.json()["question"] == {"question": "Q", "dimension": "technical_depth"}
    assert resp.json()["max_turns"] == 8
    assert resp.json()["enable_video_analysis"] is True


def test_resume_endpoint_includes_max_turns(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/resume",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    assert resp.json()["max_turns"] == 8
    assert resp.json()["enable_video_analysis"] is True


def test_setup_snapshot_endpoint_returns_live_snapshot(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/setup-snapshot",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-auth",
        **manager.handle.setup_snapshot,
    }


def test_setup_snapshot_endpoint_rejects_wrong_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/setup-snapshot",
        headers={"X-Session-Token": "wrong"},
    )

    assert resp.status_code == 403


def test_setup_snapshot_endpoint_returns_404_when_missing_snapshot(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client
    manager.handle.setup_snapshot = None

    resp = http.get(
        "/api/v1/interview/sessions/sess-auth/setup-snapshot",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 404


def test_voice_ticket_endpoint_requires_session_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post("/api/v1/interview/sessions/sess-auth/voice-ticket")

    assert resp.status_code == 401


def test_voice_ticket_endpoint_issues_short_lived_ticket(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/voice-ticket",
        headers={"X-Session-Token": "session-secret"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["ticket"], str)
    assert body["expires_in_seconds"] > 0


def test_submit_answer_requires_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A"},
    )

    assert resp.status_code == 422


def test_submit_answer_returns_conflict_for_stale_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A", "turn_idx": 1},
    )

    assert resp.status_code == 409
    assert "turn_idx" in resp.text


def test_submit_answer_forwards_turn_idx_and_llm_config(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "A",
            "turn_idx": 2,
            "llm_config": {
                "provider": "qwen",
                "api_key": "secret",
                "model": "qwen3.6-flash",
            },
        },
    )

    assert resp.status_code == 200
    assert manager.submitted == [
        {
            "session_id": "sess-auth",
            "answer": "A",
            "turn_idx": 2,
            "video_signals": None,
            "llm_config": {
                "provider": "qwen",
                "api_key": "secret",
                "model": "qwen3.6-flash",
            },
        }
    ]


def test_submit_answer_returns_structured_reauth_required(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client
    manager.reauth_required = True

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={"answer": "A", "turn_idx": 2},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "error": "reauth_required",
        "message": "This interview needs your personal LLM configuration again.",
    }


def test_skip_question_requires_session_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/skip-question",
        json={"turn_idx": 2},
    )

    assert resp.status_code == 401


def test_skip_question_forwards_turn_idx_and_reason(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/skip-question",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2, "reason": "想先练下一题"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-auth",
        "accepted": True,
        "status": "skipped",
    }
    assert manager.skipped == [
        {"session_id": "sess-auth", "turn_idx": 2, "reason": "想先练下一题"}
    ]


def test_skip_question_returns_conflict_for_stale_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/skip-question",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 1},
    )

    assert resp.status_code == 409
    assert "turn_idx" in resp.text


def test_hint_requires_session_token(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        json={"turn_idx": 2},
    )

    assert resp.status_code == 401


def test_hint_returns_404_for_missing_session(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-missing/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2},
    )

    assert resp.status_code == 404


def test_hint_forwards_turn_idx_and_llm_config(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        headers={"X-Session-Token": "session-secret"},
        json={
            "turn_idx": 2,
            "llm_config": {
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sess-auth",
        "turn_idx": 2,
        "hint": "可以先从目标、约束和验证方式三个角度组织回答。",
        "source": "contract",
    }
    assert manager.hints == [
        {
            "session_id": "sess-auth",
            "turn_idx": 2,
            "llm_config": {
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        }
    ]


def test_hint_rejects_stale_turn_idx(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 1},
    )

    assert resp.status_code == 409
    assert "turn_idx" in resp.text


def test_hint_returns_reauth_required(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client
    manager.reauth_required = True

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/hint",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 2},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "error": "reauth_required",
        "message": "This interview needs your personal LLM configuration again.",
    }


def test_submit_answer_rejects_text_above_max_length(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "x" * (interview_api.ANSWER_TEXT_MAX_LENGTH + 1),
            "turn_idx": 2,
        },
    )

    assert resp.status_code == 422
    assert manager.submitted == []


def test_submit_answer_accepts_answer_at_max_length(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "x" * interview_api.ANSWER_TEXT_MAX_LENGTH,
            "turn_idx": 2,
        },
    )

    assert resp.status_code == 200
    assert len(manager.submitted) == 1
    assert manager.submitted[0]["video_signals"] is None


def test_submit_answer_accepts_qwen_voice_realtime_overrides(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "ok",
            "turn_idx": 2,
            "llm_config": {
                "provider": "qwen",
                "api_key": "dashscope-key",
                "model": "qwen-plus",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "voice_overrides": {
                    "asr": {
                        "provider": "qwen",
                        "api_key": "dashscope-key",
                        "model": "qwen3-asr-flash-realtime",
                        "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                    },
                    "tts": {
                        "provider": "qwen",
                        "api_key": "dashscope-key",
                        "model": "qwen3-tts-flash-realtime",
                        "voice": "Cherry",
                        "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                    },
                },
            },
        },
    )

    assert resp.status_code == 200
    assert manager.submitted[-1]["llm_config"]["voice_overrides"]["asr"][
        "base_url"
    ] == "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


def test_question_audio_uses_tts_voice_override_for_current_turn(
    client: tuple[TestClient, _Manager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http, _manager = client
    tts = _StubTTS()
    monkeypatch.setattr(interview_api, "get_tts", lambda: tts)

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/question-audio",
        headers={"X-Session-Token": "session-secret"},
        json={
            "turn_idx": 2,
            "llm_config": {
                "provider": "qwen",
                "api_key": "dashscope-key",
                "model": "qwen-plus",
                "voice_overrides": {
                    "tts": {
                        "provider": "qwen",
                        "api_key": "dashscope-key",
                        "model": "qwen3-tts-flash-realtime",
                        "voice": "Cherry",
                        "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                    },
                },
            },
        },
    )

    assert resp.status_code == 200
    assert resp.content == b"audio-1audio-2"
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert tts.calls == [
        {
            "text": "Q",
            "llm_config": {
                "provider": "qwen",
                "api_key": "dashscope-key",
                "model": "qwen-plus",
                "voice_overrides": {
                    "tts": {
                        "provider": "qwen",
                        "api_key": "dashscope-key",
                        "model": "qwen3-tts-flash-realtime",
                        "voice": "Cherry",
                        "base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                    }
                },
            },
        }
    ]


def test_question_audio_rejects_stale_turn(
    client: tuple[TestClient, _Manager],
) -> None:
    http, _manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/question-audio",
        headers={"X-Session-Token": "session-secret"},
        json={"turn_idx": 1},
    )

    assert resp.status_code == 409


def test_submit_answer_accepts_valid_video_signals(
    client: tuple[TestClient, _Manager],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "ok",
            "turn_idx": 2,
            "video_signals": {
                "confidence": 0.7,
                "engagement": 0.5,
                "dominant_emotion": "positive",
                "sample_count": 12,
            },
        },
    )

    assert resp.status_code == 200
    assert manager.submitted[-1]["video_signals"] == {
        "confidence": 0.7,
        "engagement": 0.5,
        "dominant_emotion": "positive",
        "sample_count": 12,
    }


@pytest.mark.parametrize(
    "video_signals",
    [
        # missing required field
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
        },
        # confidence out of range
        {
            "confidence": 1.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 5,
        },
        # invalid emotion enum
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "angry",
            "sample_count": 5,
        },
        # extra field forbidden
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 5,
            "attention_score": 0.9,
        },
        # sample_count zero
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 0,
        },
    ],
)
def test_submit_answer_drops_invalid_video_signals(
    client: tuple[TestClient, _Manager],
    video_signals: dict[str, Any],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "ok",
            "turn_idx": 2,
            "video_signals": video_signals,
        },
    )

    assert resp.status_code == 200
    assert manager.submitted[-1]["answer"] == "ok"
    assert manager.submitted[-1]["video_signals"] is None


_IDEM_KEY = "idem-550e8400-e29b-41d4-a716-446655440000"


def test_submit_answer_replays_cached_response_for_same_idempotency_key(
    client: tuple[TestClient, _Manager],
) -> None:
    """Two identical POSTs with the same Idempotency-Key must produce
    one manager.submit_answer call and one identical response. This
    rescues clients that lost the network response on the first try."""
    http, manager = client

    payload = {"answer": "first answer", "turn_idx": 2}
    headers = {
        "X-Session-Token": "session-secret",
        "Idempotency-Key": _IDEM_KEY,
    }

    first = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json=payload,
    )
    second = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert len(manager.submitted) == 1


def test_submit_answer_returns_409_for_idempotency_key_with_mutated_body(
    client: tuple[TestClient, _Manager],
) -> None:
    """Replay-with-mutation is unsafe — surfacing 409 forces the client
    to either keep the body identical or rotate the key."""
    http, manager = client

    headers = {
        "X-Session-Token": "session-secret",
        "Idempotency-Key": _IDEM_KEY,
    }

    first = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json={"answer": "first", "turn_idx": 2},
    )
    second = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json={"answer": "DIFFERENT body", "turn_idx": 2},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "idempotency_conflict"
    assert len(manager.submitted) == 1


def test_submit_answer_without_idempotency_key_keeps_legacy_behaviour(
    client: tuple[TestClient, _Manager],
) -> None:
    """A client that does not opt into Idempotency-Key keeps the original
    submit semantics: each POST is forwarded verbatim, and a stale
    turn_idx still bubbles up as 409 from the manager."""
    http, manager = client

    headers = {"X-Session-Token": "session-secret"}
    accepted = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json={"answer": "first", "turn_idx": 2},
    )
    assert accepted.status_code == 200
    assert len(manager.submitted) == 1

    # Same body, no Idempotency-Key — manager call repeats and the stale
    # turn_idx assertion still fires.
    repeat = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json={"answer": "first", "turn_idx": 2},
    )
    # The stub manager doesn't model the post-submit turn_idx advance,
    # so a same-body resubmit still succeeds; the key point is that we
    # called submit_answer twice (no cache short-circuit).
    assert repeat.status_code == 200
    assert len(manager.submitted) == 2


def test_submit_answer_treats_too_short_idempotency_key_as_disabled(
    client: tuple[TestClient, _Manager],
) -> None:
    """A throwaway key (e.g. ``Idempotency-Key: x``) silently disables
    the cache rather than activating it on noise."""
    http, manager = client

    headers = {
        "X-Session-Token": "session-secret",
        "Idempotency-Key": "short",
    }

    first = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json={"answer": "first", "turn_idx": 2},
    )
    second = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers=headers,
        json={"answer": "first", "turn_idx": 2},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(manager.submitted) == 2


# ---------------------------------------------------------------------------
# Auth coverage scan: every /sessions/{id}/... route must reject requests
# that are missing the X-Session-Token header. This is a "guardrail" test
# rather than a behaviour test — it makes sure that future routes added
# under /sessions/{id} cannot accidentally ship without an auth check.
# ---------------------------------------------------------------------------


_SESSION_ROUTE_AUTH_CASES: list[dict[str, Any]] = [
    {
        "id": "GET /question",
        "method": "get",
        "url": "/api/v1/interview/sessions/sess-auth/question",
        "json": None,
        "params": None,
    },
    {
        "id": "POST /voice-ticket",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/voice-ticket",
        "json": None,
        "params": None,
    },
    {
        "id": "POST /question-audio",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/question-audio",
        "json": {"turn_idx": 2},
        "params": None,
    },
    {
        "id": "POST /answer",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/answer",
        "json": {"answer": "A", "turn_idx": 2},
        "params": None,
    },
    {
        "id": "POST /skip-question",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/skip-question",
        "json": {"turn_idx": 2},
        "params": None,
    },
    {
        "id": "POST /hint",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/hint",
        "json": {"turn_idx": 2},
        "params": None,
    },
    {
        "id": "POST /retry-question",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/retry-question",
        "json": None,
        "params": None,
    },
    {
        "id": "POST /claim",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/claim",
        "json": None,
        "params": None,
    },
    {
        "id": "DELETE /sessions/{id}",
        "method": "delete",
        "url": "/api/v1/interview/sessions/sess-auth",
        "json": None,
        "params": {"confirm_session_id": "sess-auth"},
    },
    {
        "id": "POST /feedback",
        "method": "post",
        "url": "/api/v1/interview/sessions/sess-auth/feedback",
        "json": {"outcome": "got_offer"},
        "params": None,
    },
    {
        "id": "GET /report",
        "method": "get",
        "url": "/api/v1/interview/sessions/sess-auth/report",
        "json": None,
        "params": None,
    },
    {
        "id": "GET /replay",
        "method": "get",
        "url": "/api/v1/interview/sessions/sess-auth/replay",
        "json": None,
        "params": None,
    },
    {
        "id": "GET /resume",
        "method": "get",
        "url": "/api/v1/interview/sessions/sess-auth/resume",
        "json": None,
        "params": None,
    },
    {
        "id": "GET /metadata",
        "method": "get",
        "url": "/api/v1/interview/sessions/sess-auth/metadata",
        "json": None,
        "params": None,
    },
    {
        "id": "GET /setup-snapshot",
        "method": "get",
        "url": "/api/v1/interview/sessions/sess-auth/setup-snapshot",
        "json": None,
        "params": None,
    },
]


@pytest.mark.parametrize(
    "case",
    _SESSION_ROUTE_AUTH_CASES,
    ids=[case["id"] for case in _SESSION_ROUTE_AUTH_CASES],
)
def test_every_session_route_rejects_missing_token(
    client: tuple[TestClient, _Manager],
    case: dict[str, Any],
) -> None:
    """Coverage scan: every ``/api/v1/interview/sessions/{id}/...`` route
    must surface ``401`` when the client did not send an
    ``X-Session-Token`` header.

    This test is the safety net for future routes added under
    ``/sessions/{id}``: forgetting ``_require_session_access`` will fail
    here long before it reaches a code review."""
    http, _manager = client
    request_kwargs: dict[str, Any] = {}
    if case["json"] is not None:
        request_kwargs["json"] = case["json"]
    if case["params"] is not None:
        request_kwargs["params"] = case["params"]

    resp = getattr(http, case["method"])(case["url"], **request_kwargs)

    assert resp.status_code == 401, (
        f"{case['id']} returned {resp.status_code}; expected 401 when "
        "X-Session-Token is missing. Body: " + resp.text[:200]
    )


def test_session_route_auth_scan_includes_all_session_id_routes() -> None:
    """If a new route is added under ``/sessions/{session_id}``, this test
    fails until ``_SESSION_ROUTE_AUTH_CASES`` is updated. That keeps the
    coverage scan honest as the API evolves."""
    session_id_routes: set[tuple[str, str]] = set()
    for route in interview_api.router.routes:
        path = getattr(route, "path", "")
        if "{session_id}" not in path:
            continue
        for method in getattr(route, "methods", set()) or set():
            method_normalised = method.lower()
            if method_normalised in {"head", "options"}:
                continue
            if path.endswith("/recover"):
                # Recovery intentionally cannot require the short
                # X-Session-Token because it exists to mint a fresh one
                # after the browser lost sessionStorage. Dedicated
                # recovery-token tests cover that auth boundary.
                continue
            session_id_routes.add((method_normalised, path))

    covered: set[tuple[str, str]] = set()
    for case in _SESSION_ROUTE_AUTH_CASES:
        # Normalise the test URL against the live router path so a
        # template change (e.g. ``{id}`` → ``{session_id}``) surfaces here
        # instead of silently bypassing the scan.
        templated = case["url"].replace("sess-auth", "{session_id}")
        covered.add((case["method"], templated))

    missing = session_id_routes - covered
    assert not missing, (
        "Routes added under /sessions/{session_id} without entries in "
        f"_SESSION_ROUTE_AUTH_CASES: {sorted(missing)}"
    )


def test_submit_answer_idempotency_isolates_across_sessions(
    client: tuple[TestClient, _Manager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cache is keyed by ``(session_id, idempotency_key)``: the same
    key reused on a different session must not leak the cached response
    between unrelated interviews."""
    http, _manager = client

    other_handle = _Handle()
    other_handle.session_token_hash = hash_session_token("other-secret")

    class _DualManager(_Manager):
        def get(self, session_id: str) -> _Handle | None:
            if session_id == "sess-auth":
                return self.handle
            if session_id == "sess-other":
                return other_handle
            return None

    dual = _DualManager()
    monkeypatch.setattr(interview_api, "get_session_manager", lambda: dual)

    first = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={
            "X-Session-Token": "session-secret",
            "Idempotency-Key": _IDEM_KEY,
        },
        json={"answer": "from sess-auth", "turn_idx": 2},
    )
    second = http.post(
        "/api/v1/interview/sessions/sess-other/answer",
        headers={
            "X-Session-Token": "other-secret",
            "Idempotency-Key": _IDEM_KEY,
        },
        json={"answer": "from sess-other", "turn_idx": 2},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    # Each call produced a fresh manager.submit_answer (no cross-session
    # cache reuse).
    assert len(dual.submitted) == 2
    answers = {entry["answer"] for entry in dual.submitted}
    assert answers == {"from sess-auth", "from sess-other"}
