# Signal-Foundry: Phase 3 + Documentation Hardening Plan

## Context

Signal-Foundry is an interview demo for VICI Holdings showing evaluation-first harness engineering. Phase 0 (skeleton), Phase 1 (Task 3 SEC 10-K), and Phase 2 (Task 2 Browser Agent) are fully complete with 103/103 tests passing. The remaining work is:

1. **Phase 3 Task 1**: GitHub CI/CD as Claude Skills — only a stub router exists; needs real execution engine
2. **UI Templates**: task1.html, task2.html, task3.html all missing (APIs are production-ready)
3. **Documentation**: README.md is placeholder; AGENTS.md/CLAUDE.md/architecture_design_spec.md need strengthening to impress interviewers

The primary goal is to complete Task 1 so all three tasks are fully functional, then polish documentation to convey the depth of engineering thinking.

---

## Priority Order

1. Task 1 core implementation (the biggest gap)
2. Prompts for Task 1
3. Tests for Task 1 (pytest, all pass)
4. Eval runner for Task 1
5. UI templates (task1.html, task2.html, task3.html) + main.py routes
6. README.md full rewrite
7. AGENTS.md + CLAUDE.md improvements
8. architecture_design_spec.md additions
9. progress_notes.md update

---

## Part 1: Task 1 — New Files to Create

### `src/task1_cicd/schemas.py`
Move `SkillRunRequest` out of router.py into this dedicated schema file. Add:
- `RepoContext` — resolved clone info (owner, repo, branch, commit_sha, clone_path, language flags)
- `SandboxResult` — subprocess output (cmd, returncode, stdout, stderr, timed_out, duration_ms)
- `LintAndTestResult` — lint issues + test pass/fail counts
- `DependencyAuditResult` — vulnerability list + outdated packages
- `SecurityScanResult` — findings list with severity breakdown
- `BuildAndReleaseResult` — changelog, version bump, release URL (None in dry_run)
- `SkillRunResponse` — wraps raw result + LLM summary + cost metadata

### `src/task1_cicd/github_client.py`
Uses `PyGithub` (already in requirements.txt) for API and `subprocess` for git clone.

Key functions:
```python
async def validate_repo(repo_url: str) -> dict  # 404 → FastFailError
async def get_repo_head_sha(owner, repo, branch) -> str  # fast, no clone
async def clone_repo(repo_url, branch, dest_dir, timeout=120) -> str  # returns HEAD SHA
    # git clone --depth 1 --branch {branch} https://{token}@github.com/{owner}/{repo}.git {dest_dir}
    # token embedded in URL, never logged (replaced with ***)
async def get_commits_since_tag(owner, repo, since_tag) -> list[dict]
async def get_latest_tag(owner, repo) -> Optional[str]
async def create_github_release(owner, repo, tag_name, name, body, token) -> str  # dry_run=False only
```

### `src/task1_cicd/sandbox.py`
Subprocess runner with timeout + cleanup. No Docker needed.

Key functions:
```python
async def run_command(cmd: list[str], config: SandboxConfig) -> SandboxResult
    # asyncio.create_subprocess_exec, SIGTERM → 5s wait → SIGKILL on timeout
    # stdout/stderr capped at 1MB
    # strips GITHUB_TOKEN from child env
def detect_language(clone_path: str) -> str  # "python" | "javascript" | "unknown"
    # checks pyproject.toml, requirements.txt, package.json in that order
def make_temp_dir(prefix="sf_cicd_") -> str  # tempfile.mkdtemp()
def cleanup_temp_dir(path: str) -> None  # shutil.rmtree, swallows errors
```

### `src/task1_cicd/skills/lint_and_test.py`
```python
async def run(ctx: RepoContext, cfg: SandboxConfig) -> LintAndTestResult
    # 1. detect language from ctx
    # 2. Python: pip install ruff pytest in temp venv (if not present), run ruff + pytest
    # 3. JS: npx eslint + jest (if package.json has scripts)
    # Parses: ruff --output-format json, pytest -q output via regex

def _parse_ruff_json(stdout: str) -> tuple[bool, list[dict]]
def _parse_pytest_output(stdout: str) -> tuple[bool, int, int, int, list[dict]]
```

