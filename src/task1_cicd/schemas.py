"""
Task 1 Pydantic Schemas: CI/CD Skills Engine.

All typed data flowing through the skill execution pipeline.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from src.shared.schemas import ModelSelectionRequest


class SkillRunRequest(BaseModel):
    """Request to run a CI/CD skill against a repository."""

    repo_url: str = Field(..., description="GitHub repository URL")
    branch: str = Field(default="main", description="Branch to analyze")
    skill_name: str = Field(
        ...,
        description="Skill to run: lint-and-test, build-and-release, dependency-audit, security-scan",
    )
    dry_run: bool = Field(default=True, description="Run in preview mode (no side effects)")
    model: ModelSelectionRequest = Field(default_factory=ModelSelectionRequest)


class RepoContext(BaseModel):
    """Resolved repository info after validation and shallow clone."""

    owner: str
    repo: str
    branch: str
    commit_sha: str
    clone_path: str
    language: str = "unknown"  # "python" | "javascript" | "unknown"
    has_pyproject: bool = False
    has_requirements_txt: bool = False
    has_package_json: bool = False
    has_package_lock: bool = False
    has_makefile: bool = False


class SandboxConfig(BaseModel):
    """Configuration for the subprocess sandbox runner."""

    timeout_seconds: int = 300
    max_output_bytes: int = 1_000_000  # 1MB cap on combined stdout+stderr
    working_dir: Optional[str] = None


class SandboxResult(BaseModel):
    """Output from a sandboxed subprocess execution."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: float = 0.0


# --- Per-skill result types ---


class LintIssue(BaseModel):
    file: str
    line: int
    col: int = 0
    code: str = ""
    message: str
    severity: str = "error"


class TestFailure(BaseModel):
    test_id: str
    message: str
    file: str = ""


class LintAndTestResult(BaseModel):
    """Result from the lint-and-test skill."""

    status: str  # "success" | "partial" | "failed"
    language: str
    lint_tool: str
    lint_passed: bool
    lint_issues: list[LintIssue] = Field(default_factory=list)
    lint_issue_count: int = 0
    test_tool: str = ""
    test_passed: bool = False
    test_total: int = 0
    test_passed_count: int = 0
    test_failed_count: int = 0
    test_skipped_count: int = 0
    test_failures: list[TestFailure] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    notes: str = ""


class PackagePin(BaseModel):
    """A pinned package dependency."""

    name: str
    version: Optional[str] = None
    ecosystem: str = "PyPI"  # "PyPI" | "npm"


class VulnerabilityEntry(BaseModel):
    """A security vulnerability finding from OSV.dev."""

    package: str
    version: str
    cve_id: str = ""
    osv_id: str = ""
    severity: str = "unknown"  # "critical" | "high" | "medium" | "low" | "unknown"
    summary: str = ""
    fixed_version: Optional[str] = None
    reference_url: str = ""


class OutdatedEntry(BaseModel):
    """An outdated package."""

    package: str
    current_version: str
    latest_version: str
    is_major_bump: bool = False


class DependencyAuditResult(BaseModel):
    """Result from the dependency-audit skill."""

    status: str  # "clean" | "warnings" | "vulnerabilities_found"
    total_dependencies: int = 0
    ecosystems_checked: list[str] = Field(default_factory=list)
    vulnerabilities: list[VulnerabilityEntry] = Field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    outdated: list[OutdatedEntry] = Field(default_factory=list)
    notes: str = ""


class SecurityFinding(BaseModel):
    """A single security finding."""

    finding_type: str  # "secret" | "sast" | "config"
    severity: str  # "critical" | "high" | "medium" | "low"
    file: str
    line: int = 0
    match_preview: str = ""  # redacted snippet, never full secret
    description: str = ""
    recommendation: str = ""
    tool: str = ""  # "regex" | "bandit"


