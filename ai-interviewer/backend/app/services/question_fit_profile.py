"""Rule-built fit profile for structured question selection.

The profile is deliberately deterministic and cheap. It summarizes the
candidate/JD/turn signals that the rule selector can safely use without
letting the shadow LLM reranker affect production question choice.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QuestionFitProfile:
    dimension: str
    turn_intent: str
    direction_tags: list[str]
    role_tags: list[str]
    candidate_projects: list[dict[str, Any]]
    candidate_skills: list[str]
    job_core_skills: list[str]
    target_skills: list[str]
    failure_categories: list[str]
    anchor_confidence: str
    generic_risk: str
    resume_anchor_terms: list[str]

    def as_artifact(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "turn_intent": self.turn_intent,
            "direction_tags": list(self.direction_tags),
            "role_tags": list(self.role_tags),
            "candidate_projects": list(self.candidate_projects),
            "candidate_skills": list(self.candidate_skills),
            "job_core_skills": list(self.job_core_skills),
            "target_skills": list(self.target_skills),
            "failure_categories": list(self.failure_categories),
            "anchor_confidence": self.anchor_confidence,
            "generic_risk": self.generic_risk,
            "resume_anchor_terms": list(self.resume_anchor_terms),
        }


def build_question_fit_profile(
    *,
    candidate: dict[str, Any] | None,
    self_intro_profile: dict[str, Any] | None,
    job_spec: dict[str, Any] | None,
    target_skills: Sequence[str] | None,
    resume_anchor: dict[str, Any] | None,
    pending_contract_hints: dict[str, Any] | None,
    dimension: str,
    probe_intent: str | None,
    runtime_config: dict[str, Any] | None = None,
) -> QuestionFitProfile:
    resume_parsed = (candidate or {}).get("resume_parsed")
    if not isinstance(resume_parsed, dict):
        resume_parsed = {}
    intro = self_intro_profile or {}
    job = job_spec or {}
    anchor = resume_anchor if isinstance(resume_anchor, dict) else {}

    projects = _extract_projects(resume_parsed, intro, anchor)
    candidate_skills = _dedup_slugs(
        [
            *_items(resume_parsed.get("skills")),
            *_items(resume_parsed.get("focus_areas")),
            *_items(resume_parsed.get("tech_stack")),
            *_items(intro.get("emphasized_skills")),
            *_items(anchor.get("tech_stack")),
            *_items(anchor.get("skills")),
            *_items(anchor.get("keywords")),
            *[
                skill
                for project in projects
                for skill in _items(project.get("skills"))
            ],
        ]
    )
    job_core_skills = _dedup_slugs(
        [
            *_items(job.get("required_skills")),
            *_items(job.get("preferred_skills")),
            *_items(job.get("skills")),
        ]
    )
    normalized_target_skills = _dedup_slugs(target_skills or [])
    failure_categories = _failure_categories(pending_contract_hints)
    anchor_terms = _anchor_terms(anchor, projects)
    direction_tags, role_tags = resolve_question_bank_tags(
        job_spec=job,
        runtime_config=runtime_config,
    )

    anchor_confidence = _anchor_confidence(
        projects=projects,
        candidate_skills=candidate_skills,
        job_core_skills=job_core_skills,
        target_skills=normalized_target_skills,
        anchor_terms=anchor_terms,
    )
    generic_risk = _generic_risk(
        projects=projects,
        candidate_skills=candidate_skills,
        job_core_skills=job_core_skills,
        target_skills=normalized_target_skills,
        anchor_confidence=anchor_confidence,
    )

    return QuestionFitProfile(
        dimension=_slugify(dimension),
        turn_intent=_slugify(probe_intent) or "",
        direction_tags=direction_tags,
        role_tags=role_tags,
        candidate_projects=projects,
        candidate_skills=candidate_skills,
        job_core_skills=job_core_skills,
        target_skills=normalized_target_skills,
        failure_categories=failure_categories,
        anchor_confidence=anchor_confidence,
        generic_risk=generic_risk,
        resume_anchor_terms=anchor_terms,
    )


def format_candidate_anchor_block(
    profile: QuestionFitProfile,
    candidate: Any,
) -> str:
    """Render rule-only grounding hints for the Generator.

    The text intentionally avoids seed/variant ids and internal answer
    signals. It is a candidate/JD grounding block, not a provenance block.
    """

    if not profile or candidate is None:
        return ""
    lines = [
        f"Anchor confidence: {profile.anchor_confidence}",
        f"Generic risk: {profile.generic_risk}",
    ]
    project = profile.candidate_projects[0] if profile.candidate_projects else {}
    if project:
        lines.append(f"Candidate project: {project.get('name') or 'unspecified'}")
        summary = str(project.get("summary") or "").strip()
        if summary:
            lines.append(f"Project summary: {summary[:240]}")
        skills = [str(item) for item in project.get("skills") or []][:6]
        if skills:
            lines.append("Project skills: " + ", ".join(skills))
    if profile.candidate_skills:
        lines.append("Candidate skills: " + ", ".join(profile.candidate_skills[:8]))
    if profile.job_core_skills:
        lines.append("Job core skills: " + ", ".join(profile.job_core_skills[:8]))
    scenario = str(getattr(candidate, "scenario_brief", "") or "").strip()
    if scenario:
        lines.append(f"Structured scenario: {scenario[:240]}")
    if profile.failure_categories:
        lines.append("Turn failure categories: " + ", ".join(profile.failure_categories[:5]))
    return "\n".join(lines)


def candidate_anchor_artifact(
    profile: QuestionFitProfile,
    candidate: Any,
) -> dict[str, Any]:
    project = profile.candidate_projects[0] if profile.candidate_projects else {}
    return {
        "variant_id": getattr(candidate, "variant_id", None),
        "title": getattr(candidate, "title", None),
        "anchor_confidence": profile.anchor_confidence,
        "generic_risk": profile.generic_risk,
        "project_name": project.get("name") if isinstance(project, dict) else None,
        "candidate_skills": list(profile.candidate_skills[:8]),
        "job_core_skills": list(profile.job_core_skills[:8]),
        "failure_categories": list(profile.failure_categories[:5]),
        "direction_tags": list(profile.direction_tags),
        "role_tags": list(profile.role_tags),
    }


def resolve_question_bank_tags(
    *,
    job_spec: dict[str, Any] | None,
    runtime_config: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Resolve structured-question direction/role tags from runtime + JD.

    The resolver is intentionally rule-only. It keeps role awareness close to
    the existing setup direction payload and avoids adding a second LLM profile
    path in the live interview loop.
    """

    job = job_spec or {}
    runtime = runtime_config or {}
    direction_tags = _dedup_slugs(
        [
            *_items(runtime.get("question_direction_tags")),
            *_items(job.get("direction_tags")),
        ]
    )
    role_tags = _dedup_slugs(
        [
            *_items(runtime.get("question_role_tags")),
            *_items(job.get("role_tags")),
        ]
    )
    if not direction_tags:
        direction_tags = _direction_tags_from_job(job)
    if not role_tags:
        role_tags = _role_tags_from_job(job)
    return direction_tags, role_tags


