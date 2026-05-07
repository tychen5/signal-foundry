# OpenRouter Vision On/Off Benchmark

- Run at: 2026-05-07T08:43:55.793893+00:00
- Models: Gemini 3.1 Pro, Claude Opus 4.7, GPT-5.5 via OpenRouter
- Task 2 cases: vision-heavy browser tasks
- Task 3 cases: `t3_apple_2023` with `--force-llm-task3` and `T3_FORCE_LLM_MAX=1`

## Summary

| Task | Model | Vision | Cases | OK rate | Cost | Avg latency | LLM calls |
|---|---|---:|---:|---:|---:|---:|---:|
| task3 | `anthropic/claude-opus-4.7` | False | 1 | 1.000 | $0.024240 | 5809.4 ms | 1 |
| task3 | `anthropic/claude-opus-4.7` | True | 1 | 1.000 | $0.025365 | 10678.1 ms | 1 |
| task3 | `google/gemini-3.1-pro-preview` | False | 1 | 1.000 | $0.002044 | 83375.8 ms | 1 |
| task3 | `google/gemini-3.1-pro-preview` | True | 1 | 1.000 | $0.002059 | 29726.4 ms | 1 |
| task3 | `openai/gpt-5.5` | False | 1 | 1.000 | $0.008155 | 112359.9 ms | 1 |
| task3 | `openai/gpt-5.5` | True | 1 | 1.000 | $0.008275 | 42347.6 ms | 1 |

## Rows

- `task3` `t3_apple_2023` `google/gemini-3.1-pro-preview` vision=False: items=23/23, cost=$0.002044, latency=83375.8 ms
- `task3` `t3_apple_2023` `google/gemini-3.1-pro-preview` vision=True: items=23/23, cost=$0.002059, latency=29726.4 ms
- `task3` `t3_apple_2023` `anthropic/claude-opus-4.7` vision=False: items=23/23, cost=$0.024240, latency=5809.4 ms
- `task3` `t3_apple_2023` `anthropic/claude-opus-4.7` vision=True: items=23/23, cost=$0.025365, latency=10678.1 ms
- `task3` `t3_apple_2023` `openai/gpt-5.5` vision=False: items=23/23, cost=$0.008155, latency=112359.9 ms
- `task3` `t3_apple_2023` `openai/gpt-5.5` vision=True: items=23/23, cost=$0.008275, latency=42347.6 ms

## Interpretation

This run proves the Task 3 multimodal Stage 2 path is live. All three
OpenRouter models executed one forced boundary-refine call with and without
vision. The harness keeps the deterministic item number fixed during forced
refinement, so the LLM can improve offset/title/status/confidence without
renaming a known boundary and triggering unnecessary missing-item detection.
