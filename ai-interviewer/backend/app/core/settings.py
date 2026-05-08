"""Centralised application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for runtime configuration.

    The class loads values from the process environment and, if present,
    from a ``.env`` file located next to ``backend/``. Keeping every
    knob here avoids scattering `os.getenv(...)` across the code base and
    makes workflow runtime configuration explicit.
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["dev", "prod", "test"] = "dev"
    app_port: int = 8000
    log_level: str = "INFO"
    # Log rendering mode used by :func:`app.core.logging.configure_logging`:
    # - ``auto`` (default): JSON when ``app_env == "prod"``, console otherwise.
    # - ``console``: always human-readable ANSI output (useful for ``app_env=prod``
    #   deployments that still want interactive logs, e.g. a single-node demo).
    # - ``json``: always newline-delimited JSON so ingestion pipelines can parse
    #   ``trace_id`` / ``session_id`` as structured fields instead of regexing
    #   the ``message`` string.
    log_format: Literal["auto", "console", "json"] = "auto"

    database_url: str = "postgresql+psycopg2://interviewer:interviewer@localhost:5433/interviewer"
    redis_url: str = "redis://localhost:6380/0"

    chroma_host: str = "localhost"
    chroma_port: int = 8100
    chroma_collection: str = "interviewer_kb"

    llm_provider: Literal[
        "openai",
        "anthropic",
        "deepseek",
        "kimi",
        "moonshot",
        "qwen",
        "dashscope",
        "zhipu",
        "mistral",
        "openai_compatible",
        "stub",
    ] = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 2048
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    # DeepSeek is an OpenAI-protocol-compatible provider. Using its own
    # client settings lets operators keep OpenAI + DeepSeek routed side
    # by side (e.g. OpenAI for eval, DeepSeek for generation) without
    # cross-contaminating ``OPENAI_API_KEY``.
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # ------------------------------------------------------------------
    # LLM-level resilience. Retries are applied to ``call_chat`` and
    # only to transient failures (timeouts, 429, 5xx). Because this is
    # an interactive interview product, defaults are intentionally
    # bounded: a slow provider should fail clearly instead of freezing
    # the next question / scoring / feedback step for minutes. Keep
    # automatic retries OFF by default for the live interview loop;
    # operators can raise this in ``.env`` when they prefer resilience
    # over responsiveness.
    # ------------------------------------------------------------------
    llm_max_retries: int = 0
    llm_retry_backoff_seconds: float = 0.5
    llm_retry_backoff_cap_seconds: float = 2.0
    # Network timeout passed to provider SDK clients. The app already
    # owns retry policy in ``call_chat``; SDK-level retries are disabled
    # so one slow request cannot silently multiply latency.
    llm_request_timeout_seconds: float = 20.0
    # First-question generation often carries the largest prompt
    # (resume anchors + JD + rubric + retrieval context). Give the
    # generator a slightly larger budget without slowing every scoring
    # or guardrail call in the live loop.
    generator_llm_timeout_seconds: float = 45.0
    # Answer scoring sits on the live interview path too, but Qwen/Kimi
    # style JSON grading can exceed the generic 20s request budget under
    # BYOK routing. Keep it role-scoped so guardrails and small utility
    # calls remain responsive.
    evaluator_llm_timeout_seconds: float = 45.0
    # Verifier is conditional rather than every turn, and recent traces
    # show borderline review calls can exceed the generic 20s budget.
    verifier_llm_timeout_seconds: float = 30.0
    # Coach runs after the live interview ends (non-realtime) and
    # produces a structured growth plan from the full QA history.
    # Give it a generous budget since output quality matters more
    # than latency here.
    coach_llm_timeout_seconds: float = 90.0
    # Resume upload is an interactive setup step. If BYOK resume_parser
    # refinement is slow, return the heuristic parse instead of making
    # the browser wait until its upload request times out.
    resume_parser_llm_timeout_seconds: float = 60.0
    # Resume parsing can involve a relatively slow LLM refinement. Cache
    # structured results briefly by extracted text + effective model config.
    # Redis is the production default; tests and local fallback can use memory.
    resume_parse_cache_enabled: bool = True
    resume_parse_cache_backend: Literal["redis", "memory", "off"] = "redis"
    resume_parse_cache_ttl_seconds: int = 86400
    resume_parse_cache_redis_prefix: str = "agentic_interviewer:resume_parse"

    # ------------------------------------------------------------------
    # Per-agent model override. ``call_chat(..., agent_role="evaluator")``
    # picks from this map first, falling back to ``llm_model`` when
    # the role is absent. Default is EMPTY so existing deployments get
    # the pre-rollout single-model behaviour; operators opt into
    # routing by filling the map in ``.env`` or via environment.
    #
    # Env example (JSON string):
    #     LLM_MODEL_PER_AGENT='{"evaluator":"gpt-4o","verifier":"gpt-4o"}'
    #
    # Recognised roles: ``generator``, ``evaluator``, ``verifier``,
    # ``guard``, ``contract_negotiator``, ``rubric_negotiator``,
    # ``session_summarizer``, ``coach``, ``llm_planner``,
    # ``strategy_dream``, ``resume_parser``, ``jd_parser``,
    # ``self_intro_parser``. Unknown keys are ignored
    # with a debug log.
    # ------------------------------------------------------------------
    llm_model_per_agent: dict[str, str] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Anthropic prompt-cache toggle.  When True we attach
    # ``cache_control: {"type":"ephemeral"}`` to the concatenated
    # system message so the static skeleton is cached on Anthropic's
    # side (see https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching).
    # OpenAI caches long system prompts automatically and needs no flag.
    # ------------------------------------------------------------------
    anthropic_prompt_cache: bool = True

    embedding_provider: Literal["openai", "stub"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    allow_stub_embeddings_in_prod: bool = False

    asr_provider: Literal["openai", "deepgram", "stub"] = "openai"
    asr_model: str = "whisper-1"
    tts_provider: Literal["openai", "stub"] = "openai"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"

    # "postgres" enables durable HITL: interviews survive process restarts
    # via PostgresSaver checkpoints + DB-persisted session state.
    # "memory" works for dev / testing but loses interrupted sessions on restart.
    checkpoint_backend: Literal["memory", "postgres"] = "memory"

    # ------------------------------------------------------------------
    # Tracer side-channel. ``state_snapshot`` was originally a deep copy
    # of every whitelisted state key, including the entire ``qa_history``
    # list. For long interviews (8+ turns × 9 trace nodes) this caused
    # the JSON column to balloon. The tracer now keeps only the most
    # recent ``tracer_qa_history_window`` entries per row plus a
    # ``qa_history_total`` counter so downstream consumers can still
    # tell how far the interview had progressed when the row was
    # written. Set the window to ``0`` to keep traces but skip the
    # tail entirely; raise it temporarily when debugging.
    # ------------------------------------------------------------------
    tracer_qa_history_window: int = 5

    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    # Base project name; the *effective* name picked up by the
    # LangSmith SDK is suffixed with ``app_env`` so prod / dev / CI
    # traces land in different dashboards. See
    # :meth:`effective_langsmith_project`.
    langsmith_project: str = "agentic-interviewer"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    # When True, the environment suffix is appended to
    # ``langsmith_project`` to produce
    # :attr:`effective_langsmith_project`. Flip OFF if you are
    # migrating an existing dashboard that relies on the legacy
    # single-bucket name and want to keep all envs merged for a
    # release window.
    langsmith_project_split_by_env: bool = True

    thompson_exploration_rate: float = 0.15
    default_max_turns: int = 8
    default_quality_threshold: float = 7.5
    default_turn_budget: int = 12

    # Bandit policy mode. ``template`` selects from the default 5 template
    # arms (``plan_simple / plan_adaptive / plan_deep_probe / plan_hint
    # / plan_switch``) and is the P1 default. ``legacy`` keeps the
    # original 4 strategy-family arms (``deepen_technical`` etc.) for
    # backwards compatibility with existing bandit checkpoints and
    # dashboards.
    policy_mode: Literal["template", "legacy"] = "template"
    # Opt-in rollout for the compact quick-review template arm. Kept OFF by
    # default so existing bandit masks, fixtures, and posteriors stay stable.
    enable_quick_review_plan: bool = False
    # Direction-scoped policies are more precise but start cold. Until
    # a direction key reaches this many observations, director_sample
    # may fall back to the global ``level:dimension`` posterior.
    policy_direction_min_observations: int = 3

    # Delayed-reward closed loop. ``enable_outcome_sync`` gates the
    # in-process APScheduler that periodically runs ``backfill_once``;
    # ``outcome_sync_interval_minutes`` is how often it wakes up. We
    # default the scheduler OFF so CI / unit tests never accidentally
    # spin a background thread, and flip it on in ``.env`` for real
    # deployments.
    enable_outcome_sync: bool = False
    outcome_sync_interval_minutes: int = 5

    # When True, rebuild the Thompson posterior from
    # ``generation_traces.applied_to_bandit=True`` rows on first use.
    # This is what turns the bandit from "in-memory demo" into a state
    # that survives process restarts.
    rehydrate_bandit_on_start: bool = True

    enable_strategy_dream: bool = False
    dream_interval_hours: int = 24
    dream_min_sessions: int = 5

    # ------------------------------------------------------------------
    # Reward shaping knobs (previously hard-coded in reward_fn.py).
    # Keep defaults equal to historic constants so behaviour stays
    # bit-identical after rollout; flip in .env when tuning.
    # ------------------------------------------------------------------
    reward_passed_bonus: float = 0.10
    reward_coverage_bonus: float = 0.10

    # ------------------------------------------------------------------
    # Delayed-reward knobs (previously hard-coded in
    # outcome_reward_bridge.py). ``outcome_weights`` may be overridden
    # via env as a JSON string, e.g.
    #     OUTCOME_WEIGHTS='{"hired":1.0,"rejected":0.0,"withdrew":0.3,"ghosted":0.2}'
    # ------------------------------------------------------------------
    outcome_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "hired": 1.0,
            "rejected": 0.0,
            "withdrew": 0.3,
            "ghosted": 0.2,
        }
    )
    outcome_perf_blend: float = 0.5

    # ------------------------------------------------------------------
    # Bandit non-stationarity (decay) knobs. OFF by default so existing
    # deployments see no behaviour change; flip ``enable_bandit_decay``
    # to opt in.  ``bandit_decay_interval_days`` is the cadence at
    # which ``ThompsonBandit.decay`` is called; ``bandit_decay_factor``
    # is applied per call (0.99 => half-life ~69 days for interval=1d).
    # ------------------------------------------------------------------
    enable_bandit_decay: bool = False
    bandit_decay_factor: float = 0.99
    bandit_decay_floor: float = 1.0
    bandit_decay_interval_days: int = 1

    # Warm-start prior for new bandit arms. Jeffreys prior (1, 1)
    # is maximally uninformative; raising these adds pseudo-observations
    # so new directions/dimensions start with a bias toward "all arms
    # roughly equal" instead of being dominated by the first observation.
    # E.g. (2, 2) = one pseudo-success + one pseudo-failure per arm.
    bandit_default_alpha: float = 1.0
    bandit_default_beta: float = 1.0

    # ------------------------------------------------------------------
    # PII redaction: extend the MVP regex sweep to cover URLs, IPv4,
    # and Chinese 18-digit national ID numbers.  Kept ON by default
    # because the cost is negligible and the coverage gap without it
    # is uncomfortably large for resumes.  Flip OFF in .env to
    # reproduce the pre-rollout behaviour bit-for-bit.
    # ------------------------------------------------------------------
    pii_extra_patterns: bool = True

    # ------------------------------------------------------------------
    # QA summary strategy used by ``compress_context_node``.
    # - ``deterministic`` (default): zero-cost aggregation, no LLM call.
    # - ``llm``: always delegate to ``session_summarizer`` for a
    #   structured per-dimension digest (progression/evidence/gaps).
    # - ``auto``: deterministic for short interviews, LLM once
    #   ``len(qa_history) >= AUTO_LLM_THRESHOLD``.
    # Per-session override: ``runtime_config.summary_mode``.
    # ------------------------------------------------------------------
    default_summary_mode: Literal["deterministic", "llm", "auto"] = "deterministic"

    # ------------------------------------------------------------------
    # Guardrail dispatch mode used by ``check_question`` / ``check_answer``.
    # - ``regex_only`` (default): existing rule-based sweep only.
    # - ``hybrid``: regex first; anything suspicious is re-examined by
    #   the guard_agent LLM so subtle phrasings get caught. Cheapest
    #   path that still improves coverage over pure regex.
    # - ``llm_only``: every check goes through the agent. Highest cost,
    #   strongest signal; useful for regulatory-heavy deployments.
    # Per-session override: ``runtime_config.guard_mode``.
    # ------------------------------------------------------------------
    default_guard_mode: Literal["regex_only", "hybrid", "llm_only"] = "regex_only"

    # When True, ``wait_answer_node`` runs ``redact_pii`` on the raw
    # candidate answer before storing it in state. If redaction changes
    # the answer, an unredacted copy is kept only in a process-local
    # side-channel referenced by ``current_answer_raw_ref`` so evaluator /
    # verifier can judge the real text without checkpointing raw PII.
    # Flip OFF to reproduce the pre-rollout behaviour.
    redact_answer_pii: bool = True

    # Lifetime of an entry in ``_RAW_ANSWER_STORE`` (audit F2). The
    # default 300 seconds comfortably exceeds the
    # ``wait_answer -> evaluator -> verification -> compress_context``
    # span; raise it for very long voice answers, lower it for tighter
    # privacy windows. Eviction is lazy on read + write, so changing
    # this number does not require a process restart for new sessions.
    raw_answer_ttl_seconds: float = 300.0

    knowledge_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "knowledge"
    )

    # ------------------------------------------------------------------
    # Transport hardening (CORS + auth). Defaults keep CORS open to
    # localhost frontends, while admin endpoints fail closed unless an
    # API token is configured or ``allow_open_admin`` is explicitly set.
    # Narrow ``cors_origins`` for any non-local deployment.
    # ------------------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )
    cors_allow_credentials: bool = True
    # When set, every ``/admin/*`` route requires
    # ``Authorization: Bearer <api_token>``.
    api_token: str | None = None
    # Explicit local-development escape hatch for opening admin routes
    # without a bearer token. Defaults fail-closed so deployments that
    # forget APP_ENV/API_TOKEN do not expose observability surfaces.
    allow_open_admin: bool = False

    # ------------------------------------------------------------------
    # SessionManager knobs.  ``session_idle_ttl_minutes`` is the TTL
    # after which an abandoned session handle (no poll / no submit) is
    # auto-cancelled and evicted.  ``session_reaper_interval_seconds``
    # is how often the reaper thread wakes up.  Setting the TTL to 0
    # disables reaping entirely.
    # ------------------------------------------------------------------
    session_idle_ttl_minutes: int = 60
    session_reaper_interval_seconds: int = 120
    session_token_ttl_hours: int = 24
    recovery_token_ttl_days: int = 7
    # Grace window between yielding an interrupt and clearing the
    # ``_running`` flag.  Too low and clients see spurious "prior
    # segment still running" warnings on cold LLM calls.
    session_resume_idle_timeout_seconds: float = 5.0

    # Lightweight per-process rate limits for high-cost setup and BYOK
    # validation endpoints. Values are per client IP per window.
    rate_limit_window_seconds: int = 60
    resume_parse_rate_limit_per_minute: int = 20
    jd_parse_rate_limit_per_minute: int = 30
    llm_test_rate_limit_per_minute: int = 120

    # Privacy lifecycle defaults. Cleanup is manual/script-driven unless
    # operators wire it into their scheduler.
    session_retention_days: int = 30
    trace_retention_days: int = 30
    outcome_retention_days: int = 180
    privacy_cleanup_batch_size: int = 500
    voice_ticket_ttl_seconds: int = 30

    # ------------------------------------------------------------------
    # Verifier trigger knobs (previously hard-coded in
    # engine/agents/verification.py).  ``verifier_margin`` is the
    # score gap below/above ``quality_threshold`` that qualifies a
    # pass as "marginal".  ``verifier_senior_always`` forces
    # verification on every senior-level passed answer.
    # ``verifier_dimensions_bluff_prone`` is the CSV of dimensions
    # that always trigger verification (e.g. system_design).
    # ------------------------------------------------------------------
    verifier_margin: float = 1.0
    verifier_senior_always: bool = True
    verifier_dimensions_bluff_prone: list[str] = Field(
        default_factory=lambda: ["system_design", "architecture"]
    )
    # Confidence floor below which a verifier verdict cannot overrule
    # the evaluator (audit P3 finding). Previously hard-coded as
    # MIN_OVERRIDE_CONFIDENCE = 0.55 in nodes/verification.py; promoting
    # to a setting lets ops tune the abstain band without a redeploy.
    verifier_min_override_confidence: float = 0.55

    # ------------------------------------------------------------------
    # Experience-extractor knobs (previously hard-coded).  Raising
    # ``experience_min_observations`` limits how aggressively the
    # extractor writes auto-strategies for thin evidence.
    # ------------------------------------------------------------------
    experience_min_observations: int = 5
    experience_high_reward_mean: float = 0.70
    experience_low_reward_mean: float = 0.30
    experience_score_spread_threshold: float = 3.0

    # ------------------------------------------------------------------
    # Reward shaping penalties.  A reward in [0,1] is still produced
    # by ``reward_fn.immediate_reward``; contract-violation penalties
    # are *subtracted* before the final clamp so arms that keep the
    # generator-evaluator pipeline honest accumulate more posterior
    # mass than arms that coast on scoring inflation.
    # ------------------------------------------------------------------
    reward_contract_unsigned_penalty: float = 0.10
    reward_acceptance_no_rate_threshold: float = 0.5
    reward_acceptance_no_penalty: float = 0.10
    reward_verifier_forced_refine_penalty: float = 0.15

    # ------------------------------------------------------------------
    # Evidence span alignment (see docs/PLAN_EVIDENCE_SPAN_ALIGNMENT.md).
    # ON by default so reports can surface whether evaluator evidence
    # quotes are actually traceable to the candidate answer. Operators
    # can still set EVIDENCE_SPAN_ALIGNMENT=false to return to the
    # legacy ``{"verdict","evidence"}`` shape. When ON,
    # ``evaluate_answer`` additively
    # populates ``acceptance_check_results[*].evidence_spans`` with
    # ``{"text", "start", "end", "match"}`` entries aligned to the
    # candidate answer via stdlib ``difflib`` fuzzy matching. No LLM
    # call is added; the alignment is pure post-hoc string work.
    # ``evidence_span_fuzzy_threshold`` is the minimum
    # ``overlap_len / len(quote)`` ratio at which a fuzzy (non-exact)
    # match is accepted; below that the span degrades to
    # ``{"start": -1, "end": -1, "match": "none"}``.
    # ------------------------------------------------------------------
    evidence_span_alignment: bool = True
    evidence_span_fuzzy_threshold: float = 0.6

    # ------------------------------------------------------------------
    # Verifier drift monitor (see docs/PLAN_VERIFIER_DRIFT.md). Tracks a
    # rolling window of DriftEvents at ``verification_node`` exit time
    # so operators can spot evaluator drift (e.g. Verifier repeatedly
    # overruling the evaluator, or ``evidence_spans[*].match=="none"``
    # rate creeping up over time). Pure observation surface: no LLM
    # calls, no routing changes, no DB writes. Exposed via
    # ``GET /admin/drift/verifier`` when enabled. Keep OFF unless you
    # plan to consume the snapshot in a dashboard / alerting pipeline.
    # ------------------------------------------------------------------
    enable_verifier_drift_monitor: bool = False
    verifier_drift_window_size: int = 200
    verifier_drift_backend: Literal["memory", "redis"] = "memory"
    verifier_drift_redis_prefix: str = "agentic_interviewer:verifier_drift"

    # ------------------------------------------------------------------
    # Adaptive verifier trigger (feedback loop from drift monitor).
    # Opt-in; OFF by default so the legacy ``should_trigger`` rule set
    # is the sole gate. When ON AND ``enable_verifier_drift_monitor``
    # is ON AND the per-dimension sample count is >=
    # ``verifier_adaptive_min_samples``:
    #
    # - ``override_rate >= verifier_adaptive_high_threshold`` FORCES a
    #   verifier call even on a clean pass (high-drift dimensions get
    #   extra scrutiny automatically).
    # - ``override_rate <= verifier_adaptive_low_threshold`` AND the
    #   evaluator's score is comfortably above threshold (score >
    #   quality_threshold + verifier_margin) SKIPS the verifier call
    #   even when baseline rules would have fired (low-drift
    #   dimensions stop paying the LLM tax).
    # - Middle range: fall through to the baseline rules unchanged.
    #
    # This is the "Verifier -> bandit feedback" loop:
    # drift monitor observations close the adaptation loop without
    # touching the bandit posterior directly. See
    # ``docs/PLAN_VERIFIER_DRIFT.md §11`` (follow-ups) for the design
    # note. Keep thresholds conservative so rollout can be monitored
    # via ``GET /admin/drift/verifier`` before tightening.
    # ------------------------------------------------------------------
    verifier_adaptive_trigger: bool = False
    verifier_adaptive_high_threshold: float = 0.25
    verifier_adaptive_low_threshold: float = 0.05
    verifier_adaptive_min_samples: int = 30

    # ------------------------------------------------------------------
    # Skill injection (see docs/PLAN_SKILL_INJECTION.md).  When ON,
    # ``ask_question_node`` reads ``app.memory.skill_store`` for cards
    # matching the current ``(dimension, job_level)`` and splices them
    # into the Generator's ``skills`` prompt slot.  Sibling feature to
    # the existing strategy injection (``strategy_store``): strategies
    # are reward-driven memory maintained by ``strategy_dream``, skills
    # are hand-authored business know-how curated by humans.  Default
    # OFF because shipping without any authored skill cards would
    # inject the ``"(no relevant interview skills)"`` placeholder on
    # every turn for no benefit.
    # ------------------------------------------------------------------
    enable_skill_injection: bool = False
    skill_retrieval_limit: int = 3

    # ------------------------------------------------------------------
    # LLM memory selector (see docs/PLAN_LLM_MEMORY_SELECTOR.md). When
    # ON, :mod:`app.memory.skill_store` and :mod:`app.memory.strategy_store`
    # run their keyword-filtered top-N through
    # :func:`app.memory.llm_selector.select_memories_with_llm` for a
    # second-pass semantic selection (Claude Code ``findRelevantMemories.sideQuery``
    # equivalent). Failure degrades silently back to the keyword
    # top-N. Default OFF because it adds one LLM call per
    # ``retrieve_*`` invocation and the current card counts (~2
    # skills, handful of strategies) are small enough that keyword
    # routing is already adequate.
    # ------------------------------------------------------------------
    enable_llm_memory_selector: bool = False
    llm_memory_selector_top_n: int = 5

    # ------------------------------------------------------------------
    # Drift → Evaluator prompt feedback (see docs/PLAN_DRIFT_FEEDBACK.md).
    # When ON, ``evaluator_node`` reads
    # :class:`VerifierDriftMonitor`'s ``overruled_patterns`` snapshot,
    # renders the top-``drift_feedback_top_n`` into a Markdown
    # negative-examples block, and injects it into the Evaluator's
    # ``dynamic_system`` context slot. Prompt-cache behaviour is
    # unchanged (dynamic_system was never cached).  Default OFF so
    # existing deployments see Phase-1 byte-identical Evaluator
    # prompts; requires ``enable_verifier_drift_monitor=True`` to
    # actually accumulate signal to feed back.
    # ------------------------------------------------------------------
    enable_evaluator_prompt_feedback: bool = False
    drift_feedback_top_n: int = 3
    drift_feedback_min_support: int = 2

    # ------------------------------------------------------------------
    # Drift → Generator avoid-patterns feedback
    # (see docs/PLAN_DRIFT_RAG_FEEDBACK.md). Companion to the Evaluator
    # feedback flag above: same ``VerifierDriftMonitor.overruled_patterns``
    # backing store, different renderer. When ON,
    # ``ask_question_node`` injects a Markdown "avoid patterns" block
    # into the Generator's ``avoid_patterns`` payload slot so the next
    # question is designed AWAY from the shallow evidence shapes that
    # historically got overruled on this dimension. Requires
    # ``enable_verifier_drift_monitor=True`` to have any data to feed
    # back. Shares ``drift_feedback_top_n`` / ``drift_feedback_min_support``
    # thresholds with the Evaluator path.
    # ------------------------------------------------------------------
    enable_generator_avoid_patterns: bool = False

    # ------------------------------------------------------------------
    # Probe intent (see docs/PLAN_PROBE_INTENT.md). When ON,
    # ``ask_question_node`` resolves a direction-aware
    # ``ProbeIntent`` from ``(direction, dimension, job_level,
    # evaluation.weaknesses)`` and injects it into the Generator's
    # ``PROBE_INTENT`` prompt slot. This controls *how* the follow-up
    # question probes the candidate (architecture challenge vs evidence
    # request vs roleplay scenario) without changing the plan topology.
    # Keep the env knob so deployments can temporarily return to the
    # pre-intent prompt shape if needed.
    # ------------------------------------------------------------------
    enable_probe_intent: bool = True

    @property
    def effective_langsmith_project(self) -> str:
        """Project name actually forwarded to the LangSmith SDK.

        When :attr:`langsmith_project_split_by_env` is True, the
        ``app_env`` value is appended as a suffix so a single base
        project name (e.g. ``agentic-interviewer``) fans out into
        ``agentic-interviewer-dev`` / ``agentic-interviewer-prod`` /
        ``agentic-interviewer-test``. This prevents local debugging
        traces from polluting the production dashboard and - equally
        important - prevents production volume from drowning out the
        handful of CI runs you want to inspect.

        The helper is a pure property so tests can stub a
        ``_StubSettings`` without monkey-patching environment
        variables.
        """
        base = (self.langsmith_project or "").strip() or "agentic-interviewer"
        if not self.langsmith_project_split_by_env:
            return base
        env = (self.app_env or "dev").strip() or "dev"
        return f"{base}-{env}"

    @property
    def use_stub_llm(self) -> bool:
        """Stub mode: no network calls, deterministic fixtures.

        Activated when provider is ``stub`` or when the relevant API
        key is missing. Using a stub keeps the graph testable without
        leaking real keys during CI.
        """
        def has_real_key(value: str | None) -> bool:
            key = (value or "").strip()
            if not key:
                return False
            lowered = key.lower()
            placeholders = {
                "sk-replace-me",
                "replace-me",
                "changeme",
                "change-me",
                "your-api-key",
                "your-openai-api-key",
                "placeholder",
            }
            return lowered not in placeholders and "replace-me" not in lowered

        if self.llm_provider == "stub":
            return True
        if self.llm_provider == "openai" and not has_real_key(self.openai_api_key):
            return True
        if self.llm_provider == "anthropic" and not has_real_key(self.anthropic_api_key):
            return True
        if self.llm_provider == "deepseek" and not has_real_key(self.deepseek_api_key):
            return True
        if self.llm_provider in {
            "kimi",
            "moonshot",
            "qwen",
            "dashscope",
            "zhipu",
            "mistral",
            "openai_compatible",
        } and not has_real_key(self.openai_api_key):
            return True
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so we don't re-parse the env on every call."""
    return Settings()
