# Phase 1 Walkthrough: Task 3 SEC 10-K Extraction

> Status: Complete for API/pipeline/eval harness | Date: 2026-05-04

## What Changed

Task 3 is now a real hybrid extraction pipeline rather than a skeleton endpoint.

Core flow:

```text
CIK/accession or filing URL
  -> SEC fetcher
  -> SGML/HTML/text normalizer
  -> rule-based item boundary parser
  -> optional LLM boundary refiner
  -> validation/autofix
  -> optional XBRL cross-check
  -> structured JSON API response
```

## Key Engineering Decisions

- **Rule-first, LLM-second**: 10-Ks are large, so the default path is deterministic and zero-cost. LLM refinement only runs for low-confidence or low-coverage parses.
- **Official SEC only**: eval cases are keyed by CIK + accession and resolved through `data.sec.gov` and `www.sec.gov/Archives`.
- **Fair access by design**: fetcher declares User-Agent, throttles below 10 req/sec, retries transient SEC/server errors, and caches downloads under `/tmp`.
- **Large-file robustness**: filing downloads stream into memory with a configured MB ceiling instead of unconstrained `response.text`.
- **SGML-aware normalization**: direct `.txt` archive submissions can include exhibits; parser extracts the primary `10-K` / `10-K/A` document first.
- **Auditable prompts**: LLM prompts live in `prompts/sec_extraction/` with a version history and rationale.

## Verification

```bash
python -m pytest tests/ -q
ruff check src/ tests/ evals/task3/run_eval.py
```

Current result:

- `61 passed`
- `ruff`: all checks passed

Live SEC smoke test:

- Apple 2023 10-K, CIK `0000320193`, accession `0000320193-23-000106`
- Raw filing: ~1.56M chars
- Normalized text: ~203K chars
- Items detected: 23
- Validation: overall valid
- LLM calls: 0
- Latency: ~973 ms

## Remaining Polish

- Build the Task 3 web UI page (`templates/task3.html`).
- Run full eval set in stable network conditions and commit a representative report.
- Convert shared schema timestamps from `datetime.utcnow()` to timezone-aware UTC.
