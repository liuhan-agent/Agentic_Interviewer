from __future__ import annotations

from types import SimpleNamespace

from app.services import resume_vector_jobs as jobs


class _ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return SimpleNamespace()


class _HoldingExecutor:
    def __init__(self) -> None:
        self.submitted: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))
        return SimpleNamespace()


def setup_function() -> None:
    jobs._reset_resume_vector_jobs_for_tests()


def teardown_function() -> None:
    jobs._reset_resume_vector_jobs_for_tests()


def test_start_resume_vector_job_dedupes_by_session_and_source(monkeypatch) -> None:
    executor = _HoldingExecutor()
    monkeypatch.setattr(jobs, "_EXECUTOR", executor)

    first = jobs.start_resume_vector_job(
        session_id="sess_a",
        resume_source_id="artifact_1",
        parsed={"summary": "Redis"},
        embedding_override={"provider": "qwen", "api_key": "sk-a"},
    )
    second = jobs.start_resume_vector_job(
        session_id="sess_a",
        resume_source_id="artifact_1",
        parsed={"summary": "Redis"},
        embedding_override={"provider": "qwen", "api_key": "sk-a"},
    )

    assert first["status"] == "pending_background"
    assert second["status"] == "pending_background"
    assert len(executor.submitted) == 1


def test_background_job_uses_embedding_override(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(jobs, "_EXECUTOR", _ImmediateExecutor())
    monkeypatch.setattr(
        jobs,
        "consume_resume_parse_artifact",
        lambda source_id: SimpleNamespace(
            artifact_id=source_id,
            redacted_text="Redis Lua project",
            parsed={"summary": "artifact"},
        ),
    )

    def fake_vectorize_resume(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ready",
            "source_type": "resume",
            "resume_revision_id": kwargs["resume_revision_id"],
            "source_artifact_id": kwargs["source_artifact_id"],
            "chunk_count": 3,
        }

    monkeypatch.setattr(jobs, "vectorize_resume", fake_vectorize_resume)
    override = {
        "provider": "qwen",
        "api_key": "sk-browser",
        "model": "text-embedding-v4",
        "dimensions": 1536,
    }

    status = jobs.wait_for_resume_vector_status(
        session_id="sess_a",
        resume_source_id="artifact_1",
        parsed={"summary": "candidate"},
        embedding_override=override,
        timeout_ms=100,
    )

    assert status["status"] == "ready"
    assert status["resume_revision_id"]
    assert captured["embedding_override"] == override
    assert captured["parsed"] == {"summary": "candidate"}
    assert captured["source_artifact_id"] == "artifact_1"


def test_background_job_returns_skipped_when_artifact_missing(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "_EXECUTOR", _ImmediateExecutor())
    monkeypatch.setattr(jobs, "consume_resume_parse_artifact", lambda _source_id: None)

    status = jobs.wait_for_resume_vector_status(
        session_id="sess_a",
        resume_source_id="missing",
        parsed={},
        timeout_ms=100,
    )

    assert status["status"] == "skipped"
    assert status["skipped_reason"] == "parse_artifact_missing_or_expired"
    assert status["resume_source_id"] == "missing"


def test_background_job_binds_cached_resume_without_vectorizing(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(jobs, "_EXECUTOR", _ImmediateExecutor())
    monkeypatch.setattr(
        jobs,
        "consume_resume_parse_artifact",
        lambda source_id: SimpleNamespace(
            artifact_id=source_id,
            redacted_text="Redis Lua project",
            parsed={"projects": [{"name": "Coupon"}]},
        ),
    )
    monkeypatch.setattr(
        jobs,
        "current_embedding_model_version",
        lambda _override=None: "qwen:text-embedding-v4:1536@v1",
    )

    def fake_bind(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ready",
            "source_type": "resume",
            "resume_revision_id": kwargs["resume_revision_id"],
            "source_artifact_id": kwargs["source_artifact_id"],
            "resume_source_id": kwargs["source_artifact_id"],
            "embedding_model_version": kwargs["embedding_model_version"],
            "chunk_count": 2,
            "cache_hit": True,
            "source_cache_key": kwargs["cache_key"],
        }

    monkeypatch.setattr(jobs, "try_bind_cached_resume_anchors", fake_bind)
    monkeypatch.setattr(
        jobs,
        "vectorize_resume",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache hit must not vectorize")
        ),
    )

    status = jobs.wait_for_resume_vector_status(
        session_id="sess_a",
        resume_source_id="artifact_1",
        parsed={"projects": [{"name": "Coupon"}]},
        timeout_ms=100,
    )

    assert status["status"] == "ready"
    assert status["cache_hit"] is True
    assert captured["session_id"] == "sess_a"
    assert captured["source_artifact_id"] == "artifact_1"
    assert captured["embedding_model_version"] == "qwen:text-embedding-v4:1536@v1"
    assert captured["cache_key"]


def test_background_job_cache_miss_vectorizes_with_cache_key(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(jobs, "_EXECUTOR", _ImmediateExecutor())
    monkeypatch.setattr(
        jobs,
        "consume_resume_parse_artifact",
        lambda source_id: SimpleNamespace(
            artifact_id=source_id,
            redacted_text="Redis Lua project",
            parsed={"projects": [{"name": "Coupon"}]},
        ),
    )
    monkeypatch.setattr(
        jobs,
        "current_embedding_model_version",
        lambda _override=None: "qwen:text-embedding-v4:1536@v1",
    )
    monkeypatch.setattr(jobs, "try_bind_cached_resume_anchors", lambda **_kwargs: None)

    def fake_vectorize_resume(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ready",
            "source_type": "resume",
            "resume_revision_id": kwargs["resume_revision_id"],
            "source_artifact_id": kwargs["source_artifact_id"],
            "source_cache_key": kwargs["source_cache_key"],
            "chunk_count": 3,
        }

    monkeypatch.setattr(jobs, "vectorize_resume", fake_vectorize_resume)

    status = jobs.wait_for_resume_vector_status(
        session_id="sess_a",
        resume_source_id="artifact_1",
        parsed={"projects": [{"name": "Coupon"}]},
        timeout_ms=100,
    )

    assert status["status"] == "ready"
    assert status["cache_hit"] is False
    assert status["source_cache_key"] == captured["source_cache_key"]
    assert captured["source_cache_key"]


def test_wait_for_resume_vector_status_marks_timeout(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "_EXECUTOR", _HoldingExecutor())

    status = jobs.wait_for_resume_vector_status(
        session_id="sess_a",
        resume_source_id="artifact_1",
        parsed={},
        timeout_ms=0,
    )

    assert status["status"] == "pending_background"
    assert status["wait_timed_out"] is True
    assert status["wait_timeout_ms"] == 0
