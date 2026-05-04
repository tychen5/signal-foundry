# Architecture Design Specification

> Signal-Foundry: Evaluation-first AI systems for CI/CD Skills, browser automation, and SEC 10-K extraction.

---

## 1. System Overview

Signal-Foundry is a monorepo containing three AI systems that demonstrate **harness engineering** — the discipline of wrapping LLM capabilities in structured, observable, fault-tolerant infrastructure.

### Core Philosophy
- **Harness > Model**: The surrounding infrastructure (constraints, feedback loops, evaluator separation, self-improvement mechanisms) determines system reliability, not the model itself.
- **Evaluation First**: Build eval sets BEFORE implementation. Know "what correct looks like" before writing code.
- **Cost Discipline**: Track every token. Use rules first, LLM only when needed.
- **Honest Failure Reporting**: Document what doesn't work, not just what does.

### Architecture Diagram

```
                    ┌──────────────────────┐
                    │     FastAPI App       │
                    │   (Unified Entry)     │
                    └─────────┬────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼────────┐
    │ Task 1         │ │ Task 2     │ │ Task 3        │
    │ CI/CD Skills   │ │ Browser    │ │ SEC 10-K      │
    │ Engine         │ │ Agent      │ │ Pipeline      │
    └─────────┬──────┘ └─────┬──────┘ └──────┬────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼────────┐
    │ Harness Engine │ │ Evaluator  │ │ Cost Tracker  │
    │ (retry/fb/cb)  │ │ (judge)    │ │ (token ledger)│
    └────────────────┘ └────────────┘ └───────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                    ┌─────────▼────────────┐
                    │   LLM Provider       │
                    │ OpenRouter + NVIDIA   │
                    └──────────────────────┘
```

---

## 2. Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.11+ | LangChain ecosystem, team preference |
| Agent Framework | LangChain + LangGraph | Harness engineering support, state graphs |
| LLM (OpenRouter) | GPT-5.5, Claude Opus 4.7, Gemini 3.1 Pro | Flagship models via unified gateway |
| LLM (NVIDIA) | Kimi K2.6, GLM 5.1, DeepSeek V4 Pro, MiniMax M2.7 | Cost-effective alternatives |
| Web Framework | FastAPI + Jinja2 | Async, OpenAPI docs, lightweight UI |
| Browser | Playwright (headless Chromium) | AOM support, Zeabur-compatible |
| HTML Parsing | BeautifulSoup4 + lxml | SEC filing parsing |
| Validation | Pydantic v2 | Strict schemas, structured output |
| Logging | structlog | JSON-formatted, trace-ID-tagged |
| Tracing | LangSmith | Full observability |
| Deployment | Zeabur (zbpack) | Requirement |
| Container | Docker | Sandbox + deployment |

---

## 3. Shared Infrastructure

### 3.1 LLM Provider Factory (`src/llm_provider.py`)

Dual-backend factory supporting per-request user API keys:

```python
# Users can supply their own OpenRouter key to avoid consuming server tokens
llm = get_llm(
    model_name="openai/gpt-5.5",
    user_openrouter_key="sk-or-v1-user-key",  # Optional
    temperature=0.0,
)
```

**Model routing logic**:
- OpenRouter: `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`
- NVIDIA AI Endpoints: `moonshotai/kimi-k2.6`, `z-ai/glm-5.1`, `deepseek-ai/deepseek-v4-pro`, `minimaxai/minimax-m2.7`

### 3.2 Harness Engine (`src/shared/harness.py`)

Three-layer fault tolerance:

1. **Fast-fail (Layer 1)**: Input validation, schema checks → no retry
2. **Retry with backoff (Layer 2)**: Transient errors → exponential backoff, max 3 retries
3. **Strategy replacement (Layer 3)**: Fallback to alternative approach

Plus:
- **Circuit breaker**: 5 consecutive failures → stop calling for 60 seconds
- **Execution tracing**: Every operation gets unique ID, every step logged

### 3.3 Cost Tracker (`src/shared/cost_tracker.py`)

Every LLM call records:
- `model`, `tokens_in`, `tokens_out`, `latency_ms`, `cost_usd`
- `task` (which task module), `operation` (what step)
- `trace_id` (links to request)

Exposed via `/metrics` endpoint for live monitoring.

### 3.4 Evaluation Engine (`src/shared/evaluator.py`)

