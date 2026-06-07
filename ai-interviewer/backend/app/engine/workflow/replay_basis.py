"""Candidate-facing context and question basis projections for replay."""
from __future__ import annotations

from typing import Any

CONTEXT_BASIS_TITLE = "开场与简历线索"
QUESTION_BASIS_TITLE = "为什么问这一题"

_FORBIDDEN_QUESTION_KEYS = {
    "resume_anchor",
    "skill_focus",
    "focus_source",
    "pending_contract_hints",
    "recommended_probe_intent",
}

_DIMENSION_LABELS = {
    "technical_depth": "技术深度",
    "problem_solving": "问题解决",
    "communication": "沟通表达",
    "system_design": "系统设计",
    "coding_quality": "代码质量",
    "project_experience": "项目经验",
    "product_thinking": "产品思维",
    "architecture": "架构能力",
    "behavioral": "行为面试",
    "leadership": "技术领导力",
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def _dict_list_labels(value: Any, key: str, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return _string_list(
        [item.get(key) for item in value if isinstance(item, dict)],
        limit=limit,
    )


def _dedupe(values: list[Any], *, limit: int | None = None) -> list[str]:
    return _string_list(values, limit=limit)


def _dimension_label(dimension: Any) -> str:
    raw = _clean_text(dimension)
    return _DIMENSION_LABELS.get(raw, raw.replace("_", " ") if raw else "")


def _anchor_label(anchor: dict[str, Any]) -> str:
    for key in ("project_name", "label", "role"):
        value = _clean_text(anchor.get(key))
        if value:
            return value
    return ""


def _target_skills(target_skills: Any, resume_anchor: dict[str, Any]) -> list[str]:
    skills: list[Any] = []
    skills.extend(target_skills if isinstance(target_skills, list) else [])
    skills.extend(resume_anchor.get("skills") or [])
    skills.extend(resume_anchor.get("tech_stack") or [])
    return _dedupe(skills, limit=4)


def _skill_text(skills: list[str]) -> str:
    return "、".join(skills[:3]) if skills else "关键能力"


def _join_cn(items: list[str]) -> str:
    if not items:
        return "现有结构化线索"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]}和{items[1]}"
    return "、".join(items[:-1]) + f"和{items[-1]}"


def _report_dimensions(report: dict[str, Any], *, limit: int = 8) -> list[str]:
    dimensions: list[Any] = []
    for key in ("dimension_summaries", "dimension_scores", "scores_per_dim"):
        value = report.get(key)
        if isinstance(value, dict):
            dimensions.extend(value.keys())
    return _dedupe(dimensions, limit=limit)


def _has_job_source(
    *,
    target_skills: list[str],
    skill_focus: dict[str, Any],
    job_spec: dict[str, Any],
) -> bool:
    focus_source = _clean_text(skill_focus.get("focus_source"))
    if focus_source in {"jd_uncovered", "jd_resume_overlap"}:
        return True
    jd_skills = {skill.lower() for skill in _string_list(job_spec.get("required_skills"))}
    return bool(jd_skills and any(skill.lower() in jd_skills for skill in target_skills))


_DECISION_SOURCE_VALUES = {
    "resume",
    "self_intro",
    "job",
    "followup",
    "rag",
    "question_seed",
    "skill_focus",
}
_TARGET_SKILL_SOURCE_VALUES = {
    "job_spec",
    "resume_parse_audit",
    "resume_anchor",
    "self_intro",
    "skill_focus",
}
_REASON_CODE_VALUES = {
    "covers_target_skills",
    "uses_resume_anchor",
    "uses_self_intro_anchor",
    "followup_context",
    "uses_question_seed",
    "uses_job_requirement",
}


def _injected_question_seed_selected(question_items: Any) -> bool:
    if not isinstance(question_items, list):
        return False
    for item in question_items:
        if not isinstance(item, dict):
            continue
        if item.get("injected") is not True:
            continue
        if str(item.get("seed_id") or item.get("variant_id") or "").strip():
            return True
    return False


def _resume_audit_skill_sets(resume_parse_audit: Any) -> dict[str, set[str]]:
    if not isinstance(resume_parse_audit, dict):
        return {"llm_only": set(), "rule_only": set(), "both": set()}
    summary = resume_parse_audit.get("skills_summary")
    if not isinstance(summary, dict):
        return {"llm_only": set(), "rule_only": set(), "both": set()}
    return {
        "llm_only": {item.lower() for item in _string_list(summary.get("llm_only"))},
        "rule_only": {item.lower() for item in _string_list(summary.get("rule_only"))},
        "both": {item.lower() for item in _string_list(summary.get("both"))},
    }


