---
name: Senior Backend Ownership Probe
description: Force ownership and quantified impact in senior backend answers.
dimensions: [leadership, system_design, problem_solving]
job_levels: [senior, staff, principal]
---

When interviewing senior / staff / principal backend candidates:

- Probe for **what the candidate personally owned**, not what "the team"
  did. If the answer stays in first-person plural, the next probe
  should name a concrete artefact ("who wrote the RFC?", "whose
  on-call burned?", "which pager alert did you specifically silence?").
- Reject **buzzword-heavy storytelling** that does not quantify
  impact. A valid senior-level answer includes at least one number:
  latency saved, incidents prevented, cost reduced, headcount
  unblocked. If the candidate keeps speaking in qualitative terms,
  the follow-up question is always "by how much, over what window?".
- **Ownership asymmetry**: a candidate taking credit for design AND
  implementation AND rollout AND on-call is usually a solo
  contributor in an engineering team. Probe one layer deeper on each
  claim to surface true ownership boundaries — the strongest
  signals come from the parts they explicitly hand off.
- When the candidate mentions a **migration** or **decommission**,
  the follow-up is always: "what did you leave running in
  compatibility mode, and for how long?". Clean answers rarely
  come from senior ICs who did real migrations.
