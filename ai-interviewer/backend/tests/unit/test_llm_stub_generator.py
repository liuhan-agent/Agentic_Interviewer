from __future__ import annotations

import json

from app.engine.agents.llm_client import ChatMessage, _stub_response


def test_generator_stub_uses_prompt_dimension_anchor_and_target_skills() -> None:
    raw = _stub_response(
        [
            ChatMessage(
                "user",
                '\n'.join(
                    [
                        '  "dimension": "technical_depth",',
                        "TARGET_DIFFICULTY = hard",
                        'TARGET_SKILLS = ["redis", "kafka"]',
                        'RESUME_ANCHOR = {"project_name": "Order System"}',
                    ]
                ),
            )
        ],
        json_mode=True,
        agent_role="generator",
    )

    data = json.loads(raw)

    assert data["dimension"] == "technical_depth"
    assert "Order System" in data["question"]
    assert "redis" in data["question"].lower()
    assert "请结合" in data["question"]
    assert "技术挑战" in data["question"]
    assert "walk me through" not in data["question"].lower()
    assert "what did you" not in data["question"].lower()
    assert data["difficulty"] == "hard"


def test_evaluator_stub_uses_chinese_candidate_feedback() -> None:
    raw = _stub_response(
        [ChatMessage("user", "CANDIDATE_ANSWER = 我用 Redis 和 Lua 保证扣减原子性。")],
        json_mode=True,
        agent_role="evaluator",
    )

    data = json.loads(raw)

    assert data["strengths"]
    assert data["weaknesses"]
    assert all("stub" not in item.lower() for item in data["strengths"])
    assert any("\u4e00" <= char <= "\u9fff" for item in data["strengths"] for char in item)
    assert any("\u4e00" <= char <= "\u9fff" for item in data["weaknesses"] for char in item)
