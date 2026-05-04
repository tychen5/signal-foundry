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