Subprocess commands:
- Python lint: `[sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"]`
- Python test: `[sys.executable, "-m", "pytest", "--tb=short", "-q", "--no-header"]`
- Install ruff+pytest: `[sys.executable, "-m", "pip", "install", "ruff", "pytest", "-q"]`

### `src/task1_cicd/skills/dependency_audit.py`
Pure parse + HTTP — no subprocess needed.

```python
async def run(ctx: RepoContext) -> DependencyAuditResult
    # 1. Find lock files (requirements.txt, pyproject.toml, package-lock.json)
    # 2. Parse dependencies into list[PackagePin]
    # 3. POST to https://api.osv.dev/v1/querybatch (free, no auth)
    # 4. GET https://pypi.org/pypi/{name}/json for latest versions
    # Returns: vulnerability list + outdated packages

def _parse_requirements_txt(path: str) -> list[PackagePin]  # handles == >= ~= etc.
def _parse_pyproject_toml(path: str) -> list[PackagePin]    # tomllib (stdlib 3.11+)
def _parse_package_lock_v2(path: str) -> list[PackagePin]   # packages["node_modules/X"]
async def _query_osv_batch(packages, ecosystem) -> list[VulnerabilityEntry]
    # httpx.AsyncClient, POST /v1/querybatch with up to 100 packages
async def _check_outdated_python(packages) -> list[OutdatedEntry]
    # GET https://pypi.org/pypi/{name}/json, compare latest vs pinned
```

### `src/task1_cicd/skills/security_scan.py`
Secret detection via pure Python regex + bandit for SAST.

```python
async def run(ctx: RepoContext, cfg: SandboxConfig) -> SecurityScanResult

def _run_secret_detection(clone_path: str) -> list[SecurityFinding]
    # Walk all text files (skip .git, node_modules, __pycache__, binary files, >1MB)
    # Regex patterns to detect:
    #   AWS key: r'AKIA[0-9A-Z]{16}'
    #   GitHub token: r'ghp_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{82}'
    #   Generic API key: r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([A-Za-z0-9\-_]{20,})'
    #   Private key: r'-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----'
    #   Slack token: r'xox[baprs]-[0-9]{12}-[0-9]{12}-[0-9a-zA-Z]{24}'
    # Returns list of SecurityFinding with file, line, severity, match_preview, recommendation

async def _run_bandit(clone_path: str, cfg: SandboxConfig) -> list[SecurityFinding]
    # cmd: [sys.executable, "-m", "bandit", "-r", ".", "-f", "json", "-ll"]
    # -ll = medium and above severity only
    # Parse bandit JSON output, map to SecurityFinding
    # bandit added to requirements.txt

def _parse_bandit_json(stdout: str) -> list[SecurityFinding]
```

### `src/task1_cicd/skills/build_and_release.py`
Dry-run by default — never creates a real release unless dry_run=False.

```python
async def run(ctx: RepoContext, dry_run: bool, token: str) -> BuildAndReleaseResult
    # 1. get_latest_tag() → current version
    # 2. get_commits_since_tag() → list of commits
    # 3. _determine_version_bump(commits) → "major"|"minor"|"patch"
    # 4. _bump_semver(current, bump) → next_version
    # 5. _build_changelog(commits) → markdown string
    # 6. if dry_run=True: return preview (no API calls)
    # 7. if dry_run=False: create tag + release via GitHub API (idempotency: check tag exists first)

def _determine_version_bump(commits: list[dict]) -> tuple[str, str]
    # Conventional commits: BREAKING CHANGE → major, feat: → minor, else → patch

def _bump_semver(current: Optional[str], bump: str) -> str
    # Parse vX.Y.Z, increment, return new tag string

def _build_changelog(commits: list[dict], current_tag: Optional[str]) -> str
    # Markdown: ## What's Changed / ### Features / ### Fixes / ### Other
```

