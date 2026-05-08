"""REST API: start an interview, poll question, submit answer, read report.

Endpoints::

    POST /api/v1/interview/sessions
        Create a session. Body = request dict (candidate + job_spec + ...).

    GET  /api/v1/interview/sessions/{session_id}/question
        Poll for the next question. Blocks up to 30 seconds.

    POST /api/v1/interview/sessions/{session_id}/answer
        Submit an answer for the current turn.

    GET  /api/v1/interview/sessions/{session_id}/report
        Retrieve the final report once status == completed.

    GET  /api/v1/interview/sessions/{session_id}/resume
        Reconnect to an interrupted session (e.g. after a process
        restart). Returns the pending question if one exists.

    POST /api/v1/interview/resume/parse
        Pre-flight upload: PDF/DOCX/TXT -> structured resume_parsed
        dict {summary, skills, highlights, projects, focus_areas}. The
        frontend uses this to pre-fill SetupForm; users can then edit
        before kicking off a session. Independent from the LangGraph
        resume_parse_node. Multipart may include optional llm_config
        JSON for a one-off resume_parser BYOK refinement.

    POST /api/v1/interview/jd/parse
        Pre-flight JD ingestion: free-text JD -> required_skills +
        rubric_dimensions + suggested_level. Lets the frontend hide
        engineering jargon (which dimensions to weight) from the
        job-seeker by inferring them from the role description. JSON
        may include optional llm_config for a one-off jd_parser BYOK
        refinement.

    GET  /api/v1/interview/dimensions
        Static catalog of evaluation dimensions with display labels.
        Used by the frontend's dimension picker.

    GET  /api/v1/interview/directions
        Static catalog of interview directions. Each direction carries
        default title / level / skills / dimension catalog and is the
        frontend source of truth for role families.

    GET  /api/v1/interview/job-template
        Static generic JD template for a selected interview direction.
        The optional level query param is echoed for future expansion
        but does not change the V1 template.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Header, HTTPException, Path, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.api_errors import api_error_detail
from app.core.idempotency import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    IdempotencyConflict,
    get_idempotency_store,
    hash_request_body,
    is_valid_idempotency_key,
)
from app.core.llm_config_schema import (
    LLM_API_KEY_MAX_LENGTH,
    LLM_BASE_URL_MAX_LENGTH,
    LLM_MODEL_MAX_LENGTH,
    LLMProvider,
)
from app.core.logging import bind_log_context, get_logger, reset_log_context
from app.core.metrics import (
    record_context_flags,
    record_rate_limit_block,
    record_setup_parse_error,
)
from app.core.rate_limit import RateLimitExceededError, check_rate_limit
from app.core.request_translator import translate_request
from app.core.session_auth import (
    hash_session_token,
    new_session_token,
    verify_session_token,
)
from app.core.session_ids import SESSION_ID_MAX_LENGTH, SESSION_ID_PATTERN
from app.core.settings import get_settings
from app.core.video_signals_schema import VideoSignalsInput
from app.core.voice_ticket import issue_voice_ticket
from app.models.base import get_session as get_db_session
from app.models.interview_session import InterviewSession
from app.services.jd_parser import (
    JDParseError,
    parse_job_spec,
)
from app.services.job_templates import JobTemplateNotFound
from app.services.interview_setup import (
    ResumeTextExtractionError,
    default_job_template_payload,
    list_dimensions_payload,
    list_directions_payload,
    parse_jd_setup_payload,
    parse_resume_setup_upload,
    resume_parse_payload,
)
from app.services.interview_feedback import (
    FEEDBACK_OUTCOME_MAP,
    save_interview_feedback,
)
from app.services.interview_question_response import build_question_poll_payload
from app.services.interview_reports import (
    attach_trace_health,
    report_payload_from_persisted_session,
)
from app.services.interview_runtime import (
    stale_session_error,
    terminal_error_payload,
    terminal_payload_from_persisted_session,
)
from app.services.privacy_cleanup import delete_session_data
from app.services.resume_parse_cache import (
    get_resume_parse_cache,
    resume_parse_cache_key,
    should_cache_resume_parse,
)
from app.services.resume_parser import (
    EXTRACT_TEXT_TIMEOUT_SECONDS,
    ResumeParseError,
    extract_text,  # noqa: F401 - module-level monkeypatch hook for parser tests.
    extract_text_with_timeout,
    parse_resume,
)
from app.services.resume_parser import (
    MAX_FILE_BYTES as MAX_RESUME_UPLOAD_BYTES,
)
from app.services.session_manager import get_session_manager
from app.services.session_replay import (
    ReplayNotFound,
    ReplayNotReady,
    build_session_replay,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/interview", tags=["interview"])

# Long-poll endpoints (``GET /sessions/{id}/question``) block on a
# threading.Event for up to ``timeout`` seconds. If left as a sync
# ``def`` route, FastAPI dispatches each call to anyio's default
# threadpool (40 tokens), so ~40 concurrent pollers exhaust it and
# every other sync handler queues. Routing the blocking wait through
# this dedicated executor keeps long-poll concurrency from starving
# the anyio pool while still avoiding a full asyncio rewrite of
# SessionManager. ws_voice.py uses the same pattern with its own
# ``_VOICE_EXECUTOR``.
_POLL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=128,
    thread_name_prefix="interview-poll",
)

REAUTH_REQUIRED_DETAIL = {
    "error": "reauth_required",
    "message": "This interview needs your personal LLM configuration again.",
}
MAX_SESSION_TURNS = 20
MAX_TURN_BUDGET = 30
CANDIDATE_SUMMARY_MAX_LENGTH = 1200
CANDIDATE_SKILLS_MAX_COUNT = 40
CANDIDATE_SKILL_MAX_LENGTH = 80
CANDIDATE_HIGHLIGHTS_MAX_COUNT = 20
CANDIDATE_HIGHLIGHT_MAX_LENGTH = 240
RESUME_PROJECTS_MAX_COUNT = 12
RESUME_PROJECT_NAME_MAX_LENGTH = 120
RESUME_PROJECT_ROLE_MAX_LENGTH = 80
RESUME_PROJECT_ANCHORS_MAX_COUNT = 8
RESUME_PROJECT_ANCHOR_MAX_LENGTH = 160
RESUME_FOCUS_AREAS_MAX_COUNT = 20
RESUME_FOCUS_LABEL_MAX_LENGTH = 160
RESUME_CONCERNS_MAX_COUNT = 10
ANSWER_TEXT_MAX_LENGTH = 8000
SessionIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=SESSION_ID_MAX_LENGTH,
        pattern=SESSION_ID_PATTERN,
    ),
]


from app.core.roles import ApiExposedRole as LLMRoleKey  # noqa: E402

SkillText = Annotated[str, Field(max_length=CANDIDATE_SKILL_MAX_LENGTH)]
HighlightText = Annotated[str, Field(max_length=CANDIDATE_HIGHLIGHT_MAX_LENGTH)]
QuestionAnchorText = Annotated[str, Field(max_length=RESUME_PROJECT_ANCHOR_MAX_LENGTH)]
FocusLabelText = Annotated[str, Field(max_length=RESUME_FOCUS_LABEL_MAX_LENGTH)]


class LLMRoleOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider | None = None
    api_key: str | None = Field(default=None, max_length=LLM_API_KEY_MAX_LENGTH)
    model: str | None = Field(default=None, max_length=LLM_MODEL_MAX_LENGTH)
    temperature: float | None = None
    base_url: str | None = Field(default=None, max_length=LLM_BASE_URL_MAX_LENGTH)

    @field_validator("provider", "api_key", "model", "base_url", mode="before")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        if not value:
            return value
        from app.engine.agents.llm_client import LLMFatal, validate_llm_base_url

        try:
            validate_llm_base_url(value)
        except LLMFatal as e:
            raise ValueError(str(e)) from e
        return value


class LLMConfigOverride(LLMRoleOverride):
    role_overrides: dict[LLMRoleKey, LLMRoleOverride] | None = None


class ResumeProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=RESUME_PROJECT_NAME_MAX_LENGTH)
    role: str | None = Field(default=None, max_length=RESUME_PROJECT_ROLE_MAX_LENGTH)
    tech_stack: list[SkillText] = Field(default_factory=list, max_length=CANDIDATE_SKILLS_MAX_COUNT)
    responsibilities: list[HighlightText] = Field(
        default_factory=list,
        max_length=CANDIDATE_HIGHLIGHTS_MAX_COUNT,
    )
    achievements: list[HighlightText] = Field(
        default_factory=list,
        max_length=CANDIDATE_HIGHLIGHTS_MAX_COUNT,
    )
    question_anchors: list[QuestionAnchorText] = Field(
        default_factory=list,
        max_length=RESUME_PROJECT_ANCHORS_MAX_COUNT,
    )


class ResumeFocusArea(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default="", max_length=40)
    label: FocusLabelText = ""
    project_id: str | None = None
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    skills: list[SkillText] = Field(default_factory=list, max_length=CANDIDATE_SKILLS_MAX_COUNT)
    priority: int | None = None


class ResumeParsed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(default="", max_length=CANDIDATE_SUMMARY_MAX_LENGTH)
    skills: list[SkillText] = Field(default_factory=list, max_length=CANDIDATE_SKILLS_MAX_COUNT)
    highlights: list[HighlightText] = Field(
        default_factory=list,
        max_length=CANDIDATE_HIGHLIGHTS_MAX_COUNT,
    )
    projects: list[ResumeProject] = Field(default_factory=list, max_length=RESUME_PROJECTS_MAX_COUNT)
    focus_areas: list[ResumeFocusArea] = Field(
        default_factory=list,
        max_length=RESUME_FOCUS_AREAS_MAX_COUNT,
    )
    concerns: list[QuestionAnchorText] = Field(
        default_factory=list,
        max_length=RESUME_CONCERNS_MAX_COUNT,
    )


class CandidateInput(BaseModel):
    """Structured candidate payload; aligns with frontend Candidate type."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, description="Candidate display name")
    email_hash: str | None = None
    resume_parsed: ResumeParsed = Field(default_factory=ResumeParsed)


