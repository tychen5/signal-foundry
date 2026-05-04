# Task 3 SEC 10-K Eval Set

This eval set is keyed by real SEC EDGAR identifiers and is resolved at runtime through official SEC endpoints:

- Submissions metadata: `https://data.sec.gov/submissions/CIK##########.json`
- Filing documents: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_document}`
- Optional XBRL cross-check: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`

The runner uses the same production fetcher as the API, including declared User-Agent headers, fair-access throttling below 10 requests/second, bounded retries, and `/tmp` disk caching for repeated runs.

## Run

```bash
python -m evals.task3.run_eval --skip-xbrl
```

Use `--allow-llm` to enable boundary refinement. The default is rule-only so CI runs do not consume LLM credits.

## Metrics

The report captures:

- `success_rate`
- extracted item count and missing items
- item status distribution
- deterministic assertion failures
- latency and LLM cost
- failure taxonomy (`parsing_error`, `missing_section`, etc.)

Results are written to `evals/task3/results/` as JSON and Markdown.