def _target_skill_source(
    skill: str,
    *,
    resume_anchor: dict[str, Any],
    job_spec: dict[str, Any],
    skill_focus: dict[str, Any],
    resume_parse_audit: Any,
) -> str:
    skill_key = skill.lower()
    jd_skills = {
        item.lower() for item in _string_list(job_spec.get("required_skills"))
    }
    if skill_key in jd_skills:
        return "job_spec"
    audit_sets = _resume_audit_skill_sets(resume_parse_audit)
    if any(skill_key in values for values in audit_sets.values()):
        return "resume_parse_audit"
    anchor_skill_values: list[Any] = []
    for key in ("skills", "tech_stack"):
        value = resume_anchor.get(key)
        if isinstance(value, list):
            anchor_skill_values.extend(value)
    anchor_skills = {
        item.lower()
        for item in _string_list(anchor_skill_values)
    }
    if skill_key in anchor_skills:
        return "resume_anchor"
    if _clean_text(skill_focus.get("focus_source")) == "self_intro":
        return "self_intro"
    return "skill_focus"


def build_question_decision_basis(
    *,
    dimension: Any,
    resume_anchor: dict[str, Any] | None,
    target_skills: Any,
    skill_focus: dict[str, Any] | None,
    job_spec: dict[str, Any] | None,
    refine_mode: bool,
    contract_hints: dict[str, Any] | None,
    question_items: Any = None,
    resume_parse_audit: Any = None,
) -> dict[str, Any] | None:
    anchor = resume_anchor if isinstance(resume_anchor, dict) else {}
    focus = skill_focus if isinstance(skill_focus, dict) else {}
    spec = job_spec if isinstance(job_spec, dict) else {}
    skills = _target_skills(target_skills, anchor)
    anchor_label = _anchor_label(anchor)
    focus_source = _clean_text(focus.get("focus_source"))
    from_self_intro = (
        anchor.get("knowledge_source") == "self_intro" or focus_source == "self_intro"
    )
    from_resume = bool(anchor_label and not from_self_intro)
    from_job = _has_job_source(
        target_skills=skills,
        skill_focus=focus,
        job_spec=spec,
    )
    from_followup = bool(refine_mode or (contract_hints or {}))
    from_seed = _injected_question_seed_selected(question_items)

    sources: list[str] = []
    if from_resume:
        sources.append("resume")
    if from_self_intro:
        sources.append("self_intro")
    if from_job:
        sources.append("job")
    if from_followup:
        sources.append("followup")
    if from_seed:
        sources.append("question_seed")
    if skills and not sources:
        sources.append("skill_focus")
    sources = _dedupe(sources, limit=6)

    reason_codes: list[str] = []
    if skills:
        reason_codes.append("covers_target_skills")
    if from_resume:
        reason_codes.append("uses_resume_anchor")
    if from_self_intro:
        reason_codes.append("uses_self_intro_anchor")
    if from_job:
        reason_codes.append("uses_job_requirement")
    if from_followup:
        reason_codes.append("followup_context")
    if from_seed:
        reason_codes.append("uses_question_seed")

    target_skill_items = [
        {
            "value": skill,
            "source": _target_skill_source(
                skill,
                resume_anchor=anchor,
                job_spec=spec,
                skill_focus=focus,
                resume_parse_audit=resume_parse_audit,
            ),
        }
        for skill in skills[:6]
    ]
    anchor_payload: dict[str, str] = {}
    if anchor_label:
        anchor_payload["label"] = anchor_label
    project_id = _clean_text(anchor.get("project_id"))
    if project_id:
        anchor_payload["project_id"] = project_id
    if anchor_payload:
        anchor_payload["source"] = "self_intro" if from_self_intro else "resume"

    if not any([sources, target_skill_items, anchor_payload, _clean_text(dimension)]):
        return None

    return sanitize_replay_question_decision_basis(
        {
            "version": "v1",
            "sources": sources,
            "dimension": _clean_text(dimension),
            "resume_anchor": anchor_payload,
            "target_skills": target_skill_items,
            "reason_codes": reason_codes,
        }
    )