class SecurityScanResult(BaseModel):
    """Result from the security-scan skill."""

    status: str  # "clean" | "findings"
    scan_types: list[str] = Field(default_factory=list)
    findings: list[SecurityFinding] = Field(default_factory=list)
    # Severity counts. Renamed from `summary` to avoid colliding with the
    # engine's LLM-generated `summary` string when the result dict is merged.
    severity_counts: dict[str, int] = Field(default_factory=dict)
    files_scanned: int = 0
    notes: str = ""


class BuildAndReleaseResult(BaseModel):
    """Result from the build-and-release skill."""

    mode: str  # "dry_run" | "execute"
    status: str  # "success" | "skipped" | "failed"
    current_version: Optional[str] = None
    next_version: str = ""
    version_bump: str = ""  # "major" | "minor" | "patch"
    changelog: str = ""
    commits_since_tag: int = 0
    release_url: Optional[str] = None  # None in dry_run
    tag_created: bool = False
    notes: str = ""


class SkillListResponse(BaseModel):
    """Available skills listing."""

    skills: list[dict[str, Any]]


# --- Auto-Router (LLM-driven skill orchestration) ---


class AutoRouterRequest(BaseModel):
    """Natural-language CI/CD request — router LLM picks which skills to run."""

    repo_url: str = Field(..., description="GitHub repository URL")
    branch: str = Field(default="main", description="Branch to analyze")
    natural_language_query: str = Field(
        default="",
        description=(
            "Optional free-form description of what the user wants checked. "
            "Examples: 'check if there are any leaked secrets', "
            "'audit my deps for CVEs', 'is this safe to ship?'. "
            "When empty, the router falls back to running include_skills_hint "
            "(if any) or the default health-check pair (dependency-audit + "
            "security-scan), so the user can run the engine purely by ticking "
            "skill chips."
        ),
    )
    include_skills_hint: list[str] = Field(
        default_factory=list,
        description="Skill names the user suggests routing through (soft hint).",
    )
    exclude_skills_hint: list[str] = Field(
        default_factory=list,
        description="Skill names the user explicitly does NOT want run (hard block).",
    )
    dry_run: bool = Field(
        default=True,
        description="If build-and-release is selected, run in preview mode (no GitHub release created).",
    )
    max_iterations: int = Field(
        default=4,
        ge=1,
        le=6,
        description="Hard cap on router decision iterations (defends against runaway loops).",
    )
    max_skills: int = Field(
        default=4,
        ge=1,
        le=4,
        description="Maximum number of distinct skills the router may run (≤4 = total catalog).",
    )
    budget_cap_usd: Optional[float] = Field(
        default=None,
        description=(
            "Optional per-request LLM budget cap in USD. Leave None to use the "
            "task default ($0.30 for task1_cicd)."
        ),
    )
    model: ModelSelectionRequest = Field(default_factory=ModelSelectionRequest)


class AutoRouterStep(BaseModel):
    """One iteration of the router loop = one skill execution + the router's reflection on it."""

    iteration: int
    skill_executed: str
    rationale: str = ""  # why this skill was picked at this iteration
    decision_after: str = ""  # "continue" | "add_skill" | "stop" | "" (terminal)
    decision_reasoning: str = ""
    decision_confidence: float = 0.0
    status: str = ""  # the skill result status (clean/findings/passed/etc.)
    summary: str = ""  # the per-skill result summary (LLM-generated)
    cache_hit: bool = False
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    raw_result: Optional[dict[str, Any]] = None  # full skill result, for the FE timeline


class AutoRouterResult(BaseModel):
    """Final structured payload returned by the auto-router."""

    query: str
    overall_intent: str = ""
    initial_plan: list[str] = Field(default_factory=list)
    plan_confidence: float = 0.0
    skills_executed: list[str] = Field(default_factory=list)
    steps: list[AutoRouterStep] = Field(default_factory=list)
    final_synthesis: str = ""
    iterations_used: int = 0
    terminated_reason: str = ""  # "router_stop" | "iteration_cap" | "budget_cap" | "plan_exhausted" | "error"
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    repo_url: str = ""
    branch: str = ""
    commit_sha: str = ""
    dry_run: bool = True
