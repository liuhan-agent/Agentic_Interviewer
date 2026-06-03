"""Session trace payload builders shared by admin and owner-facing APIs."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.services.trace_health import classify_trace_health, trace_diagnostics
from app.services.trace_nodes import trace_node_aliases, trace_node_metadata

log = get_logger(__name__)

TraceProjection = Literal["admin", "owner"]

_OWNER_NODE_INTERNAL_KEYS = {
    "action_id",
    "policy_id",
    "context_key",
    "policy_context_keys",
    "immediate_reward",
    "immediate_reward_applied",
    "langsmith_run_id",
}

_OWNER_PAYLOAD_ALLOWLIST = {
    "workflow_node",
    "semantic_node",
    "node_aliases",
    "display_name_zh",
    "display_description_zh",
    "phase",
    "reason",
    "next_step",
}


def _langsmith_web_url(api_endpoint: str | None) -> str:
    endpoint = (api_endpoint or "").strip().strip('"').strip("'").rstrip("/")
    if not endpoint:
        return "https://smith.langchain.com"

    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return "https://smith.langchain.com"

    path = parsed.path or ""
    if path.endswith("/api/v1"):
        return urlunparse(
            parsed._replace(path=path[: -len("/api/v1")] or "", query="", fragment="")
        )
    if path.endswith("/api"):
        return urlunparse(
            parsed._replace(path=path[: -len("/api")] or "", query="", fragment="")
        )

    netloc = parsed.netloc.lower()
    if netloc.startswith("eu."):
        return "https://eu.smith.langchain.com"
    if netloc.startswith("aws."):
        return "https://aws.smith.langchain.com"
    if netloc.startswith("dev."):
        return "https://dev.smith.langchain.com"
    if netloc.startswith("beta."):
        return "https://beta.smith.langchain.com"
    return "https://smith.langchain.com"


def langsmith_admin_meta() -> dict[str, Any]:
    settings = get_settings()
    return {
        "tracing_enabled": bool(getattr(settings, "langsmith_tracing", False)),
        "project": getattr(
            settings,
            "effective_langsmith_project",
            getattr(settings, "langsmith_project", "agentic-interviewer"),
        ),
        "web_url": _langsmith_web_url(getattr(settings, "langsmith_endpoint", None)),
    }


def answer_excerpt(value: Any, *, limit: int = 220) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def trace_skill_display_lookup(sess: Any) -> dict[str, dict[str, str]]:
    try:
        from app.models.skill_playbook import SkillPlaybookCard

        rows = (
            sess.query(
                SkillPlaybookCard.id,
                SkillPlaybookCard.name,
                SkillPlaybookCard.display_name_zh,
                SkillPlaybookCard.display_description_zh,
            )
            .filter(SkillPlaybookCard.status != "archived")
            .all()
        )
    except Exception as exc:  # pragma: no cover - observability remains best-effort
        log.debug("trace skill display lookup unavailable: %s", exc)
        return {}

    lookup: dict[str, dict[str, str]] = {}
    for row in rows:
        if isinstance(row, (tuple, list)) and len(row) < 4:
            continue
        mapping = getattr(row, "_mapping", None)
        card_id = (
            mapping.get("id") if mapping is not None else getattr(row, "id", None)
        )
        name = (
            mapping.get("name") if mapping is not None else getattr(row, "name", None)
        )
        display_name_zh = (
            mapping.get("display_name_zh")
            if mapping is not None
            else getattr(row, "display_name_zh", "")
        )
        display_description_zh = (
            mapping.get("display_description_zh")
            if mapping is not None
            else getattr(row, "display_description_zh", "")
        )
        display = {
            "display_name_zh": str(display_name_zh or ""),
            "display_description_zh": str(display_description_zh or ""),
        }
        keys = [card_id, name, f"{card_id}.md" if card_id else ""]
        for key in keys:
            normalized = str(key or "").strip()
            if normalized:
                lookup[normalized] = display
    return lookup


def _enrich_trace_skill_display_fields(
    payload: dict[str, Any],
    skill_display_lookup: Mapping[str, Mapping[str, str]] | None,
) -> dict[str, Any]:
    if not skill_display_lookup:
        return payload

    artifacts = payload.get("selection_artifacts")
    if not isinstance(artifacts, dict):
        return payload
    skills = artifacts.get("skills")
    if not isinstance(skills, dict):
        return payload
    refs = skills.get("refs")
    if not isinstance(refs, list) or not refs:
        return payload

    enriched = deepcopy(payload)
    enriched_refs = (
        enriched.get("selection_artifacts", {})
        .get("skills", {})
        .get("refs", [])
    )
    for ref in enriched_refs:
        if not isinstance(ref, dict):
            continue
        candidates = (
            ref.get("id"),
            ref.get("skill_id"),
            ref.get("filename"),
            ref.get("name"),
        )
        display = next(
            (
                skill_display_lookup[key]
                for value in candidates
                if (key := str(value or "").strip()) in skill_display_lookup
            ),
            None,
        )
        if not display:
            continue
        display_name = str(display.get("display_name_zh") or "")
        display_description = str(display.get("display_description_zh") or "")
        if display_name and not str(ref.get("display_name_zh") or "").strip():
            ref["display_name_zh"] = display_name
        if (
            display_description
            and not str(ref.get("display_description_zh") or "").strip()
        ):
            ref["display_description_zh"] = display_description
    return enriched


def trace_strategy_display_lookup(sess: Any) -> dict[str, dict[str, str]]:
    try:
        from app.models.strategy_memory import StrategyMemory

        rows = (
            sess.query(
                StrategyMemory.id,
                StrategyMemory.slug,
                StrategyMemory.memory_key,
                StrategyMemory.name,
                StrategyMemory.display_name_zh,
                StrategyMemory.display_description_zh,
            )
            .filter(StrategyMemory.status != "archived")
            .all()
        )
    except Exception as exc:  # pragma: no cover - observability remains best-effort
        log.debug("trace strategy display lookup unavailable: %s", exc)
        return {}

    lookup: dict[str, dict[str, str]] = {}
    for row in rows:
        if isinstance(row, (tuple, list)) and len(row) < 6:
            continue
        mapping = getattr(row, "_mapping", None)
        strategy_id = (
            mapping.get("id") if mapping is not None else getattr(row, "id", None)
        )
        slug = (
            mapping.get("slug") if mapping is not None else getattr(row, "slug", None)
        )
        memory_key = (
            mapping.get("memory_key")
            if mapping is not None
            else getattr(row, "memory_key", None)
        )
        name = (
            mapping.get("name") if mapping is not None else getattr(row, "name", None)
        )
        display_name_zh = (
            mapping.get("display_name_zh")
            if mapping is not None
            else getattr(row, "display_name_zh", "")
        )
        display_description_zh = (
            mapping.get("display_description_zh")
            if mapping is not None
            else getattr(row, "display_description_zh", "")
        )
        display = {
            "display_name_zh": str(display_name_zh or ""),
            "display_description_zh": str(display_description_zh or ""),
        }
        keys = [
            strategy_id,
            slug,
            f"{slug}.md" if slug else "",
            memory_key,
            name,
        ]
        for key in keys:
            normalized = str(key or "").strip()
            if normalized:
                lookup[normalized] = display
    return lookup


def _enrich_trace_strategy_display_fields(
    payload: dict[str, Any],
    strategy_display_lookup: Mapping[str, Mapping[str, str]] | None,
) -> dict[str, Any]:
    if not strategy_display_lookup:
        return payload

    refs: list[Any] = []
    top_refs = payload.get("strategy_memory_refs")
    if isinstance(top_refs, list):
        refs.extend(top_refs)
    artifacts = payload.get("selection_artifacts")
    if isinstance(artifacts, dict):
        artifact_refs = artifacts.get("strategies")
        if isinstance(artifact_refs, list):
            refs.extend(artifact_refs)
    if not refs:
        return payload

    enriched = deepcopy(payload)
    enriched_refs: list[Any] = []
    top_enriched = enriched.get("strategy_memory_refs")
    if isinstance(top_enriched, list):
        enriched_refs.extend(top_enriched)
    enriched_artifacts = enriched.get("selection_artifacts")
    if isinstance(enriched_artifacts, dict):
        artifact_refs = enriched_artifacts.get("strategies")
        if isinstance(artifact_refs, list):
            enriched_refs.extend(artifact_refs)

    for ref in enriched_refs:
        if not isinstance(ref, dict):
            continue
        candidates = (
            ref.get("id"),
            ref.get("slug"),
            f"{ref.get('slug')}.md" if ref.get("slug") else "",
            ref.get("memory_key"),
            ref.get("name"),
        )
        display = next(
            (
                strategy_display_lookup[key]
                for value in candidates
                if (key := str(value or "").strip()) in strategy_display_lookup
            ),
            None,
        )
        if not display:
            continue
        display_name = str(display.get("display_name_zh") or "")
        display_description = str(display.get("display_description_zh") or "")
        if display_name and not str(ref.get("display_name_zh") or "").strip():
            ref["display_name_zh"] = display_name
        if (
            display_description
            and not str(ref.get("display_description_zh") or "").strip()
        ):
            ref["display_description_zh"] = display_description
    return enriched


def _list_from_unknown(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _contract_trace_payload(
    contract: Mapping[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    must_cover = _list_from_unknown(contract.get("must_cover"))
    acceptance_checks = _list_from_unknown(contract.get("acceptance_checks"))
    signed_by = _list_from_unknown(contract.get("signed_by"))
    return {
        "contract_source": source,
        "contract": deepcopy(dict(contract)),
        "contract_must_cover_count": len(must_cover),
        "contract_acceptance_check_count": len(acceptance_checks),
        "contract_bar_level": contract.get("bar_level"),
        "signed_by": deepcopy(signed_by),
    }


def trace_record_from_unknown(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def trace_ask_question_contract_lookup(
    traces: list[Any],
) -> dict[Any, dict[str, Any]]:
    lookup: dict[Any, dict[str, Any]] = {}
    for trace in traces:
        if getattr(trace, "node", None) != "ask_question":
            continue
        snapshot = trace_record_from_unknown(getattr(trace, "state_snapshot", None))
        payload = trace_record_from_unknown(snapshot.get("payload"))
        contract = trace_record_from_unknown(payload.get("contract"))
        if not contract:
            continue
        turn_idx = getattr(trace, "turn_idx", None)
        if turn_idx is None:
            continue
        lookup[turn_idx] = _contract_trace_payload(
            contract,
            source="ask_question.contract",
        )
    return lookup


def _enrich_trace_evaluator_contract_payload(
    payload: dict[str, Any],
    trace: Any,
    evaluator_contract_lookup: Mapping[Any, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if getattr(trace, "node", None) != "evaluator" or not evaluator_contract_lookup:
        return payload
    if "contract_source" in payload or "contract" in payload:
        return payload
    contract_payload = evaluator_contract_lookup.get(getattr(trace, "turn_idx", None))
    if not contract_payload:
        return payload
    contract = trace_record_from_unknown(contract_payload.get("contract"))
    if contract and (
        "contract_must_cover_count" not in contract_payload
        or "contract_acceptance_check_count" not in contract_payload
    ):
        contract_payload = {
            **_contract_trace_payload(
                contract,
                source=str(contract_payload.get("contract_source") or "ask_question.contract"),
            ),
            **dict(contract_payload),
        }
    enriched = dict(payload)
    for key, value in contract_payload.items():
        enriched.setdefault(key, deepcopy(value))
    return enriched


def trace_node_payload(
    trace: Any,
    *,
    skill_display_lookup: Mapping[str, Mapping[str, str]] | None = None,
    strategy_display_lookup: Mapping[str, Mapping[str, str]] | None = None,
    evaluator_contract_lookup: Mapping[Any, Mapping[str, Any]] | None = None,
    projection: TraceProjection = "admin",
) -> dict[str, Any]:
    snapshot = trace.state_snapshot or {}
    payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
    summary = payload if isinstance(payload, dict) else {}
    if not summary and isinstance(snapshot, dict):
        summary = {
            key: snapshot.get(key)
            for key in (
                "diagnostics",
                "selected_action",
                "dimension_status",
                "target_difficulty",
                "timing",
            )
            if snapshot.get(key) is not None
        }
    if trace_node_aliases(trace.node):
        summary = {
            **dict(summary),
            **{
                key: deepcopy(value)
                for key, value in trace_node_metadata(trace.node).items()
                if key not in summary
            },
        }
    if is_ask_question := trace.node == "ask_question":
        summary = _enrich_trace_skill_display_fields(
            summary,
            skill_display_lookup,
        )
        summary = _enrich_trace_strategy_display_fields(
            summary,
            strategy_display_lookup,
        )
    if trace.node == "evaluator":
        summary = _enrich_trace_evaluator_contract_payload(
            summary,
            trace,
            evaluator_contract_lookup,
        )
    answer = None if is_ask_question else answer_excerpt(trace.answer)
    evaluation = None if is_ask_question else trace.evaluation
    node = {
        "id": trace.id,
        "turn_idx": trace.turn_idx,
        "node": trace.node,
        "dimension": trace.dimension,
        "action_id": trace.action_id,
        "policy_id": trace.policy_id,
        "context_key": trace.context_key,
        "policy_context_keys": trace.policy_context_keys,
        "score": trace.score,
        "passed": trace.passed,
        "immediate_reward": trace.immediate_reward,
        "immediate_reward_applied": bool(trace.immediate_reward_applied),
        "question": trace.question,
        "answer_excerpt": answer,
        "evaluation": evaluation,
        "payload": summary,
        "langsmith_run_id": trace.langsmith_run_id,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
    }
    if projection == "owner":
        return _owner_trace_node_payload(node)
    return node


def _owner_trace_node_payload(node: dict[str, Any]) -> dict[str, Any]:
    owner_node = {
        key: deepcopy(value)
        for key, value in node.items()
        if key not in _OWNER_NODE_INTERNAL_KEYS
    }
    payload = trace_record_from_unknown(owner_node.get("payload"))
    owner_payload = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key in _OWNER_PAYLOAD_ALLOWLIST
    }
    owner_node["payload"] = owner_payload
    return owner_node


def _trace_record_has_fallback_marker(record: dict[str, Any]) -> bool:
    if record.get("source") == "fallback":
        return True
    if str(record.get("fallback_reason") or "").strip():
        return True
    weaknesses = record.get("weaknesses")
    if isinstance(weaknesses, list):
        return any("fallback" in str(item or "").lower() for item in weaknesses)
    return False


def trace_has_evaluator_fallback(trace: Any) -> bool:
    if getattr(trace, "node", None) != "evaluator":
        return False
    evaluation = trace_record_from_unknown(getattr(trace, "evaluation", None))
    snapshot = trace_record_from_unknown(getattr(trace, "state_snapshot", None))
    payload = trace_record_from_unknown(snapshot.get("payload"))
    return (
        _trace_record_has_fallback_marker(evaluation)
        or _trace_record_has_fallback_marker(trace_record_from_unknown(payload.get("evaluation")))
        or _trace_record_has_fallback_marker(payload)
    )


def build_session_trace_payload(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    *,
    projection: TraceProjection = "admin",
) -> dict[str, Any]:
    from sqlalchemy import func

    from app.models import GenerationTrace, InterviewSession, get_session

    capped_limit = max(1, min(int(limit or 100), 300))
    safe_offset = max(0, min(int(offset or 0), 10_000))
    with get_session() as sess:
        row = sess.get(InterviewSession, session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="session not found")
        if projection == "owner" and row.status != "completed":
            raise HTTPException(
                status_code=409,
                detail="trace is only available for completed sessions",
            )
        summary_rows = (
            sess.query(GenerationTrace.node, func.count(GenerationTrace.id))
            .filter(GenerationTrace.session_id == session_id)
            .group_by(GenerationTrace.node)
            .all()
        )
        all_traces = (
            sess.query(GenerationTrace)
            .filter(GenerationTrace.session_id == session_id)
            .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
            .all()
        )
        traces = (
            sess.query(GenerationTrace)
            .filter(GenerationTrace.session_id == session_id)
            .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
            .offset(safe_offset)
            .limit(capped_limit)
            .all()
        )
        skill_display_lookup = trace_skill_display_lookup(sess)
        strategy_display_lookup = trace_strategy_display_lookup(sess)
        evaluator_contract_lookup = trace_ask_question_contract_lookup(all_traces)

    nodes = [
        trace_node_payload(
            trace,
            skill_display_lookup=skill_display_lookup,
            strategy_display_lookup=strategy_display_lookup,
            evaluator_contract_lookup=evaluator_contract_lookup,
            projection=projection,
        )
        for trace in traces
    ]
    report = row.final_report or {}

    node_counts = {str(node or ""): int(count) for node, count in summary_rows}
    node_type_aliases = {
        node: trace_node_aliases(node)
        for node in node_counts
        if trace_node_aliases(node)
    }
    total_trace_count = sum(node_counts.values())
    summary_nodes = [{"node": node} for node in node_counts]
    diagnostics = trace_diagnostics(summary_nodes, session_status=row.status)
    last_trace = all_traces[-1] if all_traces else None
    if last_trace is not None:
        diagnostics["last_node"] = last_trace.node
    payload = {
        "session_id": row.session_id,
        "trace_id": row.trace_id,
        "status": row.status,
        "has_report": bool(report),
        "overall_score": report.get("overall_score"),
        "overall_verdict": report.get("overall_verdict") or report.get("verdict"),
        "trace_count": total_trace_count,
        "evaluator_trace_count": int(node_counts.get("evaluator", 0)),
        "reward_trace_count": int(node_counts.get("reward_update", 0)),
        "final_report_trace_count": int(node_counts.get("final_report", 0)),
        "trace_health": classify_trace_health(summary_nodes, session_status=row.status),
        "trace_diagnostics": diagnostics,
        "node_count_total": total_trace_count,
        "node_type_counts": node_counts,
        "node_type_aliases": node_type_aliases,
        "fallback_trace_count": sum(
            1 for trace in all_traces if trace_has_evaluator_fallback(trace)
        ),
        "turn_count": len(
            {
                trace.turn_idx
                for trace in all_traces
                if getattr(trace, "turn_idx", None) is not None
            }
        ),
        "nodes_offset": safe_offset,
        "nodes_limit": capped_limit,
        "nodes_has_more": safe_offset + len(nodes) < total_trace_count,
        "nodes": nodes,
    }
    if projection == "admin":
        payload["langsmith"] = langsmith_admin_meta()
    return payload
