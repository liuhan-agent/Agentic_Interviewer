"""Quality lint for YAML-backed structured question seeds."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.question_seed_import import (
    QuestionSeedImportError,
    parse_question_seed_dir,
)

REVIEWED_CHECK_REQUIRED = {
    "check_id",
    "source",
    "source_text",
    "acceptance_check",
    "severity",
    "review_status",
    "version",
    "reviewed_seed_version",
    "reviewed_variant_version",
    "reviewed_by",
    "reviewed_at",
}
REVIEWED_CHECK_SOURCES = {"must_cover", "rubric_addition", "manual"}
REVIEWED_CHECK_SEVERITIES = {"core", "supporting"}
REVIEWED_CHECK_STATUSES = {"draft", "reviewed", "deprecated"}

JAVA_BACKEND_ROLE_REQUIREMENTS = {
    "java_backend": {
        "min_seeds": 19,
        "dimensions": {
            "technical_depth",
            "system_design",
            "problem_solving",
            "coding_quality",
            "project_experience",
            "communication",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
}

BATCH2_ROLE_REQUIREMENTS = {
    "frontend_web": {
        "min_seeds": 19,
        "dimensions": {
            "technical_depth",
            "coding_quality",
            "problem_solving",
            "project_experience",
            "product_thinking",
            "communication",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "sre": {
        "min_seeds": 16,
        "dimensions": {
            "technical_depth",
            "system_design",
            "problem_solving",
            "project_experience",
            "communication",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "ai_agent": {
        "min_seeds": 16,
        "dimensions": {
            "technical_depth",
            "system_design",
            "problem_solving",
            "product_thinking",
            "communication",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "ai_fullstack": {
        "min_seeds": 19,
        "dimensions": {
            "technical_depth",
            "system_design",
            "product_thinking",
            "project_experience",
            "problem_solving",
            "communication",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "mobile": {
        "min_seeds": 16,
        "dimensions": {
            "technical_depth",
            "problem_solving",
            "coding_quality",
            "project_experience",
            "communication",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "ai_algorithm": {
        "min_seeds": 16,
        "dimensions": {
            "technical_depth",
            "problem_solving",
            "product_thinking",
            "project_experience",
            "communication",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "architect": {
        "min_seeds": 6,
        "dimensions": {
            "system_design",
            "technical_depth",
            "leadership",
            "problem_solving",
            "communication",
        },
    },
}

BUSINESS1_ROLE_REQUIREMENTS = {
    "product_manager": {
        "min_seeds": 5,
        "dimensions": {
            "user_insight",
            "requirement_analysis",
            "prioritization",
            "metrics_thinking",
            "stakeholder_management",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "operations": {
        "min_seeds": 5,
        "dimensions": {
            "user_growth",
            "content_operations",
            "data_analysis",
            "campaign_execution",
            "process_optimization",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "sales_business": {
        "min_seeds": 5,
        "dimensions": {
            "customer_discovery",
            "solution_matching",
            "objection_handling",
            "negotiation",
            "pipeline_management",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "marketing_brand": {
        "min_seeds": 5,
        "dimensions": {
            "market_insight",
            "brand_strategy",
            "campaign_planning",
            "channel_growth",
            "content_creativity",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
}

SERVICE_MANAGEMENT_ROLE_REQUIREMENTS = {
    "hr_function": {
        "min_seeds": 5,
        "dimensions": {
            "talent_acquisition",
            "employee_relations",
            "organization_development",
            "policy_compliance",
            "service_orientation",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "customer_success": {
        "min_seeds": 5,
        "dimensions": {
            "customer_empathy",
            "issue_diagnosis",
            "solution_delivery",
            "escalation_management",
            "retention_growth",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
    "general_management": {
        "min_seeds": 5,
        "dimensions": {
            "goal_setting",
            "team_leadership",
            "decision_making",
            "execution_management",
            "cross_functional_alignment",
        },
        "required_job_levels": {"junior", "mid", "senior"},
    },
}

ROLE_COVERAGE_REQUIREMENTS = {
    **JAVA_BACKEND_ROLE_REQUIREMENTS,
    **BATCH2_ROLE_REQUIREMENTS,
    **BUSINESS1_ROLE_REQUIREMENTS,
    **SERVICE_MANAGEMENT_ROLE_REQUIREMENTS,
}

ROLE_KEYWORDS = {
    "java_backend": {
        "java",
        "backend",
        "spring",
        "redis",
        "mysql",
        "kafka",
        "microservice",
        "api",
        "transaction",
        "capacity",
        "queue",
        "service",
        "payment",
        "observability",
        "slo",
        "database",
        "data_modeling",
        "order",
    },
    "frontend_web": {
        "frontend",
        "react",
        "vue",
        "web",
        "h5",
        "browser",
        "component",
        "render",
    },
    "sre": {
        "sre",
        "devops",
        "linux",
        "kubernetes",
        "observability",
        "slo",
        "incident",
        "release",
    },
    "ai_agent": {
        "agent",
        "tool",
        "rag",
        "llm",
        "prompt",
        "memory",
        "context",
        "langchain",
        "langgraph",
    },
    "ai_fullstack": {
        "fullstack",
        "llm",
        "rag",
        "react",
        "python",
        "workflow",
        "api",
        "product",
    },
    "mobile": {
        "mobile",
        "android",
        "ios",
        "flutter",
        "react_native",
        "react-native",
        "app",
        "crash",
    },
    "ai_algorithm": {
        "algorithm",
        "model",
        "pytorch",
        "tensorflow",
        "experiment",
        "evaluation",
        "metric",
        "dataset",
    },
    "architect": {
        "architect",
        "architecture",
        "distributed",
        "governance",
        "technical",
        "staff",
        "review",
        "evolution",
    },
    "product_manager": {
        "product",
        "pm",
        "prd",
        "requirement",
        "roadmap",
        "insight",
        "user",
        "metric",
        "prioritization",
        "stakeholder",
    },
    "operations": {
        "operation",
        "operations",
        "growth",
        "content",
        "campaign",
        "data",
        "retention",
        "conversion",
        "process",
        "community",
    },
    "sales_business": {
        "sales",
        "business",
        "customer",
        "discovery",
        "icp",
        "solution",
        "objection",
        "negotiation",
        "contract",
        "crm",
        "pipeline",
    },
    "marketing_brand": {
        "marketing",
        "brand",
        "market",
        "campaign",
        "channel",
        "content",
        "creativity",
        "roi",
        "media",
    },
    "hr_function": {
        "hr",
        "recruiting",
        "talent",
        "candidate",
        "employee",
        "organization",
        "policy",
        "compliance",
        "performance",
        "service",
    },
    "customer_success": {
        "customer",
        "support",
        "success",
        "empathy",
        "issue",
        "diagnosis",
        "solution",
        "escalation",
        "renewal",
        "retention",
        "sla",
    },
    "general_management": {
        "management",
        "manager",
        "goal",
        "team",
        "leadership",
        "decision",
        "execution",
        "cross_functional",
        "alignment",
        "conflict",
    },
}


@dataclass(frozen=True)
class QuestionSeedLintIssue:
    severity: str
    code: str
    seed_id: str | None
    variant_id: str | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "seed_id": self.seed_id,
            "variant_id": self.variant_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class QuestionSeedLintResult:
    passed: bool
    strict: bool
    warning_count: int
    error_count: int
    issues: list[QuestionSeedLintIssue]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "strict": self.strict,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def lint_question_seed_dir(
    seed_dir: Path,
    *,
    strict: bool = False,
    min_active_variants: int = 2,
    check_role_coverage: bool = True,
) -> QuestionSeedLintResult:
    try:
        seeds, variants = parse_question_seed_dir(seed_dir)
    except QuestionSeedImportError as exc:
        issues = [
            QuestionSeedLintIssue(
                severity="error",
                code="schema_error",
                seed_id=None,
                variant_id=None,
                message=message,
            )
            for message in exc.errors
        ]
        return QuestionSeedLintResult(
            passed=False,
            strict=strict,
            warning_count=0,
            error_count=len(issues),
            issues=issues,
        )

    issues: list[QuestionSeedLintIssue] = []
    variants_by_seed: dict[str, list[dict[str, Any]]] = {}
    for parsed in variants:
        variants_by_seed.setdefault(parsed.values["seed_id"], []).append(parsed.values)
    seed_versions = {parsed.values["id"]: int(parsed.values.get("version") or 0) for parsed in seeds}

    role_seed_ids: dict[str, set[str]] = {}
    role_dimensions: dict[str, set[str]] = {}
    for parsed_seed in seeds:
        seed = parsed_seed.values
        seed_id = seed["id"]
        seed_variants = variants_by_seed.get(seed_id, [])
        active_variants = [
            variant for variant in seed_variants if variant.get("status") == "active"
        ]
        if len(active_variants) < min_active_variants:
            issues.append(
                _issue(
                    strict,
                    "variant_density",
                    seed_id,
                    None,
                    (
                        f"{seed_id}: active variants {len(active_variants)} < "
                        f"{min_active_variants}"
                    ),
                )
            )
        role_tags = set(seed.get("role_tags") or [])
        if not role_tags or role_tags <= {"general"}:
            issues.append(
                _issue(
                    strict,
                    "missing_role_pack",
                    seed_id,
                    None,
                    f"{seed_id}: missing concrete role_tags",
                )
            )
        if seed.get("status") == "active":
            for role in role_tags - {"general"}:
                requirement = ROLE_COVERAGE_REQUIREMENTS.get(role)
                if requirement is not None:
                    allowed_dimensions = set(requirement.get("dimensions") or set())
                    dimension = str(seed.get("dimension") or "")
                    if allowed_dimensions and dimension not in allowed_dimensions:
                        issues.append(
                            _issue(
                                strict,
                                "role_dimension_mismatch",
                                seed_id,
                                None,
                                (
                                    f"{role}: seed {seed_id} uses unsupported "
                                    f"dimension {dimension}"
                                ),
                            )
                        )
                    required_levels = set(requirement.get("required_job_levels") or set())
                    missing_levels = required_levels - set(seed.get("job_levels") or [])
                    if missing_levels:
                        issues.append(
                            _issue(
                                strict,
                                "role_level_coverage",
                                seed_id,
                                None,
                                (
                                    f"{role}: seed {seed_id} missing job_levels "
                                    f"{sorted(missing_levels)}"
                                ),
                            )
                        )
                role_seed_ids.setdefault(role, set()).add(seed_id)
                role_dimensions.setdefault(role, set()).add(str(seed.get("dimension") or ""))
        if _has_role_stem_mismatch(seed, seed_variants):
            issues.append(
                _issue(
                    strict,
                    "role_stem_mismatch",
                    seed_id,
                    None,
                    f"{seed_id}: role_tags do not match seed or variant scenario text",
                )
            )

    if check_role_coverage:
        for role, requirement in ROLE_COVERAGE_REQUIREMENTS.items():
            seed_count = len(role_seed_ids.get(role, set()))
            min_seeds = int(requirement["min_seeds"])
            if seed_count < min_seeds:
                issues.append(
                    _issue(
                        strict,
                        "role_coverage",
                        None,
                        None,
                        f"{role}: active seeds {seed_count} < {min_seeds}",
                    )
                )
            missing_dimensions = set(requirement["dimensions"]) - role_dimensions.get(
                role, set()
            )
            if missing_dimensions:
                issues.append(
                    _issue(
                        strict,
                        "role_coverage",
                        None,
                        None,
                        f"{role}: missing dimensions {sorted(missing_dimensions)}",
                    )
                )

    for parsed_variant in variants:
        variant = parsed_variant.values
        seed_id = variant["seed_id"]
        variant_id = variant["id"]
        for field in ("scenario_skill_tags", "resume_anchor_hints", "failure_categories"):
            if not variant.get(field):
                issues.append(
                    _issue(
                        strict,
                        f"missing_{field}",
                        seed_id,
                        variant_id,
                        f"{variant_id}: missing {field}",
                    )
                )
        stem = str(variant.get("question_stem") or "")
        if _is_generic_stem(stem):
            issues.append(
                _issue(
                    strict,
                    "generic_question_stem",
                    seed_id,
                    variant_id,
                    f"{variant_id}: generic question_stem",
                )
            )
        leakage_fields = {
            "question_stem": variant.get("question_stem"),
            "prompt_template": variant.get("prompt_template"),
            "scenario_brief": variant.get("scenario_brief"),
        }
        for field, value in leakage_fields.items():
            if _leaks_internal_hint(value):
                issues.append(
                    _issue(
                        strict,
                        "internal_hint_leakage",
                        seed_id,
                        variant_id,
                        f"{variant_id}: internal hint leakage risk in {field}",
                    )
                )
        issues.extend(
            _reviewed_acceptance_check_issues(
                strict=strict,
                seed_id=seed_id,
                seed_version=seed_versions.get(seed_id, 0),
                variant=variant,
            )
        )

    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    error_count = sum(1 for issue in issues if issue.severity == "error")
    return QuestionSeedLintResult(
        passed=error_count == 0,
        strict=strict,
        warning_count=warning_count,
        error_count=error_count,
        issues=issues,
    )


def _issue(
    strict: bool,
    code: str,
    seed_id: str | None,
    variant_id: str | None,
    message: str,
) -> QuestionSeedLintIssue:
    return QuestionSeedLintIssue(
        severity="error" if strict else "warning",
        code=code,
        seed_id=seed_id,
        variant_id=variant_id,
        message=message,
    )


def _is_generic_stem(stem: str) -> bool:
    text = stem.strip().lower()
    if len(text) < 12:
        return True
    generic_markers = (
        "tell me about architecture",
        "talk about architecture",
        "describe your design",
        "system design question",
    )
    return any(marker in text for marker in generic_markers)


def _leaks_internal_hint(value: Any) -> bool:
    text = str(value or "").lower()
    return any(
        token in text
        for token in (
            "expected_signals",
            "good_answer_hints",
            "anti_patterns",
            "seed_id",
            "variant_id",
            "failure trigger",
        )
    )


def _reviewed_acceptance_check_issues(
    *,
    strict: bool,
    seed_id: str,
    seed_version: int,
    variant: dict[str, Any],
) -> list[QuestionSeedLintIssue]:
    variant_id = str(variant.get("id") or "")
    variant_version = _safe_int(variant.get("version"))
    checks = variant.get("reviewed_acceptance_checks") or []
    if not isinstance(checks, list) or not checks:
        return []

    issues: list[QuestionSeedLintIssue] = []
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for idx, check in enumerate(checks):
        if not isinstance(check, dict):
            issues.append(
                _issue(
                    strict,
                    "reviewed_check_schema",
                    seed_id,
                    variant_id,
                    f"{variant_id}: reviewed_acceptance_checks[{idx}] must be a mapping",
                )
            )
            continue
        check_id = str(check.get("check_id") or "").strip()
        review_status = str(check.get("review_status") or "")
        missing = [
            field
            for field in sorted(REVIEWED_CHECK_REQUIRED)
            if _reviewed_check_field_missing(
                check,
                field=field,
                review_status=review_status,
            )
        ]
        invalid_enum = (
            str(check.get("source") or "") not in REVIEWED_CHECK_SOURCES
            or str(check.get("severity") or "") not in REVIEWED_CHECK_SEVERITIES
            or review_status not in REVIEWED_CHECK_STATUSES
        )
        if missing or invalid_enum:
            issues.append(
                _issue(
                    strict,
                    "reviewed_check_schema",
                    seed_id,
                    variant_id,
                    (
                        f"{variant_id}: invalid reviewed_acceptance_checks[{idx}] "
                        f"schema"
                    ),
                )
            )
        if check_id:
            if check_id in seen_ids:
                duplicate_ids.add(check_id)
            seen_ids.add(check_id)
        if _is_generic_acceptance_check(check.get("acceptance_check")):
            issues.append(
                _issue(
                    strict,
                    "generic_reviewed_acceptance_check",
                    seed_id,
                    variant_id,
                    f"{variant_id}: generic reviewed acceptance check {check_id or idx}",
                )
            )
        reviewed_seed_version = _safe_int(check.get("reviewed_seed_version"))
        reviewed_variant_version = _safe_int(check.get("reviewed_variant_version"))
        if (
            reviewed_seed_version < seed_version
            or reviewed_variant_version < variant_version
        ):
            issues.append(
                _issue(
                    strict,
                    "review_stale",
                    seed_id,
                    variant_id,
                    f"{variant_id}: reviewed acceptance check is stale",
                )
            )
    for duplicate_id in sorted(duplicate_ids):
        issues.append(
            _issue(
                strict,
                "reviewed_check_duplicate_id",
                seed_id,
                variant_id,
                f"{variant_id}: duplicate reviewed check_id {duplicate_id}",
            )
        )
    return issues


def _reviewed_check_field_missing(
    check: dict[str, Any],
    *,
    field: str,
    review_status: str,
) -> bool:
    if field not in check or check.get(field) is None:
        return True
    if (
        review_status == "draft"
        and field in {"reviewed_by", "reviewed_at"}
        and check.get(field) == ""
    ):
        return False
    return check.get(field) == ""


def _is_generic_acceptance_check(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    generic_checks = {
        "answer is clear.",
        "answer is correct.",
        "answer is reasonable.",
        "answer has enough depth.",
        "回答清楚即可",
        "回答合理即可",
    }
    return text in generic_checks


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _has_role_stem_mismatch(seed: dict[str, Any], variants: list[dict[str, Any]]) -> bool:
    roles = set(seed.get("role_tags") or []) - {"general"}
    if not roles:
        return False
    text_parts = [
        seed.get("id"),
        seed.get("title"),
        seed.get("dimension"),
        " ".join(seed.get("skill_tags") or []),
    ]
    for variant in variants:
        text_parts.extend(
            [
                variant.get("scenario_brief"),
                variant.get("question_stem"),
                variant.get("prompt_template"),
                " ".join(variant.get("scenario_skill_tags") or []),
                " ".join(variant.get("resume_anchor_hints") or []),
            ]
        )
    text = " ".join(str(part or "") for part in text_parts).lower().replace("-", "_")
    for role in roles:
        keywords = ROLE_KEYWORDS.get(role, set())
        if keywords and not any(keyword in text for keyword in keywords):
            return True
    return False
