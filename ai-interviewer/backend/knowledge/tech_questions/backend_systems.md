# Backend / Systems Question Bank (Senior)

## Distributed databases
- Walk me through how you would design an idempotency key for a payments
  API. What happens if the client retries after a network blip mid-write?
- A read-heavy service is showing tail latency spikes every 30 seconds.
  Where do you start looking, and what tools do you reach for first?
- Your service has a 99.9% SLO. You observe error budget burn of 40% in
  the first week of the month. Walk me through your response.

## Concurrency & correctness
- Explain optimistic vs pessimistic concurrency. When would you pick one
  over the other in a multi-writer inventory system?
- How do you reason about exactly-once semantics across a producer, a
  queue, and a consumer? Is it ever actually possible?
- Describe a race condition you have personally debugged in production.

## Caching
- Design a cache invalidation strategy for user profile data that is
  read 10k rps but only mutated a few times per day. Trade-offs?
- What breaks when TTL-based caches and write-through caches meet? How
  do you detect stale reads?

## Schema evolution
- Walk me through a zero-downtime migration for renaming a column that
  is read by two separate services.
- How do you handle backward-incompatible wire format changes in a
  system with slow-rolling clients?