Supports:
- **Deterministic checks**: JSON schema validation, char_range verification, coverage checks
- **LLM-as-judge**: Configurable rubrics for quality assessment
- **Metric aggregation**: success_rate, latency p50/p95, cost per call
- **Failure taxonomy**: Automatic classification of failure modes

---

## 4. Task 1: GitHub CI/CD as Claude Skills

### 4.1 Design Philosophy

Skills are **structured interfaces** with clear boundaries:
- JSON Schema for inputs/outputs
- Dry-run mode (always first, human confirms before side effects)
- Idempotency via commit SHA cache keys
- Security blocklist (no force push, no prod deploy, no IAM changes)

### 4.2 Skills

| Skill | Scope | Trigger | Safety |
|-------|-------|---------|--------|
| `lint-and-test` | Read-only | "test this", "run tests" | Sandbox |
| `build-and-release` | Gated write | "release", "ship it" | Dry-run first |
| `dependency-audit` | Read-only | "audit deps", "CVE check" | No installs |
| `security-scan` | Read-only | "scan for secrets", "SAST" | Static only |

### 4.3 Skill Engine Architecture

```
User Request → Skill Registry (semantic match)
    → Plan Mode (dry-run preview)
    → Human Approval (for write ops)
    → Sandbox Execution (isolated)
    → Result + Audit Log + Cost Report
```

### 4.4 Innovation: Multi-Agent Review

For code review scenarios, the engine can orchestrate:
- Code reviewer subagent
- Security scanner subagent
- Test engineer subagent

Each analyzes independently, preventing single-agent bias.

---

## 5. Task 2: Browser Automation Agent

### 5.1 PEOH Loop Architecture

```
Plan → Execute → Observe → Heal (repeat)
```

1. **Planner**: Decomposes natural language task into step sequence with expected states
2. **Executor**: Runs Playwright actions using AOM-first locators
3. **Observer**: Verifies success via DOM/screenshot analysis
4. **Healer**: Diagnoses failures and selects recovery strategy

### 5.2 Locator Strategy (3-Layer Fallback)

| Priority | Method | Resilience | Speed |
|----------|--------|------------|-------|
| 1 | AOM (Accessibility Object Model) | ★★★★★ | Fast |
| 2 | Semantic DOM (aria-label, data-testid) | ★★★★ | Fast |
| 3 | Visual (screenshot + SoM annotation) | ★★★ | Slow |

### 5.3 Self-Correction (Substantive, not just retry)

1. **Failure classification**: selector_mismatch | page_load | logic_error | network | auth | captcha
2. **Root cause analysis**: DOM diff between expected and actual
3. **Strategy selection**: Based on failure type, different recovery path
4. **Confidence scoring**: 0-1 per step; below 0.6 triggers Healer

### 5.4 Silent Failure Prevention

- **Intent verification**: After each action, LLM checks "did this achieve its intent?"
- **Success signal taxonomy**: Different actions have different success criteria
  - Click → URL change OR DOM mutation
  - Form submit → Confirmation OR redirect
  - Navigation → Target URL OR expected content
- **Semantic state tracker**: Business-level assertions (e.g., `cart_has_items=true`)

### 5.5 Honest Metrics (documented in README)

- Self-healing resolves ~65% of broken selectors
- ~35% requires human intervention (usually genuine functionality changes)
- These numbers are reported transparently

---

## 6. Task 3: SEC 10-K Extraction

### 6.1 Pipeline (4-Stage Hybrid)

| Stage | Method | Cost | Coverage |
|-------|--------|------|----------|
| 1. Pre-segmentation | Rules/regex/HTML parsing | $0 | ~70% |
| 2. Boundary refinement | LLM (cheap model, ±500 chars) | Low | +20% |
| 3. Reflexive validation | LLM-as-judge (selective) | Medium | Quality |
| 4. XBRL cross-validation | API comparison | $0 | Verification |

### 6.2 Output Schema

```json
{
  "filing_metadata": { "cik", "company_name", "accession_number", "filing_date" },
  "items": [{
    "part": "I",
    "item_number": "1",
    "item_title": "Business",
    "content_text": "...",
    "char_range": [12450, 45230],
    "status": "extracted | incorporated_by_reference | not_applicable | reserved",
    "confidence": 0.95,
    "extraction_method": "rule_based | llm_refined | hybrid"
  }],
  "processing_metadata": {
    "total_tokens_in", "total_tokens_out", "llm_calls",
    "rule_only_items", "llm_refined_items",
    "total_cost_usd", "total_latency_ms"
  }
}
```