def sanitize_replay_question_decision_basis(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if _clean_text(value.get("version")) != "v1":
        return None
    sources = [
        source
        for source in _string_list(value.get("sources"), limit=6)
        if source in _DECISION_SOURCE_VALUES
    ]
    dimension = _clean_text(value.get("dimension"))[:80]
    anchor_raw = (
        value.get("resume_anchor")
        if isinstance(value.get("resume_anchor"), dict)
        else {}
    )
    resume_anchor: dict[str, str] = {}
    label = _clean_text(anchor_raw.get("label"))[:120]
    if label:
        resume_anchor["label"] = label
    project_id = _clean_text(anchor_raw.get("project_id"))[:80]
    if project_id:
        resume_anchor["project_id"] = project_id
    anchor_source = _clean_text(anchor_raw.get("source"))
    if anchor_source in {"resume", "self_intro"} and resume_anchor:
        resume_anchor["source"] = anchor_source

    target_skills: list[dict[str, str]] = []
    raw_skills = value.get("target_skills")
    if isinstance(raw_skills, list):
        seen: set[str] = set()
        for item in raw_skills:
            if not isinstance(item, dict):
                continue
            skill = _clean_text(item.get("value"))[:80]
            source = _clean_text(item.get("source"))
            key = skill.lower()
            if not skill or key in seen or source not in _TARGET_SKILL_SOURCE_VALUES:
                continue
            seen.add(key)
            target_skills.append({"value": skill, "source": source})
            if len(target_skills) >= 6:
                break

    reason_codes = [
        code
        for code in _string_list(value.get("reason_codes"), limit=8)
        if code in _REASON_CODE_VALUES
    ]
    if not any([sources, dimension, resume_anchor, target_skills, reason_codes]):
        return None
    out: dict[str, Any] = {"version": "v1"}
    if sources:
        out["sources"] = sources
    if dimension:
        out["dimension"] = dimension
    if resume_anchor:
        out["resume_anchor"] = resume_anchor
    if target_skills:
        out["target_skills"] = target_skills
    if reason_codes:
        out["reason_codes"] = reason_codes
    return out


def build_replay_question_basis(
    *,
    dimension: Any,
    resume_anchor: dict[str, Any] | None,
    target_skills: Any,
    skill_focus: dict[str, Any] | None,
    job_spec: dict[str, Any] | None,
    refine_mode: bool,
    contract_hints: dict[str, Any] | None,
) -> dict[str, Any] | None:
    anchor = resume_anchor if isinstance(resume_anchor, dict) else {}
    focus = skill_focus if isinstance(skill_focus, dict) else {}
    spec = job_spec if isinstance(job_spec, dict) else {}
    dim_label = _dimension_label(dimension)
    anchor_label = _anchor_label(anchor)
    skills = _target_skills(target_skills, anchor)
    focus_source = _clean_text(focus.get("focus_source"))
    from_self_intro = (
        anchor.get("knowledge_source") == "self_intro" or focus_source == "self_intro"
    )
    from_resume = bool(anchor_label and not from_self_intro)
    from_job = _has_job_source(
        target_skills=skills,
        skill_focus=focus,
        job_spec=spec,
    )
    from_followup = bool(refine_mode or (contract_hints or {}))

    if not any([anchor_label, skills, dim_label, from_job, from_followup]):
        return None

    chips: list[str] = []
    if from_self_intro:
        chips.append("来自自我介绍")
    if from_resume:
        chips.append("来自简历")
    if from_job:
        chips.append("来自岗位要求")
    if dim_label:
        chips.extend(["评分维度", dim_label])
    if from_followup:
        chips.append("上一轮追问")
    chips.extend(skills)
    chips = _dedupe(chips, limit=6)

    skill_text = _skill_text(skills)
    if from_self_intro and anchor_label:
        summary = f"这题结合了你开场提到的{anchor_label}，并围绕{dim_label or '当前维度'}确认{skill_text}。"
    elif from_resume and anchor_label:
        summary = f"这题结合了简历中的{anchor_label}，并围绕{dim_label or '当前维度'}确认{skill_text}。"
    elif from_followup:
        summary = f"这题承接上一轮追问，并围绕{dim_label or '当前维度'}继续确认{skill_text}。"
    elif from_job:
        summary = f"这题围绕岗位要求中的{skill_text}，在{dim_label or '当前维度'}继续确认。"
    else:
        summary = f"这题围绕{dim_label or '当前维度'}确认{skill_text}。"

    return {
        "title": QUESTION_BASIS_TITLE,
        "summary": summary,
        "chips": chips,
    }


def sanitize_replay_question_basis(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if any(key in value for key in _FORBIDDEN_QUESTION_KEYS):
        return None
    if _clean_text(value.get("title")) != QUESTION_BASIS_TITLE:
        return None
    summary = _clean_text(value.get("summary"))
    chips = _string_list(value.get("chips"), limit=6)
    if not summary or not chips:
        return None
    return {
        "title": QUESTION_BASIS_TITLE,
        "summary": summary,
        "chips": chips,
    }


def build_replay_context_basis(
    *,
    report: dict[str, Any],
    setup_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    snapshot = setup_snapshot if isinstance(setup_snapshot, dict) else {}
    candidate = snapshot.get("candidate") if isinstance(snapshot.get("candidate"), dict) else {}
    parsed = (
        candidate.get("resume_parsed")
        if isinstance(candidate.get("resume_parsed"), dict)
        else {}
    )
    job_spec = snapshot.get("job_spec") if isinstance(snapshot.get("job_spec"), dict) else {}
    self_intro = report.get("self_intro") if isinstance(report.get("self_intro"), dict) else {}
    profile = (
        self_intro.get("profile")
        if isinstance(self_intro.get("profile"), dict)
        else {}
    )

    intro_projects = _string_list(profile.get("emphasized_projects"), limit=5)
    intro_skills = _string_list(profile.get("emphasized_skills"), limit=8)
    intro_focus = _string_list(profile.get("preferred_focus"), limit=5)

    resume_projects = _dict_list_labels(parsed.get("projects"), "name", limit=5)
    resume_focus = _dict_list_labels(parsed.get("focus_areas"), "label", limit=6)
    resume_skills = _string_list(parsed.get("skills"), limit=8)
    if not resume_skills and isinstance(parsed.get("projects"), list):
        project_skills: list[Any] = []
        for item in parsed.get("projects") or []:
            if isinstance(item, dict):
                project_skills.extend(item.get("tech_stack") or [])
        resume_skills = _dedupe(project_skills, limit=8)

    required_skills = _string_list(job_spec.get("required_skills"), limit=8)
    job_dimensions = _string_list(job_spec.get("rubric_dimensions"), limit=8)
    fallback_dimensions = [] if job_dimensions else _report_dimensions(report, limit=8)
    dimensions = job_dimensions or fallback_dimensions
    dimension_source_label = "岗位要求" if job_dimensions else "默认评分标准"
    job_title = _clean_text(job_spec.get("title"))
    job_level = _clean_text(job_spec.get("level"))
    has_self_intro = bool(intro_projects or intro_skills or intro_focus)
    has_resume = bool(resume_projects or resume_focus or resume_skills)
    has_job_spec = bool(required_skills or job_dimensions)

    if not any(
        [
            intro_projects,
            intro_skills,
            intro_focus,
            resume_projects,
            resume_focus,
            resume_skills,
            required_skills,
            dimensions,
        ]
    ):
        return None

    chips: list[str] = []
    project_count = len(_dedupe(intro_projects + resume_projects))
    skill_count = len(_dedupe(intro_skills + resume_skills + required_skills))
    dimension_count = len(dimensions)
    if project_count:
        chips.append(f"{project_count} 个项目线索")
    if skill_count:
        chips.append(f"{skill_count} 个技能线索")
    if dimension_count:
        chips.append(f"{dimension_count} 个评分维度")
    chips = _dedupe(chips, limit=8)

    source_labels: list[str] = []
    if has_self_intro:
        source_labels.append("开场自我介绍")
    if has_resume:
        source_labels.append("简历项目")
    if has_job_spec:
        source_labels.append("岗位要求")
    summary = (
        f"本场面试会结合{_join_cn(source_labels)}选择问题；"
        f"评分维度主要来自{dimension_source_label}。"
    )

    return {
        "title": CONTEXT_BASIS_TITLE,
        "summary": summary,
        "chips": chips,
        "self_intro": {
            "summary": None,
            "emphasized_projects": intro_projects,
            "emphasized_skills": intro_skills,
            "preferred_focus": intro_focus,
        },
        "resume": {
            "projects": resume_projects,
            "focus_areas": resume_focus,
            "skills": resume_skills,
        },
        "job_spec": {
            "title": job_title or None,
            "level": job_level or None,
            "required_skills": required_skills,
            "dimensions": dimensions,
            "dimension_source_label": dimension_source_label,
        },
    }
