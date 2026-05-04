# Phase 0 Walkthrough: Repo Skeleton + Infrastructure

> **Status**: ✅ Complete | **Tests**: 18/18 passing | **Date**: 2026-05-04

---

## What Was Built

### Documentation Files (Checklist Items 7-10)
| File | Purpose | Lines |
|------|---------|-------|
| [CLAUDE.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/CLAUDE.md) | Project brain — conventions, commands, red lines | ~65 |
| [AGENTS.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/AGENTS.md) | Agent instructions — layout, commands, security, verification | ~95 |
| [PLANS.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/PLANS.md) | ExecPlan template for multi-step work | ~45 |
| [code_review.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/code_review.md) | Review checklist with severity levels | ~75 |
| [architecture_design_spec.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/notes/progress/architecture_design_spec.md) | Full technical spec covering all 3 tasks | ~280 |

### Shared Infrastructure
| File | Purpose |
|------|---------|
| [config.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/config.py) | Model registry (7 models, 2 providers), env vars, cost limits |
| [llm_provider.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/llm_provider.py) | Unified LLM factory with per-user API key support |
| [harness.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/shared/harness.py) | 3-layer fault tolerance + circuit breaker |
| [evaluator.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/shared/evaluator.py) | Deterministic checks + LLM-as-judge + metric aggregation |
| [cost_tracker.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/shared/cost_tracker.py) | Token/cost/latency ledger per request |
| [logger.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/shared/logger.py) | Structured logging with trace IDs |
| [schemas.py](file:///mnt/c/Users/leoqa/Documents/signal-foundry/src/shared/schemas.py) | Shared Pydantic models + failure taxonomy |

### Claude Skills (Task 1)
| Skill | Scope | File |
|-------|-------|------|
| lint-and-test | Read-only | [SKILL.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/.claude/skills/lint-and-test/SKILL.md) |
| build-and-release | Gated write | [SKILL.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/.claude/skills/build-and-release/SKILL.md) |
| dependency-audit | Read-only | [SKILL.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/.claude/skills/dependency-audit/SKILL.md) |
| security-scan | Read-only | [SKILL.md](file:///mnt/c/Users/leoqa/Documents/signal-foundry/.claude/skills/security-scan/SKILL.md) |

### API Endpoints (Skeleton Mode)
| Route | Purpose |
|-------|---------|
| `GET /` | Dashboard with model selector + task cards |
| `GET /health` | Health check for Zeabur |
| `GET /metrics` | Cost/performance metrics |
| `GET /api/v1/models` | Available LLM models |
| `GET /api/v1/skills/list` | List CI/CD skills |
| `POST /api/v1/skills/run` | Execute a CI/CD skill |
| `POST /api/v1/browser/execute` | Run browser task |
| `POST /api/v1/sec/extract` | Extract 10-K filing |
| `GET /api/v1/sec/filings/{cik}` | List company filings |

### Eval Sets
- **Task 1**: 5 scenarios (clean project, medical repo, security scan, error handling, dry-run)
- **Task 2**: 8 browser tasks (Wikipedia, Google, forms, multi-step, dynamic, error, cookie banner)
- **Task 3**: 8 filings (Apple, Microsoft, JPMorgan, Exxon, Tesla, small-cap, old format, healthcare)

### Deployment Config
- [zbpack.json](file:///mnt/c/Users/leoqa/Documents/signal-foundry/zbpack.json) — Zeabur config
- [Dockerfile](file:///mnt/c/Users/leoqa/Documents/signal-foundry/Dockerfile) — Production container with Playwright

---

## Key Design Decisions

1. **Per-user API keys**: Users can input their own OpenRouter key to avoid consuming server tokens
2. **Dual LLM provider**: OpenRouter for flagship models + NVIDIA for cost-effective alternatives
3. **Unified FastAPI service**: Single deployment on Zeabur instead of 3 separate services
4. **Harness engineering**: Every LLM call goes through cost tracker + structured logging + trace IDs
5. **Eval-first**: Eval sets designed before implementation code

---

## Test Results

```
tests/test_api.py::TestHealthAndSystem::test_health_check PASSED
tests/test_api.py::TestHealthAndSystem::test_list_models PASSED
tests/test_api.py::TestHealthAndSystem::test_metrics PASSED
tests/test_api.py::TestHealthAndSystem::test_dashboard PASSED
tests/test_api.py::TestTask1Routes::test_list_skills PASSED
tests/test_api.py::TestTask1Routes::test_run_skill PASSED
tests/test_api.py::TestTask1Routes::test_run_invalid_skill PASSED
tests/test_api.py::TestTask2Routes::test_execute_task PASSED
tests/test_api.py::TestTask3Routes::test_extract_with_cik PASSED
tests/test_api.py::TestTask3Routes::test_extract_missing_input PASSED
tests/test_shared.py::TestSchemas::test_execution_result_creation PASSED
tests/test_shared.py::TestSchemas::test_execution_result_with_error PASSED
tests/test_shared.py::TestCostTracker::test_record_call PASSED
tests/test_shared.py::TestCostTracker::test_session_summary PASSED
tests/test_shared.py::TestHarness::test_successful_execution PASSED
tests/test_shared.py::TestHarness::test_fast_fail PASSED
tests/test_shared.py::TestEvaluator::test_deterministic_check_schema PASSED
tests/test_shared.py::TestEvaluator::test_deterministic_check_missing PASSED

======================== 18 passed ========================
```

## Next Steps
→ Phase 1: Implement Task 3 (SEC 10-K extraction pipeline)
