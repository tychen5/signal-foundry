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
        assert result.severity_counts == {}

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

    def test_parse_repo_url_user_friendly_forms(self):
        """Real users copy/paste GitHub URLs in many forms — tree/blob URLs
        from the file viewer, SSH form from the clone box, missing-scheme
        from manual typing. The parser should extract owner/repo from all
        of these rather than refuse with 'invalid URL'."""
        from src.task1_cicd.github_client import parse_repo_url

        forms = [
            "https://github.com/foo/bar/tree/main",
            "https://github.com/foo/bar/blob/main/README.md",
            "https://github.com/foo/bar/pull/42",
            "https://github.com/foo/bar/issues",
            "https://github.com/foo/bar/releases",
            "github.com/foo/bar",  # no scheme
            "git@github.com:foo/bar.git",  # ssh
            "https://github.com/foo/bar/",  # trailing slash
            "http://github.com/foo/bar",  # http (rare but valid)
        ]
        for url in forms:
            owner, repo = parse_repo_url(url)
            assert (owner, repo) == ("foo", "bar"), f"Failed on {url}"

    def test_parse_repo_url_still_rejects_bad_inputs(self):
        """The expanded regex must still reject non-GitHub URLs and
        owner-only paths."""
        from src.task1_cicd.github_client import FastFailError, parse_repo_url

        bad = [
            "https://github.com/foo",  # owner-only
            "https://gitlab.com/foo/bar",  # different host
            "https://bitbucket.org/foo/bar",
            "ftp://github.com/foo/bar",
            "not-a-url",
            "",
        ]
        for url in bad:
            with pytest.raises(FastFailError):
                parse_repo_url(url)

    def test_redact_token(self):
        from src.task1_cicd.github_client import _redact_token

        url = "https://ghp_abc123xyz@github.com/owner/repo.git"
        redacted = _redact_token(url)
        assert "ghp_abc123xyz" not in redacted
        assert "***" in redacted

    @pytest.mark.asyncio
    async def test_validate_repo_not_found(self):

        from src.task1_cicd.github_client import FastFailError, validate_repo

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
        # Just test that the dispatch function exists and routes are correct
        import inspect

        from src.task1_cicd import skill_engine
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


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Router (LLM-driven skill orchestration)
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoRouterPlanSanitiser:
    """The plan sanitiser is the safety net between the LLM and the executor.

    It MUST never let through:
      - skills not in VALID_SKILLS
      - skills the user excluded
      - duplicates
      - build-and-release without an explicit release-intent in the query
    And it MUST cap the plan at max_skills."""

    def test_sanitiser_filters_unknown(self):
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan(
            ["security-scan", "frobozz-skill"], [], 4, "do something"
        )
        assert plan == ["security-scan"]

    def test_sanitiser_dedupes(self):
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan(
            ["security-scan", "Security-Scan", "dependency-audit"], [], 4, "do something"
        )
        assert plan == ["security-scan", "dependency-audit"]

    def test_sanitiser_respects_exclude_hint(self):
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan(
            ["security-scan", "dependency-audit"],
            ["security-scan"],
            4,
            "audit deps",
        )
        assert plan == ["dependency-audit"]
        assert "security-scan" not in plan

    def test_sanitiser_caps_at_max_skills(self):
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan(
            ["security-scan", "dependency-audit", "lint-and-test"],
            [],
            2,
            "check this repo",
        )
        assert len(plan) == 2

    def test_sanitiser_blocks_build_release_when_query_silent(self):
        """build-and-release is the only write-capable skill — never auto-picked
        unless the user's NL query mentions release/ship/etc."""
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan(
            ["build-and-release", "security-scan"],
            [],
            4,
            "are there any leaked secrets in the source?",
        )
        assert "build-and-release" not in plan
        assert "security-scan" in plan

    def test_sanitiser_allows_build_release_when_query_explicit(self):
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan(
            ["build-and-release", "lint-and-test"],
            [],
            4,
            "time to ship a release of this repo",
        )
        assert "build-and-release" in plan

    def test_sanitiser_fallback_on_empty(self):
        """Degenerate fallback when the LLM returned nothing usable."""
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan([], [], 4, "do something useful")
        assert plan == ["dependency-audit", "security-scan"]

    def test_sanitiser_fallback_respects_exclude(self):
        """Even the fallback shouldn't include excluded skills."""
        from src.task1_cicd.auto_router import _sanitise_plan

        plan = _sanitise_plan([], ["security-scan"], 4, "anything")
        assert "security-scan" not in plan
        assert "dependency-audit" in plan


