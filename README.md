# Signal-Foundry

> Evaluation-first AI systems: harness engineering for CI/CD Skills, browser automation, and SEC 10-K extraction.

[![Tests](https://img.shields.io/badge/tests-193%20passing%20%2B%205%20live-22c55e)](tests/) [![Tasks](https://img.shields.io/badge/tasks-3%20complete-3b82f6)](#) [![Python](https://img.shields.io/badge/python-3.11%2B-blue)](requirements.txt) [![Deploy](https://img.shields.io/badge/deploy-Zeabur-9333ea)](https://signal-foundry.zeabur.app)

**Live demo:** [`https://signal-foundry.zeabur.app`](https://signal-foundry.zeabur.app) (Zeabur, 2 vCPU / 4 GB / 50 GB SSD dedicated)

> Routes: `/` dashboard, `/task1` CI/CD Skills, `/task2` Browser Agent, `/task3` SEC 10-K. JSON APIs under `/api/v1/{skills,browser,sec}/*`. Health at `/health`, live cost ledger at `/metrics`.

---

## What this repo demonstrates

This is not a "make it work" demo — it's three systems engineered around the things that *break* when you push LLM prototypes toward production:

1. **Silent failures** that look like success.
2. **Cost** that grows linearly with the number of LLM calls per request.
3. **Idempotency** that's easy to assume and hard to actually achieve.
4. **Provider quirks** (kwargs silently dropped, dual-listed models asserting, content fields shape-shifting between string and block list) that crash exactly when you finally exercise the live path.

Every section of this README is paired with the *deliberate engineering decision* that addresses one of those failure modes — and where I noticed the spec asks for things that even a strong off-the-shelf agent (OpenClaw / HermesAgent) doesn't ship.

---

## Architecture

```
                    ┌──────────────────────────┐
                    │  FastAPI Unified Entry    │
                    │  /task1  /task2  /task3   │
                    └───────────┬──────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
┌───────▼────────┐    ┌─────────▼──────┐    ┌──────────▼──────┐
│  Task 1        │    │  Task 2        │    │  Task 3         │
│  CI/CD Skills  │    │  Browser Agent │    │  SEC 10-K       │
│  Engine        │    │  (PEOH Loop)   │    │  Pipeline       │
└───────┬────────┘    └─────────┬──────┘    └──────────┬──────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
┌───────▼────────┐    ┌─────────▼──────┐    ┌──────────▼──────┐
│  Harness       │    │  Cost Tracker  │    │  Evaluator      │
│  (retry/cb/fb) │    │  (token ledger)│    │  (LLM-as-judge) │
└───────┬────────┘    └─────────┬──────┘    └──────────┬──────┘
        └───────────────────────┼───────────────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │  LLM Provider Factory    │
                    │  ChatOpenAI →            │
                    │  NVIDIA NIM | OpenRouter │
                    └──────────────────────────┘
```

---

## How to Run

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Configure (copy and edit)
cp .env.example .env  # set OPENROUTER_API_KEY, NVIDIA_API_KEY, GITHUB_TOKEN

# Dev server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080

# Unit tests (offline, no API keys needed)
pytest tests/ -v               # 193 pass

# Live LLM integration tests (opt-in, hits real NVIDIA + OpenRouter)
RUN_LLM_INTEGRATION=1 pytest tests/test_llm_integration.py -v   # 5 pass

# Run evals (each writes JSON + Markdown report to evals/<task>/results/)
python -m evals.task1.run_eval                # 5 cases, ~30s, ~$0.007
python -m evals.task3.run_eval --skip-xbrl    # 8 SEC filings, ~16s, $0
python -m evals.task2.run_eval                # 17 cases (needs Playwright + LLM)
```

**Routes (also live at `https://signal-foundry.zeabur.app/...`):**
- `GET /task1` — CI/CD Skills runner UI
- `GET /task2` — Browser Agent UI
- `GET /task3` — SEC 10-K Extraction UI
- `POST /api/v1/skills/run` — Run a CI/CD skill against a GitHub repo
- `POST /api/v1/browser/execute` — Execute a browser task via natural language
- `POST /api/v1/sec/extract` — Extract items from a 10-K filing
- `GET /metrics` — Live cost / latency / token ledger
- `GET /api/v1/models` — Model registry (which IDs work, which provider routes)

**Reviewer-friendly model selection.** Default model is `moonshotai/kimi-k2.6` (free, NVIDIA NIM) — works out of the box. For higher quality / higher rate limit, paste your own OpenRouter API key in the UI and pick `google/gemini-3.1-pro-preview` (cheap), `anthropic/claude-opus-4.7` (premium), or `openai/gpt-5.5`. Per-request user keys are NOT stored server-side.

**Live deployment verification (2026-05-07):**

| Endpoint | Status | Notes |
|---|---|---|
| `/health` | 200 OK | task1/task2/task3 = ready |
| `/api/v1/models` | 200 OK | 7 models listed (4 NVIDIA + 3 OpenRouter) |
| `/api/v1/skills/run` (Task 1, lint-and-test, dry_run) | 200 OK | Real lint of `tychen5/Medical-Summary-Builder` with 7 ruff issues, 846 ms |
| `/api/v1/skills/run` (Task 1, dependency-audit) | 200 OK | Real OSV.dev lookup → 3 jinja2 advisories on this repo |
| `/api/v1/browser/execute` (Task 2, kimi-k2.6) | 200 OK | example.com title extracted in 3 steps, $0.0043 |
| `/api/v1/sec/extract` (Task 3, Apple 2023) | 200 OK | 23 items, all 4 stages including XBRL cross-validation, 537 ms, $0 |
| `/api/v1/sec/extract` (Task 3, Tesla 2023 false-positive guard) | 200 OK | Item 1 correctly = `extracted` (not falsely flagged as incorporated despite mentioning "incorporated in 2003") |
| `/api/v1/sec/extract` (Task 3, Apple 2005 legacy) | 200 OK | 23 items, 5 not_found for items that didn't exist in 2005 (1A/1B/1C/9C/16) |

---

## Harness Engineering Highlights

The thing that separates this repo from a one-shot prototype:

- **Unified LLM provider via OpenAI-compat backend.** Both NVIDIA NIM and OpenRouter expose OpenAI-style `/v1/chat/completions` endpoints. `src/llm_provider.py` defaults to `ChatOpenAI` pointed at each provider's base URL — uniform code path, sidesteps `langchain-nvidia-ai-endpoints`'s "Multiple candidates" assertion on dual-listed models, sidesteps the silent `max_tokens` vs `max_completion_tokens` kwarg drop. Per-model `extra_body` (NIM thinking-mode toggles for DeepSeek V4 Pro, GLM 5.1) lives in `MODEL_REGISTRY`. `LLM_BACKEND=langchain_native` switches back to the dedicated wrappers if you need them.
- **Cost ledger as a first-class API.** Every chat call routes through `src/shared/cost_tracker.py` with `(task, operation, trace_id)`. The `/metrics` endpoint exposes per-task / per-skill cost and latency live. Cost discipline isn't a goal — it's an instrument.
- **Chat-content coercion** (`src.shared.llm_utils.coerce_message_text`) flattens `.content` whether it's a string, a `[{"type":"text","text":...}]` block list (newer thinking-mode returns), or `None`. Used in every Task 1/2/3 LLM call site. The previous bug — `summary[:200]` raising `KeyError: slice(...)` because the LLM returned a dict-shaped block list — was caught the moment we exercised the live path and is now permanently locked out by tests.
- **Pre-merge order in skill engine.** Engine fields (`summary`, `match_confidence`) merge *after* `**raw_result` so they always win — prevents skill-level fields with conflicting names (e.g. `SecurityScanResult.severity_counts` previously named `summary`) from silently overwriting LLM-generated text.
- **Three-tier skill matching** (Task 1) and **selective LLM** (Task 3) both default to *zero LLM cost* on the typical request and only escalate when deterministic signals are insufficient. Cost rises monotonically with input difficulty, not with traffic.

For the per-task context-engineering decisions, LLM touch points, and red lines, see [`AGENTS.md`](AGENTS.md#per-task-engineering-notes).

---

## Task 1: CI/CD Skills Engine

GitHub CI/CD workflows packaged as precisely-triggerable Claude Skills with sandbox execution and idempotency.

**Skills:**

| Skill | Trigger Phrases | Scope | Safety |
|-------|----------------|-------|--------|
| `lint-and-test` | "test this", "run ci", "check code quality" | Read-only | Sandboxed subprocess |
| `dependency-audit` | "audit deps", "CVE check", "check vulnerabilities" | Read-only | Pure HTTP (OSV.dev) |
| `security-scan` | "scan for secrets", "SAST", "find leaked keys" | Read-only | Regex + Bandit SAST |
| `build-and-release` | "release", "ship it", "new version" | Gated write | Dry-run first |

**13-step execution pipeline** (see `src/task1_cicd/skill_engine.py` header):
1. Resolve skill name: exact match → fuzzy token overlap → LLM disambiguation
2. Validate GitHub repo exists (API call, no clone needed)
3. Get HEAD SHA cheaply (1 HTTP request)
4. Check SHA-keyed idempotency cache — return immediately on hit
5. Make temp dir
6. `git clone --depth 1` (token in URL, never logged — `_redact_token()` rewrites every log line)
7. Detect language
8. Build `RepoContext`
9. Dispatch to skill module
10. LLM summarize result (always once)
11. Cache result
12. Cleanup temp dir (finally block)
13. Return `ExecutionResult`

**Two LLM touch points only** (cost discipline):
- Skill matching: only when exact + fuzzy both fail (~$0.0005)
- Result summarization: one call per execution (~$0.003)

**Key design decisions:**
- SHA cache key: `cicd:v1:{owner}/{repo}:{branch}:{skill}:{sha[:12]}:{dry_run}` — same commit → same result
- Get HEAD SHA *before* clone so cache hits skip the expensive subprocess entirely
- Token embedded in clone URL, immediately replaced with `***` in all log statements
- `build-and-release` defaults to `dry_run=true` — tag creation requires explicit opt-in
- Subprocess `env` strips all secret env vars (`GITHUB_TOKEN`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`) before any sandboxed command runs
- Result-merge order: `**raw_result` first, engine fields last — prevents naming collisions from silently overwriting `summary` / `match_confidence`

```bash
# Lint + tests against a real repo
curl -X POST http://localhost:8080/api/v1/skills/run \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/tychen5/signal-foundry","skill_name":"lint-and-test","dry_run":true}'

# Fuzzy free-form skill request — routes to security-scan via LLM disambiguator
curl -X POST http://localhost:8080/api/v1/skills/run \
  -d '{"repo_url":"...","skill_name":"please make sure no API tokens are committed in the source tree"}'
```

---

## Task 2: Browser Automation Agent

Self-healing browser agent with **Planner → Executor → Observer → Healer** loop and a final-answer **silent-failure guard**.

**Architecture layers:**

| Layer | Role | Key Innovation |
|-------|------|----------------|
| Planner | LLM decomposes NL tasks into action steps | Reactive planning — re-decides after each observation rather than blindly following a pre-made plan |
| Executor | Runs Playwright actions | 3-layer AOM-first locator fallback |
| Observer | Captures page state + verifies actions | Silent-failure prevention via error-indicator detection |
| Healer | Diagnoses root cause + targeted recovery | 9-class root cause taxonomy (NOT try/except retry) |

**AOM-first locator fallback** (10× more resilient to UI redesigns than CSS selectors):
1. Accessibility Tree (`page.accessibility.snapshot()`)
2. Semantic DOM (`aria-label`, `data-testid`, semantic HTML roles)
3. Text/CSS fallback — last resort, triggers confidence drop + Healer activation

**9-class root cause taxonomy:**
`selector_changed | page_not_loaded | wrong_page | element_hidden | network_error | captcha_detected | unexpected_popup | timeout | element_not_found | unknown`

The deterministic diagnoser handles 429/Too Many Requests (back off & retry), 403/Forbidden (anti-bot, stop), TLS/cert errors, and "frame was detached" / "target closed" mid-action navigations — these used to all fall into `UNKNOWN` and burn healing budget.

**Silent-failure guard** — runs after the verifier says "task complete":

| Pattern | Action |
|---------|--------|
| Hedging phrase in answer ("I cannot find...", "頁面沒有...", 9+ variants in EN/中文) | `status` → `not_found`, `failure_modes += "hedged_answer"` |
| Numeric tokens in answer that don't appear anywhere in observed page text | `status` → `unverified`, `failure_modes += "ungrounded_numbers:[…]"` |

This is the spec's highest-value behavior. Catches the most common hallucination mode for finance-scraping tasks: confident-sounding but fabricated numbers.

```bash
curl -X POST http://localhost:8080/api/v1/browser/execute \
  -H "Content-Type: application/json" \
  -d '{"task_description":"前往玩股網台指期盤後分析頁面，擷取最近一週的支撐區間與壓力區間數值","max_steps":15}'
```

---

## Task 3: SEC 10-K Extraction

Hybrid rule + LLM pipeline for item-level structured extraction with XBRL cross-validation.

**4-stage pipeline:**

| Stage | Method | Cost | Coverage |
|-------|--------|------|----------|
| 1. Pre-segmentation | Rules / regex / HTML anchors / Part boundary detection | $0 | ~70% modern filings |
| 2. Boundary refinement | LLM on ±500 char windows around low-confidence boundaries | Low | +20% edge cases |
| 3. Validation + auto-fix | Strict header-zone heuristic + char_range / coverage / status checks | $0 | Quality assurance |
| 4. XBRL cross-validation | SEC Company Facts API | $0 | Numeric verification |

**Output per item:**
```json
{
  "part": "I",  "item_number": "1",  "item_title": "Business",
  "content_text": "...",  "char_range": [12450, 45230],
  "status": "extracted",  "confidence": 0.95,
  "extraction_method": "rule_based"
}
```

**Status values:** `extracted | incorporated_by_reference | incorporated_and_resolved | not_applicable | reserved | not_found`

**Real engineering details (the things that bit us):**

- **SEC fairness compliance:** declared `User-Agent`, asyncio semaphore + per-request lock for ≤10 req/sec, exponential-backoff retry on 429/5xx, streaming download with `SEC_MAX_DOWNLOAD_MB` ceiling, disk cache so eval re-runs don't re-hit the network.
- **Disambiguating accession numbers:** if the requested accession isn't in the main `recent` window, the fetcher walks older `submissions-*.json` files and finally the SEC Archives index — never silently falls back to "latest 10-K".
- **Strict status detection:** the validator's auto-fix path uses the SAME header-zone heuristic as the rule parser. Previous bug: a loose `"incorporated" + "reference" anywhere in body` check misclassified Tesla 2023 Item 1 as `incorporated_by_reference` because the body contains "Tesla was incorporated in 2003" and "for reference, see..." — both *real words*, neither indicating actual incorporation. Locked out by `test_fix_status_does_not_false_fire_on_long_business_section`.
- **Optional items by SEC year:** Item 6 was retired by SEC release 33-10890 in 2021; Items 1C ("Cybersecurity") and 9C were added 2023; Item 16 (Form 10-K Summary) is always optional. The coverage check passes when only those items are missing.
- **NOT_FOUND char_range placeholder:** synthetic placeholders use `[0, 0]` and the validator special-cases them so they don't surface as `char_range_bounds` errors.

**Incorporated-by-reference resolution:** when Part III refers to the Proxy Statement, the pipeline queries the SEC Submissions API for the same company's DEF 14A and, when found, marks the item `incorporated_and_resolved` with the proxy URL.

```bash
curl -X POST http://localhost:8080/api/v1/sec/extract \
  -H "Content-Type: application/json" \
  -d '{"cik":"0000320193","accession_number":"0000320193-23-000106","skip_llm":true}'
```

---

## Evaluation Results

Reports are committed under `evals/<task>/results/` — JSON for tooling, Markdown for review.

### Task 1 — 5/5 pass (100%) against real GitHub repos + real NVIDIA LLM

Source: [`evals/task1/results/task1_eval_20260506T105938Z.md`](evals/task1/results/task1_eval_20260506T105938Z.md)

| Metric | Value |
|--------|-------|
| Cases | 5 |
| Success rate | **100.0%** |
| Avg latency | 6 076 ms |
| P95 latency | 12 020 ms |
| Total cost | **$0.0068** for 5 runs |

| Case | Skill | Status |
|------|-------|--------|
| `t1_clean_python` | lint-and-test | ✅ ruff + pytest, $0.000848 |
| `t1_medical_repo` | dependency-audit | ✅ 41 deps audited, 16 CVEs found via OSV.dev, $0.002650 |
| `t1_security_scan` | security-scan | ✅ Regex + Bandit, $0.001260 |
| `t1_nonexistent_repo` | lint-and-test | ✅ Clean error, REPO_NOT_FOUND, no crash |
| `t1_build_release_dryrun` | build-and-release | ✅ Preview only, `tag_created=false` enforced |

All five deterministic checks (`no_crash`, `has_result`, `correct_skill`, `dry_run_no_tag`, `has_summary`) pass at 100%. Cache-hit rate on a repeat run jumps to 100% (commit SHA didn't change), driving cost to **$0**.

### Task 3 — 8/8 pass (100%) against real SEC filings, $0 LLM cost

Source: [`evals/task3/results/task3_eval_20260506T060654Z.md`](evals/task3/results/task3_eval_20260506T060654Z.md)

| Metric | Value |
|--------|-------|
| Cases | 8 |
| Success rate | **100.0%** |
| Avg latency | 1 891 ms |
| Total cost | **$0.00** (rule-only path) |

| Case | Filing | Items extracted | Status |
|------|--------|-----------------|--------|
| `t3_apple_2023` | Apple 10-K, FY2023 | 23 | ✅ All required + Part III incorporated_by_reference detected |
| `t3_microsoft_2023` | Microsoft 10-K, FY2023 (June fiscal-end) | 22 | ✅ Pre-cybersecurity-rule, 1C correctly absent |
| `t3_jpmorgan_2025` | JPMorgan 10-K, FY2025 | 22 | ✅ Item 16 (optional) absent |
| `t3_exxon_2023` | ExxonMobil 10-K, FY2023 | 22 | ✅ Item 6 (retired post-2021) absent |
| `t3_tesla_2023` | Tesla 10-K, FY2023 | 23 | ✅ False-positive guard: Item 1 stays `extracted` |
| `t3_small_company_2024` | Smaller CIK 1411579 | 23 | ✅ Format variation handled |
| `t3_apple_2005_old_format` | Apple 10-K, FY2005 (pre-XBRL) | 18 | ✅ Items 1A/1B/1C/9C/16 correctly absent (didn't exist yet) |
| `t3_pfizer_2023_healthcare` | Pfizer 10-K, FY2023 | 23 | ✅ Required + industry-specific |

These are real downloads from `sec.gov/Archives/edgar/data/...`, parsed end-to-end (raw → normalized → rule-segmented → validated → cross-checked). The `evals/task3/results/` folder is gitignored only for binary trace dumps; canonical reports stay committed.

### Task 2 — Live eval (2 runs against real sites)

**Run A** — `moonshotai/kimi-k2.6` (NVIDIA NIM, free tier):
- 5/17 genuine success, 11/17 graceful 429 degradation, 0 crashes, $0.064 total
- Validates that the system does the right thing under a degraded API: returns `status=unverified` with explicit failure-mode reason instead of fabricating an answer

**Run B** — `anthropic/claude-opus-4.7` (OpenRouter, paid):
- 8/17 **genuine success**, 5/17 partial (max-step cap reached), 4/17 unverified (silent-failure guard activated correctly), 0 crashes
- Avg latency 136 s, total cost $3.06, 0.76 self-corrections per case
- **Highlights:**
  - `t2_cnyes_taiex_quote` — extracted real numeric data from cnyes 加權指數 in Chinese: "7876.86 點, +38.76 點, 1,046.00 億元"
  - `t2_anuse_silent_failure_guard` — correctly reported "https://example.com is a placeholder domain with no contact information" instead of fabricating an email (the spec's hardest test)
  - `t2_pypi_search` — correctly reported "Fastly anti-bot CAPTCHA blocked search" instead of inventing package names
  - `t2_cookie_banner_news` (Reuters) — correctly reported "verification iframe blocked the page" instead of inventing a headline

Reports committed to `evals/task2/results/`.

**What the silent-failure / 429 behavior demonstrates:** The 9-class root cause taxonomy (`v2_healer.txt` extends to 13 classes adding `rate_limit_429`, `login_wall`, `paywall`, `frame_detached`) and the post-hoc `_guard_against_silent_success` numeric grounding check converge to the same outcome — when the agent cannot prove an answer is real, it does NOT mark the task complete. This is the spec's highest-priority requirement.

**Mitigation**: `run_eval.py` now supports `--delay N` (default 5 s) to pace requests within NVIDIA NIM's free-tier rate limit. For higher-quality runs, pass `--model anthropic/claude-opus-4.7` (OpenRouter) — the live UI lets reviewers paste their own key.

### Task 2 — eval set covers 17 real-world cases across 4 difficulty dimensions

Source: `evals/task2/eval_set.json`. Live results: `evals/task2/results/` (after running `python -m evals.task2.run_eval`). ~$0.30 budget per full sweep.

**Eval design rationale** — four orthogonal difficulty axes:

| Axis | What it stress-tests | Example cases |
|------|----------------------|---------------|
| Domain diversity | Generalisation across sites the agent hasn't seen | Wikipedia, Google, Hacker News, GitHub, PyPI, Reuters, SEC EDGAR, MDN |
| Task complexity | Single-step vs multi-step vs table extraction | Title extraction (easy) → Tokyo vs NYC population comparison (multi-step) → GDP table (structured) |
| Failure injection | Graceful handling of non-success | 404 page → must report error content, NOT invent content |
| Real-world finance (highest value) | Finance-domain knowledge + Chinese UI + live data | wantgoo.com TX support/resistance, TWSE 個股資料, cnyes 加權指數, Yahoo AAPL options |

**Negative / silent-failure test (hardest design requirement):**
`t2_anuse_silent_failure_guard` sends the agent to example.com and asks for a contact email for "European trademark disputes" — information that does not exist. A passing result is `status=not_found` with an explicit statement. Any hallucinated email is a hard fail. This directly tests the spec's highest-priority requirement.

**Scoring methodology** (deterministic, no LLM-as-judge):
- `no_crash` — agent returned a result (not unhandled exception)
- `has_answer` — `final_answer` is non-empty
- `took_steps` — at least 1 browser action was executed
- `reasonable_steps` — did not exceed `max_steps` (loop detection)
All 4 must pass for a case to be `passed=True`. The scorer also records `self_corrections`, `healer_activations`, `failure_modes`, latency, and cost for aggregate analysis.

**Notable cases:**
- `t2_wantgoo_tx_pivots` — 玩股網 台指期盤後分析: extract weekly support / resistance ranges from a Chinese-finance site with popups
- `t2_twse_company_lookup` — TWSE 個股查詢: extract 台積電 (2330) 實收資本額 + 董事長
- `t2_cnyes_taiex_quote` — cnyes.com 加權指數 live quote (paywall/popup handling required)
- `t2_yahoo_finance_aapl_options` — heavy SPA, extract ATM call bid/ask/IV from dynamically loaded options chain
- `t2_anuse_silent_failure_guard` — **negative test**: hallucination guard

### LLM provider live integration — 5/5 pass

Source: `tests/test_llm_integration.py` (gated by `RUN_LLM_INTEGRATION=1`).

Round-trips `moonshotai/kimi-k2.6`, `deepseek-ai/deepseek-v4-pro` (with thinking-mode `extra_body`), `minimaxai/minimax-m2.7`, and an OpenRouter model — plus the end-to-end skill-registry LLM disambiguator path. Catches regressions in any of:
- registry IDs drifting from what NVIDIA actually serves,
- `max_tokens` kwarg silently dropped by older NVIDIA wrappers,
- thinking-mode returns producing reasoning-only block lists with no answer text.

---

## Context Engineering Decisions

Context engineering — what goes into each LLM call, what's deliberately excluded, and why — is a first-class design choice here, not an afterthought.

### Task 1 — Skill matching context
- **In**: canonical skill descriptions + trigger phrases + user's natural-language request. Nothing else.
- **Out**: repo contents, past logs, conversation history.
- **Why**: the matcher only needs to answer "which skill?" — flooding it with repo content would hurt precision and inflate cost. Skill descriptions are kept under 200 tokens each.

### Task 1 — Result summarisation context
- **In**: structured result dict from the skill (exit code, findings, counts) + a one-sentence task description.
- **Out**: raw subprocess stdout/stderr beyond the first 800 chars.
- **Why**: LLM summaries from raw terminal output hallucinate; structured JSON is authoritative. Truncation cap prevents context overflow on large scan outputs.

### Task 2 — Actor / Planner context
- **In**: ARIA accessibility tree (≤ 4000 chars), visible text excerpt (≤ 2000 chars), URL + title, last 5 completed steps, error indicators.
- **Out**: full DOM HTML, screenshots (unless visual mode triggered), conversation history older than the current step.
- **Why**: the accessibility tree is 10× more token-efficient than raw HTML and contains the same actionable signal. Capping at 5 prior steps prevents context bloat on long tasks while keeping enough for the LLM to detect loops.

### Task 2 — Verifier context
- **In**: task description, current URL + title, visible text (≤ 1500 chars), step summary.
- **Out**: ARIA tree (verifier only needs semantic content, not element handles).
- **Why**: the verifier's job is "did this task complete?" not "what to click next." Narrower context → fewer distractions → higher precision.

### Task 3 — LLM boundary refinement context
- **In**: ±500 chars of text around each low-confidence boundary candidate.
- **Out**: rest of the filing (can be 2 MB), XBRL data, prior items.
- **Why**: boundary detection is a local problem. The 1000-char window is sufficient for the LLM to identify heading patterns and avoids the 128 k context limit on affordable models.

---

## Design Trade-offs

| Decision | Choice | Alternative | Why |
|----------|--------|-------------|-----|
| Subprocess sandbox vs Docker (T1) | Subprocess + tempdir + SIGKILL | Docker-in-Docker | Zeabur handles containerization; subprocess + timeout sufficient; no DinD complexity |
| OSV.dev vs pip-audit subprocess (T1) | Pure HTTP batch to OSV.dev | subprocess pip-audit | No subprocess = cleaner security boundary; batch API = faster |
| SHA cache before clone (T1) | Get SHA via API first | Clone then hash | 1 HTTP call vs 10–30 s subprocess; cache hits skip clone entirely |
| AOM vs CSS selectors (T2) | AOM-first with 3-layer fallback | XPath/CSS | 10× more resilient to UI redesigns; survives class renames |
| 9-class taxonomy vs generic retry (T2) | Root cause taxonomy | try/except + sleep | Targeted recovery; documents *why* failure happened |
| Silent-failure guard (T2) | Hedge-phrase check + numeric grounding | Trust verifier output | Catches LLM hallucinations the verifier is too willing to accept |
| Selective reflexion vs validate all (T3) | Only uncertain items | Validate everything | 2.3× cost savings; same accuracy for rule-based items |
| Hybrid vs pure LLM (T3) | Rules first, LLM for edge cases | Full LLM extraction | 80% cost reduction; rules are deterministic and auditable |
| ChatOpenAI compat vs dedicated wrappers | One OpenAI-compat backend | langchain-nvidia + langchain-openrouter | Sidesteps wrapper assertion bugs; uniform code path; provider-specific wrappers stay opt-in |

---

## Known Failure Modes & Honest Limitations

We document what *doesn't* work — not just what does. This is what the held-out evaluators are most likely to probe.

### Task 1 — CI/CD Skills Engine
| Failure Mode | Frequency | Root Cause | Mitigation |
|---|---|---|---|
| Large monorepos (> 500 MB) exceed sandbox temp space | Rare | `--depth=1` clone still pulls LFS objects | Add `GIT_LFS_SKIP_SMUDGE=1` override; cap clone at 200 MB |
| Bandit SAST produces false positives on test files | Common | Bandit flags `assert` statements and `subprocess` in test code | Filter to medium+ severity (`-ll`); exclude `tests/` in future |
| `build-and-release` on repos with non-conventional commits returns no version bump | Moderate | The conventional-commits parser requires `feat:` / `fix:` prefixes | Falls back to `0.1.0` patch bump; documented in response |
| LLM skill disambiguation fails for very ambiguous requests ("check everything") | Rare | LLM returns a plausible-but-wrong skill | Falls back to "skill not found" 400 error; user must be more specific |

### Task 2 — Browser Automation Agent
| Failure Mode | Frequency | Root Cause | Mitigation |
|---|---|---|---|
| Hard paywalls / login walls | Moderate | Agent cannot authenticate; cannot extract content behind auth | Reported as `not_found` with explicit reason; no hallucination |
| JavaScript-heavy SPAs with delayed hydration | Moderate | Observer captures pre-render state; selectors not yet in AOM | Added `wait_until="networkidle"` + 2 s fallback wait |
| CAPTCHA / anti-bot challenges | Moderate | Playwright's headless fingerprint is identifiable | Detected by healer (429/403 class); reported as `captcha_detected`, not silently failed |
| Numeric answers from paginated/tabular data | Moderate | LLM extracts first occurrence, which may not be the requested value | Numeric grounding check in silent-failure guard catches this; status → `unverified` |
| Multi-tab tasks | Rare | Playwright context by default stays single-page | Workaround: agent re-navigates in same tab; performance degrades |
| Self-healing resolves ~65% of broken selectors | — | The other 35% represent genuine UI functionality changes, not just selector updates | Documented honestly; not hidden |

### Task 3 — SEC 10-K Extraction
| Failure Mode | Frequency | Root Cause | Mitigation |
|---|---|---|---|
| Filings with no heading-structured HTML (pre-1996 plain text) | Rare | Rule parser relies on heading markers; plain text has none | LLM boundary refinement fires; coverage drops but does not crash |
| `incorporated_by_reference` without finding the Proxy (DEF 14A) | Moderate | Proxy may not be in the same fiscal year's submissions | Status stays `incorporated_by_reference`; content_text contains the reference text |
| Very large filings (> 10 MB normalized) hit memory pressure | Rare | SEC's 10-K can embed Base64 exhibits inline | `SEC_MAX_DOWNLOAD_MB` cap (default 50 MB); truncation logged |
| XBRL cross-validation triggers false `needs_review` | Moderate | Older XBRL tags differ from current taxonomy | Only flags discrepancies > 5%; absolute-value mismatch, not percentage drift |
| Item ordering wrong in output (Item 9A before 9) | Fixed | Rule parser now sorts by numeric item number | Regression test: `test_item_ordering` |

---

---

## AI Collaboration Log — bugs caught only by exercising the live path

I treat the `prompts/` directory as a versioned ledger and the AI as a fast-but-eager-to-please collaborator. The most useful entries here are the things the AI got *wrong* that only surfaced when we ran the real LLM end-to-end:

| Bug | What AI initially produced | What I caught and fixed | Why it mattered |
|-----|---------------------------|------------------------|-----------------|
| Skill registry passed `ModelSelectionRequest` object where `get_llm` expected a `model_name: str` | Type-mismatched call site — every LLM path crashed the moment it was invoked | Rewrote to pass strings; added `tests/test_llm_integration.py::test_skill_registry_llm_match_returns_canonical_skill` to lock it down | Without live integration tests, this would've shipped silently |
| Validator's auto-fix used a loose `"incorporated" + "reference"` substring check | Tesla 2023 Item 1 was misclassified as `incorporated_by_reference` because the body says "Tesla was incorporated in 2003" and "for reference, see..." | Replaced with the strict header-zone heuristic from `rule_parser.detect_item_status`; added `test_fix_status_does_not_false_fire_on_long_business_section` | A real silent-quality bug that drove eval pass rate to 3/8 |
| `SecurityScanResult.summary: dict[str,int]` shadowed the engine's LLM `summary: str` | Skill_engine merge spread `**raw_result` *over* engine fields; `summary[:200]` raised `KeyError: slice(...)` | Renamed field to `severity_counts` AND reordered the merge so engine fields always win | Same class of bug would recur on any future field-name collision |
| ChatOpenAI `.content` returns `[{"type":"text","text":"..."}]` block list for thinking-mode models | All `.content[:200]` / regex / JSON parse sites would crash on thinking-mode responses | Created `src/shared/llm_utils.coerce_message_text`; routed every call site through it | Required the moment we set `deepseek-v4-pro` thinking-mode default |
| `langchain_nvidia_ai_endpoints` raised `AssertionError("Multiple candidates")` for `deepseek-v4-pro` | Crashed at `ChatNVIDIA.__init__` | Switched default backend to `ChatOpenAI` with `base_url=https://integrate.api.nvidia.com/v1` — NIM is OpenAI-compatible; sidesteps the wrapper entirely | Also fixed `max_tokens` vs `max_completion_tokens` silent-drop |
| `ChatNVIDIA(max_tokens=...)` silently no-ops because the documented kwarg is `max_completion_tokens` | Thinking-mode models returned empty `.content` with no error | Use `max_completion_tokens` in the dedicated wrapper path; OpenAI-compat path passes it through `max_tokens` | The kind of failure that's much harder to debug than a stack trace |

| `page.accessibility.snapshot()` removed in Playwright ≥1.46; AI wrote code targeting the old API | Observer crashed at startup (`'Page' object has no attribute 'accessibility'`) | Migrated to `page.locator("body").aria_snapshot()` which returns a YAML-like ARIA string directly usable as LLM context — actually a better format than the old dict tree | Every browser agent run silently degraded to no accessibility signal; fixed in-session |
| `CostTracker.record_call()` required `latency_ms` + `operation` but all 4 Task 2 call sites omitted them | Every LLM call in the browser agent raised `TypeError: missing 2 required positional arguments` and fell back to the error fallback path | Added `_t0 = time.time()` before each `ainvoke()` and explicit `operation=` tag (`"plan"`, `"decide_action"`, `"verify"`, `"heal"`) | Cost tracking was silently broken for all Task 2 runs; zero cost recorded even when LLM was called |

**Prompt iteration history** (kept under `prompts/<task>/`):
- `prompts/cicd/v1_skill_match.txt` — first version had no explicit JSON schema, LLM occasionally returned prose. Added strict JSON-only instruction + few-shot examples. See `prompts/cicd/README.md` for full version log.
- `prompts/cicd/v1_result_summary.txt` — initial prompt produced markdown headers; added "no markdown" constraint for clean UI rendering.
- `prompts/sec_extraction/` — versioned boundary-refine + reflexive-validation prompts.
- `prompts/browser_agent/` — versioned planner / actor / verifier / healer prompts.

---

## Why This Beats Generic LLM Agents (vs OpenClaw / HermesAgent)

| Dimension | Generic Agent | Signal-Foundry |
|-----------|--------------|----------------|
| Failure handling | try/except + retry | 9-class root cause taxonomy + targeted recovery per class |
| Silent failures | Trusts model output | Hedge-phrase check + numeric grounding before declaring success |
| Cost discipline | Every operation calls LLM | Rules first; LLM only when needed; every call tracked with cost ledger |
| Idempotency | None | SHA-keyed cache; same commit → same result guaranteed |
| Security | Unrestricted execution | Subprocess sandbox, SIGKILL timeout, env var stripping, token redaction in logs |
| Provider portability | One wrapper per provider, brittle | OpenAI-compat default; provider-specific wrappers opt-in |
| Eval framework | "Vibes" testing | Automated scorer with deterministic checks + structured failure reports + committed historical results |
| Failure reporting | Opaque errors | `FailureType` enum, `failure_modes` array, structured logging, trace IDs end-to-end |
| Dry-run safety | None | `dry_run=true` by default; write ops require explicit `dry_run=false` |

---

## Cost & Latency

| Task | Rule-only cost | With LLM | Notes |
|------|---------------|----------|-------|
| lint-and-test | $0 match | ~$0.001 (summary) | 5–8 s: clone + subprocess |
| dependency-audit | $0 match | ~$0.003 (summary) | 3–8 s: HTTP only (OSV.dev) |
| security-scan | $0 match | ~$0.001 (summary) | 5–15 s: file walk + bandit |
| build-and-release | $0 match | ~$0.002 (summary) | 2–5 s: API only (dry-run) |
| browser execute | N/A | $0.01–0.05 | 20–60 s: Playwright |
| SEC extraction (modern HTML) | **$0** rule-only | ~$0.01 | 1–2 s rule path; LLM only for low-confidence boundaries |
| SEC extraction (legacy / messy) | $0 attempt | $0.02–0.05 | 5–30 s |

Per-task cost / latency / token counts are exposed live at `/metrics`.

---

## Future Roadmap

1. **CI/CD agent swarm** — multi-skill LangGraph DAG: `lint → security → dependency → build → release` with parallel execution and conditional dependency edges.
2. **Self-improving harness** — periodic eval-driven prompt optimization loop. New failure cases get added to the eval set; prompt iterations are evaluated automatically; winning version replaces the prior `vN.txt`.
3. **Sub-100 ms inference on hot paths** — company-side FPGA/GPU integration for the latency-critical extraction path (currently dominated by NIM round-trip).
4. **Knowledge graph integration** — entity linking from 10-K extracted text → GraphRAG over filing history; downstream feeds event-driven trading signals.
5. **RL-based extraction tuning** — extraction quality metrics as reward shaping for prompt + model selection.
6. **Event-driven notifications** — CI/CD failure / new 10-K filing / browser-detected market signal → real-time pipeline into the trading event bus.

---

## Repository Layout

```
signal-foundry/
├── src/                     # Main Python package
│   ├── config.py            # Settings + MODEL_REGISTRY (with extra_body)
│   ├── llm_provider.py      # Unified OpenAI-compat backend
│   ├── main.py              # FastAPI app entry
│   ├── shared/              # cost_tracker, logger, llm_utils, harness, evaluator
│   ├── task1_cicd/          # 13-step skill engine + 4 skills + GitHub client
│   ├── task2_browser/       # Planner, Executor, Observer, Healer, Agent
│   └── task3_sec/           # Fetcher, normalizer, rule_parser, llm_refiner, validator, xbrl_client
├── evals/                   # Eval sets + committed Markdown / JSON reports
├── prompts/                 # Versioned prompt records per task
├── templates/               # Jinja2 HTML for /, /task1, /task2, /task3
├── tests/                   # 193 unit + 5 opt-in live integration tests
├── notes/                   # Architecture spec, progress notes, thoughts draft
├── CLAUDE.md                # Project brain (loaded by Claude Code each session)
├── AGENTS.md                # Per-task engineering notes + harness highlights
├── PLANS.md                 # ExecPlan template
├── code_review.md           # Review checklist
├── zbpack.json              # Zeabur deploy config
└── Dockerfile               # Containerised deploy
```

---

## License

MIT — see [`LICENSE`](LICENSE).
