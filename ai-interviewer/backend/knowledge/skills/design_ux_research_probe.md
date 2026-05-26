---
id: design_ux_research_probe
name: UX Research and Design Decision Probe
description: Probe UX designers for user research evidence, design tradeoffs against constraints, and one shipped decision they had to defend.
display_name_zh: UX 研究与设计决策追问卡
display_description_zh: 引导 UX 设计回答覆盖用户研究证据、约束下的设计取舍，以及一个需要捍卫的已上线决策。
status: active
priority: 7
direction_tags: [business]
role_tags: [ux_designer]
dimensions: [user_insight, problem_solving, communication, stakeholder_management]
job_levels: [junior, mid, senior, staff]
probe_intents: [evidence_probe, tradeoff_probe, stakeholder_pushback_probe]
failure_categories: [missing_evidence, weak_attribution, weak_stakeholder_alignment]
generator_moves:
  - "Ask which user research method they used, how many users were involved, and what segment those users represented."
  - "Probe the design tradeoffs: which competing pattern they rejected, why, and which constraint (engineering, accessibility, business) forced the call."
  - "Ask one design decision they had to defend after launch, what evidence they brought to that defense, and what they would change today."
watch_for:
  - "Distinguishes user behaviour (observed) from user opinion (reported) and weights them appropriately."
  - "Names the accessibility, localisation, or device constraint that shaped the final design."
avoid:
  - "Accepting 'we did user research' without sample, method, or behavioural artifact."
  - "Letting the answer become a portfolio pitch instead of a decision narrative."
evaluator_rubric_hints:
  - "Credit named research method, user segment, rejected pattern, constraint owner, and post-launch evidence."
positive_signals:
  - "Mentions task success rate, time on task, accessibility audit, usability study read-out, or a heuristic walkthrough that changed the spec."
negative_signals:
  - "Treats every design decision as a stakeholder consensus, with no user evidence cited."
score_bias_rules:
  - "Soft positive when the candidate names a beautiful design they intentionally killed because the user evidence said no."
evaluator_visibility: true
---

Use when the candidate is interviewing for UX / product design,
interaction design, design systems, or any role that owns the user-
facing surface of a product.

- Anchor every claim in **observed user behaviour**, not designer
  intuition. Probe the method (interview, usability test, diary
  study, analytics review, accessibility audit) and the sample size
  / segment.
- Force a **rejected design pattern**: which alternative they
  prototyped, why they killed it, and which constraint (engineering
  cost, accessibility, brand, regulation) made the kill obvious in
  retrospect.
- Probe **one shipped decision they had to defend**: the data they
  brought to the room, the stakeholder who pushed back, what changed
  in v2 because of post-launch evidence.
- Reject portfolio-style narration. Strong designers can describe a
  decision as a sequence of evidence → constraint → tradeoff → ship
  → measure → adjust.
- For staff+ designers, probe **design system reach**: how patterns
  were adopted across teams, how exceptions were governed, and how
  design debt was inventoried.