### `src/task1_cicd/skill_registry.py`
Three-tier matching: exact → fuzzy → LLM.

```python
_EXACT_MAP = {
    "lint-and-test": "lint-and-test", "lint_and_test": "lint-and-test",
    "build-and-release": "build-and-release", "build_and_release": "build-and-release",
    "dependency-audit": "dependency-audit", "dependency_audit": "dependency-audit",
    "security-scan": "security-scan", "security_scan": "security-scan",
}

async def resolve_skill_name(raw: str, model_name, user_api_key, trace_id) -> tuple[str, float]
    # 1. exact match → return with confidence=1.0
    # 2. fuzzy token overlap against trigger phrases → if score>0.4 return
    # 3. LLM call (v1_skill_match.txt) → structured JSON {"skill":..., "confidence":...}
    # Raises FastFailError if max confidence < 0.5

def _fuzzy_match(raw: str) -> Optional[tuple[str, float]]
    # Token overlap: split by space/dash, count matches against trigger phrase lists

async def _llm_match(raw, model_name, user_api_key, trace_id) -> tuple[str, float]
    # Load prompts/cicd/v1_skill_match.txt
    # Call LLM via llm_provider.get_llm(), track cost via cost_tracker
    # Parse JSON response: {"skill": "...", "confidence": 0.85}
```

### `src/task1_cicd/skill_engine.py`
Main orchestrator — the heart of Task 1.

```python
_result_cache: dict[str, dict] = {}   # in-process cache, keyed by SHA
_cache_lock = asyncio.Lock()

def _make_cache_key(owner, repo, branch, skill_name, commit_sha, dry_run) -> str
    # "cicd:v1:{owner}/{repo}:{branch}:{skill_name}:{commit_sha[:12]}:{dry_run}"

async def run_skill(request: SkillRunRequest, trace_id: str) -> ExecutionResult
    # Full pipeline with timing:
    # [1] resolve skill name (registry, may cost LLM tokens)
    # [2] validate repo exists (github_client.validate_repo)
    # [3] get HEAD SHA (github_client.get_repo_head_sha) — fast, no clone
    # [4] check cache — if hit, return immediately (idempotency guarantee)
    # [5] make temp dir
    # [6] clone repo (github_client.clone_repo, --depth 1)
    # [7] detect language (sandbox.detect_language)
    # [8] build RepoContext
    # [9] dispatch to skill (lint_and_test / dependency_audit / security_scan / build_and_release)
    # [10] LLM summarize (skill_registry._llm_summarize)
    # [11] cache result
    # [12] cleanup temp dir (finally block)
    # [13] return ExecutionResult with full cost metadata

async def _dispatch(skill_name, ctx, dry_run, token, sandbox_cfg) -> dict
    # Routes to correct skills/ module

async def _llm_summarize(skill_name, result, model_name, user_api_key, trace_id) -> str
    # Load prompts/cicd/v1_result_summary.txt
    # One LLM call → 2-3 sentence actionable summary
    # Tracked in cost_tracker
```

### `src/task1_cicd/skills/__init__.py`
Empty package marker.

### Update `src/task1_cicd/router.py`
Replace mock return with real engine call:
```python
# Remove the if request.skill_name not in valid_skills block (registry handles this)
# Replace skeleton return with:
return await skill_engine.run_skill(request, trace_id)
# Wrap in try/except FastFailError → 400, Exception → 500
```

---

## Part 2: Requirements Updates

Add to `requirements.txt`:
```
bandit>=1.7.9          # SAST scanning for security-scan skill
semver>=3.0.2          # Semantic versioning for build-and-release skill
```

---

## Part 3: Prompts

### `prompts/cicd/v1_skill_match.txt`
Maps free-form user requests to one of four skills. Lists all skills with trigger phrases. Asks for JSON: `{"skill": "...", "confidence": 0.85, "reasoning": "..."}`. Uses temperature=0.0 for determinism.

