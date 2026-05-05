# ML Systems Question Bank

## Data pipelines
- A feature in your training pipeline silently drifted over the last
  quarter and the model's AUC dropped 3 points in production. How do
  you investigate, and what do you put in place to prevent recurrence?
- Explain online vs offline feature parity. How do you detect skew
  between the two?

## Serving
- Walk through how you deploy a model behind a latency-sensitive API
  (p99 under 50ms). What are the biggest tail-latency risks?
- When does dynamic batching hurt more than it helps?

## Evaluation
- Your offline metric improves but online A/B shows no lift. Enumerate
  five plausible causes before picking one.
- How do you build an evaluation harness for an LLM-based feature whose
  outputs are not directly comparable between runs?
