# AGENTS.md — Agent Instructions for Signal-Foundry

## Project Overview

Signal-Foundry is a monorepo containing three AI systems demonstrating evaluation-first harness engineering:
1. **Task 1 (CI/CD Skills)**: GitHub CI/CD workflows packaged as Claude Skills
2. **Task 2 (Browser Agent)**: Self-healing browser automation with natural language input
3. **Task 3 (SEC 10-K)**: Hybrid rule+LLM pipeline for structured extraction from SEC filings
細節目標與詳細需求說明可以參考 @notes/_briefs/_TaskDescription.md
實作時的一些細節與參考注意事項可以參閱 @notes/thoughts/_ThoughtsDraft.md

## Repository Layout

```
signal-foundry/
├── src/                    # Main Python package
│   ├── config.py           # Configuration & model registry
│   ├── llm_provider.py     # LLM factory (OpenRouter + NVIDIA)
│   ├── main.py             # FastAPI app entry point
│   ├── shared/             # Shared harness infrastructure
│   │   ├── harness.py      # Retry, fallback, circuit breaker
│   │   ├── evaluator.py    # Eval engine (LLM-as-judge + deterministic)
│   │   ├── cost_tracker.py # Token/cost/latency ledger
│   │   ├── logger.py       # Structured logging
│   │   └── schemas.py      # Shared Pydantic models
│   ├── task1_cicd/         # CI/CD Skills engine
│   ├── task2_browser/      # Browser automation agent
│   └── task3_sec/          # SEC 10-K extraction pipeline
├── evals/                  # Evaluation sets & results per task
├── prompts/                # Versioned prompt records
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS, JS assets
├── tests/                  # Unit + integration tests
├── .claude/skills/         # Claude Skill definitions (SKILL.md)
└── notes/                  # Design docs & progress tracking
```

## Build, Test, and Lint Commands

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Run dev server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080

# Test
pytest tests/ -v --cov=src --cov-report=term-missing

# Lint & Format
ruff check src/ tests/
ruff format src/ tests/

# Run evaluations
python -m evals.run_all
```

## Engineering Conventions

1. **Type hints** on every function signature
2. **Pydantic v2 models** for all request/response schemas
3. **Structured logging** via `structlog` — never use `print()`
4. **Cost tracking** — every LLM call must go through `cost_tracker`
5. **Error handling** — catch specific exceptions, log context, return structured error responses
6. **Conventional Commits**: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `chore:`
7. **Docstrings** required on all public functions and classes

## Security Constraints

- API keys stored in `.env`, never committed — `.env` is in `.gitignore`
- GitHub token uses least-privilege scope (`repo:read`, `actions:read`)
- Task 1 skills execute in sandbox mode (dry-run first, human confirms)
- Task 2 browser agent runs in headless mode, no access to local filesystem
- User-supplied OpenRouter keys are accepted per-request, not stored server-side

## Testing Standards

- Unit tests for all utility functions and parsers
- Integration tests for API endpoints (use FastAPI TestClient)
- Eval sets for each task with edge cases documented
- Test names follow: `test_<function>_<scenario>_<expected_outcome>`

## Verification Checklist

Before declaring work complete:
1. All tests pass: `pytest tests/ -v`
2. Lint passes: `ruff check src/ tests/`
3. API endpoints respond correctly: test each route
4. Cost tracker reports sane values
5. Eval set runs produce expected metrics
6. No secrets in committed code

## ExecPlan Reference

When tackling multi-step work, follow the plan in `PLANS.md`. Create a step-by-step execution plan, get approval, then execute incrementally with verification at each step.

---

## Per-Task Engineering Notes

### Task 1 — CI/CD Skills Engine

**Context engineering decisions**

- The full skill engine pipeline is documented in `src/task1_cicd/skill_engine.py`'s 13-step header comment. Read that first before changing anything.
- Skills are *not* exposed as raw bash. Each skill is a Pydantic-typed function that returns a structured result (`LintAndTestResult`, `DependencyAuditResult`, `SecurityScanResult`, `BuildAndReleaseResult`). The schema is the contract.
- The skill registry uses three matching tiers (exact map → fuzzy token overlap → LLM disambiguation). Always prefer the cheaper tier; LLM is the fallback, not the default.

**LLM touch points (only two per request)**

1. `skill_registry.resolve_skill_name` — one call, only if exact + fuzzy matching both fail. ~$0.0005 per call.
2. `skill_registry.llm_summarize` — one call after the skill runs to produce a 2-3 sentence human-readable summary. ~$0.003 per call. Always tracked in `cost_tracker`.

Anything else inside Task 1 is deterministic.

**Red lines**

- `build-and-release` defaults to `dry_run=True`. The skill never creates a real tag without an explicit `dry_run=False`.
- Tokens (`GITHUB_TOKEN`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`) are stripped from `subprocess.env` before any sandboxed command runs (`sandbox.SandboxConfig._sanitized_env`).
- The clone URL contains the token but `_redact_token()` rewrites it to `https://x-access-token:***@…` before any structlog call.
- The result-merge order in `skill_engine` is `**raw_result` first, engine fields last — so engine-level keys (`summary`, `match_confidence`) always win over skill-defined fields with conflicting names. Don't reorder.

