"""
Shared Pydantic Schemas for Signal-Foundry.

Common data models used across all three tasks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """The three task domains."""

    CICD_SKILLS = "task1_cicd"
    BROWSER_AGENT = "task2_browser"
    SEC_EXTRACTION = "task3_sec"


class ExecutionStatus(str, Enum):
    """Status of an execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"


class FailureType(str, Enum):
    """Taxonomy of failure modes across tasks."""

    # General
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH_ERROR = "auth_error"
    INVALID_INPUT = "invalid_input"
    LLM_ERROR = "llm_error"

    # Task 1 - CI/CD
    REPO_NOT_FOUND = "repo_not_found"
    SKILL_MISMATCH = "skill_mismatch"
    SANDBOX_ERROR = "sandbox_error"

    # Task 2 - Browser
    SELECTOR_MISMATCH = "selector_mismatch"
    PAGE_LOAD_ERROR = "page_load_error"
    LOGIC_ERROR = "logic_error"
    CAPTCHA = "captcha"
    SILENT_FAILURE = "silent_failure"
    TOOL_ERROR = "tool_error"

    # Task 3 - SEC
    PARSING_ERROR = "parsing_error"
    HALLUCINATION = "hallucination"
    MISSING_SECTION = "missing_section"
    FORMAT_UNSUPPORTED = "format_unsupported"


# --- Request/Response Models ---


class ModelSelectionRequest(BaseModel):
    """User's model selection, optionally with their own API key."""

    model_id: str = Field(
        default="moonshotai/kimi-k2.6",
        description="Model identifier from the registry",
    )
    user_openrouter_key: Optional[str] = Field(
        default=None,
        description="User's own OpenRouter API key (avoids consuming server tokens)",
    )


class ExecutionResult(BaseModel):
    """Standard result envelope for all task executions."""

    status: ExecutionStatus
    task: TaskType
    trace_id: str
    result: Any = None
    error: Optional[str] = None
    failure_type: Optional[FailureType] = None
    cost_metadata: Optional[dict] = None
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # When LangSmith is configured, this URL deep-links to the trace tree
    # in the LangSmith UI (filtered by our internal trace_id metadata).
    # None when LangSmith env vars are absent.
    langsmith_trace_url: Optional[str] = None


class EvalCase(BaseModel):
    """A single evaluation test case."""

    case_id: str
    task: TaskType
    input_data: dict
    expected_behavior: str
    difficulty: str = "normal"  # easy, normal, hard, edge_case
    tags: list[str] = Field(default_factory=list)


class EvalResult(BaseModel):
    """Result of running a single eval case."""

    case_id: str
    passed: bool
    actual_output: Any = None
    confidence_score: float = 0.0
    failure_type: Optional[FailureType] = None
    retry_count: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    notes: str = ""


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "0.1.0"
    environment: str = "development"
    tasks: dict[str, str] = Field(
        default_factory=lambda: {
            "task1_cicd": "ready",
            "task2_browser": "ready",
            "task3_sec": "ready",
        }
    )
