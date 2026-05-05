"""Direction-aware probe intent resolver.

Maps ``(direction, dimension, job_level)`` to a ``ProbeIntent`` that
controls the *style* of the follow-up question without changing the
plan topology.  The resolver is deterministic and stateless; the
evaluator may override the default via ``recommended_probe_intent``.

The intent is consumed by ``generate_question`` as a prompt-slot
variable (``PROBE_INTENT``), not as a plan template selector —
keeping the two axes (plan complexity vs question style) orthogonal.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.engine.workflow.state import FailureCategory, ProbeIntent

log = get_logger(__name__)

_DIRECTION_DIMENSION_MAP: dict[str, dict[str, ProbeIntent]] = {
    "java_backend": {
        "technical_depth": "debugging_probe",
        "system_design": "architecture_challenge",
        "problem_solving": "evidence_probe",
        "coding_quality": "evidence_probe",
        "project_experience": "evidence_probe",
    },
    "python_backend": {
        "technical_depth": "debugging_probe",
        "system_design": "architecture_challenge",
        "problem_solving": "evidence_probe",
        "coding_quality": "evidence_probe",
        "project_experience": "evidence_probe",
    },
    "go_backend": {
        "technical_depth": "debugging_probe",
        "system_design": "architecture_challenge",
        "problem_solving": "evidence_probe",
    },
    "ai_engineering": {
        "technical_depth": "experiment_probe",
        "system_design": "architecture_challenge",
        "problem_solving": "debugging_probe",
        "data_analysis": "experiment_probe",
    },
    "ai_fullstack": {
        "technical_depth": "experiment_probe",
        "system_design": "architecture_challenge",
        "product_thinking": "metric_probe",
        "project_experience": "evidence_probe",
        "problem_solving": "debugging_probe",
    },
    "ai_agent": {
        "technical_depth": "experiment_probe",
        "system_design": "architecture_challenge",
        "problem_solving": "debugging_probe",
        "product_thinking": "metric_probe",
    },
    "frontend": {
        "technical_depth": "performance_probe",
        "problem_solving": "evidence_probe",
        "coding_quality": "tradeoff_probe",
        "project_experience": "evidence_probe",
        "product_thinking": "tradeoff_probe",
    },
    "mobile": {
        "technical_depth": "performance_probe",
        "problem_solving": "debugging_probe",
        "coding_quality": "tradeoff_probe",
        "project_experience": "evidence_probe",
    },
    "sre": {
        "technical_depth": "debugging_probe",
        "system_design": "architecture_challenge",
        "problem_solving": "debugging_probe",
        "project_experience": "evidence_probe",
    },
    "architect": {
        "system_design": "architecture_challenge",
        "technical_depth": "architecture_challenge",
        "leadership": "tradeoff_probe",
        "problem_solving": "debugging_probe",
    },
    "ai_algorithm": {
        "technical_depth": "experiment_probe",
        "problem_solving": "experiment_probe",
        "project_experience": "metric_probe",
        "product_thinking": "metric_probe",
    },
    "product_manager": {
        "user_insight": "roleplay_probe",
        "requirement_analysis": "tradeoff_probe",
        "prioritization": "prioritization_probe",
        "metrics_thinking": "metric_probe",
        # PM stakeholder management is dominated by handling
        # pushback from cross-functional partners; pushback shape
        # is a strict superset of generic roleplay so it gives
        # the generator more room without losing the old style.
        "stakeholder_management": "stakeholder_pushback_probe",
    },
    "data_analyst": {
        "technical_depth": "experiment_probe",
        "data_analysis": "experiment_probe",
        "problem_solving": "metric_probe",
    },
    "operations": {
        "user_growth": "metric_probe",
        "content_operations": "evidence_probe",
        "data_analysis": "metric_probe",
        "campaign_execution": "experiment_probe",
        # Process optimisation is much more about authoring a
        # reusable workflow than weighing alternatives, so prefer
        # the explicit process_design framing.
        "process_optimization": "process_design_probe",
    },
    "sales_business": {
        "objection_handling": "objection_probe",
        "negotiation": "roleplay_probe",
        "solution_matching": "tradeoff_probe",
        "pipeline_management": "evidence_probe",
        # B2B customer discovery is best probed by walking through
        # one concrete past customer end-to-end, not by generic
        # roleplay.
        "customer_discovery": "case_study_probe",
    },
    "marketing_brand": {
        "market_insight": "metric_probe",
        "brand_strategy": "tradeoff_probe",
        "campaign_planning": "experiment_probe",
        "channel_growth": "metric_probe",
        "content_creativity": "evidence_probe",
    },
    "hr_function": {
        # Talent acquisition leans on third-party signal
        # (referees / past managers) more than raw evidence,
        # which the new reference_check intent captures cleanly.
        "talent_acquisition": "reference_check_probe",
        "employee_relations": "roleplay_probe",
        # Org development is fundamentally process design;
        # tradeoff_probe under-specifies the expected output.
        "organization_development": "process_design_probe",
        "policy_compliance": "evidence_probe",
        "service_orientation": "roleplay_probe",
    },
    "customer_success": {
        "customer_empathy": "roleplay_probe",
        "issue_diagnosis": "debugging_probe",
        "solution_delivery": "tradeoff_probe",
        "escalation_management": "escalation_probe",
        "retention_growth": "metric_probe",
    },
    "general_management": {
        "goal_setting": "prioritization_probe",
        "team_leadership": "roleplay_probe",
        "decision_making": "tradeoff_probe",
        "execution_management": "evidence_probe",
        # Cross-functional alignment is dominated by handling
        # peer-leader pushback; the dedicated intent steers
        # the generator toward "design a counter-argument".
        "cross_functional_alignment": "stakeholder_pushback_probe",
    },
}

_DIRECTION_FAMILY: dict[str, str] = {
    "java_backend": "backend",
    "python_backend": "backend",
    "go_backend": "backend",
    "ai_engineering": "backend",
    "ai_fullstack": "backend",
    "ai_agent": "backend",
    "ai_algorithm": "data",
    "sre": "backend",
    "architect": "backend",
    "frontend": "frontend",
    "mobile": "frontend",
    "product_manager": "product",
    "data_analyst": "data",
    "operations": "product",
    "sales_business": "sales",
    "marketing_brand": "product",
    "hr_function": "service",
    "customer_success": "service",
    "general_management": "management",
}

_FAMILY_DEFAULT: dict[str, ProbeIntent] = {
    "backend": "architecture_challenge",
    "frontend": "tradeoff_probe",
    "product": "metric_probe",
    "data": "experiment_probe",
    "sales": "roleplay_probe",
    "service": "roleplay_probe",
    "management": "tradeoff_probe",
}

_FAILURE_CATEGORY_TO_INTENT: dict[FailureCategory, ProbeIntent] = {
    "missing_evidence": "evidence_probe",
    "missing_tradeoff": "tradeoff_probe",
    "missing_metrics": "metric_probe",
    "unclear_architecture": "architecture_challenge",
    "weak_debugging": "debugging_probe",
    "weak_prioritization": "prioritization_probe",
    "weak_roleplay_response": "roleplay_probe",
}


def resolve_probe_intent(
    *,
    direction: str | None,
    dimension: str,
    job_level: str | None = None,
    failure_reason: str | None = None,
    failure_category: FailureCategory | None = None,
    evaluator_hint: ProbeIntent | None = None,
    coverage_closeout: bool = False,
) -> ProbeIntent | None:
    """Pick a probe intent for the upcoming question round.

    Resolution order:
    1. ``coverage_closeout`` — remaining turn budget is tight.
    2. ``evaluator_hint`` — explicit evaluator recommendation.
    3. ``failure_category`` / ``failure_reason``.
    4. ``(direction, dimension)`` lookup in the cross table.
    5. Direction family default.
    6. ``"general"`` fallback.

    Returns ``None`` when ``enable_probe_intent`` is False so callers
    can short-circuit without injecting any prompt slot.
    """
    try:
        if not getattr(get_settings(), "enable_probe_intent", False):
            return None
    except Exception:
        return None

    if coverage_closeout:
        return "coverage_closeout"

    if evaluator_hint and evaluator_hint != "general":
        return evaluator_hint

    if failure_category:
        intent = _FAILURE_CATEGORY_TO_INTENT.get(failure_category)
        if intent:
            return intent

    if failure_reason:
        intent = _intent_from_failure_reason(failure_reason)
        if intent:
            return intent

    direction = (direction or "").strip().lower()
    dimension = (dimension or "").strip().lower()

    dim_map = _DIRECTION_DIMENSION_MAP.get(direction)
    if dim_map:
        hit = dim_map.get(dimension)
        if hit:
            return hit

    family = _DIRECTION_FAMILY.get(direction)
    if family:
        return _FAMILY_DEFAULT.get(family, "general")

    return "general"


def normalize_failure_category(
    *,
    failure_reason: str | None,
    weaknesses: list[str] | None,
    missing_must_cover: list[str] | None,
) -> FailureCategory | None:
    """Normalize free-form evaluator weakness signals into stable buckets."""
    parts = [
        str(failure_reason or ""),
        " ".join(str(item) for item in (weaknesses or [])),
        " ".join(str(item) for item in (missing_must_cover or [])),
    ]
    text = " ".join(parts).lower()
    if not text.strip():
        return None

    if any(
        kw in text
        for kw in (
            "metric",
            "metrics",
            "kpi",
            "data",
            "quant",
            "指标",
            "数据",
            "量化",
            "转化",
            "留存",
        )
    ):
        return "missing_metrics"
    if any(
        kw in text
        for kw in (
            "tradeoff",
            "trade-off",
            "alternative",
            "constraint",
            "权衡",
            "取舍",
            "方案对比",
            "约束",
        )
    ):
        return "missing_tradeoff"
    if any(
        kw in text
        for kw in (
            "architecture",
            "system design",
            "boundary",
            "scale",
            "scalability",
            "架构",
            "系统设计",
            "边界",
            "扩展",
        )
    ):
        return "unclear_architecture"
    if any(
        kw in text
        for kw in (
            "debug",
            "root cause",
            "troubleshoot",
            "incident",
            "排查",
            "故障",
            "定位",
            "根因",
        )
    ):
        return "weak_debugging"
    if any(
        kw in text
        for kw in (
            "priority",
            "prioritization",
            "roadmap",
            "排序",
            "优先级",
            "排期",
        )
    ):
        return "weak_prioritization"
    if any(
        kw in text
        for kw in (
            "roleplay",
            "customer",
            "stakeholder",
            "objection",
            "escalation",
            "客户",
            "异议",
            "升级",
            "沟通",
            "协同",
        )
    ):
        return "weak_roleplay_response"
    if any(
        kw in text
        for kw in (
            "evidence",
            "example",
            "concrete",
            "specific",
            "project",
            "outcome",
            "例子",
            "具体",
            "证据",
            "项目",
            "结果",
        )
    ):
        return "missing_evidence"

    return None


def _intent_from_failure_reason(reason: str) -> ProbeIntent | None:
    """Heuristic: map common evaluator weakness keywords to intent."""
    r = reason.lower()
    if any(kw in r for kw in ("evidence", "example", "concrete", "specific", "例子", "具体")):
        return "evidence_probe"
    if any(kw in r for kw in ("tradeoff", "trade-off", "权衡", "取舍")):
        return "tradeoff_probe"
    if any(kw in r for kw in ("metric", "指标", "量化", "数据")):
        return "metric_probe"
    if any(kw in r for kw in ("architecture", "架构", "系统设计", "边界")):
        return "architecture_challenge"
    if any(kw in r for kw in ("debug", "排查", "故障", "定位")):
        return "debugging_probe"
    return None


PROBE_INTENT_LABELS: dict[ProbeIntent, str] = {
    "general": "通用追问",
    "evidence_probe": "补充证据",
    "tradeoff_probe": "权衡分析",
    "coverage_closeout": "覆盖收尾",
    "architecture_challenge": "架构挑战",
    "debugging_probe": "排障追问",
    "performance_probe": "性能追问",
    "metric_probe": "指标追问",
    "prioritization_probe": "优先级追问",
    "experiment_probe": "实验设计",
    "roleplay_probe": "角色扮演",
    "objection_probe": "异议处理",
    "escalation_probe": "升级处理",
    "case_study_probe": "案例剖析",
    "reference_check_probe": "证人对照",
    "stakeholder_pushback_probe": "利益方反对",
    "process_design_probe": "流程设计",
}
