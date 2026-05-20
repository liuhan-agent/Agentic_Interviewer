"""Self-adaptive chunking for session-scoped resume anchors."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.settings import get_settings


class ResumeChunkerMode(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


_MODE_A_MAX_CHUNKS = 24
_MODE_A_MAX_DETAIL_CHUNKS_PER_PROJECT = 8


@dataclass(frozen=True)
class ResumeChunk:
    chunk_index: int
    tier: str
    section_name: str | None
    heading: str | None
    project_name: str | None
    text: str
    tech_keywords: list[str]
    dimensions_hint: list[str]


# Expanded dictionaries for Chinese/module-style resumes. These replace the
# compact bootstrap values above before any chunking function is called.
_SECTION_HEADERS = (
    "项目经验",
    "工作经历",
    "专业项目",
    "教育背景",
    "projects",
    "project experience",
    "experience",
    "work experience",
    "education",
    "skills",
)

_TECH_KEYWORDS = (
    "Spring Cloud",
    "Spring Boot",
    "MyBatis-Plus",
    "Elasticsearch",
    "ElasticSearch",
    "PostgreSQL",
    "RabbitMQ",
    "Kubernetes",
    "Prometheus",
    "LangChain",
    "ClickHouse",
    "Java",
    "Python",
    "React",
    "Redis",
    "Kafka",
    "Flink",
    "Docker",
    "MySQL",
    "SQLite",
    "Lua",
    "SQL",
    "API",
)

_CANONICAL_TECH = {
    "elasticsearch": "Elasticsearch",
    "elasticSearch".lower(): "Elasticsearch",
    "mybatis-plus": "MyBatis-Plus",
    "spring boot": "Spring Boot",
    "spring cloud": "Spring Cloud",
    "postgresql": "PostgreSQL",
    "rabbitmq": "RabbitMQ",
    "kubernetes": "Kubernetes",
    "prometheus": "Prometheus",
    "langchain": "LangChain",
    "clickhouse": "ClickHouse",
    "sqlite": "SQLite",
    "mysql": "MySQL",
    "api": "API",
}

_DIMENSION_BY_KEYWORD = {
    "Redis": ["system_design", "technical_depth"],
    "Lua": ["technical_depth", "coding_quality"],
    "RabbitMQ": ["system_design", "technical_depth"],
    "Kafka": ["system_design", "data_analysis"],
    "Flink": ["data_analysis", "technical_depth"],
    "Elasticsearch": ["system_design", "data_analysis"],
    "Kubernetes": ["system_design", "architecture"],
    "Prometheus": ["system_design", "debugging"],
    "Spring Boot": ["coding_quality", "technical_depth"],
    "Spring Cloud": ["system_design", "architecture"],
    "Java": ["coding_quality", "technical_depth"],
    "Python": ["coding_quality", "technical_depth"],
    "React": ["frontend", "coding_quality"],
    "SQL": ["data_analysis", "technical_depth"],
    "PostgreSQL": ["data_analysis", "system_design"],
    "MySQL": ["data_analysis", "system_design"],
}

_DIMENSION_ORDER = (
    "system_design",
    "architecture",
    "technical_depth",
    "coding_quality",
    "debugging",
    "data_analysis",
    "frontend",
    "project_experience",
)

_OCR_FIXES = {
    "SpringBoot": "Spring Boot",
    "Elastic Search": "Elasticsearch",
    "Java +8": "Java 8",
}

_INLINE_SPACE_RE = re.compile(r"[ \t\f\v\u00a0\u2009]+")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_DATE_RE = re.compile(
    r"(?:19|20)\d{2}(?:[./-]\d{1,2}|年\s*\d{1,2}\s*月)?"
    r"(?:\s*[-~至]\s*(?:19|20)?\d{0,2}(?:[./-]\d{1,2}|年\s*\d{1,2}\s*月)?)?"
)


_SECTION_HEADERS = (
    "项目经历",
    "项目经验",
    "项目",
    "个人项目",
    "专业项目",
    "工作经历",
    "工作经验",
    "实习经历",
    "实习经验",
    "教育背景",
    "专业技能",
    "技能",
    "技能清单",
    "技术栈",
    "projects",
    "project experience",
    "experience",
    "work experience",
    "education",
    "skills",
)

_TECH_KEYWORDS = (
    "Spring Cloud",
    "Spring Boot",
    "Spring Security",
    "Spring AI",
    "SpringAI",
    "MyBatis-Plus",
    "Elasticsearch",
    "ElasticSearch",
    "PostgreSQL",
    "RabbitMQ",
    "Kubernetes",
    "Prometheus",
    "LangChain",
    "LangChainj",
    "XXL-JOB",
    "Flowable",
    "WebSocket",
    "IoT",
    "Nacos",
    "OpenFeign",
    "Redisson",
    "RAG",
    "MCP",
    "Tool Calling",
    "FunctionScoreQuery",
    "ClickHouse",
    "ZSet",
    "JUC",
    "Java",
    "Python",
    "React",
    "Redis",
    "Kafka",
    "Flink",
    "Docker",
    "MySQL",
    "SQLite",
    "Lua",
    "SQL",
    "API",
)

_CANONICAL_TECH.update(
    {
        "spring security": "Spring Security",
        "spring ai": "SpringAI",
        "springai": "SpringAI",
        "xxl-job": "XXL-JOB",
        "flowable": "Flowable",
        "websocket": "WebSocket",
        "iot": "IoT",
        "nacos": "Nacos",
        "openfeign": "OpenFeign",
        "redisson": "Redisson",
        "rag": "RAG",
        "mcp": "MCP",
        "tool calling": "Tool Calling",
        "functionscorequery": "FunctionScoreQuery",
        "zset": "ZSet",
        "juc": "JUC",
        "langchainj": "LangChainj",
    }
)

_DIMENSION_BY_KEYWORD.update(
    {
        "Spring Security": ["coding_quality", "system_design"],
        "XXL-JOB": ["system_design", "debugging"],
        "Flowable": ["architecture", "system_design"],
        "LangChain": ["technical_depth", "system_design"],
        "LangChainj": ["technical_depth", "system_design"],
        "SpringAI": ["technical_depth", "system_design"],
        "WebSocket": ["system_design", "technical_depth"],
        "IoT": ["system_design", "architecture"],
        "RAG": ["technical_depth", "system_design"],
        "MCP": ["architecture", "technical_depth"],
        "Nacos": ["architecture", "system_design"],
        "OpenFeign": ["architecture", "system_design"],
        "Redisson": ["system_design", "technical_depth"],
    }
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•·▪●]\s*|\d+[.)、]\s+)")
_DATE_RE = re.compile(
    r"(?:19|20)\d{2}\s*(?:[./-]\s*\d{1,2}|年\s*\d{1,2}\s*月?)?"
    r"(?:\s*[-~至到–—]\s*(?:(?:19|20)\d{2}\s*)?"
    r"(?:[./-]?\s*\d{1,2}|年\s*\d{1,2}\s*月?)?)?"
)


def normalize_resume_text(raw: str) -> str:
    """Normalize noisy resume text while preserving useful line structure."""

    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _ZERO_WIDTH_RE.sub("", text)
    for source, target in _OCR_FIXES.items():
        text = text.replace(source, target)
    text = _normalise_ascii_punctuation(text)
    lines = [_INLINE_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    compact_lines: list[str] = []
    blank_seen = False
    for line in lines:
        if not line:
            if not blank_seen:
                compact_lines.append("")
            blank_seen = True
            continue
        compact_lines.append(line)
        blank_seen = False
    return "\n".join(compact_lines).strip()


def detect_resume_structure(text: str, parsed: dict | None) -> ResumeChunkerMode:
    normalized = normalize_resume_text(text)
    if not normalized:
        return ResumeChunkerMode.D
    if len(normalized) < int(get_settings().resume_rag_min_text_chars or 500):
        return ResumeChunkerMode.D

    parsed = parsed if isinstance(parsed, dict) else {}
    projects = parsed.get("projects")
    focus_areas = parsed.get("focus_areas")
    if isinstance(projects, list) and len(projects) >= 2:
        if isinstance(focus_areas, list) and focus_areas:
            return ResumeChunkerMode.A

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    section_headers = sum(1 for line in lines if _is_section_header(line))
    sub_items = sum(1 for line in lines if _BULLET_RE.match(line))
    date_ranges = len(_DATE_RE.findall(normalized))
    tech_hits = len(extract_tech_keywords(normalized))

    if section_headers and sub_items >= 3 and date_ranges >= 1:
        return ResumeChunkerMode.A
    if section_headers and date_ranges >= 1:
        return ResumeChunkerMode.B
    if section_headers + sub_items + date_ranges + tech_hits >= 3:
        return ResumeChunkerMode.C
    return ResumeChunkerMode.C


def chunk_resume(
    text: str,
    parsed: dict | None,
) -> tuple[ResumeChunkerMode, list[ResumeChunk]]:
    normalized = normalize_resume_text(text)
    mode = detect_resume_structure(normalized, parsed)
    if not normalized:
        return mode, []
    if mode is ResumeChunkerMode.A:
        return mode, _chunk_mode_a(normalized, parsed)
    if mode is ResumeChunkerMode.B:
        return mode, _chunk_mode_b(normalized)
    if mode is ResumeChunkerMode.C:
        return mode, _chunk_mode_c(normalized)
    return mode, [_make_chunk(0, "full", None, None, None, normalized)]


def extract_tech_keywords(text: str) -> list[str]:
    value = str(text or "")
    if not value.strip():
        return []
    found: list[str] = []
    seen: set[str] = set()
    for keyword in _TECH_KEYWORDS:
        if _contains_keyword(value, keyword):
            canonical = _CANONICAL_TECH.get(keyword.lower(), keyword)
            if canonical not in seen:
                found.append(canonical)
                seen.add(canonical)
        if len(found) >= 16:
            break
    if len(found) < 3:
        for keyword in _llm_extract_tech_keywords(value):
            if keyword not in seen:
                found.append(keyword)
                seen.add(keyword)
            if len(found) >= 16:
                break
    return found[:16]


def infer_dimensions_hint(text: str, tech_keywords: list[str]) -> list[str]:
    del text
    values: set[str] = {"project_experience"} if tech_keywords else set()
    for keyword in tech_keywords:
        for dimension in _DIMENSION_BY_KEYWORD.get(keyword, []):
            values.add(dimension)
    return [dimension for dimension in _DIMENSION_ORDER if dimension in values]


def _normalise_ascii_punctuation(text: str) -> str:
    replacements = {
        "\uff0c": ",",
        "\uff1a": ":",
        "\uff1b": ";",
        "\uff08": "(",
        "\uff09": ")",
        "\uff0f": "/",
        "\uff0b": "+",
    }
    for source, target in replacements.items():
        suffix = " " if target in {",", ";", ":"} else ""
        text = re.sub(
            rf"(?<=[A-Za-z0-9])\s*{re.escape(source)}\s*(?=[A-Za-z0-9])",
            f"{target}{suffix}",
            text,
        )
    return text


def _is_section_header(line: str) -> bool:
    cleaned = line.strip().strip(":：").lower()
    return any(
        cleaned == header
        or cleaned.startswith(f"{header}:")
        or cleaned.startswith(f"{header}：")
        for header in _SECTION_HEADERS
    )


def _contains_keyword(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword)
    if keyword.replace("-", "").replace("+", "").replace(" ", "").isalnum():
        pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    else:
        pattern = escaped
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _llm_extract_tech_keywords(text: str) -> list[str]:
    del text
    return []


def _chunk_mode_a(text: str, parsed: dict | None) -> list[ResumeChunk]:
    parsed = parsed if isinstance(parsed, dict) else {}
    parsed_chunks = _chunks_from_parsed_projects(parsed)
    parsed_chunks.extend(_chunks_from_parsed_focus_areas(parsed))
    parsed_chunks.extend(_chunks_from_parsed_skills(parsed))
    raw_chunks = _chunks_from_raw_mode_a(text)
    merged_chunks = _dedupe_and_cap_mode_a_chunks([*parsed_chunks, *raw_chunks])
    if merged_chunks:
        return merged_chunks
    return []


def _chunks_from_parsed_projects(parsed: dict[str, Any]) -> list[ResumeChunk]:
    projects = parsed.get("projects")
    if not isinstance(projects, list) or not projects:
        return []
    chunks: list[ResumeChunk] = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        project_name = str(
            project.get("name") or project.get("project_name") or "Project"
        ).strip()
        role = str(project.get("role") or "").strip()
        tech_stack = _as_text_list(project.get("tech_stack"), limit=10)
        responsibilities = _as_text_list(project.get("responsibilities"), limit=4)
        achievements = _as_text_list(project.get("achievements"), limit=4)
        summary_parts = [
            project_name,
            role,
            _labelled_list("技术栈", tech_stack),
            _labelled_list("职责", responsibilities[:2]),
            _labelled_list("成果", achievements[:2]),
        ]
        summary = _join_parts(summary_parts, max_chars=700)
        if summary:
            chunks.append(
                _make_chunk(
                    len(chunks),
                    "project",
                    "projects",
                    project_name,
                    project_name,
                    summary,
                )
            )
        for field, label in (
            ("responsibilities", "职责"),
            ("achievements", "成果"),
            ("question_anchors", "追问锚点"),
            ("highlights", "亮点"),
        ):
            for item in _as_text_list(project.get(field)):
                body = _parsed_project_detail_text(
                    project_name=project_name,
                    tech_stack=tech_stack,
                    label=label,
                    item=item,
                )
                if body:
                    chunks.append(
                        _make_chunk(
                            len(chunks),
                            "highlight",
                            "projects",
                            _heading_from_text(item),
                            project_name,
                            body,
                        )
                    )
    return chunks


def _chunks_from_parsed_focus_areas(parsed: dict[str, Any]) -> list[ResumeChunk]:
    focus_areas = parsed.get("focus_areas")
    if not isinstance(focus_areas, list):
        return []
    chunks: list[ResumeChunk] = []
    for focus in focus_areas[:6]:
        if not isinstance(focus, dict):
            continue
        label = str(focus.get("label") or focus.get("name") or "").strip()
        skills = _as_text_list(
            focus.get("skills") or focus.get("tech_stack") or focus.get("keywords"),
            limit=8,
        )
        highlights = _as_text_list(
            focus.get("highlights")
            or focus.get("question_anchors")
            or focus.get("evidence"),
            limit=3,
        )
        body = _join_parts(
            [
                label,
                _labelled_list("技能", skills),
                _labelled_list("证据", highlights),
            ],
            max_chars=500,
        )
        if not body:
            continue
        chunks.append(
            _make_chunk(
                len(chunks),
                "focus",
                "focus_areas",
                label or _heading_from_text(body),
                str(focus.get("project_name") or "").strip() or None,
                body,
            )
        )
    return chunks


def _chunks_from_parsed_skills(parsed: dict[str, Any]) -> list[ResumeChunk]:
    skills = _as_text_list(parsed.get("skills"), limit=24)
    if not skills:
        return []
    return [
        _make_chunk(
            0,
            "skill",
            "skills",
            "skills",
            None,
            _labelled_list("技能", skills),
        )
    ]


def _chunks_from_raw_mode_a(text: str) -> list[ResumeChunk]:
    chunks: list[ResumeChunk] = []
    project_lines: dict[str, list[str]] = {}
    current_section = ""
    current_project: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_section_header(line):
            current_section = line.strip().strip(":：").lower()
            current_project = None
            continue
        if _is_skill_section(current_section):
            if _looks_like_skill_line(line):
                chunk_text = _BULLET_RE.sub("", line).strip()
                chunks.append(
                    _make_chunk(
                        len(chunks),
                        "skill",
                        "skills",
                        chunk_text[:80],
                        None,
                        chunk_text,
                    )
                )
            continue
        if _is_projectish_section(current_section):
            if _BULLET_RE.match(line):
                body = _BULLET_RE.sub("", line).strip()
                project_lines.setdefault(current_project or "Project", []).append(body)
                chunks.append(
                    _make_chunk(
                        len(chunks),
                        "highlight",
                        current_section,
                        _heading_from_text(body),
                        current_project,
                        body,
                    )
                )
                continue
            if _DATE_RE.search(line) or "|" in line:
                current_project = _project_name_from_heading(line)
                project_lines.setdefault(current_project, [line])
                continue
    project_chunks: list[ResumeChunk] = []
    for project_name, lines in project_lines.items():
        summary = " ".join(lines)[:700]
        project_chunks.append(
            _make_chunk(
                len(project_chunks),
                "project",
                "projects",
                project_name,
                project_name,
                summary,
            )
        )
    return _reindex_chunks([*project_chunks, *chunks])


def _dedupe_and_cap_mode_a_chunks(chunks: list[ResumeChunk]) -> list[ResumeChunk]:
    seen: set[tuple[str, str, str]] = set()
    detail_counts_by_project: dict[str, int] = {}
    result: list[ResumeChunk] = []
    for chunk in chunks:
        if not chunk.text.strip():
            continue
        key = _chunk_dedupe_key(chunk)
        if key in seen:
            continue
        if chunk.tier == "highlight" and chunk.project_name:
            project_key = _normalise_dedupe_text(chunk.project_name)
            detail_count = detail_counts_by_project.get(project_key, 0)
            if detail_count >= _MODE_A_MAX_DETAIL_CHUNKS_PER_PROJECT:
                continue
            detail_counts_by_project[project_key] = detail_count + 1
        seen.add(key)
        result.append(chunk)
        if len(result) >= _MODE_A_MAX_CHUNKS:
            break
    return _reindex_chunks(result)


def _chunk_dedupe_key(chunk: ResumeChunk) -> tuple[str, str, str]:
    heading = chunk.heading or chunk.text[:96]
    return (
        _normalise_dedupe_text(chunk.tier),
        _normalise_dedupe_text(chunk.project_name or ""),
        _normalise_dedupe_text(heading),
    )


def _reindex_chunks(chunks: list[ResumeChunk]) -> list[ResumeChunk]:
    return [
        ResumeChunk(
            chunk_index=index,
            tier=chunk.tier,
            section_name=chunk.section_name,
            heading=chunk.heading,
            project_name=chunk.project_name,
            text=chunk.text,
            tech_keywords=chunk.tech_keywords,
            dimensions_hint=chunk.dimensions_hint,
        )
        for index, chunk in enumerate(chunks)
    ]


def _parsed_project_detail_text(
    *,
    project_name: str,
    tech_stack: list[str],
    label: str,
    item: str,
) -> str:
    return _join_parts(
        [
            project_name,
            _labelled_list("技术栈", tech_stack[:8]),
            f"{label}: {item}",
        ],
        max_chars=700,
    )


def _labelled_list(label: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"{label}: {', '.join(items)}"


def _join_parts(parts: list[str], *, max_chars: int) -> str:
    body = "。".join(part.strip().strip("。") for part in parts if part.strip())
    return body[:max_chars].strip()


def _normalise_dedupe_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _as_text_list(value: Any, *, limit: int | None = None) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    elif isinstance(value, str):
        raw_values = [value]
    else:
        raw_values = []
    values: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            item = (
                item.get("label")
                or item.get("name")
                or item.get("text")
                or item.get("summary")
                or item.get("description")
            )
        text = " ".join(str(item or "").split())
        if text:
            values.append(text)
        if limit is not None and len(values) >= limit:
            break
    return values


def _chunk_mode_b(text: str) -> list[ResumeChunk]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _DATE_RE.search(stripped) and current:
            sections.append(current)
            current = [stripped]
        else:
            current.append(stripped)
    if current:
        sections.append(current)
    chunks: list[ResumeChunk] = []
    for section in sections:
        body = " ".join(section).strip()
        if not body or not _DATE_RE.search(body):
            continue
        chunks.append(
            _make_chunk(
                len(chunks),
                "section",
                "experience",
                _heading_from_text(body),
                None,
                body,
            )
        )
    if not chunks:
        return _chunk_mode_c(text)
    return chunks


def _chunk_mode_c(text: str) -> list[ResumeChunk]:
    window = 300
    overlap = 60
    if len(text) <= window:
        return [_make_chunk(0, "window", None, None, None, text)]
    chunks: list[ResumeChunk] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + window)
        if end < len(text):
            boundary = max(text.rfind(".", start, end), text.rfind("\n", start, end))
            if boundary > start + 120:
                end = boundary + 1
        body = text[start:end].strip()
        if body:
            chunks.append(_make_chunk(len(chunks), "window", None, None, None, body))
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _make_chunk(
    chunk_index: int,
    tier: str,
    section_name: str | None,
    heading: str | None,
    project_name: str | None,
    text: str,
) -> ResumeChunk:
    keywords = extract_tech_keywords(text)
    return ResumeChunk(
        chunk_index=chunk_index,
        tier=tier,
        section_name=section_name,
        heading=heading,
        project_name=project_name,
        text=text,
        tech_keywords=keywords,
        dimensions_hint=infer_dimensions_hint(text, keywords),
    )


def _looks_like_skill_line(line: str) -> bool:
    clean = _BULLET_RE.sub("", line).strip()
    return bool(extract_tech_keywords(clean))


def _is_skill_section(section: str) -> bool:
    return "skill" in section or "技能" in section or "技术栈" in section


def _is_projectish_section(section: str) -> bool:
    return (
        "project" in section
        or "experience" in section
        or "项目" in section
        or "工作经历" in section
        or "工作经验" in section
        or "实习经历" in section
        or "实习经验" in section
    )


def _project_name_from_heading(line: str) -> str:
    head = _DATE_RE.sub("", line).strip(" |-/")
    if "|" in head:
        return head.split("|", 1)[0].strip() or "Project"
    return head or "Project"


def _heading_from_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    return value[:96]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