**Idempotency**

- Cache key: `cicd:v1:{owner}/{repo}:{branch}:{skill}:{sha[:12]}:{dry_run}`. Same repo + same commit + same skill = same result, no clone, no LLM.
- HEAD SHA is fetched from the GitHub API *before* cloning so cache hits short-circuit the entire subprocess pipeline.
- TTL: 3600s, in-process dict. Swap for Redis in production.

### Task 2 — Browser Agent

**Context engineering decisions**

- Four-stage Planner → Executor → Observer → Healer architecture. The agent does NOT blindly follow a pre-made plan: it observes after each step and `decide_next_action` re-decides based on the new page state (reactive planning).
- Locator strategy is AOM-first (accessibility tree → semantic DOM → CSS/text), because the accessibility tree survives UI redesigns far better than CSS selectors.
- Healer is *not* try/except retry. It classifies failures into a 9-class root cause taxonomy and selects a targeted recovery strategy per cause.

**Silent-failure guard (highest-value behavior)**

- `BrowserAgent._guard_against_silent_success` runs after every "completed" run.
- Hedging phrases ("I cannot find...", "頁面沒有...") in the final answer flip status to `not_found` — distinguishes "data doesn't exist" from "I succeeded".
- Numeric tokens in the final answer that don't appear in any observed page text → `unverified` with the offending values logged in `failure_modes`. Catches the most common hallucination mode for finance scraping.

**LLM touch points**

1. `planner.plan_task` — initial decomposition.
2. `planner.decide_next_action` — reactive next-step on every loop iteration.
3. `planner.verify_with_llm` — every iteration, decides if task is complete.
4. `healer.diagnose_with_llm` — only on the *second* heal attempt (the first uses deterministic diagnosis).

**Red lines**

- Default browser context is headless and runs as a generic Chromium UA. Don't add filesystem mounts.
- Cookie/popup banners are auto-dismissed in `executor.dismiss_popups` before each action — don't interleave with new code that depends on the banner being visible.
- `_MAX_HEAL_ATTEMPTS=3` is a hard cap. If three healing attempts fail, the step records the diagnosis and moves on.

### Task 3 — SEC 10-K Pipeline

**Context engineering decisions**

- 4-stage hybrid pipeline: rule-based pre-segmentation → optional LLM boundary refinement → validation/auto-fix → optional XBRL cross-validation. Each stage explicitly logs whether it ran via `processing_metadata.stages_used`.
- LLM only runs when rule-based confidence is low (`< 0.8`) or item count is suspiciously low (`< 10`). For modern HTML filings this means LLM cost is $0 in the typical case.
- The validator uses the SAME strict header-zone heuristic from `rule_parser.detect_item_status`. Don't introduce a separate looser check (the previous bug was a `dict_check loose check` that misclassified Tesla 2023 Item 1 because the body mentions both "incorporated" and "reference" in unrelated contexts).

**LLM touch points**

1. `llm_refiner.refine_boundaries` — only invoked for low-confidence boundaries. Uses ±500 char context per call.
2. (Optional) `llm_refiner._detect_missing_items` — gap-fill for items the rule parser missed entirely.

**Red lines**

- All SEC requests must declare `User-Agent` (set in `config.sec_user_agent`) and stay under 10 req/sec — the fetcher enforces this with `_rate_limiter` + `_respect_rate_limit`.
- Streaming downloads have a configurable `SEC_MAX_DOWNLOAD_MB` ceiling (default 200MB) to prevent OOM on the largest filings.
- NOT_FOUND items use `[0, 0]` as a sentinel char_range — the validator special-cases this so the placeholder doesn't surface as a `char_range_bounds` error.
- Items 6 / 1C / 9C / 16 are recognised as legitimately optional (Item 6 was retired by SEC release 33-10890 in 2021; 1C/9C added 2023; 16 always optional). Don't tighten the coverage check to require them globally.

---

## Harness Engineering Highlights (cross-cutting)

- **Cost tracker** (`src/shared/cost_tracker.py`) is the single source of truth for LLM spend. Every chat call goes through it with `(task, operation, trace_id)` so per-skill / per-task costs are auditable from the `/metrics` endpoint.
- **LLM provider** (`src/llm_provider.py`) defaults to `langchain_openai.ChatOpenAI` pointed at NVIDIA NIM or OpenRouter base URLs — uniform code path that avoids the AssertionError / max_tokens-vs-max_completion_tokens bugs in the dedicated wrappers.
- **Chat content coercion** (`src/shared/llm_utils.coerce_message_text`) flattens both string and `[{"type":"text","text":...}]` block-list responses. Use it everywhere we pull `.content` from a chat response — newer thinking-mode models return block lists and string slicing crashes.
- **Verification before completion** — Task 2 enforces this at the agent level (silent-failure guard) and Task 3 enforces it via the validator + XBRL cross-check.
