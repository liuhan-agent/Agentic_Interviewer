---
id: tech_mobile_platform_probe
name: Mobile Platform Probe
description: Force mobile answers toward OS / device constraint, APM-grounded measurement, and a reversible hotfix path.
display_name_zh: 移动端平台追问卡
display_description_zh: 引导移动端回答覆盖 OS 或设备约束、APM 支撑的度量，以及可回滚的热修路径。
status: active
priority: 7
direction_tags: [internet_tech]
role_tags: [mobile]
dimensions: [coding_quality, technical_depth, project_experience, problem_solving]
job_levels: [junior, mid, senior, staff]
probe_intents: [evidence_probe, performance_probe, rollout_probe]
failure_categories: [missing_risk_boundary, missing_evidence, weak_follow_up]
generator_moves:
  - "Ask which iOS / Android version range and device class was the binding constraint, and what feature got cut or gated by it."
  - "Probe one cold-start / battery / memory / crash-rate measurement, the APM source it came from, and the fix that moved it."
  - "Ask about the hotfix path actually used in production: forced upgrade, JSBridge patch, RN / Flutter bundle push, remote config rollback — and what was reversible without a store review."
watch_for:
  - "Names a specific OS deprecation, store policy, permission prompt, or APM signal (Crashlytics, Sentry, Bugly, Firebase Performance)."
  - "Distinguishes development-machine measurement from real-user devices."
avoid:
  - "Accepting 'we used React Native / Flutter / native' as platform answer without an OS-level constraint or device-class anchor."
  - "Letting the answer skip rollout reality: review window, force-upgrade UX, partial rollout cohort, rollback gate."
evaluator_rubric_hints:
  - "Credit explicit OS / device constraint, APM-sourced measurement, and at least one reversible hotfix path."
positive_signals:
  - "Names crash-free session rate, ANR rate, p95 cold start, energy log, or memory warning category."
negative_signals:
  - "Treats mobile delivery as a backend deploy and ignores store / device fragmentation realities."
score_bias_rules:
  - "Soft positive when the candidate explains what they kept native vs cross-platform and why."
evaluator_visibility: true
---

Use when the candidate discusses mobile app delivery: native iOS /
Android, React Native, Flutter, hybrid containers, mini programs, or
any topic touching app-store rollout, device fragmentation, OS upgrade,
crash analytics, or mobile performance budgets.

- Anchor every answer in **OS version + device class**: which iOS /
  Android range supported, which low-end device was the floor, which
  policy (App Tracking Transparency, scoped storage, notification opt-in)
  shaped the feature.
- Force at least one **APM-backed metric**: crash-free sessions, ANR
  rate, p95 cold start, frozen frame rate, memory pressure, battery
  drain. "Felt smoother" is not a number.
- Reject "we used RN / Flutter" as architecture. Probe the bridge cost,
  the native module they had to write anyway, the build-system tradeoff
  (Hermes / JSC / Skia / Impeller), and the regression class they
  intentionally accepted.
- Require a **reversible hotfix path**: forced upgrade gate, JSBridge
  patch, remote config rollback, RN / Flutter bundle push, server-side
  feature flag. If the only fix is "submit to App Store review again",
  ask how they survived a P0 incident.
- For staff+ candidates, probe organisational reality: review window,
  partial rollout cohort, crash-budget gate, on-call escalation across
  native + JS layers.
