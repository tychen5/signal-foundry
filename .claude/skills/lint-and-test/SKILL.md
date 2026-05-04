---
name: lint-and-test
description: >
  Runs linting and test suites on a GitHub repository. Use this skill when
  the user asks to "test this repo", "run tests", "check code quality",
  "lint this code", "CI check", or "validate code". Supports Python (ruff, pytest),
  JavaScript (eslint, jest), and generic Makefile/script targets. Read-only
  operation — does not modify the repository.
---

# Lint and Test Skill

## Purpose
Run automated code quality checks and test suites against a GitHub repository.
This is a read-only, idempotent operation.

## Inputs
- `repo_url` (required): GitHub repository URL (e.g., `https://github.com/owner/repo`)
- `branch` (optional): Branch name, defaults to `main`
- `config` (optional): Override linter/test configuration

## Outputs
```json
{
  "execution_id": "abc123",
  "status": "success | partial | failed",
  "lint_results": {
    "tool": "ruff",
    "passed": true,
    "issues": [],
    "execution_time_ms": 1200
  },
  "test_results": {
    "tool": "pytest",
    "passed": true,
    "total": 42,
    "passed_count": 40,
    "failed_count": 2,
    "skipped_count": 0,
    "execution_time_ms": 5600,
    "failures": []
  }
}
```

## Security Boundary
- **Read-only**: No write access to the repository
- **Sandbox**: Runs in isolated environment
- **No secrets**: Does not access or expose credentials
- **Timeout**: 5 minute maximum execution time

## Idempotency
Same repo + same commit SHA = same result. Results are cached by
`{repo}:{commit_sha}:{skill_name}` to avoid redundant executions.

## Error Handling
- Repository not found → clear error message with suggestion
- Authentication required → prompt for GitHub token
- Unsupported language → list supported languages
- Timeout → partial results with timeout indicator

## Workflow
1. Clone/fetch the repository (shallow clone for speed)
2. Detect project type (Python/JS/generic) from file patterns
3. Run linter (ruff for Python, eslint for JS)
4. Run tests (pytest for Python, jest for JS)
5. Aggregate results into structured output
6. Cache results by commit SHA