### `prompts/cicd/v1_result_summary.txt`
Converts structured skill result JSON to a 2-3 sentence human summary. Emphasizes: what was found, severity, single most important next action. No markdown formatting in output.

### `prompts/cicd/README.md`
Prompt ledger: version history, template variables, eval results for each version, reasoning for changes.

---

## Part 4: Tests

### `tests/test_task1_cicd.py`
Following the exact pattern of `tests/test_task2_browser.py`:

```
TestSchemas              — Pydantic model creation, field validation
TestGitHubClient         — URL parsing, token injection (mock subprocess), validate_repo mock
TestSandbox              — run_command with fixture commands, detect_language on temp dirs
TestSkillRegistry        — exact match, fuzzy match, rejection of unknown phrases
TestLintAndTest          — _parse_ruff_json on fixture JSON, _parse_pytest_output on fixture text
TestDependencyAudit      — _parse_requirements_txt, _parse_pyproject_toml on fixture files
TestSecurityScan         — _run_secret_detection on fixture files with fake secrets
TestBuildAndRelease      — _determine_version_bump, _bump_semver, _build_changelog
TestSkillEngine          — cache key construction, dispatch routing, cache hit behavior
TestPromptFiles          — prompts/cicd/*.txt exist and contain required template variables
TestEvalSet              — scenarios.json loads, all 5 cases have required fields
TestAPIRoutes            — monkeypatched engine: POST /run returns ExecutionResult schema
```

Key test patterns:
- No live GitHub API calls in unit tests (monkeypatch httpx/PyGithub)
- Secret detection tested against fixture Python files containing fake AWS keys
- Ruff/pytest output parsing tested against fixture JSON/text strings
- Eval set validation checks schema completeness

---

## Part 5: Eval Runner

### `evals/task1/__init__.py`
Empty package marker.

### `evals/task1/run_eval.py`
Mirrors `evals/task2/run_eval.py` exactly:
- Loads `scenarios.json` (5 cases)
- Calls POST `/api/v1/skills/run` or imports engine directly (--direct mode)
- Scores each case: no_crash, has_result, correct_skill, dry_run_no_tag, error_case_detected
- Writes JSON + Markdown report to `evals/task1/results/`
- CLI: `python -m evals.task1.run_eval [--direct] [--model X]`

---

## Part 6: UI Templates

### Add routes to `src/main.py`
```python
@app.get("/task1", response_class=HTMLResponse)
async def task1_page(request: Request):
    return templates.TemplateResponse("task1.html", {"request": request})

@app.get("/task2", response_class=HTMLResponse)  
async def task2_page(request: Request):
    return templates.TemplateResponse("task2.html", {"request": request})

@app.get("/task3", response_class=HTMLResponse)
async def task3_page(request: Request):
    return templates.TemplateResponse("task3.html", {"request": request})
```

### `templates/task1.html`
CI/CD Skills runner UI:
- Repo URL input, branch input (default: main)
- Skill dropdown (4 options)
- Dry-run checkbox (checked by default, red warning when unchecked)
- Model selector (same pattern as index.html)
- "Run Skill" button → POST to /api/v1/skills/run
- Result panel: status badge, execution time, LLM summary, collapsible raw JSON
- Specialized result renderers per skill:
  - lint-and-test: issues table + test pass/fail counts
  - dependency-audit: CVE table with links to osv.dev
  - security-scan: findings table colored by severity
  - build-and-release: changelog preview + "Confirm Release" button (calls again with dry_run: false)
- Cost display: tokens used, estimated USD

### `templates/task2.html`
Browser Agent task runner:
- Natural language task input (large textarea)
- URL hint field (optional start URL)
- Max steps selector (5/10/20)
- Model selector
- "Execute Task" button → POST to /api/v1/browser/execute
- Live status polling: GET /api/v1/browser/status/{trace_id} every 2s
- Step-by-step trace view: each step shows action, description, success/fail badge
- Final result display: extracted data, error message if failed
- Confidence score bar for each step
- Root cause taxonomy displayed for failed steps

