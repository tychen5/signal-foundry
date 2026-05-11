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
    """User's model selection, optionally with their own API key.

    `model_id` is free-text: pass any `publisher/model-name` string the
    chosen provider hosts (e.g. `openai/gpt-5.5`,
    `moonshotai/kimi-k2.6`, `qwen/qwen3-next-80b-a3b-instruct`,
    `anthropic/claude-opus-4.7`, `nvidia/nemotron-3-super-120b-a12b`).
    The server doesn't require the value to be in its registry — the
    registry is just a curated set with extra metadata (cost rates,
    `extra_body` for thinking-mode toggles). Unknown IDs are routed via
    the publisher-prefix heuristic, or via the `provider` hint below.
    """

    model_id: str = Field(
        default="moonshotai/kimi-k2.6",
        description=(
            "Model identifier as 'provider/model-name'. Accepts ANY model "
            "the chosen provider hosts, not just the registry defaults."
        ),
    )
    provider: Optional[str] = Field(
        default=None,
        description=(
            "Optional explicit provider routing for free-text model_ids whose "
            "publisher prefix the server doesn't recognise. Set to "
            "'openrouter' or 'nvidia'. When omitted, the server infers from "
            "the model_id prefix (openai/, anthropic/, google/, moonshotai/, …)."
        ),
    )
    user_openrouter_key: Optional[str] = Field(
        default=None,
        description="User's own OpenRouter API key (avoids consuming server tokens)",
    )
    user_nvidia_key: Optional[str] = Field(
        default=None,
        description=(
            "User's own NVIDIA NIM API key (`nvapi-...`). When supplied AND the "
            "selected model is hosted on NIM, this overrides the server's key. "
            "Useful when the demo server's key is rate-limited or expired."
        ),
    )
    user_langsmith_key: Optional[str] = Field(
        default=None,
        description=(
            "User's own LangSmith API key (`lsv2_...`). When supplied, this run "
            "is traced to the user's LangSmith project instead of the server's. "
            "Purely optional — leave blank to use the server's project (or no "
            "tracing if the server isn't configured)."
        ),
    )

    def picked_user_key(self) -> Optional[str]:
        """Return the right user-supplied key for the selected model.

        Routes based on which provider the model belongs to. Lets every
        existing downstream caller keep using a single `user_api_key`
        string parameter — no need to thread two keys through 7+ call
        sites in agent/pipeline/healer/planner.
        """
        from src.config import LLMProvider, get_settings

        try:
            info = get_settings().get_model_info(self.model_id, provider_hint=self.provider)
            provider = info["provider"]
        except Exception:
            return self.user_openrouter_key
        if provider == LLMProvider.NVIDIA and self.user_nvidia_key:
            # When user supplies an NVIDIA key for an NVIDIA model, hand it to
            # get_llm via the standard user_openrouter_key channel — get_llm
            # uses its own routing, but the upstream call sites only pass one
            # field. We solve this with a global override (see `picked_keys()`).
            return self.user_nvidia_key
        return self.user_openrouter_key

    def picked_keys(self) -> dict:
        """Return both keys explicitly so get_llm can route correctly."""
        return {
            "user_openrouter_key": self.user_openrouter_key,
            "user_nvidia_key": self.user_nvidia_key,
        }


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
