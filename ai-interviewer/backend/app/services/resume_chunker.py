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
    cleaned = line.strip().strip(":").lower()
    return any(cleaned == header or cleaned.startswith(f"{header}:") for header in _SECTION_HEADERS)


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
    if parsed_chunks:
        return parsed_chunks

    chunks: list[ResumeChunk] = []
    project_lines: dict[str, list[str]] = {}
    current_section = ""
    current_project: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_section_header(line):
            current_section = line.strip(":").lower()
            current_project = None
            continue
        if "skill" in current_section or "技能" in current_section:
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
        summary = " ".join(lines)[:500]
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
    all_chunks = project_chunks + chunks
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
        for index, chunk in enumerate(all_chunks)
    ]


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
        summary_parts = [
            project_name,
            str(project.get("role") or "").strip(),
            " ".join(str(item) for item in _as_list(project.get("achievements"))),
        ]
        summary = " ".join(part for part in summary_parts if part).strip()
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
        for item in _as_list(project.get("highlights")):
            body = str(item).strip()
            if body:
                chunks.append(
                    _make_chunk(
                        len(chunks),
                        "highlight",
                        "projects",
                        _heading_from_text(body),
                        project_name,
                        body,
                    )
                )
    return chunks


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


def _is_projectish_section(section: str) -> bool:
    return (
        "project" in section
        or "experience" in section
        or "项目" in section
        or "经历" in section
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