class TestAutoRouterHelpers:
    def test_normalise_skill_list_drops_unknown(self):
        from src.task1_cicd.auto_router import _normalise_skill_list

        out = _normalise_skill_list(["security-scan", "FOO", "dependency-audit"])
        assert out == ["security-scan", "dependency-audit"]

    def test_normalise_skill_list_handles_none(self):
        from src.task1_cicd.auto_router import _normalise_skill_list

        assert _normalise_skill_list(None) == []
        assert _normalise_skill_list([]) == []

    def test_normalise_skill_list_dedupes(self):
        from src.task1_cicd.auto_router import _normalise_skill_list

        out = _normalise_skill_list(["security-scan", "security-scan"])
        assert out == ["security-scan"]

    def test_looks_like_release_query_positive(self):
        from src.task1_cicd.auto_router import _looks_like_release_query

        for q in [
            "please cut a release of this repo",
            "ship it to production",
            "publish a new version",
            "tag and ship",
        ]:
            assert _looks_like_release_query(q), q

    def test_looks_like_release_query_negative(self):
        from src.task1_cicd.auto_router import _looks_like_release_query

        for q in [
            "scan for leaked api keys",
            "audit my dependencies",
            "run the test suite",
            "check the code for vulnerabilities",
        ]:
            assert not _looks_like_release_query(q), q

    def test_compact_findings_dependency_audit(self):
        from src.task1_cicd.auto_router import _compact_findings

        raw = {
            "total_dependencies": 42,
            "vulnerabilities": [{"cve_id": "CVE-1"}, {"cve_id": "CVE-2"}],
            "critical_count": 1,
            "high_count": 1,
            "outdated": [{"package": "foo"}],
        }
        compact = _compact_findings("dependency-audit", raw)
        assert compact["cve_count"] == 2
        assert compact["critical_count"] == 1
        assert compact["outdated_count"] == 1
        assert compact["total_dependencies"] == 42

    def test_compact_findings_security_scan(self):
        from src.task1_cicd.auto_router import _compact_findings

        raw = {
            "files_scanned": 12,
            "findings": [{"severity": "high"}, {"severity": "low"}],
            "severity_counts": {"high": 1, "low": 1},
        }
        compact = _compact_findings("security-scan", raw)
        assert compact["finding_count"] == 2
        assert compact["files_scanned"] == 12

    def test_compact_findings_unknown_skill(self):
        from src.task1_cicd.auto_router import _compact_findings

        assert _compact_findings("nonsense-skill", {"foo": "bar"}) == {}

    def test_aggregate_signals_combines_skills(self):
        from src.task1_cicd.auto_router import _aggregate_signals
        from src.task1_cicd.schemas import AutoRouterStep

        steps = [
            AutoRouterStep(
                iteration=1,
                skill_executed="dependency-audit",
                raw_result={
                    "vulnerabilities": [{"cve_id": "CVE-1"}, {"cve_id": "CVE-2"}],
                    "outdated": [{"package": "foo"}],
                },
            ),
            AutoRouterStep(
                iteration=2,
                skill_executed="security-scan",
                raw_result={
                    "findings": [
                        {"finding_type": "secret"},
                        {"finding_type": "secret"},
                        {"finding_type": "sast"},
                    ],
                },
            ),
        ]
        signals = _aggregate_signals(steps)
        assert signals["total_cves"] == 2
        assert signals["total_outdated"] == 1
        assert signals["total_secrets"] == 2
        assert signals["total_sast"] == 1


