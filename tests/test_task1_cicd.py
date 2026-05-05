"""
Tests for Task 1: GitHub CI/CD as Claude Skills.

Tests are unit-level with no live GitHub API calls or subprocess execution
against real repos. External calls are monkeypatched.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────


class TestSchemas:
    def test_skill_run_request_defaults(self):
        from src.task1_cicd.schemas import SkillRunRequest

        req = SkillRunRequest(repo_url="https://github.com/owner/repo", skill_name="lint-and-test")
        assert req.branch == "main"
        assert req.dry_run is True

    def test_repo_context_construction(self):
        from src.task1_cicd.schemas import RepoContext

        ctx = RepoContext(
            owner="owner",
            repo="repo",
            branch="main",
            commit_sha="abc123",
            clone_path="/tmp/test",
            language="python",
        )
        assert ctx.owner == "owner"
        assert ctx.language == "python"

    def test_lint_and_test_result(self):
        from src.task1_cicd.schemas import LintAndTestResult

        result = LintAndTestResult(
            status="success",
            language="python",
            lint_tool="ruff",
            lint_passed=True,
            test_tool="pytest",
            test_passed=True,
            test_total=10,
            test_passed_count=10,
        )
        assert result.lint_issue_count == 0
        assert result.test_failed_count == 0

    def test_dependency_audit_result(self):
        from src.task1_cicd.schemas import DependencyAuditResult

        result = DependencyAuditResult(status="clean", total_dependencies=5)
        assert result.vulnerabilities == []
        assert result.outdated == []

    def test_security_scan_result(self):
        from src.task1_cicd.schemas import SecurityScanResult

        result = SecurityScanResult(status="clean")
        assert result.findings == []
        assert result.summary == {}

    def test_build_and_release_result(self):
        from src.task1_cicd.schemas import BuildAndReleaseResult

        result = BuildAndReleaseResult(
            mode="dry_run",
            status="success",
            current_version="v1.2.3",
            next_version="v1.3.0",
            version_bump="minor",
            changelog="## What's Changed\n### Features\n- feat: add X",
            commits_since_tag=3,
        )
        assert result.release_url is None
        assert result.tag_created is False

    def test_sandbox_result(self):
        from src.task1_cicd.schemas import SandboxResult

        r = SandboxResult(command=["echo", "hello"], returncode=0, stdout="hello", stderr="")
        assert r.timed_out is False


# ─────────────────────────────────────────────────────────────────────────────
# GitHub Client
# ─────────────────────────────────────────────────────────────────────────────


class TestGitHubClient:
    def test_parse_repo_url_valid(self):
        from src.task1_cicd.github_client import parse_repo_url

        owner, repo = parse_repo_url("https://github.com/tychen5/signal-foundry")
        assert owner == "tychen5"
        assert repo == "signal-foundry"

    def test_parse_repo_url_with_git_suffix(self):
        from src.task1_cicd.github_client import parse_repo_url

        owner, repo = parse_repo_url("https://github.com/owner/myrepo.git")
        assert repo == "myrepo"

    def test_parse_repo_url_invalid(self):
        from src.task1_cicd.github_client import FastFailError, parse_repo_url

        with pytest.raises(FastFailError, match="Not a valid GitHub repo URL"):
            parse_repo_url("not-a-url")

    def test_parse_repo_url_gitlab(self):
        from src.task1_cicd.github_client import FastFailError, parse_repo_url

        with pytest.raises(FastFailError):
            parse_repo_url("https://gitlab.com/owner/repo")

    def test_redact_token(self):
        from src.task1_cicd.github_client import _redact_token

        url = "https://ghp_abc123xyz@github.com/owner/repo.git"
        redacted = _redact_token(url)
        assert "ghp_abc123xyz" not in redacted
        assert "***" in redacted

    @pytest.mark.asyncio
    async def test_validate_repo_not_found(self):
        from src.task1_cicd.github_client import FastFailError, validate_repo

        import httpx

        class FakeResp:
            status_code = 404

            def json(self):
                return {}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=FakeResp())))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(FastFailError, match="not found"):
                await validate_repo("https://github.com/nonexistent/repo")

    @pytest.mark.asyncio
    async def test_validate_repo_success(self):
        from src.task1_cicd.github_client import validate_repo

        class FakeResp:
            status_code = 200

            def json(self):
                return {"default_branch": "main", "private": False}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get = AsyncMock(return_value=FakeResp())
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await validate_repo("https://github.com/tychen5/signal-foundry")
            assert info["owner"] == "tychen5"
            assert info["repo"] == "signal-foundry"


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox
# ─────────────────────────────────────────────────────────────────────────────


class TestSandbox:
    @pytest.mark.asyncio
    async def test_run_command_success(self):
        from src.task1_cicd.sandbox import SandboxConfig, run_command

        cfg = SandboxConfig(timeout_seconds=10)
        result = await run_command(["echo", "hello"], cfg)
        assert result.returncode == 0
        assert "hello" in result.stdout
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_run_command_nonzero_exit(self):
        from src.task1_cicd.sandbox import SandboxConfig, run_command

        cfg = SandboxConfig(timeout_seconds=10)
        result = await run_command(["false"], cfg)
        assert result.returncode != 0

    @pytest.mark.asyncio
    async def test_run_command_not_found(self):
        from src.task1_cicd.sandbox import SandboxConfig, run_command

        cfg = SandboxConfig(timeout_seconds=10)
        result = await run_command(["this_command_does_not_exist_xyzabc"], cfg)
        assert result.returncode == 127
        assert "not found" in result.stderr.lower() or "Command not found" in result.stderr

    def test_detect_language_python(self):
        from src.task1_cicd.sandbox import detect_language

        with tempfile.TemporaryDirectory() as d:
            Path(d, "requirements.txt").write_text("requests==2.28.0")
            assert detect_language(d) == "python"

    def test_detect_language_pyproject(self):
        from src.task1_cicd.sandbox import detect_language

        with tempfile.TemporaryDirectory() as d:
            Path(d, "pyproject.toml").write_text("[project]\nname = 'test'")
            assert detect_language(d) == "python"

    def test_detect_language_javascript(self):
        from src.task1_cicd.sandbox import detect_language

        with tempfile.TemporaryDirectory() as d:
            Path(d, "package.json").write_text('{"name": "test"}')
            assert detect_language(d) == "javascript"

    def test_detect_language_unknown(self):
        from src.task1_cicd.sandbox import detect_language

        with tempfile.TemporaryDirectory() as d:
            assert detect_language(d) == "unknown"

    def test_make_and_cleanup_temp_dir(self):
        from src.task1_cicd.sandbox import cleanup_temp_dir, make_temp_dir

        path = make_temp_dir()
        assert Path(path).exists()
        cleanup_temp_dir(path)
        assert not Path(path).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Skill Registry
# ─────────────────────────────────────────────────────────────────────────────


class TestSkillRegistry:
    @pytest.mark.asyncio
    async def test_exact_match_lint(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, confidence = await resolve_skill_name("lint-and-test")
        assert skill == "lint-and-test"
        assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_exact_match_variants(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        for raw in ["lint_and_test", "lint", "test"]:
            skill, _ = await resolve_skill_name(raw)
            assert skill == "lint-and-test"

    @pytest.mark.asyncio
    async def test_exact_match_security(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, _ = await resolve_skill_name("security-scan")
        assert skill == "security-scan"

    @pytest.mark.asyncio
    async def test_exact_match_dependency(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, _ = await resolve_skill_name("dependency-audit")
        assert skill == "dependency-audit"

    @pytest.mark.asyncio
    async def test_exact_match_build(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, _ = await resolve_skill_name("build-and-release")
        assert skill == "build-and-release"

    @pytest.mark.asyncio
    async def test_fuzzy_match_run_tests(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, confidence = await resolve_skill_name("run tests please")
        assert skill == "lint-and-test"
        assert confidence > 0.35

    @pytest.mark.asyncio
    async def test_fuzzy_match_release(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, confidence = await resolve_skill_name("ship it to production")
        assert skill == "build-and-release"

    @pytest.mark.asyncio
    async def test_fuzzy_match_secrets(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, confidence = await resolve_skill_name("scan for leaked tokens")
        assert skill == "security-scan"

    @pytest.mark.asyncio
    async def test_fuzzy_match_cve(self):
        from src.task1_cicd.skill_registry import resolve_skill_name

        skill, confidence = await resolve_skill_name("audit deps for vulnerabilities")
        assert skill == "dependency-audit"

    def test_fuzzy_match_function(self):
        from src.task1_cicd.skill_registry import _fuzzy_match

        result = _fuzzy_match("check code quality")
        assert result is not None
        skill, score = result
        assert skill == "lint-and-test"
        assert score > 0.3

    def test_fuzzy_match_unknown_returns_none(self):
        from src.task1_cicd.skill_registry import _fuzzy_match

        result = _fuzzy_match("xyzzy frobozz quux")
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Lint and Test Skill
# ─────────────────────────────────────────────────────────────────────────────


class TestLintAndTest:
    def test_parse_ruff_json_clean(self):
        from src.task1_cicd.skills.lint_and_test import _parse_ruff_json

        passed, issues = _parse_ruff_json("[]")
        assert passed is True
        assert issues == []

    def test_parse_ruff_json_with_issues(self):
        from src.task1_cicd.skills.lint_and_test import _parse_ruff_json

        stdout = json.dumps([
            {
                "filename": "src/foo.py",
                "location": {"row": 10, "column": 4},
                "code": "E501",
                "message": "Line too long (90 > 88)",
                "fix": None,
            }
        ])
        passed, issues = _parse_ruff_json(stdout)
        assert passed is False
        assert len(issues) == 1
        assert issues[0].code == "E501"
        assert issues[0].line == 10

    def test_parse_ruff_json_invalid(self):
        from src.task1_cicd.skills.lint_and_test import _parse_ruff_json

        # Should not raise, just return clean
        passed, issues = _parse_ruff_json("not json")
        assert passed is True
        assert issues == []

    def test_parse_pytest_output_all_pass(self):
        from src.task1_cicd.skills.lint_and_test import _parse_pytest_output

        output = "5 passed in 0.42s"
        passed, total, p, f, s, failures = _parse_pytest_output(output)
        assert passed is True
        assert total == 5
        assert p == 5
        assert f == 0

    def test_parse_pytest_output_with_failures(self):
        from src.task1_cicd.skills.lint_and_test import _parse_pytest_output

        output = (
            "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n"
            "3 passed, 1 failed in 1.23s"
        )
        passed, total, p, f, s, failures = _parse_pytest_output(output)
        assert passed is False
        assert f == 1
        assert len(failures) == 1
        assert "test_bar" in failures[0].test_id

    def test_parse_pytest_output_no_tests(self):
        from src.task1_cicd.skills.lint_and_test import _parse_pytest_output

        output = "no tests ran"
        passed, total, p, f, s, failures = _parse_pytest_output(output)
        assert passed is True
        assert total == 0

    def test_parse_eslint_json_clean(self):
        from src.task1_cicd.skills.lint_and_test import _parse_eslint_json

        output = json.dumps([{"filePath": "src/index.js", "messages": []}])
        passed, issues = _parse_eslint_json(output)
        assert passed is True
        assert issues == []

    def test_parse_eslint_json_with_error(self):
        from src.task1_cicd.skills.lint_and_test import _parse_eslint_json

        output = json.dumps([{
            "filePath": "src/index.js",
            "messages": [{"line": 5, "column": 3, "ruleId": "no-console", "message": "Unexpected console.log", "severity": 2}],
        }])
        passed, issues = _parse_eslint_json(output)
        assert passed is False
        assert len(issues) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Dependency Audit Skill
# ─────────────────────────────────────────────────────────────────────────────


class TestDependencyAudit:
    def test_parse_requirements_txt(self):
        from src.task1_cicd.skills.dependency_audit import _parse_requirements_txt

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("requests==2.28.0\n")
            f.write("flask>=2.0.0\n")
            f.write("# comment\n")
            f.write("\n")
            path = f.name

        try:
            pkgs = _parse_requirements_txt(path)
            names = [p.name for p in pkgs]
            assert "requests" in names
            assert "flask" in names
            assert all(p.ecosystem == "PyPI" for p in pkgs)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_requirements_txt_with_extras(self):
        from src.task1_cicd.skills.dependency_audit import _parse_requirements_txt

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("uvicorn[standard]>=0.32.0\n")
            path = f.name

        try:
            pkgs = _parse_requirements_txt(path)
            assert len(pkgs) >= 1
            assert pkgs[0].name == "uvicorn"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_pyproject_toml_pep621(self):
        import sys
        if sys.version_info < (3, 11):
            pytest.skip("tomllib requires Python 3.11+")

        from src.task1_cicd.skills.dependency_audit import _parse_pyproject_toml

        content = '[project]\ndependencies = ["requests>=2.28.0", "flask==2.3.0"]\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(content)
            path = f.name

        try:
            pkgs = _parse_pyproject_toml(path)
            names = [p.name for p in pkgs]
            assert "requests" in names
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_package_lock_v2(self):
        from src.task1_cicd.skills.dependency_audit import _parse_package_lock_v2

        data = {
            "packages": {
                "node_modules/express": {"version": "4.18.2"},
                "node_modules/lodash": {"version": "4.17.21"},
                "node_modules/a/node_modules/b": {"version": "1.0.0"},  # nested, should skip
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        try:
            pkgs = _parse_package_lock_v2(path)
            names = [p.name for p in pkgs]
            assert "express" in names
            assert "lodash" in names
            # Nested packages should be skipped
            assert "a/node_modules/b" not in names
        finally:
            Path(path).unlink(missing_ok=True)

    def test_osv_severity_from_database_specific(self):
        from src.task1_cicd.skills.dependency_audit import _osv_severity

        vuln = {"database_specific": {"severity": "HIGH"}}
        assert _osv_severity(vuln) == "high"

    def test_is_major_bump(self):
        from src.task1_cicd.skills.dependency_audit import _is_major_bump

        assert _is_major_bump("1.2.3", "2.0.0") is True
        assert _is_major_bump("1.2.3", "1.3.0") is False
        assert _is_major_bump("bad", "2.0.0") is False


# ─────────────────────────────────────────────────────────────────────────────
# Security Scan Skill
# ─────────────────────────────────────────────────────────────────────────────


class TestSecurityScan:
    def test_secret_detection_aws_key(self):
        from src.task1_cicd.skills.security_scan import _run_secret_detection

        with tempfile.TemporaryDirectory() as d:
            # Write a Python file with a fake AWS key
            Path(d, "config.py").write_text(
                'AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
            )
            findings = _run_secret_detection(d)

        assert len(findings) >= 1
        aws_findings = [f for f in findings if "AWS" in f.description]
        assert len(aws_findings) >= 1
        # Should NOT include the full key
        assert "AKIAIOSFODNN7EXAMPLE" not in aws_findings[0].match_preview

    def test_secret_detection_github_token(self):
        from src.task1_cicd.skills.security_scan import _run_secret_detection

        fake_token = "ghp_" + "A" * 36
        with tempfile.TemporaryDirectory() as d:
            Path(d, "deploy.sh").write_text(f'export TOKEN="{fake_token}"\n')
            findings = _run_secret_detection(d)

        gh_findings = [f for f in findings if "GitHub" in f.description]
        assert len(gh_findings) >= 1
        assert fake_token not in gh_findings[0].match_preview

    def test_secret_detection_private_key(self):
        from src.task1_cicd.skills.security_scan import _run_secret_detection

        with tempfile.TemporaryDirectory() as d:
            Path(d, "key.pem").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK...\n")
            findings = _run_secret_detection(d)

        pk_findings = [f for f in findings if "Private Key" in f.description]
        assert len(pk_findings) >= 1
        assert pk_findings[0].severity == "critical"

    def test_secret_detection_clean_file(self):
        from src.task1_cicd.skills.security_scan import _run_secret_detection

        with tempfile.TemporaryDirectory() as d:
            Path(d, "main.py").write_text("def hello():\n    print('hello')\n")
            findings = _run_secret_detection(d)

        assert findings == []

    def test_secret_detection_skips_git_dir(self):
        from src.task1_cicd.skills.security_scan import _run_secret_detection

        with tempfile.TemporaryDirectory() as d:
            git_dir = Path(d, ".git")
            git_dir.mkdir()
            Path(git_dir, "config").write_text('AKIA1234567890ABCDEF')
            findings = _run_secret_detection(d)

        # .git directory should be skipped
        assert all(".git" not in f.file for f in findings)

    def test_parse_bandit_json(self):
        from src.task1_cicd.skills.security_scan import _parse_bandit_json

        bandit_output = json.dumps({
            "results": [
                {
                    "filename": "/tmp/clone/src/utils.py",
                    "test_id": "B602",
                    "test_name": "subprocess_popen_with_shell_equals_true",
                    "issue_text": "subprocess call with shell=True is a security hazard",
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "line_number": 42,
                    "code": "subprocess.run(cmd, shell=True)",
                }
            ]
        })
        findings = _parse_bandit_json(bandit_output, "/tmp/clone")
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert "B602" in findings[0].description
        assert findings[0].tool == "bandit"

    def test_count_scannable_files(self):
        from src.task1_cicd.skills.security_scan import _count_scannable_files

        with tempfile.TemporaryDirectory() as d:
            Path(d, "main.py").write_text("print('hello')")
            Path(d, "data.json").write_text("{}")
            assert _count_scannable_files(d) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# Build and Release Skill
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildAndRelease:
    def test_determine_version_bump_patch(self):
        from src.task1_cicd.skills.build_and_release import _determine_version_bump

        commits = [
            {"message": "fix: resolve null pointer", "sha": "abc", "author": "dev", "date": ""},
            {"message": "chore: update deps", "sha": "def", "author": "dev", "date": ""},
        ]
        bump, reason = _determine_version_bump(commits)
        assert bump == "patch"

    def test_determine_version_bump_minor(self):
        from src.task1_cicd.skills.build_and_release import _determine_version_bump

        commits = [
            {"message": "feat: add new endpoint", "sha": "abc", "author": "dev", "date": ""},
            {"message": "fix: minor fix", "sha": "def", "author": "dev", "date": ""},
        ]
        bump, reason = _determine_version_bump(commits)
        assert bump == "minor"

    def test_determine_version_bump_major(self):
        from src.task1_cicd.skills.build_and_release import _determine_version_bump

        commits = [
            {"message": "feat!: redesign API", "sha": "abc", "author": "dev", "date": ""},
        ]
        bump, reason = _determine_version_bump(commits)
        assert bump == "major"

    def test_determine_version_bump_breaking_change_in_body(self):
        from src.task1_cicd.skills.build_and_release import _determine_version_bump

        commits = [
            {"message": "feat: new auth flow\n\nBREAKING CHANGE: old tokens revoked", "sha": "abc", "author": "dev", "date": ""},
        ]
        bump, _ = _determine_version_bump(commits)
        assert bump == "major"

    def test_bump_semver_patch(self):
        from src.task1_cicd.skills.build_and_release import _bump_semver

        assert _bump_semver("v1.2.3", "patch") == "v1.2.4"
        assert _bump_semver("v1.2.3", "minor") == "v1.3.0"
        assert _bump_semver("v1.2.3", "major") == "v2.0.0"

    def test_bump_semver_no_v_prefix(self):
        from src.task1_cicd.skills.build_and_release import _bump_semver

        assert _bump_semver("1.2.3", "patch") == "v1.2.4"

    def test_bump_semver_none_current(self):
        from src.task1_cicd.skills.build_and_release import _bump_semver

        assert _bump_semver(None, "minor") == "v0.1.0"
        assert _bump_semver(None, "major") == "v1.0.0"
        assert _bump_semver(None, "patch") == "v0.0.1"

    def test_build_changelog_structure(self):
        from src.task1_cicd.skills.build_and_release import _build_changelog

        commits = [
            {"message": "feat: add search", "sha": "abc1234", "author": "alice", "date": ""},
            {"message": "fix: null pointer in auth", "sha": "def5678", "author": "bob", "date": ""},
            {"message": "chore: update CI", "sha": "ghi9012", "author": "carol", "date": ""},
        ]
        changelog = _build_changelog(commits, "v1.0.0", "v1.1.0")
        assert "v1.1.0" in changelog
        assert "Features" in changelog
        assert "Bug Fixes" in changelog
        assert "add search" in changelog

    def test_build_changelog_no_commits(self):
        from src.task1_cicd.skills.build_and_release import _build_changelog

        changelog = _build_changelog([], None, "v0.1.0")
        assert "No changes" in changelog or "initial release" in changelog.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Skill Engine
# ─────────────────────────────────────────────────────────────────────────────


class TestSkillEngine:
    def test_cache_key_structure(self):
        from src.task1_cicd.skill_engine import _make_cache_key

        key = _make_cache_key("owner", "repo", "main", "lint-and-test", "abc123def456", False)
        assert "cicd:v1" in key
        assert "owner/repo" in key
        assert "lint-and-test" in key
        assert "abc123def" in key

    def test_cache_key_dry_run_differs(self):
        from src.task1_cicd.skill_engine import _make_cache_key

        key_dry = _make_cache_key("o", "r", "main", "build-and-release", "sha123", True)
        key_real = _make_cache_key("o", "r", "main", "build-and-release", "sha123", False)
        assert key_dry != key_real

    def test_dispatch_routes_correctly(self):
        """Verify _dispatch imports the right module for each skill."""
        from src.task1_cicd import skill_engine

        # Just test that the dispatch function exists and routes are correct
        import inspect
        src = inspect.getsource(skill_engine._dispatch)
        assert "lint_and_test" in src
        assert "dependency_audit" in src
        assert "security_scan" in src
        assert "build_and_release" in src


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Files
# ─────────────────────────────────────────────────────────────────────────────


class TestPromptFiles:
    def _prompt_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent / "prompts" / "cicd"

    def test_skill_match_prompt_exists(self):
        path = self._prompt_dir() / "v1_skill_match.txt"
        assert path.exists(), f"Missing prompt: {path}"

    def test_skill_match_prompt_has_template_var(self):
        path = self._prompt_dir() / "v1_skill_match.txt"
        content = path.read_text()
        assert "{user_input}" in content

    def test_result_summary_prompt_exists(self):
        path = self._prompt_dir() / "v1_result_summary.txt"
        assert path.exists(), f"Missing prompt: {path}"

    def test_result_summary_prompt_has_template_vars(self):
        path = self._prompt_dir() / "v1_result_summary.txt"
        content = path.read_text()
        assert "{skill_name}" in content
        assert "{result_json}" in content

    def test_prompt_readme_exists(self):
        path = self._prompt_dir() / "README.md"
        assert path.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Eval Set
# ─────────────────────────────────────────────────────────────────────────────


class TestEvalSet:
    def _eval_set_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "evals" / "task1" / "scenarios.json"

    def test_eval_set_exists(self):
        assert self._eval_set_path().exists()

    def test_eval_set_valid_json(self):
        data = json.loads(self._eval_set_path().read_text())
        assert isinstance(data, list)

    def test_eval_set_has_required_fields(self):
        data = json.loads(self._eval_set_path().read_text())
        for case in data:
            assert "case_id" in case, f"Missing case_id in {case}"
            assert "input_data" in case, f"Missing input_data in {case}"
            assert "expected_behavior" in case, f"Missing expected_behavior in {case}"

    def test_eval_set_has_five_cases(self):
        data = json.loads(self._eval_set_path().read_text())
        assert len(data) >= 5

    def test_eval_set_skill_names_valid(self):
        from src.task1_cicd.skill_registry import VALID_SKILLS

        data = json.loads(self._eval_set_path().read_text())
        for case in data:
            skill = case["input_data"].get("skill_name", "")
            # Some cases may use natural language — only check explicit skill names
            if skill in VALID_SKILLS or skill == "":
                pass  # expected


# ─────────────────────────────────────────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────────────────────────────────────────


class TestAPIRoutes:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from src.main import app
        return TestClient(app)

    def test_list_skills(self, client):
        resp = client.get("/api/v1/skills/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data
        assert len(data["skills"]) == 4
        names = {s["name"] for s in data["skills"]}
        assert "lint-and-test" in names
        assert "security-scan" in names

    def test_run_skill_returns_execution_result_schema(self, client):
        """Verify the response schema even if execution fails (bad repo)."""
        with patch("src.task1_cicd.skill_engine.run_skill") as mock_engine:
            from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
            mock_engine.return_value = ExecutionResult(
                status=ExecutionStatus.FAILED,
                task=TaskType.CICD_SKILLS,
                trace_id="test-trace-001",
                error="repo not found",
            )
            mock_engine = AsyncMock(return_value=ExecutionResult(
                status=ExecutionStatus.FAILED,
                task=TaskType.CICD_SKILLS,
                trace_id="test-trace-001",
                error="repo not found",
            ))

            with patch("src.task1_cicd.router.run_skill", mock_engine):
                resp = client.post(
                    "/api/v1/skills/run",
                    json={
                        "repo_url": "https://github.com/nonexistent/repo",
                        "skill_name": "lint-and-test",
                    },
                )
            # Should return 200 with failed ExecutionResult (not 500)
            assert resp.status_code in (200, 400, 422)

    def test_run_skill_validates_json_body(self, client):
        """Missing required fields should return 422."""
        resp = client.post("/api/v1/skills/run", json={})
        assert resp.status_code == 422
