# Signal-Foundry — Claude Code Configuration

> Claude Code-specific project context. For universal agent instructions (conventions,
> per-task engineering notes, behavioral guidelines), see `AGENTS.md`.

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

## Build & Run (quick ref)

```bash
pip install -r requirements.txt && playwright install chromium
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080
pytest tests/ -v --cov=src
ruff check src/ tests/ && ruff format src/ tests/
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

## Red Lines (non-negotiable constraints)

- NEVER commit API keys or secrets to git
- NEVER call LLM without cost tracking
- NEVER skip input validation on API endpoints
- NEVER use bare `except:` — always catch specific exceptions
- NEVER force push to main branch
- ALWAYS route chat-response `.content` through `src.shared.llm_utils.coerce_message_text` — newer thinking-mode models return block lists, raw `.content[:200]` crashes
- ALWAYS verify char_range matches source text (Task 3)
- ALWAYS run dry-run before destructive operations (Task 1)
- For Task 2, never trust an LLM "task complete" without grounding the answer in observed page text (`BrowserAgent._guard_against_silent_success`)
- For Task 3, never tighten the coverage check to require Items 6 / 1C / 9C / 16 — they're conditionally optional by SEC year

## Harness Quick Reference

- **LLM provider** — `src/llm_provider.py` defaults to `ChatOpenAI` pointed at NVIDIA NIM or OpenRouter base URLs. Both providers via one code path avoids AssertionError / silent-kwargs-drop bugs. Per-model `extra_body` (NIM thinking toggles) lives in `MODEL_REGISTRY`.
- **Cost tracker** — every chat call through `src/shared/cost_tracker.py` with `(task, operation, trace_id)`. Per-task / per-skill cost visible from `/metrics`.
- **Skill engine merge order** (Task 1) — `**raw_result` first, engine fields last so `summary` and `match_confidence` always win.
- **Idempotency cache** (Task 1) — `cicd:v1:{owner}/{repo}:{branch}:{skill}:{sha[:12]}:{dry_run}`. HEAD SHA fetched *before* clone.
- **Reactive planning** (Task 2) — agent observes after each step; `decide_next_action` re-decides on new page state.
- **Selective LLM** (Task 3) — LLM only fires when rule-based confidence < 0.55 OR items_found < 10 AND required items missing. Modern HTML filings stay $0.
- **Multi-modal vision** (Task 2 + 3) — `src/task2_browser/vision.py` exposes `is_vision_capable()` + `make_multimodal_message()` + `make_multimodal_message_history()`. `use_vision=true` opt-in; only for OpenRouter vision-language models. NVIDIA NIM falls back silently.
- **LangSmith tracing** — `src/shared/tracing.py` provides `@traced(name, tags)` decorators + `attach_metadata()`. No-ops when env vars absent.
- **URL-based blocked-page detection** (Task 2) — `_BLOCKED_URL_MARKERS` catches /authwall, /login, /captcha, /cf-chl, /access-denied deterministically.

For deeper per-task notes (context engineering decisions, LLM touch points, red lines per task), see `AGENTS.md` § Per-Task Engineering Notes.
