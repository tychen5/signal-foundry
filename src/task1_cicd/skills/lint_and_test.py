"""
Lint and Test Skill.

Runs language-appropriate linting and test tools in a sandboxed subprocess:
- Python: ruff (lint) + pytest (tests)
- JavaScript: eslint (lint) + jest (tests)

Tools are installed into the target repo's environment if not already present.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from src.shared.logger import get_logger
from src.task1_cicd.sandbox import SandboxConfig, run_command
from src.task1_cicd.schemas import LintAndTestResult, LintIssue, RepoContext, TestFailure

logger = get_logger("lint_and_test")


async def run(ctx: RepoContext, cfg: SandboxConfig) -> LintAndTestResult:
    """Main entry: detect language → run lint → run tests → build result."""
    clone_path = ctx.clone_path
    language = ctx.language

    if language == "python":
        return await _run_python(clone_path, cfg)
    elif language == "javascript":
        return await _run_javascript(clone_path, cfg)
    else:
        return LintAndTestResult(
            status="partial",
            language="unknown",
            lint_tool="none",
            lint_passed=True,
            test_tool="none",
            test_passed=True,
            notes="No recognized language detected (no pyproject.toml, requirements.txt, or package.json found).",
        )


async def _run_python(clone_path: str, cfg: SandboxConfig) -> LintAndTestResult:
    """Run ruff + pytest on a Python project."""
    sandbox_cfg = SandboxConfig(
        timeout_seconds=cfg.timeout_seconds,
        max_output_bytes=cfg.max_output_bytes,
        working_dir=clone_path,
    )

    # Ensure ruff is available — install if needed
    await _ensure_python_tools(clone_path, sandbox_cfg)

    # --- Lint ---
    lint_result = await run_command(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json", "--no-cache"],
        sandbox_cfg,
    )
    lint_passed, lint_issues = _parse_ruff_json(lint_result.stdout)

    # ruff exits 1 when lint issues found — that's expected
    if lint_result.returncode not in (0, 1):
        logger.warning("ruff_unexpected_exit", returncode=lint_result.returncode, stderr=lint_result.stderr[:200])

    # --- Tests ---
    test_result = await run_command(
        [sys.executable, "-m", "pytest", "--tb=short", "-q", "--no-header", "--timeout=60"],
        sandbox_cfg,
    )
    test_passed, total, passed_count, failed_count, skipped_count, test_failures = _parse_pytest_output(
        test_result.stdout + "\n" + test_result.stderr
    )

    overall_status = "success" if (lint_passed and test_passed) else ("partial" if (lint_passed or test_passed) else "failed")

    return LintAndTestResult(
        status=overall_status,
        language="python",
        lint_tool="ruff",
        lint_passed=lint_passed,
        lint_issues=lint_issues,
        lint_issue_count=len(lint_issues),
        test_tool="pytest",
        test_passed=test_passed,
        test_total=total,
        test_passed_count=passed_count,
        test_failed_count=failed_count,
        test_skipped_count=skipped_count,
        test_failures=test_failures,
        execution_time_ms=lint_result.duration_ms + test_result.duration_ms,
    )


async def _run_javascript(clone_path: str, cfg: SandboxConfig) -> LintAndTestResult:
    """Run eslint + jest on a JavaScript project (if configured)."""
    sandbox_cfg = SandboxConfig(
        timeout_seconds=cfg.timeout_seconds,
        max_output_bytes=cfg.max_output_bytes,
        working_dir=clone_path,
    )

    base = Path(clone_path)
    has_eslint_config = any(
        (base / f).exists()
        for f in [".eslintrc.js", ".eslintrc.json", ".eslintrc.yml", ".eslintrc", "eslint.config.js"]
    )
    has_jest = _package_has_script(clone_path, "test")

    lint_passed = True
    lint_issues: list[LintIssue] = []
    lint_tool = "none"

    if has_eslint_config:
        lint_tool = "eslint"
        eslint_result = await run_command(
            ["npx", "--yes", "eslint", ".", "--format", "json", "--no-eslintrc"],
            sandbox_cfg,
        )
        lint_passed, lint_issues = _parse_eslint_json(eslint_result.stdout)

    test_passed = True
    test_failures: list[TestFailure] = []
    test_tool = "none"
    total, passed_count, failed_count, skipped_count = 0, 0, 0, 0

    if has_jest:
        test_tool = "jest"
        jest_result = await run_command(
            ["npx", "--yes", "jest", "--json", "--passWithNoTests"],
            sandbox_cfg,
        )
        test_passed, total, passed_count, failed_count, skipped_count, test_failures = _parse_jest_json(jest_result.stdout)

    status = "success" if (lint_passed and test_passed) else "partial"

    return LintAndTestResult(
        status=status,
        language="javascript",
        lint_tool=lint_tool,
        lint_passed=lint_passed,
        lint_issues=lint_issues,
        lint_issue_count=len(lint_issues),
        test_tool=test_tool,
        test_passed=test_passed,
        test_total=total,
        test_passed_count=passed_count,
        test_failed_count=failed_count,
        test_skipped_count=skipped_count,
        test_failures=test_failures,
        notes="npm install not run — only static analysis performed." if not has_eslint_config else "",
    )


async def _ensure_python_tools(clone_path: str, cfg: SandboxConfig) -> None:
    """
    Ensure ruff and pytest are available in the current environment.
    Installs them if missing (they're dev tools, not repo dependencies).
    """
    import importlib.util
    needs = []
    if importlib.util.find_spec("ruff") is None:
        needs.append("ruff")
    if importlib.util.find_spec("pytest") is None:
        needs.append("pytest")
    if needs:
        logger.info("installing_tools", tools=needs)
        install_cfg = SandboxConfig(timeout_seconds=120, max_output_bytes=cfg.max_output_bytes, working_dir=clone_path)
        await run_command(
            [sys.executable, "-m", "pip", "install", "--quiet"] + needs,
            install_cfg,
        )


def _parse_ruff_json(stdout: str) -> tuple[bool, list[LintIssue]]:
    """
    Parse ruff --output-format json output.

    ruff outputs a JSON array of diagnostic objects:
    [{"filename": "...", "location": {"row": 1, "column": 1}, "code": "E501", "message": "..."}]
    """
    if not stdout.strip():
        return True, []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # ruff may output partial text before crash
        return True, []

    if not isinstance(data, list):
        return True, []

    issues = []
    for item in data:
        loc = item.get("location", {})
        issues.append(LintIssue(
            file=item.get("filename", ""),
            line=loc.get("row", 0),
            col=loc.get("column", 0),
            code=item.get("code", ""),
            message=item.get("message", ""),
            severity="error" if item.get("fix") is None else "warning",
        ))

    passed = len(issues) == 0
    return passed, issues


def _parse_pytest_output(output: str) -> tuple[bool, int, int, int, int, list[TestFailure]]:
    """
    Parse pytest -q output to extract test counts and failures.

    Returns: (passed, total, passed_count, failed_count, skipped_count, failures)
    Handles patterns like:
      "5 passed, 1 failed, 2 skipped in 1.23s"
      "FAILED tests/test_foo.py::test_bar - AssertionError: ..."
    """
    if not output.strip():
        return True, 0, 0, 0, 0, []

    # Check for no tests collected
    if "no tests ran" in output.lower() or "no tests were found" in output.lower():
        return True, 0, 0, 0, 0, []

    # Extract summary line: "N passed" / "N failed" / "N skipped"
    passed_count = _extract_int(r"(\d+) passed", output)
    failed_count = _extract_int(r"(\d+) failed", output)
    skipped_count = _extract_int(r"(\d+) skipped", output)
    error_count = _extract_int(r"(\d+) error", output)
    total = passed_count + failed_count + skipped_count + error_count

    # Extract individual failure descriptions
    failures: list[TestFailure] = []
    for m in re.finditer(r"FAILED\s+([\w/\.\-:]+)\s*-\s*(.+?)(?=\n(?:FAILED|PASSED|ERROR|\d+ )|$)", output, re.DOTALL):
        test_id = m.group(1).strip()
        msg = m.group(2).strip()[:200]
        # Extract file path from test id (tests/test_foo.py::test_bar → tests/test_foo.py)
        file_path = test_id.split("::")[0] if "::" in test_id else ""
        failures.append(TestFailure(test_id=test_id, message=msg, file=file_path))

    passed = failed_count == 0 and error_count == 0
    return passed, total, passed_count, failed_count, skipped_count, failures


def _parse_eslint_json(stdout: str) -> tuple[bool, list[LintIssue]]:
    """Parse eslint --format json output."""
    if not stdout.strip():
        return True, []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return True, []

    issues = []
    for file_result in data:
        filename = file_result.get("filePath", "")
        for msg in file_result.get("messages", []):
            severity = "error" if msg.get("severity") == 2 else "warning"
            issues.append(LintIssue(
                file=filename,
                line=msg.get("line", 0),
                col=msg.get("column", 0),
                code=msg.get("ruleId", ""),
                message=msg.get("message", ""),
                severity=severity,
            ))

    errors = [i for i in issues if i.severity == "error"]
    passed = len(errors) == 0
    return passed, issues


def _parse_jest_json(stdout: str) -> tuple[bool, int, int, int, int, list[TestFailure]]:
    """Parse jest --json output."""
    if not stdout.strip():
        return True, 0, 0, 0, 0, []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return True, 0, 0, 0, 0, []

    total = data.get("numTotalTests", 0)
    passed_count = data.get("numPassedTests", 0)
    failed_count = data.get("numFailedTests", 0)
    skipped_count = data.get("numPendingTests", 0)

    failures: list[TestFailure] = []
    for suite in data.get("testResults", []):
        for test in suite.get("testResults", []):
            if test.get("status") == "failed":
                failures.append(TestFailure(
                    test_id=test.get("fullName", ""),
                    message="; ".join(test.get("failureMessages", []))[:200],
                    file=suite.get("testFilePath", ""),
                ))

    passed = failed_count == 0
    return passed, total, passed_count, failed_count, skipped_count, failures


def _extract_int(pattern: str, text: str, default: int = 0) -> int:
    """Extract an integer from text using a regex pattern."""
    m = re.search(pattern, text)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            pass
    return default


def _package_has_script(clone_path: str, script_name: str) -> bool:
    """Check if package.json has a specific npm script."""
    try:
        import json as _json
        pkg_json = Path(clone_path) / "package.json"
        if not pkg_json.exists():
            return False
        data = _json.loads(pkg_json.read_text(encoding="utf-8"))
        return script_name in data.get("scripts", {})
    except Exception:
        return False