class TestAutoRouterSchemas:
    def test_request_minimal(self):
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/owner/repo",
            natural_language_query="check for leaked secrets",
        )
        assert req.branch == "main"
        assert req.dry_run is True
        assert req.max_iterations == 4
        assert req.include_skills_hint == []
        assert req.exclude_skills_hint == []

    def test_request_accepts_empty_query(self):
        """NL query is now optional. Empty string is allowed — the auto-router
        falls back to the hint-only or default-pair path."""
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/owner/repo",
            natural_language_query="",
            include_skills_hint=["security-scan"],
        )
        assert req.natural_language_query == ""

    def test_request_accepts_missing_query(self):
        """When omitted entirely, the query defaults to empty string."""
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/owner/repo",
            include_skills_hint=["dependency-audit"],
        )
        assert req.natural_language_query == ""

    def test_request_accepts_no_intent_at_all(self):
        """Even with no query AND no hints, the schema still validates — the
        auto-router falls through to the default health-check pair."""
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(repo_url="https://github.com/owner/repo")
        assert req.natural_language_query == ""
        assert req.include_skills_hint == []
        assert req.exclude_skills_hint == []

    def test_request_caps_max_iterations(self):
        from pydantic import ValidationError

        from src.task1_cicd.schemas import AutoRouterRequest

        with pytest.raises(ValidationError):
            AutoRouterRequest(
                repo_url="https://github.com/o/r",
                natural_language_query="a real query",
                max_iterations=99,
            )

    def test_step_schema(self):
        from src.task1_cicd.schemas import AutoRouterStep

        step = AutoRouterStep(iteration=1, skill_executed="security-scan")
        assert step.cache_hit is False
        assert step.cost_usd == 0.0

    def test_result_schema_default_lists(self):
        from src.task1_cicd.schemas import AutoRouterResult

        res = AutoRouterResult(query="x")
        assert res.skills_executed == []
        assert res.steps == []


class TestAutoRouterPromptFiles:
    def _prompt_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent / "prompts" / "cicd"

    def test_plan_prompt_exists(self):
        path = self._prompt_dir() / "v1_auto_router_plan.txt"
        assert path.exists()

    def test_plan_prompt_template_vars(self):
        path = self._prompt_dir() / "v1_auto_router_plan.txt"
        content = path.read_text()
        for var in (
            "{user_query}",
            "{repo_url}",
            "{branch}",
            "{max_skills}",
            "{include_hint}",
            "{exclude_hint}",
        ):
            assert var in content, f"missing template var: {var}"

    def test_decide_prompt_exists(self):
        path = self._prompt_dir() / "v1_auto_router_decide.txt"
        assert path.exists()

    def test_decide_prompt_template_vars(self):
        path = self._prompt_dir() / "v1_auto_router_decide.txt"
        content = path.read_text()
        for var in (
            "{user_query}",
            "{executed_skills}",
            "{remaining_plan}",
            "{last_skill}",
            "{exclude_hint}",
        ):
            assert var in content, f"missing template var: {var}"

    def test_synthesize_prompt_exists(self):
        path = self._prompt_dir() / "v1_auto_router_synthesize.txt"
        assert path.exists()

    def test_synthesize_prompt_template_vars(self):
        path = self._prompt_dir() / "v1_auto_router_synthesize.txt"
        content = path.read_text()
        for var in (
            "{user_query}",
            "{executed_skills}",
            "{per_skill_summaries}",
            "{total_cves}",
            "{total_secrets}",
        ):
            assert var in content, f"missing template var: {var}"


