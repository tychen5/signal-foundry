"""
Task 1 Router: CI/CD Skills Engine API.

Endpoints for running GitHub CI/CD skills against repositories.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.shared.logger import generate_trace_id, get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, FailureType, TaskType
from src.task1_cicd.schemas import SkillListResponse, SkillRunRequest

router = APIRouter()
logger = get_logger("task1_router")

_SKILL_CATALOG = [
    {
        "name": "lint-and-test",
        "description": "Run linting and test suites on a GitHub repository",
        "trigger_phrases": ["test this", "run tests", "check code quality", "lint", "run ci"],
        "scope": "read-only",
        "languages": ["python", "javascript"],
    },
    {
        "name": "build-and-release",
        "description": "Analyze git history, determine next version, and optionally create a GitHub release",
        "trigger_phrases": ["release", "ship it", "deploy", "publish", "new version"],
        "scope": "gated-write",
        "dry_run_default": True,
    },
    {
        "name": "dependency-audit",
        "description": "Audit dependencies for CVEs and outdated packages via OSV.dev",
        "trigger_phrases": ["audit deps", "check vulnerabilities", "CVE check", "outdated packages"],
        "scope": "read-only",
        "data_sources": ["OSV.dev", "PyPI", "npm"],
    },
    {
        "name": "security-scan",
        "description": "Scan source code for hardcoded secrets and SAST vulnerabilities",
        "trigger_phrases": ["scan for secrets", "SAST", "find leaked keys", "security audit"],
        "scope": "read-only",
        "tools": ["regex-secret-detection", "bandit (Python SAST)"],
    },
]


@router.get("/list", response_model=SkillListResponse)
async def list_skills():
    """List all available CI/CD skills with their descriptions and trigger phrases."""
    return SkillListResponse(skills=_SKILL_CATALOG)


@router.post("/run", response_model=ExecutionResult)
async def run_skill(request: SkillRunRequest):
    """
    Execute a CI/CD skill against a GitHub repository.

    Skills run in dry-run mode by default. The build-and-release skill
    requires dry_run=false to actually create a GitHub release.
    """
    from src.task1_cicd.github_client import FastFailError
    from src.task1_cicd.skill_engine import run_skill as engine_run_skill

    trace_id = generate_trace_id()
    logger.info(
        "skill_run_requested",
        skill=request.skill_name,
        repo=request.repo_url,
        branch=request.branch,
        dry_run=request.dry_run,
        trace_id=trace_id,
    )

    try:
        result = await engine_run_skill(request, trace_id)
        # Skill-name mismatch is a client error — surface as 400 for clear HTTP semantics
        if result.status == ExecutionStatus.FAILED and result.failure_type == FailureType.SKILL_MISMATCH:
            raise HTTPException(status_code=400, detail=result.error or "Unknown skill")
        from src.shared.tracing import trace_url
        result.langsmith_trace_url = trace_url(trace_id)
        return result
    except HTTPException:
        raise
    except FastFailError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("skill_run_unhandled_error", error=str(e), trace_id=trace_id)
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            task=TaskType.CICD_SKILLS,
            trace_id=trace_id,
            error=f"Internal error: {e}",
        )
