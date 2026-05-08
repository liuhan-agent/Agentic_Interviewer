from __future__ import annotations

import os

from app.scripts.smoke_p0_runtime import (
    _force_offline_runtime,
    _install_offline_vectorstore,
    collect_smoke_errors,
)


def _valid_demo_result() -> dict:
    return {
        "session_id": "demo-abc123",
        "state": {
            "qa_history": [
                {"turn_idx": 0, "question": "Q1", "answer": "A1"},
                {"turn_idx": 1, "question": "Q2", "answer": "A2"},
            ],
            "final_report": {
                "overall_score": 7.4,
                "training_plan": {"source": "stub"},
                "workflow_artifacts": {
                    "latest_ask_plan": {"template": "adaptive"},
                    "latest_contract": {"signed_by": "evaluator"},
                    "latest_verification": None,
                },
            },
        },
    }


def test_collect_smoke_errors_accepts_complete_demo_result() -> None:
    assert collect_smoke_errors(_valid_demo_result(), min_turns=2) == []


def test_collect_smoke_errors_reports_missing_runtime_signals() -> None:
    result = _valid_demo_result()
    state = result["state"]
    state["qa_history"] = []
    state["final_report"] = {}

    errors = collect_smoke_errors(result, min_turns=2)

    assert "qa_history has 0 turns, expected at least 2" in errors
    assert "final_report.overall_score missing or non-numeric" in errors
    assert "final_report.training_plan missing" in errors
    assert "workflow_artifacts.latest_ask_plan missing" in errors


def test_force_offline_runtime_uses_memory_checkpoint(monkeypatch) -> None:
    monkeypatch.setenv("CHECKPOINT_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://example")

    _force_offline_runtime()

    assert os.environ["LLM_PROVIDER"] == "stub"
    assert os.environ["EMBEDDING_PROVIDER"] == "stub"
    assert os.environ["CHECKPOINT_BACKEND"] == "memory"
    assert os.environ["DATABASE_URL"] == "sqlite:///:memory:"


def test_install_offline_vectorstore_uses_shared_memory_store() -> None:
    from app.engine.rag import ingestion
    from app.engine.rag import retriever
    from app.scripts import run_demo

    original_ingestion_get_vectorstore = ingestion.get_vectorstore
    original_retriever_get_vectorstore = retriever.get_vectorstore
    original_run_demo_get_vectorstore = run_demo.get_vectorstore
    try:
        _install_offline_vectorstore()

        store = run_demo.get_vectorstore()
        assert ingestion.get_vectorstore() is store
        assert retriever.get_vectorstore() is store

        store.add(["python observability"], [{"source": "test.md", "chunk": 0}])
        assert ingestion.get_vectorstore().count() == 1
        assert retriever.get_vectorstore().count() == 1
    finally:
        ingestion.get_vectorstore = original_ingestion_get_vectorstore
        retriever.get_vectorstore = original_retriever_get_vectorstore
        run_demo.get_vectorstore = original_run_demo_get_vectorstore