### `templates/task3.html`
SEC 10-K extraction UI:
- CIK + Accession Number inputs (with examples: Apple 0000320193 / 0000320193-23-000106)
- OR file URL input (alternative)
- Skip LLM checkbox, Skip XBRL checkbox
- Model selector
- "Extract Filing" button → POST to /api/v1/sec/extract
- Results: filing metadata header (company, date, CIK)
- Items table: part, item number, title, status badge, char_range, confidence
- Click item to expand full content_text
- Cost metadata footer: tokens used, LLM calls, rule-only %, total cost, latency

---

## Part 7: Documentation Improvements

### `README.md` — Full Rewrite
Structure:
1. **Header**: tagline + 3 task badges + Zeabur URL
2. **Architecture** (Mermaid diagram): FastAPI → 3 task engines → shared harness → LLM Provider
3. **Why This Beats OpenClaw/HermesAgent**: Domain harness vs generic loop, failure taxonomy, cost discipline, eval framework
4. **Task 1: CI/CD Skills** — skill boundary design, idempotency, dry-run safety, multi-step execution trace
5. **Task 2: Browser Agent** — AOM-first locators, 9-class root cause taxonomy, silent failure prevention, SoM vision
6. **Task 3: SEC 10-K** — hybrid pipeline stages, incorporated-by-reference handling, XBRL cross-validation
7. **Design Trade-offs**: table with decision/choice/alternative/why for each major call
8. **Evaluation Discipline**: per-task metrics, failure taxonomy, held-out test strategy
9. **AI Collaboration Log**: concrete examples of Claude Code usage, where human judgment overrode AI, what prompts failed and were revised
10. **How to Run**: install, env setup, server start, individual task endpoints
11. **Deployment**: Zeabur URLs for each service
12. **Cost & Latency**: per-task benchmark table (rule-only $0 vs LLM-assisted)
13. **Future Roadmap**: multi-agent swarm, self-improving harness, RL optimization, trading system integration

### `AGENTS.md` — Improvements
Add sections:
- **AI Collaboration Patterns**: when to use subagents vs skills vs direct LLM
- **Harness Engineering**: circuit breaker thresholds, failure taxonomy reference
- **Task 1 Security Boundaries**: blocklist, dry-run enforcement, token injection rules
- **Eval Runner Usage**: how to run each task's eval set
- Update verification checklist to include Task 1

### `CLAUDE.md` — Improvements
Add:
- **Context Engineering Decisions**: what goes into each LLM call context and why
- **Task 1 Red Lines**: never embed token in logs, always dry-run first, never create release without explicit dry_run=False
- **LLM Touch Points**: exact list of where LLM is used in each task (cost discipline reference)
- Reference to prompts/ versioning convention

### `notes/progress/architecture_design_spec.md` — Additions
Add to Task 1 section:
- Full skill engine data flow diagram
- Idempotency cache design (SHA-based key, in-process dict)
- Three-tier skill matching (exact → fuzzy → LLM)
- Two LLM touch points with cost estimates
- Concrete subprocess commands per skill

