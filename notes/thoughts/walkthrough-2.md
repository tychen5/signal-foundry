# Phase 1 Task 3: SEC 10-K Extraction Pipeline — Audit Walkthrough

## Requirement Traceability

### ✅ Core Pipeline (progress_notes item 2.2)
> Pipeline: CIK + accession → structured JSON → `part`, `item_number`, `item_title`, `content_text`, `char_range`, `status`

| Component | File | Status |
|---|---|---|
| Pipeline Orchestrator | [pipeline.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/pipeline.py) | ✅ Complete |
| SEC Fetcher | [fetcher.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/fetcher.py) | ✅ Complete |
| HTML Normalizer | [normalizer.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/normalizer.py) | ✅ Complete |
| Rule Parser (Stage 1) | [rule_parser.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/rule_parser.py) | ✅ Complete |
| LLM Refiner (Stage 2) | [llm_refiner.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/llm_refiner.py) | ✅ Complete |
| Validator (Stage 3) | [validator.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/validator.py) | ✅ Complete |
| XBRL Cross-Check (Stage 4) | [xbrl_client.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/xbrl_client.py) | ✅ Complete |
| Schemas | [schemas.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/schemas.py) | ✅ 22 items + variants |
| API Router | [router.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/task3_sec/router.py) | ✅ 3 endpoints |

### ✅ SEC Official API Integration (progress_notes item 2.3)
- `User-Agent` header configured: `signal-foundry/1.0`
- Rate limiting: `asyncio.Semaphore(8)` + 120ms interval = ~8 req/sec (safely under 10)
- Submissions API: `data.sec.gov/submissions/CIK{padded}.json`
- XBRL Company Facts: `data.sec.gov/api/xbrl/companyfacts/`
- Archive index fallback: `sec.gov/Archives/edgar/data/{CIK}/{acc}/index.json`

### ✅ Evaluation Set (progress_notes items 2.4, 2.7)
- [eval_set.json](file:///mnt/c/Users/leoqa/Documents/signal-foundry/evals/task3/eval_set.json): 8 real SEC filings
- Covers: tech (Apple, Microsoft, Tesla), finance (JPMorgan), energy (Exxon), pharma (Pfizer), small-cap, legacy format (Apple 2005)
- [run_eval.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/evals/task3/run_eval.py): Full eval runner with JSON + Markdown reports

### ✅ Prompt Versioning (progress_notes items 2.6, 2.9)
- All prompts in [prompts/sec_extraction/](file:///mnt/c/Users/leoqa/Documents/signal-foundry/prompts/sec_extraction/)
- Version ledger: [README.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/prompts/sec_extraction/README.md)
- 3 versioned prompts: `v2_boundary_refine.txt`, `v2_missing_item_detect.txt`, `v2_reflexive_validate.txt`

### ✅ Robustness Features (progress_notes item 2.7, 2.8)
- **Disk cache**: `/tmp/signal_foundry_sec_cache/` to avoid repeated downloads
- **Streaming download**: `_download_text_streaming()` with byte ceiling (`SEC_MAX_DOWNLOAD_MB=200`)
- **Retry/backoff**: 3 retries with exponential backoff on 429/5xx
- **SGML extraction**: `extract_primary_10k_document()` strips exhibits from raw `.txt` SGML
- **Format detection**: XBRL-HTML, standard HTML, and plain text
- **No silent fallback**: Specific accession → error if not found (never fallback to latest)

### ✅ NVIDIA Default (progress_notes item 2.10)
- `.env`: `DEFAULT_MODEL=moonshotai/kimi-k2.6`
- `src/config.py`: Default changed to `moonshotai/kimi-k2.6`
- LLM refiner defaults to `deepseek-ai/deepseek-v4-pro` (NVIDIA) for cost efficiency
- Model registry includes: `kimi-k2.6`, `glm-5.1`, `deepseek-v4-pro`, `minimax-m2.7`

---

## Gaps Fixed in This Session

| Gap | Fix | Files |
|---|---|---|
| `.env` DEFAULT_MODEL was OpenRouter | Changed to `moonshotai/kimi-k2.6` (NVIDIA) | `.env`, `.env.example`, `config.py`, `schemas.py` |
| `notes/_briefs/` not gitignored | Uncommented in `.gitignore` | `.gitignore` |
| `datetime.utcnow()` deprecation | Changed to `datetime.now(timezone.utc)` | `src/shared/schemas.py` |
| `detect_item_status()` ordering | Reserved checked before Not Applicable | `src/task3_sec/rule_parser.py` |

---

## Verification Results

### Tests: 61/61 Passed ✅
```
tests/test_api.py          10 passed
tests/test_shared.py        8 passed
tests/test_task3_sec.py    43 passed  (schemas: 5, normalizer: 9, rule_parser: 12, fetcher: 6, validator: 6, integration: 5)
─────────────────────────────
Total:                     61 passed in 1.02s
```

### Lint: All Checks Passed ✅
```bash
ruff check src/ tests/ evals/task3/run_eval.py → All checks passed!
```

### Server Startup: Clean ✅
```
INFO: Started server process
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8080
```

### Live Smoke Test (Apple 2023 10-K, previous session)
- CIK: `0000320193`, Accession: `0000320193-23-000106`
- Items detected: 23 (including sub-items 1A, 1B, 1C, 7A, 9A, 9B, 9C)
- Status: 11 extracted, 7 incorporated_by_reference, 5 not_applicable
- Validation: overall valid
- LLM calls: 0 (rule-only), Cost: $0.00
- Latency: ~973ms (after download)

---

## Remaining Items (Phase 4 Polish)
1. Full eval set run with stable network → commit `evals/task3/results/` report
2. `templates/task3.html` UI (API is working, UI is placeholder)
3. LLM reflexive validation prompt (`v2_reflexive_validate.txt`) integration test with real LLM call