def _extract_projects(
    resume_parsed: dict[str, Any],
    self_intro_profile: dict[str, Any],
    resume_anchor: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_projects: list[Any] = []
    raw_projects.extend(_items(resume_parsed.get("projects"), keep_dict=True))
    raw_projects.extend(_items(self_intro_profile.get("projects"), keep_dict=True))
    if resume_anchor:
        raw_projects.insert(0, resume_anchor)

    projects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_projects:
        if not isinstance(raw, dict):
            continue
        name = _first_text(raw, ("project_name", "name", "label", "project", "title"))
        summary = " ".join(
            item
            for item in [
                _first_text(raw, ("summary", "description", "background")),
                _first_text(raw, ("role", "responsibility")),
                " ".join(_items(raw.get("highlights"))[:3]),
            ]
            if item
        ).strip()
        skills = _dedup_slugs(
            [
                *_items(raw.get("tech_stack")),
                *_items(raw.get("skills")),
                *_items(raw.get("keywords")),
            ]
        )
        key = _slugify(name) or _slugify(summary) or ",".join(skills)
        if not key or key in seen:
            continue
        seen.add(key)
        projects.append(
            {
                "name": name or "unspecified project",
                "summary": summary,
                "skills": skills,
            }
        )
    return projects[:5]


def _direction_tags_from_job(job: dict[str, Any]) -> list[str]:
    text = _job_text(job)
    lowered = text.lower()
    direction = _slugify(job.get("interview_direction") or job.get("direction"))
    if direction in {
        "product_manager",
        "operations",
        "sales_business",
        "marketing_brand",
        "hr_function",
        "customer_success",
        "general_management",
    }:
        return ["business"]
    if any(
        token in lowered
        for token in (
            "product manager",
            "product",
            "prd",
            "operation",
            "growth",
            "campaign",
            "sales",
            "business development",
            "bd",
            "crm",
            "marketing",
            "brand",
            "market",
            "channel",
            "hr",
            "human resources",
            "recruiting",
            "employee relations",
            "customer success",
            "customer support",
            "renewal",
            "retention",
            "general management",
            "team management",
            "leadership",
            "goal setting",
            "execution management",
            "\u4ea7\u54c1",
            "\u9700\u6c42",
            "\u7528\u6237\u6d1e\u5bdf",
            "\u8fd0\u8425",
            "\u589e\u957f",
            "\u6d3b\u52a8",
            "\u7559\u5b58",
            "\u8f6c\u5316",
            "\u9500\u552e",
            "\u5546\u52a1",
            "\u5ba2\u6237",
            "\u5408\u540c",
            "\u8c08\u5224",
            "\u5e02\u573a",
            "\u54c1\u724c",
            "\u8425\u9500",
            "\u6295\u653e",
            "\u6e20\u9053",
        )
    ):
        return ["business"]
    if direction in {
        "java_backend",
        "frontend",
        "sre",
        "ai_fullstack",
        "ai_agent",
        "mobile",
        "ai_algorithm",
        "architect",
    }:
        return ["internet_tech"]
    if any(token in text for token in ("互联网技术", "技术", "frontend", "sre", "devops")):
        return ["internet_tech"]
    if any(
        token in text.lower()
        for token in (
            "java",
            "backend",
            "react",
            "kubernetes",
            "redis",
            "microservices",
            "mysql",
            "kafka",
            "spring",
            "agent",
            "llm",
            "rag",
            "android",
            "ios",
            "flutter",
            "react-native",
            "pytorch",
            "tensorflow",
            "algorithm",
            "architect",
            "architecture",
            "staff",
        )
    ):
        return ["internet_tech"]
    return []


def _role_tags_from_job(job: dict[str, Any]) -> list[str]:
    direction = _slugify(job.get("interview_direction") or job.get("direction"))
    if direction in {
        "product_manager",
        "operations",
        "sales_business",
        "marketing_brand",
        "hr_function",
        "customer_success",
        "general_management",
    }:
        return [direction]
    if direction == "frontend":
        return ["frontend_web"]
    if direction in {
        "java_backend",
        "sre",
        "ai_agent",
        "ai_fullstack",
        "mobile",
        "ai_algorithm",
        "architect",
    }:
        return [direction]

    text = _job_text(job)
    lowered = text.lower()
    if any(
        token in lowered
        for token in (
            "product manager",
            "pm",
            "prd",
            "requirement",
            "roadmap",
            "user insight",
            "prioritization",
            "\u4ea7\u54c1",
            "\u9700\u6c42",
            "\u7528\u6237\u6d1e\u5bdf",
            "\u8def\u7ebf\u56fe",
            "\u6307\u6807",
        )
    ):
        return ["product_manager"]
    if any(
        token in lowered
        for token in (
            "operation",
            "operations",
            "growth",
            "retention",
            "conversion",
            "community",
            "content operation",
            "\u8fd0\u8425",
            "\u589e\u957f",
            "\u6d3b\u52a8",
            "\u5185\u5bb9",
            "\u793e\u7fa4",
            "\u7559\u5b58",
            "\u8f6c\u5316",
            "\u590d\u76d8",
        )
    ):
        return ["operations"]
    if any(
        token in lowered
        for token in (
            "sales",
            "business development",
            "bd",
            "customer discovery",
            "pipeline",
            "negotiation",
            "contract",
            "crm",
            "\u9500\u552e",
            "\u5546\u52a1",
            "\u5ba2\u6237\u5f00\u53d1",
            "\u5546\u673a",
            "\u5408\u540c",
            "\u8c08\u5224",
        )
    ):
        return ["sales_business"]
    if any(
        token in lowered
        for token in (
            "marketing",
            "brand",
            "market",
            "campaign",
            "channel",
            "media buying",
            "content creativity",
            "\u5e02\u573a",
            "\u54c1\u724c",
            "\u8425\u9500",
            "\u6295\u653e",
            "\u6e20\u9053",
            "\u5185\u5bb9\u521b\u610f",
        )
    ):
        return ["marketing_brand"]
    if any(
        token in lowered
        for token in (
            "hr",
            "human resources",
            "recruiting",
            "talent acquisition",
            "employee relations",
            "organization development",
            "policy compliance",
        )
    ):
        return ["hr_function"]
    if any(
        token in lowered
        for token in (
            "customer success",
            "customer support",
            "support specialist",
            "issue diagnosis",
            "escalation",
            "renewal",
            "retention",
            "sla",
        )
    ):
        return ["customer_success"]
    if any(
        token in lowered
        for token in (
            "general management",
            "team management",
            "people manager",
            "goal setting",
            "team leadership",
            "decision making",
            "execution management",
            "cross functional",
            "cross-functional",
        )
    ):
        return ["general_management"]
    if any(
        token in lowered
        for token in (
            "ai agent",
            "agent",
            "tool calling",
            "tool-calling",
            "langchain",
            "langgraph",
        )
    ) or any(token in text for token in ("智能体", "工具调用", "上下文", "记忆")):
        return ["ai_agent"]
    if any(token in lowered for token in ("ai fullstack", "fullstack", "llm app")) or any(
        token in text for token in ("AI 全栈", "全栈", "AI应用", "AI 应用")
    ):
        return ["ai_fullstack"]
    if any(
        token in lowered
        for token in ("android", "ios", "flutter", "react native", "react-native", "mobile")
    ) or any(token in text for token in ("移动端", "小程序", "端侧")):
        return ["mobile"]
    if any(
        token in lowered
        for token in (
            "machine learning",
            "deep learning",
            "pytorch",
            "tensorflow",
            "algorithm",
            "model evaluation",
        )
    ) or any(token in text for token in ("算法", "模型", "机器学习", "深度学习", "评估")):
        return ["ai_algorithm"]
    if any(
        token in lowered
        for token in ("architect", "architecture", "staff", "technical expert")
    ) or any(token in text for token in ("架构师", "技术专家", "复杂系统", "技术治理")):
        return ["architect"]
    if any(token in lowered for token in ("sre", "devops", "site reliability")) or any(
        token in text for token in ("运维", "稳定性")
    ):
        return ["sre"]
    if any(token in lowered for token in ("frontend", "react", "vue", "web", "h5")) or any(
        token in text for token in ("前端", "小程序")
    ):
        return ["frontend_web"]
    if any(
        token in lowered
        for token in ("java", "backend", "spring", "redis", "mysql", "kafka", "microservices")
    ) or "后端" in text:
        return ["java_backend"]
    return []


def _job_text(job: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "interview_direction",
        "interview_direction_label",
        "direction",
        "role_id",
        "target_role",
        "title",
        "default_title",
    ):
        values.extend(str(item) for item in _items(job.get(key)))
    values.extend(str(item) for item in _items(job.get("required_skills")))
    values.extend(str(item) for item in _items(job.get("skills")))
    return " ".join(values)


def _anchor_confidence(
    *,
    projects: list[dict[str, Any]],
    candidate_skills: list[str],
    job_core_skills: list[str],
    target_skills: list[str],
    anchor_terms: list[str],
) -> str:
    if projects and anchor_terms and (
        set(candidate_skills) & (set(job_core_skills) | set(target_skills) | set(anchor_terms))
    ):
        return "high"
    if projects or candidate_skills or target_skills:
        return "medium"
    return "low"


def _generic_risk(
    *,
    projects: list[dict[str, Any]],
    candidate_skills: list[str],
    job_core_skills: list[str],
    target_skills: list[str],
    anchor_confidence: str,
) -> str:
    if anchor_confidence == "high" and projects and (candidate_skills or target_skills):
        return "low"
    if projects or candidate_skills or job_core_skills or target_skills:
        return "medium"
    return "high"


def _failure_categories(hints: dict[str, Any] | None) -> list[str]:
    if not isinstance(hints, dict):
        return []
    multi = hints.get("failure_categories")
    if isinstance(multi, list):
        return _dedup_slugs(multi)
    single = hints.get("failure_category")
    return _dedup_slugs([single] if single else [])


def _anchor_terms(anchor: dict[str, Any], projects: list[dict[str, Any]]) -> list[str]:
    values: list[Any] = []
    values.extend(_items(anchor.get("project_name")))
    values.extend(_items(anchor.get("name")))
    values.extend(_items(anchor.get("label")))
    values.extend(_items(anchor.get("tech_stack")))
    values.extend(_items(anchor.get("skills")))
    values.extend(_items(anchor.get("keywords")))
    for project in projects:
        values.append(project.get("name"))
        values.extend(project.get("skills") or [])
    return _dedup_slugs(values)


def _items(value: Any, *, keep_dict: bool = False) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if keep_dict or str(item or "").strip()]
    if isinstance(value, tuple | set):
        return [item for item in value if keep_dict or str(item or "").strip()]
    if keep_dict and isinstance(value, dict):
        return [value]
    text = str(value).strip()
    return [text] if text else []


def _first_text(raw: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _dedup_slugs(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        slug = _slugify(value)
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")
