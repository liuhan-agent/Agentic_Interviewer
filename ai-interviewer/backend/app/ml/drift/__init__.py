"""Drift monitors: in-process rolling observability on agent behaviour.

Modules under this package expose lightweight, opt-in monitors that
watch an agent's decisions over a rolling window and surface
aggregate drift signals (e.g. Verifier overruling Evaluator, evidence
span alignment misses). They are designed to run inside the FastAPI
process with zero external dependencies, and are read via admin
endpoints (``/admin/drift/*``) on demand.

Submodules
----------
- :mod:`verifier_drift` — rolling-window monitor for
  :class:`~app.engine.agents.verification.verify_answer` calls.
- :mod:`prompt_feedback` — renders drift patterns into a negative-
  examples block that the Evaluator consumes via its
  ``dynamic_system`` context slot (``PLAN_DRIFT_FEEDBACK.md``).
"""
