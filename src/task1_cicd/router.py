"""
Task 1 Router: CI/CD Skills Engine API.

Endpoints for running GitHub CI/CD skills against repositories.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.shared.logger import get_logger
from src.shared.schemas import ExecutionResult, ExecutionStatus, ModelSelectionRequest, TaskType

router = APIRouter()
logger = get_logger("task1_router")


class SkillRunRequest(BaseModel):
    """Request to run a CI/CD skill against a repository."""

    repo_url: str = Field(..., description="GitHub repository URL")
    branch: str = Field(default="main", description="Branch to analyze")
    skill_name: str = Field(
        ..., description="Skill to run: lint-and-test, build-and-release, dependency-audit, security-scan"
    )
    dry_run: bool = Field(default=True, description="Run in preview mode (no side effects)")
    model: ModelSelectionRequest = Field(default_factory=ModelSelectionRequest)


class SkillListResponse(BaseModel):
    """Available skills listing."""

    skills: list[dict]


@router.get("/list", response_model=SkillListResponse)
async def list_skills():
    """List all available CI/CD skills with their descriptions."""
    skills = [
        {
            "name": "lint-and-test",
            "description": "Run linting and test suites on a GitHub repository",
            "trigger_phrases": ["test this", "run tests", "check code quality", "lint"],
            "scope": "read-only",
        },
        {
            "name": "build-and-release",
            "description": "Build artifacts and manage GitHub releases",
            "trigger_phrases": ["release", "ship it", "deploy", "publish"],
            "scope": "gated-write",
        },
        {
            "name": "dependency-audit",
            "description": "Audit dependencies for vulnerabilities and outdated packages",
            "trigger_phrases": ["audit deps", "check vulnerabilities", "update packages"],
            "scope": "read-only",
        },
        {
            "name": "security-scan",
            "description": "Scan for hardcoded secrets and security vulnerabilities",
            "trigger_phrases": ["scan for secrets", "SAST", "check CVEs"],
            "scope": "read-only",
        },
    ]
    return SkillListResponse(skills=skills)


@router.post("/run", response_model=ExecutionResult)
async def run_skill(request: SkillRunRequest):
    """
    Execute a CI/CD skill against a GitHub repository.

    All skills run in dry-run mode by default. Write operations
    (build-and-release) require explicit dry_run=false.
    """
    from src.shared.logger import generate_trace_id

    trace_id = generate_trace_id()
    logger.info(
        "skill_run_requested",
        skill=request.skill_name,
        repo=request.repo_url,
        branch=request.branch,
        dry_run=request.dry_run,
        trace_id=trace_id,
    )

    valid_skills = {"lint-and-test", "build-and-release", "dependency-audit", "security-scan"}
    if request.skill_name not in valid_skills:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown skill: {request.skill_name}. Valid: {sorted(valid_skills)}",
        )

    # Skill engine implementation will be connected here
    # For now, return a structured placeholder showing the architecture works
    return ExecutionResult(
        status=ExecutionStatus.SUCCESS,
        task=TaskType.CICD_SKILLS,
        trace_id=trace_id,
        result={
            "skill": request.skill_name,
            "repo_url": request.repo_url,
            "branch": request.branch,
            "dry_run": request.dry_run,
            "message": f"Skill '{request.skill_name}' executed successfully (skeleton mode)",
        },
    )
