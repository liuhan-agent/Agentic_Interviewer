# System Design Question Bank

## Design: URL shortener with analytics
Rubric focus: capacity estimation, hotkey handling, analytics pipeline
trade-offs, read/write path separation, eventual consistency windows.

Probe deeper on:
- how to protect against enumeration of short codes
- how to isolate analytics writes from the read path
- what guarantees you make about click counts vs uniques

## Design: real-time collaborative editor
Rubric focus: CRDT vs OT, presence channel, conflict semantics, persistence,
offline reconciliation.

Probe deeper on:
- how cursor presence is throttled to avoid n^2 fanout
- what happens when two clients edit the same character during a network
  partition

## Design: recommendation service with online learning
Rubric focus: feature store latency budget, model rollout vs shadow,
guardrails against runaway training signals, exploration vs exploitation.

Probe deeper on:
- how you separate "serving features" from "training features" without
  skew
- how you decide to roll back a model that has degraded on a narrow
  cohort only
