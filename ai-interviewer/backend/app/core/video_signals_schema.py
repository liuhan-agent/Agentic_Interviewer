"""Shared validation schema for ``video_signals`` answer payloads.

Both the HTTP ``POST /sessions/{id}/answer`` endpoint and the WebSocket
``stop`` frame must accept the same MediaPipe-derived signals so that
the evaluator prompt receives a consistent dict shape regardless of
which channel submitted the answer. Centralising the schema here also
keeps the surface narrow: clients can send only the four documented
fields, with strict ranges, instead of a free-form ``dict[str, Any]``
that downstream consumers have to reinterpret.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VideoSignalsEmotion = Literal["neutral", "positive", "nervous", "confused"]


class VideoSignalsInput(BaseModel):
    """Aggregated face-analysis signal for a single answer turn.

    The client (camera component) windows MediaPipe samples between
    ``record_start`` and ``stop`` and reports the aggregate confidence
    and engagement scores plus the dominant emotion bucket. Empty
    payloads (``None``) are accepted upstream when the camera is off
    or the user disabled video analysis.
    """

    model_config = ConfigDict(extra="forbid")

    confidence: float = Field(ge=0, le=1)
    engagement: float = Field(ge=0, le=1)
    dominant_emotion: VideoSignalsEmotion
    sample_count: int = Field(ge=1, le=1000)
