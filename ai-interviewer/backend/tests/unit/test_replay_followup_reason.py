from __future__ import annotations

from app.engine.workflow.followup_reason import (
    attach_replay_followup_reason,
    build_replay_followup_reason,
    sanitize_replay_followup_reason,
)


def test_refine_evaluation_builds_display_followup_reason() -> None:
    reason = build_replay_followup_reason(
        {
            "recommended_next": "refine",
            "recommended_next_plan": "deep_probe",
            "recommended_probe_intent": "metric_probe",
            "failure_reason": "容量估算缺少峰值和 key/value 估算",
            "weaknesses": ["容量估算不够具体"],
            "rubric_coverage": {
                "缓存淘汰": "covered",
                "容量估算": "missing",
            },
        }
    )

    assert reason is not None
    assert reason["title"] == "为什么继续追问"
    assert reason["source"] == "evaluator"
    assert "容量估算" in reason["summary"]
    assert "深挖追问" in reason["chips"]
    assert "量化指标" in reason["chips"]
    assert 2 <= len(reason["chips"]) <= 4
    assert "deep_probe" not in str(reason)
    assert "metric_probe" not in str(reason)


def test_advance_and_fallback_do_not_build_followup_reason() -> None:
    assert (
        build_replay_followup_reason(
            {
                "recommended_next": "advance",
                "recommended_next_plan": "deep_probe",
                "recommended_probe_intent": "metric_probe",
            }
        )
        is None
    )

    assert (
        build_replay_followup_reason(
            {
                "source": "fallback",
                "fallback_reason": "llm_failed",
                "recommended_next": "refine",
                "recommended_next_plan": "deep_probe",
                "weaknesses": ["Evaluator LLM unavailable."],
            }
        )
        is None
    )


def test_attach_followup_reason_removes_stale_non_refine_reason() -> None:
    evaluation = {
        "recommended_next": "advance",
        "followup_reason": {
            "title": "为什么继续追问",
            "summary": "旧的追问说明不应继续保留。",
            "chips": ["继续追问"],
            "source": "evaluator",
        },
    }

    out = attach_replay_followup_reason(evaluation)

    assert out is not evaluation
    assert "followup_reason" not in out


def test_sanitize_followup_reason_rejects_malformed_payload() -> None:
    assert sanitize_replay_followup_reason({"summary": "缺 chips"}) is None
    assert (
        sanitize_replay_followup_reason(
            {
                "title": "为什么继续追问",
                "summary": "说明",
                "chips": "不是数组",
                "source": "evaluator",
            }
        )
        is None
    )
    assert (
        sanitize_replay_followup_reason(
            {
                "title": "为什么继续追问",
                "summary": "说明",
                "chips": ["补充证据"],
                "source": "internal",
            }
        )
        is None
    )