Add new section:
- **Context Engineering**: per-task context design rationale (what's included/excluded/why)
- **Innovation vs OpenClaw/HermesAgent**: expanded comparison table

---

## Part 8: progress_notes.md Updates

Mark Phase 3 Task 1 checkbox as ✅ after implementation. Add:
- Phase 3 Task 1 completion state with validation results
- Phase 4 remaining items (Zeabur deployment, eval runs, README)
- Link to this plan for implementation reference

---

## Critical Files Modified

| File | Action | Priority |
|------|--------|----------|
| `src/task1_cicd/schemas.py` | CREATE | 1 |
| `src/task1_cicd/github_client.py` | CREATE | 1 |
| `src/task1_cicd/sandbox.py` | CREATE | 1 |
| `src/task1_cicd/skills/__init__.py` | CREATE | 1 |
| `src/task1_cicd/skills/dependency_audit.py` | CREATE | 2 |
| `src/task1_cicd/skills/security_scan.py` | CREATE | 2 |
| `src/task1_cicd/skills/lint_and_test.py` | CREATE | 2 |
| `src/task1_cicd/skills/build_and_release.py` | CREATE | 2 |
| `src/task1_cicd/skill_registry.py` | CREATE | 3 |
| `src/task1_cicd/skill_engine.py` | CREATE | 3 |
| `src/task1_cicd/router.py` | UPDATE | 3 |
| `prompts/cicd/v1_skill_match.txt` | CREATE | 3 |
| `prompts/cicd/v1_result_summary.txt` | CREATE | 3 |
| `prompts/cicd/README.md` | CREATE | 3 |
| `tests/test_task1_cicd.py` | CREATE | 4 |
| `evals/task1/__init__.py` | CREATE | 4 |
| `evals/task1/run_eval.py` | CREATE | 4 |
| `requirements.txt` | UPDATE (+bandit, +semver) | 1 |
| `src/main.py` | UPDATE (add /task1, /task2, /task3 routes) | 5 |
| `templates/task1.html` | CREATE | 5 |
| `templates/task2.html` | CREATE | 5 |
| `templates/task3.html` | CREATE | 5 |
| `README.md` | REWRITE | 6 |
| `AGENTS.md` | UPDATE | 7 |
| `CLAUDE.md` | UPDATE | 7 |
| `notes/progress/architecture_design_spec.md` | UPDATE | 7 |
| `notes/progress/progress_notes.md` | UPDATE | 8 |

---

## Verification

After implementation:

```bash
# 1. All tests pass
pytest tests/ -v
# Expected: 103 existing + ~40 new Task 1 tests = 140+ passed

# 2. No lint warnings
ruff check src/ tests/ evals/

# 3. Server starts clean
uvicorn src.main:app --host 0.0.0.0 --port 8080

# 4. Task 1 API responds (not skeleton anymore)
curl -X POST http://localhost:8080/api/v1/skills/run \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/tychen5/signal-foundry", "skill_name": "lint-and-test", "dry_run": true}'
# Expected: real result with lint issues + test results (not "skeleton mode" message)

# 5. Skill registry fuzzy match works
curl -X POST http://localhost:8080/api/v1/skills/run \
  -d '{"repo_url": "...", "skill_name": "check if my code has leaked tokens"}'
# Expected: routes to security-scan via LLM matching

# 6. Dependency audit hits real OSV.dev
curl -X POST http://localhost:8080/api/v1/skills/run \
  -d '{"repo_url": "https://github.com/tychen5/signal-foundry", "skill_name": "dependency-audit"}'
# Expected: real CVE results or "no vulnerabilities found"

# 7. Eval runner completes
python -m evals.task1.run_eval --direct

# 8. UI pages load (no 404)
curl http://localhost:8080/task1
curl http://localhost:8080/task2  
curl http://localhost:8080/task3
```

---

## Key Design Decisions (for Documentation)

1. **Why in-process dict cache (not Redis)**: SHA-based cache is sufficient for demo; comment notes where to swap Redis for production. Avoids unnecessary dependency.

2. **Why get SHA before clone**: GitHub REST API returns HEAD SHA cheaply (1 HTTP request vs full clone). Cache hit before clone = zero subprocess cost.

3. **Why subprocess not Docker**: Zeabur manages containerization. Subprocess with tempdir + timeout + SIGKILL achieves sufficient sandbox for this demo. Docker-in-Docker adds complexity without proportional benefit.

4. **Why OSV.dev not pip-audit subprocess**: Pure HTTP, free, no auth, batch endpoint, perfectly fits the "no execution in audit" constraint. More portable than subprocess tools.

5. **Two LLM touch points only**: skill matching (only when fuzzy fails) and result summarization (always once). Both are tracked. This is cost discipline — not using LLM where rules suffice.

6. **Dry-run as first-class design**: build-and-release returns a preview with identical schema as a real release, just `release_url=None` and `tag_created=False`. The UI shows a "Confirm Release" button that sends the same request with `dry_run=false`. This is the human-in-the-loop pattern.
