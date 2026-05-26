---
id: senior_backend_distributed_state_probe
name: Senior Backend Distributed State Probe
description: Probe senior backend / architect answers for consistency model, partition-time behavior, and one ordering / dedup invariant they personally defended.
display_name_zh: 高级后端分布式状态追问卡
display_description_zh: 引导高级后端或架构回答覆盖一致性模型、分区期间行为，以及亲自维护的排序或去重不变量。
status: active
priority: 8
direction_tags: [internet_tech]
role_tags: [java_backend, architect, ai_fullstack]
dimensions: [system_design, technical_depth, problem_solving, project_experience]
job_levels: [senior, staff, principal]
probe_intents: [architecture_challenge, contract_probe, tradeoff_probe]
failure_categories: [missing_scale_reasoning, vague_process, missing_risk_boundary]
generator_moves:
  - "Ask which consistency model the system advertised (strong, linearizable, sequential, causal, read-your-writes, eventual) and where the boundary sat."
  - "Probe partition-time behavior: which side stays available, which side rejects, what the client sees, and which CAP / PACELC tradeoff was committed in writing."
  - "Ask about one ordering / dedup invariant they personally defended: idempotency key, sequence number, fencing token, transaction outbox, or compensating action."
watch_for:
  - "Names the failure mode the chosen consistency model controls and the cost it forces on the application layer."
  - "Distinguishes consensus (Raft / Paxos / Zab), replication, and quorum reads — does not collapse them into 'we use Zookeeper / etcd'."
avoid:
  - "Accepting 'we use distributed transactions' or 'we use Kafka exactly-once' without explaining the actual delivery guarantee at the consumer."
  - "Letting the answer drift to framework features without owning the data-correctness contract."
evaluator_rubric_hints:
  - "Credit explicit consistency model, partition-time behavior, ordering / dedup invariant, and the application-side cost of the chosen guarantee."
positive_signals:
  - "Mentions idempotency token, fencing, outbox / inbox pattern, vector clock, hybrid logical clock, or saga compensation step."
negative_signals:
  - "Believes a database default is sufficient for cross-service correctness without naming the boundary."
score_bias_rules:
  - "Soft positive when the candidate explains a stronger guarantee they intentionally rejected because the cost was not worth the correctness it bought."
evaluator_visibility: true
---

Use when the scenario requires distributed state ownership: payment
processing, inventory, ride-hailing dispatch, multi-region writes,
order workflow, stream joins with state, or any system whose
correctness survives node loss and network partition.

- Anchor every claim in a **named consistency model**. "We use
  distributed transactions" is not a model; "we offer linearizable
  reads on the primary key and read-your-writes on secondary
  indexes" is.
- Force a **partition-time decision**: when a partition happens,
  which side stays available, which side rejects, what error the
  client sees. CAP must land on one side — the strongest answers
  also explain the PACELC latency cost during the non-partitioned
  case.
- Probe one **ordering / dedup invariant** the candidate personally
  defended: idempotency key, fencing token, monotonic sequence,
  transaction outbox, saga compensation. The strongest answers
  name the application-level recovery code that runs when the
  invariant is violated.
- Reject "we use Kafka exactly-once" / "Zookeeper handles it" /
  "Spanner is strongly consistent" as ceiling claims. Probe the
  consumer-side delivery guarantee, the failure mode that survives
  the abstraction, and the cost the application layer paid.
- For staff+ candidates, probe **the organisational cost**: how the
  consistency contract was negotiated with caller teams, how
  on-call runbooks handle split-brain, how schema migration
  preserves the chosen guarantee.
