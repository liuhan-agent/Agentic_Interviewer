from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.models import base


def test_init_db_adds_durable_hitl_columns_to_existing_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / "interviewer.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE interview_sessions (
                    session_id VARCHAR(64) PRIMARY KEY,
                    trace_id VARCHAR(64),
                    candidate_name VARCHAR(128),
                    job_title VARCHAR(128),
                    job_level VARCHAR(32),
                    mode VARCHAR(32),
                    status VARCHAR(32),
                    final_report JSON,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )

    monkeypatch.setattr(base, "_engine", engine)
    base.SessionLocal.configure(bind=engine)

    base.init_db()

    columns = {col["name"] for col in inspect(engine).get_columns("interview_sessions")}
    assert {
        "session_token_hash",
        "owner_user_id",
        "owner_claimed_at",
        "current_question",
        "llm_config_meta",
        "turn_idx",
        "asked_turn",
        "enable_video_analysis",
    } <= columns

    tables = set(inspect(engine).get_table_names())
    assert "user_credit_accounts" in tables
    assert "user_credit_ledger" in tables
    assert "user_credit_requests" in tables