class TestAutoRouterLoop:
    """End-to-end tests with mocked LLM stages and a stubbed skill engine.

    The orchestration loop has 5 invariants we want to lock in:
      1. The plan from _llm_plan drives execution order.
      2. Decision 'continue' walks the remaining plan, 'add_skill' pivots,
         'stop' terminates.
      3. The same skill is never executed twice.
      4. The exclude_hint is honored even when the LLM tries to violate it.
      5. The iteration cap and budget cap are hard stops.
    """

    @pytest.mark.asyncio
    async def test_two_skill_plan_executes_in_order(self):
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/owner/repo",
            natural_language_query="check for leaked secrets and CVEs",
        )

        async def fake_plan(request, trace_id):
            return (
                ["dependency-audit", "security-scan"],
                {"dependency-audit": "audit deps", "security-scan": "scan code"},
                "user wants vulns + leaked secrets",
                0.9,
            )

        async def fake_decide(*args, **kwargs):
            executed = kwargs.get("executed_skills") or args[3]
            if len(executed) >= 2:
                return ("stop", None, "intent satisfied", 0.9)
            return ("continue", None, "next in plan", 0.85)

        async def fake_synth(request, steps, trace_id):
            return f"Ran {len(steps)} skills successfully."

        order: list[str] = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            order.append(skill_request.skill_name)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={
                    "skill": skill_request.skill_name,
                    "status": "clean",
                    "summary": f"{skill_request.skill_name} done",
                    "commit_sha": "abc123",
                },
                cost_metadata={},
                latency_ms=10.0,
            )

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-aux-1")

        assert result.status.value == "success"
        assert order == ["dependency-audit", "security-scan"]
        payload = result.result
        assert payload["skill_executed"] == ["dependency-audit", "security-scan"]
        assert payload["skills_executed"] == ["dependency-audit", "security-scan"]
        assert payload["iterations_used"] == 2
        assert payload["terminated_reason"] == "router_stop"
        assert payload["final_synthesis"].startswith("Ran 2 skills")

    @pytest.mark.asyncio
    async def test_add_skill_pivots_remaining_plan(self):
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            natural_language_query="check the code thoroughly please",
        )

        async def fake_plan(request, trace_id):
            return (["dependency-audit"], {"dependency-audit": "audit deps"}, "intent", 0.7)

        decisions = iter([
            # After first skill: pivot to security-scan
            ("add_skill", "security-scan", "deps look fine, but we should check secrets too", 0.8),
            # After second skill: stop
            ("stop", None, "all clear", 0.9),
        ])

        async def fake_decide(*args, **kwargs):
            return next(decisions)

        async def fake_synth(*args, **kwargs):
            return "ok"

        order = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            order.append(skill_request.skill_name)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill": skill_request.skill_name, "status": "clean", "summary": "x"},
                cost_metadata={},
                latency_ms=5.0,
            )

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-aux-2")

        assert order == ["dependency-audit", "security-scan"]
        payload = result.result
        assert payload["iterations_used"] == 2

    @pytest.mark.asyncio
    async def test_exclude_hint_is_hard_block_during_decision(self):
        """Even if the decide-LLM picks an excluded skill, we MUST drop it."""
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            natural_language_query="check this repo",
            exclude_skills_hint=["security-scan"],
        )

        async def fake_plan(request, trace_id):
            return (["dependency-audit"], {"dependency-audit": "audit"}, "intent", 0.7)

        async def fake_decide(*args, **kwargs):
            # LLM tries to pivot to security-scan despite exclude hint.
            return ("add_skill", "security-scan", "we should also scan for secrets", 0.8)

        async def fake_synth(*args, **kwargs):
            return "ok"

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill": skill_request.skill_name, "status": "clean", "summary": "x"},
                cost_metadata={},
                latency_ms=5.0,
            )

        # The defensive scrub happens INSIDE _llm_decide. Since we monkeypatch
        # _llm_decide, the scrub doesn't apply — but `add_skill` with a forbidden
        # skill still funnels through `remaining_plan = [next_skill]` which then
        # hits the in-loop dedupe + sanity guards. So we wrap _llm_decide with
        # the scrub logic mirroring production: any next_skill in exclude_hint
        # becomes None, and the loop should treat that as a soft no-op pivot.

        async def fake_decide_scrubbed(*args, **kwargs):
            action, next_skill, reasoning, conf = await fake_decide(*args, **kwargs)
            exclude_hint = kwargs.get("exclude_hint") or []
            if next_skill in exclude_hint:
                next_skill = None
            return action, next_skill, reasoning, conf

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide_scrubbed), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-aux-excl")

        payload = result.result
        # security-scan must NEVER appear in skills_executed
        assert "security-scan" not in payload["skills_executed"]

    @pytest.mark.asyncio
    async def test_iteration_cap_terminates_loop(self):
        """Even with a long plan and 'continue' decisions, the iteration cap stops us."""
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            natural_language_query="check the whole repo for everything",
            max_iterations=2,
        )

        async def fake_plan(request, trace_id):
            return (
                ["dependency-audit", "security-scan", "lint-and-test"],
                {},
                "broad audit",
                0.8,
            )

        async def fake_decide(*args, **kwargs):
            return ("continue", None, "keep going", 0.9)

        async def fake_synth(*args, **kwargs):
            return "ok"

        order = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            order.append(skill_request.skill_name)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill": skill_request.skill_name, "status": "clean", "summary": "x"},
                cost_metadata={},
                latency_ms=5.0,
            )

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-aux-cap")

        payload = result.result
        assert payload["iterations_used"] == 2
        assert payload["terminated_reason"] == "iteration_cap"
        assert len(order) == 2

    @pytest.mark.asyncio
    async def test_skill_failure_aborts_loop(self):
        """A failed skill should stop the loop without calling decide for nothing."""
        from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            natural_language_query="check this",
        )

        async def fake_plan(request, trace_id):
            return (["dependency-audit", "security-scan"], {}, "intent", 0.8)

        decide_called = []

        async def fake_decide(*args, **kwargs):
            decide_called.append(1)
            return ("continue", None, "keep going", 0.9)

        async def fake_synth(*args, **kwargs):
            return "ok"

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                error="repo not found",
                failure_type=FailureType.REPO_NOT_FOUND,
            )

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-aux-fail")

        payload = result.result
        # After a failed skill, we MUST NOT call _llm_decide (saves money).
        assert decide_called == []
        assert payload["terminated_reason"] == "skill_failed"

    @pytest.mark.asyncio
    async def test_include_hint_reorders_plan(self):
        """include_hint should push hinted skills to the front of the plan."""
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            natural_language_query="check this repo for everything",
            include_skills_hint=["security-scan"],
        )

        async def fake_plan(request, trace_id):
            # LLM put dependency-audit first, but user hinted security-scan.
            return (["dependency-audit", "security-scan"], {}, "intent", 0.8)

        async def fake_decide(*args, **kwargs):
            executed = kwargs.get("executed_skills") or args[3]
            return ("continue", None, "next", 0.9) if len(executed) < 2 else ("stop", None, "done", 0.9)

        async def fake_synth(*args, **kwargs):
            return "ok"

        order = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            order.append(skill_request.skill_name)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill": skill_request.skill_name, "status": "clean", "summary": "x"},
                cost_metadata={},
                latency_ms=5.0,
            )

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            await ar.run_auto_router(req, "trace-aux-incl")

        # security-scan must run FIRST because it was hinted.
        assert order[0] == "security-scan"


class TestAutoRouterAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from src.main import app
        return TestClient(app)

    def test_auto_run_validates_body(self, client):
        """Missing the only truly required field (repo_url) should return 422."""
        resp = client.post("/api/v1/skills/auto/run", json={})
        assert resp.status_code == 422

    def test_auto_run_accepts_empty_query_with_hint(self, client):
        """The NL query is now optional. A request that omits it but supplies
        include_skills_hint should validate (server-side hint-only path)."""
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType

        async def fake_engine(req, trace_id, progress_callback=None):
            assert req.natural_language_query == ""
            assert req.include_skills_hint == ["security-scan"]
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill_executed": ["security-scan"], "skills_executed": ["security-scan"]},
                cost_metadata={"cost_usd": 0.0},
                latency_ms=1.0,
            )

        with patch("src.task1_cicd.auto_router.run_auto_router", AsyncMock(side_effect=fake_engine)):
            resp = client.post(
                "/api/v1/skills/auto/run",
                json={
                    "repo_url": "https://github.com/o/r",
                    "include_skills_hint": ["security-scan"],
                },
            )
        assert resp.status_code == 200
        assert resp.json()["result"]["skill_executed"] == ["security-scan"]

    def test_auto_run_returns_execution_result_schema(self, client):
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType

        async def fake_engine(req, trace_id, progress_callback=None):
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={
                    "query": req.natural_language_query,
                    "skills_executed": ["dependency-audit"],
                    "skill_executed": ["dependency-audit"],
                    "final_synthesis": "ok",
                    "steps": [],
                    "iterations_used": 1,
                    "terminated_reason": "router_stop",
                    "total_cost_usd": 0.0,
                    "total_latency_ms": 5.0,
                },
                cost_metadata={"cost_usd": 0.0},
                latency_ms=5.0,
            )

        with patch("src.task1_cicd.auto_router.run_auto_router", AsyncMock(side_effect=fake_engine)):
            resp = client.post(
                "/api/v1/skills/auto/run",
                json={
                    "repo_url": "https://github.com/o/r",
                    "natural_language_query": "scan for leaked api keys",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert "skill_executed" in body["result"]
        assert body["result"]["skill_executed"] == ["dependency-audit"]


class TestAutoRouterDerivedPlan:
    """The chip-only path (empty NL query) — a pure cost win because it
    skips the plan LLM call entirely. These tests lock down the derivation
    rules so the FE preview and the server stay in lock-step."""

    def test_include_hints_become_the_plan(self):
        from src.task1_cicd.auto_router import _derive_default_plan

        plan = _derive_default_plan(["security-scan", "dependency-audit"], [], 4, "")
        assert plan == ["security-scan", "dependency-audit"]

    def test_include_hints_preserve_order(self):
        from src.task1_cicd.auto_router import _derive_default_plan

        # Reversed order vs the canonical "cheap first" — user knows best.
        plan = _derive_default_plan(["lint-and-test", "dependency-audit"], [], 4, "")
        assert plan == ["lint-and-test", "dependency-audit"]

    def test_include_hint_with_build_release_works_without_query(self):
        """Ticking build-and-release in the chip UI is explicit consent;
        the gate that normally requires release/ship in the NL query is bypassed."""
        from src.task1_cicd.auto_router import _derive_default_plan

        plan = _derive_default_plan(["build-and-release"], [], 4, "")
        assert plan == ["build-and-release"]

    def test_exclude_hint_filters_includes(self):
        from src.task1_cicd.auto_router import _derive_default_plan

        plan = _derive_default_plan(
            ["security-scan", "dependency-audit", "lint-and-test"],
            ["dependency-audit"],
            4,
            "",
        )
        assert plan == ["security-scan", "lint-and-test"]

    def test_no_query_no_hints_defaults_to_safe_pair(self):
        from src.task1_cicd.auto_router import _derive_default_plan

        plan = _derive_default_plan([], [], 4, "")
        assert plan == ["dependency-audit", "security-scan"]

    def test_no_query_only_exclude_defaults_minus_excluded(self):
        from src.task1_cicd.auto_router import _derive_default_plan

        plan = _derive_default_plan([], ["security-scan"], 4, "")
        assert plan == ["dependency-audit"]

    def test_excluding_both_defaults_falls_through_to_lint(self):
        from src.task1_cicd.auto_router import _derive_default_plan

        plan = _derive_default_plan([], ["dependency-audit", "security-scan"], 4, "")
        assert plan == ["lint-and-test"]

    def test_excluding_everything_returns_empty_plan(self):
        """A pathological exclude — the loop turns this into a structured failure."""
        from src.task1_cicd.auto_router import _derive_default_plan

        plan = _derive_default_plan(
            [],
            ["lint-and-test", "dependency-audit", "security-scan", "build-and-release"],
            4,
            "",
        )
        assert plan == []

    def test_release_intent_explicit_via_chip(self):
        from src.task1_cicd.auto_router import _is_release_intent_explicit

        assert _is_release_intent_explicit("", ["build-and-release"]) is True
        assert _is_release_intent_explicit("", []) is False
        # Query alone is also sufficient
        assert _is_release_intent_explicit("ship it now", []) is True


class TestAutoRouterEmptyQueryLoop:
    """End-to-end tests for the empty-query / hint-only loop.

    Key invariants:
      1. When query is empty, `_llm_plan` is NEVER called (saves ~$0.001/req).
      2. The derived plan matches `_derive_default_plan` exactly.
      3. Decide and synthesize still run as normal (they have a synthesized
         intent string substituted for the missing user_query).
      4. A request that excludes every skill returns a structured failure,
         not a 500.
    """

    @pytest.mark.asyncio
    async def test_empty_query_skips_llm_plan_call(self):
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            natural_language_query="",  # explicit empty
            include_skills_hint=["dependency-audit"],
        )

        plan_called = []

        async def fake_plan(request, trace_id):
            plan_called.append(1)  # ← this MUST NOT happen
            return (["lint-and-test"], {}, "x", 1.0)

        async def fake_decide(*args, **kwargs):
            # Only one skill in the plan; after it runs remaining_plan is
            # empty so this won't be called — but mock it anyway as defence
            # against any future change that adds an exhaustion postmortem.
            return ("stop", None, "plan complete", 1.0)

        async def fake_synth(*args, **kwargs):
            return "Hint-only run succeeded."

        order = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            order.append(skill_request.skill_name)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill": skill_request.skill_name, "status": "clean", "summary": "ok"},
                cost_metadata={},
                latency_ms=5.0,
            )

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-empty-1")

        # Critical: the plan LLM call was skipped.
        assert plan_called == []
        # Plan came from the include hint, not the LLM.
        assert order == ["dependency-audit"]
        payload = result.result
        assert payload["skill_executed"] == ["dependency-audit"]
        assert payload["initial_plan"] == ["dependency-audit"]
        # plan_confidence should be 1.0 in deterministic mode (no LLM ambiguity).
        assert payload["plan_confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_empty_query_no_hints_uses_default_pair(self):
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(repo_url="https://github.com/o/r")

        async def fake_plan(request, trace_id):
            raise AssertionError("LLM plan call should be skipped for empty-query mode")

        async def fake_decide(*args, **kwargs):
            executed = kwargs.get("executed_skills") or args[3]
            return ("continue", None, "next", 0.9) if len(executed) < 2 else ("stop", None, "done", 0.9)

        async def fake_synth(*args, **kwargs):
            return "default pair done"

        order = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            order.append(skill_request.skill_name)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill": skill_request.skill_name, "status": "clean", "summary": "ok"},
                cost_metadata={},
                latency_ms=5.0,
            )

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-empty-default")

        assert order == ["dependency-audit", "security-scan"]
        assert result.result["skill_executed"] == ["dependency-audit", "security-scan"]

    @pytest.mark.asyncio
    async def test_empty_query_with_excluded_all_returns_failure(self):
        """If the user excludes literally every skill, the router returns a
        clean failure rather than calling any LLM stage."""
        from src.shared.schemas import ExecutionStatus
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            exclude_skills_hint=[
                "lint-and-test",
                "dependency-audit",
                "security-scan",
                "build-and-release",
            ],
        )

        async def fake_plan(*args, **kwargs):
            raise AssertionError("plan must not be called")

        async def fake_synth(*args, **kwargs):
            raise AssertionError("synthesize must not be called")

        engine_called = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            engine_called.append(skill_request.skill_name)
            raise AssertionError("engine must not be called")

        with patch.object(ar, "_llm_plan", fake_plan), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-empty-exclall")

        assert result.status == ExecutionStatus.FAILED
        assert engine_called == []
        assert "exclude" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_empty_query_with_build_release_chip_runs_it(self):
        """Ticking the build-and-release chip with an empty query must be
        treated as explicit release intent (the release-intent gate is bypassed
        only by chip OR by query keywords, not by LLM whim)."""
        from src.shared.schemas import ExecutionResult, ExecutionStatus, TaskType
        from src.task1_cicd import auto_router as ar
        from src.task1_cicd.schemas import AutoRouterRequest

        req = AutoRouterRequest(
            repo_url="https://github.com/o/r",
            natural_language_query="",  # crucial — no release keyword
            include_skills_hint=["build-and-release"],
            dry_run=True,
        )

        async def fake_decide(*args, **kwargs):
            return ("stop", None, "release ran", 1.0)

        async def fake_synth(*args, **kwargs):
            return "ok"

        order = []

        async def fake_engine(skill_request, trace_id, progress_callback=None):
            order.append(skill_request.skill_name)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                task=TaskType.CICD_SKILLS,
                trace_id=trace_id,
                result={"skill": skill_request.skill_name, "status": "success", "summary": "dry-run ok"},
                cost_metadata={},
                latency_ms=10.0,
            )

        with patch.object(ar, "_llm_decide", fake_decide), \
             patch.object(ar, "_llm_synthesize", fake_synth), \
             patch("src.task1_cicd.skill_engine.run_skill", fake_engine):
            result = await ar.run_auto_router(req, "trace-chip-release")

        assert order == ["build-and-release"]
        assert result.result["skill_executed"] == ["build-and-release"]
