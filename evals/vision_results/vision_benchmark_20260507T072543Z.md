# OpenRouter Vision On/Off Benchmark

- Run at: 2026-05-07T07:25:43.038036+00:00
- Models: Gemini 3.1 Pro, Claude Opus 4.7, GPT-5.5 via OpenRouter
- Task 2 cases: vision-heavy browser tasks
- Task 3 cases: legacy / foreign issuer / proxy-heavy filings
- Scoring note: `OK rate` is status-level automation. For visual extraction, manually inspect the JSON `answer_preview` before treating a row as semantically correct.

## Summary

| Task | Model | Vision | Cases | OK rate | Cost | Avg latency | LLM calls |
|---|---|---:|---:|---:|---:|---:|---:|
| task2 | `anthropic/claude-opus-4.7` | False | 1 | 0.000 | $0.782115 | 118904.6 ms | 24 |
| task2 | `anthropic/claude-opus-4.7` | True | 1 | 1.000 | $0.048690 | 27544.9 ms | 1 |
| task2 | `google/gemini-3.1-pro-preview` | False | 1 | 1.000 | $0.003805 | 21843.4 ms | 1 |
| task2 | `google/gemini-3.1-pro-preview` | True | 1 | 1.000 | $0.003800 | 21114.9 ms | 1 |
| task2 | `openai/gpt-5.5` | False | 1 | 1.000 | $0.067510 | 93390.5 ms | 6 |
| task2 | `openai/gpt-5.5` | True | 1 | 1.000 | $0.035255 | 49822.4 ms | 3 |
| task3 | `anthropic/claude-opus-4.7` | False | 1 | 1.000 | $0.000000 | 1196.5 ms | 0 |
| task3 | `anthropic/claude-opus-4.7` | True | 1 | 1.000 | $0.000000 | 1226.6 ms | 0 |
| task3 | `google/gemini-3.1-pro-preview` | False | 1 | 1.000 | $0.000000 | 1977.5 ms | 0 |
| task3 | `google/gemini-3.1-pro-preview` | True | 1 | 1.000 | $0.000000 | 1231.1 ms | 0 |
| task3 | `openai/gpt-5.5` | False | 1 | 1.000 | $0.000000 | 1051.2 ms | 0 |
| task3 | `openai/gpt-5.5` | True | 1 | 1.000 | $0.000000 | 1267.1 ms | 0 |

## Rows

- `task2` `t2_vision_image_caption` `google/gemini-3.1-pro-preview` vision=False: status=success, steps=3, cost=$0.003805, latency=21843.4 ms
- `task3` `t3_apple_2005_old_format` `google/gemini-3.1-pro-preview` vision=False: items=18/23, cost=$0.000000, latency=1977.5 ms
- `task2` `t2_vision_image_caption` `google/gemini-3.1-pro-preview` vision=True: status=success, steps=3, cost=$0.003800, latency=21114.9 ms
- `task3` `t3_apple_2005_old_format` `google/gemini-3.1-pro-preview` vision=True: items=18/23, cost=$0.000000, latency=1231.1 ms
- `task2` `t2_vision_image_caption` `anthropic/claude-opus-4.7` vision=False: status=partial, steps=15, cost=$0.782115, latency=118904.6 ms
- `task3` `t3_apple_2005_old_format` `anthropic/claude-opus-4.7` vision=False: items=18/23, cost=$0.000000, latency=1196.5 ms
- `task2` `t2_vision_image_caption` `anthropic/claude-opus-4.7` vision=True: status=success, steps=3, cost=$0.048690, latency=27544.9 ms
- `task3` `t3_apple_2005_old_format` `anthropic/claude-opus-4.7` vision=True: items=18/23, cost=$0.000000, latency=1226.6 ms
- `task2` `t2_vision_image_caption` `openai/gpt-5.5` vision=False: status=success, steps=5, cost=$0.067510, latency=93390.5 ms
- `task3` `t3_apple_2005_old_format` `openai/gpt-5.5` vision=False: items=18/23, cost=$0.000000, latency=1051.2 ms
- `task2` `t2_vision_image_caption` `openai/gpt-5.5` vision=True: status=success, steps=4, cost=$0.035255, latency=49822.4 ms
- `task3` `t3_apple_2005_old_format` `openai/gpt-5.5` vision=True: items=18/23, cost=$0.000000, latency=1267.1 ms
