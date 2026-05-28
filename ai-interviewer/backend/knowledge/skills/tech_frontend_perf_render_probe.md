---
id: tech_frontend_perf_render_probe
name: Frontend Performance and Render Probe
description: Push frontend performance answers toward Core Web Vitals baseline, render-path bottleneck, and one regression caught in production.
display_name_zh: 前端性能与渲染追问卡
display_description_zh: 引导前端性能回答覆盖 Core Web Vitals 基线、渲染路径瓶颈和一次线上回归发现。
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [frontend_web, mobile, ai_fullstack]
dimensions: [technical_depth, system_design, problem_solving]
job_levels: [junior, mid, senior, staff]
probe_intents: [performance_probe, tradeoff_probe, evidence_probe]
failure_categories: [missing_evidence, shallow_analysis, weak_attribution]
generator_moves:
  - "Ask for FCP / LCP / INP / CLS baseline, the bottleneck path (hydration / bundle / network / paint), and the one metric that moved."
  - "Probe SSR vs CSR vs streaming tradeoff, code-split granularity, and how the candidate decided which route to optimize first."
  - "Require one regression that LCP / INP caught in production and how it surfaced (RUM, synthetic, or user report)."
watch_for:
  - "Connects render budget to a real device + network class (low-end Android, 3G, throttled CPU)."
  - "Distinguishes tools used (Lighthouse, WebPageTest, Chrome DevTools, RUM) and what each one was meant to answer."
avoid:
  - "Accepting 'add memo / virtualize list / use SWR / lazy load' without showing it was on the critical path."
  - "Letting the answer talk only about averages when a tail-latency metric (INP, p95) is the actual user pain."
evaluator_rubric_hints:
  - "Credit baseline metric, identified bottleneck path, tradeoff explanation, and one production regression caught."
positive_signals:
  - "Mentions LCP element, hydration cost, JS execution time, critical CSS, or font-loading tradeoff with a number attached."
negative_signals:
  - "Optimizes a component without showing the change moved a Core Web Vital on a real device."
score_bias_rules:
  - "Soft positive when the candidate names what they intentionally did not optimize and why (e.g. admin-only route, low-traffic page)."
evaluator_visibility: true
---

Use when the candidate discusses page speed, bundle size, rendering
strategy, hydration cost, list virtualization, image / font delivery, or
any topic touching Core Web Vitals on web / hybrid apps.

- Anchor every claim to a baseline: which device class, which network
  profile, which route, which user segment. "We made the page faster"
  without a device / network anchor is rejected.
- Force the **bottleneck path** to surface: was the issue main-thread
  JS, hydration cost, render-blocking CSS, image bytes, fetch
  waterfall, or third-party scripts? The optimization name should fall
  out of the bottleneck, not the other way around.
- Probe one **rejected** optimization: SSR vs CSR vs RSC, lazy hydration
  vs full SSR, edge SSR vs origin SSR. Strong answers name the tradeoff
  they took (cost / DX / SEO / TTFB).
- Require one production regression that a metric caught: an INP spike
  after a deploy, an LCP regression after an A/B test rollout, or a CLS
  jump after an ad-slot redesign. Insist on the alert source and the
  rollback decision.
- Reject "added memo / virtualization / SWR" answers that cannot show
  the optimization was on the critical render path for a real route.
