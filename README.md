# Signal-Foundry

> Evaluation-first AI systems: harness engineering for CI/CD Skills, browser automation, and SEC 10-K extraction.

[![Tests](https://img.shields.io/badge/tests-offline%20%2B%20opt--in%20live-22c55e)](tests/) [![Tasks](https://img.shields.io/badge/tasks-3%20complete-3b82f6)](#) [![Python](https://img.shields.io/badge/python-3.11%2B-blue)](requirements.txt) [![Deploy](https://img.shields.io/badge/deploy-Zeabur-9333ea)](https://signal-foundry.zeabur.app)

**Live demo:** [`https://signal-foundry.zeabur.app`](https://signal-foundry.zeabur.app) (Zeabur, 2 vCPU / 4 GB / 50 GB SSD dedicated)

> Routes: `/` dashboard, `/task1` CI/CD Skills, `/task2` Browser Agent, `/task3` SEC 10-K. JSON APIs under `/api/v1/{skills,browser,sec}/*`. Health at `/health`, live cost ledger at `/metrics`.
> Browser visits to `/health`, `/metrics`, and `/api/v1/models` render user-friendly HTML dashboards; API clients still receive JSON.

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
pytest tests/ -v

# Live LLM integration tests (opt-in, hits real NVIDIA + OpenRouter)
RUN_LLM_INTEGRATION=1 pytest tests/test_llm_integration.py -v   # 5 pass

# Live eval regression tests (opt-in, hits real websites / SEC EDGAR)
RUN_LIVE_EVALS=1 pytest tests/test_live_evals.py -v

# Run evals (each writes JSON + Markdown report to evals/<task>/results/)
python -m evals.task1.run_eval                # 5 cases, ~30s, ~$0.007
python -m evals.task3.run_eval --skip-xbrl    # 35 SEC filings, ~$0 rule path
python -m evals.task3.run_eval --allow-llm --vision --force-llm --timeout 300
python -m evals.task2.run_eval --vision --timeout 120   # 38-case set, Playwright + LLM
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

**Bring-your-own-key (BYOK) on the homepage.** The model selector accepts THREE optional keys:

- **OpenRouter** (`sk-or-v1-...`) — required if you pick `gpt-5.5`, `claude-opus-4.7`, or `gemini-3.1-pro-preview`. Pay-per-call, faster, higher quality. Top up at [openrouter.ai/credits](https://openrouter.ai/credits).
- **NVIDIA NIM** (`nvapi-...`) — free signup at [build.nvidia.com](https://build.nvidia.com). Required if you pick `kimi-k2.6`, `glm-5.1`, `deepseek-v4-pro`, or `minimax-m2.7`. Rate-limited to ~4 calls/min on the free tier; the server's bundled NVIDIA key may rotate / expire, in which case BYOK keeps you working.
- **LangSmith** (`lsv2_...`, optional) — paste your own LangSmith API key from [smith.langchain.com/settings](https://smith.langchain.com/settings) to send your runs' traces to your own console instead of the server's project.

You must paste at least ONE of the OpenRouter or NVIDIA keys — without it, the dropdown can't reach the corresponding provider and the request will fail with a clear `invalid_key` error message. All keys are kept in your browser session only (`sessionStorage`), never persisted server-side.

**Live progress for slow Task 2 runs.** Browser-agent tasks can take 30-180 s per case (planning → executing → verifying). The Task 2 UI calls `/api/v1/browser/stream` (Server-Sent Events), so users see milestones in real time:
```
[10:42:15] 🧭 planning task with google/gemini-3.1-pro-preview
[10:42:18] ✅ plan ready — 4 step(s)
[10:42:18] ▶️ step 1: navigate → Wikipedia
[10:42:21] ✓ step 1 conf:0.95
[10:42:21] ▶️ step 2: fill → main search input
...
[10:42:45] 🏁 success in 4 step(s) — $0.0042
```
No more spinner-and-wait — every step / healer activation / confidence score is visible.

**Errors that explain themselves.** A 4xx/429/500 from the LLM provider is classified into one of `invalid_key | rate_limit | insufficient_credit | quota_exhausted | timeout | no_response | server_error` and surfaced in the UI with an actionable suggestion ("top up at openrouter.ai/credits", "rotate key on console", "wait 30 s and retry"). Users don't have to dig through stack traces.

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
| `/api/v1/sec/extract` (Task 3, TSMC 20-F 2026) | 200 OK | 23 items, foreign-issuer form gracefully handled (12 extracted from 20-F's different schema) |
| `/api/v1/sec/extract` (Task 3, Tesla 10-K/A 2025 amendment) | 200 OK | 6 items extracted (amendments are partial), 17 marked not_found honestly |

---

## API Reference (for users)

All examples use the live deployment at `https://signal-foundry.zeabur.app`. Replace with `http://localhost:8080` for local testing. JSON requests; responses are also JSON. The user's own NVIDIA / OpenRouter API key can be passed in the `model` block per-request — never stored server-side.

### POST `/api/v1/skills/run` — Task 1: CI/CD Skill against a real GitHub repo

Request body:
```json
{
  "repo_url": "https://github.com/tychen5/Medical-Summary-Builder",
  "branch": "main",
  "skill_name": "lint-and-test",
  "dry_run": true,
  "model": {
    "model_id": "moonshotai/kimi-k2.6",
    "user_openrouter_key": null
  }
}
```
- `skill_name`: one of `lint-and-test`, `dependency-audit`, `security-scan`, `build-and-release`
- `dry_run`: required `true` for `build-and-release` unless user explicitly opts in
- `model.model_id`: any model from `/api/v1/models`
- `model.user_openrouter_key`: optional — supply your own key for OpenRouter models (server uses its own key for NVIDIA models)

Response (success):
```json
{
  "status": "success",
  "task": "task1_cicd",
  "trace_id": "ad32a07b-a9a",
  "result": {
    "status": "warnings",
    "language": "python",
    "lint_tool": "ruff",
    "lint_passed": false,
    "lint_issues": [{"file": "...", "line": 3, "code": "F401", "message": "..."}],
    "tests_passed": null,
    "summary": "Ruff linting found 7 unused imports..."
  },
  "match_confidence": 1.0,
  "skill_executed": "lint-and-test",
  "cost_metadata": {"cost_usd": 0.001, "tokens_in": 800, "tokens_out": 200},
  "latency_ms": 846.4
}
```

### POST `/api/v1/browser/execute` — Task 2: Natural-language browser task

Request body:
```json
{
  "task_description": "Go to https://arxiv.org/abs/2509.13753 and report the paper's title and the first two authors",
  "target_url": "https://arxiv.org/abs/2509.13753",
  "max_steps": 10,
  "use_vision": true,
  "model": {
    "model_id": "google/gemini-3.1-pro-preview",
    "user_openrouter_key": "sk-or-v1-..."
  }
}
```

Response (success):
```json
{
  "status": "success",
  "task": "task2_browser",
  "trace_id": "...",
  "result": {
    "status": "success",
    "task_description": "...",
    "final_answer": "Title: ST-LINK ... Authors: Hyotaek Jeon, Hyunwook Lee",
    "total_steps": 4,
    "self_corrections": 0,
    "healer_activations": 0,
    "failure_modes": [],
    "cost_usd": 0.0041,
    "steps": [{"step_number": 1, "action": {...}, "verification": {...}}, ...]
  }
}
```

`status` field meaning:
- `success` — task complete with grounded answer
- `partial` — agent ran out of steps; last URL + best-effort answer returned
- `not_found` — silent-failure guard fired: page is 404 / login wall / paywall / CAPTCHA OR LLM hedged. Honest "couldn't" report rather than hallucination
- `unverified` — answer fields contain numbers that don't appear on observed pages (likely hallucination)
- `failed` — uncaught exception (rare; system catches most error classes)

`use_vision=true` attaches bounded viewport JPEG history to the actor and verifier, but only for the three OpenRouter vision-language models (`google/gemini-3.1-pro-preview`, `anthropic/claude-opus-4.7`, `openai/gpt-5.5`). NVIDIA models accept the flag and fall back to text-only AOM context.

### POST `/api/v1/sec/extract` — Task 3: SEC 10-K item-level extraction

Request body (CIK + accession):
```json
{
  "cik": "0000320193",
  "accession_number": "0000320193-23-000106",
  "skip_llm": false,
  "skip_xbrl": false,
  "force_llm": false,
  "use_vision": false,
  "model": {
    "model_id": "moonshotai/kimi-k2.6"
  }
}
```

Or directly by URL:
```json
{
  "filing_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
}
```

`use_vision=true` is only consulted if Stage 2 LLM boundary refinement actually runs. High-confidence modern HTML filings stay rule-only, so the flag has no cost or quality effect on the normal path. For user demos that need to visibly compare text-only vs multimodal boundary refinement, set `force_llm=true` with an OpenRouter vision model.

Response (success):
```json
{
  "status": "success",
  "task": "task3_sec",
  "trace_id": "...",
  "result": {
    "filing_metadata": {
      "cik": "0000320193",
      "company_name": "Apple Inc.",
      "accession_number": "0000320193-23-000106",
      "filing_date": "2023-11-03",
      "form_type": "10-K",
      "filing_url": "..."
    },
    "items": [
      {
        "part": "I",
        "item_number": "1",
        "item_title": "Business",
        "content_text": "Company Background...",
        "char_range": [0, 45985],
        "status": "extracted",
        "confidence": 0.95,
        "extraction_method": "rule_based"
      },
      ...
    ],
    "processing_metadata": {
      "total_tokens_in": 0,
      "total_tokens_out": 0,
      "total_cost_usd": 0.0,
      "total_latency_ms": 537,
      "rule_only_items": 23,
      "llm_refined_items": 0,
      "stages_used": ["rule_based", "validation", "xbrl_cross_check"],
      "validation_report": {"overall_valid": true, "issues": []},
      "xbrl_report": {"status": "completed", "checks": [...]}
    }
  }
}
```

`status` per item:
- `extracted` — item content found and present
- `incorporated_by_reference` — item refers to another doc (Proxy / DEF 14A)
- `not_applicable` — item explicitly marked as N/A
- `reserved` — SEC marked the item as Reserved
- `not_found` — item not present in the filing (may be legitimate, e.g. 1C didn't exist before 2023)

### Useful aux endpoints

- `GET /api/v1/sec/filings/{cik}?filing_type=10-K&limit=10` — list a company's recent 10-Ks (find accession numbers)
- `GET /api/v1/sec/company/{cik}` — company metadata: name, ticker, exchange, SIC code
- `GET /api/v1/skills/list` — list available CI/CD skills + trigger phrases
- `GET /api/v1/models` — model registry
- `GET /metrics` — live cost/latency/token ledger
- `GET /health` — readiness check

### Authentication notes

- **NVIDIA models** (default): server uses its own NVIDIA API key. Free tier has rate limits (~4 calls/min/model).
- **OpenRouter models** (paid): if you DON'T supply `user_openrouter_key`, the server uses its own key (limited budget, may exhaust). For sustained / heavy use, pass your own key in the `model` block — never stored, only used for that request.

---

## Harness Engineering Highlights

The thing that separates this repo from a one-shot prototype:

- **Unified LLM provider via OpenAI-compat backend.** Both NVIDIA NIM and OpenRouter expose OpenAI-style `/v1/chat/completions` endpoints. `src/llm_provider.py` defaults to `ChatOpenAI` pointed at each provider's base URL — uniform code path, sidesteps `langchain-nvidia-ai-endpoints`'s "Multiple candidates" assertion on dual-listed models, sidesteps the silent `max_tokens` vs `max_completion_tokens` kwarg drop. Per-model `extra_body` (NIM thinking-mode toggles for DeepSeek V4 Pro, GLM 5.1) lives in `MODEL_REGISTRY`. `LLM_BACKEND=langchain_native` switches back to the dedicated wrappers if you need them.
- **Cost ledger as a first-class API.** Every chat call routes through `src/shared/cost_tracker.py` with `(task, operation, trace_id)`. The `/metrics` endpoint exposes per-task / per-skill cost and latency live. Cost discipline isn't a goal — it's an instrument.
- **Chat-content coercion** (`src.shared.llm_utils.coerce_message_text`) flattens `.content` whether it's a string, a `[{"type":"text","text":...}]` block list (newer thinking-mode returns), or `None`. Used in every Task 1/2/3 LLM call site. The previous bug — `summary[:200]` raising `KeyError: slice(...)` because the LLM returned a dict-shaped block list — was caught the moment we exercised the live path and is now permanently locked out by tests.
- **Pre-merge order in skill engine.** Engine fields (`summary`, `match_confidence`) merge *after* `**raw_result` so they always win — prevents skill-level fields with conflicting names (e.g. `SecurityScanResult.severity_counts` previously named `summary`) from silently overwriting LLM-generated text.
- **Three-tier skill matching** (Task 1) and **selective LLM** (Task 3) both default to *zero LLM cost* on the typical request and only escalate when deterministic signals are insufficient. Cost rises monotonically with input difficulty, not with traffic.

### Harness Guards (added in latest iterations)

- **SSE streaming for Task 2** (`/api/v1/browser/stream`). The agent emits milestone events through an `asyncio.Queue` (`phase_start` → `phase_done` → `step_start`/`step_done` per action with healer flag, confidence, and error → `agent_complete`). Reverse-proxy heartbeat every 20 s prevents Caddy / Zeabur from dropping the connection on long runs. Frontend uses `fetch + ReadableStream` (not `EventSource`) so we can POST the request body in one shot. Without this, the UI was hanging silently on multi-minute browser tasks.
- **LLM error classifier** (`src/shared/llm_errors.py`). Maps the raw provider exception (regex over the message string + HTTP code) to one of: `invalid_key`, `rate_limit`, `insufficient_credit`, `quota_exhausted`, `timeout`, `no_response`, `server_error`. Each ships with a `suggested_action` string ("top up at openrouter.ai/credits", "rotate key on console", "wait 30 s and retry"). All 3 task routers populate `ExecutionResult.cost_metadata` with the classified payload; the SSE stream emits an `error` event with the same shape; the UI shows a colour-coded banner so users see the cause + the fix, not a 500.
- **URL-based blocked-page detection** (`src/task2_browser/agent._BLOCKED_URL_MARKERS`). Deterministic check: if the agent's last URL contains `/authwall`, `/login?`, `accounts.google.com/signin`, `/cf-chl`, `/captcha`, `/access-denied`, `edgar/error`, etc., the silent-failure guard flips status to `not_found` *regardless* of what the LLM said. The redirect itself is the evidence. Fires for both `success` and `partial` states.
- **Idempotency cache + token redaction** (Task 1). Cache key is `cicd:v1:{owner}/{repo}:{branch}:{skill}:{sha[:12]}:{dry_run}`. HEAD SHA is fetched via the GitHub REST API *before* clone, so cache hits skip the entire clone+subprocess pipeline. The clone URL has the token redacted (`https://x-access-token:***@github.com/...`) in every log line. Subprocess env strips `GITHUB_TOKEN`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY` so child processes can't exfiltrate.
- **Selective vision** (Task 2 + Task 3). `use_vision=true` is opt-in. `is_vision_capable()` checks the model id against a registry (gemini-3.1-pro / claude-opus-4.7 / gpt-5.5); for the 4 NVIDIA NIM text-only models the toggle silently degrades to AOM-only — no `image_url` payload sent, no 4xx surfaced. Task 2 keeps a bounded screenshot history (3 frames) so the LLM sees what *changed* between actions; Task 3 renders 3 zoom levels per uncertain boundary (header zone + local context + neighbour context) with a yellow `<mark>` highlight at the candidate position.
- **Rate-limit circuit-break** (Task 3 LLM refiner). Inter-call delay (`LLM_REFINER_DELAY_S`, default 1.5 s) paces NVIDIA NIM's free-tier ~4 calls/min. After 3 consecutive 429s the refiner abandons further refinement rather than hammering the rate-limit window into next-month's quota. Vision rendering capped at `T3_VISION_MAX` (default 5) per filing — each render adds ~1.5 s, beyond which the latency dominates.
- **`@traced` LangSmith decorators** (`src/shared/tracing.py`). Decorate the 3 task entry points; metadata-tag each span with model_name / trace_id / repo / cik / task_description for filterable runs in the LangSmith UI. No-op when env vars absent — zero cost for users without a LangSmith account.
- **Honest status taxonomy.** Task 2 returns `success | partial | not_found | unverified | failed`. Each has a precise meaning: `not_found` is the *correct* outcome on a login wall, paywall, captcha, or page that genuinely doesn't contain the answer. The eval scorer treats `not_found` on a negative-test case (example.com hallucination guard) as a pass.
- **Stuck-loop guard** (`src/task2_browser/agent._detect_stuck_loop`). The reactive loop now detects when the planner picks the *same action* (action_type + target_description) AND the URL doesn't change for 3 consecutive steps — typical pattern when a Submit button silently fails or a captcha-locked field resets. The guard breaks out as `partial` with a `stuck_loop` failure mode rather than burning through `max_steps` repeating the same mistake. Healed retries with different selectors and redirect cycles correctly do *not* trip it.
- **Per-request budget cap** (`src/shared/cost_tracker.BudgetExceededError`). Spec calls out "$0.50 per filing"; the tracker now enforces it. After Stage 2 in T3 (the only paid stage), the pipeline calls `check_request_budget(trace_id, cap, task)`. On overrun: emits a `budget_cap_hit` SSE event, marks the stage in `stages_used`, and skips remaining LLM stages. Default caps: $0.30 (T1), $0.50 (T2 / T3); set `max_cost_usd=0` on the request to disable for benchmarks.
- **NVIDIA-key contextvar plumbing** (`src/llm_provider.set_user_keys`). The router calls `set_user_keys(openrouter=..., nvidia=...)` once per request; the contextvar isolates concurrent requests via `asyncio` task scope. `get_llm()` falls back to the contextvar when its explicit `user_*_key` arg is absent — this lets the 7+ downstream agent / healer / planner / refiner call sites keep their existing single-key signature while still routing user-supplied NVIDIA keys correctly.
- **Multilingual hedge-phrase guard.** The `_NOT_FOUND_PHRASES` list now includes traditional + simplified Chinese (`需要登入` / `需要登录`, `維護中` / `维护中`, `頁面沒有`), Japanese (`ログインが必要`, `メンテナンス中`), and Cloudflare interstitial English ("just a moment", "checking your browser"). Real silent failures across CJK locales now flip to `not_found` rather than passing through as `success`.
- **Word-boundary verifier parsing.** Previous prose-fallback used substring matching ("complete" in lowered_response), which let *"The task is incomplete"* register as positive. Replaced with `\bincomplete\b | not\s+complete | task\s+is\s+complete` regex — JSON path still preferred, but the prose fallback no longer flips honest negatives to silent successes.

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

### Task 3 — latest eval sweep: 35/35 pass (100%); $0 rule-only cost

Source: [`evals/task3/results/task3_eval_20260508T092259Z.md`](evals/task3/results/task3_eval_20260508T092259Z.md)

| Metric | Value |
|--------|-------|
| Cases in eval set | **35** |
| Success rate | **100.0%** |
| Avg latency | 1 568 ms |
| Total cost | **$0.00** (rule-only path across all 35 cases) |
| Avg confidence | 0.890 |
| LLM triggered | 0 cases (selective LLM fires only when confidence < 0.55 or items_found < 10) |
| Prompt version | v4 boundary-refine (edge-case hardening: combined items, SPAC N/A, early ASCII, going-concern guard) |

| Coverage slice | Representative filings | What it tests |
|---|---|---|
| Modern mega-cap 10-K | Apple 2023, Microsoft 2023, JPMorgan 2025, Exxon 2023, Tesla 2023, Nvidia 2024 | Standard inline-XBRL HTML, optional-item policy |
| Small / mid-cap | Small company 2024, Rivian 2023 first-year EV, Coinbase 2024 crypto, GameStop meme-era | Size variation, new-industry formats |
| Industry spread | Pfizer 2023, Boeing 2024, AT&T 2023, Wells Fargo 2023, Realty Income REIT, Ares Capital BDC | Healthcare, aerospace, banking, telecom, REIT, BDC |
| Conglomerate / unusual structure | Berkshire 2024, GE 2023, Ford 2023 large filing | Multi-segment complexity, unusual heading formats |
| Older / legacy formats | Apple 2005 (pre-cybersecurity rule), AmEx 1994 (plain-text EDGAR), Costco 2016 10-K/A | Pre-HTML normalization, legacy ASCII format, amendment behavior |
| Pre-bankruptcy / financial crisis | Enron Corp FY2000, WorldCom FY2001, Lehman Brothers FY2007 | Early-2000s HTML structure, dense financial disclosures |
| Post-bankruptcy / going concern | Hertz 2025, Sears 2017 (going-concern language) | v4 prompt guards against going-concern → not_applicable false positive |
| Amendments (10-K/A) | Tesla 2025 amendment, Costco 2016 amendment | Partial filings: only amended items present |
| Foreign private issuers (20-F) | TSMC 2026, Toyota 2025, Kingsoft Cloud 2022, Red Metal 2025 | Different item schema, duplicate/reserved headings |
| Special entity types | Asset-Backed Trust 2011 (mass N/A), IBM 2025 proxy-heavy | SPV N/A classification, Part III incorporation by reference |

The fetcher fix in this iteration: `find_10k_filing` no longer raises `ValueError` before checking older submissions pages — enabling older companies (e.g. Lehman, Enron, WorldCom) whose 10-K filings pre-date the 1 000-filing recent window. The LLM refiner now also runs `_detect_missing_items` when `items_found < 10` even if all found boundaries are high-confidence (prevents silent gap-skip on old plain-text filings).

**LLM + vision is always available as a fallback** (`--allow-llm --vision --force-llm` flags or API `force_llm=true`). The vision benchmark (`evals/run_vision_benchmark.py`) uses `--force-llm-task3` to render ±500-char text snippets as 3-tier JPEG snapshots (header zone / local context / neighbour context) and compare LLM accuracy with and without visual layout context.

### Task 2 — Live eval (3 runs across 3 different models)

**Run A** — `moonshotai/kimi-k2.6` (NVIDIA NIM, free tier):
- 5/17 genuine success, 11/17 graceful 429 degradation, 0 crashes, $0.064 total
- Validates that the system does the right thing under a degraded API: returns `status=unverified` with explicit failure-mode reason instead of fabricating an answer

**Run B** — `anthropic/claude-opus-4.7` (OpenRouter, paid):
- 8/17 **genuine success**, 5/17 partial (max-step cap reached), 4/17 unverified (silent-failure guard activated correctly), 0 crashes
- Avg latency 136 s, total cost $3.06, 0.76 self-corrections per case

**Run C** — `google/gemini-3.1-pro-preview` (after v2-prompt + URL-marker + healer-recovery improvements, 21-case eval set):
- **13/21 genuine success (62%)**, 7/21 not_found (correct anti-hallucination), 1/21 partial, 0 crashes
- Avg latency 52 s (down from 136 s in run B), total cost **$0.175 (-94%)**, 0.81 self-corrections per case
- Iteration cycle wins:
  - `t2_table_extraction` (Wikipedia GDP table): SUCCESS in 4 steps (run B was partial / max-steps)
  - `t2_yahoo_finance_aapl_options`: SUCCESS in 8 steps (run B was partial)
  - `t2_twse_company_lookup` (台積電 2330): SUCCESS in 8 steps (run B was partial)
  - `t2_stackoverflow_question`: SUCCESS in 6 steps (previously max-stepped locally)
  - `t2_cnyes_taiex_quote`: SUCCESS — live TAIEX numbers extracted from cnyes
  - `t2_anuse_silent_failure_guard`: NOT_FOUND in 3 steps with NO hallucination — validates the spec's highest-priority requirement
  - `t2_pypi_search`, `t2_cookie_banner_news` (Reuters), `t2_sec_edgar_lookup`: correctly NOT_FOUND when blocked by anti-bot / login

Reports committed to `evals/task2/results/`.

**Latest expanded sweep** — `google/gemini-3.1-pro-preview`, 30-case live run:
- **20/30 genuine success (66%)**, 9/30 correct `not_found`, 1/30 partial, 0 crashes
- Avg latency 45.0 s, total cost **$0.2186**, avg self-corrections 0.57
- Source: [`evals/task2/results/task2_eval_20260507T023943Z.md`](evals/task2/results/task2_eval_20260507T023943Z.md)

**What the silent-failure / 429 behavior demonstrates:** The 9-class root cause taxonomy (`v2_healer.txt` extends to 13 classes adding `rate_limit_429`, `login_wall`, `paywall`, `frame_detached`) and the post-hoc `_guard_against_silent_success` numeric grounding check converge to the same outcome — when the agent cannot prove an answer is real, it does NOT mark the task complete. This is the spec's highest-priority requirement.

**Mitigation**: `run_eval.py` now supports `--delay N` (default 5 s) to pace requests within NVIDIA NIM's free-tier rate limit. For higher-quality runs, pass `--model anthropic/claude-opus-4.7` (OpenRouter) — the live UI lets users paste their own key.

### Task 2 — eval set covers 38 real-world cases across 5 difficulty dimensions

Source: `evals/task2/eval_set.json`. Live results: `evals/task2/results/` (after running `python -m evals.task2.run_eval`). The latest committed live sweep covers 30 cases; the current set adds 8 vision-focused cases for OpenRouter `use_vision` comparison. Budget: roughly $0.25-$0.45 for a Gemini sweep, higher for Claude/GPT.

**Eval design rationale** — four orthogonal difficulty axes:

| Axis | What it stress-tests | Example cases |
|------|----------------------|---------------|
| Domain diversity | Generalisation across sites the agent hasn't seen | Wikipedia, Google/Bing, Hacker News, GitHub, PyPI, Reuters, SEC EDGAR, MDN |
| Task complexity | Single-step vs multi-step vs table extraction | Title extraction (easy) → Tokyo vs NYC population comparison (multi-step) → GDP table (structured) |
| Failure injection | Graceful handling of non-success | 404 page → must report error content, NOT invent content |
| Real-world finance (highest value) | Finance-domain knowledge + Chinese UI + live data | wantgoo.com TX support/resistance, TWSE/MOPS, cnyes 加權指數, Yahoo TW 2330, Yahoo AAPL options |
| Visual / layout-heavy | When AOM text is insufficient | TradingView chart canvas, Wikipedia image caption, Nobel table layout, color indicators, D3 SVG, OpenStreetMap tiles, CAPTCHA iframe |

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
- `t2_vision_chart_trend` — TradingView canvas chart, intended to show the difference between AOM-only and `use_vision=true`
- `t2_vision_image_caption` / `t2_vision_table_layout` — layout/image/table cases where vision should improve confidence even if text-only can sometimes answer
- `t2_vision_map_location` / `t2_vision_d3_chart` / `t2_vision_captcha_detect` — map tiles, SVG chart perception, and honest CAPTCHA limitation reporting

### OpenRouter vision on/off benchmark

The three OpenRouter models that support image input are `google/gemini-3.1-pro-preview`, `anthropic/claude-opus-4.7`, and `openai/gpt-5.5`. The repo now has a dedicated live runner for the requested differential benchmark:

```bash
python -m evals.run_vision_benchmark --task both --force-llm-task3 --timeout 180
```

Default benchmark slice:

| Task | Cases | Vision should help with |
|---|---|---|
| Task 2 | TradingView chart trend, Wikipedia image caption, Nobel table layout | Canvas/image/table cues that are weak or absent in AOM text |
| Task 3 | Apple 2005 legacy, TSMC 20-F, IBM proxy-heavy | Typography/layout around uncertain SEC item boundaries; `--force-llm-task3` makes Stage 2 fire for controlled vision on/off comparison |

Committed Task 2 live slice: [`evals/vision_results/vision_benchmark_20260507T072543Z.md`](evals/vision_results/vision_benchmark_20260507T072543Z.md). This is a compact 1-case-per-task slice, not the full 3-case default sweep. Status/step/cost metrics are automatic; answer quality should still be manually spot-checked from the JSON preview for visual extraction cases.

| Task | Model | Vision off | Vision on | Delta |
|---|---|---:|---:|---|
| Task 2 Mona Lisa image caption | Gemini 3.1 Pro | success, 3 steps, $0.003805, 21.8 s | success, 3 steps, $0.003800, 21.1 s | No material difference; text/AOM already sufficient |
| Task 2 Mona Lisa image caption | Claude Opus 4.7 | partial, 15 steps, $0.782115, 118.9 s | success, 3 steps, $0.048690, 27.5 s | Vision prevented a costly max-step loop |
| Task 2 Mona Lisa image caption | GPT-5.5 | success, 5 steps, $0.067510, 93.4 s | success, 4 steps, $0.035255, 49.8 s | Vision roughly halved cost and latency |
| Task 3 Apple 2005 legacy filing | Gemini / Claude / GPT | 18/23 items, $0, 0 LLM calls | 18/23 items, $0, 0 LLM calls | No effect because Stage 2 did not fire; rule parser confidence was high |

Committed forced Task 3 slice: [`evals/vision_results/vision_benchmark_20260507T084355Z.md`](evals/vision_results/vision_benchmark_20260507T084355Z.md). Run command: `T3_FORCE_LLM_MAX=1 python -m evals.run_vision_benchmark --task task3 --task3-cases t3_apple_2023 --force-llm-task3 --timeout 240`.

| Task 3 Apple 2023 forced Stage 2 | Vision off | Vision on | Delta |
|---|---:|---:|---|
| Gemini 3.1 Pro | 23/23 items, 1 call, $0.002044, 83.4 s | 23/23 items, 1 call, $0.002059, 29.7 s | Vision cut latency by ~64%; cost unchanged |
| Claude Opus 4.7 | 23/23 items, 1 call, $0.024240, 5.8 s | 23/23 items, 1 call, $0.025365, 10.7 s | Vision adds small cost/latency; both correct |
| GPT-5.5 | 23/23 items, 1 call, $0.008155, 112.4 s | 23/23 items, 1 call, $0.008275, 42.3 s | Vision cut latency by ~62%; cost unchanged |

Interpretation: Task 2 is where vision clearly pays off when visual context prevents loops. Task 3 preserves cost discipline by default, and the forced benchmark proves the multimodal Stage 2 path is live. A regression surfaced during the forced run: one model tried to rename a known Item 7 boundary. The harness now locks the original item number during boundary refinement and only lets the LLM adjust offset/title/status/confidence.

### Vision engineering decisions

| Area | Implementation | Benefit |
|---|---|---|
| Task 2 screenshot history | `use_vision=true` sends a bounded chronological screenshot history to actor + verifier; visual/sparse-AOM pages use capped full-page screenshots | The model can see state changes, modals, maps/charts, and visual-only data instead of relying only on AOM text |
| Task 2 focused callouts | `annotate_screenshot_with_markers()` can draw numbered bounding boxes for future element-level vision evals | Makes ambiguous UI targets auditable in screenshots without changing the LLM transport schema |
| Task 3 multi-snapshot context | Stage 2 can attach header-zone, local-context, and neighbor/comparison snapshots around each boundary | Helps distinguish real item headings from ToC/prose mentions and classify `incorporated_by_reference`, `not_applicable`, and `reserved` statuses |
| Cost guard | Task 3 vision only renders for vision-capable OpenRouter models and is capped by `T3_VISION_MAX`; forced benchmarks are capped by `T3_FORCE_LLM_MAX` | User demos can show multimodal gains without accidentally turning every filing into a high-cost full-LLM extraction |

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
| Earliest EDGAR / plain-text filings | Rare | SEC says EDGAR data starts in 1994/1995, so true pre-1994 electronic filings are generally not available; early complete-submission text can be exhibit-heavy | Eval set includes American Express 1994 complete submission; LLM boundary refinement + vision snapshots can be forced for benchmark comparison |
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
| XBRL cross-validation crashed with `argument of type 'int' is not iterable` because SEC's `fy` field is an int | Stage 4 of the pipeline silently failed for every Task 3 case (caught and logged; the rule-based result was returned without XBRL verification) | `str(e.get("fy", ""))` coerces to string before substring check | Now all 4 stages of Task 3 fire, including financial-number cross-validation against the official XBRL Company Facts API |
| Zeabur Python builder didn't include `git` binary at runtime → `git clone` fails with exit 127 | Task 1 returned `sandbox_error: "Command not found: git"` for every live request after the first deploy | Two-pronged fix: (1) Dockerfile + zbpack.json install git system package; (2) `_clone_via_api_tarball` GitHub-API fallback that downloads the repo as a tarball and extracts in pure Python — works even when git isn't installed | Defense in depth: even if Zeabur's image rebuild ever drops git again, the API path keeps Task 1 working |
| Task 3 LLM refiner's default model was `deepseek-v4-pro` thinking-mode, which takes 200+ s per call. With ~15 boundaries to refine in a typical filing, that's a 50-minute runaway | First call took 245 s on Microsoft 2023; eval would never complete | Switched default to `kimi-k2.6` (~3 s); added inter-call rate-limit delay (`LLM_REFINER_DELAY_S`, default 1.5 s) + circuit-break after 3 consecutive 429s. Tightened the LLM-fire-trigger so most modern filings stay rule-only ($0) | The pipeline now correctly trades off quality vs latency — thinking-mode is opt-in, not default |
| Task 1 demo button for `encode/httpx` returned `GitHub API error 422` because skill_engine ignored `repo_info["default_branch"]` and always used `request.branch="main"`; httpx defaults to `master` | Tarball API returned 422 for nonexistent ref; user demos failed | Honour `repo_info["default_branch"]` when caller left `branch` at the schema default; allows different repos to seamlessly use their own default branches | Real-world: many older OSS projects still use `master` |
| Task 3 demo buttons (`Microsoft FY2023`, `Abbott Labs`) used hand-typed accession strings that don't exist on SEC | All demo clicks returned `404 Not Found` for `https://www.sec.gov/Archives/edgar/data/.../...txt` | Pulled real accessions from `data.sec.gov/submissions/CIK*.json` and pinned them in `templates/task3.html` | The lesson — never hand-type SEC accessions; always look them up |
| `find_10k_filing` raised `ValueError: No 10-K / 20-F filings found for CIK X` *before* checking older submission pages | Lehman, Enron, WorldCom (whose 10-Ks pre-date the 1 000-filing recent window) failed unrecoverably | Defer the empty-list raise until after `_find_in_additional_submission_files` and `resolve_filing_from_archive` fallbacks have both been tried | Pre-bankruptcy filings are now reachable end-to-end |
| LLM refiner's `_detect_missing_items` was silently skipped when all found boundaries had high confidence — even when `items_found < 10` | Old-format filings (Enron 2000, WorldCom 2001) detected only 3 items, all at conf=0.95, so the LLM never fired to fill the gaps | Keep iterating into the missing-item detector when `items_found < 10` regardless of per-boundary confidence; the trigger condition was already in `pipeline.py` but the refiner returned too early | Trigger now properly cascades into Stage 2 detection logic |
| LangSmith `trace_url(trace_id)` constructed `https://smith.langchain.com/o/projects/p/{name}` URLs that always 404'd because LangSmith requires UUID org-id + project-id, not project name | "View in LangSmith" button pointed at a permanent 404 page | Made `trace_url` return None unconditionally; UI hides the button and instead shows a copy-able trace_id chip — accurate, and users can paste it into LangSmith search themselves | Honest behaviour beats a broken-link footgun |

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
| browser execute + vision | N/A | Provider-dependent | Adds bounded JPEG history to OpenRouter VLM calls; measure with `evals.run_vision_benchmark` |
| SEC extraction (modern HTML) | **$0** rule-only | ~$0.01 | 1–2 s rule path; LLM only for low-confidence boundaries |
| SEC extraction (legacy / messy) | $0 attempt | $0.02–0.05 | 5–30 s |
| SEC boundary refine + vision | N/A | Provider-dependent | Only when Stage 2 fires; no effect on high-confidence rule-only filings |

Per-task cost / latency / token counts are exposed live at `/metrics`.

---

## Latest Trace-Driven UX & Harness Tweaks

This pass traced the FastAPI routes, UI templates, schemas, eval artifacts, and README against the user flow. Changes made:

| Area | Tweak | Why it matters for demo/review |
|---|---|---|
| System pages | `/health`, `/metrics`, `/api/v1/models` now render HTML dashboards for browser navigation while preserving JSON for API clients | Users can inspect readiness, spend, and model routing without reading raw JSON |
| Dashboard | Added a user launchpad and shared in-session model/API-key controls | Faster video flow across Task 1/2/3 pages |
| Task 2 UI | Fixed execution trace rendering from `[object Object]` to action + target + verification confidence; examples now prefill target URLs | Makes the PEOH loop visually auditable instead of hiding the agent's decisions |
| Task 2 harness | Result metadata records `model_name`, `use_vision_requested`, and `use_vision_active`; v3 actor/verifier prompts consume multi-screenshot history | Makes OpenRouter vision experiments reproducible and shows whether vision really activated |
| Task 2 tests | Playwright-heavy screenshot helpers run under `asyncio.wait_for`; opt-in live eval test executes a real BrowserAgent case | Confirms screenshot code paths do not hang and eval tests are not just render smoke |
| Task 3 UI | Direct filing URL now sends `filing_url` (schema-correct), added `use_vision` + `force_llm` toggles, stage diagram, IBM/TSMC edge-case chips | Users can exercise URL-based filings, 20-F, proxy-heavy cases, and forced multimodal refinement directly |
| Task 3 evals | Added early EDGAR plain text, SPV not-applicable, duplicate-heading 20-F, and small-cap reserved-item cases | Expands LLM/vision-trigger candidates beyond clean rule-only modern 10-Ks |
| Docs/evals | README updated from old 17/8-case claims to current 38-case Task 2 set and 27-case Task 3 set | Prevents stale documentation from understating the work |

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
├── tests/                   # Offline tests + opt-in live LLM/eval tests
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
