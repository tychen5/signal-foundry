# OpenRouter Vision On/Off Benchmark

- Run at: 2026-05-07T08:38:16.593309+00:00
- Models: Gemini 3.1 Pro, Claude Opus 4.7, GPT-5.5 via OpenRouter
- Task 2 cases: vision-heavy browser tasks
- Task 3 cases: legacy / foreign issuer / proxy-heavy filings

## Summary

| Task | Model | Vision | Cases | OK rate | Cost | Avg latency | LLM calls |
|---|---|---:|---:|---:|---:|---:|---:|
| task3 | `anthropic/claude-opus-4.7` | False | 1 | 1.000 | $0.158460 | 37566.3 ms | 10 |
| task3 | `anthropic/claude-opus-4.7` | True | 1 | 1.000 | $0.025365 | 12780.9 ms | 1 |
| task3 | `google/gemini-3.1-pro-preview` | False | 1 | 1.000 | $0.002044 | 100328.9 ms | 1 |
| task3 | `google/gemini-3.1-pro-preview` | True | 1 | 1.000 | $0.002059 | 30131.4 ms | 1 |
| task3 | `openai/gpt-5.5` | False | 1 | 1.000 | $0.008365 | 106466.8 ms | 1 |
| task3 | `openai/gpt-5.5` | True | 1 | 1.000 | $0.008230 | 56690.3 ms | 1 |

## Rows

- `task3` `t3_apple_2023` `google/gemini-3.1-pro-preview` vision=False: items=23/23, cost=$0.002044, latency=100328.9 ms
- `task3` `t3_apple_2023` `google/gemini-3.1-pro-preview` vision=True: items=23/23, cost=$0.002059, latency=30131.4 ms
- `task3` `t3_apple_2023` `anthropic/claude-opus-4.7` vision=False: items=23/24, cost=$0.158460, latency=37566.3 ms
- `task3` `t3_apple_2023` `anthropic/claude-opus-4.7` vision=True: items=23/23, cost=$0.025365, latency=12780.9 ms
- `task3` `t3_apple_2023` `openai/gpt-5.5` vision=False: items=23/23, cost=$0.008365, latency=106466.8 ms
- `task3` `t3_apple_2023` `openai/gpt-5.5` vision=True: items=23/23, cost=$0.008230, latency=56690.3 ms