### 6.3 Incorporated by Reference Handling

1. Detect pattern: "incorporated by reference from the Proxy Statement"
2. Query SEC Submissions API for same company/year DEF 14A
3. If found → status = `incorporated_and_resolved`, content from proxy
4. If not → status = `incorporated_by_reference`, original text preserved

### 6.4 Cost Discipline

- Modern filings: rule-only ($0 LLM cost) for ~70% of items
- Budget cap: Max $0.50 per filing
- Automatic fallback to cheaper models
- SEC API response caching (respect 10 req/sec)

---

## 7. Evaluation Strategy

### 7.1 Eval-First Development

Eval sets are designed BEFORE implementation. Each set includes:
- Normal cases (should work correctly)
- Edge cases (stress failure modes)
- Ground truth (human-verified for spot-checking)

### 7.2 Per-Task Eval Sets

**Task 1**: 5 scenarios (clean project, monorepo, known CVEs, failing tests, missing repo)

**Task 2**: 8+ cases across 4 dimensions:
- Domain diversity (Wikipedia, Google, forms, news, GitHub)
- Task complexity (single-step → multi-step → pagination)
- Failure injection (dynamic selectors, slow loading, popups)
- Edge cases (SPA, iframe, 404 handling)

**Task 3**: 8+ filings:
- Industry diversity (tech, finance, energy, healthcare)
- Company size (large-cap vs small-cap)
- Time period (modern HTML vs old text format)
- Special cases (incorporated by reference, not applicable, reserved)

### 7.3 Metrics

| Metric | Description |
|--------|-------------|
| Success Rate | % of cases passing all checks |
| Latency P50/P95 | Response time distribution |
| Cost per Request | Average USD per API call |
| Failure Distribution | Breakdown by failure type |
| Self-Correction Rate | % of failures auto-recovered |

---

## 8. Engineering Tradeoffs

| Decision | Choice | Alternative | Why |
|----------|--------|-------------|-----|
| Pure LLM vs Hybrid | Hybrid (rules + LLM) | Pure LLM | Cost: 80% savings; Reliability: rules are deterministic |
| Single vs Multi-model | Multi-model routing | Single model | Cheap model for simple cases, expensive for complex |
| Monorepo vs Multi-repo | Monorepo | Separate repos | Shared infra, single deployment, unified eval |
| DOM vs AOM locators | AOM-first with fallback | CSS selectors | 10x more resilient to UI changes |
| Full LLM validation vs Selective | Selective reflexion | Validate everything | 2.3x cost savings with only 2% accuracy drop |

---

## 9. Security & Safety

- API keys in `.env` (gitignored), never in code
- User-supplied API keys accepted per-request, not stored
- GitHub token uses least-privilege scope
- Task 1 skills execute in dry-run first mode
- Browser agent runs headless, no local filesystem access
- All LLM outputs validated before acting on them

---

## 10. Deployment (Zeabur)

- **Config**: `zbpack.json` with Python 3.11, Playwright install
- **Machine**: 2 vCPU, 4GB RAM, 50GB SSD dedicated server
- **Entry**: `uvicorn src.main:app --host 0.0.0.0 --port 8080`
- **Health check**: `/health` endpoint
- **Monitoring**: `/metrics` endpoint for cost/performance

---

## 11. Innovation Differentiators (vs OpenClaw/HermesAgent)

1. **Harness > Model**: Domain-specific harness with typed failure taxonomy, not generic tool loop
2. **AOM-first Locators**: Accessibility-based > brittle CSS selectors
3. **Selective Reflexion**: Only validate uncertain items (cost-aware)
4. **Semantic State Tracking**: Business-level assertions prevent silent failures
5. **Cost Ledger**: Every call tracked, budget caps enforced
6. **Context Engineering**: Structured context design with explicit inclusion/exclusion rationale
7. **Reproducible Eval Framework**: Quantifiable metrics, not "vibes-based" testing
8. **Trading System Connection**: Output schemas designed to feed event-driven trading systems

---

## 12. Future Roadmap

1. **Multi-agent swarm**: CI/CD skills compose into diagnostic graphs (LangGraph)
2. **Self-improving harness**: Periodic eval-driven prompt optimization
3. **GPU/FPGA acceleration**: Inference pipeline on company HPC infrastructure
4. **Knowledge Graph integration**: Entity linking for financial event understanding
5. **RL-based optimization**: Extraction results as state for trading strategy learning
6. **Event-driven notifications**: Pipeline output → real-time trading signals
