# Signal-Foundry

> Evaluation-first AI systems: harness / eval / observability / tradeoffs / deployment

## Project Architecture

@notes/progress/architecture_design_spec.md
細節目標與詳細需求說明可以參考 @notes/_briefs/_TaskDescription.md
實作時的一些細節與參考注意事項可以參閱 @notes/thoughts/_ThoughtsDraft.md

## Tech Stack

- **Language**: Python 3.11+
- **Framework**: FastAPI + Jinja2 (unified monorepo service)
- **Agent**: LangChain + LangGraph (harness engineering)
- **LLM Providers**: langchain-openrouter (GPT-5.5, Claude Opus 4.7, Gemini 3.1 Pro) + langchain-nvidia-ai-endpoints (Kimi K2.6, GLM 5.1, DeepSeek V4 Pro, MiniMax M2.7)
- **Browser**: Playwright (headless Chromium)
- **Parsing**: BeautifulSoup4 + lxml (SEC filings)
- **Observability**: structlog + LangSmith

## Build & Run

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run locally
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080

# Run tests
pytest tests/ -v --cov=src

# Lint
ruff check src/ tests/
ruff format src/ tests/
```

## Project Structure

```
src/
├── config.py              # Env vars, model registry
├── llm_provider.py         # LLM factory (OpenRouter + NVIDIA)
├── main.py                 # FastAPI app entry
├── shared/                 # Harness, evaluator, cost tracker, logger
├── task1_cicd/             # CI/CD Skills engine
├── task2_browser/          # Browser automation agent
└── task3_sec/              # SEC 10-K extraction pipeline
```

## Conventions

- All code uses `ruff` for linting and formatting
- Type hints required on all functions
- Pydantic models for all I/O schemas
- Structured logging via `structlog` (never print())
- Every LLM call tracked in cost_tracker
- Tests required for all non-trivial logic
- Conventional Commits for git messages

## Red Lines

- NEVER commit API keys or secrets to git
- NEVER call LLM without cost tracking
- NEVER skip input validation on API endpoints
- NEVER use bare `except:` — always catch specific exceptions
- NEVER force push to main branch
- ALWAYS verify char_range matches source text (Task 3)
- ALWAYS run dry-run before destructive operations (Task 1)
- ALWAYS route chat-response `.content` through `src.shared.llm_utils.coerce_message_text` — newer thinking-mode models return block lists, raw `.content[:200]` crashes
- For Task 2, never trust an LLM "task complete" without grounding the answer in observed page text (`BrowserAgent._guard_against_silent_success`)
- For Task 3, never tighten the coverage check to require Items 6 / 1C / 9C / 16 — they're conditionally optional by SEC year

## Harness Engineering Quick Reference

- **LLM provider** — `src/llm_provider.py` defaults to `langchain_openai.ChatOpenAI` pointed at NVIDIA NIM or OpenRouter base URLs. Both providers via one code path avoids the AssertionError / silent-kwargs-drop bugs in the dedicated wrappers. Per-model `extra_body` (NIM thinking toggles) lives in `MODEL_REGISTRY`.
- **Cost tracker** — every chat call through `src/shared/cost_tracker.py` with `(task, operation, trace_id)`. Per-task / per-skill cost visible from the `/metrics` endpoint.
- **Skill engine merge order** (Task 1) — `**raw_result` first, engine fields last so `summary` and `match_confidence` always win over skill-level keys with name collisions (the previous bug: `SecurityScanResult.summary` shadowed the LLM summary).
- **Idempotency cache** (Task 1) — `cicd:v1:{owner}/{repo}:{branch}:{skill}:{sha[:12]}:{dry_run}`. HEAD SHA fetched *before* clone so cache hits skip the entire subprocess pipeline.
- **Reactive planning** (Task 2) — agent observes after each step and `decide_next_action` re-decides on the new page state, rather than blindly following a pre-made plan.
- **Selective LLM** (Task 3) — LLM only fires when rule-based confidence < 0.8 or items_found < 10. Modern HTML filings stay $0.

For deeper per-task notes (context engineering decisions, LLM touch points, red lines), see `AGENTS.md`.
