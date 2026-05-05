"""Static generic JD templates used by the setup flow.

The templates live in ``backend/knowledge`` so product updates can be
reviewed like other interview knowledge, while the frontend only consumes a
small API shape and keeps the text editable by the user.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.job_directions import (
    InterviewDirection,
    InterviewDirectionNotFound,
    get_interview_direction,
    list_interview_directions,
)


class JobTemplateNotFound(ValueError):  # noqa: N818
    """Raised when a requested interview direction has no JD template."""


@dataclass(frozen=True)
class JobTemplate:
    direction: str
    title: str
    template: str
    skills: list[str]
    rubric_dimensions: list[str]

    def to_api_dict(self, *, level: str | None = None) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "level": level,
            "title": self.title,
            "template": self.template,
            "skills": self.skills,
            "rubric_dimensions": self.rubric_dimensions,
        }


def _from_direction(direction: InterviewDirection) -> JobTemplate:
    return JobTemplate(
        direction=direction.direction,
        title=direction.default_title,
        template=direction.template,
        skills=list(direction.skills),
        rubric_dimensions=direction.rubric_dimensions[:5],
    )


def list_job_templates() -> list[JobTemplate]:
    """Return all configured templates in direction catalog order."""
    return [_from_direction(direction) for direction in list_interview_directions()]


def get_job_template(direction: str) -> JobTemplate:
    """Return a template for the selected direction."""
    try:
        return _from_direction(get_interview_direction(direction))
    except InterviewDirectionNotFound as e:
        raise JobTemplateNotFound(direction) from e
