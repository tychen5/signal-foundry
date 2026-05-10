# OpenRouter Vision On/Off Benchmark

- Run at: 2026-05-08T10:26:14.840296+00:00
- Models: Gemini 3.1 Pro, Claude Opus 4.7, GPT-5.5 via OpenRouter
- Task 2 cases: vision-heavy browser tasks
- Task 3 cases: legacy / foreign issuer / proxy-heavy filings

## Summary

| Task | Model | Vision | Cases | OK rate | Cost | Avg latency | LLM calls |
|---|---|---:|---:|---:|---:|---:|---:|
| task3 | `google/gemini-3.1-pro-preview` | False | 5 | 0.800 | $0.046195 | 158837.7 ms | 28 |
| task3 | `google/gemini-3.1-pro-preview` | True | 5 | 0.600 | $0.039959 | 202197.3 ms | 25 |
| task3 | `moonshotai/kimi-k2.6` | False | 5 | 0.600 | $0.022400 | 131420.7 ms | 6 |
| task3 | `moonshotai/kimi-k2.6` | True | 5 | 1.000 | $0.000000 | 23759.7 ms | 0 |

## Rows

- `task3` `t3_american_express_1994_plain_text` `moonshotai/kimi-k2.6` vision=False: items=10/23, conf=0.988, cost=$0.018970, latency=100932.7 ms
- `task3` `t3_asset_backed_trust_2011_not_applicable` `moonshotai/kimi-k2.6` vision=False: items=0/0, conf=n/a, cost=$0.000000, latency=240000.0 ms
- `task3` `t3_kingsoft_cloud_2022_20f_duplicate_heading` `moonshotai/kimi-k2.6` vision=False: items=0/0, conf=n/a, cost=$0.000000, latency=240000.0 ms
- `task3` `t3_enron_2000_complex_segments` `moonshotai/kimi-k2.6` vision=False: items=15/23, conf=0.933, cost=$0.003430, latency=48573.5 ms
- `task3` `t3_lehman_2007_investment_bank` `moonshotai/kimi-k2.6` vision=False: items=20/23, conf=0.907, cost=$0.000000, latency=27597.4 ms
- `task3` `t3_american_express_1994_plain_text` `moonshotai/kimi-k2.6` vision=True: items=10/23, conf=0.9, cost=$0.000000, latency=21169.8 ms
- `task3` `t3_asset_backed_trust_2011_not_applicable` `moonshotai/kimi-k2.6` vision=True: items=20/23, conf=0.91, cost=$0.000000, latency=19917.6 ms
- `task3` `t3_kingsoft_cloud_2022_20f_duplicate_heading` `moonshotai/kimi-k2.6` vision=True: items=16/23, conf=0.541, cost=$0.000000, latency=27605.7 ms
- `task3` `t3_enron_2000_complex_segments` `moonshotai/kimi-k2.6` vision=True: items=15/23, conf=0.907, cost=$0.000000, latency=23684.0 ms
- `task3` `t3_lehman_2007_investment_bank` `moonshotai/kimi-k2.6` vision=True: items=20/23, conf=0.907, cost=$0.000000, latency=26421.6 ms
- `task3` `t3_american_express_1994_plain_text` `google/gemini-3.1-pro-preview` vision=False: items=11/24, conf=1.0, cost=$0.008714, latency=69953.5 ms
- `task3` `t3_asset_backed_trust_2011_not_applicable` `google/gemini-3.1-pro-preview` vision=False: items=20/23, conf=0.962, cost=$0.006206, latency=100532.5 ms
- `task3` `t3_kingsoft_cloud_2022_20f_duplicate_heading` `google/gemini-3.1-pro-preview` vision=False: items=0/0, conf=n/a, cost=$0.000000, latency=240000.0 ms
- `task3` `t3_enron_2000_complex_segments` `google/gemini-3.1-pro-preview` vision=False: items=20/28, conf=0.996, cost=$0.015335, latency=204302.3 ms
- `task3` `t3_lehman_2007_investment_bank` `google/gemini-3.1-pro-preview` vision=False: items=25/28, conf=0.979, cost=$0.015940, latency=179400.2 ms
- `task3` `t3_american_express_1994_plain_text` `google/gemini-3.1-pro-preview` vision=True: items=11/24, conf=1.0, cost=$0.008744, latency=104682.8 ms
- `task3` `t3_asset_backed_trust_2011_not_applicable` `google/gemini-3.1-pro-preview` vision=True: items=0/0, conf=n/a, cost=$0.000000, latency=240000.0 ms
- `task3` `t3_kingsoft_cloud_2022_20f_duplicate_heading` `google/gemini-3.1-pro-preview` vision=True: items=0/0, conf=n/a, cost=$0.000000, latency=240000.0 ms
- `task3` `t3_enron_2000_complex_segments` `google/gemini-3.1-pro-preview` vision=True: items=20/28, conf=0.996, cost=$0.015405, latency=194576.2 ms
- `task3` `t3_lehman_2007_investment_bank` `google/gemini-3.1-pro-preview` vision=True: items=25/28, conf=0.978, cost=$0.015810, latency=231727.4 ms
