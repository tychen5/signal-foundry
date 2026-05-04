# Code Review Guidelines

> Referenced by `AGENTS.md`. Agents and human reviewers follow these standards.

## Review Checklist

### 1. Correctness
- [ ] Logic handles edge cases (empty input, None, malformed data)
- [ ] Error paths return structured error responses, not raw exceptions
- [ ] Async code properly awaited — no fire-and-forget without tracking
- [ ] Type hints match actual behavior

### 2. Security
- [ ] No hardcoded secrets, tokens, or API keys
- [ ] User input validated before processing
- [ ] LLM outputs validated before acting on them (anti-hallucination)
- [ ] GitHub tokens use least-privilege scope
- [ ] File paths sanitized (no path traversal)

### 3. Cost Discipline
- [ ] Every LLM call wrapped with cost_tracker
- [ ] Cheaper models used when sufficient (rule-based first, LLM only when needed)
- [ ] Token limits enforced on LLM inputs
- [ ] Caching used for repeated identical requests

### 4. Observability
- [ ] Structured logging with trace IDs on all operations
- [ ] Latency measured on critical paths
- [ ] Error conditions logged with sufficient context for debugging
- [ ] No `print()` statements — use `structlog`

### 5. Testing
- [ ] New logic has corresponding tests
- [ ] Edge cases covered (empty, malformed, large input)
- [ ] Tests are deterministic (no flaky external calls without mocking)
- [ ] Test names descriptive: `test_<what>_<scenario>_<expected>`

### 6. Code Quality
- [ ] Functions under 50 lines (extract if longer)
- [ ] No duplicated logic — use shared utilities
- [ ] Docstrings on public functions
- [ ] Imports organized (stdlib → third-party → local)
- [ ] Ruff lint and format pass

### 7. Architecture
- [ ] New code follows existing patterns in the module
- [ ] Pydantic models for I/O boundaries
- [ ] No tight coupling between task modules (use shared/ for common logic)
- [ ] Configuration via environment variables, not hardcoded values

## Severity Levels

| Level | Description | Action |
|-------|-------------|--------|
| 🔴 **Blocker** | Security risk, data loss, or crash | Must fix before merge |
| 🟡 **Major** | Logic bug, missing test, poor error handling | Should fix before merge |
| 🟢 **Minor** | Style, naming, small optimization | Fix if convenient |
| 💬 **Nit** | Suggestion, alternative approach | Optional |

## Anti-Patterns to Flag

- `except Exception: pass` — swallowing errors silently
- Raw string concatenation for SQL/API calls — use parameterized queries
- `time.sleep()` in async code — use `asyncio.sleep()`
- Unbounded loops without timeout
- LLM calls without max_tokens limit
- Mutable default arguments in function signatures
