"""Snapshot guard for the interview LangGraph topology.

The snapshot is captured from the registration helpers, not from a
compiled graph, so this test never initializes the configured
checkpointer.
"""
from __future__ import annotations

from app.engine.workflow import langgraph_workflow

EXPECTED_TOPOLOGY = {
    "nodes": [
        "resume_parse",
        "self_intro_question",
        "self_intro_parse",
        "director_sample",
        "ask_question",
        "wait_answer",
        "skip_question",
        "evaluator",
        "verification",
        "reward_update",
        "turn_finalize",
        "refine_followup",
        "final_report",
        "training_plan",
        "experience_extractor",
    ],
    "edges": [
        {"source": "START", "target": "resume_parse"},
        {"source": "resume_parse", "target": "self_intro_question"},
        {"source": "self_intro_question", "target": "wait_answer"},
        {"source": "self_intro_parse", "target": "director_sample"},
        {"source": "director_sample", "target": "ask_question"},
        {"source": "ask_question", "target": "wait_answer"},
        {"source": "evaluator", "target": "verification"},
        {"source": "verification", "target": "reward_update"},
        {"source": "reward_update", "target": "turn_finalize"},
        {"source": "refine_followup", "target": "director_sample"},
        {"source": "final_report", "target": "training_plan"},
        {"source": "training_plan", "target": "experience_extractor"},
        {"source": "experience_extractor", "target": "END"},
    ],
    "conditional_edges": [
        {
            "source": "wait_answer",
            "router": "route_after_wait",
            "branches": {
                "self_intro_parse": "self_intro_parse",
                "skip_question": "skip_question",
                "evaluator": "evaluator",
                "end": "final_report",
            },
        },
        {
            "source": "skip_question",
            "router": "route_after_skip",
            "branches": {
                "next_question": "director_sample",
                "end": "final_report",
            },
        },
        {
            "source": "turn_finalize",
            "router": "route_after_eval",
            "branches": {
                "refine": "refine_followup",
                "next_question": "director_sample",
                "end": "final_report",
            },
        },
    ],
}


def test_workflow_topology_snapshot_matches_registered_graph(
    monkeypatch,
) -> None:
    def fail_if_compiling_graph() -> object:
        raise AssertionError("topology snapshot must not compile the graph")

    monkeypatch.setattr(
        langgraph_workflow,
        "_default_checkpointer",
        fail_if_compiling_graph,
    )

    assert hasattr(langgraph_workflow, "workflow_topology_snapshot")
    assert langgraph_workflow.workflow_topology_snapshot() == EXPECTED_TOPOLOGY
