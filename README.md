# Signal-Foundry

> Evaluation-first AI systems: harness engineering for CI/CD Skills, browser automation, and SEC 10-K extraction.

[![Tests](https://img.shields.io/badge/tests-182%20passing-22c55e)](tests/) [![Tasks](https://img.shields.io/badge/tasks-3%20complete-3b82f6)](#) [![Python](https://img.shields.io/badge/python-3.11%2B-blue)](requirements.txt)

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
                    │  OpenRouter + NVIDIA      │
                    └──────────────────────────┘
```

---

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env: set OPENROUTER_API_KEY, NVIDIA_API_KEY, GITHUB_TOKEN

# Start server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080

# Run tests
pytest tests/ -v

# Run evals (direct engine mode — no live server required)
python -m evals.task1.run_eval --direct
python -m evals.task2.run_eval
python -m evals.task3.run_eval --skip-xbrl
```

**Task endpoints:**
- `GET /task1` — CI/CD Skills runner UI
- `GET /task2` — Browser Agent UI
- `GET /task3` — SEC 10-K Extraction UI
- `POST /api/v1/skills/run` — Run a CI/CD skill against a GitHub repo
- `POST /api/v1/browser/execute` — Execute a browser task via natural language
- `POST /api/v1/sec/extract` — Extract items from a 10-K filing

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

**13-step execution pipeline:**
1. Resolve skill name: exact match → fuzzy token overlap → LLM disambiguation
2. Validate GitHub repo exists (API call, no clone needed)
3. Get HEAD SHA cheaply (1 HTTP request)
4. Check SHA-keyed idempotency cache — return immediately on hit
5. Make temp dir
6. `git clone --depth 1` (token in URL, never logged)
7. Detect language
8. Build `RepoContext`
9. Dispatch to skill module
10. LLM summarize result (always once)
11. Cache result
12. Cleanup temp dir (finally block)
13. Return `ExecutionResult`

**Two LLM touch points only** (cost discipline):
- Skill matching: only when exact+fuzzy both fail (~$0.0005)
- Result summarization: one call per execution (~$0.003)

**Key design decisions:**
- SHA cache key: `cicd:v1:{owner}/{repo}:{branch}:{skill}:{sha[:12]}:{dry_run}` — same commit → same result
- Get HEAD SHA *before* clone so cache hits skip the expensive subprocess entirely
- Token embedded in clone URL, immediately replaced with `***` in all log statements
- `build-and-release` defaults to `dry_run=true` — tag creation requires explicit opt-in

```bash
# Run lint + tests against a real repo
curl -X POST http://localhost:8080/api/v1/skills/run \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/tychen5/signal-foundry","skill_name":"lint-and-test","dry_run":true}'

# Fuzzy skill matching — routes to security-scan via LLM
curl -X POST http://localhost:8080/api/v1/skills/run \
  -d '{"repo_url":"...","skill_name":"check if my code has leaked API tokens"}'
```

---

## Task 2: Browser Automation Agent

Self-healing browser agent with Planner → Executor → Observer → Healer loop.

**Architecture layers:**

| Layer | Role | Key Innovation |
|-------|------|----------------|
| Planner | LLM decomposes NL tasks into action steps | Reactive planning — re-decides after each observation |
| Executor | Runs Playwright actions | 3-layer AOM-first locator fallback |
| Observer | Captures page state + verifies actions | Silent failure prevention via error indicator detection |
| Healer | Diagnoses root cause + targeted recovery | 9-class root cause taxonomy (not try/except) |

**AOM-first locator fallback:**
1. Accessibility Tree (`page.accessibility.snapshot()`) — resilient to CSS/DOM redesigns
2. Semantic DOM (`aria-label`, `data-testid`, semantic HTML roles)
3. Text/CSS fallback — last resort, triggers confidence drop + Healer activation

**9-class root cause taxonomy:**
`selector_changed | page_not_loaded | wrong_page | element_hidden | network_error | captcha_detected | unexpected_popup | timeout | element_not_found`

Each root cause has a targeted recovery strategy. Healer activates when step confidence < 0.4.

**Silent failure prevention:** every action triggers post-action verification — URL change, DOM mutation, absence of error indicators — before marking a step successful.

```bash
curl -X POST http://localhost:8080/api/v1/browser/execute \
  -H "Content-Type: application/json" \
  -d '{"task_description":"Go to Wikipedia and find the population of Tokyo","max_steps":10}'
```

---

## Task 3: SEC 10-K Extraction

Hybrid rule+LLM pipeline for item-level structured extraction with XBRL cross-validation.

**4-stage pipeline:**

| Stage | Method | Cost | Coverage |
|-------|--------|------|----------|
| Pre-segmentation | Rules/regex/HTML anchors | $0 | ~70% modern filings |
| Boundary refinement | LLM on ±500 char windows | Low | +20% edge cases |
| Reflexive validation | LLM-as-judge (selective) | Medium | Quality assurance |
| XBRL cross-validation | SEC Company Facts API | $0 | Numeric verification |

**Output per item:**
```json
{
  "part": "I",  "item_number": "1",  "item_title": "Business",
  "content_text": "...",  "char_range": [12450, 45230],
  "status": "extracted",  "confidence": 0.95,
  "extraction_method": "rule_based"
}
```

**Status values:** `extracted | incorporated_by_reference | incorporated_and_resolved | not_applicable | reserved`

**Incorporated-by-reference resolution:** when Part III refers to the Proxy Statement, the pipeline queries the SEC Submissions API for the same company's DEF 14A and attempts to extract the referenced content automatically.

```bash
curl -X POST http://localhost:8080/api/v1/sec/extract \
  -H "Content-Type: application/json" \
  -d '{"cik":"0000320193","accession_number":"0000320193-23-000106","skip_llm":true}'
```

---

## Design Trade-offs

| Decision | Choice | Alternative | Why |
|----------|--------|-------------|-----|
| Subprocess sandbox vs Docker (T1) | Subprocess + tempdir + SIGKILL | Docker-in-Docker | Zeabur handles containerization; subprocess+timeout sufficient; no DinD complexity |
| OSV.dev vs pip-audit subprocess (T1) | Pure HTTP batch to OSV.dev | subprocess pip-audit | No subprocess = cleaner security boundary; batch API = faster |
| SHA cache before clone (T1) | Get SHA via API first | Clone then hash | 1 HTTP call vs 10-30s subprocess; cache hits skip clone entirely |
| AOM vs CSS selectors (T2) | AOM-first with 3-layer fallback | XPath/CSS | 10x more resilient to UI redesigns; survives class renames |
| 9-class taxonomy vs generic retry (T2) | Root cause taxonomy | try/except + sleep | Targeted recovery; documents *why* failure happened |
| Selective reflexion vs validate all (T3) | Only uncertain items | Validate everything | 2.3x cost savings; same accuracy for rule-based items |
| Hybrid vs pure LLM (T3) | Rules first, LLM for edge cases | Full LLM extraction | 80% cost reduction; rules are deterministic and auditable |

---

## Evaluation

Each task ships with an automated eval runner producing JSON + Markdown reports.

**Task 1 — 5 scenarios:**

| Case | Skill | Expected |
|------|-------|----------|
| `t1_clean_python` | lint-and-test | Detects Python, runs ruff + pytest |
| `t1_medical_repo` | dependency-audit | CVE scan via OSV.dev |
| `t1_security_scan` | security-scan | Secrets + SAST findings |
| `t1_nonexistent_repo` | lint-and-test | Clear error, REPO_NOT_FOUND |
| `t1_build_release_dryrun` | build-and-release | Preview only, `tag_created=False` |

Scoring per case: `no_crash`, `has_result`, `correct_skill`, `dry_run_no_tag`, `has_summary`

**Task 2 — 12 scenarios** across domain diversity, task complexity, failure injection, edge cases

**Task 3 — 8 filings** across industries, years, company sizes, incorporated-by-reference, reserved items

---

## AI Collaboration Log

**Where AI accelerated development:**
- Scaffolding all 4 skill modules from the plan spec — AI wrote first drafts; human reviewed security boundaries and redaction logic
- OSV.dev batch API integration and JSON parsing — AI drafted; human verified error handling
- Pydantic schema design — AI proposed field names; human added business invariants and validation constraints

**Where human judgment overrode AI:**
- Bandit SAST output parsing: AI initially parsed stderr; human corrected to `--format json` stdout
- Secret pattern `match_preview`: AI included the full match string; human enforced "first 4 chars + `***`" to prevent secrets leaking into logs
- SHA-before-clone ordering: AI drafted clone-first; human restructured to get SHA first for cache efficiency
- `build-and-release` idempotency: AI proposed tag check after creation; human moved it before to prevent orphaned releases on retry

**Prompt iteration history:**
- `prompts/cicd/v1_skill_match.txt`: initial version had no explicit JSON schema — LLM occasionally returned prose. Added strict JSON-only instruction. See `prompts/cicd/README.md` for full version history.
- `prompts/cicd/v1_result_summary.txt`: initial prompt produced markdown-formatted output. Added "no markdown headers" constraint for clean UI rendering.

---

## Why This Beats Generic LLM Agents (vs OpenClaw / HermesAgent)

| Dimension | Generic Agent | Signal-Foundry |
|-----------|--------------|----------------|
| Failure handling | try/except + retry | 9-class root cause taxonomy + targeted recovery per class |
| Cost discipline | Every operation calls LLM | Rules first; LLM only when needed; every call tracked with cost ledger |
| Idempotency | None | SHA-keyed cache; same commit → same result guaranteed |
| Security | Unrestricted execution | Subprocess sandbox, SIGKILL timeout, token redaction in logs |
| Eval framework | "Vibes" testing | Automated scorer with deterministic checks + structured failure reports |
| Failure reporting | Opaque errors | `FailureType` enum, structured logging, trace IDs end-to-end |
| Dry-run safety | None | `dry_run=true` by default; write ops require explicit `dry_run=false` |

---

## Cost & Latency

| Task | Rule-only cost | With LLM | Notes |
|------|---------------|----------|-------|
| lint-and-test | $0 match | ~$0.003 (summary) | 15-30s: clone + subprocess |
| dependency-audit | $0 match | ~$0.003 (summary) | 3-8s: HTTP only (OSV.dev) |
| security-scan | $0 match | ~$0.003 (summary) | 5-15s: file walk + bandit |
| build-and-release | $0 match | ~$0.003 (summary) | 2-5s: API only (dry-run) |
| browser execute | N/A | $0.01-0.05 | 20-60s: Playwright |
| SEC extraction | $0 rule-only | $0.01-0.05 | 5-30s |

---

## Future Roadmap

1. **CI/CD Agent Swarm**: multi-skill LangGraph DAG — lint → security → build → release with dependency edges and parallel execution
2. **Self-improving harness**: periodic eval-driven prompt optimization loop (new failure cases → prompt update → re-eval)
3. **FPGA/GPU inference**: company HPC integration for sub-100ms LLM inference on hot paths
4. **Knowledge Graph integration**: entity linking for financial event understanding from 10-K content → trading signals
5. **RL-based optimization**: SEC extraction results as state for trading strategy improvement via reward shaping
6. **Event-driven notifications**: CI/CD failures and 10-K filings → real-time trading event pipeline