class JobSpecInput(BaseModel):
    """Structured job spec payload; aligns with frontend JobSpec type."""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, description="Job title")
    level: Literal["junior", "mid", "senior", "staff", "principal"] = "senior"
    required_skills: list[str] = Field(default_factory=list)
    rubric_dimensions: list[str] = Field(default_factory=list)
    rubric: dict[str, str] = Field(default_factory=dict)
    interview_industry: str | None = None
    interview_direction: str | None = None
    interview_direction_label: str | None = None


class StartSessionRequest(BaseModel):
    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=SESSION_ID_MAX_LENGTH,
        pattern=SESSION_ID_PATTERN,
    )
    trace_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=SESSION_ID_MAX_LENGTH,
        pattern=SESSION_ID_PATTERN,
    )
    candidate: CandidateInput
    job_spec: JobSpecInput
    mode: str = "mixed"
    enable_video_analysis: bool = False
    max_turns: int | None = Field(default=None, ge=1, le=MAX_SESSION_TURNS)
    quality_threshold: float | None = Field(default=None, ge=0, le=10)
    turn_budget: int | None = Field(default=None, ge=1, le=MAX_TURN_BUDGET)
    llm_config: LLMConfigOverride | None = None


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=ANSWER_TEXT_MAX_LENGTH)
    turn_idx: int
    video_signals: VideoSignalsInput | None = None
    llm_config: LLMConfigOverride | None = None


class SkipQuestionRequest(BaseModel):
    turn_idx: int
    reason: str | None = Field(default=None, max_length=200)


class HintRequest(BaseModel):
    turn_idx: int
    llm_config: LLMConfigOverride | None = None


async def _read_upload_limited(
    file: UploadFile,
    *,
    max_bytes: int | None = None,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    limit = MAX_RESUME_UPLOAD_BYTES if max_bytes is None else max_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=api_error_detail(
                    "resume_file_too_large",
                    f"file too large: max {limit} bytes",
                    "compress_or_upload_text",
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _clamp_poll_timeout(timeout: float) -> float:
    return max(0.0, min(60.0, float(timeout)))


def _session_token_hash_from_db(session_id: str) -> str | None:
    try:
        with get_db_session() as db:
            row = db.get(InterviewSession, session_id)
            return row.session_token_hash if row is not None else None
    except Exception as e:
        log.warning("session token lookup failed for %s: %s", session_id, e)
        return None


def _require_session_access(
    session_id: str,
    session_token: str | None,
    *,
    handle: Any | None = None,
) -> None:
    token_hash = getattr(handle, "session_token_hash", None)
    if not token_hash:
        token_hash = _session_token_hash_from_db(session_id)
    if not token_hash:
        if get_settings().app_env != "prod":
            return
        raise HTTPException(status_code=401, detail="session token required")
    if not session_token:
        raise HTTPException(status_code=401, detail="session token required")
    if not verify_session_token(session_token, token_hash):
        raise HTTPException(status_code=403, detail="invalid session token")


def _get_or_recover_session(manager: Any, session_id: str) -> Any | None:
    handle = manager.get(session_id)
    if handle is not None:
        return handle
    recover = getattr(manager, "recover_waiting_session", lambda _sid: None)
    return recover(session_id)


def _session_id_in_use(manager: Any, session_id: str) -> bool:
    session_exists = getattr(manager, "session_exists", None)
    if callable(session_exists):
        return bool(session_exists(session_id))
    get_handle = getattr(manager, "get", None)
    return bool(callable(get_handle) and get_handle(session_id) is not None)


def _terminal_error_payload(
    *,
    session_id: str,
    error: str | None,
    error_kind: str | None,
    retryable: bool = False,
) -> dict[str, Any]:
    return terminal_error_payload(
        session_id=session_id,
        error=error,
        error_kind=error_kind,
        retryable=retryable,
    )


def _stale_session_error(
    session_id: str,
    *,
    status: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return stale_session_error(
        session_id,
        status=status,
        retryable=retryable,
    )


def _terminal_payload_from_persisted_session(
    session_id: str,
    *,
    retryable: bool = False,
) -> dict[str, Any] | None:
    """Return persisted terminal/session-unavailable state after restart.

    The live endpoints primarily use the in-memory SessionHandle. In dev
    and desktop-style flows the backend process may restart while the
    browser still keeps a local history entry. When that happens, give the
    frontend a structured terminal state instead of a vague 404.
    """
    return terminal_payload_from_persisted_session(session_id, retryable=retryable)


def _load_terminal_payload_from_persisted_session(
    session_id: str,
    *,
    retryable: bool = False,
) -> dict[str, Any] | None:
    try:
        return _terminal_payload_from_persisted_session(
            session_id,
            retryable=retryable,
        )
    except TypeError:
        # Some narrow unit tests monkeypatch the helper with the older
        # one-argument signature. Keep that call shape compatible while the
        # real implementation carries the retry hint.
        return _terminal_payload_from_persisted_session(session_id)


def _report_payload_from_persisted_session(
    session_id: str,
) -> dict[str, Any] | None:
    return report_payload_from_persisted_session(session_id)


def _attach_trace_health(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Inject ``trace_health`` so the QualityCenter card can show the same
    coverage signal that the engineer-facing Trace Explorer relies on.

    Errors in the trace lookup degrade gracefully to ``"missing"``:
    the report is the candidate's deliverable and must not 500 just
    because the observability stack is having a bad day.
    """
    return attach_trace_health(payload, session_id)


def _delete_checkpoint_thread(session_id: str) -> bool | None:
    manager = get_session_manager()
    workflow = getattr(manager, "_workflow", None)
    checkpointer = getattr(workflow, "checkpointer", None)
    delete_thread = getattr(checkpointer, "delete_thread", None)
    if not callable(delete_thread):
        return None
    delete_thread(session_id)
    return True


def _parse_llm_config_form(raw: str | None) -> dict[str, Any] | None:
    """Parse optional multipart ``llm_config`` without echoing secrets."""
    if raw is None or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=api_error_detail(
                "llm_config_invalid_json",
                "模型配置不是有效 JSON，请检查后再试。",
                "edit_llm_config",
            ),
        ) from e
    try:
        parsed = LLMConfigOverride.model_validate(data)
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=api_error_detail(
                "llm_config_invalid",
                "模型配置字段不合法，请检查服务商、模型和 Base URL。",
                "edit_llm_config",
            ),
        ) from e
    return parsed.model_dump(exclude_none=True)


def _resume_parse_payload(parsed: Any, text: str) -> dict[str, Any]:
    return resume_parse_payload(parsed, text)


def _rate_limit_client_key(request: Request, endpoint: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{endpoint}:{host}"


def _enforce_setup_rate_limit(
    request: Request,
    *,
    endpoint: str,
    limit: int,
) -> None:
    settings = get_settings()
    try:
        check_rate_limit(
            _rate_limit_client_key(request, endpoint),
            limit=limit,
            window_seconds=settings.rate_limit_window_seconds,
        )
    except RateLimitExceededError as e:
        record_rate_limit_block(endpoint)
        raise HTTPException(
            status_code=429,
            detail=api_error_detail(
                "rate_limit_exceeded",
                "请求过于频繁，请稍后再试。",
                "retry_later",
            ),
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e


@router.post("/sessions")
def start_session(req: StartSessionRequest) -> dict[str, Any]:
    session_id, trace_id, initial = translate_request(req.model_dump(exclude_none=False))
    token = bind_log_context(session_id=session_id, trace_id=trace_id)
    manager = get_session_manager()
    llm_override = (
        req.llm_config.model_dump(exclude_none=True) if req.llm_config else None
    )
    session_token = new_session_token()
    try:
        if _session_id_in_use(manager, session_id):
            raise HTTPException(
                status_code=409,
                detail=api_error_detail(
                    "session_id_conflict",
                    "这场面试的会话标识已存在，请重新开始一次。",
                    "restart_session",
                ),
            )
        manager.start(
            session_id,
            trace_id,
            initial,
            llm_config=llm_override,
            session_token_hash=hash_session_token(session_token),
        )
    except ValueError as e:
        if "session_id already exists" in str(e):
            raise HTTPException(
                status_code=409,
                detail=api_error_detail(
                    "session_id_conflict",
                    "这场面试的会话标识已存在，请重新开始一次。",
                    "restart_session",
                ),
            ) from e
        raise
    else:
        return {
            "session_id": session_id,
            "session_token": session_token,
            "trace_id": trace_id,
            "status": "running",
            "max_turns": initial.get("max_turns"),
        }
    finally:
        reset_log_context(token)


@router.get("/sessions/{session_id}/question")
async def poll_question(
    session_id: SessionIdPath,
    timeout: float = Query(default=30.0),
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    manager = get_session_manager()
    handle = _get_or_recover_session(manager, session_id)
    _require_session_access(session_id, session_token, handle=handle)
    if handle is None:
        can_retry = getattr(manager, "can_retry_failed_question", lambda _sid: False)
        persisted = _load_terminal_payload_from_persisted_session(
            session_id,
            retryable=bool(can_retry(session_id)),
        )
        if persisted is not None:
            return persisted
        raise HTTPException(status_code=404, detail="session not found")
    token = bind_log_context(session_id=session_id, trace_id=handle.trace_id)
    try:
        # ``manager.wait_for_next_question`` blocks on a threading.Event
        # internally; running it on the dedicated executor keeps the
        # event loop responsive and the anyio threadpool free for other
        # sync handlers under high concurrency.
        loop = asyncio.get_running_loop()
        question = await loop.run_in_executor(
            _POLL_EXECUTOR,
            manager.wait_for_next_question,
            session_id,
            _clamp_poll_timeout(timeout),
        )
        done = handle.done_event.is_set()
        cancelled = handle.cancelled
        final_report = (handle.final_state or {}).get("final_report")
        final_status = (handle.final_state or {}).get("status")
        turn_idx = handle.turn_idx
        max_turns = handle.max_turns
    finally:
        reset_log_context(token)
    # The graph pipeline caches a compact projection of the candidate's
    # last evaluated turn on the handle (see ``_extract_last_turn_evaluation``
    # in ``session_manager``). Echoing it on every poll lets the UI render
    # in-interview feedback without a second round-trip; the key is always
    # present (``None`` when there is no displayable feedback) so the
    # frontend never has to special-case its absence.
    previous_turn_evaluation = getattr(handle, "last_turn_evaluation", None)
    # End-to-end wall-clock latency of the most recent ``_run_segment``
    # in milliseconds (#11). The frontend uses it to render an ETA hint
    # ("AI 正在思考，预计 ≈ 5 秒") on the next loading state. ``None``
    # until the first segment finishes.
    server_latency_ms = getattr(handle, "last_segment_latency_ms", None)
    retryable = False
    if question is None and done and handle.error:
        retryable = bool(
            getattr(manager, "can_retry_failed_question", lambda _sid: False)(
                session_id
            )
        )
    return build_question_poll_payload(
        session_id=session_id,
        question=question,
        done=done,
        cancelled=cancelled,
        final_status=final_status,
        final_report=final_report,
        error=handle.error,
        error_kind=getattr(handle, "error_kind", None),
        retryable=retryable,
        turn_idx=turn_idx,
        max_turns=max_turns,
        previous_turn_evaluation=previous_turn_evaluation,
        server_latency_ms=server_latency_ms,
    )


@router.post("/sessions/{session_id}/voice-ticket")
def create_voice_ticket(
    session_id: SessionIdPath,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    manager = get_session_manager()
    handle = _get_or_recover_session(manager, session_id)
    _require_session_access(session_id, session_token, handle=handle)
    if handle is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "ticket": issue_voice_ticket(session_id),
        "expires_in_seconds": get_settings().voice_ticket_ttl_seconds,
    }


@router.post("/sessions/{session_id}/answer")
def submit_answer(
    session_id: SessionIdPath,
    body: AnswerRequest,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
    ),
) -> dict[str, Any]:
    manager = get_session_manager()
    handle = _get_or_recover_session(manager, session_id)
    _require_session_access(session_id, session_token, handle=handle)
    if handle is None:
        raise HTTPException(status_code=404, detail="session not found") from None
    token = bind_log_context(session_id=session_id, trace_id=handle.trace_id)
    llm_override = (
        body.llm_config.model_dump(exclude_none=True) if body.llm_config else None
    )
    video_signals_payload = (
        body.video_signals.model_dump(exclude_none=False)
        if body.video_signals is not None
        else None
    )

    # Idempotency: replay-safe wrapper around the manager call. The
    # request hash *intentionally* excludes ``llm_config`` so a client
    # can re-issue the same logical answer with a refreshed BYOK token
    # and still get the cached response back; the answer text and turn
    # index are what define "the same submission".
    use_idempotency = is_valid_idempotency_key(idempotency_key)
    request_hash = ""
    idempotency_scope = ""
    if use_idempotency:
        request_hash = hash_request_body(
            {
                "answer": body.answer,
                "turn_idx": body.turn_idx,
                "video_signals": video_signals_payload,
            }
        )
        idempotency_scope = f"answer:{session_id}"
        store = get_idempotency_store()
        try:
            cached = store.lookup(idempotency_scope, idempotency_key, request_hash)
        except IdempotencyConflict as exc:
            reset_log_context(token)
            log.info(
                "idempotency conflict: scope=%s key_prefix=%s",
                idempotency_scope,
                (idempotency_key or "")[:8],
            )
            raise HTTPException(
                status_code=409,
                detail=api_error_detail(
                    "idempotency_conflict",
                    "幂等键已被使用且请求体不一致，请使用新的 Idempotency-Key 或保持请求体不变。",
                    "use_new_idempotency_key",
                ),
            ) from exc
        if cached is not None:
            reset_log_context(token)
            return cached.response

    try:
        manager.submit_answer(
            session_id,
            body.answer,
            turn_idx=body.turn_idx,
            video_signals=video_signals_payload,
            llm_config=llm_override,
        )
    except ValueError as e:
        if "reauth_required" in str(e):
            raise HTTPException(status_code=409, detail=REAUTH_REQUIRED_DETAIL) from e
        raise HTTPException(status_code=409, detail=str(e)) from e
    finally:
        reset_log_context(token)

    response = {"session_id": session_id, "accepted": True}
    if use_idempotency:
        get_idempotency_store().record(
            idempotency_scope,
            idempotency_key,
            request_hash,
            response,
        )
    return response


@router.post("/sessions/{session_id}/skip-question")
def skip_question(
    session_id: SessionIdPath,
    body: SkipQuestionRequest,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    manager = get_session_manager()
    handle = _get_or_recover_session(manager, session_id)
    _require_session_access(session_id, session_token, handle=handle)
    if handle is None:
        raise HTTPException(status_code=404, detail="session not found") from None
    token = bind_log_context(session_id=session_id, trace_id=handle.trace_id)
    try:
        manager.skip_question(
            session_id,
            turn_idx=body.turn_idx,
            reason=body.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    finally:
        reset_log_context(token)
    return {"session_id": session_id, "accepted": True, "status": "skipped"}


@router.post("/sessions/{session_id}/hint")
def request_hint(
    session_id: SessionIdPath,
    body: HintRequest,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    manager = get_session_manager()
    handle = _get_or_recover_session(manager, session_id)
    _require_session_access(session_id, session_token, handle=handle)
    if handle is None:
        raise HTTPException(status_code=404, detail="session not found") from None
    token = bind_log_context(session_id=session_id, trace_id=handle.trace_id)
    llm_override = (
        body.llm_config.model_dump(exclude_none=True) if body.llm_config else None
    )
    try:
        return manager.request_hint(
            session_id,
            turn_idx=body.turn_idx,
            llm_config=llm_override,
        )
    except ValueError as e:
        if "reauth_required" in str(e):
            raise HTTPException(status_code=409, detail=REAUTH_REQUIRED_DETAIL) from e
        raise HTTPException(status_code=409, detail=str(e)) from e
    finally:
        reset_log_context(token)


@router.post("/sessions/{session_id}/retry-question")
def retry_failed_question(
    session_id: SessionIdPath,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    manager = get_session_manager()
    _require_session_access(
        session_id,
        session_token,
        handle=_get_or_recover_session(manager, session_id),
    )
    handle = manager.retry_failed_question(session_id)
    if handle is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "question retry is not available",
                "message": "当前会话没有可重试的出题失败状态。",
            },
        )
    return {"session_id": session_id, "status": "retrying"}


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: SessionIdPath,
    confirm_session_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=SESSION_ID_MAX_LENGTH,
        pattern=SESSION_ID_PATTERN,
    ),
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    if confirm_session_id != session_id:
        raise HTTPException(
            status_code=400,
            detail="confirm_session_id must match session_id",
        )

    manager = get_session_manager()
    active_removed = False
    _require_session_access(session_id, session_token, handle=manager.get(session_id))
    if manager.get(session_id) is not None:
        try:
            manager.cancel(session_id)
        finally:
            manager.remove(session_id)
            active_removed = True

    payload = delete_session_data(session_id)
    payload["deleted"] = bool(payload["deleted"] or active_removed)
    try:
        checkpoint_deleted = _delete_checkpoint_thread(session_id)
    except Exception as e:
        log.warning("delete checkpoint thread failed for %s: %s", session_id, e)
        checkpoint_deleted = False
    if checkpoint_deleted is not None:
        payload["checkpoint_deleted"] = bool(checkpoint_deleted)
    return payload


class FeedbackRequest(BaseModel):
    """C-end user feedback submitted on the report page."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["got_offer", "no_offer", "still_preparing", "withdrew"]
    helpful_score: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=1024)


_FEEDBACK_OUTCOME_MAP = FEEDBACK_OUTCOME_MAP


@router.post("/sessions/{session_id}/feedback")
def submit_feedback(
    session_id: SessionIdPath,
    body: FeedbackRequest,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    """Accept C-end user outcome feedback and upsert into OutcomeRecord.

    Idempotent: repeated submissions for the same session_id overwrite
    the previous record. The existing ``backfill_once`` scheduler picks
    up the new/updated OutcomeRecord and propagates the delayed reward
    to the Thompson Sampling bandit.
    """
    manager = get_session_manager()
    _require_session_access(
        session_id,
        session_token,
        handle=_get_or_recover_session(manager, session_id),
    )
    try:
        result = save_interview_feedback(
            session_id=session_id,
            outcome=body.outcome,
            helpful_score=body.helpful_score,
            notes=body.notes,
            get_db_session_fn=get_db_session,
        )
    except Exception as e:
        log.exception("submit_feedback failed for session %s", session_id)
        raise HTTPException(
            status_code=500,
            detail=api_error_detail(
                "feedback_save_failed",
                "反馈保存失败，请稍后重试。",
                "retry_later",
            ),
        ) from e

    log.info(
        "feedback saved: session=%s outcome=%s helpful=%.2f",
        session_id,
        result.canonical_outcome,
        result.helpful_norm if result.helpful_norm is not None else -1,
    )
    return {"session_id": session_id, "accepted": True}


@router.get("/sessions/{session_id}/report")
def get_report(
    session_id: SessionIdPath,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    manager = get_session_manager()
    handle = manager.get(session_id)
    _require_session_access(session_id, session_token, handle=handle)
    if handle is None:
        persisted = _report_payload_from_persisted_session(session_id)
        if persisted is not None:
            return persisted
        raise HTTPException(status_code=404, detail="session not found")
    token = bind_log_context(session_id=session_id, trace_id=handle.trace_id)
    try:
        done = handle.done_event.is_set()
        final_report = (handle.final_state or {}).get("final_report")
        final_status = (handle.final_state or {}).get("status")
        cancelled = handle.cancelled
        error = handle.error
    finally:
        reset_log_context(token)
    if not done:
        raise HTTPException(status_code=409, detail="interview still running")
    if cancelled or final_status == "cancelled":
        return _attach_trace_health(
            {
                "session_id": session_id,
                "final_report": final_report,
                "error": "session cancelled",
                "error_kind": None,
            },
            session_id,
        )
    if error:
        return _attach_trace_health(
            {
                "session_id": session_id,
                "final_report": final_report,
                "error": error,
                "error_kind": getattr(handle, "error_kind", None),
            },
            session_id,
        )
    return _attach_trace_health(
        {
            "session_id": session_id,
            "final_report": final_report,
            "error": error,
        },
        session_id,
    )


@router.get("/sessions/{session_id}/replay")
def get_replay(
    session_id: SessionIdPath,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    manager = get_session_manager()
    _require_session_access(
        session_id,
        session_token,
        handle=manager.get(session_id),
    )
    try:
        with get_db_session() as db:
            return build_session_replay(db, session_id)
    except ReplayNotFound as e:
        raise HTTPException(status_code=404, detail="session not found") from e
    except ReplayNotReady as e:
        raise HTTPException(
            status_code=409,
            detail="replay is only available for completed sessions",
        ) from e


@router.get("/sessions/{session_id}/resume")
def resume_session(
    session_id: SessionIdPath,
    session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> dict[str, Any]:
    """Reconnect to a session that was interrupted (e.g. after restart).

    If the session handle already exists in memory, returns its
    current question. Otherwise, checks the DB for a rehydrated
    handle and returns the persisted question so the client can
    continue the interview without data loss.
    """
    manager = get_session_manager()
    handle = _get_or_recover_session(manager, session_id)
    _require_session_access(session_id, session_token, handle=handle)

    if handle is None:
        can_retry = getattr(manager, "can_retry_failed_question", lambda _sid: False)
        persisted = _load_terminal_payload_from_persisted_session(
            session_id,
            retryable=bool(can_retry(session_id)),
        )
        if persisted is not None:
            return persisted
        raise HTTPException(
            status_code=404,
            detail="session not found — it may have completed or was never started",
        )

    token = bind_log_context(session_id=session_id, trace_id=handle.trace_id)
    try:
        done = handle.done_event.is_set()
        cancelled = handle.cancelled
        final_report = (handle.final_state or {}).get("final_report")
        final_status = (handle.final_state or {}).get("status")
        current_question = handle.current_question
        turn_idx = handle.turn_idx
        max_turns = handle.max_turns
    finally:
        reset_log_context(token)

    if cancelled or final_status == "cancelled":
        return {
            "session_id": session_id,
            "status": "cancelled",
            "question": None,
            "max_turns": max_turns,
        }

    if done:
        if handle.error:
            return _terminal_error_payload(
                session_id=session_id,
                error=handle.error,
                error_kind=getattr(handle, "error_kind", None),
                retryable=bool(
                    getattr(manager, "can_retry_failed_question", lambda _sid: False)(
                        session_id
                    )
                ),
            )
        return {
            "session_id": session_id,
            "status": "completed",
            "question": None,
            "final_report": final_report,
            "max_turns": max_turns,
        }

    return {
        "session_id": session_id,
        "status": "waiting_for_answer" if current_question else "running",
        "turn_idx": turn_idx,
        "question": current_question,
        "max_turns": max_turns,
    }


@router.post("/resume/parse")
async def parse_resume_upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    llm_config: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Decode a PDF/DOCX/TXT upload into a ``resume_parsed`` dict.

    The response shape is intentionally compatible with the
    ``candidate.resume_parsed`` field expected by ``POST /sessions``,
    so the frontend can drop it straight into the setup form for the
    user to review/edit before starting the interview.

    Errors:
        - 413 if the file exceeds the size limit
        - 415 for unsupported formats
        - 422 for files that decode to empty text
        - 500 on unexpected parser failures
    """
    _enforce_setup_rate_limit(
        request,
        endpoint="resume_parse",
        limit=get_settings().resume_parse_rate_limit_per_minute,
    )
    raw = await _read_upload_limited(file)
    log.info(
        "resume_parse_upload: filename=%r content_type=%r size=%d",
        file.filename,
        file.content_type,
        len(raw),
    )
    llm_override = _parse_llm_config_form(llm_config)
    try:
        result = parse_resume_setup_upload(
            filename=file.filename,
            content_type=file.content_type,
            raw=raw,
            llm_override=llm_override,
            extract_text_fn=extract_text_with_timeout,
            parse_resume_fn=parse_resume,
            get_cache_fn=get_resume_parse_cache,
            cache_key_fn=resume_parse_cache_key,
            should_cache_fn=should_cache_resume_parse,
            timeout_seconds=EXTRACT_TEXT_TIMEOUT_SECONDS,
        )
    except ResumeParseError as e:
        msg = str(e)
        if "too large" in msg.lower():
            record_setup_parse_error("resume", "resume_file_too_large")
            raise HTTPException(
                status_code=413,
                detail=api_error_detail(
                    "resume_file_too_large",
                    msg,
                    "compress_or_upload_text",
                ),
            ) from e
        if "unsupported" in msg.lower():
            record_setup_parse_error("resume", "resume_file_unsupported")
            raise HTTPException(
                status_code=415,
                detail=api_error_detail(
                    "resume_file_unsupported",
                    msg,
                    "upload_supported_format",
                ),
            ) from e
        record_setup_parse_error("resume", "resume_parse_failed")
        raise HTTPException(
            status_code=422,
            detail=api_error_detail("resume_parse_failed", msg, "edit_resume_manually"),
        ) from e
    except ResumeTextExtractionError as e:
        log.exception("resume_parse_upload: unexpected decode failure")
        record_setup_parse_error("resume", "resume_read_failed")
        raise HTTPException(
            status_code=500,
            detail=api_error_detail(
                "resume_read_failed",
                f"Failed to read file: {e.original}",
                "retry_upload",
            ),
        ) from e

    if result.cached:
        log.info(
            "resume_parse_cache_hit: key=%s age_ms=%s",
            result.cache_key[:16],
            result.cache_age_ms,
        )
    else:
        log.info("resume_parse_cache_miss: key=%s", result.cache_key[:16])
    payload = result.payload
    log.info(
        "resume_parse_upload_done: mode=%s reason=%s elapsed_ms=%s text_chars=%s projects=%d focus_areas=%d",
        payload.get("parse_status", {}).get("mode"),
        payload.get("parse_status", {}).get("reason"),
        payload.get("parse_status", {}).get("elapsed_ms"),
        payload.get("parse_status", {}).get("text_chars"),
        len(payload.get("projects") or []),
        len(payload.get("focus_areas") or []),
    )
    record_context_flags("resume", payload.get("context_flags") or [])
    return payload


class ParseJobSpecRequest(BaseModel):
    """Free-text JD body for ``POST /jd/parse``.

    The optional ``title`` and ``level`` fields give the parser
    setup-form context without letting it overwrite the user's selected
    target level.
    """

    text: str = Field(min_length=1, max_length=20_000)
    direction: str | None = None
    title: str | None = None
    level: str | None = None
    llm_config: LLMConfigOverride | None = None


@router.post("/jd/parse")
def parse_jd(req: ParseJobSpecRequest, request: Request) -> dict[str, Any]:
    """Infer required_skills + rubric_dimensions from a job description.

    Used by the SetupForm so the user only types role + (optionally)
    pastes a JD, and the rubric dimensions are picked automatically.
    The response carries UI-friendly Chinese labels alongside the
    canonical dimension IDs so the frontend doesn't need a parallel
    translation table.
    """
    _enforce_setup_rate_limit(
        request,
        endpoint="jd_parse",
        limit=get_settings().jd_parse_rate_limit_per_minute,
    )
    llm_override = (
        req.llm_config.model_dump(exclude_none=True) if req.llm_config else None
    )
    try:
        payload = parse_jd_setup_payload(
            text=req.text,
            direction=req.direction,
            title=req.title,
            level=req.level,
            llm_override=llm_override,
            parse_job_spec_fn=parse_job_spec,
        )
    except JDParseError as e:
        message = "岗位要求为空，请补充后再试。" if "empty" in str(e).lower() else str(e)
        code = "jd_empty" if "empty" in str(e).lower() else "jd_parse_failed"
        record_setup_parse_error("jd", code)
        raise HTTPException(
            status_code=422,
            detail=api_error_detail(code, message, "edit_jd"),
        ) from e
    log.info(
        "jd_parse: title=%r level=%r dims=%s skills=%d",
        req.title,
        req.level,
        payload["rubric_dimensions"],
        len(payload["required_skills"]),
    )
    record_context_flags("jd", payload.get("context_flags") or [])
    return payload


@router.get("/dimensions")
def list_dimensions() -> dict[str, Any]:
    """Static catalog used by the dimension picker in the SetupForm."""
    return list_dimensions_payload()


@router.get("/directions")
def list_directions() -> dict[str, Any]:
    """Static direction catalog used by SetupForm."""
    return list_directions_payload()


@router.get("/job-template")
def get_default_job_template(direction: str, level: str | None = None) -> dict[str, Any]:
    """Return the editable generic JD template for a setup direction."""
    try:
        return default_job_template_payload(direction, level=level)
    except JobTemplateNotFound as e:
        raise HTTPException(status_code=404, detail="Job template not found") from e
